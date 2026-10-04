'Processes (Prozesse) - spezifikation-wiedervorlage.md 8, phase D'
import datetime

from dateutil.relativedelta import relativedelta

from trytond.i18n import gettext
from trytond.model import (
    DeactivableMixin, ModelSQL, ModelView, Unique, Workflow, fields,
    sequence_ordered)
from trytond.model.exceptions import ValidationError
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Bool, Eval, If, PYSONDecoder, PYSONEncoder
from trytond.transaction import Transaction
from trytond.wizard import (
    Button, StateAction, StateTransition, StateView, Wizard)

# Named methods of process steps (spec 8.5): due date
# Process._step_date_<name>(process) and done check
# Process._step_done_<name>(process) -> bool
STEP_DATE_METHODS = ['billing_deadline_for_contract']
STEP_DONE_METHODS = ['deposit_paid', 'meter_readings_complete',
    'billing_settled', 'handover_move_in_done',
    'handover_pre_inspection_done', 'handover_move_out_done']
# Offsets from a system setting (re_accounting): name -> field
OFFSET_SETTINGS = {'deposit_task_months': 'deposit_task_months'}


def _decode(domain):
    return PYSONDecoder({}).decode(domain) if domain else []


def _date_fields(model):
    if not model:
        return [(None, '')]
    Model = Pool().get(model)
    return [(None, '')] + [(name, f'{field.string} ({name})')
        for name, field in sorted(Model._fields.items())
        if getattr(field, '_type', None) == 'date']


#**********************************************************************
class ProcessTemplate(DeactivableMixin, ModelSQL, ModelView):
    "Process Template"
    __name__ = 'real_estate.process.template'

    name = fields.Char("Name", required=True, translate=True)
    code = fields.Char("Code",
        help="Optional technical key, e.g. move_out.")
    model = fields.Selection('get_models', "Reference Object",
        required=True)
    anchor_field = fields.Selection('get_anchor_fields', "Anchor Date",
        help="Date field of the reference object the steps are scheduled "
             "from (e.g. contract end) - empty = start date of the "
             "process.")
    steps = fields.One2Many('real_estate.process.template.step',
        'template', "Steps")
    description = fields.Text("Description")

    @classmethod
    def __setup__(cls):
        super().__setup__()
        t = cls.__table__()
        cls._sql_constraints += [
            ('code_unique', Unique(t, t.code),
                'real_estate.msg_process_template_code_unique'),
            ]

    @classmethod
    def get_models(cls):
        return Pool().get('real_estate.task').get_resources()

    @fields.depends('model')
    def get_anchor_fields(self):
        return _date_fields(self.model)


