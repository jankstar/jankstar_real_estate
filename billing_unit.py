'Billing Unit'
from trytond.model import (sequence_ordered,
    DeactivableMixin, ModelSQL, ModelView, Workflow, fields)
from trytond.model.exceptions import ValidationError
from trytond.i18n import gettext
from trytond.pool import Pool
from trytond.transaction import Transaction
from trytond.pyson import Bool, Eval, If
from trytond.modules.currency.fields import Monetary

from dateutil.relativedelta import relativedelta

import datetime
from decimal import Decimal, ROUND_HALF_UP

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
class BillingUnit(Workflow, DeactivableMixin, sequence_ordered(), ModelSQL, ModelView):
    """Billing Unit, e.g. operating cost settlement for a year, WEG annual statement, etc."""
    __name__ = 'real_estate.billing_unit'
    __rec_name__ = 'name'

    company = fields.Function(fields.Many2One('company.company', 'Company'),
        'on_change_with_company')

    property = fields.Many2One('real_estate.base_object',
        "Property", required=True, path='path', ondelete='CASCADE',
        states={
            'readonly': Eval('state') != 'draft',
            },
        domain=[
            ('type', '=', 'property'),],)

    collective_billing = fields.Function(fields.Boolean('Collective Billing'),
        'on_change_with_collective_billing')

    start_date = fields.Date('Start Date',
        states={
            'readonly': ((Eval('state') != 'draft')),
            },
        required=True,
        domain=[If(Bool(Eval('end_date')), ('start_date', '<=', Eval('end_date', None)), ())],
        )

    end_date = fields.Function(fields.Date('End Date'), 'on_change_with_end_date')

    calculation_method = fields.Selection([
        ('rental_apartment', 'Rental Apartment'),
        ('WEG_billing', 'WEG Billing'),
        ], "Calculation Method", sort=False,
        states={'readonly': Eval('state') != 'draft'},
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
        states={'readonly': Eval('state') != 'draft'},
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

    planned_costs = fields.Function(Monetary('Planned Costs', currency='currency', digits='currency'),
        'on_change_with_planned_costs')

    currency = fields.Function(fields.Many2One('currency.currency', 'Currency'), 'on_change_with_currency')

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
            )

    sub_state = fields.Function(fields.Selection('get_sub_states', "Sub State"), 'on_change_with_sub_state')

    term_types_of_use = fields.MultiSelection(
            'get_term_types_of_use', "Term Types",
            help="The term type which can use this billing unit.")

    settlement_units = fields.One2Many('real_estate.settlement_unit', 'billing_unit', 'Settlement Units',
            states={'readonly': Eval('state') != 'draft'},
            )

    invoice_lines = fields.Function(fields.One2Many('account.invoice.line', None, 'Invoice Lines'),
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
        if self.calculation_method == 'WEG_billing' and (self.start_date.month != 1 or self.start_date.day != 1):
            raise InvalidCalculationMethod(gettext("real_estate.msg_invalid_calculation_method").format(
                self.start_date))

    @fields.depends('start_date')
    def on_change_with_end_date(self, name=None):
        if self.start_date:
            return self.start_date - relativedelta(days=1) + relativedelta(years=1)
        return None

    @fields.depends(methods=['_check_calculation_method_notify'])
    def on_change_notify(self):
        notifications = super().on_change_notify()
        notifications.extend(self._check_calculation_method_notify())
        return notifications

    @fields.depends('calculation_method', 'start_date')
    def _check_calculation_method_notify(self):
        if self.calculation_method == 'WEG_billing' and (self.start_date.month != 1 or self.start_date.day != 1):
            logger.warning(f"Invalid calculation method for billing unit {self.id}: start date {self.start_date} is not the first day of the year.")
            yield ('warning',
                   gettext("real_estate.msg_invalid_calculation_method").format(
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
