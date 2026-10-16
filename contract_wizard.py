'Contract Wizards'
from trytond.model import ModelView, fields
from trytond.model.exceptions import ValidationError
from trytond.i18n import gettext
from trytond.pool import Pool
from trytond.transaction import Transaction
from trytond.pyson import Bool, Eval, If, PYSONEncoder
from trytond.wizard import (
    Button, StateAction, StateTransition, StateView, Wizard)
from trytond.transaction import check_access, without_check_access

from dateutil.relativedelta import relativedelta

from trytond.modules.currency.fields import Monetary
from trytond.modules.product import price_digits

import datetime
import calendar
from decimal import Decimal


#**********************************************************************
class TerminateContractWizard(Wizard):
    """Wizard to terminate contract, set termination date, reason and notice period"""
    __name__ = 'real_estate.terminate_contract.wizard'

    start = StateView('real_estate.terminate_contract.start',
        'real_estate.terminate_contract_view_form', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('OK', 'terminate_contract', 'tryton-ok', True),
            ])
    terminate_contract = StateTransition()

    @without_check_access
    def transition_terminate_contract(self):
        pool = Pool()
        User = pool.get('res.user')
        Contract = pool.get('real_estate.contract')
        user = User(Transaction().user)

        self.start.contract.state = 'terminated'
        self.start.contract.terminated_by = user.employee.id if user.employee else None
        self.start.contract.terminated_by_type = self.start.terminated_by
        self.start.contract.receipt_of_termination_notice = self.start.receipt_of_termination_notice
        self.start.contract.termination_date = self.start.termination_date
        if self.start.termination_date_calc and not self.start.contract.termination_date:
            self.start.contract.termination_date = self.start.termination_date_calc
        self.start.contract.termination_reason = self.start.reason
        self.start.contract.termination_notice = self.start.notice_period
        self.start.contract.end_date = self.start.contract.termination_date
        self.start.contract.save()
        return 'end'

#**********************************************************************
class TerminateContractStart(ModelView):
    """Start view for Terminate Contract Wizard"""
    __name__ = 'real_estate.terminate_contract.start'

    contract = fields.Many2One('real_estate.contract', 'Contract', required=True)
    terminated_by = fields.Selection('get_terminated_by_type', 'Terminated by', required=True)
    receipt_of_termination_notice = fields.Date('Receipt of Termination Notice', required=True)
    reason = fields.Char('Termination Reason')
    notice_period = fields.Selection('get_notice_period', 'Notice Period', required=True, sort=False)
    termination_date_calc = fields.Function(fields.Date('Termination Date',
         states={'invisible': (Eval('notice_period') == ''),
        }),
        'on_change_with_termination_date_calc',)
    termination_date = fields.Date('Termination Date',
        states={
            'invisible': (Eval('notice_period') != ''),
        })

    @classmethod
    def get_terminated_by_type(cls):
        pool = Pool()
        Contract = pool.get('real_estate.contract')
        return Contract.fields_get(['terminated_by_type'])['terminated_by_type']['selection']

    @classmethod
    def get_notice_period(cls):
        pool = Pool()
        Contract = pool.get('real_estate.contract')
        return Contract.fields_get(['termination_notice'])['termination_notice']['selection']

    @fields.depends('receipt_of_termination_notice', 'notice_period')
    def on_change_with_termination_date_calc(self, name=None):
        if self.receipt_of_termination_notice and self.notice_period != '':
            t_date = self.receipt_of_termination_notice.replace(day=1) + relativedelta(months=1) - relativedelta(days=1)
            if self.receipt_of_termination_notice and self.notice_period:
                if self.notice_period == '3m':
                    return t_date + relativedelta(months=3)
                elif self.notice_period == '6m':
                    return t_date + relativedelta(months=6)
                elif self.notice_period == '9m':
                    return t_date + relativedelta(months=9)
                elif self.notice_period == '12m':
                    return t_date + relativedelta(months=12)
        return None

    @classmethod
    def default_terminated_by(cls):
        return 'tenant'

    @classmethod
    def default_receipt_of_termination_notice(cls):
        return Pool().get('ir.date').today()

    @classmethod
    def default_notice_period(cls):
        return '3m'

    @classmethod
    def default_contract(cls):
        return Transaction().context.get('active_id')