#**********************************************************************
class ProcessTemplateStep(sequence_ordered(), ModelSQL, ModelView):
    "Process Template Step"
    __name__ = 'real_estate.process.template.step'

    template = fields.Many2One('real_estate.process.template', "Template",
        required=True, ondelete='CASCADE')
    template_model = fields.Function(fields.Char("Reference Object"),
        'on_change_with_template_model')
    name = fields.Char("Name", required=True, translate=True)
    task_type = fields.Many2One('real_estate.task.type', "Task Type",
        required=True, ondelete='RESTRICT',
        domain=[('for_model', '=', Eval('template_model', ''))],
        help="Reminder and escalation of the step; responsibility unless "
             "set below.")
    responsible_group = fields.Many2One('res.group', "Responsible Group",
        help="Responsibility of the step - empty = of the task type.")
    responsible_role = fields.Many2One('real_estate.object_party.role',
        "Responsible Party Role", ondelete='SET NULL',
        help="The party holding this role on the reference object on the "
             "due date becomes responsible (as user if linked via an "
             "employee) - empty = role of the task type.")
    due_base = fields.Selection([
            ('start', "Start of the Process"),
            ('anchor', "Anchor Date"),
            ('previous_done', "Previous Step Done"),
            ('method', "Method"),
            ], "Due from", required=True, sort=False,
        help="Previous Step Done: the task is created only when the "
             "previous step is done.")
    date_method = fields.Selection(
        [(None, '')] + [(m, m) for m in STEP_DATE_METHODS], "Date Method",
        states={
            'invisible': Eval('due_base') != 'method',
            'required': Eval('due_base') == 'method',
            })
    offset_setting = fields.Selection([
            (None, ''),
            ('deposit_task_months', "Months until Deposit Settlement"),
            ], "Offset from Setting",
        help="Offset in months from the real estate accounting instead of "
             "the fixed offset.")
    offset_months = fields.Integer("Offset (Months)")
    offset_days = fields.Integer("Offset (Days)")
    mandatory = fields.Boolean("Mandatory",
        help="Required to complete the process - optional steps can be "
             "cancelled (skipped).")
    description = fields.Text("Work Instruction", translate=True)
    action = fields.Many2One('ir.action', "Action", ondelete='SET NULL',
        domain=[('type', 'in', ['ir.action.report', 'ir.action.wizard',
                    'ir.action.act_window'])],
        help="Report, wizard or list to execute for the step (button "
             "'Execute Action' on the task, with the reference record).")
    completion = fields.Selection([
            ('manual', "Manual"),
            ('action', "By Action"),
            ('condition', "By Condition"),
            ], "Completion", required=True, sort=False,
        help="Manual: button Done. By Action: executing the action sets "
             "the step done. By Condition: done as soon as the reference "
             "record fulfils the condition.")
    done_condition = fields.Char("Done Condition",
        states={'invisible': Eval('completion') != 'condition'},
        help="PYSON domain on the reference record.")
    done_method = fields.Selection(
        [(None, '')] + [(m, m) for m in STEP_DONE_METHODS], "Done Method",
        states={'invisible': Eval('completion') != 'condition'})
    result_required = fields.Boolean("Result Required",
        help="Done only with an entry in 'Result'.")

    @staticmethod
    def default_due_base():
        return 'anchor'

    @staticmethod
    def default_mandatory():
        return True

    @staticmethod
    def default_completion():
        return 'manual'

    @fields.depends('template', '_parent_template.model')
    def on_change_with_template_model(self, name=None):
        return self.template.model if self.template else None

    @classmethod
    def validate_fields(cls, steps, field_names):
        super().validate_fields(steps, field_names)
        if 'done_condition' in field_names:
            for step in steps:
                try:
                    assert isinstance(_decode(step.done_condition), list)
                except Exception:
                    raise ValidationError(gettext(
                            'real_estate.msg_process_step_condition',
                            step=step.rec_name))


