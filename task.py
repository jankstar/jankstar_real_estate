'Tasks and follow-ups (Aufgaben und Wiedervorlagen) - spezifikation-wiedervorlage.md'
import datetime
import logging

from dateutil.relativedelta import relativedelta

from trytond.i18n import gettext
from trytond.model import (
    DeactivableMixin, ModelSQL, ModelView, Unique, Workflow, fields,
    sequence_ordered)
from trytond.model.exceptions import AccessError, ValidationError
from trytond.modules.company.model import employee_field
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Bool, Eval, If
from trytond.transaction import Transaction, without_check_access
from trytond.wizard import Button, StateTransition, StateView, Wizard

logger = logging.getLogger(__name__)

# Models a task can refer to (spec 4.2) - extensible by override
TASK_RESOURCES = [
    'real_estate.contract',
    'real_estate.contract.party',
    'real_estate.contract.rent_adjustment',
    'real_estate.contract.term.adjustment',
    'real_estate.base_object',
    'real_estate.billing_unit',
    'real_estate.price_index',
    'real_estate.cron_task',
    'party.party',
    'real_estate.inspection',
    'real_estate.inspection.defect',
    'real_estate.meter_reading.sheet',
    ]


_C = 'real_estate.contract'
_RA = 'real_estate.contract.rent_adjustment'
_TA = 'real_estate.contract.term.adjustment'
_BO = 'real_estate.base_object'
_BU = 'real_estate.billing_unit'

# Fixed catalog of the task codes used by the module code (hooks,
# rules, processes): code -> (label, reference models - empty = all,
# manual = may be created by a user). Types without code are user
# defined (spezifikation-wiedervorlage.md 4.1)
TASK_CODES = {
    'manual': ("Follow-up", [], True),
    'contract_unsigned': ("Contract not signed", [_C], True),
    'contract_end': ("Fixed-term contract ends", [_C], True),
    'no_follow_up': ("No follow-up contract", [_C], True),
    'party_end': ("Contract party ends", ['real_estate.contract.party'],
        True),
    'index_prepare': ("Prepare index rent adjustment", [_RA], True),
    'graduated_end': ("Graduated rent ends", [_RA], True),
    'waiver_end': ("Termination waiver ends", [_RA], True),
    'index_declare': ("Declare index rent adjustment", [_TA], False),
    'index_receipt': ("Capture receipt of index declaration", [_TA], False),
    'index_execute': ("Execute index rent adjustment", [_TA], False),
    'index_values': ("Index values outdated", ['real_estate.price_index'],
        False),
    'tight_market_end': ("Tight market regulation / cap rule ends", [_BO],
        True),
    'billing_deadline': ("Operating cost billing deadline", [_BU], True),
    'prepayment_adjust': ("Adjust operating cost prepayments", [_BU], True),
    'bved_cutoff': ("BVED exchange cutoff", [_BU], True),
    'meter_reading': ("Record meter readings", [_BO], True),
    'meter_calibration': ("Meter calibration expires / meter exchange",
        [_BO], True),
    'object_end': ("Object ends", [_BO], True),
    'cron_error': ("Scheduled task failed", ['real_estate.cron_task'],
        False),
    'cron_missing': ("Scheduled task not run", ['real_estate.cron_task'],
        False),
    'process_step': ("Process step", [], False),
    'inspection_defect': ("Inspection defect",
        ['real_estate.inspection.defect'], False),
    'inspection_overdue': ("Inspection overdue",
        ['real_estate.inspection'], False),
    'inspection_defect_overdue': ("Inspection defect overdue",
        ['real_estate.inspection.defect'], False),
    }


def _model_exists(name):
    try:
        Pool().get(name)
    except KeyError:
        return False
    return True


