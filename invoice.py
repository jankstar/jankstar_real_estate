from decimal import Decimal

from sql import Column

from trytond.model import Index, ModelSQL, fields
from trytond.modules.currency.fields import Monetary
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Bool, Eval, If


class Invoice(metaclass=PoolMeta):
    """Invoice extension for real estate"""
    __name__ = 'account.invoice'

    contract = fields.Many2One('real_estate.contract', 'Contract',
        states={
            'readonly': Eval('state') != 'draft',
            },
        domain=[
            ('company', '=', Eval('company', -1)),
            ]          
        )  # CODE COMMENT: Link to the real estate contract
    
    @classmethod
    def __setup__(cls):
        super(Invoice, cls).__setup__()
        table = cls.__table__()
        cls._sql_indexes.add(
            Index(table,
                (Column(table, 'contract'), Index.Range(order='ASC NULLS FIRST')),
                (table.id, Index.Range(order='ASC NULLS FIRST'))))  


#**********************************************************************
class InvoiceLine(metaclass=PoolMeta):
    """Invoice Line extension for real estate"""
    __name__ = 'account.invoice.line'

    assignment_control = fields.Selection([
            ('', 'All'),
            ('contract', 'Contract'),
            ('operating_costs', 'Operating Costs'),
            ('settlement_result_contract', 'Settlement Result Contract'),
            ('settlement_result_vacant', 'Settlement Result Vacant'),
        ], 'Account Assignment Control',
        sort=False,
    )

    contract = fields.Many2One(
        'real_estate.contract', 'Contract',
        states={
            'readonly': Eval('invoice_state') != 'draft',
            'invisible': Eval('assignment_control', '').in_(
                ['operating_costs', 'settlement_result_vacant']),
        },
        depends=['assignment_control'],
        domain=[
            If(Bool(Eval('company')),
                ('company', '=', Eval('company', -1)),
                ()),
        ]
    )

    term = fields.Many2One(
        'real_estate.contract.term', 'Term',
        states={
            'readonly': Eval('invoice_state') != 'draft',
            'invisible': Eval('assignment_control', '').in_(
                ['operating_costs', 'settlement_result_vacant']),
        },
        depends=['assignment_control'],
        domain=[
            If(Bool(Eval('contract')),
                ('contract', '=', Eval('contract', -1)),
                ()),
        ]
    )

    base_object = fields.Many2One(
        'real_estate.base_object', 'Object',
        depends=['assignment_control'],
        domain=[
            If(Bool(Eval('company')),
                ('company', '=', Eval('company', -1)),
                ()),
        ]
    )

    property = fields.Function(
        fields.Many2One('real_estate.base_object', 'Property'),
        'on_change_with_property'
    )

    invoice_date = fields.Function(
        fields.Date('Invoice Date'),
        'on_change_with_invoice_date'
    )

    tax_amount = fields.Function(
        Monetary('Tax Amount', currency='currency', digits='currency'),
        'on_change_with_tax_amount'
    )

    total_amount = fields.Function(
        Monetary('Total Amount', currency='currency', digits='currency'),
        'on_change_with_total_amount'
    )

    billing_unit = fields.Many2One(
        'real_estate.billing_unit', 'Billing Unit',
        states={
            'invisible': Eval('assignment_control', '').in_(
                ['contract', 'operating_costs']),
        },
        depends=['assignment_control'],
        domain=[
            If(Bool(Eval('property')),
                ('property', '=', Eval('property', -1)),
                ()),
        ]
    )

    settlement_unit = fields.Many2One(
        'real_estate.settlement_unit', 'Settlement Unit',
        states={
            'invisible': Eval('assignment_control', '').in_(
                ['contract', 'settlement_result_contract',
                    'settlement_result_vacant']),
        },
        depends=['assignment_control'],
        domain=[
            If(Bool(Eval('billing_unit')),
                ('billing_unit', '=', Eval('billing_unit', -1)),
                If(Bool(Eval('property')),
                    ('billing_unit.property', '=', Eval('property', -1)),
                    ())),
            ('billing_unit.state', 'not in', ['draft', 'billed']),
        ]
    )

    service_period_from = fields.Date(
        'Service Period From',
        states={
            'invisible': Eval('assignment_control', '').in_(
                ['contract', 'settlement_result_contract',
                    'settlement_result_vacant']),
        },
        depends=['assignment_control'],
        domain=[
            If(Bool(Eval('service_period_from')) & Bool(Eval('service_period_to')),
                ('service_period_from', '<=', Eval('service_period_to')),
                ()),
        ]
    )

    service_period_to = fields.Date(
        'Service Period To',
        states={
            'invisible': Eval('assignment_control', '').in_(
                ['contract', 'settlement_result_contract',
                    'settlement_result_vacant']),
        },
        depends=['assignment_control'],
        domain=[
            If(Bool(Eval('service_period_from')) & Bool(Eval('service_period_to')),
                ('service_period_to', '>=', Eval('service_period_from')),
                ()),
        ]
    )

    estg_35a = fields.Selection([
        ('', 'none'),
        ('abs1', 'Para. 1 - Minor Employment in the Household'),
        ('abs2', 'Para. 2 - Household-Related Services (e.g. Garden Maintenance)'),
        ('abs3', 'Para. 3 - Craftsmen Services (e.g. Chimney Sweep)'),
    ], '§35a EStG',
        sort=False,
        states={
            'invisible': Eval('assignment_control', '').in_(
                ['contract', 'settlement_result_contract',
                    'settlement_result_vacant']),
        },
        depends=['assignment_control'],
    )

    @classmethod
    def default_assignment_control(cls):
        return ''

    @classmethod
    def default_estg_35a(cls):
        return ''

    @classmethod
    def __setup__(cls):
        super(InvoiceLine, cls).__setup__()
        table = cls.__table__()
        cls._sql_indexes.add(
            Index(table,
                (Column(table, 'contract'), Index.Range(order='ASC NULLS FIRST')),
                (table.id, Index.Range(order='ASC NULLS FIRST'))))
        cls._sql_indexes.add(
            Index(table,
                (Column(table, 'term'), Index.Range(order='ASC NULLS FIRST')),
                (table.id, Index.Range(order='ASC NULLS FIRST'))))
        cls._sql_indexes.add(
            Index(table,
                (Column(table, 'settlement_unit'), Index.Range(order='ASC NULLS FIRST')),
                (table.id, Index.Range(order='ASC NULLS FIRST'))))
        cls._sql_indexes.add(
            Index(table,
                (Column(table, 'billing_unit'), Index.Range(order='ASC NULLS FIRST')),
                (table.id, Index.Range(order='ASC NULLS FIRST'))))

    @fields.depends('billing_unit', 'settlement_unit', 'term', 'base_object')
    def on_change_with_property(self, name=None):
        if self.billing_unit and self.billing_unit.property:
            return self.billing_unit.property
        if self.settlement_unit and self.settlement_unit.billing_unit:
            return self.settlement_unit.billing_unit.property
        if self.term and self.term.property:
            return self.term.property
        if self.base_object:
            if self.base_object.type == 'property':
                return self.base_object
            if self.base_object.property:
                return self.base_object.property
        return None

    @fields.depends('invoice')
    def on_change_with_invoice_date(self, name=None):
        if self.invoice:
            return getattr(self.invoice, 'invoice_date', None)
        return None

    @fields.depends('taxes', 'unit_price', 'quantity', 'taxes_date', 'invoice')
    def on_change_with_tax_amount(self, name=None):
        if not self.taxes:
            return Decimal(0)
        Tax = Pool().get('account.tax')
        date = (self.taxes_date
            or (getattr(self.invoice, 'invoice_date', None)
                if self.invoice else None))
        if date is None:
            return Decimal(0)
        tax_list = Tax.compute(
            list(self.taxes),
            self.unit_price or Decimal(0),
            self.quantity or Decimal(0),
            date)
        total = sum(t['amount'] for t in tax_list)
        currency = getattr(self.invoice, 'currency', None) if self.invoice else None
        if currency:
            total = currency.round(total)
        return total

    @fields.depends('amount', 'taxes', 'unit_price', 'quantity', 'taxes_date', 'invoice')
    def on_change_with_total_amount(self, name=None):
        amount = self.amount or Decimal(0)
        tax_amount = self.on_change_with_tax_amount() or Decimal(0)
        return amount + tax_amount

    @fields.depends('term')
    def on_change_term(self):
        if self.term and self.term.contract:
            self.contract = self.term.contract

    def get_move_lines(self):
        lines = super().get_move_lines()
        for line in lines:
            line.contract = self.contract
            line.term = self.term
            line.base_object = self.base_object
            line.billing_unit = self.billing_unit
            line.settlement_unit = self.settlement_unit
            line.assignment_control = self.assignment_control or ''
        return lines

    @classmethod
    def validate(cls, lines):
        super().validate(lines)
        for line in lines:
            if (line.service_period_from and line.service_period_to
                    and line.service_period_from > line.service_period_to):
                raise ValueError(
                    f'Service period from ({line.service_period_from})'
                    f' must be before to ({line.service_period_to})')
            if (line.term and line.contract
                    and line.term.contract != line.contract):
                raise ValueError(
                    f'Term "{line.term.rec_name}" does not belong to'
                    f' contract "{line.contract.rec_name}".')