#**********************************************************************
class Process(Workflow, ModelSQL, ModelView):
    "Process"
    __name__ = 'real_estate.process'

    company = fields.Many2One('company.company', "Company", required=True,
        readonly=True)
    template = fields.Many2One('real_estate.process.template', "Template",
        required=True, readonly=True, ondelete='RESTRICT')
    resource = fields.Reference("Reference", selection='get_resources',
        required=True, readonly=True)
    contract = fields.Many2One('real_estate.contract', "Contract",
        ondelete='CASCADE', states={'readonly': True})
    property = fields.Many2One('real_estate.base_object', "Property",
        readonly=True, ondelete='CASCADE')
    start_date = fields.Date("Start Date", required=True, readonly=True)
    anchor_date = fields.Date("Anchor Date",
        states={'readonly': Eval('state') != 'running'},
        help="After a change, button 'Reschedule' moves the open tasks "
             "scheduled from the anchor date.")
    steps = fields.One2Many('real_estate.process.step', 'process', "Steps",
        readonly=True)
    tasks = fields.One2Many('real_estate.task', 'process', "Tasks",
        readonly=True)
    progress = fields.Function(fields.Char("Progress"), 'get_progress')
    state = fields.Selection([
            ('running', "Running"),
            ('done', "Done"),
            ('cancelled', "Cancelled"),
            ], "State", readonly=True, required=True, sort=False)
    # not "log": would hide ModelStorage.log() used by the workflow
    history = fields.Text("History", readonly=True)

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._order = [('start_date', 'DESC'), ('id', 'DESC')]
        cls._transitions |= {
            ('running', 'done'),
            ('running', 'cancelled'),
            }
        running = Eval('state') == 'running'
        cls._buttons.update({
            'check': {'invisible': ~running, 'depends': ['state']},
            'reschedule': {'invisible': ~running, 'depends': ['state']},
            'cancel': {'invisible': ~running, 'depends': ['state']},
            })

    @classmethod
    def get_resources(cls):
        return Pool().get('real_estate.task').get_resources()

    @staticmethod
    def default_state():
        return 'running'

    def get_rec_name(self, name):
        resource = (self.resource.rec_name
            if self.resource and self.resource.id >= 0 else '')
        return f'{self.template.name}: {resource}'

    def get_progress(self, name):
        steps = [s for s in self.steps if s.mandatory]
        done = [s for s in steps if s.state in ('done', 'skipped')]
        return gettext('real_estate.msg_process_progress',
            done=len(done), total=len(steps))

    # ------------------------------------------------------------------
    # Start (spec 8.3)

    @classmethod
    def start(cls, template, record, start_date=None):
        """Start the process 'template' for 'record' - not twice while a
        process of the template is running for it. Returns the process."""
        pool = Pool()
        Task = pool.get('real_estate.task')
        Date = pool.get('ir.date')
        running = cls.search([
                ('template', '=', template.id),
                ('resource', '=', str(record)),
                ('state', '=', 'running'),
                ], limit=1)
        if running:
            return running[0]
        start_date = start_date or Date.today()
        anchor = (getattr(record, template.anchor_field, None)
            if template.anchor_field else None) or start_date
        contract, property_ = Task._resource_links(record)
        company = Task._resource_company(record) or Transaction().context.get(
            'company')
        process, = cls.create([{
                    'company': getattr(company, 'id', company),
                    'template': template.id,
                    'resource': str(record),
                    'contract': contract.id if contract else None,
                    'property': property_.id if property_ else None,
                    'start_date': start_date,
                    'anchor_date': anchor,
                    'steps': [('create', [{
                                    'template_step': step.id,
                                    'sequence': step.sequence,
                                    'name': step.name,
                                    } for step in template.steps])],
                    }])
        process._create_due_tasks()
        return process

    def _step_due_date(self, step, previous_done=None):
        template = step.template_step
        base = None
        if template.due_base == 'start':
            base = self.start_date
        elif template.due_base == 'anchor':
            base = self.anchor_date
        elif template.due_base == 'previous_done':
            base = previous_done
        elif template.due_base == 'method':
            base = getattr(self, f'_step_date_{template.date_method}')()
        if base is None:
            return None
        months = template.offset_months or 0
        if template.offset_setting:
            months = self._setting(template.offset_setting)
        return base + relativedelta(months=months,
            days=template.offset_days or 0)

    def _setting(self, name):
        company = self.company
        re_accounting = company.re_accounting if company else None
        value = getattr(re_accounting, OFFSET_SETTINGS[name], None) \
            if re_accounting else None
        return value if value is not None else 6

    def _create_due_tasks(self):
        """Create the tasks of the steps that can be scheduled now: start,
        anchor and method steps, previous_done steps once the previous
        step is done (or skipped)."""
        pool = Pool()
        Task = pool.get('real_estate.task')
        Step = pool.get('real_estate.process.step')
        previous = None
        for step in self.steps:
            template = step.template_step
            if not step.task:
                due = None
                if template.due_base == 'previous_done':
                    if previous is None or (previous.task
                            and previous.task.state != 'open'):
                        done_date = (previous.task.done_date
                            if previous and previous.task
                            and previous.task.done_date else Pool().get(
                                'ir.date').today())
                        due = self._step_due_date(step,
                            previous_done=done_date)
                else:
                    due = self._step_due_date(step)
                if due is not None:
                    values = {
                        'company': self.company.id,
                        'name': f'{step.name}: {self.resource.rec_name}',
                        'task_type': template.task_type.id,
                        'resource': str(self.resource),
                        'due_date': due,
                        'description': template.description,
                        'responsible_group': (
                            template.responsible_group.id
                            if template.responsible_group else None),
                        'origin': str(self),
                        'origin_key': f'{self.id}:{step.id}',
                        'automatic': True,
                        'process': self.id,
                        'process_step': step.id,
                        }
                    # Party role of the step, else of the task type
                    role = (template.responsible_role
                        or template.task_type.responsible_role)
                    if role:
                        party, user = Task._role_responsible(role,
                            self.resource, due, self.company)
                        values['responsible_party'] = (
                            party.id if party else None)
                        if user:
                            values['responsible_user'] = user.id
                            if not values['responsible_group']:
                                type_group = (
                                    template.task_type.responsible_group)
                                values['responsible_group'] = (
                                    type_group.id if type_group else None)
                    task, = Task.create([values])
                    Step.write([step], {'task': task.id})
                    step = Step(step.id)
            previous = step

    # ------------------------------------------------------------------
    # Progress, completion (spec 8.3, 8.5)

    @classmethod
    def update_progress(cls, processes):
        """Create the next tasks (previous_done) and complete processes
        whose mandatory steps are done or skipped."""
        to_done = []
        for process in processes:
            if process.state != 'running':
                continue
            process._create_due_tasks()
            process = cls(process.id)
            mandatory = [s for s in process.steps if s.mandatory]
            if mandatory and all(s.state in ('done', 'skipped')
                    for s in mandatory):
                to_done.append(process)
        if to_done:
            cls.done(to_done)

    @classmethod
    @Workflow.transition('done')
    def done(cls, processes):
        pass

    @classmethod
    @ModelView.button
    def check(cls, processes):
        "Evaluate the done conditions of the open steps"
        Task = Pool().get('real_estate.task')
        for process in processes:
            if process.state != 'running':
                continue
            for step in process.steps:
                template = step.template_step
                if (template.completion != 'condition' or not step.task
                        or step.task.state != 'open'):
                    continue
                if process._step_condition_met(template):
                    Task.write([step.task], {'result': gettext(
                                'real_estate.msg_process_step_auto_done')})
                    Task.done([step.task])
        cls.update_progress(cls.browse([p.id for p in processes]))

    def _step_condition_met(self, template):
        resource = self.resource
        if template.done_condition:
            Model = Pool().get(resource.__name__)
            if not Model.search([('id', '=', resource.id)]
                    + _decode(template.done_condition), limit=1):
                return False
        if template.done_method:
            if not getattr(self, f'_step_done_{template.done_method}')():
                return False
        return bool(template.done_condition or template.done_method)

    @classmethod
    @ModelView.button
    def reschedule(cls, processes):
        """Move the open tasks scheduled from the anchor date after a
        change of the anchor date (log in the process)."""
        pool = Pool()
        Task = pool.get('real_estate.task')
        Date = pool.get('ir.date')
        for process in processes:
            lines = []
            for step in process.steps:
                task = step.task
                if (not task or task.state != 'open'
                        or step.template_step.due_base != 'anchor'):
                    continue
                due = process._step_due_date(step)
                if due and due != task.due_date:
                    delta = due - task.due_date
                    Task.write([task], {
                            'due_date': due,
                            'remind_date': (task.remind_date + delta
                                if task.remind_date else None),
                            'notified_date': None,
                            })
                    lines.append(gettext(
                            'real_estate.msg_process_rescheduled',
                            step=step.name,
                            old=task.due_date.strftime('%d.%m.%Y'),
                            new=due.strftime('%d.%m.%Y')))
            if lines:
                header = Date.today().strftime('%d.%m.%Y')
                cls.write([process], {'history': '\n'.join(filter(None, [
                                process.history, header] + lines))})

    @classmethod
    @ModelView.button
    @Workflow.transition('cancelled')
    def cancel(cls, processes):
        Task = Pool().get('real_estate.task')
        for process in processes:
            open_ = [t for t in process.tasks if t.state == 'open']
            if open_:
                Task.write(open_, {'result': gettext(
                            'real_estate.msg_process_cancelled')})
                Task.cancel(open_)

    # ------------------------------------------------------------------
    # Named step methods

    def _contract(self):
        return self.contract

    def _step_date_billing_deadline_for_contract(self):
        """Billing deadline (end + 12 months) of the billing unit of the
        property whose period contains the end of the contract"""
        BillingUnit = Pool().get('real_estate.billing_unit')
        contract = self._contract()
        end = contract.get_effective_end_date() if contract else None
        if not end or not contract.property:
            return None
        for unit in BillingUnit.search([
                    ('property', '=', contract.property.id),
                    ('start_date', '<=', end),
                    ]):
            if unit.end_date and unit.end_date >= end:
                return unit.end_date + relativedelta(months=12)
        return None

    def _step_done_deposit_paid(self):
        "The deposit (term type 1900) of the contract is paid"
        contract = self._contract()
        if not contract:
            return False
        deposits = [t for t in contract.terms
            if t.term_type and t.term_type.sequence == 1900]
        flows = [cf for t in deposits for cf in t.cash_flow]
        return bool(flows) and all(
            cf.invoice_state == 'paid' for cf in flows)

    def _step_done_meter_readings_complete(self):
        """All meters of the contract's objects have a reading within 7
        days of the anchor date"""
        pool = Pool()
        BaseObject = pool.get('real_estate.base_object')
        Reading = pool.get('real_estate.meter_reading')
        contract = self._contract()
        if not contract or not self.anchor_date:
            return False
        objects = [o.id for item in contract.items for o in item.objects]
        meters = BaseObject.search([
                ('parent', 'child_of', objects),
                ('type', '=', 'equipment'),
                ('e_type', '=', 'meters'),
                ]) if objects else []
        if not meters:
            return False
        window = datetime.timedelta(days=7)
        return all(Reading.search([
                    ('base_object', '=', m.id),
                    ('reading_date', '>=', self.anchor_date - window),
                    ('reading_date', '<=', self.anchor_date + window),
                    ], limit=1) for m in meters)

    def _step_done_billing_settled(self):
        """The billing unit whose period contains the contract end is
        billed"""
        BillingUnit = Pool().get('real_estate.billing_unit')
        contract = self._contract()
        end = contract.get_effective_end_date() if contract else None
        if not end or not contract.property:
            return False
        for unit in BillingUnit.search([
                    ('property', '=', contract.property.id),
                    ('start_date', '<=', end),
                    ]):
            if unit.end_date and unit.end_date >= end:
                return unit.state == 'billed'
        return False

    @classmethod
    def check_running(cls, companies=None):
        domain = [('state', '=', 'running')]
        if companies:
            domain.append(('company', 'in', [c.id for c in companies]))
        processes = cls.search(domain)
        if processes:
            cls.check(processes)