#**********************************************************************
class TaskType(
        DeactivableMixin, sequence_ordered(), ModelSQL, ModelView):
    "Task Type"
    __name__ = 'real_estate.task.type'

    name = fields.Char("Name", required=True, translate=True)
    code = fields.Selection('get_codes', "Code", sort=False,
        states={
            'readonly': Bool(Eval('code')) & (Eval('id', -1) >= 0),
            },
        help="Function of the type in the module (fixed catalog): hooks, "
             "rules and processes create and close tasks of this "
             "code. Cannot be changed once saved. Empty = own type "
             "without function in the module.")
    resource_models = fields.Function(fields.MultiSelection(
            'get_resources', "Reference Objects",
            help="Objects tasks of this type can refer to - from the "
                 "catalog for a code, else as selected. Empty = all."),
        'on_change_with_resource_models')
    custom_models = fields.MultiSelection('get_resources',
        "Reference Objects",
        states={'invisible': Bool(Eval('code'))},
        help="Objects tasks of this own type can refer to - empty = "
             "all.")
    all_models = fields.Boolean("All Objects", readonly=True)
    manual = fields.Function(fields.Boolean("Manual",
            help="Can be created by a user - types of the catalog marked "
                 "as automatic are only created by the module."),
        'on_change_with_manual', searcher='search_manual')
    for_model = fields.Function(fields.Char("For Object"),
        'get_for_model', searcher='search_for_model')
    responsible_group = fields.Many2One('res.group', "Responsible Group",
        help="Default responsibility: all members of the group.")
    responsible_user = fields.Many2One('res.user', "Responsible User",
        help="Default responsibility - takes precedence over the group.")
    responsible_role = fields.Many2One('real_estate.object_party.role',
        "Responsible Party Role", ondelete='SET NULL',
        help="The party holding this role on the object of the task "
             "(e.g. administrator of the property) on the due date "
             "becomes responsible - as user if linked to a user via an "
             "employee, else only shown; then user/group above apply.")
    creator_responsible = fields.Boolean(
        "Creator Responsible on Manual Entry",
        help="For a task entered manually without a responsible user from "
             "the party role: the creator becomes the responsible user - "
             "else the user stays empty (group of the type, the task can "
             "be taken over).")
    remind_days = fields.Integer("Remind Days Before",
        domain=[('remind_days', '>=', 0)],
        help="Reminder this many days before the due date.")
    remind_daily = fields.Boolean("Remind Daily",
        help="Remind every day until done, else once.")
    escalate_days = fields.Integer("Escalate Days After",
        domain=[If(Bool(Eval('escalate_days')),
                ('escalate_days', '>=', 0), ())],
        help="Escalation this many days after the due date - empty = "
             "no escalation.")
    escalation_group = fields.Many2One('res.group', "Escalation Group",
        states={'required': Bool(Eval('escalate_days'))})
    recurrence_months = fields.Integer("Recurrence (Months)",
        domain=[If(Bool(Eval('recurrence_months')),
                ('recurrence_months', '>', 0), ())],
        help="Default recurrence - empty = once.")
    email = fields.Boolean("E-Mail",
        help="Additionally remind by e-mail (needs an SMTP configuration "
             "of the server).")
    icon = fields.Selection('list_icons', "Icon")
    note_on_done = fields.Boolean("Note on Done",
        help="Add a note to the referenced record when done.")
    description = fields.Text("Description")

    @classmethod
    def __setup__(cls):
        super().__setup__()
        t = cls.__table__()
        cls._sql_constraints += [
            ('code_unique', Unique(t, t.code),
                'real_estate.msg_task_type_code_unique'),
            ]

    @classmethod
    def get_codes(cls):
        # Labels as messages: a selection from a method is not translated
        return [(None, '')] + [
            (code, gettext(f'real_estate.msg_task_code_{code}'))
            for code in TASK_CODES]

    @classmethod
    def get_resources(cls):
        return Pool().get('real_estate.task').get_resources()[1:]

    @fields.depends('code', 'custom_models')
    def on_change_with_resource_models(self, name=None):
        if self.code in TASK_CODES:
            return list(TASK_CODES[self.code][1])
        return list(self.custom_models or [])

    @fields.depends('code')
    def on_change_with_manual(self, name=None):
        if self.code in TASK_CODES:
            return TASK_CODES[self.code][2]
        return True

    @fields.depends('code', 'name')
    def on_change_code(self):
        if self.code in TASK_CODES and not self.name:
            self.name = TASK_CODES[self.code][0]

    @classmethod
    def search_manual(cls, name, clause):
        _, operator, value = clause[:3]
        manual = [c for c, (_, _, m) in TASK_CODES.items() if m]
        positive = ['OR', ('code', '=', None), ('code', 'in', manual)]
        if (operator == '=') == bool(value):
            return positive
        return [('code', 'in', [c for c in TASK_CODES
                    if c not in manual])]

    def get_for_model(self, name):
        return None

    @classmethod
    def search_for_model(cls, name, clause):
        "Types allowed for tasks referring to the model (clause value)"
        model = clause[2]
        if not model:
            return []
        codes = [c for c, (_, models, _) in TASK_CODES.items()
            if not models or model in models]
        return ['OR',
            ('code', 'in', codes),
            [('code', '=', None),
                ['OR', ('all_models', '=', True),
                    ('custom_models', 'in', model)]],
            ]

    def allows_model(self, model):
        models = self.resource_models
        return not models or model in models

    @classmethod
    def create(cls, vlist):
        return super().create([cls._set_all_models(v) for v in vlist])

    @classmethod
    def write(cls, *args):
        actions = iter(args)
        args = []
        for records, values in zip(actions, actions):
            if 'custom_models' in values:
                values = cls._set_all_models(values)
            args.extend((records, values))
        super().write(*args)

    @classmethod
    def _set_all_models(cls, values):
        values = values.copy()
        values['all_models'] = not values.get('custom_models')
        return values

    @classmethod
    def list_icons(cls):
        return Pool().get('res.notification').list_icons()

    @classmethod
    def default_remind_days(cls):
        return 0

    @classmethod
    def default_icon(cls):
        return 'tryton-notification'

    @classmethod
    def get_by_code(cls, code, strict=True):
        with Transaction().set_context(active_test=False):
            types = cls.search([('code', '=', code)], limit=1)
        if not types:
            if not strict:
                return None
            raise ValidationError(gettext(
                    'real_estate.msg_task_type_unknown', code=code))
        return types[0]