#**********************************************************************
class CreateContractMovesStart(ModelView):
    """Start view for Create Moves Wizard"""
    __name__ = 'real_estate.contract.create_moves.start'

    date = fields.Date('to Date', required=True)
    company = fields.Many2One('company.company', "Company", required=True, )
    action = fields.Selection([
        ('create', 'Create moves'),
        ('re_calc', 'Re-Calculate moves'),
        ('re_calc_and_create', 'Re-Calculate and Create moves'),
        ], 'Action',
        help="Create moves: create moves until date\n"
               "Re-Calculate moves: re-calculate next document/due date by rhythm and last posting date\n"
               "Re-Calculate and Create moves: first sync re-calculate, then async create moves until date",
        required=True)

    invoice_date = fields.Date('Invoice Date',
        states={
            'invisible': ~Eval('action', '').in_(['create', 're_calc_and_create']),
            'required': Eval('action', '').in_(['create', 're_calc_and_create']),
        })

    invoice_date_in_past = fields.Boolean('Invoice Date in Past', readonly=True)

    invoice_state = fields.Selection([
        ('draft', 'Draft'),
        ('posted', 'Posted'),
        ], 'Invoice State',
        states={
            'invisible': ~Eval('action', '').in_(['create', 're_calc_and_create']),
        },
        help="Draft: invoices are saved as draft.\nPosted: invoices are posted immediately after creation.")

    execute_in_queue = fields.Boolean('Execute in queue',
        help="If checked, the moves will be created as queued moves, which can be posted later. Otherwise, the moves will be posted immediately after creation.")

    propertys = fields.Many2Many(
        'real_estate.base_object', None, None, 'Filter Properties',
        domain=[('company', '=', Eval('company', -1)),
                ('type', '=', 'property'),
                ],
    )

    contracts = fields.Many2Many(
        'real_estate.contract', None, None, 'Filter Contracts',
        domain=[('company', '=', Eval('company', -1))],
    )

    @fields.depends('date', 'invoice_date')
    def on_change_date(self):
        today = Pool().get('ir.date').today()
        if self.date and self.date < today:
            self.invoice_date = self.date.replace(day=1)
        self.invoice_date_in_past = self._check_past(self.invoice_date)

    @fields.depends('invoice_date')
    def on_change_invoice_date(self):
        self.invoice_date_in_past = self._check_past(self.invoice_date)

    @staticmethod
    def _check_past(invoice_date):
        if not invoice_date:
            return False
        return invoice_date < Pool().get('ir.date').today()

    @staticmethod
    def default_date():
        Date = Pool().get('ir.date')
        today = Date.today()
        last_day_month = calendar.monthrange(today.year, today.month)[1]
        return datetime.date(today.year, today.month, last_day_month)

    @staticmethod
    def default_company():
        User = Pool().get('res.user')
        user = User(Transaction().user)
        return user.company.id if user.company else None

    @staticmethod
    def default_action():
        return 're_calc_and_create'

    @staticmethod
    def default_invoice_date():
        return Pool().get('ir.date').today()

    @staticmethod
    def default_invoice_state():
        return 'posted'

    @staticmethod
    def default_invoice_date_in_past():
        return False

    @staticmethod
    def default_execute_in_queue():
        return True


#**********************************************************************
class CreateContractMovesConfirm(ModelView):
    'Create Contract Moves - Confirm'
    __name__ = 'real_estate.contract.create_moves.confirm'

    contracts_count = fields.Integer('Matching Contracts', readonly=True)
    date = fields.Date('Up to Date', readonly=True)
    action = fields.Char('Action', readonly=True)
    invoice_state = fields.Char('Invoice State', readonly=True)
    execute_in_queue = fields.Boolean('Execute in Queue', readonly=True)
    n_properties = fields.Integer('Properties Filter', readonly=True)
    n_contracts = fields.Integer('Contracts Filter', readonly=True)


#**********************************************************************
class CreateContractMovesResult(ModelView):
    'Create Contract Moves - Result'
    __name__ = 'real_estate.contract.create_moves.result'

    contracts_count = fields.Integer('Contracts', readonly=True)
    action = fields.Char('Action', readonly=True)
    mode = fields.Char('Mode', readonly=True)
    message = fields.Text('Details', readonly=True)