#**********************************************************************
class ProcessStep(sequence_ordered(), ModelSQL, ModelView):
    "Process Step"
    __name__ = 'real_estate.process.step'

    process = fields.Many2One('real_estate.process', "Process",
        required=True, ondelete='CASCADE')
    template_step = fields.Many2One('real_estate.process.template.step',
        "Template Step", required=True, ondelete='RESTRICT')
    name = fields.Char("Step", required=True)
    task = fields.Many2One('real_estate.task', "Task", ondelete='SET NULL')
    mandatory = fields.Function(fields.Boolean("Mandatory"),
        'get_template_info')
    action = fields.Function(fields.Many2One('ir.action', "Action"),
        'get_template_info')
    due_date = fields.Function(fields.Date("Due Date"), 'get_task_info')
    responsible = fields.Function(fields.Char("Responsible"),
        'get_task_info')
    state = fields.Function(fields.Selection([
                ('planned', "Planned"),
                ('open', "Open"),
                ('overdue', "Overdue"),
                ('done', "Done"),
                ('skipped', "Skipped"),
                ], "Step State"), 'get_task_info')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._order.insert(0, ('process', 'ASC'))

    @classmethod
    def view_attributes(cls):
        return super().view_attributes() + [
            ('/tree', 'visual', If(Eval('state') == 'overdue', 'danger',
                    If(Eval('state') == 'open', 'warning',
                        If(Eval('state').in_(['done', 'skipped']),
                            'muted', ''))),
                ['state']),
            ]

    def get_template_info(self, name):
        template = self.template_step
        if name == 'mandatory':
            return template.mandatory
        return template.action.id if template.action else None

    def get_task_info(self, name):
        Date = Pool().get('ir.date')
        task = self.task
        if name == 'due_date':
            return task.due_date if task else None
        if name == 'responsible':
            if not task:
                return None
            return (task.responsible_user.rec_name if task.responsible_user
                else task.responsible_group.rec_name
                if task.responsible_group else None)
        if not task:
            return 'planned'
        if task.state == 'done':
            return 'done'
        if task.state == 'cancelled':
            return 'skipped'
        if task.due_date and task.due_date < Date.today():
            return 'overdue'
        return 'open'