#**********************************************************************
class Task(Workflow, ModelSQL, ModelView):
    "Task"
    __name__ = 'real_estate.task'

    _states_open = {'readonly': Eval('state') != 'open'}

    company = fields.Many2One('company.company', "Company", required=True,
        states=_states_open)
    name = fields.Char("Subject", required=True, states=_states_open)
    task_type = fields.Many2One('real_estate.task.type', "Type",
        required=True, ondelete='RESTRICT', states=_states_open,
        domain=[
            ('for_model', '=', Eval('resource_model', '')),
            If(Eval('automatic', False), (), ('manual', '=', True)),
            ],
        help="Only types for the reference object; types of the module "
             "marked as automatic only for automatically created "
             "tasks.")
    resource_model = fields.Function(fields.Char("Reference Object"),
        'on_change_with_resource_model')
    automatic = fields.Boolean("Automatic", readonly=True,
        help="Created by the module (hook, rule or process).")
    resource = fields.Reference("Reference", selection='get_resources',
        states={
            'readonly': Eval('state') != 'open',
            'required': ~Bool(Eval('contract')),
            },
        help="Record the task refers to - empty when created on the "
             "'Tasks' tab of a contract: the contract.")
    # Not statically readonly: the client must send it when a task is
    # created on the contract's 'Tasks' tab (parent field)
    contract = fields.Many2One('real_estate.contract', "Contract",
        ondelete='CASCADE', states={'readonly': True},
        help="Contract of the reference (derived).")
    property = fields.Many2One('real_estate.base_object', "Property",
        readonly=True, ondelete='CASCADE',
        help="Property of the reference (derived).")
    due_date = fields.Date("Due Date",
        states={
            'readonly': Eval('state') != 'open',
            'required': Eval('state') == 'open',
            })
    remind_date = fields.Date("Remind Date", states=_states_open,
        help="Date of the reminder - default: due date minus the remind "
             "days of the type.")
    responsible_user = fields.Many2One('res.user', "Responsible User",
        states=_states_open)
    responsible_group = fields.Many2One('res.group', "Responsible Group",
        states=_states_open,
        help="All members of the group see the task and are "
             "reminded.")
    responsible_party = fields.Many2One('party.party', "Responsible Party",
        ondelete='SET NULL', states={'readonly': True},
        help="Party holding the responsible role of the type on the "
             "object of the task on the due date (e.g. administrator, "
             "caretaker).")
    priority = fields.Selection([
            ('low', "Low"),
            ('normal', "Normal"),
            ('high', "High"),
            ], "Priority", required=True, sort=False, states=_states_open)
    description = fields.Text("Description", states=_states_open)
    result = fields.Text("Result",
        states={'readonly': Eval('state') == 'cancelled'},
        help="Result / note on completion (required to cancel).")
    state = fields.Selection([
            ('planned', "Planned"),
            ('open', "Open"),
            ('done', "Done"),
            ('cancelled', "Cancelled"),
            ], "State", readonly=True, required=True, sort=False,
        help="Planned: step of a process not due yet (no due date, no "
             "reminder) - opened by the process.")
    done_by = employee_field("Done by", states=['open', 'done', 'cancelled'])
    done_date = fields.Date("Done on", readonly=True)
    recurrence_months = fields.Integer("Recurrence (Months)",
        domain=[If(Bool(Eval('recurrence_months')),
                ('recurrence_months', '>', 0), ())],
        states=_states_open,
        help="When done, a new task is created this many months "
             "later.")
    previous = fields.Many2One('real_estate.task', "Previous",
        readonly=True, ondelete='SET NULL')
    origin = fields.Reference("Origin", selection='get_origins',
        readonly=True, help="Rule or process - empty = manual.")
    origin_key = fields.Char("Origin Key", readonly=True)
    notified_date = fields.Date("Last Reminder", readonly=True)
    escalated_date = fields.Date("Escalated on", readonly=True)
    is_mine = fields.Function(fields.Boolean("Mine"),
        'get_is_mine', searcher='search_is_mine')
    overdue = fields.Function(fields.Boolean("Overdue"),
        'get_overdue', searcher='search_overdue')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._order = [
            ('due_date', 'ASC'),
            ('priority', 'DESC'),
            ('id', 'ASC'),
            ]
        cls._transitions |= {
            ('open', 'done'),
            ('open', 'cancelled'),
            ('done', 'open'),
            ('cancelled', 'open'),
            # planned steps of processes
            ('planned', 'open'),
            ('planned', 'cancelled'),
            ('cancelled', 'planned'),
            }
        cls._buttons.update({
            'done': {
                'invisible': Eval('state') != 'open',
                'depends': ['state'],
                },
            'cancel': {
                'invisible': ~Eval('state').in_(['open', 'planned']),
                'depends': ['state'],
                },
            'reopen': {
                'invisible': Eval('state').in_(['open', 'planned']),
                'depends': ['state'],
                },
            'postpone': {
                'invisible': Eval('state') != 'open',
                'depends': ['state'],
                },
            'take': {
                'invisible': Eval('state') != 'open',
                'depends': ['state'],
                },
            })

    @classmethod
    def view_attributes(cls):
        return super().view_attributes() + [
            ('/tree', 'visual', If(Eval('overdue', False), 'danger',
                    If(Eval('state').in_(['planned', 'done', 'cancelled']),
                        'muted',
                        If(Eval('priority') == 'high', 'warning', ''))),
                ['overdue', 'priority', 'state']),
            ]

    @classmethod
    def get_resources(cls):
        Model = Pool().get('ir.model')
        return [(None, '')] + [(m, Model.get_name(m))
            for m in cls._resource_models()]

    @classmethod
    def _resource_models(cls):
        return [m for m in TASK_RESOURCES if _model_exists(m)]

    @classmethod
    def _resource_company(cls, record):
        "Company of a referenced record (rule tasks, hooks)"
        if record is None:
            return None
        company = getattr(record, 'company', None)
        if company:
            return company
        contract, property_ = cls._resource_links(record)
        if contract:
            return contract.company
        if property_:
            return property_.company
        return None

    @classmethod
    def get_origins(cls):
        pool = Pool()
        Model = pool.get('ir.model')
        models = [m for m in ['real_estate.task.rule',
                'real_estate.process'] if _model_exists(m)]
        return [(None, '')] + [(m, Model.get_name(m)) for m in models]

    @staticmethod
    def default_company():
        return Transaction().context.get('company')

    @staticmethod
    def default_automatic():
        return False

    @fields.depends('resource', 'contract', '_parent_contract.id',
        'property', '_parent_property.id')
    def on_change_with_resource_model(self, name=None):
        if self.resource:
            return self.resource.__name__
        if self.contract:
            return 'real_estate.contract'
        if self.property:
            return 'real_estate.base_object'
        return None

    @staticmethod
    def default_state():
        return 'open'

    @staticmethod
    def default_priority():
        return 'normal'

    @fields.depends('task_type', 'responsible_user', 'responsible_group',
        'responsible_party', 'resource', 'contract', '_parent_contract.id',
        'property', '_parent_property.id', 'company', 'recurrence_months',
        'due_date', 'remind_date', 'name')
    def on_change_task_type(self):
        type_ = self.task_type
        if not type_:
            return
        if not self.responsible_user and not self.responsible_group:
            (self.responsible_user, self.responsible_group,
                self.responsible_party) = self._default_responsible(type_,
                self.resource or self.contract or self.property,
                self.due_date, self.company, manual=True)
        if not self.recurrence_months:
            self.recurrence_months = type_.recurrence_months
        if not self.name:
            self.name = type_.name
        self.remind_date = self._default_remind_date()

    @fields.depends('task_type', 'due_date', methods=[
            '_default_remind_date'])
    def on_change_due_date(self):
        self.remind_date = self._default_remind_date()

    @fields.depends('task_type', 'due_date')
    def _default_remind_date(self):
        if not self.due_date:
            return None
        days = (self.task_type.remind_days or 0
            if self.task_type else 0)
        return self.due_date - datetime.timedelta(days=days)

    def get_rec_name(self, name):
        return f'{self.name} ({self.due_date:%d.%m.%Y})' if self.due_date \
            else self.name

    @classmethod
    def search_rec_name(cls, name, clause):
        return [('name',) + tuple(clause[1:])]

    def get_is_mine(self, name):
        User = Pool().get('res.user')
        return bool(
            (self.responsible_user
                and self.responsible_user.id == Transaction().user)
            or (self.responsible_group
                and self.responsible_group.id in User.get_groups()))

    @classmethod
    def search_is_mine(cls, name, clause):
        User = Pool().get('res.user')
        _, operator, value = clause[:3]
        mine = ['OR',
            ('responsible_user', '=', Transaction().user),
            ('responsible_group', 'in', list(User.get_groups())),
            ]
        positive = (operator == '=') == bool(value)
        return mine if positive else ['NOT', mine]

    def get_overdue(self, name):
        Date = Pool().get('ir.date')
        return bool(self.state == 'open' and self.due_date
            and self.due_date < Date.today())

    @classmethod
    def search_overdue(cls, name, clause):
        Date = Pool().get('ir.date')
        _, operator, value = clause[:3]
        overdue = [('state', '=', 'open'), ('due_date', '<', Date.today())]
        positive = (operator == '=') == bool(value)
        return overdue if positive else ['NOT', overdue]

    # ------------------------------------------------------------------
    # Derived contract / property (stored, spec 13.1)

    @classmethod
    def _resource_links(cls, resource):
        """(contract, property) of a referenced record."""
        if not resource or getattr(resource, 'id', None) is None \
                or resource.id < 0:
            return None, None
        name = resource.__name__
        contract = None
        if name == 'real_estate.contract':
            contract = resource
        elif name in ('real_estate.contract.party',
                'real_estate.contract.rent_adjustment',
                'real_estate.contract.term.adjustment'):
            contract = getattr(resource, 'contract', None)
        if contract:
            return contract, contract.property
        if name == 'real_estate.base_object':
            node = resource
            while node and node.type != 'property':
                node = node.parent
            return None, node
        if name == 'real_estate.billing_unit':
            return None, getattr(resource, 'property', None)
        if name in ('real_estate.inspection', 'real_estate.inspection.defect',
                'real_estate.meter_reading.sheet'):
            return None, getattr(resource, 'property', None)
        return None, None

    @staticmethod
    def _resource_instance(value):
        "Record of a reference value ('model,id' or record)"
        if not value or not isinstance(value, str):
            return value or None
        model, _, id_ = value.partition(',')
        try:
            return Pool().get(model)(int(id_))
        except (KeyError, ValueError):
            return None

    @classmethod
    def _role_objects(cls, resource):
        """Object ids of a reference by level, most specific first: the
        objects of the contract items (resp. the object itself or the
        property), then their parents up to the property."""
        if (not resource or getattr(resource, 'id', None) is None
                or resource.id < 0):
            return []
        contract, property_ = cls._resource_links(resource)
        if contract:
            level = [o for item in contract.items for o in item.objects]
            if not level and contract.property:
                level = [contract.property]
        elif resource.__name__ == 'real_estate.base_object':
            level = [resource]
        elif resource.__name__ == 'real_estate.meter_reading.sheet':
            level = [resource.base_object]
        elif getattr(resource, 'building', None):
            # inspection: building, then up to the property
            level = [resource.building]
        elif property_:
            level = [property_]
        else:
            return []
        levels, seen = [], set()
        while level:
            ids = []
            for obj in level:
                if obj.id not in seen:
                    seen.add(obj.id)
                    ids.append(obj.id)
            if ids:
                levels.append(ids)
            level = [o.parent for o in level
                if o.parent and o.parent.id not in seen]
        return levels

    @classmethod
    def _role_responsible(cls, role, resource, date=None, company=None):
        """(party, user) holding the party role on the objects of the
        reference on 'date': the most specific object level wins, on one
        level the latest 'valid from'. The user is the only active user
        linked to an employee of the party in the company valid on the
        date - else None."""
        pool = Pool()
        ObjectParty = pool.get('real_estate.object_party')
        Employee = pool.get('company.employee')
        User = pool.get('res.user')
        if not role:
            return None, None
        date = date or pool.get('ir.date').today()
        company = getattr(company, 'id', company)
        with without_check_access():
            party = None
            for ids in cls._role_objects(resource):
                found = ObjectParty.search([
                        ('base_object', 'in', ids),
                        ('role', '=', role.id),
                        ['OR', ('valid_from', '=', None),
                            ('valid_from', '<=', date)],
                        ['OR', ('valid_to', '=', None),
                            ('valid_to', '>=', date)],
                        ], order=[('valid_from', 'DESC NULLS LAST'),
                        ('id', 'DESC')], limit=1)
                if found:
                    party = found[0].party
                    break
            if not party:
                return None, None
            domain = [
                ('party', '=', party.id),
                ['OR', ('start_date', '=', None), ('start_date', '<=', date)],
                ['OR', ('end_date', '=', None), ('end_date', '>=', date)],
                ]
            if company:
                domain.append(('company', '=', company))
            employees = Employee.search(domain)
            users = User.search([
                    ('employees', 'in', [e.id for e in employees]),
                    ]) if employees else []
        return party, (users[0] if len(users) == 1 else None)

    @classmethod
    def _default_responsible(cls, type_, resource, date=None, company=None,
            manual=False):
        """(user, group, party) of a new task of the type: the user of the
        party role on the object, else the creator for a manual entry with
        'creator_responsible', else the user of the type (may be empty);
        the group of the type in any case."""
        User = Pool().get('res.user')
        party, user = cls._role_responsible(
            type_.responsible_role, resource, date, company)
        if not user:
            if manual and type_.creator_responsible:
                user = User(Transaction().user)
            else:
                user = type_.responsible_user
        return user, type_.responsible_group, party

    @classmethod
    def _complete_values(cls, values):
        values = values.copy()
        if 'resource' in values:
            resource = values['resource']
            if isinstance(resource, str):
                model, id_ = resource.split(',')
                resource = Pool().get(model)(int(id_)) if id_ else None
            contract, property_ = cls._resource_links(resource)
            values['contract'] = contract.id if contract else None
            values['property'] = property_.id if property_ else None
        return values

    @classmethod
    def create(cls, vlist):
        pool = Pool()
        Type = pool.get('real_estate.task.type')
        user = Transaction().user
        vlist = [v.copy() for v in vlist]
        for values in vlist:
            # Created on the contract's tab: the contract is the reference
            if not values.get('resource') and values.get('contract'):
                values['resource'] = (
                    f"real_estate.contract,{values['contract']}")
            # Created on the property's tab: the property is the reference
            elif not values.get('resource') and values.get('property'):
                values['resource'] = (
                    f"real_estate.base_object,{values['property']}")
        vlist = [cls._complete_values(v) for v in vlist]
        for values in vlist:
            type_ = (Type(values['task_type'])
                if values.get('task_type') else None)
            # Responsibility: given, else the defaults of the type (party
            # role, creator on manual entry, user/group of the type)
            no_responsible = (not values.get('responsible_user')
                and not values.get('responsible_group'))
            if type_ and (no_responsible or (type_.responsible_role
                        and not values.get('responsible_party'))):
                r_user, r_group, r_party = cls._default_responsible(type_,
                    cls._resource_instance(values.get('resource')),
                    values.get('due_date'), values.get('company'),
                    manual=not values.get('automatic'))
                if not values.get('responsible_party'):
                    values['responsible_party'] = (
                        r_party.id if r_party else None)
                if no_responsible:
                    values['responsible_user'] = (
                        r_user.id if r_user else None)
                    values['responsible_group'] = (
                        r_group.id if r_group else None)
            # Nobody responsible at all: the creator
            if (not values.get('responsible_user')
                    and not values.get('responsible_group') and user):
                values['responsible_user'] = user
            if type_ and 'recurrence_months' not in values:
                values['recurrence_months'] = type_.recurrence_months
            if (type_ and values.get('due_date')
                    and not values.get('remind_date')):
                values['remind_date'] = values['due_date'] - (
                    datetime.timedelta(days=type_.remind_days or 0))
        return super().create(vlist)

    @classmethod
    def write(cls, *args):
        actions = iter(args)
        args = []
        for records, values in zip(actions, actions):
            args.extend((records, cls._complete_values(values)))
        super().write(*args)

    @classmethod
    def validate_fields(cls, tasks, field_names):
        super().validate_fields(tasks, field_names)
        if field_names & {'responsible_user', 'responsible_group', 'state'}:
            for task in tasks:
                if task.state == 'planned':
                    continue
                if (not task.responsible_user
                        and not task.responsible_group):
                    raise ValidationError(gettext(
                            'real_estate.msg_task_responsible',
                            task=task.rec_name))
        if field_names & {'origin', 'origin_key', 'state'}:
            cls._check_origin_key(tasks)

    @classmethod
    def _check_origin_key(cls, tasks):
        # One open task per origin and key (rules, hooks) - checked
        # here as well since SQLite has no partial unique constraint
        for task in tasks:
            if task.state != 'open' or not task.origin_key:
                continue
            domain = [
                ('id', '!=', task.id),
                ('state', '=', 'open'),
                ('origin_key', '=', task.origin_key),
                ('task_type', '=', task.task_type.id),
                ]
            domain.append(('origin', '=', str(task.origin))
                if task.origin else ('origin', '=', None))
            if cls.search(domain, limit=1):
                raise ValidationError(gettext(
                        'real_estate.msg_task_origin_key',
                        task=task.rec_name))

    @classmethod
    def copy(cls, tasks, default=None):
        default = default.copy() if default else {}
        for field in ('done_by', 'done_date', 'result', 'notified_date',
                'escalated_date', 'origin', 'origin_key', 'previous',
                'automatic'):
            default.setdefault(field, None)
        return super().copy(tasks, default=default)

    # ------------------------------------------------------------------
    # Workflow

    @classmethod
    @ModelView.button
    @Workflow.transition('done')
    def done(cls, tasks):
        pool = Pool()
        User = pool.get('res.user')
        Date = pool.get('ir.date')
        Note = pool.get('ir.note')
        today = Date.today()
        employee = User(Transaction().user).employee
        cls.write(tasks, {
                'done_date': today,
                'done_by': employee.id if employee else None,
                })
        to_create, notes = [], []
        for task in tasks:
            if task.recurrence_months:
                to_create.append(task._next_recurrence_values())
            if (task.task_type.note_on_done and task.resource
                    and task.resource.id >= 0):
                notes.append({
                        'resource': str(task.resource),
                        'message': gettext(
                            'real_estate.msg_task_note_done',
                            task=task.name,
                            result=task.result or ''),
                        })
        if to_create:
            cls.create(to_create)
        if notes:
            Note.create(notes)

    def _next_recurrence_values(self):
        months = relativedelta(months=self.recurrence_months)
        return {
            'company': self.company.id,
            'name': self.name,
            'task_type': self.task_type.id,
            'resource': str(self.resource),
            'due_date': self.due_date + months,
            'remind_date': (self.remind_date + months
                if self.remind_date else None),
            'responsible_user': (self.responsible_user.id
                if self.responsible_user else None),
            'responsible_group': (self.responsible_group.id
                if self.responsible_group else None),
            'priority': self.priority,
            'description': self.description,
            'recurrence_months': self.recurrence_months,
            'previous': self.id,
            'automatic': self.automatic,
            }

    @classmethod
    @ModelView.button
    @Workflow.transition('cancelled')
    def cancel(cls, tasks):
        for task in tasks:
            if not task.result:
                raise ValidationError(gettext(
                        'real_estate.msg_task_cancel_result',
                        task=task.rec_name))

    @classmethod
    @ModelView.button
    @Workflow.transition('open')
    def reopen(cls, tasks):
        pool = Pool()
        ModelData = pool.get('ir.model.data')
        User = pool.get('res.user')
        user = Transaction().user
        admin = ModelData.get_id('real_estate', 'group_real_estate_admin')
        if user and admin not in User.get_groups():
            for task in tasks:
                if task.create_uid.id != user:
                    raise AccessError(gettext(
                            'real_estate.msg_task_reopen',
                            task=task.rec_name))
        cls.write(tasks, {'done_date': None, 'done_by': None})

    @classmethod
    @Workflow.transition('open')
    def activate(cls, tasks):
        "A planned task (process step) becomes due"
        pass

    @classmethod
    @Workflow.transition('planned')
    def replan(cls, tasks):
        "A task cancelled with its process becomes planned again"
        cls.write(tasks, {'result': None, 'due_date': None,
                'remind_date': None, 'notified_date': None,
                'escalated_date': None})

    @classmethod
    @ModelView.button_action('real_estate.wizard_task_postpone')
    def postpone(cls, tasks):
        pass

    @classmethod
    @ModelView.button
    def take(cls, tasks):
        cls.write(tasks, {'responsible_user': Transaction().user})

    # ------------------------------------------------------------------
    # Programming interface for the module code (hooks, spec 4.3)

    @classmethod
    def _open_for(cls, record, type_code):
        Type = Pool().get('real_estate.task.type')
        # Hooks never fail because of a deleted task type
        type_ = Type.get_by_code(type_code, strict=False)
        if not type_:
            return []
        return cls.search([
                ('resource', '=', str(record)),
                ('task_type', '=', type_.id),
                ('state', '=', 'open'),
                ])

    @classmethod
    def create_for(cls, record, type_code, due_date, name=None,
            description=None, user=None, group=None, origin=None,
            origin_key=None, company=None):
        """Create a task for 'record' - idempotent: an open task
        of the type for the record (and origin key) is returned instead."""
        Type = Pool().get('real_estate.task.type')
        type_ = Type.get_by_code(type_code, strict=False)
        if not type_ or not type_.active:
            return None
        domain = [
            ('resource', '=', str(record)),
            ('task_type', '=', type_.id),
            ('state', '=', 'open'),
            ]
        if origin_key:
            domain.append(('origin_key', '=', origin_key))
        existing = cls.search(domain, limit=1)
        if existing:
            return existing[0]
        if company is None:
            company = (getattr(record, 'company', None)
                or Transaction().context.get('company'))
        values = {
            'company': getattr(company, 'id', company),
            'name': name or f'{type_.name}: {record.rec_name}',
            'task_type': type_.id,
            'resource': str(record),
            'due_date': due_date,
            'description': description,
            'responsible_user': getattr(user, 'id', user),
            'responsible_group': getattr(group, 'id', group),
            'origin': str(origin) if origin else None,
            'origin_key': origin_key,
            'automatic': True,
            }
        task, = cls.create([values])
        return task

    @classmethod
    def close_for(cls, record, type_code, result=None):
        "Set the open tasks of the type for 'record' to done"
        tasks = cls._open_for(record, type_code)
        if tasks:
            if result:
                cls.write(tasks, {'result': result})
            cls.done(tasks)
        return tasks

    @classmethod
    def cancel_for(cls, record, type_code, result=None):
        "Cancel the open tasks of the type for 'record'"
        tasks = cls._open_for(record, type_code)
        if tasks:
            cls.write(tasks, {'result': result or gettext(
                        'real_estate.msg_task_cancel_auto')})
            cls.cancel(tasks)
        return tasks

    # ------------------------------------------------------------------
    # Reminders and escalation (spezifikation-wiedervorlage.md 6, phase B)

    def _recipients(self, group=None):
        """Active users to remind: the responsible user, else the active
        members of the responsible group (or of the given group)."""
        if group is None and self.responsible_user:
            return [self.responsible_user] if self.responsible_user.active \
                else []
        group = group or self.responsible_group
        if not group:
            return []
        return [u for u in group.users if u.active]

    @classmethod
    def notify(cls, companies=None, date=None):
        """Remind the responsible users of due open tasks (client
        notification, optionally e-mail) and escalate overdue ones - at
        most once a day per task (remind_daily) resp. once at all.
        Returns (reminded, escalated) task counts."""
        pool = Pool()
        Date = pool.get('ir.date')
        today = date or Date.today()
        domain = [
            ('state', '=', 'open'),
            ('remind_date', '<=', today),
            ]
        if companies:
            domain.append(('company', 'in', [c.id for c in companies]))
        reminded = []
        for task in cls.search(domain):
            if task.notified_date and (task.notified_date >= today
                    or not task.task_type.remind_daily):
                continue
            for user in task._recipients():
                task._notify(user, gettext(
                        'real_estate.msg_task_reminder_label',
                        task=task.name), escalation=False)
            reminded.append(task)
        if reminded:
            cls.write(reminded, {'notified_date': today})

        escalated = []
        domain = [
            ('state', '=', 'open'),
            ('escalated_date', '=', None),
            ('task_type.escalate_days', '!=', None),
            ('task_type.escalation_group', '!=', None),
            ('due_date', '<', today),
            ]
        if companies:
            domain.append(('company', 'in', [c.id for c in companies]))
        for task in cls.search(domain):
            type_ = task.task_type
            if task.due_date + datetime.timedelta(
                    days=type_.escalate_days) > today:
                continue
            for user in task._recipients(group=type_.escalation_group):
                task._notify(user, gettext(
                        'real_estate.msg_task_escalation_label',
                        task=task.name), escalation=True)
            escalated.append(task)
        if escalated:
            cls.write(escalated, {'escalated_date': today})
        return len(reminded), len(escalated)

    def _notify(self, user, label, escalation=False):
        description = gettext('real_estate.msg_task_reminder_description',
            due_date=self.due_date.strftime('%d.%m.%Y'),
            resource=(self.resource.rec_name
                if self.resource and self.resource.id >= 0 else ''))
        self.__class__.notify_user([self],
            icon=self.task_type.icon or 'tryton-notification',
            label=label, description=description, user=user.id)
        if (self.task_type.email and user.email
                and getattr(user, 'task_email', True)):
            self._send_email(user, label, description)

    def _send_email(self, user, subject, body):
        "E-mail reminder - an error (e.g. no SMTP) is only logged"
        Email = Pool().get('ir.email')
        try:
            Email.send(to=user.email, subject=subject, body=body,
                record=(self.__name__, self.id))
        except Exception:
            logger.warning('task %s: e-mail to %s failed', self.id,
                user.login, exc_info=True)

    @classmethod
    def cron_error(cls, cron_task, company, message):
        """Task 'cron_error' (S01) for a failed scheduled task - an open
        task of the same scheduled task gets the new error appended."""
        Date = Pool().get('ir.date')
        task = cls.create_for(cron_task, 'cron_error', Date.today(),
            description=message, company=company)
        if task and task.description != message:
            cls.write([task], {'description': '\n\n'.join(filter(None, [
                                task.description, message]))})
        return task

