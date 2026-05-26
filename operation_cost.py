
'Base Object'
from trytond.model import (sequence_ordered, 
    DeactivableMixin, Index, ModelSQL, ModelView, Workflow, fields, Unique, Check,
    sum_tree, tree)
from trytond.model.exceptions import ValidationError
from trytond.i18n import gettext
from trytond.cache import Cache
from trytond.report import Report
from trytond.pool import Pool
from trytond.transaction import Transaction
from trytond.pyson import Bool, Eval, If, PYSONEncoder, TimeDelta, Equal
from trytond.pool import PoolMeta
from trytond.i18n import lazy_gettext
from trytond.modules.company import CompanyReport
from trytond.modules.product import price_digits
from trytond.modules.currency.fields import Monetary
from trytond.exceptions import UserWarning

from dateutil.relativedelta import relativedelta

from sql import Column
import re
import datetime
from decimal import Decimal, ROUND_HALF_UP
from . import base_object

import logging

logger = logging.getLogger(__name__)
class InvalidCalculationMethod(ValidationError):
    pass

#**********************************************************************
class CostCategoryGroup(DeactivableMixin, sequence_ordered(), ModelSQL, ModelView):
    "Cost Category Group, grouping of cost types for reporting and analysis purposes, e.g. heating, water, etc."
    __name__ = 'real_estate.cost_category_group'

    name = fields.Char("Name", required=True, translate=True)

#**********************************************************************
class CostType(DeactivableMixin, sequence_ordered(), ModelSQL, ModelView):
    """Cost Type, e.g. heating, water, common electricity, etc."""
    __name__ = 'real_estate.cost_type'

    name = fields.Char("Name", required=True, translate=True)
    comment = fields.Text("Comment")
    no_print = fields.Boolean("No Print")
    category_group = fields.Many2One(
        'real_estate.cost_category_group', "Category Group",
        ondelete='SET NULL')

