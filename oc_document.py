'''Operating cost assignment (Betriebskostenzuordnung): the postings on the
accounts of the cost types with a property are assigned to settlement
units, contracts or the owner - specification:
specs/spezifikation-betriebskostenzuordnung.md'''
from decimal import ROUND_HALF_UP, Decimal

from dateutil.relativedelta import relativedelta

from trytond.exceptions import UserWarning
from trytond.i18n import gettext
from trytond.model import (
    ModelSQL, ModelView, Unique, Workflow, dualmethod, fields,
    sequence_ordered)
from trytond.model.exceptions import AccessError, ValidationError
from trytond.modules.company.model import (
    CompanyMultiValueMixin, CompanyValueMixin, employee_field)
from trytond.modules.currency.fields import Monetary
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Bool, Eval, If
from trytond.transaction import Transaction, without_check_access
from trytond.wizard import Button, StateTransition, StateView, Wizard

from . import bved_records

STATES = [
    ('open', "Open"),
    ('proposed', "Proposed"),
    ('confirmed', "Confirmed"),
    ]

TARGETS = [
    ('settlement_unit', "Settlement Unit"),
    ('contract', "Contract + Settlement Unit"),
    ('property', "Property (Owner)"),
    ]

ESTG_35A = [
    ('', 'none'),
    ('abs1', 'Para. 1 - Minor Employment in the Household'),
    ('abs2', 'Para. 2 - Household-Related Services (e.g. Garden Maintenance)'),
    ('abs3', 'Para. 3 - Craftsmen Services (e.g. Chimney Sweep)'),
    ]

# Billing unit states in which the assignment can no longer be changed
LOCKED_STATES = ('ready_for_billing', 'billed')

_CENT = Decimal('0.01')


def distribute(amount, weights):
    """Split 'amount' in proportion to 'weights' into cent amounts which
    sum up exactly to 'amount' - the rounding remainder goes to the last
    non-zero weight"""
    weights = [Decimal(str(w or 0)) for w in weights]
    total = sum(weights)
    if not weights:
        return []
    if not total:
        return [Decimal(0)] * len(weights)
    result = [(amount * w / total).quantize(_CENT, rounding=ROUND_HALF_UP)
        for w in weights]
    rest = amount - sum(result)
    if rest:
        last = max(i for i, w in enumerate(weights) if w)
        result[last] += rest
    return result


def split_by_days(start, end, periods):
    """Days of [start, end] falling into each of 'periods' - a list of
    (key, period start, period end); returns [(key, from, to, days)] of
    the overlapping periods in the given order"""
    result = []
    for key, p_start, p_end in periods:
        part_start = max(start, p_start)
        part_end = min(end, p_end)
        if part_start <= part_end:
            result.append(
                (key, part_start, part_end, (part_end - part_start).days + 1))
    return result


def _property_of(obj):
    node = obj
    while node and node.type != 'property':
        node = node.parent
    return node


def _period_of(billing_unit):
    return (billing_unit.start_date, billing_unit.start_date
        + relativedelta(years=1) - relativedelta(days=1))


#**********************************************************************
class CostType(CompanyMultiValueMixin, metaclass=PoolMeta):
    __name__ = 'real_estate.cost_type'

    account = fields.MultiValue(fields.Many2One('account.account',
            "Account",
            domain=[
                ('closed', '!=', True),
                ('company', '=', Eval('context', {}).get('company', -1)),
                ],
            states={
                'invisible': ~Eval('context', {}).get('company'),
                },
            help="Account the costs of this cost type are posted on (per "
                 "company). Every posted line on this account with a "
                 "property has to be assigned in 'Assign Operating "
                 "Costs'."))
    accounts = fields.One2Many('real_estate.cost_type.account', 'cost_type',
        "Accounts")

    @classmethod
    def multivalue_model(cls, field):
        if field == 'account':
            return Pool().get('real_estate.cost_type.account')
        return super().multivalue_model(field)

    @classmethod
    def oc_account_ids(cls, company_id=None):
        "Ids of the operating cost accounts (accounts of the cost types)"
        Value = Pool().get('real_estate.cost_type.account')
        domain = [('account', '!=', None)]
        if company_id:
            domain.append(('company', '=', company_id))
        return {v.account.id for v in Value.search(domain)}

    @classmethod
    def ids_of_account(cls, account):
        "Ids of the cost types with the operating cost account 'account'"
        Value = Pool().get('real_estate.cost_type.account')
        return list({v.cost_type.id for v in Value.search([
                        ('account', '=', account.id),
                        ])})


class CostTypeAccount(ModelSQL, CompanyValueMixin):
    "Cost Type Account"
    __name__ = 'real_estate.cost_type.account'

    cost_type = fields.Many2One('real_estate.cost_type', "Cost Type",
        ondelete='CASCADE',
        context={'company': Eval('company', -1)},
        depends={'company'})
    account = fields.Many2One('account.account', "Account",
        domain=[('company', '=', Eval('company', -1))])


def _other_level(line):
    """True for a move line on another object than a property or a rental
    object (building, land, equipment ...) - no operating cost document
    (E33)"""
    obj = getattr(line, 'base_object', None)
    return bool(obj and obj.type not in ('property', 'object'))


class OcOtherLevelWarning(UserWarning):
    pass


