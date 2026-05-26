'Contract Core'
from trytond.model import (sequence_ordered,
    DeactivableMixin, ModelSQL, ModelView, Workflow, fields)
from trytond.model.exceptions import ValidationError
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

from sql import Column, Null
from sql.aggregate import Sum, Count, Min
from sql.conditionals import Coalesce
from collections import defaultdict
from itertools import groupby

from . import base_object
import logging
from decimal import Decimal
import datetime

from trytond.modules.account.account import _GeneralLedgerAccount
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
        line = Line.__table__()
        account = Account.__table__()
        contract = Contract.__table__()

        account_party = line.select(
                Min(line.id).as_('id'), line.account, line.party,
                where=line.party != Null,
                group_by=[line.account, line.party])

        columns = []
        for fname, field in cls._fields.items():
            if not hasattr(field, 'set'):
                if fname in {'id', 'account', 'party'}:
                    column = Column(account_party, fname)
                elif fname in {'contract'}:
                    column = Column(contract, 'id')
                else:
                    column = Column(account, fname)
                columns.append(column.as_(fname))
        return (
            account_party.join(
                account, condition=account_party.account == account.id)
            .join(
                contract, condition=account_party.party == contract.contractual_partner)
            .select(
                *columns,
                where=account.party_required))

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

    type_of_use = fields.Selection('get_term_types_of_use',
        "Type of Use",
        required=True,
        sort=False,
        states={
            'readonly': ((Eval('state') != 'draft') | ((Bool(Eval('c_type')) != False))),
            }
        )

    c_type = fields.Many2One(
        'real_estate.contract.type', "Contract Type", required=True,
        domain=[('types_of_use', 'in', Eval('type_of_use'))],
        states={
            'readonly': ((Eval('state') != 'draft')),
            'invisible': ((Bool(Eval('type_of_use', 0)) == False)),
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

    end_date = fields.Date('End Date',
        states={'readonly': ((Eval('state') != 'draft'))},
        required=False,
        domain=[If(Bool(Eval('end_date')), ('end_date', '>=', Eval('start_date', None)), ())],
        )

    start_booking_date = fields.Date('Start Booking Date',
        states={'readonly': ((Eval('state') != 'draft'))},
        domain=[If(Bool(Eval('end_date') & Eval('start_booking_date')), ('start_booking_date', '<=', Eval('end_date', None)), ()),
                If(Bool(Eval('start_date') & Eval('start_booking_date')), ('start_booking_date', '>=', Eval('start_date', None)), ())],
        )

    contract_number = fields.Char("No", states={'readonly': True})

    comment = fields.Text("Comment")

    date_of_signature = fields.Date('Date of Signature')

    contractual_partner = fields.Many2One(
        'party.party', "Contractual Partner", required=True, ondelete='CASCADE',
        states={
            'readonly': (Eval('terms', [0]) | (Eval('state') != 'draft')),
            })
    invoice_address = fields.Many2One('party.address', 'Invoice Address',
        required=True,
        domain=[('party', '=', Eval('contractual_partner', -1))])

    payment_term = fields.Many2One(
        'account.invoice.payment_term', "Payment Term",
        ondelete='RESTRICT')

    phone_partner = fields.Function(fields.Char("Phone Partner"), 'get_phone_partner')

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

    cash_flow_draft = fields.Function(
        fields.One2Many('real_estate.contract.term.cash_flow', None, 'Cash Flow draft', readonly=True),
        'on_change_with_cash_flow', setter='set_cash_flow')

    cash_flow_pending = fields.One2Many('account.invoice', 'contract', 'Cash Flow Pending',
        filter=['AND', [
            ('state', '!=', 'paid'),
            ('state', '!=', 'cancelled'),
        ]],
        order=[('invoice_date', 'ASC')],
        states={'readonly': True})

    cash_flow_paid = fields.One2Many('account.invoice', 'contract', 'Cash Flow Paid',
        filter=[('state', '=', 'paid')],
        order=[('invoice_date', 'ASC')],
        states={'readonly': True})

    meters = fields.Function(
        fields.One2Many('real_estate.base_object', None, 'Meters'),
        'on_change_with_meters', setter='set_meters')

    measurements = fields.Function(
        fields.One2Many('real_estate.measurement', None, 'Measurements'),
        'on_change_with_measurements', setter='set_measurements')

    cost_shares = fields.Function(
        fields.One2Many('real_estate.cost_share', None, 'Cost Shares', readonly=True),
        'get_cost_shares')

    _states_termination = {
            'invisible': ((Eval('state') != 'terminated')),
            }

    terminated_by_type = fields.Selection([
            (None, 'none'),
            ('tenant', 'Tenant'),
            ('landlord', 'Landlord')
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
        cls._transitions |= set((
            ('draft', 'running'),
            ('draft', 'cancelled'),
            ('running', 'terminated'),
            ('running', 'cancelled'),
            ('terminated', 'running'),
            ))
        cls._buttons.update({
            'running': {
                'invisible': (~Eval('state').in_(['draft', 'terminated'])),
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
                'invisible': ~Eval('state').in_(['draft', 'cancelled']),
                'depends': ['state'],
                },
            'open_party_ledger': {
                'invisible': (~Eval('state').in_(['draft']))
                }
            })

    @classmethod
    @ModelView.button
    def open_party_ledger(cls, contracts):
        for contract in contracts:
            if contract.contractual_partner:
                return 'act_party_ledger_from_contract', {
                    'contractual_partner': contract.contractual_partner.id
                }

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
        cls._refresh_occupancy_for_contracts(contrats)

    @classmethod
    @ModelView.button_action('real_estate.wizard_terminate_contract')
    def terminate(cls, contrats):
        pass

    @classmethod
    @ModelView.button
    @Workflow.transition('cancelled')
    @set_employee('cancelled_by')
    def cancel(cls, contrats):
        for contract in contrats:
            contract.add_log('state_change', f'contract state changed to cancelled')
            contract.state = 'cancelled'
            contract.save()
        cls._refresh_occupancy_for_contracts(contrats)

    @classmethod
    @ModelView.button
    def change_partner(cls, contrats):
        for contract in contrats:
            contract.add_log('change_partner', f'contract partner changed from {contract.contractual_partner.name if contract.contractual_partner else "None"} to {contract.contractual_partner.name if contract.contractual_partner else "None"}')
            contract.save()

    @classmethod
    def _refresh_occupancy_for_contracts(cls, contracts):
        pool = Pool()
        BaseObjectOccupancy = pool.get('real_estate.base_object.occupancy')
        BaseObject = pool.get('real_estate.base_object')
        ContractItem = pool.get('real_estate.contract.item')
        base_object_ids = set()
        for contract in contracts:
            for item in contract.items:
                if item.object:
                    base_object_ids.add(item.object.id)
        if base_object_ids:
            BaseObjectOccupancy.refresh(BaseObject.browse(list(base_object_ids)))
            ContractItem._trigger_billing_unit_selection(base_object_ids)

    _COMPUTE_VALUE_SHARES_FIELDS = frozenset({
        'state', 'start_date', 'end_date',
        'termination_date', 'terminated_by_type',
        'termination_notice', 'receipt_of_termination_notice',
    })

    @classmethod
    def write(cls, *args):
        super().write(*args)
        contract_ids = set()
        actions = iter(args)
        for records, values in zip(actions, actions):
            if cls._COMPUTE_VALUE_SHARES_FIELDS & set(values):
                for c in records:
                    contract_ids.add(c.id)
        if contract_ids:
            fresh = cls.browse(list(contract_ids))
            cls._refresh_occupancy_for_contracts(fresh)
            BaseObject = Pool().get('real_estate.base_object')
            property_ids = {c.property.id for c in fresh if c.property}
            if property_ids:
                BaseObject.compute_value_shares(
                    BaseObject.browse(list(property_ids)))

    @classmethod
    def set_cash_flow(cls, record, name, value):
        pass

    @fields.depends('company', 'items')
    def on_change_with_meters(self, name=None):
        return [child for item in self.items for child in item.children if child.e_type == 'meters']

    @fields.depends('company', 'items')
    def on_change_with_measurements(self, name=None):
        return [measurement for item in self.items if item.object for measurement in item.object.measurements]

    @classmethod
    def get_cost_shares(cls, contracts, name):
        pool = Pool()
        CostShare = pool.get('real_estate.cost_share')
        result = {c.id: [] for c in contracts}
        contract_ids = [c.id for c in contracts]
        shares = CostShare.search([
            ('contract', 'in', contract_ids),
            ('settlement_unit.billing_unit.state', 'not in', ['draft', 'billed']),
        ])
        for share in shares:
            result[share.contract.id].append(share.id)
        return result

    @classmethod
    def get_term_types_of_use(cls):
        pool = Pool()
        BaseObject = pool.get('real_estate.base_object')
        return BaseObject.fields_get(['type_of_use'])['type_of_use']['selection']

    @classmethod
    def default_company(cls):
        return Transaction().context.get('company')

    def get_effective_end_date(self):
        if self.termination_date and (
                not self.end_date or self.termination_date < self.end_date):
            return self.termination_date
        return self.end_date

    @fields.depends('terms')
    def on_change_with_cash_flow(self, name=None):
        return sorted([cash_flow_line for term in self.terms for cash_flow_line in term.cash_flow
                        if (cash_flow_line.invoice is None or cash_flow_line.state == 'draft')],
                    key=lambda line: (line.document_date, line.posting_date, line.name))

    def add_log(self, event, description=None):
        pool = Pool()
        ContractLog = pool.get('real_estate.contract.log')
        ContractLog.create([{
            'contract': self.id,
            'event': event,
            'description': description or '',
        }])
        print(f'contract {self.id}, event {event}, description {description}')

    @staticmethod
    def default_state():
        return 'draft'

    @staticmethod
    def default_start_date():
        return Pool().get('ir.date').today().replace(day=1)

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
        if self.contractual_partner:
            self.invoice_address = self.contractual_partner.address_get(type='invoice')
            if self.c_type.invoice_type == 'out':
                self.payment_term = self.contractual_partner.customer_payment_term
            elif self.c_type.invoice_type == 'in':
                self.payment_term = self.contractual_partner.supplier_payment_term
        else:
            self.invoice_address = None
            self.payment_term = None

    @fields.depends('company')
    def on_change_with_currency(self, name=None):
        return self.company.currency if self.company else None

    @fields.depends('c_type', 'property', 'company')
    def on_change_with_sequence(self, name=None):
        if (self.sequence != None and self.sequence != 0):
            return self.sequence
        if self.c_type != None and self.property != None and self.company != None:
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
        if self.c_type == None or self.property == None or not self.sequence:
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

    def get_phone_partner(self, name=None):
        if self.contractual_partner:
            Party = Pool().get('party.party')
            party = Party(self.contractual_partner)
            phone = party.contact_mechanism_get(types='phone')
            if phone:
                return phone.value.replace('\n', ' / ')
        return ''

    @classmethod
    def set_meters(cls, record, name, value):
        pass

    @classmethod
    def set_measurements(cls, record, name, value):
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

    def _create_moves(self, terms, date, invoice_state='draft', invoice_date=None):
        self.add_log('process', f'start quere contract {self.id} at {date}')
        if not terms:
            self.add_log('process', f'stop quere contract {self.id} at {date} - no terms')
            return

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
                        new_invoice_line = InvoiceLine(
                            type='line',
                            company=self.company.id,
                            party=self.contractual_partner.id,
                            invoice_type=self.c_type.invoice_type,
                            description=cash_flow.name,
                            quantity=term.quantity,
                            unit=term.unit,
                            unit_price=term.unit_price,
                            account=l_account,
                            currency=self.currency.id,
                            taxes=list(taxes),
                            contract=self,
                            term=term,
                        )
                        new_invoice_line.save()

                        cash_flow.state = 'done'
                        cash_flow.posting_date = cash_flow.document_date
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
            l_account = self.contractual_partner.account_receivable.id \
                if self.contractual_partner.account_receivable \
                else config.default_account_receivable.id
        else:
            l_account = self.contractual_partner.account_payable.id \
                if self.contractual_partner.account_payable \
                else config.default_account_payable.id

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
                invoice_address=self.invoice_address,
                currency=self.currency.id,
                journal=self.c_type.account_journal.id,
                account=self.c_type.account.id if self.c_type.account else l_account,
                payment_term=self.payment_term.id if self.payment_term else None,
                description=f'{l_description} - {posting_date.strftime("%Y-%m-%d")}',
                reference=self.contract_number,
                lines=invoice_lines,
                contract=self,
            )
            Invoice.save([invoice])
            if invoice_state == 'posted':
                Invoice.post([invoice])
            self.add_log('process',
                f'contract {self.id} / invoice {invoice.id} saved'
                f' (state={invoice_state}, posting_date={posting_date}).')

    @classmethod
    def call_create_moves(cls, contract_ids, date, action='re_calc', execute_in_queue=True, invoice_state='draft', invoice_date=None):
        """call create_moves in queue or directly based on execute_in_queue flag"""
        if len(contract_ids) > 0:
            chunks = [contract_ids[i:i+_chunk_size] for i in range(0, len(contract_ids), _chunk_size)]
            for chunk in chunks:
                if execute_in_queue:
                    transaction = Transaction()
                    context = transaction.context
                    with transaction.set_context(
                        queue_batch=context.get('queue_batch', True)):
                        cls.__queue__.create_moves(chunk, date, action, invoice_state, invoice_date)
                else:
                    cls.create_moves(chunk, date, action, invoice_state, invoice_date)

    @classmethod
    def create_moves(cls, contract_ids, date, action='re_calc', invoice_state='draft', invoice_date=None):
        """Calculate and Create all account move on contract before a date."""
        for contract_id in contract_ids:
            contract = cls(contract_id)
            contract.add_log('process', f'start "create_moves" with date {date} and action {action}')
            if contract.state != 'running' and contract.state != 'terminated':
                contract.add_log('process', f'contract state {contract.state} - finished')
                exit
            effective_start = contract.start_booking_date or contract.start_date
            if effective_start > date:
                contract.add_log('process', f'contract booking start {effective_start} - finished')
                exit
            if contract.get_effective_end_date() != None and contract.get_effective_end_date() < date:
                contract.add_log('process', f'contract effective_end_date {contract.get_effective_end_date()} - finished')
                exit

            process_terms = []
            for term in contract.terms:
                term.next_document_date = term.on_change_with_next_document_date()
                term.next_due_date = term.on_change_with_next_due_date()
                if action in ('re_calc', 're_calc_and_create'):
                    contract.add_log('process', f'term {term.name} with re-calc')
                    term.re_calc()
                term.save()

                if term.next_document_date <= date \
                    and term.next_document_date != term.last_document_date \
                    and term.total_amount != 0:
                    contract.add_log('process', f'term {term.name} with total amount {term.total_amount}')
                    process_terms.append(term.id)

            if len(process_terms) > 0 and action in ('create', 're_calc_and_create'):
                cls._create_moves(contract, process_terms, date, invoice_state, invoice_date)

            contract.add_log('process', f'"create_moves" finished')
            contract.save()