#**********************************************************************
class BillingUnit(Workflow,DeactivableMixin, sequence_ordered(), ModelSQL, ModelView):
    """Billing Unit, e.g. operating cost settlement for a year, WEG annual statement, etc."""
    __name__ = 'real_estate.billing_unit'
    __rec_name__ = 'name'

    company = fields.Function(fields.Many2One('company.company','Company'),
        'on_change_with_company')
    
    property = fields.Many2One('real_estate.base_object',
        "Property", required=True, path='path', ondelete='CASCADE',
        states={
            'readonly': Eval('state') != 'draft',
            },
        domain=[
            ('type', '=', 'property' ),],)

    collective_billing = fields.Function(fields.Boolean('Collective Billing'),
        'on_change_with_collective_billing')

    start_date = fields.Date('Start Date', 
        states={
            'readonly': ((Eval('state') != 'draft')),
            },
        required=True,
        domain=[If(Bool(Eval('end_date')), ('start_date', '<=', Eval('end_date', None)),())],
        )
      
    end_date = fields.Function(fields.Date('End Date'),'on_change_with_end_date')

    calculation_method = fields.Selection([
        ('rental_apartment', 'Rental Apartment'),
        ('WEG_billing', 'WEG Billing'),
        ], "Calculation Method", sort=False,
        states={ 'readonly': Eval('state') != 'draft', },
        help=(
            "Rental Apartment: Operating cost settlement for residential tenancies under §§ 1–2 BetrKV. "
            "Cost shares are allocated to tenants based on floor area, consumption, or number of occupants. "
            "Advance payments made by tenants are offset; the result is a credit or additional charge per tenant.\n"
            "WEG Billing: Annual statement for condominium owner associations under § 28 WEG. "
            "Total costs are distributed among owners according to their co-ownership shares (MEA). "
            "Paid maintenance fees are offset; reserve fund contributions and non-allocable costs "
            "remain with the individual owner."
        ),
        )

    billing_type = fields.Selection([
        ('planned_billing', 'Planned Billing'),
        ('actual_billing', 'Actual Billing'),
        ], "Billing Type", sort=False,
        states={ 'readonly': Eval('state') != 'draft', },
        help=(
            "Planned Billing: Settlement based on all invoice lines that have not been cancelled, "
            "including amounts that are still open (unpaid). "
            "Suitable for operating cost settlements where all costs incurred in a period are to be "
            "taken into account regardless of payment receipt.\n"
            "Actual Billing: Only invoice lines that have actually been paid (status 'paid') are included. "
            "Suitable for WEG annual statements or cash-based accounting where only "
            "payments actually received form the basis for settlement."
        ),
        )

    planned_costs = fields.Function(Monetary('Planned Costs', currency='currency', digits= 'currency',#(16, 2),
        ),'on_change_with_planned_costs',
        )

    currency = fields.Function(fields.Many2One('currency.currency', 'Currency',), 'on_change_with_currency') 

    description = fields.Char('Description', required=True)

    name = fields.Function(fields.Char("Name"), 'on_change_with_name', 
                searcher='name_search')  
    
    state = fields.Selection([
            ('draft', 'Draft'),
            ('approved', 'Approved'),
            ('selection', 'Selection'),
            ('value_share', 'Value Share'),
            ('billed', 'Billed'),
            ], "State", sort=False,
            #states={ 'readonly': True, },
            )

    sub_state = fields.Function(fields.Selection('get_sub_states', "Sub State"), 'on_change_with_sub_state')      

    term_types_of_use = fields.MultiSelection(
            'get_term_types_of_use', "Term Types",
            help="The term type which can use this billing unit.")


    settlement_units = fields.One2Many('real_estate.settlement_unit', 'billing_unit', 'Settlement Units',
            #states=_states_only_propperty
            states={ 'readonly': Eval('state') != 'draft', },
            )    


    invoice_lines = fields.Function(fields.One2Many('account.invoice.line', None, 'Invoice Lines',),
        'on_change_with_invoice_lines')
    
    cost_shares = fields.Function(fields.One2Many('real_estate.cost_share', None, 'Cost Shares'),
        'on_change_with_cost_shares')

    cash_flow_lines = fields.Function(fields.One2Many('real_estate.contract.term.cash_flow', None, 'Cash Flow Lines'),
        'on_change_with_cash_flow_lines')
    
    settlment_results = fields.One2Many('real_estate.settlement_result', 'billing_unit', 'Settlement Results')

    sum_planned_costs = fields.Function(
        Monetary('Sum Planned Costs', currency='currency', digits='currency'),
        'on_change_with_sum_planned_costs')

    sum_actual_costs = fields.Function(
        Monetary('Sum Actual Costs', currency='currency', digits='currency'),
        'on_change_with_sum_actual_costs')

    sum_actual_cost_by_owner = fields.Function(
        Monetary('Sum Actual Cost by Owner', currency='currency', digits='currency'),
        'on_change_with_sum_actual_cost_by_owner')

    sum_actual_cost_by_allocation = fields.Function(
        Monetary('Sum Actual Cost by Allocation', currency='currency', digits='currency'),
        'on_change_with_sum_actual_cost_by_allocation')

    sum_advanced_payment = fields.Function(
        Monetary('Sum Advanced Payment', currency='currency', digits='currency'),
        'on_change_with_sum_advanced_payment')

    sum_refund_receivable = fields.Function(
        Monetary('Sum Refund/Receivable', currency='currency', digits='currency'),
        'on_change_with_sum_refund_receivable')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._transitions |= set((
            ('draft', 'approved'),
            ('approved', 'selection'),
            ('selection', 'value_share'),
            ('value_share', 'billed'),
            ))

        cls._buttons.update({
                'approved': {
                    'invisible': ~Eval('state').in_(['draft']),
                    'depends': ['state'],
                    },
                'selection': {
                    'invisible': ~Eval('state').in_(['approved', 'selection']),
                    'depends': ['state'],
                    },
                'compute_value_shares_button': {
                    'invisible': ~Eval('state').in_(['selection', 'value_share']),
                    'depends': ['state'],
                    },
                'billing': {
                    'invisible': ~Eval('state').in_(['value_share']) | Bool(Eval('collective_billing')),
                    'depends': ['state', 'collective_billing'],
                    },
                'compute_settlement_result': {
                    'invisible': ~Eval('state').in_(['value_share']),
                    'depends': ['state'],
                    },
                })

    @classmethod
    @ModelView.button
    @Workflow.transition('approved')
    def approved(cls, billing_units):
        for billing_unit in billing_units:
            if not billing_unit.settlement_units:
                raise ValidationError(gettext(
                    "real_estate.msg_settlement_units_error").format(
                    billing_unit.name))
            if not billing_unit.term_types_of_use:
                raise ValidationError(gettext(
                    "real_estate.msg_term_types_of_use").format(
                    billing_unit.name))
            billing_unit.add_log('state_change',
                'billing unit state changed to approved')
            billing_unit.state = 'approved'
            billing_unit.save()

    @classmethod
    @ModelView.button
    def selection(cls, billing_units):
        SettlementUnit = Pool().get('real_estate.settlement_unit')
        for billing_unit in billing_units:
            for su in billing_unit.settlement_units:
                su.selection()
            sus = SettlementUnit.browse(
                [su.id for su in billing_unit.settlement_units])
            all_selection = all(
                su.sub_state == 'selection' for su in sus)
            if all_selection and billing_unit.state == 'approved':
                billing_unit.add_log('state_change',
                    'billing unit state changed to selection')
                billing_unit.state = 'selection'
            billing_unit.save()

    @classmethod
    @ModelView.button
    def compute_value_shares_button(cls, billing_units):
        SettlementUnit = Pool().get('real_estate.settlement_unit')
        value_share_ids = []
        for billing_unit in billing_units:
            for su in billing_unit.settlement_units:
                su.compute_value_shares()
            sus = SettlementUnit.browse(
                [su.id for su in billing_unit.settlement_units])
            all_value_share = all(
                su.sub_state == 'value_share' for su in sus)
            if all_value_share:
                billing_unit.add_log('state_change',
                    'billing unit state changed to value_share')
                billing_unit.state = 'value_share'
                value_share_ids.append(billing_unit.id)
            billing_unit.save()
        if value_share_ids:
            refreshed = cls.browse(value_share_ids)
            cls.compute_settlement_result(refreshed)

    @classmethod
    @ModelView.button
    def billing(cls, billing_units):
        pass

    @classmethod
    @ModelView.button
    def compute_settlement_result(cls, billing_units):
        """Compute settlement result based on cost shares and cash flow lines of all settlement units. 
        For each unique combination of contract and base_object, create a settlement result record with 
        aggregated planned and actual costs, and allocated advanced payment and refund/receivable amounts."""
        pool = Pool()
        SettlementResult = pool.get('real_estate.settlement_result')
        for billing_unit in billing_units:
            if billing_unit.state != 'value_share':
                raise ValidationError(
                    f"Billing unit {billing_unit.name} is not in state 'value_share'.")
            existing = SettlementResult.search(
                [('billing_unit', '=', billing_unit.id)])
            if existing:
                SettlementResult.delete(existing)
            groups = {}
            for cs in billing_unit._get_cost_shares():
                if cs.contract:
                    key = ('contract', cs.contract.id,
                        cs.base_object.id if cs.base_object else None)
                elif cs.base_object:
                    key = ('object', cs.base_object.id)
                else:
                    key = None
                if key not in groups:
                    groups[key] = {
                        'contract': cs.contract if cs.contract else None,
                        'base_object': cs.base_object if cs.base_object else None,
                        'start_date': cs.start_date,
                        'end_date': cs.end_date,
                        'planned_costs': Decimal(0),
                        'actual_costs': Decimal(0),
                    }
                g = groups[key]
                if cs.start_date and (
                        g['start_date'] is None or cs.start_date < g['start_date']):
                    g['start_date'] = cs.start_date
                if cs.end_date and (
                        g['end_date'] is None or cs.end_date > g['end_date']):
                    g['end_date'] = cs.end_date
                g['planned_costs'] += cs.planned_costs or Decimal(0)
                g['actual_costs'] += cs.actual_costs or Decimal(0)
            advanced_by_contract = {}
            terms_by_contract = {}
            for line in (billing_unit.cash_flow_lines or []):
                if line.contract:
                    cid = line.contract.id
                    advanced_by_contract[cid] = (
                        advanced_by_contract.get(cid, Decimal(0))
                        + (line.amount or Decimal(0)))
                    if line.term:
                        terms_by_contract.setdefault(cid, set()).add(line.term.id)
            contract_actual_totals = {}
            contract_object_count = {}
            for key, g in groups.items():
                if key and key[0] == 'contract':
                    cid = key[1]
                    contract_actual_totals[cid] = (
                        contract_actual_totals.get(cid, Decimal(0))
                        + g['actual_costs'])
                    contract_object_count[cid] = (
                        contract_object_count.get(cid, 0) + 1)
            for key, g in groups.items():
                contract_id = g['contract'].id if g['contract'] else None
                base_object_id = g['base_object'].id if g['base_object'] else None
                if contract_id:
                    total_adv = advanced_by_contract.get(contract_id, Decimal(0))
                    total_actual = contract_actual_totals.get(contract_id, Decimal(0))
                    if total_actual > 0:
                        adv = (total_adv * g['actual_costs'] / total_actual).quantize(
                            Decimal('0.01'), rounding=ROUND_HALF_UP)
                    else:
                        n = contract_object_count.get(contract_id, 1)
                        adv = (total_adv / n).quantize(
                            Decimal('0.01'), rounding=ROUND_HALF_UP)
                    refund = g['actual_costs'] - adv
                else:
                    adv = None
                    refund = None
                term_ids = terms_by_contract.get(contract_id, set()) if contract_id else set()
                term_id = term_ids.pop() if len(term_ids) == 1 else None
                result = SettlementResult(
                    billing_unit=billing_unit.id,
                    contract=contract_id,
                    base_object=base_object_id,
                    term=term_id,
                    start_date=g['start_date'],
                    end_date=g['end_date'],
                    planned_costs=g['planned_costs'],
                    actual_costs=g['actual_costs'],
                    advanced_payment=adv,
                    refund_receivable=refund,
                )
                result.save()
            billing_unit.add_log('compute_settlement_result',
                f'Settlement results computed: {len(groups)} records created.')


    @staticmethod
    def default_state():
        return 'draft'
    
    @staticmethod
    def default_calculation_method():
        return 'rental_apartment'

    @staticmethod
    def default_billing_type():
        return 'planned_billing'

    @staticmethod
    def get_sub_states():
        pool = Pool()
        CostShare = pool.get('real_estate.cost_share')
        return CostShare.fields_get(['state'])['state']['selection']
    
    @fields.depends('settlement_units')
    def on_change_with_sub_state(self, name=None):
        #return the lowest state of all settlement units
        if self.settlement_units:
            states = set(settlement_unit.sub_state for settlement_unit in self.settlement_units)
            if len(states) == 1:
                return states.pop()
            elif 'error' in states:
                return 'error'
            elif 'selection' in states:
                return 'selection'
            elif 'value_share' in states:
                return 'value_share'
        return None
    
    @fields.depends('settlement_units')
    def on_change_with_invoice_lines(self, name=None):
        invoice_lines = []
        for settlement_unit in self.settlement_units:
            invoice_lines.extend(settlement_unit.invoice_lines)
        return invoice_lines

    @fields.depends('settlement_units')
    def on_change_with_cost_shares(self, name=None):
        cost_shares = []
        for settlement_unit in self.settlement_units:
            cost_shares.extend(settlement_unit.cost_shares)
        return cost_shares

    @fields.depends('settlement_units', 'start_date', 'end_date',
            'term_types_of_use', 'billing_type')
    def on_change_with_cash_flow_lines(self, name=None):
        """Collect contracts from cost_shares of all settlement_units.
        Filter by term_types_of_use and document_date within start_date..end_date.
        billing_type='actual_billing': only paid lines (invoice_state='paid').
        billing_type='planned_billing': all lines except cancelled invoices."""
        CashFlowLine = Pool().get('real_estate.contract.term.cash_flow')
        contract_ids = list({
            cs.contract.id
            for su in (self.settlement_units or [])
            for cs in su.cost_shares
            if cs.contract
        })
        if not contract_ids:
            return []
        domain = [('term.contract', 'in', contract_ids)]
        if self.term_types_of_use:
            term_type_ids = [int(t) for t in self.term_types_of_use]
            domain.append(('term.term_type', 'in', term_type_ids))
        if self.start_date:
            domain.append(('document_date', '>=', self.start_date))
        if self.end_date:
            domain.append(('document_date', '<=', self.end_date))
        if self.billing_type == 'actual_billing':
            domain.append(('invoice_state', '=', 'paid'))
        else:
            domain.append(('invoice_state', '!=', 'cancelled'))
        return CashFlowLine.search(domain)

    def _get_cost_shares(self):
        """Returns all cost_shares across settlement_units, or [] if guard fails."""
        if self.state == 'draft':
            return []
        shares = [
            cs
            for su in (self.settlement_units or [])
            for cs in su.cost_shares
        ]
        return shares

    @fields.depends('state', 'settlement_units')
    def on_change_with_sum_planned_costs(self, name=None):
        shares = self._get_cost_shares()
        if not shares:
            return Decimal(0)
        return sum((cs.planned_costs or Decimal(0)) for cs in shares)

    @fields.depends('state', 'settlement_units')
    def on_change_with_sum_actual_costs(self, name=None):
        shares = self._get_cost_shares()
        if not shares:
            return Decimal(0)
        return sum((cs.actual_costs or Decimal(0)) for cs in shares)

    @fields.depends('state', 'settlement_units')
    def on_change_with_sum_actual_cost_by_owner(self, name=None):
        """Cost shares without contract = costs borne by owner (vacancy/object)."""
        shares = self._get_cost_shares()
        if not shares:
            return Decimal(0)
        return sum(
            (cs.actual_costs or Decimal(0))
            for cs in shares
            if not cs.contract
        )

    @fields.depends('state', 'settlement_units')
    def on_change_with_sum_actual_cost_by_allocation(self, name=None):
        """Cost shares with contract = costs allocated to tenants."""
        shares = self._get_cost_shares()
        if not shares:
            return Decimal(0)
        return sum(
            (cs.actual_costs or Decimal(0))
            for cs in shares
            if cs.contract
        )

    @fields.depends('state', 'settlement_units', 'cash_flow_lines')
    def on_change_with_sum_advanced_payment(self, name=None):
        if not self._get_cost_shares():
            return Decimal(0)
        return sum(
            (line.amount or Decimal(0))
            for line in (self.cash_flow_lines or [])
        )

    @fields.depends('state', 'settlement_units', 'cash_flow_lines')
    def on_change_with_sum_refund_receivable(self, name=None):
        """Positive = tenant owes additional payment; negative = refund due to tenant."""
        shares = self._get_cost_shares()
        if not shares:
            return Decimal(0)
        allocation = sum(
            (cs.actual_costs or Decimal(0))
            for cs in shares
            if cs.contract
        )
        advanced = sum(
            (line.amount or Decimal(0))
            for line in (self.cash_flow_lines or [])
        )
        return allocation - advanced

    @fields.depends('property')
    def on_change_with_company(self, name=None):
        return self.property.company if self.property else None

    @fields.depends('property')
    def on_change_with_collective_billing(self, name=None):
        return bool(self.property.collective_billing) if self.property else False

    def pre_validate(self):
        super().pre_validate()
        self.check_calculation_method()

    @fields.depends('calculation_method', 'start_date')
    def check_calculation_method(self, name=None):
        if self.calculation_method == 'WEG_billing' and ( self.start_date.month != 1 or self.start_date.day != 1 ):
            raise InvalidCalculationMethod(gettext("real_estate.msg_invalid_calculation_method",).format(
                self.start_date))


    @fields.depends('start_date')
    def on_change_with_end_date(self, name=None):
        if self.start_date :
            return self.start_date - relativedelta(days=1) + relativedelta(years=1)
        return None

    @fields.depends(methods=['_check_calculation_method_notify'])
    def on_change_notify(self):
        notifications = super().on_change_notify()
        notifications.extend(self._check_calculation_method_notify())
        return notifications

    @fields.depends('calculation_method', 'start_date')
    def _check_calculation_method_notify(self):
        if self.calculation_method == 'WEG_billing' and ( self.start_date.month != 1 or self.start_date.day != 1 ):
            logger.warning(f"Invalid calculation method for billing unit {self.id}: start date {self.start_date} is not the first day of the year.")
            yield ('warning', 
                   gettext("real_estate.msg_invalid_calculation_method",).format(
                       self.start_date))

    @classmethod
    def get_term_types_of_use(cls):
        pool = Pool()
        TermType = pool.get('real_estate.contract.term.type')
        term_types = TermType.search([])
        if term_types:
            result = [(str(ele.id), ele.name) for ele in term_types]
            return result
        return [] 

    @classmethod
    def search_name(cls, name, offset=0, limit=None, order=None):
        pool = Pool()
        BaseObject = pool.get('real_estate.base_object')
        return BaseObject.search_name(name, offset, limit, order)

    @staticmethod
    def default_start_date():
        #first day of the current month
        return Pool().get('ir.date').today().replace(day=1)    

    @fields.depends('start_date', 'end_date', 'description')
    def on_change_with_name(self, name=None):
        if self.start_date and self.end_date:     
            return f"{self.description} - {self.start_date} / {self.end_date}"
        return f" ? "

    @fields.depends('company')
    def on_change_with_currency(self, name=None):
        return self.company.currency if self.company else None

    @fields.depends('settlement_units')
    def on_change_with_planned_costs(self, name=None):
        if self.settlement_units:
            return sum(settlement_unit.planned_costs for settlement_unit in self.settlement_units if settlement_unit.planned_costs)

        # # here you can implement the logic to calculate the planned costs based on the start and end date
        # # for example, you can sum up the costs of all cost objects that fall within the date range
        # if self.start_date and self.end_date:
        #     pool = Pool()
        #     SettlementUnit = pool.get('real_estate.settlement_unit')
        #     settlement_units = SettlementUnit.search([
        #         ('billing_unit', '=', self.id),
        #         ('start_date', '>=', self.start_date),
        #         ('end_date', '<=', self.end_date),
        #     ])
        #     total_costs = sum(settlement_unit.planned_costs for settlement_unit in settlement_units)
        #     return total_costs
        # return None

    @fields.depends('property')
    def on_change_with_company(self, name=None):
        return self.property.company if self.property else None

    @classmethod
    def name_search(cls, name, clause):
        if clause[1].startswith('!') or clause[1].startswith('not '):
            bool_op = 'AND'
        else:
            bool_op = 'OR'

        return [bool_op,
            ('property.name',) + tuple(clause[1:]),
        ]  


    def add_log(self, event, description=None):
        pool = Pool()
        CostLog = pool.get('real_estate.billing_unit.log')
        CostLog.create([{
            'billing_unit': self.id,
            'event': event,
            'description': description or '',
        }])
        print(f'billing unit {self.id}, event {event}, description {description}')