#**********************************************************************
class Move(metaclass=PoolMeta):
    __name__ = 'account.move'

    @classmethod
    def _get_origin(cls):
        # cost reclassification moves of the operating cost settlement
        return super()._get_origin() + ['real_estate.billing_unit']

    @dualmethod
    @ModelView.button
    def post(cls, moves):
        pool = Pool()
        CostType = pool.get('real_estate.cost_type')
        Warning = pool.get('res.user.warning')
        # operating cost line on another level than property / rental
        # object: no part of the settlement (E33) - only a hint
        with without_check_access(), Transaction().set_context(
                active_test=False):
            account_ids = CostType.oc_account_ids()
        other = [l for m in cls.browse(moves) for l in m.lines
            if l.account.id in account_ids and _other_level(l)]
        if other:
            key = Warning.format('oc_other_level', other)
            if Warning.check(key):
                raise OcOtherLevelWarning(key, gettext(
                        'real_estate.msg_oc_other_level_warning',
                        objects=', '.join(sorted({
                                    l.base_object.rec_name for l in other}))))
        super().post(moves)
        Document = pool.get('real_estate.oc_document')
        # the posting user needs no access to the operating cost documents
        with without_check_access():
            Document.create_for_lines(
                [l for m in cls.browse(moves) for l in m.lines])