#**********************************************************************
class CreateContractMovesWizard(Wizard):
    """Wizard to create moves for contracts until given date, with option to
    re-calculate next document/due date by rhythm and last posting date before move creation"""
    __name__ = 'real_estate.contract.create_moves.wizard'

    start = StateView('real_estate.contract.create_moves.start',
        'real_estate.contract_create_moves_start_view_form', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('OK', 'confirm', 'tryton-ok', True),
            ])
    confirm = StateView('real_estate.contract.create_moves.confirm',
        'real_estate.contract_create_moves_confirm_view_form', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('Process', 'create_moves', 'tryton-ok', True),
            ])
    create_moves = StateTransition()
    result = StateView('real_estate.contract.create_moves.result',
        'real_estate.contract_create_moves_result_view_form', [
            Button('Close', 'end', 'tryton-ok', True),
            ])

    def default_confirm(self, fields):
        pool = Pool()
        Contract = pool.get('real_estate.contract')

        action_labels = {
            'create': 'Create moves',
            're_calc': 'Re-calculate moves',
            're_calc_and_create': 'Re-calculate and create moves',
        }
        invoice_labels = {'draft': 'Draft', 'posted': 'Posted'}

        search_domain = [
            ('state', 'in', ('running', 'terminated')),
            ('start_date', '<=', self.start.date),
        ]
        if self.start.propertys:
            property_ids = [p.id for p in self.start.propertys]
            search_domain.append(('property', 'in', property_ids))
        if self.start.contracts:
            contract_ids_filter = [c.id for c in self.start.contracts]
            search_domain.append(('id', 'in', contract_ids_filter))

        count = len(Contract.search(search_domain))

        return {
            'contracts_count': count,
            'date': self.start.date,
            'action': action_labels.get(self.start.action, self.start.action),
            'invoice_state': invoice_labels.get(
                self.start.invoice_state or 'draft',
                self.start.invoice_state or 'draft'),
            'execute_in_queue': self.start.execute_in_queue,
            'n_properties': len(self.start.propertys) if self.start.propertys else 0,
            'n_contracts': len(self.start.contracts) if self.start.contracts else 0,
        }

    @without_check_access
    def transition_create_moves(self):
        pool = Pool()
        with check_access():
            search_domain = [('state', 'in', ('running', 'terminated')),
                            ('start_date', '<=', self.start.date)
                            ]
            if self.start.propertys:
                property_ids = [p.id for p in self.start.propertys]
                search_domain.append(('property', 'in', property_ids))
            if self.start.contracts:
                contract_ids_filter = [c.id for c in self.start.contracts]
                search_domain.append(('id', 'in', contract_ids_filter))

            Contract = pool.get('real_estate.contract')
            contract_ids = Contract.search(search_domain)
            count = len(contract_ids)

            skipped = 0
            if contract_ids:
                skipped = Contract.call_create_moves(
                    contract_ids, self.start.date, self.start.action,
                    self.start.execute_in_queue, self.start.invoice_state or 'draft',
                    self.start.invoice_date) or 0

            action_labels = {
                'create': 'Create moves',
                're_calc': 'Re-calculate moves',
                're_calc_and_create': 'Re-calculate and create moves',
            }
            self.result.contracts_count = count
            self.result.action = action_labels.get(self.start.action, self.start.action)
            date = self.start.date.strftime('%d.%m.%Y')
            if count == 0:
                self.result.mode = gettext('real_estate.msg_queue_mode_none')
                self.result.message = gettext(
                    'real_estate.msg_create_moves_none', date=date)
            elif self.start.execute_in_queue:
                self.result.mode = gettext('real_estate.msg_queue_mode_queued')
                lines = []
                if count - skipped:
                    lines.append(gettext(
                            'real_estate.msg_create_moves_queued',
                            count=count - skipped, date=date))
                if skipped:
                    lines.append(gettext(
                            'real_estate.msg_create_moves_skipped',
                            count=skipped))
                lines.append(gettext('real_estate.msg_create_moves_hint'))
                self.result.message = '\n'.join(lines)
            else:
                self.result.mode = gettext(
                    'real_estate.msg_queue_mode_completed')
                self.result.message = gettext(
                    'real_estate.msg_create_moves_done', count=count,
                    date=date)
        return 'result'

    def default_result(self, fields):
        return {
            'contracts_count': self.result.contracts_count,
            'action': self.result.action,
            'mode': self.result.mode,
            'message': self.result.message,
        }