#**********************************************************************
class TaskPostponeStart(ModelView):
    "Postpone Task - Start"
    __name__ = 'real_estate.task.postpone.start'

    due_date = fields.Date("New Due Date", required=True)
    reason = fields.Text("Reason", required=True)


#**********************************************************************
class TaskPostpone(Wizard):
    "Postpone Task"
    __name__ = 'real_estate.task.postpone'

    start = StateView('real_estate.task.postpone.start',
        'real_estate.task_postpone_start_view_form', [
            Button("Cancel", 'end', 'tryton-cancel'),
            Button("Postpone", 'postpone', 'tryton-ok', default=True),
            ])
    postpone = StateTransition()

    def default_start(self, fields):
        if self.record:
            return {'due_date': self.record.due_date}
        return {}

    def transition_postpone(self):
        pool = Pool()
        Task = pool.get('real_estate.task')
        User = pool.get('res.user')
        Date = pool.get('ir.date')
        user = User(Transaction().user)
        for task in self.records:
            if task.state != 'open':
                continue
            delta = self.start.due_date - task.due_date
            line = gettext('real_estate.msg_task_postponed',
                date=Date.today().strftime('%d.%m.%Y'), user=user.rec_name,
                old=task.due_date.strftime('%d.%m.%Y'),
                new=self.start.due_date.strftime('%d.%m.%Y'),
                reason=self.start.reason)
            Task.write([task], {
                    'due_date': self.start.due_date,
                    'remind_date': (task.remind_date + delta
                        if task.remind_date else None),
                    'notified_date': None,
                    'escalated_date': None,
                    'description': '\n'.join(filter(None, [
                                task.description, line])),
                    })
        return 'end'


