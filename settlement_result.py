'Settlement Result'
from trytond.model import (
    DeactivableMixin, ModelSQL, ModelView, fields)
from trytond.pool import Pool
from trytond.transaction import Transaction
from trytond.pyson import Bool, Eval, If
from trytond.modules.currency.fields import Monetary

from decimal import Decimal


#**********************************************************************
class CostShare(DeactivableMixin, ModelSQL, ModelView):
    """Cost Share, e.g. share of a specific cost type and period allocated to a specific contract or object."""
    __name__ = 'real_estate.cost_share'
    __rec_name__ = 'name'

    settlement_unit = fields.Many2One('real_estate.settlement_unit', 'Settlement Unit', required=True, ondelete='CASCADE',
                                      states={'readonly': True},)

    name = fields.Function(fields.Char('Name'), 'on_change_with_name',
        searcher='search_name')

    state = fields.Selection([
            ('preparation', 'Preparation'),
            ('selection', 'Selection'),
            ('estimated_value_share', 'Estimated Value Share'),
            ('value_share', 'Value Share'),
            ('no_allocation', 'No Allocation'),
            ('error', 'Error'),
            ], "State", sort=False,
            states={'readonly': True},
            )

    start_date = fields.Date('Start Date',
        states={'readonly': True})

    end_date = fields.Date('End Date',
        states={'readonly': True})

    contract = fields.Many2One('real_estate.contract', 'Contract', ondelete='CASCADE',
        states={'readonly': True})

    base_object = fields.Many2One('real_estate.base_object', 'Object', ondelete='CASCADE',
        domain=[('type', '=', 'object')],
        states={'readonly': True})

    allocation_rule = fields.Function(
        fields.Selection('get_allocation_rules', 'Allocation Rule'),
        'on_change_with_allocation_rule')

    value_share = fields.Float('Value Share', digits=(16, 4),
        states={'readonly': True},)

    time_share = fields.Function(fields.Integer('Time Share (days)'),
        'on_change_with_time_share')

    external_billing = fields.Function(
        fields.Boolean('External Billing'),
        'on_change_with_external_billing')

    planned_costs = Monetary('Planned Costs', currency='currency', digits='currency',
        states={'readonly': ~Eval('external_billing', False)})

    actual_costs = Monetary('Actual Costs', currency='currency', digits='currency',
        states={'readonly': ~Eval('external_billing', False)})

    currency = fields.Function(fields.Many2One('currency.currency', 'Currency'), 'on_change_with_currency')

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

    @staticmethod
    def get_allocation_rules():
        pool = Pool()
        SettlementUnit = pool.get('real_estate.settlement_unit')
        return SettlementUnit.fields_get(
            ['allocation_rule'])['allocation_rule']['selection']

    @fields.depends('settlement_unit', '_parent_settlement_unit.allocation_rule')
    def on_change_with_allocation_rule(self, name=None):
        return self.settlement_unit.allocation_rule if self.settlement_unit else None

    @fields.depends('settlement_unit', '_parent_settlement_unit.allocation_rule')
    def on_change_with_external_billing(self, name=None):
        if self.settlement_unit:
            return self.settlement_unit.allocation_rule == 'allocation_from_external_billing'
        return False

    @fields.depends('settlement_unit', '_parent_settlement_unit.currency')
    def on_change_with_currency(self, name=None):
        return self.settlement_unit.currency if self.settlement_unit else None

    @fields.depends('start_date', 'end_date')
    def on_change_with_time_share(self, name=None):
        if self.start_date and self.end_date:
            return (self.end_date - self.start_date).days + 1
        return None