#**********************************************************************
class OcDocument(Workflow, ModelSQL, ModelView):
    "Operating Cost Document"
    __name__ = 'real_estate.oc_document'

    company = fields.Many2One('company.company', "Company", required=True,
        readonly=True)
    move_line = fields.Many2One('account.move.line', "Move Line",
        required=True, readonly=True, ondelete='CASCADE')
    move = fields.Function(fields.Many2One('account.move', "Move"),
        'on_change_with_move')
    property = fields.Many2One('real_estate.base_object', "Property",
        readonly=True, domain=[('type', '=', 'property')],
        help="Empty: the posting has no property - it can only be assigned "
             "after a correction posting with property.")
    base_object = fields.Many2One('real_estate.base_object', "Booked Object",
        readonly=True,
        help="Object of the posting: the property (normal case, distributed "
             "by a settlement unit) or a rental object (cost of this rental "
             "object, not distributed - E31).")
    contract = fields.Many2One('real_estate.contract', "Contract",
        readonly=True,
        help="Contract of the posting on a rental object - the cost goes "
             "to this contract (E32).")
    date = fields.Date("Date", readonly=True)
    account = fields.Many2One('account.account', "Account", readonly=True)
    party = fields.Many2One('party.party', "Supplier", readonly=True)
    description = fields.Char("Description", readonly=True)
    invoice = fields.Many2One('account.invoice', "Invoice", readonly=True)
    invoice_line = fields.Many2One('account.invoice.line', "Invoice Line",
        readonly=True)
    currency = fields.Function(fields.Many2One('currency.currency',
            "Currency"), 'on_change_with_currency')
    amount_booked = Monetary("Booked", currency='currency',
        digits='currency', readonly=True,
        help="Debit - credit of the posting on the cost account (net plus "
             "non-deductible input tax).")
    amount_net = Monetary("Net", currency='currency', digits='currency',
        readonly=True)
    amount_gross = Monetary("Gross", currency='currency',
        digits='currency', readonly=True,
        help="Net plus the full tax of the invoice line - equal to net "
             "without invoice.")
    lines = fields.One2Many('real_estate.oc_document.line', 'document',
        "Assignment",
        states={'readonly': Eval('state') == 'confirmed'})
    assigned_net = fields.Function(Monetary("Assigned Net",
            currency='currency', digits='currency'), 'get_sums')
    assigned_gross = fields.Function(Monetary("Assigned Gross",
            currency='currency', digits='currency'), 'get_sums')
    open_net = fields.Function(Monetary("Open Net", currency='currency',
            digits='currency'), 'get_sums')
    open_gross = fields.Function(Monetary("Open Gross",
            currency='currency', digits='currency'), 'get_sums')
    summary = fields.Function(fields.Char("Assignment Summary"),
        'get_summary')
    history = fields.Function(fields.One2Many('real_estate.oc_document',
            None, "Earlier Assignments",
            help="Confirmed documents of the same supplier and account - "
                 "first of the own property, then of other properties."),
        'get_history', setter='set_history')
    state = fields.Selection(STATES, "State", readonly=True, required=True,
        sort=False)
    confirmed_by = employee_field("Confirmed by", states=['confirmed'])
    confirmed_date = fields.Date("Confirmed on", readonly=True)

    @classmethod
    def __setup__(cls):
        super().__setup__()
        t = cls.__table__()
        cls._sql_constraints += [
            ('move_line_unique', Unique(t, t.move_line),
                'real_estate.msg_oc_document_move_line_unique'),
            ]
        cls._order = [('date', 'DESC'), ('id', 'DESC')]
        cls._transitions |= {
            ('proposed', 'confirmed'),
            ('confirmed', 'proposed'),
            }
        cls._buttons.update({
            'propose': {
                'invisible': (Eval('state') == 'confirmed')
                | ~Eval('property'),
                'depends': ['state', 'property'],
                },
            'confirm': {
                'invisible': Eval('state') != 'proposed',
                'depends': ['state'],
                },
            'reset': {
                'invisible': Eval('state') != 'confirmed',
                'depends': ['state'],
                },
            'split_period': {
                'invisible': (Eval('state') == 'confirmed')
                | ~Eval('property'),
                'depends': ['state', 'property'],
                },
            'take_history': {
                'invisible': (Eval('state') == 'confirmed')
                | ~Eval('property'),
                'depends': ['state', 'property'],
                },
            })

    @staticmethod
    def default_state():
        return 'open'

    @fields.depends('move_line', '_parent_move_line.move')
    def on_change_with_move(self, name=None):
        return self.move_line.move if self.move_line else None

    @fields.depends('company', '_parent_company.currency')
    def on_change_with_currency(self, name=None):
        return self.company.currency if self.company else None

    def get_rec_name(self, name):
        return ' - '.join(filter(None, [
                    self.date.strftime('%d.%m.%Y') if self.date else '',
                    self.party.rec_name if self.party else '',
                    self.account.code if self.account else '',
                    str(self.amount_gross)
                    if self.amount_gross is not None else '']))

    @classmethod
    def search_rec_name(cls, name, clause):
        if clause[1].startswith('!') or clause[1].startswith('not '):
            bool_op = 'AND'
        else:
            bool_op = 'OR'
        return [bool_op,
            ('party.rec_name',) + tuple(clause[1:]),
            ('description',) + tuple(clause[1:]),
            ('invoice.rec_name',) + tuple(clause[1:]),
            ]

    @classmethod
    def get_sums(cls, documents, names):
        result = {n: {} for n in names}
        for doc in documents:
            net = sum((l.amount_net or Decimal(0) for l in doc.lines),
                Decimal(0))
            gross = sum((l.amount_gross or Decimal(0) for l in doc.lines),
                Decimal(0))
            values = {
                'assigned_net': net,
                'assigned_gross': gross,
                'open_net': (doc.amount_net or Decimal(0)) - net,
                'open_gross': (doc.amount_gross or Decimal(0)) - gross,
                }
            for name in names:
                result[name][doc.id] = values[name]
        return result

    def get_summary(self, name):
        return ', '.join(l.get_summary() for l in self.lines)

    @classmethod
    def set_history(cls, documents, name, value):
        pass

    def get_history(self, name):
        if not self.account:
            return []
        domain = [
            ('state', '=', 'confirmed'),
            ('account', '=', self.account.id),
            ('party', '=', self.party.id if self.party else None),
            ('id', '!=', self.id),
            ]
        own = self.search(domain
            + [('property', '=', self.property.id if self.property else None)],
            limit=10)
        others = self.search(domain + [
                ('property', '!=', None),
                ('property', '!=',
                    self.property.id if self.property else None),
                ], limit=10)
        return [d.id for d in own + others]

    # --- creation from postings ------------------------------------------

    @classmethod
    def _document_values(cls, line):
        "Values of the document of the posted move line 'line'"
        pool = Pool()
        InvoiceLine = pool.get('account.invoice.line')
        booked = (line.debit or Decimal(0)) - (line.credit or Decimal(0))
        values = {
            'company': line.move.company.id,
            'move_line': line.id,
            'date': line.date,
            'account': line.account.id,
            'party': line.party.id if line.party else None,
            'description': line.description or line.move.description,
            'amount_booked': booked,
            'amount_net': booked,
            'amount_gross': booked,
            'state': 'open',
            }
        obj = getattr(line, 'base_object', None)
        prop = _property_of(obj) if obj else None
        values['property'] = prop.id if prop else None
        values['base_object'] = obj.id if obj else None
        contract = getattr(line, 'contract', None)
        values['contract'] = (contract.id
            if contract and obj and obj.type == 'object' else None)
        origin = line.origin
        if isinstance(origin, InvoiceLine) and origin.invoice:
            values['invoice_line'] = origin.id
            values['invoice'] = origin.invoice.id
            if not values['party'] and origin.invoice.party:
                values['party'] = origin.invoice.party.id
            values['description'] = (origin.description
                or values['description'])
            currency = origin.invoice.currency
            net = currency.round(
                Decimal(str(origin.quantity or 0))
                * (origin.unit_price or Decimal(0)))
            gross = origin.total_amount or net
            base = origin.amount or Decimal(0)
            # factor of the posting to the invoice line: sign of a
            # cancellation/credit note and currency conversion
            factor = (booked / base) if base else Decimal(1)
            values['amount_net'] = (net * factor).quantize(_CENT)
            values['amount_gross'] = (gross * factor).quantize(_CENT)
        return values

    @classmethod
    def create_for_lines(cls, lines):
        """Create the documents of the posted move lines on operating cost
        accounts (accounts of a cost type) not yet having one - postings in
        adjustment periods (opening/closing) are excluded. Returns the
        documents created."""
        pool = Pool()
        CostType = pool.get('real_estate.cost_type')
        # without the cost reclassification of the settlement (and its
        # cancellation): it is no new cost
        lines = [l for l in lines
            if l.move.state == 'posted'
            and l.move.period and l.move.period.type == 'standard'
            and getattr(l, 'assignment_control', None) != 'oc_reclass']
        if not lines:
            return []
        with Transaction().set_context(active_test=False):
            account_ids = CostType.oc_account_ids()
        lines = [l for l in lines if l.account.id in account_ids
            and not _other_level(l)]
        if not lines:
            return []
        existing = {d.move_line.id for d in cls.search([
                    ('move_line', 'in', [l.id for l in lines]),
                    ])}
        vlist = [cls._document_values(l) for l in lines
            if l.id not in existing]
        return cls.create(vlist) if vlist else []

    @classmethod
    def update_documents(cls, company_id):
        """Create the missing documents of all posted lines of the company
        on operating cost accounts (e.g. after an account was added to a
        cost type). Returns the number created."""
        pool = Pool()
        CostType = pool.get('real_estate.cost_type')
        MoveLine = pool.get('account.move.line')
        with Transaction().set_context(active_test=False):
            account_ids = CostType.oc_account_ids(company_id)
        if not account_ids:
            return 0
        lines = MoveLine.search([
                ('account', 'in', list(account_ids)),
                ('move.state', '=', 'posted'),
                ('move.company', '=', company_id),
                ])
        return len(cls.create_for_lines(lines))

    # --- state -----------------------------------------------------------

    def _sums_match(self):
        sums = self.get_sums([self], ['open_net', 'open_gross'])
        return (bool(self.lines) and not sums['open_net'][self.id]
            and not sums['open_gross'][self.id])

    @classmethod
    def update_state(cls, documents):
        """open / proposed from the sums of the lines - a change of the
        assignment of a confirmed document makes it proposed again"""
        for doc in cls.browse([d.id for d in documents]):
            state = 'proposed' if doc._sums_match() else 'open'
            if doc.state != state:
                cls.write([doc], {
                        'state': state,
                        'confirmed_by': None,
                        'confirmed_date': None,
                        })

    @classmethod
    def check_locked(cls, documents):
        "The assignment of a ready or billed billing unit cannot change"
        for doc in documents:
            for line in doc.lines:
                line.check_locked()

    @classmethod
    def delete(cls, documents):
        cls.check_locked(documents)
        super().delete(documents)

    # --- buttons ---------------------------------------------------------

    @classmethod
    @ModelView.button
    def propose(cls, documents):
        Line = Pool().get('real_estate.oc_document.line')
        documents = [d for d in documents
            if d.state != 'confirmed' and d.property]
        cls.check_locked(documents)
        for doc in documents:
            Line.delete(list(doc.lines))
            vlist = doc._proposal()
            if vlist:
                Line.create(vlist)
        cls.update_state(documents)

    @classmethod
    @ModelView.button
    @Workflow.transition('confirmed')
    def confirm(cls, documents):
        pool = Pool()
        User = pool.get('res.user')
        Date = pool.get('ir.date')
        user = User(Transaction().user)
        for doc in documents:
            if not doc._sums_match():
                raise ValidationError(gettext(
                        'real_estate.msg_oc_document_sums',
                        document=doc.rec_name))
            for line in doc.lines:
                line.check_complete()
        cls.write(documents, {
                'confirmed_by': user.employee.id if user.employee else None,
                'confirmed_date': Date.today(),
                })

    @classmethod
    @ModelView.button
    @Workflow.transition('proposed')
    def reset(cls, documents):
        cls.check_locked(documents)
        cls.write(documents, {
                'confirmed_by': None,
                'confirmed_date': None,
                })

    @classmethod
    @ModelView.button_action('real_estate.wizard_oc_document_split')
    def split_period(cls, documents):
        pass

    @classmethod
    @ModelView.button_action('real_estate.wizard_oc_document_history')
    def take_history(cls, documents):
        pass

    # --- proposal --------------------------------------------------------

    def _open_settlement_units(self, cost_type_ids):
        """Settlement units of the cost types of this property whose
        billing unit can still be changed"""
        SettlementUnit = Pool().get('real_estate.settlement_unit')
        if not cost_type_ids or not self.property:
            return []
        return SettlementUnit.search([
                ('billing_unit.property', '=', self.property.id),
                ('type', 'in', list(cost_type_ids)),
                ('billing_unit.state', 'not in', LOCKED_STATES),
                ])

    @staticmethod
    def _covers(settlement_unit, date):
        start, end = _period_of(settlement_unit.billing_unit)
        return start <= date <= end

    def _account_cost_type_ids(self):
        CostType = Pool().get('real_estate.cost_type')
        if not self.account:
            return []
        return CostType.ids_of_account(self.account)

    @staticmethod
    def _chain(settlement_unit):
        """The settlement unit with its predecessors and successors (the
        same settlement unit in the other periods)"""
        SettlementUnit = Pool().get('real_estate.settlement_unit')
        chain = [settlement_unit]
        seen = {settlement_unit.id}
        node = settlement_unit.predecessor
        while node and node.id not in seen:
            chain.append(node)
            seen.add(node.id)
            node = node.predecessor
        node = settlement_unit
        while True:
            successors = SettlementUnit.search([
                    ('predecessor', '=', node.id),
                    ], limit=1)
            if not successors or successors[0].id in seen:
                break
            node = successors[0]
            chain.append(node)
            seen.add(node.id)
        return chain

    def _map_settlement_unit(self, settlement_unit, date):
        """The settlement unit for 'date' - the same one of another period
        (predecessor/successor), else the only open settlement unit of its
        cost type in this property"""
        if settlement_unit.billing_unit.property == self.property:
            for su in self._chain(settlement_unit):
                if (self._covers(su, date)
                        and su.billing_unit.state not in LOCKED_STATES):
                    return su
        candidates = [su for su in self._open_settlement_units(
                [settlement_unit.type.id]) if self._covers(su, date)]
        return candidates[0] if len(candidates) == 1 else None

    def object_booked(self):
        "The rental object the document is booked on (E31), else None"
        obj = self.base_object
        return obj if obj and obj.type == 'object' else None

    def _proposal(self):
        "Values of the proposed lines (stages 1-4 of the specification)"
        date = self.date
        obj = self.object_booked()
        # 1. account unique: one cost type with one settlement unit
        cost_type_ids = self._account_cost_type_ids()
        su = None
        if len(cost_type_ids) == 1:
            sus = [su for su in self._open_settlement_units(cost_type_ids)
                if self._covers(su, date)]
            if len(sus) == 1:
                su = sus[0]
        # booked on a rental object with contract: to this contract (E32)
        if obj and self.contract and su:
            return self._lines_values([{
                        'target': 'contract',
                        'contract': self.contract.id,
                        'base_object': obj.id,
                        'settlement_unit': su.id,
                        'percent': Decimal(100),
                        'proposal_source': gettext(
                            'real_estate.msg_oc_proposal_object_contract',
                            object=obj.rec_name),
                        }])
        if su:
            return self._lines_values([{
                        'target': 'settlement_unit',
                        'settlement_unit': su.id,
                        'percent': Decimal(100),
                        'proposal_source': gettext(
                            'real_estate.msg_oc_proposal_object'
                            if obj else 'real_estate.msg_oc_proposal_account',
                            object=obj.rec_name if obj else ''),
                        }])
        # 2. as last time for this property, 3. as for another property
        for doc in self.get_history_documents():
            values = self._values_from(doc)
            if values:
                if obj:
                    values = self._to_object(values, obj)
                if values:
                    return values
        return []

    def _to_object(self, values, obj):
        """Proposed lines of a document booked on a rental object (E32):
        the settlement units of the history, target this contract or (without
        contract) the settlement unit for this rental object only"""
        result = []
        for value in values:
            if not value.get('settlement_unit'):
                continue
            value = dict(value)
            if self.contract:
                value.update({
                        'target': 'contract',
                        'contract': self.contract.id,
                        'base_object': obj.id,
                        })
            else:
                value.update({'target': 'settlement_unit',
                        'contract': None, 'base_object': None})
            result.append(value)
        return result

    def get_history_documents(self):
        return self.browse(self.get_history(None))

    def _values_from(self, source):
        """Lines of 'source' transferred to this document (settlement units
        of the matching period, same percentages) - [] if none of its
        settlement units can be transferred"""
        same_property = source.property == self.property
        key = ('real_estate.msg_oc_proposal_history' if same_property
            else 'real_estate.msg_oc_proposal_other_property')
        source_text = gettext(key, document=source.rec_name,
            property=source.property.rec_name if source.property else '')
        years = (self.date.year - source.date.year
            if self.date and source.date else 0)
        values = []
        mapped = False
        for line in source.lines:
            value = {
                'target': line.target,
                'percent': line.get_percent(),
                'estg_35a': line.estg_35a,
                'estg_35a_labor_share_percent':
                    line.estg_35a_labor_share_percent,
                'bved_fuel_type': line.bved_fuel_type,
                'comment': line.comment,
                'proposal_source': source_text,
                }
            if line.service_period_from and line.service_period_to:
                value['service_period_from'] = (
                    line.service_period_from + relativedelta(years=years))
                value['service_period_to'] = (
                    line.service_period_to + relativedelta(years=years))
            if line.target == 'property':
                if not same_property:
                    continue
                mapped = True
            else:
                su = (self._map_settlement_unit(line.settlement_unit,
                        value.get('service_period_from') or self.date)
                    if line.settlement_unit else None)
                if su:
                    mapped = True
                    value['settlement_unit'] = su.id
                if line.target == 'contract':
                    if not same_property:
                        continue
                    value['contract'] = (line.contract.id
                        if line.contract else None)
                    value['base_object'] = (line.base_object.id
                        if line.base_object else None)
            values.append(value)
        if not mapped:
            return []
        return self._lines_values(values)

    def _lines_values(self, values):
        """Complete the line values: document, sequence and the amounts
        from the percentages (exact sums)"""
        nets = distribute(self.amount_net or Decimal(0),
            [v['percent'] for v in values])
        grosses = distribute(self.amount_gross or Decimal(0),
            [v['percent'] for v in values])
        for i, (value, net, gross) in enumerate(
                zip(values, nets, grosses)):
            value.update({
                    'document': self.id,
                    'sequence': (i + 1) * 10,
                    'amount_net': net,
                    'amount_gross': gross,
                    })
        return values

    def split_lines(self, start, end):
        """Split the lines with a settlement unit day by day onto the
        settlement units of the periods of [start, end] (same settlement
        unit in the other periods via predecessor/successor)"""
        Line = Pool().get('real_estate.oc_document.line')
        self.check_locked([self])
        new = []
        to_delete = []
        for line in self.lines:
            if not line.settlement_unit:
                Line.write([line], {
                        'service_period_from': start,
                        'service_period_to': end,
                        })
                continue
            chain = self._chain(line.settlement_unit)
            periods = [(su, *_period_of(su.billing_unit)) for su in chain]
            parts = split_by_days(start, end, periods)
            covered = sum(p[3] for p in parts)
            if covered != (end - start).days + 1:
                raise ValidationError(gettext(
                        'real_estate.msg_oc_split_period_missing',
                        settlement_unit=line.settlement_unit.rec_name,
                        start=start.strftime('%d.%m.%Y'),
                        end=end.strftime('%d.%m.%Y')))
            days = [p[3] for p in parts]
            nets = distribute(line.amount_net or Decimal(0), days)
            grosses = distribute(line.amount_gross or Decimal(0), days)
            for (su, part_start, part_end, _), net, gross in zip(
                    parts, nets, grosses):
                if su.billing_unit.state in LOCKED_STATES:
                    raise AccessError(gettext(
                            'real_estate.msg_oc_line_locked',
                            billing_unit=su.billing_unit.rec_name))
                new.append({
                        'document': self.id,
                        'target': line.target,
                        'settlement_unit': su.id,
                        'contract': line.contract.id
                        if line.contract else None,
                        'base_object': line.base_object.id
                        if line.base_object else None,
                        'amount_net': net,
                        'amount_gross': gross,
                        'service_period_from': part_start,
                        'service_period_to': part_end,
                        'estg_35a': line.estg_35a,
                        'estg_35a_labor_share_percent':
                            line.estg_35a_labor_share_percent,
                        'bved_fuel_type': line.bved_fuel_type,
                        'comment': line.comment,
                        'proposal_source': line.proposal_source,
                        })
            to_delete.append(line)
        if to_delete:
            Line.delete(to_delete)
        if new:
            for i, value in enumerate(new):
                value['sequence'] = (i + 1) * 10
            Line.create(new)
        self.update_state([self])


