'Contract Wizards'
from trytond.model import ModelView, fields
from trytond.pool import Pool
from trytond.transaction import Transaction
from trytond.pyson import Eval
from trytond.wizard import (
    Button, StateTransition, StateView, Wizard)
from trytond.transaction import check_access, without_check_access
from trytond.modules.currency.fields import Monetary

from dateutil.relativedelta import relativedelta

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
        return 'create'

    @staticmethod
    def default_invoice_date():
        return Pool().get('ir.date').today()

    @staticmethod
    def default_invoice_state():
        return 'draft'

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

            if contract_ids:
                Contract.call_create_moves(
                    contract_ids, self.start.date, self.start.action,
                    self.start.execute_in_queue, self.start.invoice_state or 'draft',
                    self.start.invoice_date)

            action_labels = {
                'create': 'Create moves',
                're_calc': 'Re-calculate moves',
                're_calc_and_create': 'Re-calculate and create moves',
            }
            self.result.contracts_count = count
            self.result.action = action_labels.get(self.start.action, self.start.action)
            if count == 0:
                self.result.mode = 'No matching contracts found'
                self.result.message = (
                    'No contracts matched the selected filters '
                    f'(up to {self.start.date}).')
            elif self.start.execute_in_queue:
                self.result.mode = 'Queued'
                self.result.message = (
                    f'{count} contract(s) queued for background processing '
                    f'up to {self.start.date}.')
            else:
                self.result.mode = 'Completed'
                self.result.message = (
                    f'{count} contract(s) processed '
                    f'up to {self.start.date}.')
        return 'result'

    def default_result(self, fields):
        return {
            'contracts_count': self.result.contracts_count,
            'action': self.result.action,
            'mode': self.result.mode,
            'message': self.result.message,
        }


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
class ContractTermAdjustmentStart(ModelView):
    'Contract Term Adjustment - Start'
    __name__ = 'real_estate.contract_term_adjustment.start'

    procedure = fields.Selection([
        ('operation_costs_billing', 'Operation Costs Billing'),
        ('operation_costs_plan', 'Operation Costs Plan'),
        ('free_adjustment', 'Free Adjustment'),
        ], 'Adjustment Procedure', required=True, sort=False,
        help="Operation Costs Billing: adjust advance payments based on an "
             "operating cost billing run. Operation Costs Plan: adjust "
             "advance payments based on an operating cost plan. Free "
             "Adjustment: adjust by a free percentage or absolute value.")
    adjustment_mode = fields.Selection('get_adjustment_mode',
        'Adjustment Mode', sort=False,
        states={
            'invisible': Eval('procedure') != 'free_adjustment',
            'required': Eval('procedure') == 'free_adjustment',
        })

    company = fields.Many2One('company.company', 'Company', required=True)
    property = fields.Many2One('real_estate.base_object', 'Property',
        domain=[
            ('type', '=', 'property'),
            ('company', '=', Eval('company', -1)),
        ])

    valid_from_new = fields.Date('Valid From (New Term)', required=True,
        help="Effective date from which the new, adjusted term is valid. "
             "The old term is closed the day before this date.")

    billing_run_id = fields.Selection('get_billing_run_ids', 'Billing Run ID',
        states={
            'invisible': Eval('procedure') != 'operation_costs_billing',
            'required': Eval('procedure') == 'operation_costs_billing',
        },
        help="Only billing run IDs of billed billing units matching "
             "Company/Property above are shown.")

    no_terminated_contracts = fields.Boolean('No Contracts with Termination',
        states={'invisible': Eval('procedure') != 'operation_costs_billing'},
        help="Do not adjust terms of contracts that already have a "
             "termination (Kündigung) set.")
    no_future_terms = fields.Boolean('No Future Terms',
        states={'invisible': Eval('procedure') != 'operation_costs_billing'},
        help="Do not adjust terms that already have a future condition "
             "scheduled (a later term with a later valid_from already "
             "exists).")
    no_booked_terms = fields.Boolean('Do Not Adjust Booked Terms',
        states={'invisible': Eval('procedure') != 'operation_costs_billing'},
        help="Do not adjust terms that already have booked (posted) cash "
             "flow entries for the affected period.")
    only_rhythm_monthly_1 = fields.Boolean('Only Rhythm Monthly x1',
        states={'invisible': Eval('procedure') != 'operation_costs_billing'},
        help="Only adjust terms with rhythm type 'monthly' and rhythm "
             "count 1.")
    max_adjustment_percent = fields.Numeric('Max Adjustment %',
        digits=(None, 2),
        states={'invisible': Eval('procedure') != 'operation_costs_billing'},
        help="Maximum allowed adjustment, expressed as a percentage of the "
             "current amount.")
    currency = fields.Function(
        fields.Many2One('currency.currency', 'Currency'),
        'on_change_with_currency')
    max_adjustment_absolute = Monetary('Max Adjustment Absolute',
        currency='currency', digits='currency',
        states={'invisible': Eval('procedure') != 'operation_costs_billing'},
        help="Maximum allowed adjustment, expressed as an absolute amount.")

    @classmethod
    def get_adjustment_mode(cls):
        pool = Pool()
        Adjustment = pool.get('real_estate.contract.term.adjustment')
        return Adjustment.fields_get(
            ['adjustment_mode'])['adjustment_mode']['selection']

    @fields.depends('company', 'property')
    def get_billing_run_ids(self):
        pool = Pool()
        BillingUnit = pool.get('real_estate.billing_unit')
        domain = [('state', '=', 'billed'), ('billing_run_id', '!=', None)]
        if self.company:
            domain.append(('company', '=', self.company.id))
        if self.property:
            domain.append(('property', '=', self.property.id))
        units = BillingUnit.search(domain)
        run_ids = sorted({u.billing_run_id for u in units if u.billing_run_id})
        return [(run_id, run_id) for run_id in run_ids]

    @fields.depends('company')
    def on_change_with_currency(self, name=None):
        if self.company and self.company.currency:
            return self.company.currency.id
        return None

    @staticmethod
    def default_procedure():
        return 'operation_costs_billing'

    @staticmethod
    def default_valid_from_new():
        return Pool().get('ir.date').today()

    @staticmethod
    def default_no_terminated_contracts():
        return True

    @staticmethod
    def default_no_future_terms():
        return True

    @staticmethod
    def default_no_booked_terms():
        return True

    @staticmethod
    def default_only_rhythm_monthly_1():
        return True

    @staticmethod
    def default_max_adjustment_percent():
        return Decimal('10')

    @staticmethod
    def default_max_adjustment_absolute():
        return Decimal('50')

    @classmethod
    def default_company(cls):
        pool = Pool()
        context = Transaction().context
        active_id = context.get('active_id')
        active_model = context.get('active_model')
        if active_id and active_model == 'real_estate.base_object':
            prop = pool.get('real_estate.base_object')(active_id)
            return prop.company.id if prop.company else None
        user = pool.get('res.user')(Transaction().user)
        return user.company.id if user.company else None

    @classmethod
    def default_property(cls):
        context = Transaction().context
        active_id = context.get('active_id')
        active_model = context.get('active_model')
        if active_id and active_model == 'real_estate.base_object':
            return active_id
        return None