#**********************************************************************
class Task(metaclass=PoolMeta):
    __name__ = 'real_estate.task'

    process = fields.Many2One('real_estate.process', "Process",
        readonly=True, ondelete='CASCADE')
    process_step = fields.Many2One('real_estate.process.step',
        "Process Step", readonly=True, ondelete='SET NULL')
    step_action = fields.Function(fields.Many2One('ir.action', "Action"),
        'get_step_action')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._buttons.update({
            'execute_action': {
                'invisible': (~Bool(Eval('step_action'))
                    | (Eval('state') != 'open')),
                'depends': ['step_action', 'state'],
                },
            })

    def get_step_action(self, name):
        step = self.process_step
        if step and step.template_step.action:
            return step.template_step.action.id
        return None

    @classmethod
    @ModelView.button_action('real_estate.wizard_task_execute_action')
    def execute_action(cls, tasks):
        pass

    @classmethod
    def done(cls, tasks):
        for task in tasks:
            step = task.process_step
            if (step and step.template_step.result_required
                    and not task.result):
                raise ValidationError(gettext(
                        'real_estate.msg_process_step_result',
                        task=task.rec_name))
        super().done(tasks)
        cls._update_processes(tasks)

    @classmethod
    def cancel(cls, tasks):
        super().cancel(tasks)
        cls._update_processes(tasks)

    @classmethod
    def _update_processes(cls, tasks):
        Process = Pool().get('real_estate.process')
        processes = {t.process.id for t in tasks
            if t.process and t.process.state == 'running'}
        if processes:
            Process.update_progress(Process.browse(list(processes)))