#**********************************************************************
class CancelPeriodBookingStart(ModelView):
    'Cancel Period Booking - Start'
    __name__ = 'real_estate.cancel_period_booking.start'

    company = fields.Many2One('company.company', 'Company', required=True)
    property = fields.Many2One('real_estate.base_object', 'Property',
        domain=[
            ('type', '=', 'property'),
            ('company', '=', Eval('company', -1)),
        ])
    create_moves_run_id = fields.Selection('get_run_ids', 'Create Moves Run ID',
        required=True,
        help="Only run IDs of already booked period postings (state="
             "'done') matching Company/Property above are shown. All "
             "postings with this run ID will be cancelled.")
    invoice_date = fields.Date('Invoice Date', required=True,
        help="Reference date for this cancellation, recorded in the "
             "contract log. The date of the reversal accounting move "
             "itself is determined automatically by the accounting "
             "module.")

    @fields.depends('company', 'property')
    def get_run_ids(self):
        pool = Pool()
        CashFlowLine = pool.get('real_estate.contract.term.cash_flow')
        domain = [('state', '=', 'done'), ('create_moves_run_id', '!=', None)]
        if self.company:
            domain.append(('company', '=', self.company.id))
        if self.property:
            domain.append(('property', '=', self.property.id))
        lines = CashFlowLine.search(domain)
        run_ids = sorted(
            {l.create_moves_run_id for l in lines if l.create_moves_run_id})
        return [(run_id, run_id) for run_id in run_ids]

    @staticmethod
    def default_invoice_date():
        return Pool().get('ir.date').today()

    @classmethod
    def default_company(cls):
        pool = Pool()
        context = Transaction().context
        active_id = context.get('active_id')
        active_model = context.get('active_model')
        if active_id and active_model == 'real_estate.base_object':
            prop = pool.get('real_estate.base_object')(active_id)
            return prop.company.id if prop.company else None
        if active_id and active_model == 'real_estate.contract':
            contract = pool.get('real_estate.contract')(active_id)
            return contract.company.id if contract.company else None
        user = pool.get('res.user')(Transaction().user)
        return user.company.id if user.company else None

    @classmethod
    def default_property(cls):
        pool = Pool()
        context = Transaction().context
        active_id = context.get('active_id')
        active_model = context.get('active_model')
        if active_id and active_model == 'real_estate.base_object':
            return active_id
        if active_id and active_model == 'real_estate.contract':
            contract = pool.get('real_estate.contract')(active_id)
            return contract.property.id if contract.property else None
        return None


#**********************************************************************
class CancelPeriodBookingWizard(Wizard):
    'Cancel Period Booking Wizard'
    __name__ = 'real_estate.cancel_period_booking.wizard'

    start = StateView('real_estate.cancel_period_booking.start',
        'real_estate.cancel_period_booking_start_view_form', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('OK', 'do_cancel', 'tryton-ok', True),
        ])
    do_cancel = StateTransition()

    def transition_do_cancel(self):
        pool = Pool()
        CashFlowLine = pool.get('real_estate.contract.term.cash_flow')
        Contract = pool.get('real_estate.contract')

        lines = CashFlowLine.search([
            ('create_moves_run_id', '=', self.start.create_moves_run_id),
            ('state', '=', 'done'),
        ])
        if not lines:
            raise ValidationError(gettext(
                'real_estate.msg_cancel_period_booking_no_lines_found',
                run_id=self.start.create_moves_run_id))

        Contract.cancel_period_booking(lines, invoice_date=self.start.invoice_date)

        return 'end'


#**********************************************************************
class ContractRunningWizard(Wizard):
    'Set Contracts to Running'
    __name__ = 'real_estate.contract.running.wizard'

    start_state = 'start'
    start = StateTransition()

    def transition_start(self):
        Contract = Pool().get('real_estate.contract')
        contracts = [
            c for c in Contract.browse(
                Transaction().context.get('active_ids', []))
            if c.state == 'draft'
        ]
        if contracts:
            Contract.running(contracts)
        return 'end'


