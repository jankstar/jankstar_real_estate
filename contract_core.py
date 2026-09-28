'Contract Core'
from trytond.model import (sequence_ordered,
    DeactivableMixin, ModelSQL, ModelView, Workflow, fields)
from trytond.model.exceptions import ValidationError
from trytond.exceptions import UserWarning
from trytond.i18n import gettext
from trytond.pool import Pool
from trytond.transaction import Transaction
from trytond.pyson import Bool, Eval, If
from trytond import backend
from trytond.modules.currency.fields import Monetary
from trytond.modules.company.model import (
    employee_field, reset_employee, set_employee)
from trytond.tools import sqlite_apply_types
from trytond.transaction import without_check_access
from trytond.report import Report

from sql import Column, Null
from sql.aggregate import Sum, Count, Min, Max
from sql.conditionals import Coalesce
from collections import defaultdict
from itertools import groupby

from . import base_object
import logging
from decimal import Decimal
import datetime
import calendar

from trytond.modules.account.account import (
    _GeneralLedgerAccount, GeneralLedgerAccountContext)
from trytond.modules.account.common import ActivePeriodMixin

logger = logging.getLogger(__name__)

_chunk_size = 100


#**********************************************************************
class ContractLog(ModelSQL, ModelView):
    "Contract log obj"
    __name__ = 'real_estate.contract.log'

    contract = fields.Many2One('real_estate.contract', 'Contract', required=True, ondelete='CASCADE')
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

    @fields.depends('contract')
    def on_change_with_property(self, name=None):
        if self.contract and self.contract.property:
            return self.contract.property
        return None

    @fields.depends('contract')
    def on_change_with_company(self, name=None):
        if self.contract and self.contract.company:
            return self.contract.company
        return None

    @classmethod
    def search_property(cls, name, clause):
        return [('contract.property',) + tuple(clause[1:])]

    @classmethod
    def search_company(cls, name, clause):
        return [('contract.company',) + tuple(clause[1:])]


#**********************************************************************
class ContractContext(ModelView):
    'Contract Context'
    __name__ = 'real_estate.contract.context'

    company = fields.Many2One('company.company', 'Company', required=True)
    property = fields.Many2One('real_estate.base_object', 'Property',
        domain=[
            ('type', '=', 'property'),
            ('company', '=', Eval('company', -1)),
        ])
    c_type = fields.Many2One('real_estate.contract.type', 'Contract Type')

    @classmethod
    def default_company(cls):
        return Transaction().context.get('company')