#**********************************************************************
class AccountMoveLine(metaclass=PoolMeta):
    """Account Move Line extension for real estate"""
    __name__ = 'account.move.line'

    assignment_control = fields.Selection([
            ('', ''),
            ('contract', 'Contract'),
            ('operating_costs', 'Operating Costs'),
            ('settlement_result_contract', 'Settlement Result Contract'),
            ('settlement_result_vacant', 'Settlement Result Vacant'),
        ], 'Account Assignment Control',
        sort=False,
    )

    contract = fields.Many2One('real_estate.contract', 'Contract',
        ondelete='SET NULL',
        states={
            'invisible': Eval('assignment_control', '').in_(
                ['operating_costs', 'settlement_result_vacant']),
        },
        depends=['assignment_control'])

    term = fields.Many2One('real_estate.contract.term', 'Term',
        ondelete='SET NULL',
        states={
            'invisible': Eval('assignment_control', '').in_(
                ['operating_costs', 'settlement_result_vacant']),
        },
        depends=['assignment_control'])

    base_object = fields.Many2One('real_estate.base_object', 'Object',
        ondelete='SET NULL',
        depends=['assignment_control'])

    billing_unit = fields.Many2One('real_estate.billing_unit', 'Billing Unit',
        ondelete='SET NULL',
        states={
            'invisible': Eval('assignment_control', '').in_(
                ['contract', 'operating_costs']),
        },
        depends=['assignment_control'])

    settlement_unit = fields.Many2One('real_estate.settlement_unit',
        'Settlement Unit', ondelete='SET NULL',
        states={
            'invisible': Eval('assignment_control', '').in_(
                ['contract', 'settlement_result_contract',
                    'settlement_result_vacant']),
        },
        depends=['assignment_control'])

    property = fields.Function(
        fields.Many2One('real_estate.base_object', 'Property'),
        'on_change_with_property')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        table = cls.__table__()
        cls._sql_indexes.add(
            Index(table,
                (Column(table, 'contract'), Index.Range(order='ASC NULLS FIRST')),
                (table.id, Index.Range(order='ASC NULLS FIRST'))))
        cls._sql_indexes.add(
            Index(table,
                (Column(table, 'billing_unit'), Index.Range(order='ASC NULLS FIRST')),
                (table.id, Index.Range(order='ASC NULLS FIRST'))))

    @fields.depends('billing_unit', 'settlement_unit', 'term', 'base_object')
    def on_change_with_property(self, name=None):
        if self.billing_unit and self.billing_unit.property:
            return self.billing_unit.property
        if self.settlement_unit and self.settlement_unit.billing_unit:
            return self.settlement_unit.billing_unit.property
        if self.term and self.term.property:
            return self.term.property
        if self.base_object:
            if self.base_object.type == 'property':
                return self.base_object
            if self.base_object.property:
                return self.base_object.property
        return None