#**********************************************************************
class ChangeContractPartnerStart(ModelView):
    'Change Contract Partner - Start'
    __name__ = 'real_estate.change_contract_partner.start'

    contract = fields.Many2One('real_estate.contract', 'Contract',
        required=True, readonly=True)
    current_party = fields.Function(
        fields.Many2One('party.party', 'Current Partner'),
        'on_change_with_current_party')
    new_party = fields.Many2One('party.party', 'New Partner', required=True,
        domain=[('id', '!=', Eval('current_party', -1))],
        depends=['current_party'],
        help="Only still-open (unreconciled) booked items are rebooked to "
             "this partner - already settled invoices are left untouched.")
    contract_start_date = fields.Function(
        fields.Date('Contract Start Date'),
        'on_change_with_contract_start_date')
    contract_end_date = fields.Function(
        fields.Date('Contract End Date'),
        'on_change_with_contract_end_date')
    change_date = fields.Date('Change Date', required=True,
        domain=[
            If(Bool(Eval('contract_start_date')),
                ('change_date', '>=', Eval('contract_start_date')),
                ()),
            If(Bool(Eval('contract_end_date')),
                ('change_date', '<=', Eval('contract_end_date')),
                ()),
            ],
        depends=['contract_start_date', 'contract_end_date'],
        help="Effective date of the change: the old partner's 'Main "
             "Tenant Role' assignment ends the day before, the old "
             "partner's 'Secondary Tenant Role' and the new partner's "
             "'Main Tenant Role' assignments start on this date. Also "
             "used as the booking date for the rebooked open invoices. "
             "Must not be before the contract's start date or after its "
             "(effective) end date.")

    @classmethod
    def default_contract(cls):
        return Transaction().context.get('active_id')

    @classmethod
    def default_change_date(cls):
        return Pool().get('ir.date').today()

    @fields.depends('contract', '_parent_contract.contractual_partner')
    def on_change_with_current_party(self, name=None):
        if self.contract:
            return self.contract.contractual_partner
        return None

    @fields.depends('contract', '_parent_contract.start_date')
    def on_change_with_contract_start_date(self, name=None):
        return self.contract.start_date if self.contract else None

    @fields.depends(
        'contract', '_parent_contract.end_date',
        '_parent_contract.termination_date')
    def on_change_with_contract_end_date(self, name=None):
        if self.contract:
            return self.contract.get_effective_end_date()
        return None


#**********************************************************************
class ChangeContractPartnerWizard(Wizard):
    'Change Contract Partner Wizard'
    __name__ = 'real_estate.change_contract_partner.wizard'

    start = StateView('real_estate.change_contract_partner.start',
        'real_estate.change_contract_partner_start_view_form', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('OK', 'do_change', 'tryton-ok', True),
        ])
    do_change = StateTransition()

    def transition_do_change(self):
        pool = Pool()
        Contract = pool.get('real_estate.contract')
        Contract.execute_change_partner(
            [self.start.contract], self.start.new_party,
            change_date=self.start.change_date)
        return 'end'


#**********************************************************************
class OpenContractSettlementUnits(Wizard):
    "Open the Operating Cost Settlement Units of a Contract"
    __name__ = 'real_estate.contract.open_settlement_units'

    start_state = 'open_'
    open_ = StateAction('real_estate.act_contract_settlement_unit_relate')

    def do_open_(self, action):
        Contract = Pool().get('real_estate.contract')
        ids = []
        for contract in self.records:
            ids.extend(su.id for su in
                Contract.get_settlement_units_all_periods(contract)
                if su.id not in ids)
        action['pyson_domain'] = PYSONEncoder().encode([('id', 'in', ids)])
        return action, {}


#**********************************************************************
# Copy the terms of another contract (predecessor, offer) into a draft
# contract - only for the existing items

class CopyTermsStart(ModelView):
    'Copy Terms - Source'
    __name__ = 'real_estate.contract.copy_terms.start'

    contract = fields.Many2One('real_estate.contract', "Contract",
        readonly=True)
    company = fields.Many2One('company.company', "Company", readonly=True)
    source = fields.Many2One('real_estate.contract', "Source Contract",
        required=True,
        domain=[
            ('company', '=', Eval('company', -1)),
            ('id', '!=', Eval('contract', -1)),
            ],
        help="Contract whose terms are proposed - default: the previous "
             "contract of the rental units of the items (also an offer "
             "in draft).")