#**********************************************************************
class TaskCreateStart(ModelView):
    "New Task - Start"
    __name__ = 'real_estate.task.create.start'

    resource_model = fields.Char("Reference Object", readonly=True)
    task_type = fields.Many2One('real_estate.task.type', "Type",
        required=True,
        domain=[
            ('for_model', '=', Eval('resource_model', '')),
            ('manual', '=', True),
            ])
    resource = fields.Char("Reference")
    name = fields.Char("Subject", required=True)
    due_date = fields.Date("Due Date", required=True)
    responsible_user = fields.Many2One('res.user', "Responsible User")
    responsible_group = fields.Many2One('res.group', "Responsible Group")
    responsible_party = fields.Many2One('party.party', "Responsible Party",
        states={'readonly': True})
    priority = fields.Selection([
            ('low', "Low"),
            ('normal', "Normal"),
            ('high', "High"),
            ], "Priority", required=True, sort=False)
    recurrence_months = fields.Integer("Recurrence (Months)")
    description = fields.Text("Description")

    @staticmethod
    def default_priority():
        return 'normal'

    @fields.depends('task_type', 'name', 'responsible_user',
        'responsible_group', 'responsible_party', 'resource', 'due_date',
        'recurrence_months')
    def on_change_task_type(self):
        pool = Pool()
        Task = pool.get('real_estate.task')
        type_ = self.task_type
        if not type_:
            return
        if not self.name:
            self.name = type_.name
        if not self.responsible_user and not self.responsible_group:
            (self.responsible_user, self.responsible_group,
                self.responsible_party) = Task._default_responsible(type_,
                Task._resource_instance(self.resource), self.due_date,
                Transaction().context.get('company'), manual=True)
        if not self.recurrence_months:
            self.recurrence_months = type_.recurrence_months