#**********************************************************************
class ContractLogContext(ModelView):
    'Contract Log Context'
    __name__ = 'real_estate.contract.log.context'

    company = fields.Many2One('company.company', 'Company', required=True)
    property = fields.Many2One('real_estate.base_object', 'Property',
        domain=[
            ('type', '=', 'property'),
            ('company', '=', Eval('company', -1)),
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
        return Pool().get('ir.date').today()


#**********************************************************************
class AccountContract(ActivePeriodMixin, ModelSQL):
    """Contract Account - used to link accounts to contracts and have balance, debit, credit for the contract and party on the account"""
    __name__ = 'real_estate.contract.account_contract'
    account = fields.Many2One('account.account', "Account")
    party = fields.Many2One(
        'party.party', "Party",
        context={'company': Eval('company', -1)},
        depends={'company'})
    contract = fields.Many2One(
        'real_estate.contract', "Contract", ondelete='CASCADE',
        context={'company': Eval('company', -1)},
        depends={'company'})
    name = fields.Char("Name")
    code = fields.Char("Code")
    company = fields.Many2One('company.company', "Company")
    type = fields.Many2One('account.account.type', "Type")
    debit_type = fields.Many2One('account.account.type', "Debit Type")
    credit_type = fields.Many2One('account.account.type', "Credit Type")
    closed = fields.Boolean("Closed")

    balance = fields.Function(Monetary(
            "Balance", currency='currency', digits='currency'),
        'get_balance')
    credit = fields.Function(Monetary(
            "Credit", currency='currency', digits='currency'),
        'get_credit_debit')
    debit = fields.Function(Monetary(
            "Debit", currency='currency', digits='currency'),
        'get_credit_debit')
    amount_second_currency = fields.Function(Monetary(
            "Amount Second Currency",
            currency='second_currency', digits='second_currency',
            states={'invisible': ~Eval('second_currency')}),
        'get_credit_debit')
    line_count = fields.Function(
        fields.Integer("Line Count"), 'get_credit_debit')
    second_currency = fields.Many2One(
        'currency.currency', "Secondary Currency")

    currency = fields.Function(fields.Many2One(
            'currency.currency', "Currency"),
        'get_currency', searcher='search_currency')

    @classmethod
    def table_query(cls):
        pool = Pool()
        Line = pool.get('account.move.line')
        Account = pool.get('account.account')
        Contract = pool.get('real_estate.contract')
        LedgerAccountContext = pool.get(
            'account.general_ledger.account.context')
        # Same company scoping as core's own _GeneralLedgerAccount.
        # table_query() (account.py) - without it, this (account, party)
        # grouping could mix rows from several companies under the same
        # id whenever the same account+party pair exists in more than
        # one company, which callers reachable without an active_ids-
        # scoped domain (e.g. a standalone menu, unlike the contract
        # form's own 'form_relate' button) can genuinely encounter -
        # triggering a "row not covered by any rule" RuntimeError once
        # Tryton's own ir.rule-based access check kicks in downstream.
        context = LedgerAccountContext.get_context()
        line = Line.__table__()
        account = Account.__table__()
        contract = Contract.__table__()

        account_party = line.select(
                Min(line.id).as_('id'), line.account, line.party,
                where=line.party != Null,
                group_by=[line.account, line.party])

        # One row per party, restricted to the current company: without
        # this grouping, joining the raw 'contract' table directly (by
        # contractual_partner alone) returns one row per MATCHING contract,
        # not per party - so a party with more than one contract (e.g. a
        # follow-up contract after termination, or contracts in different
        # companies once no company filter restricts it) makes the join
        # yield several rows sharing the same account_party.id, which
        # violates the table_query() uniqueness of ids and triggers a
        # "row not covered by any rule"/"Undetected access error"
        # RuntimeError once Tryton reads those rows back downstream. Same
        # company scoping as core's own _GeneralLedgerAccount.table_query()
        # (account.py); Max(id) deterministically picks one (the most
        # recent) contract per party when more than one exists.
        contract_by_party = contract.select(
                Max(contract.id).as_('id'), contract.contractual_partner,
                where=contract.company == context.get('company'),
                group_by=[contract.contractual_partner])

        columns = []
        for fname, field in cls._fields.items():
            if not hasattr(field, 'set'):
                if fname in {'id', 'account', 'party'}:
                    column = Column(account_party, fname)
                elif fname in {'contract'}:
                    column = Column(contract_by_party, 'id')
                else:
                    column = Column(account, fname)
                columns.append(column.as_(fname))
        return (
            account_party.join(
                account, condition=account_party.account == account.id)
            .join(
                contract_by_party,
                condition=(
                    account_party.party == contract_by_party.contractual_partner))
            .select(
                *columns,
                where=account.party_required
                & (account.company == context.get('company'))))

    @classmethod
    def get_balance(cls, records, name):
        pool = Pool()
        Account = pool.get('account.account')
        MoveLine = pool.get('account.move.line')
        FiscalYear = pool.get('account.fiscalyear')
        transaction = Transaction()
        cursor = transaction.connection.cursor()

        table_a = Account.__table__()
        table_c = Account.__table__()
        line = MoveLine.__table__()
        balances = defaultdict(Decimal)

        for company, c_records in groupby(records, lambda r: r.company):
            c_records = list(c_records)
            account_ids = {a.account.id for a in c_records}
            party_ids = {a.party.id for a in c_records}
            account_party2id = {
                (a.account.id, a.party.id): a.id for a in c_records}
            with transaction.set_context(company=company.id):
                line_query, fiscalyear_ids = MoveLine.query_get(line)
            account_sql = fields.SQL_OPERATORS['in'](table_a.id, account_ids)
            party_sql = fields.SQL_OPERATORS['in'](line.party, party_ids)
            query = (table_a.join(table_c,
                    condition=(table_c.left >= table_a.left)
                    & (table_c.right <= table_a.right)
                    ).join(line, condition=line.account == table_c.id
                    ).select(
                    table_a.id,
                    line.party,
                    Sum(
                        Coalesce(line.debit, Decimal(0))
                        - Coalesce(line.credit, Decimal(0))).as_('balance'),
                    where=account_sql & party_sql & line_query,
                    group_by=[table_a.id, line.party]))
            if backend.name == 'sqlite':
                sqlite_apply_types(query, [None, None, 'NUMERIC'])
            cursor.execute(*query)
            for account_id, party_id, balance in cursor:
                try:
                    id_ = account_party2id[(account_id, party_id)]
                except KeyError:
                    continue
                balances[id_] = balance

            for record in c_records:
                balances[record.id] = record.currency.round(balances[record.id])

            fiscalyears = FiscalYear.browse(fiscalyear_ids)

            def func(records, names):
                return {names[0]: cls.get_balance(records, names[0])}
            Account._cumulate(
                fiscalyears, c_records, [name], {name: balances}, func,
                deferral=None)[name]
        return balances

    @classmethod
    def get_credit_debit(cls, records, names):
        pool = Pool()
        Account = pool.get('account.account')
        MoveLine = pool.get('account.move.line')
        FiscalYear = pool.get('account.fiscalyear')
        transaction = Transaction()
        cursor = transaction.connection.cursor()

        result = {}
        for name in names:
            if name not in {
                    'credit', 'debit', 'amount_second_currency', 'line_count'}:
                raise ValueError('Unknown name: %s' % name)
            column_type = int if name == 'line_count' else Decimal
            result[name] = defaultdict(column_type)

        table = Account.__table__()
        line = MoveLine.__table__()
        columns = [table.id, line.party]
        types = [None, None]
        for name in names:
            if name == 'line_count':
                columns.append(Count().as_(name))
                types.append(None)
            else:
                columns.append(Sum(Coalesce(Column(line, name), Decimal(0))).as_(name))
                types.append('NUMERIC')

        for company, c_records in groupby(records, key=lambda r: r.company):
            c_records = list(c_records)
            account_ids = {a.account.id for a in c_records}
            party_ids = {a.party.id for a in c_records}
            account_party2id = {
                (a.account.id, a.party.id): a.id for a in c_records}

            with transaction.set_context(company=company.id):
                line_query, fiscalyear_ids = MoveLine.query_get(line)

            account_sql = fields.SQL_OPERATORS['in'](table.id, account_ids)
            party_sql = fields.SQL_OPERATORS['in'](line.party, party_ids)
            query = (table.join(line, 'LEFT',
                    condition=line.account == table.id
                    ).select(*columns,
                    where=account_sql & party_sql & line_query,
                    group_by=[table.id, line.party]))
            if backend.name == 'sqlite':
                sqlite_apply_types(query, types)
            cursor.execute(*query)
            for row in cursor:
                try:
                    id_ = account_party2id[tuple(row[0:2])]
                except KeyError:
                    continue
                for i, name in enumerate(names, 2):
                    result[name][id_] = row[i]
            for record in c_records:
                for name in names:
                    if name == 'line_count':
                        continue
                    if (name == 'amount_second_currency'
                            and record.second_currency):
                        currency = record.second_currency
                    else:
                        currency = record.currency
                    result[name][record.id] = currency.round(result[name][record.id])

            cumulate_names = []
            if transaction.context.get('cumulate'):
                cumulate_names = names
            elif 'amount_second_currency' in names:
                cumulate_names = ['amount_second_currency']
            if cumulate_names:
                fiscalyears = FiscalYear.browse(fiscalyear_ids)
                Account._cumulate(
                    fiscalyears, c_records, cumulate_names, result,
                    cls.get_credit_debit, deferral=None)
        return result

    def get_currency(self, name):
        return self.company.currency.id

    @classmethod
    def search_currency(cls, name, clause):
        return [('company.' + clause[0], *clause[1:])]


#**********************************************************************
class GeneralLedgerAccountContract(_GeneralLedgerAccount):
    """General Ledger Account for Contract - used to link accounts to contracts and 
    have balance, debit, credit for the contract and party on the account"""
    __name__ = 'real_estate.account_contract'

    party = fields.Many2One(
        'party.party', "Party",
        context={'company': Eval('company', -1)},
        depends={'company'})

    contract = fields.Many2One(
        'real_estate.contract', "Contract",
        context={'company': Eval('company', -1)},
        depends={'company'})

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._order.insert(2, ('contract', 'ASC'))

    @classmethod
    def _get_account(cls):
        pool = Pool()
        return pool.get('real_estate.contract.account_contract')

    def get_rec_name(self, name):
        return ' - '.join((self.account.rec_name, self.contract.rec_name))

    def get_party(self, name):
        if self.contract:
            return self.contract.contractual_partner

    @classmethod
    def search_rec_name(cls, name, clause):
        if clause[1].startswith('!') or clause[1].startswith('not '):
            bool_op = 'AND'
        else:
            bool_op = 'OR'
        return [bool_op,
            ('account.rec_name',) + tuple(clause[1:]),
            ('party.rec_name',) + tuple(clause[1:]),
            ('contract.rec_name',) + tuple(clause[1:]),
            ]


class ContractGeneralLedgerAccountContractContext(GeneralLedgerAccountContext):
    """Selection panel for the standalone 'Kontenblatt' menu under Contracts
    - reuses core's own General Ledger account context (fiscalyear/period/
    date range/company/posted/journal, unchanged) and adds Party and
    Contract filters on top, translated into a domain on
    real_estate.account_contract via this action's own context_domain."""
    __name__ = 'real_estate.contract.general_ledger_account_contract.context'

    party = fields.Many2One(
        'party.party', "Party",
        context={'company': Eval('company', -1)},
        depends={'company'})
    contract = fields.Many2One(
        'real_estate.contract', "Contract",
        domain=[('company', '=', Eval('company', -1))],
        depends={'company'})


class ContractGeneralLedgerAccountContractReport(Report):
    """Prints the real_estate.account_contract rows selected in the
    'Kontenblatt' list under the Contracts menu - triggered like any other
    Tryton report (select the desired rows in the list, then Print), not
    tied to that one list's own live column/sort choices (those are
    client-side UI state, invisible to the report engine) - the printed
    columns are a fixed selection instead: Account, Party, Contract, Start
    Balance, Debit, Credit, End Balance, plus a totals row."""
    __name__ = 'real_estate.contract.general_ledger_account_contract.report'

    @classmethod
    def format_value(cls, value):
        if value is None:
            return ''
        if type(value) == str:
            return value
        if type(value) == bool:
            return str(value)
        if type(value) == int:
            return str(value)
        if type(value) == float:
            return cls.format_number(value, None, digits=2)
        if type(value) == Decimal:
            return cls.format_number(value, None, digits=2)
        if type(value) == datetime.date:
            return cls.format_date(value)
        if type(value) == datetime.datetime:
            return cls.format_datetime(value)
        return value

    @classmethod
    def _selection_summary(cls):
        """Human-readable summary of the filter panel values active when
        the list this report is printed from was last searched -
        available here because the act_window's own 'context' field
        (contract.xml) forwards the context_model's fields into the
        transaction context, on top of them already feeding
        'context_domain' to build the search domain itself."""
        pool = Pool()
        transaction_context = Transaction().context
        parts = []

        party_id = transaction_context.get('party')
        if party_id:
            Party = pool.get('party.party')
            parts.append('Partei: %s' % Party(party_id).rec_name)

        contract_id = transaction_context.get('contract')
        if contract_id:
            Contract = pool.get('real_estate.contract')
            parts.append('Vertrag: %s' % Contract(contract_id).rec_name)

        fiscalyear_id = transaction_context.get('fiscalyear')
        if fiscalyear_id:
            FiscalYear = pool.get('account.fiscalyear')
            parts.append(
                'Geschäftsjahr: %s' % FiscalYear(fiscalyear_id).rec_name)

        start_period_id = transaction_context.get('start_period')
        end_period_id = transaction_context.get('end_period')
        if start_period_id or end_period_id:
            Period = pool.get('account.period')
            parts.append('Periode: %s - %s' % (
                Period(start_period_id).rec_name if start_period_id
                else '...',
                Period(end_period_id).rec_name if end_period_id else '...'))

        date_from = transaction_context.get('from_date')
        date_to = transaction_context.get('to_date')
        if date_from or date_to:
            parts.append('Zeitraum: %s - %s' % (
                cls.format_value(date_from) if date_from else '...',
                cls.format_value(date_to) if date_to else '...'))

        journal_id = transaction_context.get('journal')
        if journal_id:
            Journal = pool.get('account.journal')
            parts.append('Journal: %s' % Journal(journal_id).rec_name)

        if transaction_context.get('posted', False):
            parts.append('nur gebuchte Bewegungen')

        return '; '.join(parts) if parts else 'keine Einschränkung'

    @classmethod
    def get_context(cls, records, header, data):
        context = super().get_context(records, header, data)
        context['format_value'] = cls.format_value
        context['lines'] = records
        context['total_start_balance'] = sum(
            (line.start_balance or Decimal(0) for line in records),
            Decimal(0))
        context['total_debit'] = sum(
            (line.debit or Decimal(0) for line in records), Decimal(0))
        context['total_credit'] = sum(
            (line.credit or Decimal(0) for line in records), Decimal(0))
        context['total_end_balance'] = sum(
            (line.end_balance or Decimal(0) for line in records),
            Decimal(0))
        context['selection_summary'] = cls._selection_summary()
        return context


class ContractCancelWarning(UserWarning):
    pass


class ContractPartyRoleWarning(UserWarning):
    pass


class ContractPartnerChangedWarning(UserWarning):
    pass


class ContractPartnerChangeDraftInvoicesWarning(UserWarning):
    pass


#**********************************************************************
class Contract(Workflow, DeactivableMixin, base_object.re_sequence_ordered(), ModelSQL, ModelView):
    "Contract - base class for contracts"
    __name__ = 'real_estate.contract'
    __rec_name__ = 'name'
    __history__ = True

    company = fields.Many2One('company.company', "Company", required=True, ondelete='CASCADE')
    property = fields.Many2One('real_estate.base_object', "Property", required=True, ondelete='CASCADE',
        states={
            'readonly': ((Eval('state') != 'draft')),
            'invisible': ((Bool(Eval('c_type')) == False)),
            },
        domain=[
            ('company', '=', Eval('company', -1)),
            ('type', '=', 'property'),],)

    # Contract type is picked first (always visible); type of use stays
    # visible too, but is only editable once a contract type is chosen AND
    # that contract type actually allows more than one type of use (see
    # c_type_multi_use/on_change_c_type below). If it allows just one,
    # that one is preset automatically and the field is readonly, since
    # there is nothing left to choose; same while no contract type is
    # chosen yet.
    type_of_use = fields.Selection('get_term_types_of_use',
        "Type of Use",
        required=True,
        sort=False,
        states={
            'readonly': (
                (Eval('state') != 'draft')
                | ~Bool(Eval('c_type'))
                | ~Eval('c_type_multi_use', False)),
            }
        )

    c_type_multi_use = fields.Function(
        fields.Boolean("Contract Type Has Multiple Types of Use"),
        'on_change_with_c_type_multi_use')

    company_re_accounting = fields.Function(
        fields.Many2One('real_estate.re_accounting', "Company Accounting"),
        'on_change_with_company_re_accounting', loading='eager')

    c_type = fields.Many2One(
        'real_estate.contract.type', "Contract Type", required=True,
        domain=[
            ('re_accounting', '=', Eval('company_re_accounting', -1)),
            ],
        states={
            'readonly': ((Eval('state') != 'draft')),
            }
        )

    currency = fields.Many2One('currency.currency', 'Currency',
        states={'readonly': True},
        required=True)

    start_date = fields.Date('Start Date',
        states={'readonly': ((Eval('state') != 'draft'))},
        required=True,
        domain=[If(Bool(Eval('end_date')), ('start_date', '<=', Eval('end_date', None)), ())],
        )

    unlimited = fields.Boolean('Unlimited Contract',
        states={'readonly': (Eval('state') != 'draft')},
        help="Unset to enter a fixed end date for this contract.")

    end_date = fields.Date('End Date',
        states={
            'readonly': (Eval('state') != 'draft') | Bool(Eval('unlimited', True)),
            'required': ~Bool(Eval('unlimited', True)),
            },
        domain=[If(Bool(Eval('end_date')), ('end_date', '>=', Eval('start_date', None)), ())],
        )

    start_booking_date = fields.Date('Start Booking Date',
        states={'readonly': ((Eval('state') != 'draft'))},
        domain=[If(Bool(Eval('end_date') & Eval('start_booking_date')), ('start_booking_date', '<=', Eval('end_date', None)), ()),
                If(Bool(Eval('start_date') & Eval('start_booking_date')), ('start_booking_date', '>=', Eval('start_date', None)), ())],
        )

    contract_number = fields.Char("No", states={'readonly': True})

    sequence = fields.Integer("Sequence", required=True,
        states={'readonly': (Eval('state') != 'draft')})

    comment = fields.Text("Comment")

    date_of_signature = fields.Date('Date of Signature')

    main_tenant_party_ids = fields.Function(
        fields.Many2Many('party.party', None, None, 'Main Tenant Party Ids'),
        'on_change_with_main_tenant_party_ids')

    contractual_partner = fields.Many2One(
        'party.party', "Contractual Partner", ondelete='CASCADE',
        states={
            'readonly': (Eval('terms', [0]) | (Eval('state') != 'draft')),
            'invisible': ~Bool(Eval('parties', [])),
            },
        domain=[('id', 'in', Eval('main_tenant_party_ids', []))],
        depends=['main_tenant_party_ids', 'parties'],
        help="Auto-filled from the party assignment list (see the "
             "'Parties' tab) with whichever party currently holds the "
             "contract type's 'Main Tenant Role', as of today (clamped to "
             "this contract's own start/end date). Can only be picked "
             "manually among parties already assigned that role there. "
             "Hidden until at least one party is assigned; whether it is "
             "actually mandatory to fill in is enforced by the 'Mandatory "
             "Role' flag on the party role itself (a warning while the "
             "contract is 'Draft', an error otherwise), not by this field "
             "directly - see ContractPartyRole.mandatory.")
    invoice_address = fields.Function(
        fields.Many2One('party.address', 'Invoice Address',
            help="Maintained on the current main tenant's row in the "
                 "'Parties' tab (real_estate.contract.party."
                 "invoice_address), not here - falls back to that "
                 "party's own default invoice address if left empty "
                 "there. See Contract.get_invoice_address."),
        'on_change_with_invoice_address')

    payment_term = fields.Many2One(
        'account.invoice.payment_term', "Payment Term",
        ondelete='RESTRICT')

    phone_partner = fields.Function(
        fields.Char("Phone Partner",
            help="Maintained on the current main tenant's row in the "
                 "'Parties' tab (real_estate.contract.party."
                 "phone_partner), not here."),
        'on_change_with_phone_partner')

    name = fields.Function(fields.Char("Name"),
        'on_change_with_name',
        searcher='name_search')

    running_by = employee_field("Running By User", states=['running'])
    terminated_by = employee_field("Terminated By User", states=['terminated'])
    cancelled_by = employee_field("Cancelled By User", states=['cancelled'])

    state = fields.Selection([
            ('draft', 'Draft'),
            ('running', 'Running'),
            ('terminated', 'Terminated'),
            ('cancelled', 'Cancelled'),
            ], "State", sort=False,
            states={'readonly': True},
            )

    items = fields.One2Many('real_estate.contract.item', 'contract', 'Items',
        order=[
            ('valid_from', 'ASC'),
            ('valid_to', 'ASC NULLS LAST'),
        ],
        states={
            'readonly': (Eval('state') != 'draft') | (Bool(Eval('c_type')) == False) | (Bool(Eval('property')) == False),
            },
        )

    next_item_sequence = fields.Function(fields.Integer("Next Item Sequence"),
        'on_change_with_next_item_sequence')

    terms = fields.One2Many('real_estate.contract.term', 'contract', 'Terms',
        order=[
            ('valid_from', 'ASC'),
            ('sequence', 'ASC NULLS FIRST'),
        ],
        states={
            'readonly': ((Eval('items', []) == []) | (Eval('state') != 'draft')),
        })

    next_term_sequence = fields.Function(fields.Integer("Next Term Sequence"),
        'on_change_with_next_term_sequence')

    current_terms_date = fields.Function(fields.Date("Key Date",
            help="Date for which the current terms are shown: today, the "
                 "contract's start date if it lies in the future, or its "
                 "(effective) end date if it lies in the past."),
        'on_change_with_current_terms_date')
    current_terms = fields.Function(fields.One2Many(
            'real_estate.contract.term', None, "Current Terms",
            readonly=True,
            help="Terms valid on the key date (valid from <= key date and "
                 "valid to empty or >= key date)."),
        'on_change_with_current_terms')

    parties = fields.One2Many('real_estate.contract.party', 'contract', 'Parties',
        order=[('valid_from', 'DESC NULLS LAST')])

    cash_flow_draft = fields.Function(
        fields.One2Many('real_estate.contract.term.cash_flow', None, 'Cash Flow draft', readonly=True),
        'on_change_with_cash_flow_draft', setter='set_cash_flow')

    cash_flow_booked = fields.One2Many('account.invoice', 'contract', 'Cash Flow Booked',
        filter=[('state', 'in', ('posted', 'paid'))],
        order=[('invoice_date', 'ASC')],
        states={'readonly': True},
        help="Booked invoices (posted or paid) for this contract. Not "
             "split by paid/open - an advance payment invoice can stay "
             "open past its own due date until the operating cost "
             "settlement resolves it, so that distinction does not "
             "reliably reflect what the tenant actually owes; see the "
             "'Payable/Receivable Lines' relate action for actual open "
             "items on the receivable/payable account.")

    meters = fields.Function(
        fields.One2Many('real_estate.base_object', None, 'Meters'),
        'on_change_with_meters', setter='set_meters')

    measurements = fields.Function(
        fields.One2Many('real_estate.measurement', None, 'Measurements'),
        'on_change_with_measurements', setter='set_measurements')

    cost_shares = fields.Function(
        fields.One2Many('real_estate.cost_share', None, 'Cost Shares', readonly=True),
        'get_cost_shares', setter='set_cost_shares')

    settlement_units = fields.Function(
        fields.One2Many('real_estate.settlement_unit', None, 'Settlement Units', readonly=True),
        'get_settlement_units', setter='set_settlement_units')

    _states_termination = {
            'invisible': ((Eval('state') != 'terminated')),
            }

    terminated_by_type = fields.Selection([
            (None, 'none'),
            ('tenant', 'Tenant'),
            ('landlord', 'Landlord'),
            ('expired', 'Expired (fixed term)'),
        ], 'Terminated by',
        states={
            'invisible': (Eval('state') != 'terminated'),
            'readonly': (Eval('state') == 'terminated'),
        })

    receipt_of_termination_notice = fields.Date('Receipt of Termination Notice',
        states={
            'invisible': (Eval('state') != 'terminated'),
            'readonly': (Eval('state') == 'terminated'),
        })

    termination_notice = fields.Selection([
            ('', 'manually'),
            ('3m', '3 Months'),
            ('6m', '6 Months'),
            ('9m', '9 Months'),
            ('12m', '12 Months'),
        ], 'Notice Period', sort=False,
        states={
            'invisible': (Eval('state') != 'terminated'),
            'readonly': (Eval('state') == 'terminated'),
        })

    termination_date = fields.Date('Termination Date',
        states={
            'invisible': (Eval('state') != 'terminated'),
            'readonly': (Eval('state') == 'terminated'),
        })

    termination_reason = fields.Char('Termination Reason',
        states={
            'invisible': (Eval('state') != 'terminated'),
            'readonly': (Eval('state') == 'terminated'),
        })

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._order.insert(0, ('contract_number', 'ASC'))
        cls._order.insert(0, ('start_date', 'ASC'))
        cls._transitions |= set((
            ('draft', 'running'),
            ('draft', 'cancelled'),
            ('running', 'terminated'),
            ('running', 'cancelled'),
            ('terminated', 'running'),
            ))
        cls._buttons.update({
            'running': {
                'invisible': (Eval('state') != 'draft'),
                'depends': ['state'],
                },
            'revert_termination': {
                'invisible': (Eval('state') != 'terminated'),
                'depends': ['state'],
                },
            'terminate': {
                'invisible': ~Eval('state').in_(['running']),
                'depends': ['state'],
                },
            'cancel': {
                'invisible': ~Eval('state').in_(['draft', 'running']),
                'depends': ['state'],
                },
            'change_partner': {
                'invisible': ~Eval('state').in_(['running', 'terminated']),
                'depends': ['state'],
                },
            'open_party_ledger': {
                'invisible': Eval('state').in_(['draft'])
                },
            })

    @classmethod
    def __register__(cls, module_name):
        table = cls.__table_handler__(module_name)
        is_new_unlimited = not table.column_exist('unlimited')

        super().__register__(module_name)

        if is_new_unlimited:
            # The column-wide default (True) applied by field-sync above
            # cannot know, per row, whether a fixed end_date was already
            # set on existing contracts - correct those explicitly here.
            cursor = Transaction().connection.cursor()
            sql_table = cls.__table__()
            cursor.execute(*sql_table.update(
                columns=[sql_table.unlimited],
                values=[False],
                where=sql_table.end_date != Null))

    @classmethod
    def validate_fields(cls, contracts, fields):
        super().validate_fields(contracts, fields)
        for contract in contracts:
            # Only enforced in draft: end_date is set to the termination
            # date on termination (see TerminateContractWizard) regardless
            # of 'unlimited', and running/terminated contracts are no
            # longer expected to satisfy this data-entry-time invariant.
            if (('unlimited' in fields or 'end_date' in fields)
                    and contract.unlimited and contract.end_date
                    and contract.state == 'draft'):
                raise ValidationError(gettext(
                    'real_estate.msg_contract_unlimited_with_end_date',
                    name=contract.rec_name))
        cls._check_party_roles(contracts)

    @staticmethod
    def _party_role_overlaps(assignments):
        """True if any two of these ContractParty records (same role,
        same contract) overlap in time - None valid_from/valid_to is
        treated as open-ended."""
        ranges = sorted(
            (cp.valid_from or datetime.date.min,
                cp.valid_to or datetime.date.max)
            for cp in assignments)
        for (_, prev_to), (next_from, _) in zip(ranges, ranges[1:]):
            if prev_to >= next_from:
                return True
        return False

    @staticmethod
    def _party_role_has_gap(assignments, start, end):
        """True if these ContractParty records (same role, same contract)
        do not cover [start, end] without gaps - end=None means the
        contract itself is open-ended, so coverage must be open-ended too
        (some assignment with valid_to=None). None valid_from is treated
        as covering from the beginning."""
        ranges = sorted(
            (cp.valid_from or datetime.date.min, cp.valid_to)
            for cp in assignments)
        cursor = start
        for from_, to_ in ranges:
            if from_ > cursor:
                return True
            if to_ is None:
                return False
            if to_ >= cursor:
                cursor = to_ + datetime.timedelta(days=1)
        return end is None or cursor <= end

    @classmethod
    def _check_party_roles(cls, contracts):
        """'Mandatory Role' and 'Only Once' checks from
        real_estate.contract.party.role - a warning while the contract is
        still 'Draft' (the user is still assembling the party list), an
        error otherwise (see ContractPartyRole.mandatory/only_once)."""
        pool = Pool()
        PartyRole = pool.get('real_estate.contract.party.role')
        Warning = pool.get('res.user.warning')

        for contract in contracts:
            by_role = defaultdict(list)
            for cp in contract.parties:
                by_role[cp.role.id].append(cp)

            roles = PartyRole.search(['OR',
                ('contract_types', '=', None),
                ('contract_types', '=',
                    contract.c_type.id if contract.c_type else -1),
            ])
            for role in roles:
                assignments = by_role.get(role.id, [])

                if role.mandatory and cls._party_role_has_gap(
                        assignments, contract.start_date,
                        contract.get_effective_end_date()):
                    message = gettext(
                        'real_estate.msg_contract_party_role_mandatory_missing',
                        contract=contract.rec_name, role=role.name)
                    if contract.state == 'draft':
                        # No records in the key on purpose: Warning.format()
                        # hashes str(records), i.e. includes the contract's
                        # own id - fine for an existing contract (write()),
                        # but during create() of a brand-new contract the
                        # first, warned attempt is rolled back and retried
                        # with the SAME values, yet gets a DIFFERENT id
                        # (PostgreSQL sequences aren't rolled back), so the
                        # confirmed key would never match on retry -
                        # confirming 'Yes' would just re-ask forever. A
                        # role-scoped (not contract-instance-scoped) key
                        # is stable across that retry and is precise enough
                        # for what is only an advisory, draft-only warning.
                        key = Warning.format(
                            f'contract_party_role_mandatory_{role.id}', [])
                        if Warning.check(key):
                            raise ContractPartyRoleWarning(key, message)
                    else:
                        raise ValidationError(message)

                if (role.only_once and len(assignments) > 1
                        and cls._party_role_overlaps(assignments)):
                    message = gettext(
                        'real_estate.msg_contract_party_role_only_once_violated',
                        contract=contract.rec_name, role=role.name)
                    if contract.state == 'draft':
                        # Same reasoning as above - no contract in the key.
                        key = Warning.format(
                            f'contract_party_role_only_once_{role.id}', [])
                        if Warning.check(key):
                            raise ContractPartyRoleWarning(key, message)
                    else:
                        raise ValidationError(message)

    @classmethod
    @ModelView.button_action(
            'real_estate.act_general_ledger_account_contract_form_contract')
    def open_party_ledger(cls, contracts):
        pass

    @classmethod
    def view_attributes(cls):
        return super().view_attributes() + [
            ('/form/notebook/page[@id="page_termination"]', 'states', cls._states_termination),
            ]

    @classmethod
    @ModelView.button
    @Workflow.transition('running')
    @set_employee('running_by')
    @reset_employee('cancelled_by', 'terminated_by')
    def running(cls, contrats):
        for contract in contrats:
            contract.add_log('state_change', f'contract state changed to running')
            contract.state = 'running'
            contract.terminated_by_type = None
            contract.receipt_of_termination_notice = None
            contract.termination_notice = ''
            contract.termination_date = None
            contract.termination_reason = None
            contract.save()

    @classmethod
    @ModelView.button
    @Workflow.transition('running')
    @reset_employee('terminated_by')
    def revert_termination(cls, contracts):
        for contract in contracts:
            contract.add_log('state_change',
                'contract termination reverted, state changed to running')
            contract.state = 'running'
            contract.terminated_by_type = None
            contract.receipt_of_termination_notice = None
            contract.termination_notice = ''
            contract.termination_date = None
            contract.termination_reason = None
            if contract.unlimited:
                contract.end_date = None
            contract.save()

    @classmethod
    @ModelView.button_action('real_estate.wizard_terminate_contract')
    def terminate(cls, contrats):
        pass

    @classmethod
    @ModelView.button
    @Workflow.transition('cancelled')
    @set_employee('cancelled_by')
    def cancel(cls, contrats):
        pool = Pool()
        CashFlow = pool.get('real_estate.contract.term.cash_flow')
        Warning = pool.get('res.user.warning')
        for contract in contrats:
            # Booked terms (with a last posting date): their postings are
            # not reversed here and have to be cancelled manually
            if any(term.last_posting_date for term in contract.terms):
                key = Warning.format('cancel_contract_has_postings', [contract])
                if Warning.check(key):
                    raise ContractCancelWarning(
                        key,
                        gettext('real_estate.msg_cancel_contract_has_postings'
                            ).format(contract.rec_name))
            draft_flows = CashFlow.search([
                ('term.contract', '=', contract.id),
                ('state', '=', 'draft'),
            ])
            if draft_flows:
                CashFlow.delete(draft_flows)
            contract.add_log('state_change', 'contract state changed to cancelled')
            contract.state = 'cancelled'
            contract.save()

    @classmethod
    @ModelView.button_action('real_estate.wizard_change_contract_partner')
    def change_partner(cls, contracts):
        pass

    @classmethod
    def execute_change_partner(cls, contracts, new_party, change_date=None):
        """Reassign the contractual partner as of change_date (defaults to
        today). Only still-open (unreconciled) booked items are rebooked -
        already settled invoices are left untouched. Per open original
        invoice ("Beleg"): a credit note closes the old partner's open
        item (same mechanism as BillingUnit.cancel_units), and a new
        invoice with identical lines (same values, only accounting_date is
        change_date) reopens the same charge under the new partner.

        Party assignment: the old partner's open 'Main Tenant Role'
        assignment is ended on change_date - 1 day, and (if configured on
        the contract type) the old partner is given 'Secondary Tenant
        Role' from change_date; the new partner is given 'Main Tenant
        Role' from change_date."""
        pool = Pool()
        Invoice = pool.get('account.invoice')
        InvoiceLine = pool.get('account.invoice.line')
        MoveLine = pool.get('account.move.line')
        CashFlowLine = pool.get('real_estate.contract.term.cash_flow')
        ContractParty = pool.get('real_estate.contract.party')
        Date = pool.get('ir.date')

        if change_date is None:
            change_date = Date.today()

        for contract in contracts:
            old_party = contract.contractual_partner
            if not old_party or new_party.id == old_party.id:
                raise ValidationError(gettext(
                    'real_estate.msg_change_partner_same_party',
                    contract=contract.rec_name))

            effective_end = contract.get_effective_end_date()
            if ((contract.start_date and change_date < contract.start_date)
                    or (effective_end and change_date > effective_end)):
                raise ValidationError(gettext(
                    'real_estate.msg_change_partner_date_out_of_range',
                    contract=contract.rec_name,
                    start_date=str(contract.start_date),
                    end_date=str(effective_end) if effective_end else '-'))

            # Draft invoices for the old party are never picked up by the
            # rebooking below (it only rebooks posted/done cash flow lines)
            # and would otherwise silently stay with the old party - warn
            # and let the user abort instead of just missing them.
            draft_invoices = Invoice.search([
                ('contract', '=', contract.id),
                ('party', '=', old_party.id),
                ('state', '=', 'draft'),
            ])
            if draft_invoices:
                Warning = pool.get('res.user.warning')
                key = Warning.format(
                    'contract_partner_change_draft_invoices',
                    [contract] + draft_invoices)
                if Warning.check(key):
                    raise ContractPartnerChangeDraftInvoicesWarning(
                        key, gettext(
                            'real_estate.'
                            'msg_contract_partner_change_draft_invoices',
                            contract=contract.rec_name,
                            party=old_party.rec_name,
                            count=len(draft_invoices)))

            cash_flow_lines = CashFlowLine.search([
                ('term.contract', '=', contract.id),
                ('state', '=', 'done'),
                ('invoice_state', '=', 'posted'),
            ])
            invoice_ids = {cf.invoice.id for cf in cash_flow_lines if cf.invoice}
            open_invoices = [
                invoice for invoice in Invoice.browse(list(invoice_ids))
                if any(not line.reconciliation for line in invoice.lines_to_pay)]

            rebooked = 0
            for invoice in open_invoices:
                # 1) Close the old party's open item via a credit note -
                # same mechanism as BillingUnit.cancel_units.
                credit_notes = Invoice.credit(
                    [invoice], refund=False, invoice_date=change_date)
                Invoice.post(credit_notes)
                credit_note = credit_notes[0]

                open_lines = [
                    line for line in
                    list(invoice.lines_to_pay) + list(credit_note.lines_to_pay)
                    if not line.reconciliation]
                if open_lines and sum(
                        line.debit - line.credit
                        for line in open_lines) == Decimal(0):
                    MoveLine.reconcile(open_lines)

                # 2) Re-issue the same charges to the new party, booked on
                # change_date - all other values (account, amount, taxes,
                # invoice_date, ...) are copied 1:1 from the original.
                new_lines = []
                for line in invoice.lines:
                    if line.type != 'line':
                        continue
                    new_line = InvoiceLine(
                        type='line',
                        company=line.company.id,
                        party=new_party.id,
                        invoice_type=line.invoice_type,
                        description=line.description,
                        quantity=line.quantity,
                        unit=line.unit.id if line.unit else None,
                        unit_price=line.unit_price,
                        account=line.account.id,
                        taxes=[t.id for t in line.taxes],
                        currency=line.currency.id,
                        contract=contract.id,
                        term=line.term.id if line.term else None,
                        base_object=line.base_object.id if line.base_object else None,
                        assignment_control=line.assignment_control,
                    )
                    new_line.save()
                    new_lines.append(new_line)

                new_invoice = Invoice(
                    company=invoice.company.id,
                    type=invoice.type,
                    party=new_party.id,
                    invoice_date=invoice.invoice_date,
                    accounting_date=change_date,
                    journal=invoice.journal.id,
                    account=invoice.account.id,
                    invoice_address=new_party.address_get(type='invoice'),
                    currency=invoice.currency.id,
                    payment_term=invoice.payment_term.id if invoice.payment_term else None,
                    description=f"{invoice.description} (Change Partner)",
                    reference=invoice.reference,
                    lines=new_lines,
                    contract=contract.id,
                )
                Invoice.save([new_invoice])
                Invoice.post([new_invoice])
                rebooked += 1

            main_role = contract.c_type.main_tenant_role
            secondary_role = contract.c_type.secondary_tenant_role
            if main_role:
                open_main_assignments = ContractParty.search([
                    ('contract', '=', contract.id),
                    ('party', '=', old_party.id),
                    ('role', '=', main_role.id),
                    ('valid_to', '=', None),
                ])
                if open_main_assignments:
                    ContractParty.write(
                        open_main_assignments,
                        {'valid_to': change_date - datetime.timedelta(days=1)})
                if secondary_role:
                    ContractParty.create([{
                        'contract': contract.id,
                        'party': old_party.id,
                        'role': secondary_role.id,
                        'valid_from': change_date,
                    }])
                new_party_address = new_party.address_get(type='invoice')
                ContractParty.create([{
                    'contract': contract.id,
                    'party': new_party.id,
                    'role': main_role.id,
                    'valid_from': change_date,
                    'invoice_address': (
                        new_party_address.id if new_party_address else None),
                }])

            contract.contractual_partner = new_party
            contract.save()
            contract.add_log('change_partner',
                f'Partner changed from {old_party.name} to {new_party.name} '
                f'({rebooked} open invoice(s) rebooked).')

            # Re-calculate (not create/book) the cash flow so that still-
            # draft plan entries reflect the new partner right away instead
            # of only picking it up whenever the next scheduled
            # create_moves run happens to process this contract.
            cls.call_create_moves(
                [contract.id], change_date, action='re_calc',
                execute_in_queue=False)

    @classmethod
    def _refresh_occupancy_for_contracts(cls, contracts):
        pool = Pool()
        BaseObjectOccupancy = pool.get('real_estate.base_object.occupancy')
        BaseObject = pool.get('real_estate.base_object')
        ContractItem = pool.get('real_estate.contract.item')
        base_object_ids = set()
        for contract in contracts:
            for item in contract.items:
                for obj in item.objects:
                    base_object_ids.add(obj.id)
        if base_object_ids:
            BaseObjectOccupancy.refresh(BaseObject.browse(list(base_object_ids)))
            ContractItem._trigger_billing_unit_selection(base_object_ids)

    _COMPUTE_VALUE_SHARES_FIELDS = frozenset({
        'state', 'start_date', 'end_date',
        'termination_date', 'terminated_by_type',
        'termination_notice', 'receipt_of_termination_notice',
    })

    _RE_CALC_CONTRACT_FIELDS = frozenset({
        'state', 'start_date', 'end_date', 'termination_date', 'start_booking_date',
    })

    @classmethod
    def _re_calc_terms(cls, contracts):
        """Rebuild cash flows for all terms of the given contracts (once per contract)."""
        with Transaction().set_context(_skip_re_calc=True):
            for contract in contracts:
                if contract.state not in ('running', 'terminated'):
                    continue
                for term in contract.terms:
                    term.re_calc()
                    term.next_document_date = term.on_change_with_next_document_date()
                    term.next_due_date = term.on_change_with_next_due_date()
                    term.save()

    @classmethod
    def _warn_contractual_partner_change(cls, args):
        """Warn (not block) when contractual_partner is being changed away
        from a party that already has booked (state='done') cash flow
        entries on this contract - e.g. editing the 'Parties' tab
        directly (deleting the old main tenant's row, adding a new one)
        rather than going through the dedicated 'Change Partner' wizard,
        which handles rebooking open items itself. Must run before
        super().write() so contract.contractual_partner still reflects
        the pre-write value."""
        pool = Pool()
        Warning = pool.get('res.user.warning')
        CashFlowLine = pool.get('real_estate.contract.term.cash_flow')

        actions = iter(args)
        for contracts, values in zip(actions, actions):
            if 'contractual_partner' not in values:
                continue
            new_partner_id = values['contractual_partner']
            for contract in contracts:
                old_partner = contract.contractual_partner
                if not old_partner or old_partner.id == new_partner_id:
                    continue
                has_bookings = any(
                    cf.invoice and cf.invoice.party.id == old_partner.id
                    for cf in CashFlowLine.search([
                        ('term.contract', '=', contract.id),
                        ('state', '=', 'done'),
                    ]))
                if not has_bookings:
                    continue
                key = Warning.format(
                    'contract_partner_changed_has_bookings', [contract])
                if Warning.check(key):
                    raise ContractPartnerChangedWarning(key, gettext(
                        'real_estate.msg_contract_partner_changed_has_bookings',
                        contract=contract.rec_name, party=old_partner.name))

    @classmethod
    def write(cls, *args):
        cls._warn_contractual_partner_change(args)
        super().write(*args)
        occ_ids = set()
        re_calc_ids = set()
        actions = iter(args)
        for records, values in zip(actions, actions):
            if cls._COMPUTE_VALUE_SHARES_FIELDS & set(values):
                for c in records:
                    occ_ids.add(c.id)
            if cls._RE_CALC_CONTRACT_FIELDS & set(values):
                for c in records:
                    re_calc_ids.add(c.id)
        if occ_ids:
            fresh = cls.browse(list(occ_ids))
            cls._refresh_occupancy_for_contracts(fresh)
            BaseObject = Pool().get('real_estate.base_object')
            property_ids = {c.property.id for c in fresh if c.property}
            if property_ids:
                BaseObject.compute_value_shares(
                    BaseObject.browse(list(property_ids)))
        if re_calc_ids and not Transaction().context.get('_skip_re_calc'):
            cls._re_calc_terms(cls.browse(list(re_calc_ids)))

    @classmethod
    def set_cash_flow(cls, record, name, value):
        pass

    @fields.depends('company', 'items')
    def on_change_with_meters(self, name=None):
        return [child for item in self.items for child in item.children if child.e_type == 'meters']

    @fields.depends('company', 'items')
    def on_change_with_measurements(self, name=None):
        return [
            measurement
            for item in self.items
            for obj in item.objects
            for measurement in obj.measurements]

    @classmethod
    def get_cost_shares(cls, contracts, name):
        """Cost shares of this contract's settlement units (see
        ``get_settlement_units``), restricted to those actually assigned to
        this contract."""
        pool = Pool()
        SettlementUnit = pool.get('real_estate.settlement_unit')
        result = {c.id: [] for c in contracts}
        settlement_unit_ids = cls.get_settlement_units(contracts, 'settlement_units')
        all_su_ids = {su_id for ids in settlement_unit_ids.values() for su_id in ids}
        if not all_su_ids:
            return result
        settlement_units = SettlementUnit.browse(list(all_su_ids))
        su_by_id = {su.id: su for su in settlement_units}
        for contract in contracts:
            for su_id in settlement_unit_ids.get(contract.id, []):
                su = su_by_id[su_id]
                for cs in su.cost_shares:
                    if cs.contract and cs.contract.id == contract.id:
                        result[contract.id].append(cs.id)
        return result

    @classmethod
    def get_settlement_units(cls, contracts, name):
        """Settlement units of the contract's property whose objects overlap
        with the objects assigned to this contract via its items.

        Billing units are restricted to the property's
        ``next_billing_start_date`` (the earliest non-billed billing unit
        start date). If the property has none set, the billing units in
        state ``billed`` with the latest (most recent) ``start_date`` are
        used instead — i.e. the most recently completed settlement period.
        """
        pool = Pool()
        BillingUnit = pool.get('real_estate.billing_unit')
        result = {c.id: [] for c in contracts}
        billing_units_by_property = {}
        for contract in contracts:
            if not contract.property:
                continue
            contract_object_ids = {
                obj.id
                for item in contract.items
                for obj in item.objects}
            if not contract_object_ids:
                continue

            property_id = contract.property.id
            if property_id not in billing_units_by_property:
                next_date = contract.property.next_billing_start_date
                domain = [('property', '=', property_id)]
                if next_date:
                    units = BillingUnit.search(
                        domain + [('start_date', '=', next_date)])
                else:
                    billed_domain = domain + [('state', '=', 'billed')]
                    latest = BillingUnit.search(
                        billed_domain, order=[('start_date', 'DESC')], limit=1)
                    if latest:
                        units = BillingUnit.search(billed_domain + [
                            ('start_date', '=', latest[0].start_date)])
                    else:
                        units = []
                billing_units_by_property[property_id] = units

            for bu in billing_units_by_property[property_id]:
                for su in bu.settlement_units:
                    # 'allocation_via_cost_collector' units generate no
                    # cost shares/settlement results of their own (see
                    # settlement_unit.py) - only the settlement unit they
                    # reference should ever surface here, or the tenant
                    # would see the same cost type twice (e.g. in the
                    # Annex 4 report).
                    if su.allocation_rule == 'allocation_via_cost_collector':
                        continue
                    if any(obj.id in contract_object_ids for obj in su.objects):
                        result[contract.id].append(su.id)
        return result

    @fields.depends('c_type')
    def get_term_types_of_use(self, name=None):
        # Instance method (not classmethod) on purpose: restricts the
        # dropdown to only the types of use the chosen contract type
        # actually allows, once one is chosen - the field is invisible
        # anyway while c_type is empty or unambiguous, see 'type_of_use'
        # states above.
        pool = Pool()
        BaseObject = pool.get('real_estate.base_object')
        all_selection = BaseObject.fields_get(
            ['type_of_use'])['type_of_use']['selection']
        if self.c_type and self.c_type.types_of_use:
            allowed = set(self.c_type.types_of_use)
            return [(k, v) for k, v in all_selection if k in allowed]
        return all_selection

    @classmethod
    def default_company(cls):
        return Transaction().context.get('company')

    def get_effective_end_date(self):
        if self.termination_date and (
                not self.end_date or self.termination_date < self.end_date):
            return self.termination_date
        return self.end_date

    @fields.depends('start_date', 'end_date', 'termination_date')
    def on_change_with_current_terms_date(self, name=None):
        today = Pool().get('ir.date').today()
        if self.start_date and today < self.start_date:
            return self.start_date
        end_date = self.get_effective_end_date()
        if end_date and today > end_date:
            return end_date
        return today

    @fields.depends('terms', methods=['on_change_with_current_terms_date'])
    def on_change_with_current_terms(self, name=None):
        key_date = self.on_change_with_current_terms_date()
        # Unsaved terms (negative/virtual id) cannot be listed in a
        # Function One2Many - they appear here once the contract is saved.
        terms = [t for t in (self.terms or [])
            if t.id is not None and t.id >= 0
            and t.valid_from and t.valid_from <= key_date
            and (not t.valid_to or t.valid_to >= key_date)]
        terms.sort(key=lambda t: (t.sequence is None, t.sequence or 0))
        return [t.id for t in terms]

    @fields.depends('terms')
    def on_change_with_cash_flow_draft(self, name=None):
        def _is_draft(cf):
            if not cf.invoice_line:
                return True
            inv = cf.invoice_line.invoice
            return inv is None or inv.state in ('draft', 'validated')
        # A new, unsaved term (negative/virtual id) cannot have any cash
        # flow yet - term.cash_flow is a required FK to a saved term, so
        # there is nothing to look up. The client also doesn't send the
        # 'cash_flow' sub-field for such rows in the on_change payload,
        # which would otherwise raise an AttributeError here.
        return sorted(
            [cf for term in self.terms if isinstance(term.id, int) and term.id > 0
                for cf in term.cash_flow if _is_draft(cf)],
            key=lambda line: (line.document_date, line.posting_date, line.name))

    def add_log(self, event, description=None):
        pool = Pool()
        ContractLog = pool.get('real_estate.contract.log')
        ContractLog.create([{
            'contract': self.id,
            'event': event,
            'description': description or '',
        }])

    @classmethod
    def cron_daily(cls):
        """Single daily ir.cron entry point. Dispatches to the individual
        real_estate.cron_task rows (one per real_estate.re_accounting and
        task code) that are due, based on each task's own scheduling
        (schedule_day_of_month if set, otherwise interval_days / last_run).
        Adding a new recurring operation only requires a new '_cron_<task>'
        classmethod and a new option in CronTask.get_tasks() - no new
        ir.cron entry."""
        pool = Pool()
        CronTask = pool.get('real_estate.cron_task')
        Date = pool.get('ir.date')
        today = Date.today()
        for task in CronTask.search([('active', '=', True)]):
            if not cls._cron_task_is_due(task, today):
                continue
            handler = getattr(cls, f'_cron_{task.task}', None)
            if handler is None:
                continue
            handler(task.re_accounting, task)
            task.last_run = today
            task.save()

    @classmethod
    def _cron_task_is_due(cls, task, today):
        """valid_from/valid_until (if set) are hard lower/upper bounds -
        the task never runs before valid_from or after valid_until,
        regardless of scheduling mode - and valid_from additionally serves,
        for interval_months, as the day-of-month anchor for exact
        recurrences (see below).

        Three scheduling modes, in this priority order:
        1. schedule_day_of_month set: runs (at most) once a month, on/after
           that calendar day (capped to the last day of the current month
           for day 29-31 in shorter months).
        2. Otherwise, interval_months set: if valid_from is also set, runs
           on the exact recurring date valid_from + k*interval_months
           months (same day-of-month as valid_from, clamped to shorter
           months) - computed by repeatedly advancing from valid_from past
           last_run, so a delayed run re-aligns to the next correct slot
           instead of drifting. If valid_from is not set, falls back to a
           looser check: due once at least interval_months calendar months
           (year/month difference, not exact days) have passed since
           last_run.
        3. Otherwise, plain interval_days/last_run check.
        Each mode ignores the ones below it once set."""
        if task.valid_from and today < task.valid_from:
            return False
        if task.valid_until and today > task.valid_until:
            return False
        if task.schedule_day_of_month:
            if (task.last_run is not None
                    and (task.last_run.year, task.last_run.month)
                        == (today.year, today.month)):
                return False
            last_day_of_month = calendar.monthrange(
                today.year, today.month)[1]
            run_day = min(task.schedule_day_of_month, last_day_of_month)
            return today.day >= run_day
        if task.interval_months:
            if task.last_run is None:
                return True
            if task.valid_from:
                next_due = cls._add_months(
                    task.valid_from, task.interval_months)
                while next_due <= task.last_run:
                    next_due = cls._add_months(
                        next_due, task.interval_months)
                return today >= next_due
            months_elapsed = ((today.year - task.last_run.year) * 12
                + (today.month - task.last_run.month))
            return months_elapsed >= task.interval_months
        if not task.interval_days:
            return False
        return (task.last_run is None
            or (today - task.last_run).days >= task.interval_days)

    @staticmethod
    def _add_months(date, months):
        """date advanced by 'months' calendar months, clamped to the last
        day of the target month if the original day doesn't exist there
        (e.g. 31.01. + 1 month -> 28./29.02.)."""
        month_index = date.month - 1 + months
        year = date.year + month_index // 12
        month = month_index % 12 + 1
        last_day = calendar.monthrange(year, month)[1]
        return date.replace(year=year, month=month, day=min(date.day, last_day))

    @classmethod
    def _cron_update_contract_status(cls, re_accounting, task=None):
        """Auto-terminate fixed-term contracts (end_date set, no active
        termination) whose end_date has passed. Reuses the 'terminated'
        state (see get_effective_end_date/occupancy, which already treat
        end_date/termination_date identically) rather than adding a new
        state, so existing state-dependent logic keeps working unchanged.

        Also repairs the reverse data gap: an unlimited contract that is
        already 'terminated' (normally via TerminateContractWizard, which
        sets end_date = termination_date unconditionally,
        contract_wizard.py:46) but ended up with no end_date - e.g. state/
        termination_date set by some other path than the wizard. Once its
        termination_date has passed, end_date is synced to it here too.

        Also auto-fills contractual_partner (see get_main_tenant) for any
        contract where it is still empty, so contracts entered without
        going through the on_change-driven fill (e.g. via import) still
        end up with a partner once a Main Tenant party is assigned."""
        Date = Pool().get('ir.date')
        today = Date.today()
        contracts = cls.search([
            ('state', '=', 'running'),
            ('end_date', '!=', None),
            ('end_date', '<', today),
            ('termination_date', '=', None),
            ('company.re_accounting', '=', re_accounting.id),
        ])
        for contract in contracts:
            contract.state = 'terminated'
            contract.termination_date = contract.end_date
            contract.terminated_by_type = 'expired'
            contract.termination_reason = gettext(
                'real_estate.msg_contract_auto_terminated')
            contract.save()
            contract.add_log('state_change',
                f'contract auto-terminated: end date {contract.end_date} '
                f'reached')

        gap_contracts = cls.search([
            ('state', '=', 'terminated'),
            ('unlimited', '=', True),
            ('end_date', '=', None),
            ('termination_date', '!=', None),
            ('termination_date', '<', today),
            ('company.re_accounting', '=', re_accounting.id),
        ])
        for contract in gap_contracts:
            contract.end_date = contract.termination_date
            contract.save()
            contract.add_log('state_change',
                f'contract end date synced to termination date '
                f'{contract.termination_date} (was empty on an already '
                f'terminated, unlimited contract)')

        # Auto-fill contractual_partner from the party assignment list
        # (see Contract.get_main_tenant) for any contract where it is
        # still empty - never overwrites an already-set value.
        unassigned_contracts = cls.search([
            ('contractual_partner', '=', None),
            ('company.re_accounting', '=', re_accounting.id),
        ])
        for contract in unassigned_contracts:
            main_tenant = contract.get_main_tenant()
            if main_tenant:
                contract.contractual_partner = main_tenant
                contract.save()
                contract.add_log('state_change',
                    f'contractual_partner auto-filled from party '
                    f'assignment list: {main_tenant.name}')

    @classmethod
    def _cron_update_contract_cash_flow(cls, re_accounting, task=None):
        """Recalculates each term's cash flow (ContractTermCashFlow),
        without requiring a person to run the wizard repeatedly.
        Recalculation only ('re_calc') - no invoices are created here; see
        _cron_book_contract_cash_flow for the separate, explicitly
        scheduled booking step.

        How far each recalculated term's cash flow extends is fixed at
        exactly 1 year from today (see contract_term.py:_re_calc_year,
        used inside Term.re_calc()) and not affected by the horizon below.
        `date` here only decides which not-yet-started contracts get
        included in this run at all - a contract whose start_date is more
        than `future_contracts_horizon_days` away is skipped and picked up
        by a later run once its start_date comes within range.
        Already-running/-terminated contracts are always included
        regardless of this horizon."""
        Date = Pool().get('ir.date')
        horizon = (task.future_contracts_horizon_days if task else None) or 60
        date = Date.today() + datetime.timedelta(days=horizon)
        contracts = cls.search([
            ('state', 'in', ('running', 'terminated')),
            ('start_date', '<=', date),
            ('company.re_accounting', '=', re_accounting.id),
        ])
        if contracts:
            cls.call_create_moves(
                [c.id for c in contracts], date, 're_calc',
                True, 'draft', None)

    @classmethod
    def _cron_book_contract_cash_flow(cls, re_accounting, task):
        """Books (creates invoices for) all due terms up to the end of the
        month that is horizon_months_ahead months after today - e.g. run
        on the 15th of the month (schedule_day_of_month=15) with
        horizon_months_ahead=1 books everything due up to the end of next
        month. Uses 're_calc_and_create' so it is self-sufficient (does not
        depend on _cron_update_contract_cash_flow's horizon already
        covering the booking horizon). The row's own invoice_state
        ('draft'/'posted', default 'draft') determines whether the created
        invoices are posted immediately - see call_create_moves/
        _create_moves."""
        Date = Pool().get('ir.date')
        today = Date.today()
        months_ahead = (task.horizon_months_ahead or 1) if task else 1
        month_index = today.month - 1 + months_ahead
        target_year = today.year + month_index // 12
        target_month = month_index % 12 + 1
        last_day = calendar.monthrange(target_year, target_month)[1]
        date = datetime.date(target_year, target_month, last_day)
        invoice_state = (task.invoice_state if task else None) or 'draft'
        contracts = cls.search([
            ('state', 'in', ('running', 'terminated')),
            ('start_date', '<=', date),
            ('company.re_accounting', '=', re_accounting.id),
        ])
        if contracts:
            cls.call_create_moves(
                [c.id for c in contracts], date, 're_calc_and_create',
                True, invoice_state, None)

    @classmethod
    def _cron_update_option_rate(cls, re_accounting, task=None):
        """Recompute and, where the rate actually changed, book new option
        rates (see OptionRate.process_update) for all properties of every
        company using this real estate accounting configuration, as of
        today. Intended to run monthly (schedule_day_of_month=1), which
        also determines the effective_date used by process_update (the
        1st of the current month)."""
        pool = Pool()
        Company = pool.get('company.company')
        BaseObject = pool.get('real_estate.base_object')
        OptionRate = pool.get('real_estate.option_rate')
        Date = pool.get('ir.date')
        companies = Company.search([('re_accounting', '=', re_accounting.id)])
        if not companies:
            return
        base_objects = BaseObject.search([
            ('type', '=', 'property'),
            ('company', 'in', [c.id for c in companies]),
        ])
        if not base_objects:
            return
        counts, detail_log = OptionRate.process_update(
            base_objects, [], [], Date.today())
        logger.info(
            'cron _cron_update_option_rate for re_accounting %s: %s',
            re_accounting.id, counts)
        for line in detail_log:
            logger.debug(line)

    @staticmethod
    def default_state():
        return 'draft'

    @staticmethod
    def default_start_date():
        return Pool().get('ir.date').today().replace(day=1)

    @staticmethod
    def default_unlimited():
        return True

    @fields.depends('terms', 'c_type')
    def on_change_with_next_term_sequence(self, name=None):
        if self.terms and self.c_type:
            return max(term.sequence for term in self.terms) + self.c_type.step_term
        return self.c_type.step_term if self.c_type else 1

    @fields.depends('items', 'c_type')
    def on_change_with_next_item_sequence(self, name=None):
        if self.items and self.c_type:
            return max(item.sequence for item in self.items) + self.c_type.step_item
        return self.c_type.step_item if self.c_type else 1

    @fields.depends('contractual_partner', 'c_type')
    def on_change_contractual_partner(self, name=None):
        # invoice_address is no longer settable here - it is a Function
        # field derived from the main tenant's own party-assignment row
        # (see on_change_with_invoice_address).
        if self.contractual_partner:
            if self.c_type.invoice_type == 'out':
                self.payment_term = self.contractual_partner.customer_payment_term
            elif self.c_type.invoice_type == 'in':
                self.payment_term = self.contractual_partner.supplier_payment_term
        else:
            self.payment_term = None

    @fields.depends('parties', 'c_type')
    def on_change_with_main_tenant_party_ids(self, name=None):
        role = self.c_type.main_tenant_role if self.c_type else None
        if not role:
            return []
        return [cp.party.id for cp in (self.parties or [])
            if cp.role and cp.role.id == role.id]

    def get_main_tenant_assignment(self, date=None):
        """Return the real_estate.contract.party record currently holding
        the contract type's 'Main Tenant Role', as of date (defaults to
        today), clamped to this contract's own validity period
        [start_date, effective end date]. Returns the first matching
        assignment, or None if no role is configured or none matches."""
        role = self.c_type.main_tenant_role if self.c_type else None
        if not role:
            return None
        if date is None:
            date = Pool().get('ir.date').today()
        start = self.start_date
        end = self.get_effective_end_date()
        if start and date < start:
            date = start
        if end and date > end:
            date = end
        for cp in (self.parties or []):
            if not cp.role or cp.role.id != role.id:
                continue
            if cp.valid_from and date < cp.valid_from:
                continue
            if cp.valid_to and date > cp.valid_to:
                continue
            return cp
        return None

    def get_main_tenant(self, date=None):
        """Return the party of get_main_tenant_assignment(date), or None."""
        assignment = self.get_main_tenant_assignment(date)
        return assignment.party if assignment else None

    def get_invoice_address(self, date=None):
        """Return the invoice address to use for booking (and for
        display in the 'invoice_address' Function field): the address
        maintained on the current main tenant's own party-assignment row
        (see get_main_tenant_assignment), falling back to that party's
        own default invoice address if the assignment doesn't have one
        set. None if there is no current main tenant assignment."""
        assignment = self.get_main_tenant_assignment(date)
        if not assignment:
            return None
        if assignment.invoice_address:
            return assignment.invoice_address
        return assignment.party.address_get(type='invoice')

    @fields.depends(
        'parties', 'c_type', 'start_date', 'end_date', 'termination_date')
    def on_change_with_invoice_address(self, name=None):
        address = self.get_invoice_address()
        return address.id if address else None

    @fields.depends(
        'parties', 'c_type', 'start_date', 'end_date', 'termination_date')
    def on_change_with_phone_partner(self, name=None):
        assignment = self.get_main_tenant_assignment()
        return assignment.phone_partner if assignment else ''

    @fields.depends(
        'parties', 'c_type', 'contractual_partner', 'start_date',
        'end_date', 'termination_date',
        methods=['on_change_contractual_partner'])
    def on_change_parties(self):
        # contractual_partner is derived/auto-managed (its own domain
        # already restricts manual picks to the same 'currently valid
        # main tenant' set), so always keep it in sync here rather than
        # only filling it when empty - otherwise replacing the main
        # tenant (delete the old party-assignment row, add a new one)
        # leaves the stale, now out-of-domain party in place and fails
        # validation on save.
        main_tenant = self.get_main_tenant()
        old_id = self.contractual_partner.id if self.contractual_partner else None
        new_id = main_tenant.id if main_tenant else None
        if old_id != new_id:
            self.contractual_partner = main_tenant
            self.on_change_contractual_partner()

    @fields.depends('unlimited')
    def on_change_unlimited(self, name=None):
        if self.unlimited:
            self.end_date = None

    @fields.depends('company')
    def on_change_with_currency(self, name=None):
        return self.company.currency if self.company else None

    @fields.depends('company', '_parent_company.re_accounting')
    def on_change_with_company_re_accounting(self, name=None):
        if self.company and self.company.re_accounting:
            return self.company.re_accounting.id
        return None

    @fields.depends('c_type')
    def on_change_with_c_type_multi_use(self, name=None):
        if self.c_type and self.c_type.types_of_use:
            return len(self.c_type.types_of_use) > 1
        return False

    @fields.depends('c_type', 'type_of_use',
        methods=['on_change_with_c_type_multi_use'])
    def on_change_c_type(self):
        # Preset type_of_use automatically when the chosen contract type
        # only allows exactly one - nothing left to pick, and the field
        # stays hidden (see its 'invisible' state). Clear it when it no
        # longer matches the (new) contract type's allowed values.
        if not self.c_type or not self.c_type.types_of_use:
            self.type_of_use = None
            return
        allowed = self.c_type.types_of_use
        if len(allowed) == 1:
            self.type_of_use = allowed[0]
        elif self.type_of_use not in allowed:
            self.type_of_use = None

    @fields.depends('c_type', 'property', 'company', 'sequence')
    def on_change_with_sequence(self, name=None):
        if (getattr(self, 'sequence', None) is not None and self.sequence != 0):
            return self.sequence
        if self.c_type is not None and self.property is not None and self.company is not None:
            contracts = Pool().get('real_estate.contract').search([
                ('company', '=', self.company.id),
                ('c_type', '=', self.c_type.id),
                ('property', '=', self.property.id),
            ], order=[('sequence', 'DESC')], limit=1)
            return (contracts[0].sequence + 1 if contracts else 1)
        return 0

    @fields.depends('c_type', 'property', 'sequence')
    def on_change_with_contract_number(self, name=None):
        self.sequence = self.on_change_with_sequence()
        if self.c_type is None or self.property is None or not self.sequence:
            return f" - "
        return f"{self.c_type.prefix}-{self.property.sequence}-{self.sequence}"

    @fields.depends('contract_number', 'contractual_partner')
    def on_change_with_name(self, name=None):
        if not self.contract_number or not self.contractual_partner:
            return f" - "
        return f"{self.contract_number} / {self.contractual_partner.name}"

    def get_address_partner(self, name=None):
        if self.contractual_partner:
            Party = Pool().get('party.party')
            party = Party(self.contractual_partner)
            if party and party.addresses:
                return party.addresses[0].full_address.replace('\n', ' / ')
        return ''

    @classmethod
    def set_meters(cls, record, name, value):
        pass

    @classmethod
    def set_measurements(cls, record, name, value):
        pass

    @classmethod
    def set_cost_shares(cls, records, name, value):
        pass

    @classmethod
    def set_settlement_units(cls, records, name, value):
        pass

    @classmethod
    def name_search(cls, name, clause):
        if clause[1].startswith('!') or clause[1].startswith('not '):
            bool_op = 'AND'
        else:
            bool_op = 'OR'
        return [bool_op,
            ('contract_number',) + tuple(clause[1:]),
            ('contractual_partner.name',) + tuple(clause[1:]),
        ]

    def _create_moves(self, terms, date, invoice_state='draft', invoice_date=None, run_id=None):
        self.add_log('process', f'start quere contract {self.id} at {date}')
        if not terms:
            self.add_log('process', f'stop quere contract {self.id} at {date} - no terms')
            return

        # run_id is normally generated once per property by the caller
        # (call_create_moves), so all contracts of that property share it.
        # Fall back to a freshly generated one for direct/standalone calls.
        create_moves_run_id = run_id or (
            f"{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"
            f"-U{Transaction().user}")

        pool = Pool()
        Invoice = pool.get('account.invoice')
        InvoiceLine = pool.get('account.invoice.line')
        Configuration = pool.get('account.configuration')
        config = Configuration(1)

        lines_by_date = defaultdict(
            lambda: {'lines': [], 'document_date': None, 'due_date': None})

        for term_id in terms:
            term = next(
                (obj for obj in self.terms if obj.id == term_id), None)
            if term:
                taxes = set(term.taxes)
                l_account = term.account.id if term.account \
                    else config.account_revenue.id if self.c_type.invoice_type == 'out' \
                    else config.account_expense.id

                for cash_flow in term.cash_flow:
                    if cash_flow.document_date <= date and cash_flow.state == 'draft':
                        ref_item = term.reference_item
                        m_type = (term.term_type.m_type
                            if term.term_type else None)

                        multi_objects = bool(ref_item and ref_item.objects
                            and len(ref_item.objects) > 1)

                        # Build per-object lines when multiple objects are
                        # assigned: measurement-based terms get each
                        # object's own measurement as quantity, absolute
                        # terms (no measurement type) split their unit
                        # price by the term's object_distribution;
                        # otherwise single line.
                        per_obj_lines = []
                        per_obj_values = []
                        if multi_objects and m_type:
                            from .contract_term import ContractTerm
                            for obj in ref_item.objects:
                                obj_qty = ContractTerm._sum_measurements(
                                    type('_R', (), {'objects': [obj]})(),
                                    m_type,
                                    cash_flow.document_date)
                                if not obj_qty:
                                    self.add_log('warning',
                                        f'term "{term.name}": object '
                                        f'"{obj.name}" has no matching '
                                        f'measurement "{m_type.name}" for '
                                        f'{cash_flow.document_date} - no '
                                        f'invoice line created for this '
                                        f'object.')
                                    continue
                                per_obj_values.append(
                                    (obj, obj_qty, term.unit_price))
                        elif multi_objects:
                            parts, warnings = term.split_unit_price(
                                list(ref_item.objects),
                                cash_flow.document_date)
                            for warning in warnings:
                                self.add_log('warning',
                                    f'term "{term.name}": {warning}')
                            per_obj_values = [
                                (obj, term.quantity, part_price)
                                for obj, part_price in parts if part_price]

                        for obj, obj_qty, obj_unit_price in per_obj_values:
                            line = InvoiceLine(
                                type='line',
                                company=self.company.id,
                                party=self.contractual_partner.id,
                                invoice_type=self.c_type.invoice_type,
                                description=(
                                    cash_flow.name + ' – ' + obj.name),
                                quantity=obj_qty,
                                unit=term.unit,
                                unit_price=obj_unit_price,
                                account=l_account,
                                currency=self.currency.id,
                                taxes=list(taxes),
                                contract=self,
                                term=term,
                                base_object=obj.id,
                                assignment_control='contract',
                            )
                            line.save()
                            per_obj_lines.append(line)

                        # No object had a measurement / share — fall
                        # through to single-line behaviour below
                        if per_obj_lines:
                            cash_flow.state = 'done'
                            cash_flow.posting_date = cash_flow.document_date
                            cash_flow.create_moves_run_id = create_moves_run_id
                            group = lines_by_date[cash_flow.posting_date]
                            group['lines'].extend(per_obj_lines)
                            if group['document_date'] is None:
                                group['document_date'] = cash_flow.document_date
                                group['due_date'] = cash_flow.due_date
                            # link first line to cash_flow for traceability
                            cash_flow.invoice_line = per_obj_lines[0]
                            cash_flow.save()
                            term.last_posting_date = cash_flow.posting_date
                            continue

                        # Default: single invoice line
                        first_obj = (
                            ref_item.objects[0]
                            if ref_item and ref_item.objects else None)
                        # Planned quantity of this cash flow entry (for
                        # measurement-based terms the measurement as of its
                        # document date, see ContractTerm.re_calc)
                        line_quantity = cash_flow.quantity
                        if (m_type and not line_quantity
                                and not multi_objects):
                            self.add_log('warning',
                                f'term "{term.name}": no assigned object '
                                f'has a matching measurement "{m_type.name}" '
                                f'for {cash_flow.document_date} - quantity '
                                f'is 0.')
                        new_invoice_line = InvoiceLine(
                            type='line',
                            company=self.company.id,
                            party=self.contractual_partner.id,
                            invoice_type=self.c_type.invoice_type,
                            description=cash_flow.name,
                            quantity=line_quantity,
                            unit=term.unit,
                            unit_price=term.unit_price,
                            account=l_account,
                            currency=self.currency.id,
                            taxes=list(taxes),
                            contract=self,
                            term=term,
                            base_object=first_obj.id if first_obj else None,
                            assignment_control='contract',
                        )
                        new_invoice_line.save()

                        cash_flow.state = 'done'
                        cash_flow.posting_date = cash_flow.document_date
                        cash_flow.create_moves_run_id = create_moves_run_id
                        group = lines_by_date[cash_flow.posting_date]
                        group['lines'].append(new_invoice_line)
                        if group['document_date'] is None:
                            group['document_date'] = cash_flow.document_date
                            group['due_date'] = cash_flow.due_date

                        cash_flow.invoice_line = new_invoice_line
                        cash_flow.save()

                        term.last_posting_date = cash_flow.posting_date
                        term.last_document_date = cash_flow.document_date
                        term.next_document_date = term.on_change_with_next_document_date()
                        term.next_due_date = term.on_change_with_next_due_date()
                        term.save()

        if not lines_by_date:
            self.add_log('process', f'contract {self.id} - no term computed')
            return

        if self.c_type.invoice_type == 'out':
            l_account = (
                self.c_type.account.id
                if self.c_type.account
                else self.contractual_partner.account_receivable.id
                if self.contractual_partner.account_receivable
                else config.default_account_receivable.id)
        else:
            l_account = (
                self.c_type.account.id
                if self.c_type.account
                else self.contractual_partner.account_payable.id
                if self.contractual_partner.account_payable
                else config.default_account_payable.id)

        for posting_date, group in sorted(lines_by_date.items()):
            invoice_lines = sorted(group['lines'], key=lambda l: l.description)
            document_date = group['document_date']
            due_date = group['due_date']
            inv_date = invoice_date or document_date

            l_description = self.c_type.mark if self.c_type.mark else self.c_type.name

            invoice = Invoice(
                company=self.company.id,
                type=self.c_type.invoice_type,
                party=self.contractual_partner.id,
                invoice_date=inv_date,
                accounting_date=posting_date,
                payment_term_date=due_date,
                invoice_address=self.get_invoice_address(),
                currency=self.currency.id,
                journal=self.c_type.account_journal.id,
                account=l_account,
                payment_term=self.payment_term.id if self.payment_term else None,
                description=f'{l_description} - {posting_date.strftime("%Y-%m-%d")}',
                reference=self.contract_number,
                lines=invoice_lines,
                contract=self,
            )
            Invoice.save([invoice])
            if invoice_state == 'posted':
                with Transaction().set_context(_skip_warnings=True):
                    Invoice.post([invoice])
            self.add_log('process',
                f'contract {self.id} / invoice {invoice.id} saved'
                f' (state={invoice_state}, posting_date={posting_date}).')

    @classmethod
    def cancel_period_booking(cls, cash_flow_lines, invoice_date=None):
        """Cancel a period booking run, given its already-booked
        (state='done') cash flow lines - one call per create_moves_run_id,
        analogous to BillingUnit.cancel_units for billing_run_id."""
        pool = Pool()
        Invoice = pool.get('account.invoice')
        CashFlowLine = pool.get('real_estate.contract.term.cash_flow')

        # 'posted' and 'paid' invoices are always reversed via a credit note
        # (never cancelled directly); only when the original is still open
        # ('posted') is it also reconciled against the new credit note's
        # matching line. Everything else (typically 'draft') is simply
        # cancelled. Same rule as BillingUnit.cancel_units.
        invoice_ids = {cf.invoice.id for cf in cash_flow_lines if cf.invoice}
        if invoice_ids:
            MoveLine = pool.get('account.move.line')
            invoices = Invoice.browse(list(invoice_ids))
            to_credit = [i for i in invoices if i.state in ('posted', 'paid')]
            to_cancel = [
                i for i in invoices if i.state not in ('posted', 'paid', 'cancelled')]

            if to_cancel:
                Invoice.cancel(to_cancel)

            if to_credit:
                new_invoices = Invoice.credit(
                    to_credit, refund=False, invoice_date=invoice_date)
                Invoice.post(new_invoices)

                for invoice, new_invoice in zip(to_credit, new_invoices):
                    if invoice.state != 'posted':
                        continue
                    open_lines = [
                        line for line in
                        list(invoice.lines_to_pay) + list(new_invoice.lines_to_pay)
                        if not line.reconciliation]
                    if open_lines and sum(
                            line.debit - line.credit
                            for line in open_lines) == Decimal(0):
                        MoveLine.reconcile(open_lines)

        # Reset the cash flow lines back to draft, unlinked from the
        # (now cancelled/credited) invoice line, so a future period
        # booking run recreates them. document_date/due_date belong to the
        # recurring schedule itself and are left untouched.
        CashFlowLine.write(list(cash_flow_lines), {
            'state': 'draft',
            'invoice_line': None,
            'posting_date': None,
            'create_moves_run_id': None,
        })

        contracts = {cf.contract for cf in cash_flow_lines if cf.contract}
        for contract in contracts:
            contract.add_log('cancel_period_booking',
                'Period booking cancelled.')

    @classmethod
    def call_create_moves(cls, contract_ids, date, action='re_calc', execute_in_queue=True, invoice_state='draft', invoice_date=None):
        """call create_moves in queue or directly based on execute_in_queue flag"""
        if len(contract_ids) > 0:
            # One run ID per property, generated once for this whole wizard
            # invocation (before chunking/queueing), so that all contracts
            # of the same property share the same create_moves_run_id even
            # if they end up in different chunks/queued jobs.
            property_run_ids = {}
            for contract in cls.browse(contract_ids):
                prop_id = str(contract.property.id)
                if prop_id not in property_run_ids:
                    property_run_ids[prop_id] = (
                        f"{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"
                        f"-U{Transaction().user}")

            chunks = [contract_ids[i:i+_chunk_size] for i in range(0, len(contract_ids), _chunk_size)]
            for chunk in chunks:
                if execute_in_queue:
                    transaction = Transaction()
                    context = transaction.context
                    with transaction.set_context(
                        queue_batch=context.get('queue_batch', True)):
                        cls.__queue__.create_moves(
                            chunk, date, action, invoice_state, invoice_date,
                            property_run_ids)
                else:
                    cls.create_moves(
                        chunk, date, action, invoice_state, invoice_date,
                        property_run_ids)

    @classmethod
    def create_moves(cls, contract_ids, date, action='re_calc', invoice_state='draft', invoice_date=None, property_run_ids=None):
        """Calculate and Create all account move on contract before a date."""
        property_run_ids = property_run_ids or {}
        for contract_id in contract_ids:
            contract = cls(contract_id)
            contract.add_log('process', f'start "create_moves" with date {date} and action {action}')
            if contract.state != 'running' and contract.state != 'terminated':
                contract.add_log('process', f'contract state {contract.state} - finished')
                continue
            effective_start = contract.start_booking_date or contract.start_date
            if effective_start > date:
                contract.add_log('process', f'contract booking start {effective_start} - finished')
                continue
            if contract.get_effective_end_date() is not None and contract.get_effective_end_date() < date:
                contract.add_log('process', f'contract effective_end_date {contract.get_effective_end_date()} - finished')
                continue

            process_terms = []
            for term in contract.terms:
                term.next_document_date = term.on_change_with_next_document_date()
                term.next_due_date = term.on_change_with_next_due_date()
                if action in ('re_calc', 're_calc_and_create'):
                    contract.add_log('process', f'term {term.name} with re-calc')
                    term.re_calc()
                # re_calc() may update the quantity of a measurement-based
                # term - save without a second cash flow rebuild via write()
                with Transaction().set_context(_skip_re_calc=True):
                    term.save()

                if term.next_document_date <= date \
                    and term.next_document_date != term.last_document_date \
                    and term.total_amount != 0:
                    contract.add_log('process', f'term {term.name} with total amount {term.total_amount}')
                    process_terms.append(term.id)

            if len(process_terms) > 0 and action in ('create', 're_calc_and_create'):
                run_id = property_run_ids.get(str(contract.property.id))
                cls._create_moves(
                    contract, process_terms, date, invoice_state,
                    invoice_date, run_id)

            contract.add_log('process', f'"create_moves" finished')
            contract.save()