class CopyTermsLines(ModelView):
    'Copy Terms - Proposal'
    __name__ = 'real_estate.contract.copy_terms.lines'

    source = fields.Many2One('real_estate.contract', "Source Contract",
        readonly=True)
    reference_date = fields.Date("Reference Date", readonly=True,
        help="The terms of the source contract valid on this date are "
             "proposed (its end, else today; for a draft its start).")
    lines = fields.One2Many('real_estate.contract.copy_terms.line', None,
        "Terms")


class CopyTermsLine(ModelView):
    'Copy Terms - Line'
    __name__ = 'real_estate.contract.copy_terms.line'

    apply = fields.Boolean("Copy",
        states={'readonly': ~Eval('allowed', False)},
        depends=['allowed'])
    allowed = fields.Boolean("Allowed", readonly=True)
    source_term = fields.Many2One('real_estate.contract.term', "Term",
        readonly=True)
    term_type = fields.Many2One('real_estate.contract.term.type',
        "Term Type", readonly=True)
    item = fields.Many2One('real_estate.contract.item', "Item",
        readonly=True)
    rhythm = fields.Char("Rhythm", readonly=True)
    quantity = fields.Float("Quantity", readonly=True)
    currency = fields.Many2One('currency.currency', "Currency",
        readonly=True)
    unit_price_old = Monetary("Unit Price (previous)", currency='currency',
        digits=price_digits, readonly=True)
    amount_old = Monetary("Amount (previous)", currency='currency',
        digits='currency', readonly=True)
    unit_price = Monetary("New Unit Price", currency='currency',
        digits=price_digits,
        states={'readonly': ~Eval('allowed', False)},
        depends=['allowed'])
    note = fields.Char("Note", readonly=True)

    @classmethod
    def view_attributes(cls):
        # not copyable rows in grey
        return super().view_attributes() + [
            ('/tree', 'visual', If(~Eval('allowed', False), 'muted', ''),
                ['allowed']),
            ]