#**********************************************************************
class OcDocumentLine(sequence_ordered(), ModelSQL, ModelView):
    "Operating Cost Document Line"
    __name__ = 'real_estate.oc_document.line'

    document = fields.Many2One('real_estate.oc_document', "Document",
        required=True, ondelete='CASCADE')
    property = fields.Function(fields.Many2One('real_estate.base_object',
            "Property"), 'on_change_with_property')
    account = fields.Function(fields.Many2One('account.account',
            "Account"), 'on_change_with_account')
    currency = fields.Function(fields.Many2One('currency.currency',
            "Currency"), 'on_change_with_currency')
    # Document data for the lists on settlement unit and billing unit
    document_date = fields.Function(fields.Date("Document Date"),
        'get_document_field')
    document_party = fields.Function(fields.Many2One('party.party',
            "Supplier"), 'get_document_field')
    document_invoice = fields.Function(fields.Many2One('account.invoice',
            "Invoice"), 'get_document_field')
    document_state = fields.Function(fields.Selection(STATES,
            "Document State"), 'get_document_field')
    target = fields.Selection(TARGETS, "Target", required=True, sort=False)
    settlement_unit = fields.Many2One('real_estate.settlement_unit',
        "Settlement Unit", ondelete='RESTRICT',
        domain=[
            ('billing_unit.property', '=', Eval('property', -1)),
            ('type.accounts.account', '=', Eval('account', -1)),
            ],
        states={
            'invisible': Eval('target') == 'property',
            'required': Eval('target') != 'property',
            },
        help="Only settlement units of this property whose cost type has "
             "the account of the document.")
    billing_unit = fields.Function(fields.Many2One('real_estate.billing_unit',
            "Billing Unit"), 'on_change_with_billing_unit')
    contract = fields.Many2One('real_estate.contract', "Contract",
        ondelete='RESTRICT',
        domain=[('property', '=', Eval('property', -1))],
        states={
            'invisible': Eval('target') != 'contract',
            'required': Eval('target') == 'contract',
            },
        help="The costs are added to the settlement result of this "
             "contract in the billing unit of the settlement unit.")
    base_object = fields.Many2One('real_estate.base_object', "Rental Object",
        ondelete='RESTRICT',
        domain=[
            ('property', '=', Eval('property', -1)),
            ('type', '=', 'object'),
            ],
        states={'invisible': Eval('target') != 'contract'},
        help="Only needed if the contract has several settlement results "
             "(rental objects) in the billing unit.")
    percent = fields.Numeric("Percent", digits=(7, 4),
        help="Share of the document - sets net and gross amount.")
    amount_net = Monetary("Net", currency='currency', digits='currency',
        required=True)
    amount_gross = Monetary("Gross", currency='currency',
        digits='currency', required=True)
    service_period_from = fields.Date("Service Period From",
        domain=[If(Bool(Eval('service_period_from'))
                & Bool(Eval('service_period_to')),
                ('service_period_from', '<=', Eval('service_period_to')),
                ())])
    service_period_to = fields.Date("Service Period To",
        domain=[If(Bool(Eval('service_period_from'))
                & Bool(Eval('service_period_to')),
                ('service_period_to', '>=', Eval('service_period_from')),
                ())])
    estg_35a = fields.Selection(ESTG_35A, '§35a EStG', sort=False)
    estg_35a_labor_share_percent = fields.Numeric(
        "Labor Share (%)", digits=(5, 2),
        domain=[
            If(Bool(Eval('estg_35a_labor_share_percent')),
                [('estg_35a_labor_share_percent', '>=', 0),
                    ('estg_35a_labor_share_percent', '<=', 100)],
                []),
            ],
        states={'invisible': ~Eval('estg_35a', '')},
        help="Share of the gross amount that is labor cost (§35a EStG "
             "certificate, BVED K-Satz field 14).")
    bved_fuel_type = fields.Selection('get_bved_fuel_types',
        "BVED Fuel Type", sort=False, help="BVED Tabelle 'B'.")
    bved_fuel_quantity = fields.Numeric("BVED Quantity", digits=(8, 3),
        help="Delivered fuel quantity for BVED K-Satz field 10.")
    proposal_source = fields.Char("Proposal", readonly=True)
    comment = fields.Char("Comment")

    @staticmethod
    def default_target():
        return 'settlement_unit'

    @staticmethod
    def default_estg_35a():
        return ''

    @staticmethod
    def get_bved_fuel_types():
        return [('', '')] + bved_records.as_selection(bved_records.TABLE_B)

    def get_document_field(self, name):
        document = self.document
        if not document:
            return None
        value = getattr(document, name[len('document_'):])
        return value.id if hasattr(value, 'id') else value

    @fields.depends('document', '_parent_document.property')
    def on_change_with_property(self, name=None):
        return self.document.property if self.document else None

    @fields.depends('document', '_parent_document.account')
    def on_change_with_account(self, name=None):
        return self.document.account if self.document else None

    @fields.depends('document', '_parent_document.company')
    def on_change_with_currency(self, name=None):
        if self.document and self.document.company:
            return self.document.company.currency
        return None

    @fields.depends('settlement_unit', '_parent_settlement_unit.billing_unit')
    def on_change_with_billing_unit(self, name=None):
        return (self.settlement_unit.billing_unit
            if self.settlement_unit else None)

    @fields.depends('target', 'settlement_unit', 'contract', 'base_object')
    def on_change_target(self):
        if self.target == 'property':
            self.settlement_unit = None
        if self.target != 'contract':
            self.contract = None
            self.base_object = None

    @fields.depends('percent', 'document', '_parent_document.amount_net',
        '_parent_document.amount_gross', '_parent_document.company')
    def on_change_percent(self):
        if self.percent is None or not self.document:
            return
        self.amount_net = ((self.document.amount_net or Decimal(0))
            * self.percent / 100).quantize(_CENT)
        self.amount_gross = ((self.document.amount_gross or Decimal(0))
            * self.percent / 100).quantize(_CENT)

    @fields.depends('amount_net', 'document', '_parent_document.amount_net',
        '_parent_document.amount_gross')
    def on_change_amount_net(self):
        if self.amount_net is None or not self.document:
            return
        doc_net = self.document.amount_net or Decimal(0)
        if doc_net:
            self.percent = (self.amount_net / doc_net * 100).quantize(
                Decimal('0.0001'))
            self.amount_gross = ((self.document.amount_gross or Decimal(0))
                * self.amount_net / doc_net).quantize(_CENT)

    def get_percent(self):
        "Share of the document in percent"
        if self.percent is not None:
            return self.percent
        doc_net = self.document.amount_net or Decimal(0)
        if doc_net:
            return ((self.amount_net or Decimal(0)) / doc_net * 100)
        return Decimal(0)

    def get_summary(self):
        if self.target == 'property':
            target = gettext('real_estate.msg_oc_target_owner')
        else:
            target = (self.settlement_unit.rec_name
                if self.settlement_unit else '?')
            if self.settlement_unit:
                target += f' ({self.settlement_unit.billing_unit.rec_name})'
            if self.target == 'contract' and self.contract:
                target = f'{self.contract.rec_name}: {target}'
        return f'{target} {self.get_percent():.2f} %'

    def get_rec_name(self, name):
        return self.get_summary()

    def check_locked(self):
        su = self.settlement_unit
        if su and su.billing_unit.state in LOCKED_STATES:
            raise AccessError(gettext('real_estate.msg_oc_line_locked',
                    billing_unit=su.billing_unit.rec_name))

    def check_object_booked(self):
        """E32: a document booked on a rental object is assigned only to
        this rental object (settlement unit: distributed over its occupancy
        periods) or to a contract of it - not to the owner"""
        doc = self.document
        obj = doc.object_booked()
        if not obj:
            return
        contract_ok = (self.target != 'contract' or (
                self.contract
                and (not doc.contract or self.contract == doc.contract)
                and obj in [o for item in self.contract.items
                    for o in item.objects]
                and (not self.base_object or self.base_object == obj)))
        if self.target == 'property' or not contract_ok:
            raise ValidationError(gettext(
                    'real_estate.msg_oc_line_object_booked',
                    document=doc.rec_name, object=obj.rec_name))

    def check_complete(self):
        "Z02: target complete and settlement unit of the property/account"
        if self.target != 'property' and not self.settlement_unit:
            raise ValidationError(gettext(
                    'real_estate.msg_oc_line_settlement_unit_required',
                    document=self.document.rec_name))
        if self.target == 'contract' and not self.contract:
            raise ValidationError(gettext(
                    'real_estate.msg_oc_line_contract_required',
                    document=self.document.rec_name))

    @classmethod
    def validate(cls, lines):
        super().validate(lines)
        CostType = Pool().get('real_estate.cost_type')
        for line in lines:
            line.check_object_booked()
        for line in lines:
            su = line.settlement_unit
            if not su:
                continue
            doc = line.document
            if (su.billing_unit.property != doc.property
                    or su.type.id not in CostType.ids_of_account(
                        doc.account)):
                raise ValidationError(gettext(
                        'real_estate.msg_oc_line_settlement_unit_invalid',
                        settlement_unit=su.rec_name,
                        document=doc.rec_name))

    @classmethod
    def create(cls, vlist):
        lines = super().create(vlist)
        for line in lines:
            line.check_locked()
        Pool().get('real_estate.oc_document').update_state(
            list({l.document for l in lines}))
        return lines

    @classmethod
    def write(cls, *args):
        actions = iter(args)
        all_lines = []
        for lines, _ in zip(actions, actions):
            for line in lines:
                line.check_locked()
            all_lines.extend(lines)
        super().write(*args)
        for line in all_lines:
            line.check_locked()
        Pool().get('real_estate.oc_document').update_state(
            list({l.document for l in all_lines}))

    @classmethod
    def delete(cls, lines):
        for line in lines:
            line.check_locked()
        document_ids = list({l.document.id for l in lines})
        super().delete(lines)
        Document = Pool().get('real_estate.oc_document')
        # not the documents deleted together with their lines
        Document.update_state(Document.search([('id', 'in', document_ids)]))


