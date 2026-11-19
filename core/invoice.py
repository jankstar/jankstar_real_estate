from decimal import Decimal
from itertools import groupby

from sql import Column, Literal, Null, Window
from sql.aggregate import Sum
from sql.conditionals import Case, Coalesce

from trytond import backend
from trytond.tools import sqlite_apply_types

from trytond.model import Index, ModelSQL, fields
from trytond.model.exceptions import ValidationError
from trytond.i18n import gettext
from trytond.modules.currency.fields import Monetary
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Bool, Eval, If
from trytond.transaction import Transaction


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

    def _get_move_line(self, date, amount):
        # Core builds the receivable/payable move line directly from the
        # invoice header, bypassing InvoiceLine.get_move_lines() (which
        # already copies contract onto the regular revenue/expense lines
        # below) - without this, the one line actually shown on the
        # 'Payable/Receivable Lines' list (account.type.receivable/
        # payable) never gets a contract, even though the invoice header
        # itself has one.
        line = super()._get_move_line(date, amount)
        line.contract = self.contract
        return line

    def _credit(self, **values):
        # Keep the contract on the credit note (e.g. from 'Cancel Period
        # Booking' or 'Change Partner'), so it shows up on the contract
        # and its move lines stay assigned to it - and the reference (e.g.
        # the contract number), which core does not copy
        credit = super()._credit(**values)
        credit.contract = self.contract
        if 'reference' not in values:
            credit.reference = self.reference
        return credit


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
        # the assignment of a posted line is not changed any more - the
        # operating cost assignment (oc_document) is done separately
        states={
            'readonly': Eval('invoice_state') != 'draft',
        },
    )

    contract = fields.Many2One(
        'real_estate.contract', 'Contract',
        states={
            'readonly': Eval('invoice_state') != 'draft',
            # with operating costs: cost of a rental object and its
            # contract (spezifikation-betriebskostenzuordnung.md E31)
            'invisible': Eval('assignment_control', '').in_(
                ['settlement_result_vacant']),
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
        states={
            'readonly': Eval('invoice_state') != 'draft',
        },
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

    @classmethod
    def default_assignment_control(cls):
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

    @fields.depends(
        'term', 'base_object',
        '_parent_term.property', '_parent_base_object.type',
        '_parent_base_object.property')
    def on_change_with_property(self, name=None):
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

    @staticmethod
    def _option_rate_priority(base_object, property_):
        """Pick the object to use for the option rate lookup: the booked
        base_object, else the property (the derived property base_object,
        as a fallback) - option rates are kept on objects only
        (spezifikation-betriebskostenzuordnung.md E18). Returns
        (ref_field, record) or (None, None) if neither is set."""
        if base_object:
            return 'base_object', base_object
        if property_:
            return 'base_object', property_
        return None, None

    @fields.depends(
        'base_object',
        'company', 'taxes_date', 'invoice', 'invoice_type',
        '_parent_base_object.option_rate_method',
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
            self.base_object, self.on_change_with_property())
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
            property_ = None
            if not base_object and values.get('term'):
                property_ = ContractTerm(values['term']).property or None

            ref_field, record = cls._option_rate_priority(
                base_object, property_)
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

    def _credit(self):
        # Copy the real-estate assignment onto the credit line, so the
        # reversal is booked on the same contract/term/object as the
        # original line (core only copies its own fields). origin (set by
        # core) links it to this line - used by ContractTerm.re_calc() to
        # recognise credited lines.
        line = super()._credit()
        for field in [
                'assignment_control', 'contract', 'term', 'base_object']:
            setattr(line, field, getattr(self, field))
        return line

    def get_move_lines(self):
        lines = super().get_move_lines()
        for line in lines:
            line.contract = self.contract
            line.term = self.term
            line.base_object = self.base_object
            line.assignment_control = self.assignment_control or ''
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
        for line in lines:
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
            if line.base_object and line.contract:
                contract_object_ids = {
                    obj.id
                    for item in line.contract.items
                    for obj in item.objects}
                if line.base_object.id not in contract_object_ids:
                    raise ValidationError(gettext(
                        'real_estate.msg_invoice_line_object_not_in_contract',
                        object=line.base_object.rec_name,
                        contract=line.contract.rec_name))


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
            ('oc_reclass', 'Operating Cost Reclassification'),
        ], 'Account Assignment Control',
        sort=False,
        # like the core fields: not changeable on a posted move
        states={
            'readonly': Eval('move_state') == 'posted',
        },
    )

    contract = fields.Many2One('real_estate.contract', 'Contract',
        ondelete='SET NULL',
        states={
            'readonly': Eval('move_state') == 'posted',
            'invisible': Eval('assignment_control', '').in_(
                ['settlement_result_vacant']),
        },
        depends=['assignment_control'])

    effective_contract = fields.Function(
        fields.Many2One('real_estate.contract', "Effective Contract",
            help="This line's own 'Contract' if set, else the 'Contract' "
                 "of whichever other line in the same reconciliation "
                 "group has one - so a payment line, which never gets "
                 "its own contract at booking time, is still found when "
                 "filtering/searching by contract via the invoice line "
                 "it settles."),
        'on_change_with_effective_contract',
        searcher='search_effective_contract')

    term = fields.Many2One('real_estate.contract.term', 'Term',
        ondelete='SET NULL',
        states={
            'readonly': Eval('move_state') == 'posted',
            'invisible': Eval('assignment_control', '').in_(
                ['operating_costs', 'settlement_result_vacant']),
        },
        depends=['assignment_control'])

    base_object = fields.Many2One('real_estate.base_object', 'Object',
        ondelete='SET NULL',
        states={
            'readonly': Eval('move_state') == 'posted',
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

    @fields.depends(
        'term', 'base_object',
        '_parent_term.property', '_parent_base_object.type',
        '_parent_base_object.property')
    def on_change_with_property(self, name=None):
        if self.term and self.term.property:
            return self.term.property
        if self.base_object:
            if self.base_object.type == 'property':
                return self.base_object
            if self.base_object.property:
                return self.base_object.property
        return None

    @fields.depends('contract', 'reconciliation',
        '_parent_reconciliation.lines')
    def on_change_with_effective_contract(self, name=None):
        if self.contract:
            return self.contract
        if self.reconciliation:
            for line in self.reconciliation.lines:
                if line.id != self.id and line.contract:
                    return line.contract
        return None

    @classmethod
    def search_effective_contract(cls, name, clause):
        return ['OR',
            ('contract',) + tuple(clause[1:]),
            ('reconciliation.lines.contract',) + tuple(clause[1:]),
            ]

    @classmethod
    def get_payable_receivable_balance(cls, lines, name):
        """Running balance of the payable/receivable lists. Core sums all
        receivable/payable lines of the party; when the list is scoped to
        contracts (context 'payable_receivable_contracts' from the contract
        form's relate action, or 'contract' from the Contracts menu filter)
        only the lines of these contracts count - the lines with the
        contract plus the lines reconciled with them (payments), like the
        list's own effective_contract filter."""
        context = Transaction().context
        contract_ids = context.get('payable_receivable_contracts')
        if not contract_ids and context.get('contract'):
            contract_ids = [context['contract']]
        if not contract_ids:
            return super().get_payable_receivable_balance(lines, name)
        contract_ids = [int(i) for i in contract_ids]

        pool = Pool()
        Account = pool.get('account.account')
        AccountType = pool.get('account.account.type')
        Move = pool.get('account.move')
        cursor = Transaction().connection.cursor()

        line = cls.__table__()
        other = cls.__table__()
        account = Account.__table__()
        account_type = AccountType.__table__()
        move = Move.__table__()

        balances = dict.fromkeys(map(int, lines))
        date = Coalesce(line.maturity_date, move.date)
        contract_where = (fields.SQL_OPERATORS['in'](
                line.contract, contract_ids)
            | fields.SQL_OPERATORS['in'](line.reconciliation,
                other.select(other.reconciliation,
                    where=fields.SQL_OPERATORS['in'](
                        other.contract, contract_ids)
                    & (other.reconciliation != Null))))

        for company, company_lines in groupby(lines, lambda l: l.company):
            company_lines = list(company_lines)
            id2currency = {
                l.id: l.second_currency or company.currency
                for l in company_lines}
            where = (account.company == company.id) & contract_where
            where_type = Literal(False)
            if context.get('receivable', True):
                where_type |= account_type.receivable
            if context.get('payable', True):
                where_type |= account_type.payable
            where &= where_type
            if not context.get('reconciled'):
                where &= line.reconciliation == Null

            currency = Coalesce(line.second_currency, company.currency.id)
            sign = Case(
                (account_type.statement == 'income', -1),
                else_=1)
            balance = sign * Case(
                (line.amount_second_currency != Null,
                    line.amount_second_currency),
                else_=line.debit - line.credit)
            balance = Sum(balance,
                window=Window(
                    [line.party, currency],
                    order_by=[date.asc.nulls_first, line.id.desc]))

            query = (line
                .join(move, condition=line.move == move.id)
                .join(account, condition=line.account == account.id)
                .join(account_type,
                    condition=account.type == account_type.id)
                .select(line.id.as_('id'), balance.as_('balance'),
                    where=where))
            query = query.select(
                query.id, query.balance.as_('balance'),
                where=fields.SQL_OPERATORS['in'](
                    query.id, [l.id for l in company_lines]))
            if backend.name == 'sqlite':
                sqlite_apply_types(query, [None, 'NUMERIC'])
            cursor.execute(*query)
            balances.update(
                (i, id2currency[i].round(a)) for (i, a) in cursor)
        return balances


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