#**********************************************************************
class ContractTermAdjustmentConfirm(ModelView):
    'Contract Term Adjustment - Confirm'
    __name__ = 'real_estate.contract_term_adjustment.confirm'

    procedure = fields.Char('Adjustment Procedure', readonly=True)
    adjustment_mode = fields.Char('Adjustment Mode', readonly=True)
    company = fields.Many2One('company.company', 'Company', readonly=True)
    property = fields.Many2One('real_estate.base_object', 'Property',
        readonly=True)
    valid_from_new = fields.Date('Valid From (New Term)', readonly=True)
    billing_run_id = fields.Char('Billing Run ID', readonly=True)
    no_terminated_contracts = fields.Boolean('No Contracts with Termination',
        readonly=True)
    no_future_terms = fields.Boolean('No Future Terms', readonly=True)
    no_booked_terms = fields.Boolean('Do Not Adjust Booked Terms',
        readonly=True)
    only_rhythm_monthly_1 = fields.Boolean('Only Rhythm Monthly x1',
        readonly=True)
    max_adjustment_percent = fields.Numeric('Max Adjustment %', readonly=True)
    max_adjustment_absolute = fields.Numeric('Max Adjustment Absolute',
        readonly=True)


#**********************************************************************
class ContractTermAdjustmentResult(ModelView):
    'Contract Term Adjustment - Result'
    __name__ = 'real_estate.contract_term_adjustment.result'

    processed = fields.Integer('Processed', readonly=True)
    message = fields.Text('Message', readonly=True)


