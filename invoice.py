from decimal import Decimal

from sql import Column

from trytond.model import Index, ModelSQL, fields
from trytond.model.exceptions import ValidationError
from trytond.exceptions import UserWarning
from trytond.i18n import gettext
from trytond.modules.currency.fields import Monetary
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Bool, Eval, If
from trytond.transaction import Transaction

from . import bved_records


class InvoiceLineBillingUnitBilledWarning(UserWarning):
    pass


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

    @classmethod
    def post(cls, invoices):
        for invoice in invoices:
            for line in invoice.lines:
                if (getattr(line, 'assignment_control', None) == 'operating_costs'
                        and getattr(line, 'billing_unit', None)
                        and line.billing_unit.state == 'billed'):
                    raise ValidationError(gettext(
                        'real_estate.msg_invoice_line_billing_unit_billed_error',
                        line=line.rec_name))
        super().post(invoices)


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
            ('settlement_result_flat_rate', 'Settlement Result Flat Rate'),
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
            'invisible': Eval('assignment_control', '') == 'contract',
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
            ['OR',
                ('id', '=', Eval('settlement_unit', -1)),
                ('billing_unit.state', '!=', 'draft')],
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
        # Deliberately no 'readonly: invoice_state != draft' - the §35a
        # classification (and its labor share below) must stay correctable
        # after posting, like base_object/billing_unit/settlement_unit.
    )

    estg_35a_labor_share_percent = fields.Numeric(
        "Labor Share (%)", digits=(5, 2),
        domain=[
            # Guarded with If/Bool: the field is optional, and an
            # unguarded '>=0'/'<=100' domain fails validation for an
            # empty (NULL) value too, since NULL never satisfies a SQL
            # comparison - only enforce the range once a value is set.
            If(Bool(Eval('estg_35a_labor_share_percent')),
                [('estg_35a_labor_share_percent', '>=', 0),
                    ('estg_35a_labor_share_percent', '<=', 100)],
                []),
            ],
        states={
            'invisible': ~Eval('estg_35a', ''),
        },
        depends=['estg_35a'],
        help="Share of this line's gross amount that is labor cost, for "
             "the §35a EStG tax certificate / BVED K-Satz field 14. "
             "Stays editable after posting, like estg_35a itself.")

    bved_fuel_type = fields.Selection(
        'get_bved_fuel_types', "BVED Fuel Type", sort=False,
        states={
            'invisible': Eval('assignment_control', '').in_(
                ['contract', 'settlement_result_contract',
                    'settlement_result_vacant']),
        },
        depends=['assignment_control'],
        help="BVED Tabelle 'B'.",
        # No readonly-after-draft clause - follows base_object/billing_unit/
        # settlement_unit, not contract/term (see invoice.py notes).
        )

    bved_fuel_quantity = fields.Numeric(
        "BVED Quantity", digits=(8, 3),
        states={
            'invisible': Eval('assignment_control', '').in_(
                ['contract', 'settlement_result_contract',
                    'settlement_result_vacant']),
        },
        depends=['assignment_control'],
        help="Delivered fuel quantity for BVED K-Satz field 10 (e.g. "
             "3500 for a 3500-liter heating oil delivery), independent of "
             "the invoice's own quantity/unit-price quantity.")

    bved_fuel_unit = fields.Function(
        fields.Char("BVED Unit"), 'on_change_with_bved_fuel_unit')

    @staticmethod
    def get_bved_fuel_types():
        return [('', '')] + bved_records.as_selection(bved_records.TABLE_B)

    @fields.depends('bved_fuel_type')
    def on_change_with_bved_fuel_unit(self, name=None):
        if self.bved_fuel_type:
            return bved_records.get_fuel_unit(self.bved_fuel_type)
        return None

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
        # Core's check_modification() (account_invoice) blocks writes to
        # any field not in _check_modify_exclude once the invoice is
        # posted/paid/cancelled. estg_35a and the BVED fuel fields must
        # stay correctable after posting (see invoice.py notes above), so
        # they need to be added here too - the view's lack of a
        # 'readonly: invoice_state != draft' state alone does not bypass
        # this deeper ORM-level guard.
        cls._check_modify_exclude |= {
            'estg_35a', 'estg_35a_labor_share_percent',
            'bved_fuel_type', 'bved_fuel_quantity',
            }

    @fields.depends(
        'billing_unit', 'settlement_unit', 'term', 'base_object',
        '_parent_billing_unit.property', '_parent_settlement_unit.billing_unit',
        '_parent_term.property', '_parent_base_object.type',
        '_parent_base_object.property')
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

    @fields.depends('invoice', '_parent_invoice.invoice_date')
    def on_change_with_invoice_date(self, name=None):
        if self.invoice:
            return getattr(self.invoice, 'invoice_date', None)
        return None

    @fields.depends(
        'taxes', 'unit_price', 'quantity', 'taxes_deductible_rate',
        'taxes_date', 'invoice', 'invoice_type',
        '_parent_invoice.invoice_date', '_parent_invoice.currency',
        '_parent_invoice.type', '_parent_invoice.company',
        methods=['_get_taxes'])
    def on_change_with_tax_amount(self, name=None):
        # Uses _get_taxes() (core) rather than Tax.compute() on the raw
        # unit_price, so the non-deductible share of the tax (folded into
        # amount via taxes_deductible_rate, see core's on_change_with_amount)
        # is not counted a second time here.
        if not self.taxes:
            return Decimal(0)
        total = sum(t.amount for t in self._get_taxes().values())
        currency = getattr(self.invoice, 'currency', None) if self.invoice else None
        if currency:
            total = currency.round(total)
        return total

    @fields.depends(
        'amount', 'taxes', 'unit_price', 'quantity', 'taxes_date', 'invoice',
        '_parent_invoice.invoice_date', '_parent_invoice.currency',
        methods=['on_change_with_tax_amount'])
    def on_change_with_total_amount(self, name=None):
        amount = self.amount or Decimal(0)
        tax_amount = self.on_change_with_tax_amount() or Decimal(0)
        return amount + tax_amount

    @fields.depends('term')
    def on_change_term(self):
        if self.term and self.term.contract:
            self.contract = self.term.contract

    @fields.depends(
        'settlement_unit', '_parent_settlement_unit.billing_unit',
        methods=['_set_taxes_deductible_rate_from_option_rate'])
    def on_change_settlement_unit(self):
        if self.settlement_unit and self.settlement_unit.billing_unit:
            self.billing_unit = self.settlement_unit.billing_unit
        self._set_taxes_deductible_rate_from_option_rate()

    @staticmethod
    def _option_rate_priority(base_object, settlement_unit, billing_unit,
            property_):
        """Pick the real-estate reference to use for the option rate
        lookup, in order of specificity: base_object, settlement_unit,
        billing_unit, property (the derived property base_object, as a
        last-resort fallback). Returns (ref_field, record) matching
        real_estate.option_rate's own reference field names, or
        (None, None) if none of the four is set."""
        if base_object:
            return 'base_object', base_object
        if settlement_unit:
            return 'settlement_unit', settlement_unit
        if billing_unit:
            return 'billing_unit', billing_unit
        if property_:
            return 'base_object', property_
        return None, None

    @fields.depends(
        'base_object', 'settlement_unit', 'billing_unit',
        'company', 'taxes_date', 'invoice', 'invoice_type',
        '_parent_base_object.option_rate_method',
        '_parent_settlement_unit.option_rate_method',
        '_parent_billing_unit.option_rate_method',
        '_parent_company.purchase_taxes_expense',
        '_parent_invoice.invoice_date', '_parent_invoice.type',
        methods=['on_change_with_property'])
    def _set_taxes_deductible_rate_from_option_rate(self):
        """Auto-fill taxes_deductible_rate from the applicable option rate
        (see _option_rate_priority), unless: the line is not a purchase
        line, or the company always books input VAT as an expense
        (purchase_taxes_expense - matches core's own on_change_company,
        which already forces the rate to 0 in that case). The contract
        field is ignored - it has no bearing on this logic."""
        invoice_type = (
            self.invoice.type if self.invoice else self.invoice_type)
        if invoice_type != 'in':
            return
        if self.company and self.company.purchase_taxes_expense:
            return
        ref_field, record = self._option_rate_priority(
            self.base_object, self.settlement_unit, self.billing_unit,
            self.on_change_with_property())
        if not record:
            return
        date = (self.taxes_date
            or (self.invoice.invoice_date if self.invoice else None)
            or Pool().get('ir.date').today())
        rate = Pool().get('real_estate.option_rate').get_current_rate_fraction(
            ref_field, record, date)
        if rate is not None:
            self.taxes_deductible_rate = rate

    @fields.depends(methods=['_set_taxes_deductible_rate_from_option_rate'])
    def on_change_base_object(self):
        self._set_taxes_deductible_rate_from_option_rate()

    @fields.depends(methods=['_set_taxes_deductible_rate_from_option_rate'])
    def on_change_billing_unit(self):
        self._set_taxes_deductible_rate_from_option_rate()

    @classmethod
    def create(cls, vlist):
        """Auto-fill taxes_deductible_rate on programmatic creation (e.g.
        proteus scripts, future automated invoice-line creation) the same
        way on_change_* does interactively - see
        _set_taxes_deductible_rate_from_option_rate for the applicable
        conditions and reference priority (the contract field is ignored).
        Never overrides a value the caller passed explicitly."""
        pool = Pool()
        BaseObject = pool.get('real_estate.base_object')
        SettlementUnit = pool.get('real_estate.settlement_unit')
        BillingUnit = pool.get('real_estate.billing_unit')
        ContractTerm = pool.get('real_estate.contract.term')
        OptionRate = pool.get('real_estate.option_rate')
        Company = pool.get('company.company')
        Invoice = pool.get('account.invoice')
        Date = pool.get('ir.date')

        vlist = [dict(values) for values in vlist]
        for values in vlist:
            if 'taxes_deductible_rate' in values:
                continue

            invoice_id = values.get('invoice')
            invoice_type = values.get('invoice_type')
            if not invoice_type and invoice_id:
                invoice_type = Invoice(invoice_id).type
            if invoice_type != 'in':
                continue

            company_id = (
                values.get('company') or Transaction().context.get('company'))
            if not company_id or Company(company_id).purchase_taxes_expense:
                continue

            base_object = (BaseObject(values['base_object'])
                if values.get('base_object') else None)
            settlement_unit = (SettlementUnit(values['settlement_unit'])
                if values.get('settlement_unit') else None)
            billing_unit = (BillingUnit(values['billing_unit'])
                if values.get('billing_unit') else None)
            property_ = None
            if (not (base_object or settlement_unit or billing_unit)
                    and values.get('term')):
                property_ = ContractTerm(values['term']).property or None

            ref_field, record = cls._option_rate_priority(
                base_object, settlement_unit, billing_unit, property_)
            if not record:
                continue

            date = values.get('taxes_date')
            if not date and invoice_id:
                date = Invoice(invoice_id).invoice_date
            if not date:
                date = Date.today()

            rate = OptionRate.get_current_rate_fraction(
                ref_field, record, date)
            if rate is not None:
                values['taxes_deductible_rate'] = rate

        return super().create(vlist)

    def get_move_lines(self):
        lines = super().get_move_lines()
        for line in lines:
            line.contract = self.contract
            line.term = self.term
            line.base_object = self.base_object
            line.billing_unit = self.billing_unit
            line.settlement_unit = self.settlement_unit
            line.assignment_control = self.assignment_control or ''
            line.bved_fuel_type = self.bved_fuel_type
            line.bved_fuel_quantity = self.bved_fuel_quantity
        return lines

    def _compute_taxes(self):
        """Work around a bug in
        account_tax_non_deductible.InvoiceLine._compute_taxes(): its
        non-deductible-flagged recomputation pass is not guarded by
        invoice_type == 'in' (unlike that module's own taxable_lines
        override), so for a sales (out) invoice line it unconditionally
        recomputes and appends a duplicate 'base' entry plus a spurious
        'tax' entry for every tax on the line - a 'tax'-type entry should
        never appear on an individual line's own move line, only on the
        invoice's aggregated tax move line. Only 'in' lines actually need
        that extra non-deductible bookkeeping, so for 'out' lines the
        bogus duplicate/'tax' entries are discarded here instead of
        touching the core/contrib module."""
        tax_lines = super()._compute_taxes()
        invoice_type = self.invoice.type if self.invoice else self.invoice_type
        if invoice_type != 'in':
            seen_taxes = set()
            deduped = []
            for tax_line in tax_lines:
                if tax_line.type != 'base' or tax_line.tax.id in seen_taxes:
                    continue
                seen_taxes.add(tax_line.tax.id)
                deduped.append(tax_line)
            tax_lines = deduped
        return tax_lines

    @classmethod
    def validate(cls, lines):
        super().validate(lines)
        pool = Pool()
        Warning = pool.get('res.user.warning')
        for line in lines:
            if (line.service_period_from and line.service_period_to
                    and line.service_period_from > line.service_period_to):
                raise ValidationError(gettext(
                    'real_estate.msg_invoice_line_service_period_invalid',
                    service_period_from=line.service_period_from,
                    service_period_to=line.service_period_to))
            if (line.term and line.contract
                    and line.term.contract != line.contract):
                raise ValidationError(gettext(
                    'real_estate.msg_invoice_line_term_contract_mismatch',
                    term=line.term.rec_name,
                    contract=line.contract.rec_name))
            if line.term and not line.contract:
                raise ValidationError(gettext(
                    'real_estate.msg_invoice_line_term_requires_contract',
                    term=line.term.rec_name))
            if line.settlement_unit and (
                    not line.billing_unit
                    or line.billing_unit != line.settlement_unit.billing_unit):
                raise ValidationError(gettext(
                    'real_estate.msg_invoice_line_settlement_unit_requires_billing_unit',
                    settlement_unit=line.settlement_unit.rec_name,
                    billing_unit=(line.settlement_unit.billing_unit.rec_name
                        if line.settlement_unit.billing_unit else '')))
            if line.base_object and line.contract:
                contract_object_ids = {
                    item_obj.object.id
                    for item in line.contract.items
                    for item_obj in item.objects
                    if item_obj.object}
                if line.base_object.id not in contract_object_ids:
                    raise ValidationError(gettext(
                        'real_estate.msg_invoice_line_object_not_in_contract',
                        object=line.base_object.rec_name,
                        contract=line.contract.rec_name))
            if (line.assignment_control == 'operating_costs'
                    and line.invoice
                    and line.invoice.state not in ('posted', 'paid')
                    and line.billing_unit
                    and line.billing_unit.state == 'billed'):
                key = Warning.format(
                    'invoice_line_billing_unit_billed', [line])
                if Warning.check(key):
                    raise InvoiceLineBillingUnitBilledWarning(key, gettext(
                        'real_estate.msg_invoice_line_billing_unit_billed_warning'))


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
            ('settlement_result_flat_rate', 'Settlement Result Flat Rate'),
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
            'invisible': Eval('assignment_control', '') == 'contract',
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

    bved_fuel_type = fields.Selection(
        'get_bved_fuel_types', "BVED Fuel Type", sort=False, readonly=True,
        help="BVED Tabelle 'B'.")

    bved_fuel_quantity = fields.Numeric(
        "BVED Quantity", digits=(8, 3), readonly=True)

    bved_fuel_unit = fields.Function(
        fields.Char("BVED Unit"), 'on_change_with_bved_fuel_unit')

    @staticmethod
    def get_bved_fuel_types():
        return [('', '')] + bved_records.as_selection(bved_records.TABLE_B)

    @fields.depends('bved_fuel_type')
    def on_change_with_bved_fuel_unit(self, name=None):
        if self.bved_fuel_type:
            return bved_records.get_fuel_unit(self.bved_fuel_type)
        return None

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
        # Same reasoning as InvoiceLine._check_modify_exclude above - core
        # (account.move.line) blocks writes to any field not listed here
        # once the move is posted.
        cls._check_modify_exclude |= {'bved_fuel_type', 'bved_fuel_quantity'}

    @fields.depends(
        'billing_unit', 'settlement_unit', 'term', 'base_object',
        '_parent_billing_unit.property', '_parent_settlement_unit.billing_unit',
        '_parent_term.property', '_parent_base_object.type',
        '_parent_base_object.property')
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