class CopyTerms(Wizard):
    'Copy Terms'
    __name__ = 'real_estate.contract.copy_terms'

    start = StateView('real_estate.contract.copy_terms.start',
        'real_estate.copy_terms_start_view_form', [
            Button("Cancel", 'end', 'tryton-cancel'),
            Button("Next", 'lines', 'tryton-forward', default=True),
            ])
    lines = StateView('real_estate.contract.copy_terms.lines',
        'real_estate.copy_terms_lines_view_form', [
            Button("Cancel", 'end', 'tryton-cancel'),
            Button("Back", 'start', 'tryton-back'),
            Button("Copy Terms", 'create_terms', 'tryton-ok', default=True),
            ])
    create_terms = StateTransition()

    def default_start(self, fields):
        contract = self.record
        if contract.state != 'draft':
            raise ValidationError(gettext(
                    'real_estate.msg_copy_terms_draft',
                    contract=contract.rec_name))
        predecessor = self._predecessor(contract)
        return {
            'contract': contract.id,
            'company': contract.company.id if contract.company else None,
            'source': predecessor.id if predecessor else None,
            }

    @staticmethod
    def _objects(contract):
        return {o.id for item in contract.items for o in item.objects}

    @classmethod
    def _predecessor(cls, contract):
        """Latest other contract of the rental units of the items: first
        the running/terminated ones starting before, then drafts
        (offers)"""
        Contract = Pool().get('real_estate.contract')
        objects = cls._objects(contract)
        if not objects:
            return None
        candidates = Contract.search([
                ('id', '!=', contract.id),
                ('company', '=', contract.company.id),
                ('items.objects', 'in', list(objects)),
                ('state', '!=', 'cancelled'),
                ], order=[('start_date', 'DESC'), ('id', 'DESC')])
        start = contract.start_date
        for draft in (False, True):
            for candidate in candidates:
                if (candidate.state == 'draft') == draft and (
                        draft or not start
                        or candidate.start_date <= start):
                    return candidate
        return None

    @staticmethod
    def _reference_date(source):
        Date = Pool().get('ir.date')
        today = Date.today()
        if source.state == 'draft':
            return source.start_date or today
        end = source.get_effective_end_date()
        return end if end and end < today else today

    def _proposal(self, contract, source):
        "Lines of the source terms valid on the reference date"
        pool = Pool()
        TermType = pool.get('real_estate.contract.term.type')
        date = self._reference_date(source)
        rhythms = dict(pool.get('real_estate.contract.term')
            .get_rhythm_type())
        existing = {(t.term_type.id, t.reference_item.id
                if t.reference_item else None) for t in contract.terms}
        lines = []
        for term in sorted(source.terms,
                key=lambda t: (t.sequence or 0, t.id)):
            one_time = term.rhythm_type == 'one_time'
            if not one_time and (term.valid_from > date
                    or (term.valid_to and term.valid_to < date)):
                continue
            # item of the new contract with the same rental units
            objects = ({o.id for o in term.reference_item.objects}
                if term.reference_item else set())
            item = next((i for i in contract.items
                    if objects & {o.id for o in i.objects}), None)
            notes, allowed = [], True
            if term.reference_item and not item:
                allowed = False
                notes.append(gettext('real_estate.msg_copy_terms_no_item'))
            domain = [
                ('id', '=', term.term_type.id),
                ('types_of_use', 'in', [contract.type_of_use]),
                ('re_accounting', '=', contract.company_re_accounting.id
                    if contract.company_re_accounting else -1),
                ['OR',
                    ('c_type', '=', None),
                    ('c_type', '=', contract.c_type.id
                        if contract.c_type else -1),
                    ],
                ]
            if allowed and not TermType.search(domain, limit=1):
                allowed = False
                notes.append(gettext(
                        'real_estate.msg_copy_terms_type_not_allowed'))
            if allowed and (term.term_type.id,
                    item.id if item else None) in existing:
                allowed = False
                notes.append(gettext('real_estate.msg_copy_terms_exists'))
            if term.term_type.m_type:
                notes.append(gettext('real_estate.msg_copy_terms_measured'))
            if term.rent_adjustment or term.graduated_locked:
                notes.append(gettext('real_estate.msg_copy_terms_agreement'))
            if one_time:
                notes.append(gettext('real_estate.msg_copy_terms_one_time'))
            quantity = Decimal(str(term.quantity or 0))
            lines.append({
                    'apply': allowed,
                    'allowed': allowed,
                    'source_term': term.id,
                    'term_type': term.term_type.id,
                    'item': item.id if item else None,
                    'rhythm': ' '.join(filter(None, [
                                str(term.rhythm or ''),
                                rhythms.get(term.rhythm_type, '')])),
                    'quantity': float(term.quantity or 0),
                    'currency': (contract.currency.id
                        if contract.currency else None),
                    'unit_price_old': term.unit_price,
                    'amount_old': (quantity * (term.unit_price
                            or Decimal(0))).quantize(Decimal('0.01')),
                    'unit_price': term.unit_price,
                    'note': '; '.join(notes) or None,
                    })
        return date, lines

    def default_lines(self, fields):
        contract = self.record
        source = self.start.source
        date, lines = self._proposal(contract, source)
        return {
            'source': source.id,
            'reference_date': date,
            'lines': lines,
            }

    def transition_create_terms(self):
        pool = Pool()
        Term = pool.get('real_estate.contract.term')
        contract = self.record
        if contract.state != 'draft':
            return 'end'
        # The client sends back only the editable values of the lines
        # (copy flag, new unit price): the lines are built again in the
        # same order
        _, proposal = self._proposal(contract, self.start.source)
        selected = [(values, line) for values, line
            in zip(proposal, self.lines.lines)
            if values['allowed'] and line.apply]
        if not selected:
            raise ValidationError(gettext(
                    'real_estate.msg_copy_terms_nothing_selected'))
        step = (contract.c_type.step_term
            if contract.c_type and contract.c_type.step_term else 1)
        sequence = max([t.sequence or 0 for t in contract.terms] or [0])
        names = []
        for values, line in selected:
            sequence += step
            source_term = Term(values['source_term'])
            unit_price = (line.unit_price if line.unit_price is not None
                else values['unit_price'])
            new, = Term.copy([source_term], default={
                    'contract': contract.id,
                    'reference_item': values['item'],
                    'valid_from': contract.start_date,
                    'valid_to': None,
                    'unit_price': unit_price,
                    'sequence': sequence,
                    'cash_flow': [],
                    })
            names.append(new.rec_name.strip())
        contract.add_log('copy_terms', gettext(
                'real_estate.msg_copy_terms_log',
                source=self.start.source.rec_name,
                terms=', '.join(names)))
        return 'end'