#**********************************************************************
class ContractTermAdjustmentWizard(Wizard):
    'Contract Term Adjustment Wizard'
    __name__ = 'real_estate.contract_term_adjustment.wizard'

    start = StateView('real_estate.contract_term_adjustment.start',
        'real_estate.contract_term_adjustment_start_view_form', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('OK', 'confirm', 'tryton-ok', True),
        ])
    confirm = StateView('real_estate.contract_term_adjustment.confirm',
        'real_estate.contract_term_adjustment_confirm_view_form', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('Process', 'do_adjustment', 'tryton-ok', True),
        ])
    do_adjustment = StateTransition()
    result = StateView('real_estate.contract_term_adjustment.result',
        'real_estate.contract_term_adjustment_result_view_form', [
            Button('Close', 'end', 'tryton-ok', True),
        ])

    _procedure_labels = {
        'operation_costs_billing': 'Operation Costs Billing',
        'operation_costs_plan': 'Operation Costs Plan',
        'free_adjustment': 'Free Adjustment',
    }
    _adjustment_mode_labels = {
        'percentage': 'Percentage',
        'absolute': 'Absolute',
    }

    def default_confirm(self, fields):
        return {
            'procedure': self._procedure_labels.get(
                self.start.procedure, self.start.procedure or ''),
            'adjustment_mode': self._adjustment_mode_labels.get(
                self.start.adjustment_mode,
                self.start.adjustment_mode or ''),
            'company': self.start.company.id if self.start.company else None,
            'property': self.start.property.id if self.start.property else None,
            'valid_from_new': self.start.valid_from_new,
            'billing_run_id': self.start.billing_run_id or '',
            'no_terminated_contracts': self.start.no_terminated_contracts,
            'no_future_terms': self.start.no_future_terms,
            'no_booked_terms': self.start.no_booked_terms,
            'only_rhythm_monthly_1': self.start.only_rhythm_monthly_1,
            'max_adjustment_percent': self.start.max_adjustment_percent,
            'max_adjustment_absolute': self.start.max_adjustment_absolute,
        }

    def transition_do_adjustment(self):
        result = self._adjustment()
        self.result.processed = result.get('processed', 0)
        self.result.message = result.get('message', '')
        return 'result'

    def _adjustment_operation_costs_billing(self):
        # Implementation for operation costs billing adjustment
        return {
            'processed': 0,
            'message': (
                f'Adjustment processing for procedure '
                f'"{self.start.procedure}" is not yet implemented.'),
        }

    def _adjustment_operation_costs_plan(self):
        # Implementation for operation costs plan adjustment
        return {
            'processed': 0,
            'message': (
                f'Adjustment processing for procedure '
                f'"{self.start.procedure}" is not yet implemented.'),
        }

    def _adjustment_free_adjustment(self):
        # Implementation for free adjustment
        return {
            'processed': 0,
            'message': (
                f'Adjustment processing for procedure '
                f'"{self.start.procedure}" is not yet implemented.'),
        }

    def _adjustment(self):
        """Placeholder for the term adjustment processing.

        Selection logic and write-back to ContractTerm are not yet
        specified and will be added in a later step.
        """


        match self.start.procedure:
            case 'operation_costs_billing':
                return self._adjustment_operation_costs_billing()
            case 'operation_costs_plan':
                return self._adjustment_operation_costs_plan()
            case 'free_adjustment':
                return self._adjustment_free_adjustment()
            case _: 

                return {
                    'processed': 0,
                    'message': (
                        f'Adjustment processing for procedure '
                        f'"{self.start.procedure}" is not yet implemented.'),
        }

    def default_result(self, fields):
        return {
            'processed': self.result.processed,
            'message': self.result.message,
        }