#**********************************************************************
class BillingUnitLog(ModelSQL, ModelView):
    "Billing Unit log obj"
    __name__ = 'real_estate.billing_unit.log'

    billing_unit = fields.Many2One('real_estate.billing_unit', 'Billing Unit', required=True, ondelete='CASCADE')
    event = fields.Char('Event', required=True)
    description = fields.Text('Description')
    create_date = fields.DateTime('Create Date', readonly=True)
    create_uid = fields.Many2One('res.user', 'User', readonly=True)

    log_date = fields.Function(fields.Date('Date'), 'get_log_date',
        searcher='search_log_date')

    property = fields.Function(
        fields.Many2One('real_estate.base_object', 'Property'),
        'on_change_with_property', searcher='search_property')

    company = fields.Function(
        fields.Many2One('company.company', 'Company'),
        'on_change_with_company', searcher='search_company')

    def get_log_date(self, name):
        if self.create_date:
            return self.create_date.date()
        return None

    @classmethod
    def search_log_date(cls, name, clause):
        _, operator, value = clause
        if value is None:
            return [('create_date', operator, None)]
        if isinstance(value, datetime.date) and not isinstance(value, datetime.datetime):
            if operator == '>=':
                value = datetime.datetime.combine(value, datetime.time.min)
            elif operator == '<=':
                value = datetime.datetime.combine(value, datetime.time.max)
            elif operator == '=':
                return ['AND',
                    ('create_date', '>=', datetime.datetime.combine(value, datetime.time.min)),
                    ('create_date', '<=', datetime.datetime.combine(value, datetime.time.max)),
                ]
        return [('create_date', operator, value)]

    @fields.depends('billing_unit')
    def on_change_with_property(self, name=None):
        if self.billing_unit and self.billing_unit.property:
            return self.billing_unit.property
        return None

    @fields.depends('billing_unit')
    def on_change_with_company(self, name=None):
        if self.billing_unit and self.billing_unit.property:
            return self.billing_unit.property.company
        return None

    @classmethod
    def search_property(cls, name, clause):
        return [('billing_unit.property',) + tuple(clause[1:])]

    @classmethod
    def search_company(cls, name, clause):
        return [('billing_unit.property.company',) + tuple(clause[1:])]