#**********************************************************************
class TaskExecuteAction(Wizard):
    "Execute Action of a Process Step"
    __name__ = 'real_estate.task.execute_action'

    start_state = 'open_'
    # Placeholder - replaced by the action of the step in do_open_
    open_ = StateAction('real_estate.act_task_mine')

    def do_open_(self, action):
        pool = Pool()
        Task = pool.get('real_estate.task')
        task = self.record
        step_action = task.step_action
        resource = task.resource
        action = step_action.get_action_value()
        data = {
            'model': resource.__name__,
            'id': resource.id,
            'ids': [resource.id],
            }
        if (action.get('type') == 'ir.action.act_window'
                and action.get('res_model') == resource.__name__):
            action['pyson_domain'] = PYSONEncoder().encode(
                [('id', '=', resource.id)])
        # Completion 'by action': executing the action completes the step
        if (task.process_step
                and task.process_step.template_step.completion == 'action'
                and task.state == 'open'):
            Task.write([task], {'result': gettext(
                        'real_estate.msg_process_step_action_done',
                        action=step_action.rec_name)})
            Task.done([task])
        return action, data


#**********************************************************************
class ProcessStartStart(ModelView):
    "Start Process - Start"
    __name__ = 'real_estate.process.start.start'

    resource_model = fields.Char("Reference Object", readonly=True)
    template = fields.Many2One('real_estate.process.template', "Template",
        required=True,
        domain=[('model', '=', Eval('resource_model', ''))])
    start_date = fields.Date("Start Date", required=True)

    @staticmethod
    def default_start_date():
        return Pool().get('ir.date').today()