#**********************************************************************
class OcDocumentContext(ModelView):
    "Operating Cost Document Context"
    __name__ = 'real_estate.oc_document.context'

    company = fields.Many2One('company.company', "Company", required=True)
    property = fields.Many2One('real_estate.base_object', "Property",
        domain=[
            ('type', '=', 'property'),
            ('company', '=', Eval('company', -1)),
            ])
    account = fields.Many2One('account.account', "Account",
        domain=[('company', '=', Eval('company', -1))])
    party = fields.Many2One('party.party', "Supplier")
    from_date = fields.Date("From Date")
    to_date = fields.Date("To Date")
    without_property = fields.Boolean("Without Property",
        help="Only postings on operating cost accounts without property.")

    @classmethod
    def default_company(cls):
        return Transaction().context.get('company')


#**********************************************************************
class OcDocumentSplitStart(ModelView):
    "Operating Cost Document Split - Start"
    __name__ = 'real_estate.oc_document.split.start'

    service_period_from = fields.Date("Service Period From", required=True)
    service_period_to = fields.Date("Service Period To", required=True,
        domain=[If(Bool(Eval('service_period_from')),
                ('service_period_to', '>=', Eval('service_period_from')),
                ())])


class OcDocumentSplit(Wizard):
    "Operating Cost Document Split"
    __name__ = 'real_estate.oc_document.split'

    start = StateView('real_estate.oc_document.split.start',
        'real_estate.oc_document_split_start_view_form', [
            Button("Cancel", 'end', 'tryton-cancel'),
            Button("Split", 'split', 'tryton-ok', default=True),
            ])
    split = StateTransition()

    def default_start(self, fields):
        doc = self.record
        dates = [d for l in doc.lines
            for d in (l.service_period_from, l.service_period_to) if d]
        if dates:
            return {
                'service_period_from': min(dates),
                'service_period_to': max(dates),
                }
        return {}

    def transition_split(self):
        self.record.split_lines(self.start.service_period_from,
            self.start.service_period_to)
        return 'end'