#**********************************************************************
class TaskCreate(Wizard):
    "New Task"
    __name__ = 'real_estate.task.create'

    start = StateView('real_estate.task.create.start',
        'real_estate.task_create_start_view_form', [
            Button("Cancel", 'end', 'tryton-cancel'),
            Button("Create", 'create_', 'tryton-ok', default=True),
            ])
    create_ = StateTransition()

    def default_start(self, fields):
        # the reference (for the party role) only for a single record
        return {
            'resource_model': self.model.__name__ if self.model else None,
            'resource': (str(self.record)
                if self.record and len(self.records) == 1 else None),
            }

    def transition_create_(self):
        Task = Pool().get('real_estate.task')
        start = self.start
        Task.create([{
                    'company': (getattr(self.record, 'company', None)
                        or Transaction().context.get('company')),
                    'name': start.name,
                    'task_type': start.task_type.id,
                    'resource': str(record),
                    'due_date': start.due_date,
                    'responsible_user': (start.responsible_user.id
                        if start.responsible_user else None),
                    'responsible_group': (start.responsible_group.id
                        if start.responsible_group else None),
                    'responsible_party': (start.responsible_party.id
                        if start.responsible_party
                        and str(record) == start.resource else None),
                    'priority': start.priority,
                    'recurrence_months': start.recurrence_months,
                    'description': start.description,
                    } for record in self.records])
        return 'end'