#**********************************************************************
class BillingUnitContext(ModelView):
    'Billing Unit Context'
    __name__ = 'real_estate.billing_unit.context'

    company = fields.Many2One('company.company', 'Company', required=True)
    property = fields.Many2One('real_estate.base_object', 'Property',
        domain=[
            ('type', '=', 'property'),
            ('company', '=', Eval('company', -1)),
        ])

    @classmethod
    def default_company(cls):
        return Transaction().context.get('company')


class BillingUnitLogContext(ModelView):
    'Billing Unit Log Context'
    __name__ = 'real_estate.billing_unit.log.context'

    company = fields.Many2One('company.company', 'Company', required=True)
    property = fields.Many2One('real_estate.base_object', 'Property',
        domain=[
            ('type', '=', 'property'),
            ('company', '=', Eval('company', -1)),
        ])
    billing_unit = fields.Many2One('real_estate.billing_unit', 'Billing Unit',
        domain=[
            If(Eval('property', None),
                [('property', '=', Eval('property', None))],
                []),
        ])
    from_date = fields.Date('From Date')
    to_date = fields.Date('To Date')

    @classmethod
    def default_company(cls):
        return Transaction().context.get('company')

    @classmethod
    def default_from_date(cls):
        today = Pool().get('ir.date').today()
        return today.replace(month=1, day=1)

    @classmethod
    def default_to_date(cls):
        return Pool().get('ir.date').today()