#++********************************************************************
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

    billing_unit = fields.Many2One('real_estate.billing_unit', 'Billing Unit', required=True, ondelete='CASCADE')

    billing_unit_external_billing = fields.Function(
        fields.Boolean('External Billing'),
        'on_change_with_billing_unit_external_billing')

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
            states={'readonly': True},
            )

    start_date = fields.Date('Start Date',
        states={'readonly': True})

    end_date = fields.Date('End Date',
        states={'readonly': True})

    contract = fields.Many2One('real_estate.contract', 'Contract', ondelete='CASCADE',
        states={'readonly': True})

    base_object = fields.Many2One('real_estate.base_object', 'Object', ondelete='CASCADE',
        domain=[('type', '=', 'object')],
        states={'readonly': True})

    planned_costs = Monetary('Planned Costs', currency='currency', digits='currency',
        states={'readonly': ~Eval('billing_unit_external_billing', False)},
        depends=['billing_unit_external_billing'])

    actual_costs = Monetary('Actual Costs', currency='currency', digits='currency',
        states={'readonly': ~Eval('billing_unit_external_billing', False)},
        depends=['billing_unit_external_billing'])

    advanced_payment = Monetary('Advanced Payment', currency='currency', digits='currency',
        states={'readonly': True})

    refund_receivable = Monetary('Refund/Receivable', currency='currency', digits='currency',
        states={'readonly': True})

    invoice = fields.Many2One('account.invoice', 'Invoice',
        ondelete='SET NULL',
        states={'readonly': True})

    currency = fields.Function(fields.Many2One('currency.currency', 'Currency'), 'on_change_with_currency')

    bved_state = fields.Selection([
            ('', ''),
            ('awaiting_import', 'Awaiting Import'),
            ('imported', 'Imported'),
            ('validated', 'Validated'),
            ('validation_error', 'Validation Error'),
            ], "BVED State", sort=False,
        states={'readonly': Eval('state') == 'billed'},
        depends=['state'],
        help="Progress of the BVED data exchange for this result - "
             "separate from 'state' (approved/billed), which tracks the "
             "invoicing workflow, not the data exchange. Manually "
             "editable until this result is billed - e.g. to override a "
             "plausibility check false positive (see apply()'s advance-"
             "payment check) without waiting for a re-import.")

    bved_import_date = fields.DateTime("BVED Import Date", readonly=True)

    bved_check_message = fields.Text("BVED Check Message", readonly=True)

    bved_import_line = fields.Many2One(
        'real_estate.bved.import.line', "BVED Import Line",
        ondelete='SET NULL', readonly=True,
        help="The D-Satz import line that last wrote actual_costs here.")

    bved_matched_lines = fields.Function(
        fields.One2Many('real_estate.bved.import.line', None,
            "BVED Lines", readonly=True),
        'on_change_with_bved_matched_lines')

    bved_e835_lines = fields.Function(
        fields.One2Many('real_estate.bved.import.line', None, "E835 Lines",
            readonly=True),
        'on_change_with_bved_e835_lines')

    bved_p_lines = fields.Function(
        fields.One2Many('real_estate.bved.import.line', None, "P-Satz Lines",
            readonly=True),
        'on_change_with_bved_p_lines')

    bved_e835_labor_share_user_total = fields.Function(
        Monetary("E835 Labor Share (User)", currency='currency',
            digits='currency'),
        'on_change_with_bved_e835_labor_share_user_total')

    bved_p_user_amount_total = fields.Function(
        Monetary("P-Satz User Amount", currency='currency',
            digits='currency'),
        'on_change_with_bved_p_user_amount_total')

    @fields.depends('start_date', 'end_date', 'contract', 'base_object', 'id')
    def on_change_with_name(self, name=None):
        date_part = (
            f"{self.start_date:%Y-%m-%d}" if self.start_date else '?'
        ) + ' - ' + (
            f"{self.end_date:%Y-%m-%d}" if self.end_date else '?'
        )
        if self.contract:
            return f"{date_part} / {self.contract.rec_name} ({self.id})"
        elif self.base_object:
            return f"{date_part} / {self.base_object.rec_name} ({self.id})"
        return f"{date_part} ({self.id})"

    @classmethod
    def search_name(cls, name, clause):
        _, operator, value = clause
        return ['OR',
            ('contract', operator, value),
            ('base_object.name', operator, value),
            ('id', operator, value),
        ]

    @staticmethod
    def default_state():
        return 'approved'

    @fields.depends('billing_unit', '_parent_billing_unit.currency')
    def on_change_with_currency(self, name=None):
        return self.billing_unit.currency if self.billing_unit else None

    @fields.depends('billing_unit', '_parent_billing_unit.external_billing')
    def on_change_with_billing_unit_external_billing(self, name=None):
        if self.billing_unit:
            return bool(self.billing_unit.external_billing)
        return False

    @fields.depends('actual_costs', 'advanced_payment')
    def on_change_actual_costs(self):
        if self.actual_costs is not None and self.advanced_payment is not None:
            self.refund_receivable = self.actual_costs - self.advanced_payment
        elif self.actual_costs is not None:
            self.refund_receivable = self.actual_costs

    def _bved_lines(self, record_type=None):
        if not self.id:
            return []
        ImportLine = Pool().get('real_estate.bved.import.line')
        domain = [('matched_settlement_result', '=', self.id)]
        if record_type:
            domain.append(('record_type', '=', record_type))
        return ImportLine.search(
            domain, order=[('record_type', 'ASC'), ('sequence', 'ASC')])

    @fields.depends('id')
    def on_change_with_bved_e835_lines(self, name=None):
        return self._bved_lines('E835')

    @fields.depends('id')
    def on_change_with_bved_p_lines(self, name=None):
        return self._bved_lines('P')

    @fields.depends('id')
    def on_change_with_bved_matched_lines(self, name=None):
        """All import lines matched to this result, across every record
        type (D/E835/E898/P) and state - not just the informational E835/
        P ones with a dedicated rollup, so the user can see the full set
        of what Match found, including a not-yet-applied D-Satz line."""
        return self._bved_lines()

    @fields.depends('id', methods=['on_change_with_bved_e835_lines'])
    def on_change_with_bved_e835_labor_share_user_total(self, name=None):
        lines = self.on_change_with_bved_e835_lines()
        return sum(
            (line.user_share_amount or Decimal(0) for line in lines),
            Decimal(0))

    @fields.depends('id', methods=['on_change_with_bved_p_lines'])
    def on_change_with_bved_p_user_amount_total(self, name=None):
        lines = self.on_change_with_bved_p_lines()
        return sum(
            (line.p_user_share_gross or Decimal(0) for line in lines),
            Decimal(0))