#**********************************************************************
class GeneralLedgerLine(metaclass=PoolMeta):
    """General Ledger Line extension for real estate.

    Mirrors the real-estate columns already present on ``account.move.line``
    (same field names) so that ``GeneralLedgerLine.table_query`` — which
    pulls any non-Function field straight from the move line table by name —
    picks them up automatically without an override.
    """
    __name__ = 'account.general_ledger.line'

    contract = fields.Many2One('real_estate.contract', 'Contract',
        readonly=True)

    term = fields.Many2One('real_estate.contract.term', 'Term',
        readonly=True)

    base_object = fields.Many2One('real_estate.base_object', 'Object',
        readonly=True)

    billing_unit = fields.Many2One('real_estate.billing_unit', 'Billing Unit',
        readonly=True)

    settlement_unit = fields.Many2One('real_estate.settlement_unit',
        'Settlement Unit', readonly=True)

    bved_fuel_type = fields.Selection(
        'get_bved_fuel_types', "BVED Fuel Type", sort=False, readonly=True,
        help="BVED Tabelle 'B'.")

    bved_fuel_quantity = fields.Numeric(
        "BVED Quantity", digits=(8, 3), readonly=True)

    @staticmethod
    def get_bved_fuel_types():
        return [('', '')] + bved_records.as_selection(bved_records.TABLE_B)