#**********************************************************************
class SettlementUnit(DeactivableMixin, base_object.re_sequence_ordered(), ModelSQL, ModelView):
    """Settlement Unit, e.g. cost allocation for a specific cost type and period within a billing unit."""
    __name__ = 'real_estate.settlement_unit'
    __rec_name__ = 'name'

    property = fields.Function(fields.Many2One('real_estate.base_object','Property'),
        'on_change_with_property')

    company = fields.Function(fields.Many2One('company.company','Company'),
        'on_change_with_company')
    
    billing_unit = fields.Many2One('real_estate.billing_unit', 'Billing Unit',
        required=True, ondelete='CASCADE',
        # domain=[
        #      ('company', '=', Eval('company', -1)),
        #      ('property', '=', Eval('property', -1)),],
             ) 

    start_date = fields.Function(fields.Date('Start Date',), 'on_change_with_start_date',)
    
    end_date = fields.Function(fields.Date('End Date'),'on_change_with_end_date')   

    state = fields.Function(fields.Selection('get_states', "State"), 'on_change_with_state')  

    sub_state = fields.Function(fields.Selection('get_sub_states', "Sub State"), 'on_change_with_sub_state')  

    type = fields.Many2One(
        'real_estate.cost_type', "Cost Type", required=True, on_change='on_change_type',)
    
    comment = fields.Text("Comment")    
    
    name = fields.Function(fields.Char("Name"), 'on_change_with_name', 
                searcher='name_search')  

    planned_costs = Monetary('Planned Costs', currency='currency', digits='currency',
        states={'readonly': Eval('state') == 'billed'},
        )

    actual_costs = Monetary('Actual Costs', currency='currency', digits='currency',
        states={'readonly': Eval('state') == 'billed'},
        )

    currency = fields.Function(fields.Many2One('currency.currency', 'Currency',), 'on_change_with_currency')


    allocation_rule =  fields.Selection([
            ('no_allocation', 'No allocation'),
            ('allocation_by_measurement', 'Allocation by measurement'),
            ('allocation_by_consumption', 'Allocation by consumption'),
            ('allocation_per_rental_unit', 'Allocation per rental unit'),
            ], "Allocation Rule", sort=False,
            #states={ 'readonly': True, },
            ) 

    vacancy = fields.Selection([
        ('no_allocation', 'No allocation (all cost allocated by tenant)'),
        ('by_owner', 'Allocation by owner'),
        ], "Allocation During Vacancy", sort=False,
        states={ 'invisible': Eval('allocation_rule') == 'no_allocation', },
        )
    
    m_type = fields.Many2One(
        'real_estate.measurement.type', "Measurement Type",
        domain=[('types', '=', ['object'])], #exact only 'object'
        states={
            'invisible': Eval('allocation_rule') != 'allocation_by_measurement',
            'required': Eval('allocation_rule') == 'allocation_by_measurement',
            },)


    meter_unit = fields.Many2One('product.uom', "Unit",
        states={
            'invisible': Eval('allocation_rule') != 'allocation_by_consumption',
            'required': Eval('allocation_rule') == 'allocation_by_consumption',
            },)

    reg_ex_object = fields.Char("Reg. Ex. Object",
        help="Regular expression to find the object. For Example '[1-9/ ]*Apartement[1-9()# ]*' to find the object with name contains '100/100 Apartement #45'.",
        states={
            'invisible': Eval('allocation_rule') == 'no_allocation',
            #'required': Eval('allocation_rule') != 'no_allocation',
            },)
    
    reg_ex_meter = fields.Char("Reg. Ex. Meter",
        help="Regular expression to find the meter. For Example '[1-9/ ]*Electricity[1-9a-Z()# ]*' to find the meter with name contains '556 Electricity Meter'.",
        states={
            'invisible': Eval('allocation_rule') != 'allocation_by_consumption',
            #'required': Eval('allocation_rule') == 'allocation_by_consumption',
            },)  


    objects = fields.Function(fields.One2Many('real_estate.base_object', None, 'Objects',
                                              readonly=True,
        #domain=[('company', '=', Eval('company', -1)),
        #        ('property', '=', Eval('property', -1)),
        #        ('type', '=', 'object')],
        states={
            'invisible': ((Eval('allocation_rule') == 'no_allocation') | (Eval('state') == 'billed')),
            }
        ),'on_change_with_objects', 
        setter='set_objects',
        )
    

    meters = fields.Function(fields.One2Many('real_estate.base_object', None, 'Meters',
                                              readonly=True,
        #domain=[('company', '=', Eval('company', -1)),
        #        ('property', '=', Eval('property', -1)),
        #        ('type', '=', 'meter')],
        states={
            'invisible': ((Eval('allocation_rule') != 'allocation_by_consumption') | (Eval('state') == 'billed')),
            }
        ),'on_change_with_meters', 
        setter='set_meters',
        )

    measurements = fields.Function(fields.One2Many('real_estate.measurement', None, 'Measurements',
                                              readonly=True,
        #domain=[('company', '=', Eval('company', -1)),
        #        ('property', '=', Eval('property', -1)),
        #        ('m_type', '=', Eval('m_type', -1))],
        states={
            'invisible': ((Eval('allocation_rule') != 'allocation_by_measurement') | (Eval('state') == 'billed')),
            }
        ),'on_change_with_measurements', 
        setter='set_measurements',
        )


    cost_shares = fields.One2Many('real_estate.cost_share', 'settlement_unit', 'Cost Shares',
        states={ 
            'readonly': True, 
            'invisible': ((Bool(Eval('cost_shares',0)) == False ) | (Eval('state') == 'draft')),
            },
        )
    
    value_total = fields.Float('Value to Total', digits=(16, 4),
      states={  'readonly': True,  }
        )

    time_total = fields.Function(fields.Integer('Time Total (days)'),
        'on_change_with_time_total')

    invoice_lines = fields.Function(fields.One2Many('account.invoice.line', 'settlement_unit', 'Invoice Lines',),
        'on_change_with_invoice_lines')

    @classmethod
    def view_attributes(cls):
        return super().view_attributes() + [
            ('//page[@id="page_measurements"]', 'states', {
                'invisible': Eval('allocation_rule') != 'allocation_by_measurement',
            }),
            ('//page[@id="page_meters"]', 'states', {
                'invisible': Eval('allocation_rule') != 'allocation_by_consumption',
            }),
        ]

    @classmethod
    def default_company(cls):
        return Transaction().context.get('company')

    @classmethod
    def default_allocation_rule(cls):
        return 'no_allocation'
    
    @staticmethod
    def default_vacancy():
        return 'no_allocation'

    @staticmethod
    def get_states():
        pool = Pool()
        BillingUnit = pool.get('real_estate.billing_unit')
        return BillingUnit.fields_get(['state'])['state']['selection']     
    
    @staticmethod
    def get_sub_states():
        pool = Pool()
        CostShare = pool.get('real_estate.cost_share')
        return CostShare.fields_get(['state'])['state']['selection']

    @fields.depends('type', 'sequence')
    def on_change_type(self):
        if self.type and not self.sequence:
            self.sequence = self.type.sequence

    @fields.depends('billing_unit')
    def on_change_with_state(self, name=None):
        return self.billing_unit.state if self.billing_unit else None     
    
    @fields.depends('cost_shares')
    def on_change_with_sub_state(self, name=None):
        #return the lowest state of all cost shares
        if self.cost_shares:
            states = set(cost_share.state for cost_share in self.cost_shares)
            if len(states) == 1:
                return states.pop()
            elif 'error' in states:
                return 'error'
            elif 'selection' in states:
                return 'selection'
            elif 'estimated_value_share' in states:
                return 'estimated_value_share'
            elif 'value_share' in states:
                return 'value_share'
        return 'preparation' #if no cost share linked, return preparation as default sub state

    @fields.depends('billing_unit')
    def on_change_with_property(self, name=None):
        return self.billing_unit.property if self.billing_unit else None
    
    @fields.depends('billing_unit')
    def on_change_with_company(self, name=None):
        return self.billing_unit.property.company if self.billing_unit else None

    @fields.depends('billing_unit', 'reg_ex_object', 'allocation_rule')
    def on_change_with_objects(self, name=None):
        objects = []
        if self.billing_unit and self.allocation_rule != 'no_allocation':
            objects = Pool().get('real_estate.base_object').search([
                ('company', '=', self.billing_unit.company),
                ('property', '=', self.billing_unit.property),
                ('type', '=', 'object'),
                ('state', '=', 'approved'), #only search approved objects
            ])
            if self.reg_ex_object:
                pattern = re.compile(self.reg_ex_object)
                objects = [item for item in objects if pattern.search(item.name)]
        return objects
    
    @fields.depends('billing_unit', 'reg_ex_meter', 'allocation_rule', 'objects', 'meter_unit')
    def on_change_with_meters(self, name=None):
        meters = []
        if self.billing_unit and self.objects and self.allocation_rule == 'allocation_by_consumption':
            meters = Pool().get('real_estate.base_object').search([
                ('company', '=', self.billing_unit.company),
                ('property', '=', self.billing_unit.property),
                ('parent', 'in', [obj.id for obj in self.objects]), #only search meters which are linked to the objects
                ('type', '=', 'equipment'),
                ('e_type', '=', 'meters'), #only search meters which have measurement type
                ('meter_unit', '=', self.meter_unit), #only search meters which have the same unit
                ('state', '=', 'approved'), #only search approved objects
            ])
            if self.reg_ex_meter:
                pattern = re.compile(self.reg_ex_meter)
                meters = [item for item in meters if pattern.search(item.name)]
        return meters

    @fields.depends('billing_unit', 'm_type', 'allocation_rule', 'objects')
    def on_change_with_measurements(self, name=None):
        measurements = []
        if self.billing_unit and self.objects and self.allocation_rule == 'allocation_by_measurement':
            measurements = Pool().get('real_estate.measurement').search([
                ('base_object', 'in', [obj.id for obj in self.objects]), #only search measurements which are linked to the objects
                ('m_type', '=', self.m_type), #only search measurements which have the same measurement type
            ], order=[('base_object', 'ASC'),('valid_from', 'DESC')]) #order by field_name to make sure the sequence of measurements is correct
        return measurements

    def on_change_with_invoice_lines(self, name=None):
        invoice_lines = Pool().get('account.invoice.line').search([
            ('settlement_unit', '=', self.id),
            ('invoice.state', '!=', 'cancelled'),
        ])
        return invoice_lines

    @classmethod
    def set_objects(cls, objects, name, value):
        # `objects` = Liste der Instanzen,
        # `name` = Feldname ('objects'),
        # `value` = neuer Wert, z.B. Liste von IDs bei Many2Many
        pass   # hier Logik schreiben    

    @classmethod
    def set_meters(cls, meters, name, value):
        pass   # hier Logik schreiben

    @classmethod
    def set_measurements(cls, measurements, name, value):
        pass   # hier Logik schreiben

    @fields.depends('type')
    def on_change_with_sequence(self, name=None):
        return self.type.sequence if ( self.type and not self.sequence ) else self.sequence

    @fields.depends('billing_unit')
    def on_change_with_start_date(self, name=None):
        return self.billing_unit.start_date if self.billing_unit else None
    
    @fields.depends('billing_unit')
    def on_change_with_end_date(self, name=None):
        return self.billing_unit.end_date if self.billing_unit else None

    @fields.depends('type', 'sequence')
    def on_change_with_name(self, name=None):
        return f"{self.sequence} - {self.type.name}" if self.type else f"{self.sequence} - ? "
    
    @fields.depends('company')
    def on_change_with_currency(self, name=None):
        return self.company.currency if self.company else None

    @fields.depends('start_date', 'end_date')
    def on_change_with_time_total(self, name=None):
        if self.start_date and self.end_date:
            return (self.end_date - self.start_date).days + 1
        return None

    def selection(self):
        """Select objects and contracts for billing using the occupancy table."""
        if self.state != 'approved' and self.state != 'selection' and self.state != 'value_share':
            raise ValidationError(gettext("Only settlement units with state 'Approved' or 'Selection' or 'Value Share' can be selected."))

        CostShare = Pool().get('real_estate.cost_share')
        if self.cost_shares:
            CostShare.delete(list(self.cost_shares))

        Occupancy = Pool().get('real_estate.base_object.occupancy')
        is_weg = self.billing_unit.calculation_method == 'WEG_billing'
        bu_start = self.billing_unit.start_date
        bu_end = self.billing_unit.end_date
        object_count = 0

        for object in self.objects:
            if not (object.state == 'approved'
                    and object.start_date <= bu_end
                    and (object.end_date is None or object.end_date >= bu_start)):
                continue
            object_count += 1

            # Refresh occupancy so date ranges reflect current contract state
            Occupancy.refresh([object])

            # Occupancy entries overlapping the billing unit period
            occ_domain = [
                ('base_object', '=', object.id),
                ('start_date', '<=', bu_end),
                ['OR', ('end_date', '=', None), ('end_date', '>=', bu_start)],
            ]

            if is_weg:
                # WEG: last rented entry covers the entire billing unit period
                entries = Occupancy.search(
                    occ_domain + [('state', '=', 'rented')],
                    order=[('start_date', 'DESC')], limit=1)
                if not entries:
                    self.billing_unit.add_log('selection_error',
                        f'Settlement unit {self.id}: no rented occupancy found'
                        f' for object {object.id}.')
                else:
                    cost_share = CostShare(
                        settlement_unit=self.id,
                        contract=entries[0].contract.id if entries[0].contract else None,
                        base_object=object.id,
                        start_date=bu_start,
                        end_date=bu_end,
                        state='selection',
                    )
                    cost_share.save()
            else:
                # Non-WEG: all rented entries create cost shares for their respective periods; 
                # if vacancy allocation by owner, also create cost shares for vacant periods
                entries = Occupancy.search(occ_domain, order=[('start_date', 'ASC')])
                by_owner = self.vacancy == 'by_owner'
                rented = any(e.state == 'rented' for e in entries)
                if not rented and not (any(e.state == 'vacant' for e in entries) and by_owner):
                    self.billing_unit.add_log('selection_error',
                        f'Settlement unit {self.id}: no rented occupancy found'
                        f' for object {object.id}.')
                else:
                    for occ in entries:
                        # cap to billing unit period
                        share_start = max(occ.start_date, bu_start)
                        if occ.end_date:
                            share_end = min(occ.end_date, bu_end) if bu_end else occ.end_date
                        else:
                            share_end = bu_end

                        if occ.state == 'rented':
                            cost_share = CostShare(
                                settlement_unit=self.id,
                                contract=occ.contract.id if occ.contract else None,
                                base_object=object.id,
                                start_date=share_start,
                                end_date=share_end,
                                state='selection',
                            )
                            cost_share.save()
                        elif occ.state == 'vacant' and by_owner:
                            cost_share = CostShare(
                                settlement_unit=self.id,
                                contract=None,
                                base_object=object.id,
                                start_date=share_start,
                                end_date=share_end,
                                state='selection',
                            )
                            cost_share.save()
                            self.billing_unit.add_log('vacancy_selection',
                                f'Settlement unit {self.id}: vacancy cost share created'
                                f' for object {object.id} from {share_start} to {share_end}.')

        self.billing_unit.add_log('selection',
            f'Settlement unit {self.id} selection completed: {object_count} objects processed.')
        self.save()

    def selection_actual_costs(self):
        """Sum amount + tax of all invoice lines assigned to this settlement unit
        and write the result into actual_costs."""
        pool = Pool()
        InvoiceLine = pool.get('account.invoice.line')
        Tax = pool.get('account.tax')
        lines = InvoiceLine.search([
            ('settlement_unit', '=', self.id),
            ('invoice.state', '!=', 'cancelled'),
        ])
        actual = Decimal(0)
        for line in lines:
            amount = line.amount or Decimal(0)
            tax_amount = Decimal(0)
            if line.taxes:
                tax_date = (line.invoice.invoice_date
                    if line.invoice and line.invoice.invoice_date
                    else datetime.date.today())
                computed = Tax.compute(
                    list(line.taxes),
                    line.unit_price or Decimal(0),
                    line.quantity or Decimal(0),
                    tax_date,
                )
                tax_amount = sum(
                    Decimal(str(t['amount'])) for t in computed
                )

            if self.property and self.property.billing_as == 'commercial':
                actual += amount
            else:
                actual += amount + tax_amount
        self.actual_costs = actual.quantize(Decimal('0.01'))
        self.save()

    def compute_value_shares(self):
        """Compute value_share on each CostShare based on allocation_rule,
        then write value_total as the sum on this SettlementUnit."""
        self.selection_actual_costs()
        pool = Pool()
        Measurement = pool.get('real_estate.measurement')
        BaseObject = pool.get('real_estate.base_object')
        MeterReading = pool.get('real_estate.meter_reading')

        if self.allocation_rule == 'no_allocation':
            return

        total = 0.0

        for cost_share in self.cost_shares:
            if not cost_share.base_object:
                continue

            value = None
            error_msg = None

            if self.allocation_rule == 'allocation_by_measurement':
                measurements = Measurement.search([
                    ('base_object', '=', cost_share.base_object.id),
                    ('m_type', '=', self.m_type.id),
                    ('valid_from', '<=', cost_share.end_date),
                ], order=[('valid_from', 'DESC')], limit=1)
                if measurements:
                    value = float(measurements[0].value or 0)
                else:
                    error_msg = (
                        f'No measurement for {cost_share.base_object.rec_name}'
                        f' type {self.m_type.name} on {cost_share.end_date}')

            elif self.allocation_rule == 'allocation_by_consumption':
                meter_domain = [
                    ('parent', '=', cost_share.base_object.id),
                    ('type', '=', 'equipment'),
                    ('e_type', '=', 'meters'),
                    ('meter_unit', '=', self.meter_unit.id),
                    ('state', '=', 'approved'),
                ]
                meters = BaseObject.search(meter_domain)
                if self.reg_ex_meter:
                    pattern = re.compile(self.reg_ex_meter)
                    meters = [m for m in meters if pattern.search(m.name or '')]

                consumption = 0.0
                found = False
                for meter in meters:
                    factor = float(meter.meter_factor or 1)
                    if meter.meter_is_counter:
                        end_rdg = MeterReading.search([
                            ('base_object', '=', meter.id),
                            ('reading_date', '<=', cost_share.end_date),
                        ], order=[('reading_date', 'DESC')], limit=1)
                        start_rdg = MeterReading.search([
                            ('base_object', '=', meter.id),
                            ('reading_date', '<=', cost_share.start_date),
                        ], order=[('reading_date', 'DESC')], limit=1)
                        if end_rdg and start_rdg:
                            consumption += (
                                float(end_rdg[0].value or 0)
                                - float(start_rdg[0].value or 0)
                            ) * factor
                            found = True
                    else:
                        rdgs = MeterReading.search([
                            ('base_object', '=', meter.id),
                            ('reading_date', '>=', cost_share.start_date),
                            ('reading_date', '<=', cost_share.end_date),
                        ], order=[('reading_date', 'DESC')], limit=1)
                        if rdgs:
                            consumption += float(rdgs[0].value or 0) * factor
                            found = True

                if found:
                    value = consumption
                else:
                    error_msg = (
                        f'No meter readings for {cost_share.base_object.rec_name}'
                        f' in {cost_share.start_date} – {cost_share.end_date}')

            elif self.allocation_rule == 'allocation_per_rental_unit':
                value = 1.0

            if value is not None:
                cost_share.value_share = value
                if cost_share.state in ('selection', 'estimated_value_share'):
                    cost_share.state = 'value_share'
                total += value
            else:
                cost_share.state = 'error'
                cost_share.error_message = error_msg
            cost_share.save()

        self.value_total = total
        self.save()

        # Second pass: distribute planned_costs and actual_costs
        CostShare = pool.get('real_estate.cost_share')
        vt = Decimal(str(total)) if total else Decimal(0)
        time_total = (
            (self.end_date - self.start_date).days + 1
            if self.start_date and self.end_date else 0)

        cost_shares = CostShare.search(
            [('settlement_unit', '=', self.id),
             ('state', '=', 'value_share')])

        def _distribute(su_amount):
            """Return list of (cost_share, rounded_amount) summing to su_amount."""
            _cent = Decimal('0.01')
            rows = []
            for cs in cost_shares:
                if not cs.value_share or not vt:
                    raw = Decimal(0)
                else:
                    vs = Decimal(str(cs.value_share))
                    if self.allocation_rule == 'allocation_by_consumption':
                        raw = su_amount * vs / vt
                    else:
                        ts = (
                            (cs.end_date - cs.start_date).days + 1
                            if cs.start_date and cs.end_date else 0)
                        time_factor = (
                            Decimal(ts) / Decimal(time_total)
                            if time_total else Decimal(0))
                        raw = su_amount * vs / vt * time_factor
                rows.append([cs, raw.quantize(_cent, rounding=ROUND_HALF_UP)])
            diff = (su_amount - sum(r[1] for r in rows)).quantize(_cent)
            if diff and rows:
                n = int(abs(diff) / _cent)
                if diff > 0:
                    rows.sort(key=lambda r: r[1])
                    for i in range(n):
                        rows[i % len(rows)][1] += _cent
                else:
                    rows.sort(key=lambda r: r[1], reverse=True)
                    for i in range(n):
                        rows[i % len(rows)][1] -= _cent
            return rows

        planned_rows = _distribute(self.planned_costs or Decimal(0))
        actual_rows = _distribute(self.actual_costs or Decimal(0))

        actual_by_id = {r[0].id: r[1] for r in actual_rows}
        for cost_share, planned_amount in planned_rows:
            cost_share.planned_costs = planned_amount
            cost_share.actual_costs = actual_by_id.get(cost_share.id, Decimal(0))
            cost_share.save()

    def builling(self, selection_on=False):
        if self.state == 'billed':
            raise ValidationError(gettext("This settlement unit is already billed."))
        if self.state != 'draft':
            raise ValidationError(gettext("Only settlement unit with state 'Approved' can be billed."))

        if selection_on:
            #if cost object without allocation rule 'no_allocation' can be billed without selection
            if self.allocation_rule != 'no_allocation':
                self.selection()
            

        #self.state = 'billed'
        #self.save()



    @classmethod
    def name_search(cls, name, clause):
        if clause[1].startswith('!') or clause[1].startswith('not '):
            bool_op = 'AND'
        else:
            bool_op = 'OR'

        return [bool_op,
            ('property.name',) + tuple(clause[1:]),
            ('commend',) + tuple(clause[1:]),
        ]      