#**********************************************************************
class Contract(metaclass=PoolMeta):
    __name__ = 'real_estate.contract'

    @classmethod
    def _cron_task_notify(cls, re_accounting, task=None):
        "Scheduled task 'task_notify': reminders and escalation"
        pool = Pool()
        Company = pool.get('company.company')
        Task = pool.get('real_estate.task')
        companies = Company.search([('re_accounting', '=', re_accounting.id)])
        if companies:
            Task.notify(companies)

    # All tasks of the contract, also of its rent adjustments,
    # adjustments and parties (stored 'contract', spec 13.1) - new ones
    # can be added directly ('+'), the contract is then the reference
    tasks = fields.One2Many('real_estate.task', 'contract',
        "Tasks", order=[('state', 'ASC'), ('due_date', 'ASC')])
    # Tab "Tasks and Processes": open tasks ('+' creates a task) and
    # the history of done/cancelled tasks
    tasks_open = fields.One2Many('real_estate.task', 'contract',
        "Tasks", filter=[('state', '=', 'open')],
        order=[('due_date', 'ASC'), ('id', 'ASC')])
    tasks_history = fields.One2Many('real_estate.task', 'contract',
        "Tasks", filter=[('state', 'in', ['done', 'cancelled'])],
        order=[('due_date', 'DESC'), ('id', 'DESC')], readonly=True)


