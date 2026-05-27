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

    contract = fields.Function(
        fields.Many2One('real_estate.contract', 'Contract'),
        'on_change_with_contract'
    )

    term = fields.Many2One(
        'real_estate.contract.term', 'Term',
        states={'readonly': Eval('invoice_state') != 'draft'},
        domain=[
            If(Bool(Eval('contract')),
                ('contract', '=', Eval('contract', -1)),
                ()),
        ]
    )

    property = fields.Many2One(
        'real_estate.base_object', 'Property',
        domain=[
            ('type', '=', 'property'),
            If(Bool(Eval('company')),
                ('company', '=', Eval('company', -1)),
                ()),
        ]
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

    settlement_unit = fields.Many2One(
        'real_estate.settlement_unit', 'Settlement Unit',
        domain=[
            If(Bool(Eval('property')),
                ('billing_unit.property', '=', Eval('property', -1)),
                ()),
            ('billing_unit.state', 'not in', ['draft', 'billed']),
        ]
    )

    service_period_from = fields.Date(
        'Service Period From',
        domain=[
            If(Bool(Eval('service_period_from')) & Bool(Eval('service_period_to')),
                ('service_period_from', '<=', Eval('service_period_to')),
                ()),
        ]
    )

    service_period_to = fields.Date(
        'Service Period To',
        domain=[
            If(Bool(Eval('service_period_from')) & Bool(Eval('service_period_to')),
                ('service_period_to', '>=', Eval('service_period_from')),
                ()),
        ]
    )

    estg_35a = fields.Selection([
        ('', ''),
        ('abs1', 'Abs. 1 - Minijob im Haushalt'),
        ('abs2', 'Abs. 2 - Haushaltsnahe Dienstleistungen (z.B. Gartenpflege)'),
        ('abs3', 'Abs. 3 - Handwerkerleistungen (z.B. Schornsteinfeger)'),
    ], '§35a EStG',
        sort=False,
    )

    @classmethod
    def __setup__(cls):
        super(InvoiceLine, cls).__setup__()
        table = cls.__table__()
        cls._sql_indexes.add(
            Index(table,
                (Column(table, 'term'), Index.Range(order='ASC NULLS FIRST')),
                (table.id, Index.Range(order='ASC NULLS FIRST'))))
        cls._sql_indexes.add(
            Index(table,
                (Column(table, 'settlement_unit'), Index.Range(order='ASC NULLS FIRST')),
                (table.id, Index.Range(order='ASC NULLS FIRST'))))

    @fields.depends('invoice')
    def on_change_with_invoice_date(self, name=None):
        if self.invoice:
            return self.invoice.invoice_date
        return None

    @fields.depends('taxes', 'unit_price', 'quantity', 'taxes_date', 'invoice')
    def on_change_with_tax_amount(self, name=None):
        if not self.taxes:
            return Decimal(0)
        Tax = Pool().get('account.tax')
        date = (self.taxes_date
            or (self.invoice.invoice_date if self.invoice else None))
        tax_list = Tax.compute(
            list(self.taxes),
            self.unit_price or Decimal(0),
            self.quantity or Decimal(0),
            date)
        total = sum(t['amount'] for t in tax_list)
        if self.invoice and self.invoice.currency:
            total = self.invoice.currency.round(total)
        return total

    @fields.depends('amount', 'taxes', 'unit_price', 'quantity', 'taxes_date', 'invoice')
    def on_change_with_total_amount(self, name=None):
        amount = self.amount or Decimal(0)
        tax_amount = self.on_change_with_tax_amount() or Decimal(0)
        return amount + tax_amount

    @fields.depends('invoice')
    def on_change_with_contract(self, name=None):
        if self.invoice and hasattr(self.invoice, 'contract'):
            return self.invoice.contract
        return None

    @classmethod
    def validate(cls, lines):
        super().validate(lines)
        for line in lines:
            if (line.service_period_from and line.service_period_to
                    and line.service_period_from > line.service_period_to):
                raise ValueError(
                    f'Service period from ({line.service_period_from})'
                    f' must be before to ({line.service_period_to})')