class SettlementUnitContext(ModelView):
    'Settlement Unit Context'
    __name__ = 'real_estate.settlement_unit.context'

    company = fields.Many2One('company.company', 'Company', required=True)
    property = fields.Many2One('real_estate.base_object', 'Property',
        domain=[
            ('type', '=', 'property'),
            ('company', '=', Eval('company', -1)),
        ])

    @classmethod
    def default_company(cls):
        return Transaction().context.get('company')


#**********************************************************************
class CostShare(DeactivableMixin, ModelSQL, ModelView):
    """Cost Share, e.g. share of a specific cost type and period allocated to a specific contract or object."""
    __name__ = 'real_estate.cost_share'
    __rec_name__ = 'name'

    settlement_unit = fields.Many2One('real_estate.settlement_unit', 'Settlement Unit', required=True, ondelete='CASCADE',)

    name = fields.Function(fields.Char('Name'), 'on_change_with_name',
        searcher='search_name')

    state = fields.Selection([
            ('preparation', 'Preparation'),
            ('selection', 'Selection'),
            ('estimated_value_share', 'Estimated Value Share'),
            ('value_share', 'Value Share'),
            ('error', 'Error'),
            ], "State", sort=False,
            states={ 'readonly': True, },
            )
    
    start_date = fields.Date('Start Date', 
         states={
        'readonly': True,},
        )
    
    end_date = fields.Date('End Date', 
         states={
        'readonly': True,},
        )
    
    contract = fields.Many2One('real_estate.contract', 'Contract', ondelete='CASCADE',
        states={
        'readonly': True,},
        )
    
    base_object = fields.Many2One('real_estate.base_object', 'Object', ondelete='CASCADE',
        domain=[('type', '=', 'object')],
        )
    
    value_share = fields.Float('Value Share',digits=(16, 4),
        states={
        'readonly': Eval('state') != 'value_share',},
        )

    time_share = fields.Function(fields.Integer('Time Share (days)'),
        'on_change_with_time_share')

    planned_costs = Monetary('Planned Costs', currency='currency', digits= 'currency',#(16, 2),
        states={
            'readonly': Eval('state') == 'billed',
            },
        )
    
    actual_costs = Monetary('Actual Costs', currency='currency', digits= 'currency',#(16, 2),
        states={
            'readonly': Eval('state') != 'value_share',
            },
        )

    currency = fields.Function(fields.Many2One('currency.currency', 'Currency',), 'on_change_with_currency') 

    error_message = fields.Char('Error Message', readonly=True)


    @classmethod
    def default_state(cls):
        return 'selection'
    
    @fields.depends('start_date', 'end_date', 'contract', 'base_object')
    def on_change_with_name(self, name=None):
        date_part = (
            f"{self.start_date:%Y-%m-%d}" if self.start_date else '?'
        ) + ' - ' + (
            f"{self.end_date:%Y-%m-%d}" if self.end_date else '?'
        )
        if self.contract:
            return f"{date_part} / {self.contract.rec_name}"
        elif self.base_object:
            return f"{date_part} / {self.base_object.rec_name}"
        return date_part
    
    @classmethod
    def search_name(cls, name, clause):
        _, operator, value = clause
        return ['OR',
            ('contract', operator, value),
            ('base_object.name', operator, value),
        ]

    @fields.depends('settlement_unit')
    def on_change_with_currency(self, name=None):
        return self.settlement_unit.currency if self.settlement_unit else None

    @fields.depends('start_date', 'end_date')
    def on_change_with_time_share(self, name=None):
        if self.start_date and self.end_date:
            return (self.end_date - self.start_date).days + 1
        return None