#**********************************************************************
class ProcessStart(Wizard):
    "Start Process"
    __name__ = 'real_estate.process.start'

    start = StateView('real_estate.process.start.start',
        'real_estate.process_start_start_view_form', [
            Button("Cancel", 'end', 'tryton-cancel'),
            Button("Start", 'start_', 'tryton-ok', default=True),
            ])
    start_ = StateTransition()

    def default_start(self, fields):
        return {'resource_model': self.model.__name__ if self.model else None}

    def transition_start_(self):
        Process = Pool().get('real_estate.process')
        for record in self.records:
            Process.start(self.start.template, record, self.start.start_date)
        return 'end'


#**********************************************************************
class ContractType(metaclass=PoolMeta):
    __name__ = 'real_estate.contract.type'

    start_process_template = fields.Many2One('real_estate.process.template',
        "Process at Contract Start", ondelete='SET NULL',
        domain=[('model', '=', 'real_estate.contract')],
        help="Started when a contract of this type is set to running "
             "(e.g. Move-in).")
    termination_process_template = fields.Many2One(
        'real_estate.process.template', "Process at Termination",
        ondelete='SET NULL', domain=[('model', '=', 'real_estate.contract')],
        help="Started when a termination is entered (e.g. Move-out).")
    partner_change_process_template = fields.Many2One(
        'real_estate.process.template', "Process at Partner Change",
        ondelete='SET NULL', domain=[('model', '=', 'real_estate.contract')],
        help="Started when the contract partner is changed by the wizard.")


class Contract(metaclass=PoolMeta):
    __name__ = 'real_estate.contract'

    processes = fields.One2Many('real_estate.process', 'contract',
        "Processes", readonly=True)
    # Tab "Tasks and Processes": running processes and the history of
    # done/cancelled ones
    processes_open = fields.One2Many('real_estate.process', 'contract',
        "Processes", filter=[('state', '=', 'running')], readonly=True)
    processes_history = fields.One2Many('real_estate.process', 'contract',
        "Processes", filter=[('state', 'in', ['done', 'cancelled'])],
        readonly=True)

    @classmethod
    def running(cls, contracts):
        super().running(contracts)
        cls._start_type_process(contracts, 'start_process_template')

    @classmethod
    def _start_type_process(cls, contracts, field):
        Process = Pool().get('real_estate.process')
        for contract in cls.browse([c.id for c in contracts]):
            template = getattr(contract.c_type, field, None) \
                if contract.c_type else None
            if template and template.active:
                Process.start(template, contract)


    @classmethod
    def _cron_task_rules(cls, re_accounting, task=None):
        "Also evaluate the done conditions of the running processes"
        pool = Pool()
        Company = pool.get('company.company')
        Process = pool.get('real_estate.process')
        super()._cron_task_rules(re_accounting, task)
        companies = Company.search([('re_accounting', '=', re_accounting.id)])
        if companies:
            Process.check_running(companies)


class TerminateContractWizard(metaclass=PoolMeta):
    __name__ = 'real_estate.terminate_contract.wizard'

    def transition_terminate_contract(self):
        Contract = Pool().get('real_estate.contract')
        state = super().transition_terminate_contract()
        Contract._start_type_process([self.start.contract],
            'termination_process_template')
        return state


class ChangeContractPartnerWizard(metaclass=PoolMeta):
    __name__ = 'real_estate.change_contract_partner.wizard'

    def transition_do_change(self):
        Contract = Pool().get('real_estate.contract')
        state = super().transition_do_change()
        Contract._start_type_process([self.start.contract],
            'partner_change_process_template')
        return state