#**********************************************************************
class OcDocumentHistoryStart(ModelView):
    "Operating Cost Document History - Start"
    __name__ = 'real_estate.oc_document.history.start'

    candidates = fields.Many2Many('real_estate.oc_document', None, None,
        "Candidates", readonly=True)
    source = fields.Many2One('real_estate.oc_document', "Earlier Document",
        required=True,
        domain=[('id', 'in', Eval('candidates', []))],
        help="Its assignment is transferred to the settlement units of the "
             "matching period with the same percentages.")


class OcDocumentHistory(Wizard):
    "Operating Cost Document History"
    __name__ = 'real_estate.oc_document.history'

    start = StateView('real_estate.oc_document.history.start',
        'real_estate.oc_document_history_start_view_form', [
            Button("Cancel", 'end', 'tryton-cancel'),
            Button("Take Over", 'take', 'tryton-ok', default=True),
            ])
    take = StateTransition()

    def default_start(self, fields):
        candidates = self.record.get_history(None)
        return {
            'candidates': candidates,
            'source': candidates[0] if candidates else None,
            }

    def transition_take(self):
        Line = Pool().get('real_estate.oc_document.line')
        doc = self.record
        doc.check_locked([doc])
        values = doc._values_from(self.start.source)
        if not values:
            raise ValidationError(gettext(
                    'real_estate.msg_oc_history_not_transferable',
                    document=self.start.source.rec_name))
        Line.delete(list(doc.lines))
        Line.create(values)
        return 'end'