class CostShareContext(ModelView):
    'Cost Share Context'
    __name__ = 'real_estate.cost_share.context'

    company = fields.Many2One('company.company', 'Company', required=True)
    property = fields.Many2One('real_estate.base_object', 'Property',
        domain=[
            ('type', '=', 'property'),
            ('company', '=', Eval('company', -1)),
        ])
    billing_unit = fields.Many2One('real_estate.billing_unit', 'Billing Unit',
        domain=[
            If(Eval('property', None),
                [('property', '=', Eval('property', None))],
                []),
        ])
    settlement_unit = fields.Many2One('real_estate.settlement_unit',
        'Settlement Unit',
        domain=[
            If(Eval('billing_unit', None),
                [('billing_unit', '=', Eval('billing_unit', None))],
                []),
        ])
    base_object = fields.Many2One('real_estate.base_object', 'Object',
        domain=[
            ('type', '=', 'object'),
            If(Eval('property', None),
                [('property', '=', Eval('property', None))],
                []),
        ])
    contract = fields.Many2One('real_estate.contract', 'Contract',
        domain=[
            ('company', '=', Eval('company', -1)),
            If(Eval('property', None),
                [('property', '=', Eval('property', None))],
                []),
        ])
    from_date = fields.Date('From Date')
    to_date = fields.Date('To Date')

    @classmethod
    def default_company(cls):
        return Transaction().context.get('company')

    @classmethod
    def default_from_date(cls):
        today = Pool().get('ir.date').today()
        return today.replace(month=1, day=1)

    @classmethod
    def default_to_date(cls):
        today = Pool().get('ir.date').today()
        return today.replace(month=12, day=31)
    