_TASK_OPEN = [('state', '=', 'open')]
_TASK_HISTORY = [('state', 'in', ['done', 'cancelled'])]
_ORDER_OPEN = [('due_date', 'ASC'), ('id', 'ASC')]
_ORDER_HISTORY = [('due_date', 'DESC'), ('id', 'DESC')]


class RentAdjustment(metaclass=PoolMeta):
    __name__ = 'real_estate.contract.rent_adjustment'

    # Tasks referring to the rent adjustment - '+' sets the reference
    tasks = fields.One2Many('real_estate.task', 'resource',
        "Tasks", order=[('state', 'ASC'), ('due_date', 'ASC')])
    # Tab "Tasks and Processes": open ('+') and history
    tasks_open = fields.One2Many('real_estate.task', 'resource', "Tasks",
        filter=_TASK_OPEN, order=_ORDER_OPEN)
    tasks_history = fields.One2Many('real_estate.task', 'resource', "Tasks",
        filter=_TASK_HISTORY, order=_ORDER_HISTORY, readonly=True)


class BillingUnit(metaclass=PoolMeta):
    __name__ = 'real_estate.billing_unit'

    tasks = fields.One2Many('real_estate.task', 'resource',
        "Tasks", order=[('state', 'ASC'), ('due_date', 'ASC')])
    # Tab "Tasks and Processes": open ('+') and history
    tasks_open = fields.One2Many('real_estate.task', 'resource', "Tasks",
        filter=_TASK_OPEN, order=_ORDER_OPEN)
    tasks_history = fields.One2Many('real_estate.task', 'resource', "Tasks",
        filter=_TASK_HISTORY, order=_ORDER_HISTORY, readonly=True)


class BaseObject(metaclass=PoolMeta):
    __name__ = 'real_estate.base_object'

    _not_property = {'invisible': Eval('type') == 'property'}
    _property = {'invisible': Eval('type') != 'property'}

    tasks = fields.One2Many('real_estate.task', 'resource',
        "Tasks", order=[('state', 'ASC'), ('due_date', 'ASC')])
    # A property additionally lists the tasks of all its objects
    property_tasks = fields.One2Many('real_estate.task', 'property',
        "Tasks of the Property", readonly=True,
        order=[('state', 'ASC'), ('due_date', 'ASC')],
        states={'invisible': Eval('type') != 'property'})
    # Tab "Tasks and Processes": the tasks of the object itself ('+'),
    # for a property all tasks of the property (objects, contracts,
    # billing units - stored 'property'), for a rental object also the
    # tasks of the contracts on it
    tasks_open = fields.One2Many('real_estate.task', 'resource', "Tasks",
        filter=_TASK_OPEN, order=_ORDER_OPEN, states=_not_property)
    tasks_history = fields.One2Many('real_estate.task', 'resource', "Tasks",
        filter=_TASK_HISTORY, order=_ORDER_HISTORY, readonly=True,
        states=_not_property)
    property_tasks_open = fields.One2Many('real_estate.task', 'property',
        "Tasks of the Property", filter=_TASK_OPEN, order=_ORDER_OPEN,
        states=_property)
    property_tasks_history = fields.One2Many('real_estate.task', 'property',
        "Tasks of the Property", filter=_TASK_HISTORY,
        order=_ORDER_HISTORY, readonly=True, states=_property)
    contract_tasks_open = fields.Function(fields.One2Many(
            'real_estate.task', None, "Tasks of the Contracts",
            readonly=True, states={'invisible': Eval('type') != 'object'}),
        'get_contract_tasks', setter='set_contract_tasks')
    contract_tasks_history = fields.Function(fields.One2Many(
            'real_estate.task', None, "Tasks of the Contracts",
            readonly=True, states={'invisible': Eval('type') != 'object'}),
        'get_contract_tasks', setter='set_contract_tasks')

    @classmethod
    def set_contract_tasks(cls, objects, name, value):
        pass

    @classmethod
    def get_contract_tasks(cls, objects, names):
        "Tasks of the contracts whose items contain the rental object"
        Task = Pool().get('real_estate.task')
        result = {n: {o.id: [] for o in objects} for n in names}
        for name in names:
            open_ = name == 'contract_tasks_open'
            for obj in objects:
                if obj.type != 'object':
                    continue
                result[name][obj.id] = [t.id for t in Task.search([
                            _TASK_OPEN[0] if open_ else _TASK_HISTORY[0],
                            ('contract.items.objects', '=', obj.id),
                            ], order=_ORDER_OPEN if open_ else _ORDER_HISTORY)]
        return result


class User(metaclass=PoolMeta):
    __name__ = 'res.user'

    task_email = fields.Boolean("Task Reminders by E-Mail",
        help="Receive the e-mail reminders of tasks whose type sends "
             "e-mails (in addition to the client notification).")

    @classmethod
    def default_task_email(cls):
        return True

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._preferences_fields.append('task_email')