#**********************************************************************
class OcDocumentUpdateStart(ModelView):
    "Operating Cost Documents Update - Start"
    __name__ = 'real_estate.oc_document.update.start'

    company = fields.Many2One('company.company', "Company", required=True)

    @classmethod
    def default_company(cls):
        return Transaction().context.get('company')


class OcDocumentUpdateResult(ModelView):
    "Operating Cost Documents Update - Result"
    __name__ = 'real_estate.oc_document.update.result'

    created = fields.Integer("Documents Created", readonly=True)


class OcDocumentUpdate(Wizard):
    "Operating Cost Documents Update"
    __name__ = 'real_estate.oc_document.update'

    start = StateView('real_estate.oc_document.update.start',
        'real_estate.oc_document_update_start_view_form', [
            Button("Cancel", 'end', 'tryton-cancel'),
            Button("Update", 'update', 'tryton-ok', default=True),
            ])
    update = StateTransition()
    result = StateView('real_estate.oc_document.update.result',
        'real_estate.oc_document_update_result_view_form', [
            Button("Close", 'end', 'tryton-ok', default=True),
            ])

    def transition_update(self):
        Document = Pool().get('real_estate.oc_document')
        self.result.created = Document.update_documents(
            self.start.company.id)
        return 'result'

    def default_result(self, fields):
        return {'created': self.result.created}