#**********************************************************************
class SettlementResultContext(ModelView):
    'Settlement Result Context'
    __name__ = 'real_estate.settlement_result.context'

    company = fields.Many2One('company.company', 'Company', required=True)
    property = fields.Many2One('real_estate.base_object', 'Property',
        domain=[
            ('type', '=', 'property'),
            ('company', '=', Eval('company', -1)),
        ])
    billing_unit = fields.Many2One('real_estate.billing_unit', 'Billing Unit',
        domain=[
            If(Eval('property', None),
                [('property', '=', Eval('property', None))],
                []),
        ])
    contract = fields.Many2One('real_estate.contract', 'Contract',
        domain=[
            ('company', '=', Eval('company', -1)),
            If(Eval('property', None),
                [('property', '=', Eval('property', None))],
                []),
        ])
    base_object = fields.Many2One('real_estate.base_object', 'Object',
        domain=[
            ('type', '=', 'object'),
            If(Eval('property', None),
                [('property', '=', Eval('property', None))],
                []),
        ])
    from_date = fields.Date('From Date')
    to_date = fields.Date('To Date')

    @classmethod
    def default_company(cls):
        return Transaction().context.get('company')

    @classmethod
    def default_from_date(cls):
        today = Pool().get('ir.date').today()
        return today.replace(month=1, day=1)

    @classmethod
    def default_to_date(cls):
        today = Pool().get('ir.date').today()
        return today.replace(month=12, day=31)

 #**********************************************************************
class SettlementResult(ModelSQL, ModelView):
    """Settlement Result, e.g. result of cost allocation for a specific cost type and period within a billing unit, used for reporting and invoicing."""
    __name__ = 'real_estate.settlement_result'
    __rec_name__ = 'name'

    billing_unit = fields.Many2One('real_estate.billing_unit', 'Billing Unit', required=True, ondelete='CASCADE',)

    term = fields.Many2One('real_estate.contract.term', 'Term',
        ondelete='SET NULL',
        states={'readonly': True},
        )

    name = fields.Function(fields.Char('Name'), 'on_change_with_name',
        searcher='search_name')

    state = fields.Selection([
            ('approved', 'Approved'),
            ('billed', 'Billed'),
            ], "State", sort=False,
            states={ 'readonly': True, },
            )
    
    start_date = fields.Date('Start Date', 
         states={
        'readonly': True,},
        )
    
    end_date = fields.Date('End Date', 
         states={
        'readonly': True,},
        )
    
    contract = fields.Many2One('real_estate.contract', 'Contract', ondelete='CASCADE',
        states={
            'readonly': True,},
        )
    
    base_object = fields.Many2One('real_estate.base_object', 'Object', ondelete='CASCADE',
        domain=[('type', '=', 'object')],
        states={
            'readonly': True,},        
        )
    
    planned_costs = Monetary('Planned Costs', currency='currency', digits= 'currency',#(16, 2),
        states={
            'readonly': True,},
        )
    
    actual_costs = Monetary('Actual Costs', currency='currency', digits= 'currency',#(16, 2),
        states={
            'readonly': True,},
        )

    advanced_payment = Monetary('Advanced Payment', currency='currency', digits='currency',
        states={ 
            'readonly': True,},
        )

    refund_receivable = Monetary('Refund/Receivable', currency='currency', digits='currency',
        states={ 
            'readonly': True,},
        )

    currency = fields.Function(fields.Many2One('currency.currency', 'Currency',), 'on_change_with_currency') 


    @fields.depends('start_date', 'end_date', 'contract', 'base_object')
    def on_change_with_name(self, name=None):
        date_part = (
            f"{self.start_date:%Y-%m-%d}" if self.start_date else '?'
        ) + ' - ' + (
            f"{self.end_date:%Y-%m-%d}" if self.end_date else '?'
        )
        if self.contract:
            return f"{date_part} / {self.contract.rec_name}"
        elif self.base_object:
            return f"{date_part} / {self.base_object.rec_name}"
        return date_part

    @classmethod
    def search_name(cls, name, clause):
        _, operator, value = clause
        return ['OR',
            ('contract', operator, value),
            ('base_object.name', operator, value),
        ]    
    
    @staticmethod
    def default_state():
        return 'approved'

    @fields.depends('billing_unit')
    def on_change_with_currency(self, name=None):
        return self.billing_unit.currency if self.billing_unit else None


