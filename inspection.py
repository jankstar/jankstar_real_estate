'Recurring inspections (spezifikation-pruefungen.md) - phases P1, P2'
import datetime

from dateutil.relativedelta import relativedelta

from trytond.exceptions import UserWarning
from trytond.i18n import gettext
from trytond.model import (
    DeactivableMixin, ModelSQL, ModelView, Unique, Workflow, fields,
    sequence_ordered)
from trytond.model.exceptions import AccessError, ValidationError
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Bool, Eval, If, PYSONDecoder
from trytond.report import Report
from trytond.transaction import Transaction, without_check_access
from trytond.wizard import StateReport, StateTransition, Wizard

INTERVAL_UNITS = [
    ('day', "Days"),
    ('week', "Weeks"),
    ('month', "Months"),
    ('year', "Years"),
    ]
INTERVAL_BASES = [
    ('fixed', "Fixed Rhythm"),
    ('done', "From Execution"),
    ]
MONTHS = [
    (None, ''),
    ('1', "January"),
    ('2', "February"),
    ('3', "March"),
    ('4', "April"),
    ('5', "May"),
    ('6', "June"),
    ('7', "July"),
    ('8', "August"),
    ('9', "September"),
    ('10', "October"),
    ('11', "November"),
    ('12', "December"),
    ]
SEVERITIES = [
    ('critical', "Critical"),
    ('major', "Major"),
    ('minor', "Minor"),
    ('note', "Note"),
    ]


def add_interval(date, interval, unit):
    "Date plus 'interval' units"
    interval = interval or 0
    if unit == 'day':
        return date + datetime.timedelta(days=interval)
    if unit == 'week':
        return date + datetime.timedelta(weeks=interval)
    if unit == 'month':
        return date + relativedelta(months=interval)
    return date + relativedelta(years=interval)


def apply_preferred_month(date, month, not_before):
    """First of the preferred month in the year of 'date' - in the
    following year if that is not after 'not_before' (spec 5)"""
    if not month:
        return date
    result = datetime.date(date.year, int(month), 1)
    if not_before and result <= not_before:
        result = datetime.date(date.year + 1, int(month), 1)
    return result


def next_due_date(due_date, done_date, interval, unit, basis,
        preferred_month=None):
    """Next due date after an execution on 'done_date' (spec 5): fixed
    rhythm from the previous due date (repeated until after the execution)
    or from the execution date"""
    if not interval or interval < 1:
        return None
    if basis == 'fixed' and due_date:
        result = add_interval(due_date, interval, unit)
        while result <= done_date:
            result = add_interval(result, interval, unit)
    else:
        result = add_interval(done_date, interval, unit)
    return apply_preferred_month(result, preferred_month, done_date)


def _decode(domain):
    return PYSONDecoder({}).decode(domain) if domain else []


#**********************************************************************
class EquipmentKind(DeactivableMixin, ModelSQL, ModelView):
    "Equipment Kind"
    __name__ = 'real_estate.equipment.kind'

    name = fields.Char("Name", required=True, translate=True)
    code = fields.Char("Code", help="Short code for the equipment kind, e.g. 'smoke detector'. Used in the inspection type to select the equipment of this kind.")

    @classmethod
    def __setup__(cls):
        super().__setup__()
        t = cls.__table__()
        cls._sql_constraints += [
            ('code_unique', Unique(t, t.code),
                'real_estate.msg_equipment_kind_code_unique'),
            ]
        cls._order.insert(0, ('name', 'ASC'))


class BaseObject(metaclass=PoolMeta):
    __name__ = 'real_estate.base_object'

    equipment_kind = fields.Many2One('real_estate.equipment.kind',
        "Equipment Kind", ondelete='RESTRICT',
        states={'invisible': Eval('type') != 'equipment'},
        help="Kind of the equipment (e.g. smoke detector, elevator) - "
             "selects the equipment of inspections.")
    # Tab "Inspections": plans of a property (all, also of its buildings)
    # resp. of a building
    property_inspection_plans = fields.One2Many(
        'real_estate.inspection.plan', 'property', "Inspection Plans",
        states={'invisible': Eval('type') != 'property'})
    building_inspection_plans = fields.One2Many(
        'real_estate.inspection.plan', 'building', "Inspection Plans",
        states={'invisible': Eval('type') != 'building'})

    @classmethod
    def view_attributes(cls):
        return super().view_attributes() + [
            ('//page[@id="page_inspections"]', 'states', {
                    'invisible': Eval('type') == 'land',
                    }, ['type']),
            ]


#**********************************************************************
class InspectionChecklist(DeactivableMixin, ModelSQL, ModelView):
    "Inspection Checklist"
    __name__ = 'real_estate.inspection.checklist'

    name = fields.Char("Name", required=True, translate=True)
    items = fields.One2Many('real_estate.inspection.checklist.item',
        'checklist', "Check Items")


class InspectionChecklistItem(sequence_ordered(), ModelSQL, ModelView):
    "Inspection Checklist Item"
    __name__ = 'real_estate.inspection.checklist.item'

    checklist = fields.Many2One('real_estate.inspection.checklist',
        "Checklist", required=True, ondelete='CASCADE')
    section = fields.Char("Section", translate=True,
        help="Heading the item is grouped under.")
    question = fields.Char("Question", required=True, translate=True)
    answer_type = fields.Selection([
            ('ok_nok_na', "OK / Not OK / N/A"),
            ('yes_no', "Yes / No"),
            ('number', "Number"),
            ('text', "Text"),
            ('date', "Date"),
            ('selection', "Selection"),
            ], "Answer Type", required=True, sort=False)
    selection_values = fields.Text("Selection Values",
        states={
            'invisible': Eval('answer_type') != 'selection',
            'required': Eval('answer_type') == 'selection',
            },
        help="One value per line.")
    unit = fields.Many2One('product.uom', "Unit",
        states={'invisible': Eval('answer_type') != 'number'})
    min_value = fields.Float("Minimum",
        states={'invisible': Eval('answer_type') != 'number'})
    max_value = fields.Float("Maximum",
        states={'invisible': Eval('answer_type') != 'number'})
    mandatory = fields.Boolean("Mandatory")
    photo_on_nok = fields.Boolean("Photo if Not OK",
        states={'invisible': ~Eval('answer_type').in_(
                ['ok_nok_na', 'yes_no'])},
        help="A not OK answer requires an attachment.")
    create_defect_on_nok = fields.Boolean("Defect if Not OK",
        states={'invisible': ~Eval('answer_type').in_(
                ['ok_nok_na', 'yes_no'])},
        help="A not OK answer creates a defect.")
    default_severity = fields.Selection([(None, '')] + SEVERITIES,
        "Default Severity", sort=False,
        states={
            'invisible': ~Bool(Eval('create_defect_on_nok')),
            'required': Bool(Eval('create_defect_on_nok')),
            })

    @staticmethod
    def default_answer_type():
        return 'ok_nok_na'

    @staticmethod
    def default_mandatory():
        return True


#**********************************************************************
class InspectionType(DeactivableMixin, ModelSQL, ModelView):
    "Inspection Type"
    __name__ = 'real_estate.inspection.type'

    name = fields.Char("Name", required=True, translate=True)
    code = fields.Char("Code", help="Short code for the inspection type, e.g. 'annual inspection'. Used in the inspection plan to select the type of inspection.")
    category = fields.Selection([
            ('safety', "Safety"),
            ('technical', "Technical"),
            ('legal', "Legal"),
            ('walkthrough', "Walkthrough"),
            ], "Category", required=True, sort=False)
    legal_basis = fields.Text("Legal Basis", translate=True)
    scope = fields.Selection([
            ('property', "Property"),
            ('building', "Building"),
            ], "Scope", required=True, sort=False,
        help="Object of plan and inspection: one inspection = one notice, "
             "one report, one approval.")
    line_granularity = fields.Selection([
            ('none', "None"),
            ('unit', "Rental Unit"),
            ('equipment', "Equipment"),
            ], "Lines", required=True, sort=False,
        help="Results only in the header, or one line per rental unit "
             "resp. equipment below the object of the inspection.")
    equipment_kind = fields.Many2One('real_estate.equipment.kind',
        "Equipment Kind", ondelete='RESTRICT',
        states={'invisible': Eval('line_granularity') == 'none'},
        help="Equipment lines: only equipment of this kind. Rental unit "
             "lines: only units with equipment of this kind.")
    line_filter = fields.Char("Line Filter",
        states={'invisible': Eval('line_granularity') == 'none'},
        help="Additional PYSON domain on the objects of the lines, e.g. "
             "[[\"type_of_use\", \"=\", \"residential\"]].")
    interval = fields.Integer("Interval", required=True,
        domain=[('interval', '>=', 1)])
    interval_unit = fields.Selection(INTERVAL_UNITS, "Interval Unit",
        required=True, sort=False)
    interval_basis = fields.Selection(INTERVAL_BASES, "Interval Basis",
        required=True, sort=False,
        help="Fixed rhythm: next due date from the previous due date. From "
             "execution: from the date the inspection was done.")
    preferred_month = fields.Selection(MONTHS, "Preferred Month",
        sort=False,
        help="The due date is moved to the first of this month.")
    lead_time_days = fields.Integer("Lead Time (Days)",
        domain=[('lead_time_days', '>=', 0)],
        help="The inspection is created this many days before it is due.")
    tolerance_days = fields.Integer("Tolerance (Days)",
        domain=[('tolerance_days', '>=', 0)],
        help="Overdue this many days after the due date.")
    notice_days = fields.Integer("Notice Days",
        domain=[('notice_days', '>=', 0)],
        help="Minimum days between the tenant notice and the inspection - "
             "a warning when scheduling, not an error.")
    responsible_role = fields.Many2One('real_estate.object_party.role',
        "Responsible Party Role", ondelete='SET NULL')
    contractor_required = fields.Boolean("Contractor Required",
        help="Done only with contractor and external report number or an "
             "attachment.")
    requires_unit_access = fields.Boolean("Requires Unit Access")
    access_attempts = fields.Integer("Access Attempts",
        states={'invisible': ~Eval('requires_unit_access')})
    requires_approval = fields.Boolean("Requires Approval")
    approval_group = fields.Many2One('res.group', "Approval Group",
        states={
            'invisible': ~Eval('requires_approval'),
            'required': Bool(Eval('requires_approval')),
            })
    header_checklist = fields.Many2One('real_estate.inspection.checklist',
        "Header Checklist", ondelete='RESTRICT')
    line_checklist = fields.Many2One('real_estate.inspection.checklist',
        "Line Checklist", ondelete='RESTRICT',
        states={'invisible': Eval('line_granularity') == 'none'})
    process_template = fields.Many2One('real_estate.process.template',
        "Process Template", ondelete='RESTRICT',
        domain=[('model', '=', 'real_estate.inspection')],
        help="Steps of the inspection as tasks, scheduled from the planned "
             "date.")
    defect_days_critical = fields.Integer("Deadline Critical (Days)")
    defect_days_major = fields.Integer("Deadline Major (Days)")
    defect_days_minor = fields.Integer("Deadline Minor (Days)")

    @classmethod
    def __setup__(cls):
        super().__setup__()
        t = cls.__table__()
        cls._sql_constraints += [
            ('code_unique', Unique(t, t.code),
                'real_estate.msg_inspection_type_code_unique'),
            ]
        cls._order.insert(0, ('name', 'ASC'))

    @staticmethod
    def default_category():
        return 'walkthrough'

    @staticmethod
    def default_scope():
        return 'building'

    @staticmethod
    def default_line_granularity():
        return 'none'

    @staticmethod
    def default_interval():
        return 1

    @staticmethod
    def default_interval_unit():
        return 'year'

    @staticmethod
    def default_interval_basis():
        return 'fixed'

    @staticmethod
    def default_lead_time_days():
        return 30

    @staticmethod
    def default_tolerance_days():
        return 14

    @staticmethod
    def default_notice_days():
        return 14

    @staticmethod
    def default_access_attempts():
        return 2

    @staticmethod
    def default_defect_days_critical():
        return 1

    @staticmethod
    def default_defect_days_major():
        return 14

    @staticmethod
    def default_defect_days_minor():
        return 90

    @classmethod
    def validate_fields(cls, types, field_names):
        super().validate_fields(types, field_names)
        if 'line_filter' in field_names:
            for type_ in types:
                try:
                    assert isinstance(_decode(type_.line_filter), list)
                except Exception:
                    raise ValidationError(gettext(
                            'real_estate.msg_inspection_line_filter',
                            type=type_.rec_name))


#**********************************************************************
class InspectionPlan(DeactivableMixin, ModelSQL, ModelView):
    "Inspection Plan"
    __name__ = 'real_estate.inspection.plan'

    company = fields.Many2One('company.company', "Company", required=True)
    type = fields.Many2One('real_estate.inspection.type', "Inspection Type",
        required=True, ondelete='RESTRICT')
    scope = fields.Function(fields.Selection([
                (None, ''),
                ('property', "Property"),
                ('building', "Building"),
                ], "Scope"), 'on_change_with_scope')
    property = fields.Many2One('real_estate.base_object', "Property",
        ondelete='CASCADE',
        domain=[
            ('type', '=', 'property'),
            ('company', '=', Eval('company', -1)),
            ],
        states={
            'required': ~Eval('building'),
            'readonly': Bool(Eval('building')),
            },
        help="Taken over from the building.")
    building = fields.Many2One('real_estate.base_object', "Building",
        ondelete='CASCADE',
        domain=[
            ('type', '=', 'building'),
            If(Eval('property'),
                ('parent', 'child_of', [Eval('property', -1)]), ()),
            ],
        states={
            'invisible': Eval('scope') != 'building',
            'required': Eval('scope') == 'building',
            })
    interval = fields.Integer("Interval", required=True,
        domain=[('interval', '>=', 1)])
    interval_unit = fields.Selection(INTERVAL_UNITS, "Interval Unit",
        required=True, sort=False)
    interval_basis = fields.Selection(INTERVAL_BASES, "Interval Basis",
        required=True, sort=False)
    preferred_month = fields.Selection(MONTHS, "Preferred Month",
        sort=False)
    lead_time_days = fields.Integer("Lead Time (Days)",
        domain=[('lead_time_days', '>=', 0)])
    responsible_user = fields.Many2One('res.user', "Responsible User",
        help="Overrides the responsibility by the party role.")
    contractor = fields.Many2One('party.party', "Contractor")
    owner_maintains = fields.Boolean("Maintained by Owner",
        help="The owner (resp. the administration) has taken over the "
             "maintenance (e.g. smoke detectors).")
    last_done_date = fields.Date("Last Done", readonly=True)
    next_due_date = fields.Date("Next Due Date", required=True)
    overdue = fields.Function(fields.Boolean("Overdue"),
        'get_overdue', searcher='search_overdue')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._order = [('next_due_date', 'ASC'), ('id', 'ASC')]

    @staticmethod
    def default_company():
        return Transaction().context.get('company')

    @fields.depends('type')
    def on_change_with_scope(self, name=None):
        return self.type.scope if self.type else None

    @staticmethod
    def _building_property(building):
        "Property of a building (stored field, else the parent chain)"
        if building.property:
            return building.property
        node = building
        while node and node.type != 'property':
            node = node.parent
        return node

    @fields.depends('building', 'property', '_parent_property.id',
        '_parent_building.id')
    def on_change_building(self):
        "The property of the plan is the one of the building"
        if self.building:
            prop = self._building_property(self.building)
            if prop:
                self.property = prop

    @classmethod
    def _property_of(cls, values):
        "Property of the building in the values (create/write)"
        BaseObject = Pool().get('real_estate.base_object')
        if values.get('building'):
            prop = cls._building_property(BaseObject(values['building']))
            if prop:
                values = values.copy()
                values['property'] = prop.id
        return values

    @classmethod
    def create(cls, vlist):
        return super().create([cls._property_of(v) for v in vlist])

    @classmethod
    def write(cls, *args):
        actions = iter(args)
        args = []
        for plans, values in zip(actions, actions):
            args.extend((plans, cls._property_of(values)))
        super().write(*args)

    @fields.depends('type', 'interval', 'interval_unit', 'interval_basis',
        'preferred_month', 'lead_time_days', 'next_due_date',
        methods=['_compute_first_due'])
    def on_change_type(self):
        type_ = self.type
        if not type_:
            return
        self.interval = type_.interval
        self.interval_unit = type_.interval_unit
        self.interval_basis = type_.interval_basis
        self.preferred_month = type_.preferred_month
        self.lead_time_days = type_.lead_time_days
        if not self.next_due_date:
            self.next_due_date = self._compute_first_due()

    @fields.depends('interval', 'interval_unit', 'preferred_month')
    def _compute_first_due(self):
        "First due date: today plus the interval (spec 5)"
        today = Pool().get('ir.date').today()
        if not self.interval or not self.interval_unit:
            return None
        return apply_preferred_month(
            add_interval(today, self.interval, self.interval_unit),
            self.preferred_month, today)

    @fields.depends('last_done_date', 'next_due_date', 'interval',
        'interval_unit', 'interval_basis', 'preferred_month')
    def _recompute_due(self):
        "After a change of the interval: from the last execution"
        if self.last_done_date and self.interval and self.interval_unit:
            self.next_due_date = next_due_date(None, self.last_done_date,
                self.interval, self.interval_unit, 'done',
                self.preferred_month) or self.next_due_date

    @fields.depends(methods=['_recompute_due'])
    def on_change_interval(self):
        self._recompute_due()

    @fields.depends(methods=['_recompute_due'])
    def on_change_interval_unit(self):
        self._recompute_due()

    @fields.depends(methods=['_recompute_due'])
    def on_change_preferred_month(self):
        self._recompute_due()

    def get_rec_name(self, name):
        obj = self.building or self.property
        return f'{self.type.rec_name}: {obj.rec_name if obj else ""}'

    @classmethod
    def search_rec_name(cls, name, clause):
        _, operator, value = clause
        bool_op = 'AND' if operator.startswith('!') else 'OR'
        return [bool_op,
            ('type.rec_name', operator, value),
            ('property.rec_name', operator, value),
            ('building.rec_name', operator, value),
            ]

    def _overdue_date(self):
        tolerance = self.type.tolerance_days or 0 if self.type else 0
        return self.next_due_date + datetime.timedelta(days=tolerance)

    def get_overdue(self, name):
        today = Pool().get('ir.date').today()
        return bool(self.active and self.next_due_date
            and self._overdue_date() < today)

    @classmethod
    def search_overdue(cls, name, clause):
        _, operator, value = clause
        plans = cls.search([])
        ids = [p.id for p in plans if p.get_overdue(name)]
        positive = (operator == '=') == bool(value)
        return [('id', 'in' if positive else 'not in', ids)]

    def compute_next_due(self, done_date, due_date=None):
        "Next due date after an execution (spec 5)"
        return next_due_date(due_date or self.next_due_date, done_date,
            self.interval, self.interval_unit, self.interval_basis,
            self.preferred_month)

    @classmethod
    def validate_fields(cls, plans, field_names):
        super().validate_fields(plans, field_names)
        if field_names & {'type', 'property', 'building', 'active'}:
            for plan in plans:
                if not plan.property:
                    raise ValidationError(gettext(
                            'real_estate.msg_inspection_plan_property',
                            plan=plan.rec_name))
                if plan.type.scope == 'building' and not plan.building:
                    raise ValidationError(gettext(
                            'real_estate.msg_inspection_plan_building',
                            plan=plan.rec_name))
                domain = [
                    ('id', '!=', plan.id),
                    ('type', '=', plan.type.id),
                    ('property', '=', plan.property.id),
                    ('building', '=',
                        plan.building.id if plan.building else None),
                    ]
                if plan.active and cls.search(domain, limit=1):
                    raise ValidationError(gettext(
                            'real_estate.msg_inspection_plan_unique',
                            plan=plan.rec_name))


#**********************************************************************
# Phase P2: inspection (protocol), lines, results
STATES = [
    ('draft', "Draft"),
    ('scheduled', "Scheduled"),
    ('in_progress', "In Progress"),
    ('done', "Done"),
    ('approved', "Approved"),
    ('cancelled', "Cancelled"),
    ]
OPEN_STATES = ['draft', 'scheduled', 'in_progress', 'done']
ACCESS_STATES = [
    ('accessed', "Accessed"),
    ('no_access', "No Access"),
    ('refused', "Refused"),
    ('vacant', "Vacant"),
    ('not_required', "Not Required"),
    ]
LINE_RESULTS = [
    (None, ''),
    ('ok', "OK"),
    ('defect', "Defect"),
    ('not_inspected', "Not Inspected"),
    ]
OVERALL_RESULTS = [
    (None, ''),
    ('ok', "OK"),
    ('ok_with_defects', "OK with Defects"),
    ('not_ok', "Not OK"),
    ]
ANSWER_FIELDS = {
    'ok_nok_na': 'value_ok',
    'yes_no': 'value_yes_no',
    'number': 'value_number',
    'text': 'value_text',
    'date': 'value_date',
    'selection': 'value_choice',
    }


class InspectionNoticeWarning(UserWarning):
    pass


class InspectionAccessWarning(UserWarning):
    pass


def _attachments(records):
    "Ids of the records with at least one attachment"
    Attachment = Pool().get('ir.attachment')
    if not records:
        return set()
    return {int(a.resource.id) for a in Attachment.search([
                ('resource', 'in', [str(r) for r in records]),
                ])}


class Inspection(Workflow, ModelSQL, ModelView):
    "Inspection"
    __name__ = 'real_estate.inspection'
    _rec_name = 'number'

    _locked = Eval('state').in_(['approved', 'cancelled'])
    _states = {'readonly': _locked}

    company = fields.Many2One('company.company', "Company", required=True,
        readonly=True)
    number = fields.Char("Number", readonly=True)
    plan = fields.Many2One('real_estate.inspection.plan', "Inspection Plan",
        required=True, readonly=True, ondelete='RESTRICT')
    type = fields.Many2One('real_estate.inspection.type', "Inspection Type",
        required=True, readonly=True, ondelete='RESTRICT')
    property = fields.Many2One('real_estate.base_object', "Property",
        required=True, readonly=True, ondelete='RESTRICT')
    building = fields.Many2One('real_estate.base_object', "Building",
        readonly=True, ondelete='RESTRICT')
    due_date = fields.Date("Due Date", required=True, readonly=True)
    planned_date = fields.Date("Planned Date",
        states={
            'readonly': ~Eval('state').in_(['draft', 'scheduled']),
            'required': Eval('state') != 'draft',
            },
        help="Anchor of the process steps (e.g. notice 14 days before).")
    planned_date_to = fields.Date("Planned to", states=_states,
        domain=[If(Bool(Eval('planned_date_to')) & Bool(Eval('planned_date')),
                ('planned_date_to', '>=', Eval('planned_date')), ())],
        help="End of the time window of the notice.")
    done_date = fields.Date("Done Date",
        states={'readonly': Eval('state') != 'in_progress'})
    state = fields.Selection(STATES, "State", readonly=True, required=True,
        sort=False)
    inspector = fields.Many2One('party.party', "Inspector", states=_states)
    participants = fields.Many2Many('real_estate.inspection-party.party',
        'inspection', 'party', "Participants", states=_states)
    contractor = fields.Many2One('party.party', "Contractor", states=_states)
    external_report_number = fields.Char("External Report Number",
        states=_states)
    summary = fields.Text("Summary", states=_states)
    overall_result = fields.Selection(OVERALL_RESULTS, "Overall Result",
        sort=False, states=_states)
    header_results = fields.One2Many('real_estate.inspection.result',
        'inspection', "Header Results", filter=[('line', '=', None)],
        states=_states)
    lines = fields.One2Many('real_estate.inspection.line', 'inspection',
        "Lines", states=_states)
    process = fields.Function(fields.Many2One('real_estate.process',
            "Process"), 'get_process')
    process_state = fields.Function(fields.Selection([
                (None, ''),
                ('running', "Running"),
                ('done', "Done"),
                ('cancelled', "Cancelled"),
                ], "Process State"), 'get_process_info')
    process_progress = fields.Function(fields.Char("Progress"),
        'get_process_info')
    process_tasks = fields.Function(fields.One2Many('real_estate.task',
            None, "Workflow", readonly=True,
            help="Steps of the process of the inspection with state, due "
                 "date and responsible."),
        'get_process_tasks', setter='set_process_tasks')
    overdue = fields.Function(fields.Boolean("Overdue"),
        'get_overdue', searcher='search_overdue')
    approved_by = fields.Many2One('res.user', "Approved by", readonly=True)
    approved_date = fields.Date("Approved on", readonly=True)
    report = fields.Many2One('ir.attachment', "Report (Document)",
        readonly=True, ondelete='SET NULL')
    previous = fields.Many2One('real_estate.inspection', "Corrects",
        states=_states, ondelete='SET NULL',
        domain=[('plan', '=', Eval('plan', -1)), ('state', '=', 'approved')],
        help="Approved inspection corrected by this one.")
    cancel_reason = fields.Text("Cancel Reason",
        states={'readonly': _locked})
    attempt = fields.Integer("Attempt", readonly=True)
    time_slots = fields.Text("Time Slots", states=_states,
        help="Time slots and contact for the tenant notice.")
    notice_date = fields.Date("Notice Date", readonly=True,
        help="Date the tenant notice was created (proof).")
    notice = fields.Many2One('ir.attachment', "Notice (Document)",
        readonly=True, ondelete='SET NULL')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._order = [('due_date', 'DESC'), ('id', 'DESC')]
        cls._transitions |= {
            ('draft', 'scheduled'),
            ('scheduled', 'draft'),
            ('scheduled', 'in_progress'),
            ('in_progress', 'done'),
            ('done', 'in_progress'),
            ('done', 'approved'),
            ('draft', 'cancelled'),
            ('scheduled', 'cancelled'),
            ('in_progress', 'cancelled'),
            # undo (every step can be taken back)
            ('in_progress', 'scheduled'),
            ('approved', 'done'),
            ('cancelled', 'draft'),
            }
        cls._buttons.update({
            'schedule': {
                'invisible': Eval('state') != 'draft',
                'depends': ['state'],
                },
            'unschedule': {
                'invisible': Eval('state') != 'scheduled',
                'depends': ['state'],
                },
            'start': {
                'invisible': Eval('state') != 'scheduled',
                'depends': ['state'],
                },
            'done': {
                'invisible': Eval('state') != 'in_progress',
                'depends': ['state'],
                },
            'reopen': {
                'invisible': Eval('state') != 'done',
                'depends': ['state'],
                },
            'approve': {
                'invisible': Eval('state') != 'done',
                'depends': ['state'],
                },
            'cancel': {
                'invisible': ~Eval('state').in_(
                    ['draft', 'scheduled', 'in_progress']),
                'depends': ['state'],
                },
            'next_attempt': {
                'invisible': Eval('state') != 'in_progress',
                'depends': ['state'],
                },
            'rebuild_lines': {
                'invisible': Eval('state') != 'draft',
                'depends': ['state'],
                },
            'back_to_scheduled': {
                'invisible': Eval('state') != 'in_progress',
                'depends': ['state'],
                },
            'unapprove': {
                'invisible': Eval('state') != 'approved',
                'depends': ['state'],
                },
            'reactivate': {
                'invisible': Eval('state') != 'cancelled',
                'depends': ['state'],
                },
            'all_ok': {
                'invisible': ~Eval('state').in_(['scheduled', 'in_progress']),
                'depends': ['state'],
                },
            })

    @classmethod
    def view_attributes(cls):
        # header and lines only shown when the type has them
        return super().view_attributes() + [
            ('//page[@id="page_header"]', 'states', {
                    'invisible': ~Eval('header_results', []),
                    }, ['header_results']),
            ('//page[@id="page_workflow"]', 'states', {
                    'invisible': ~Eval('process'),
                    }, ['process']),
            ('//page[@name="lines"]', 'states', {
                    'invisible': ~Eval('lines', []),
                    }, ['lines']),
            ]

    @staticmethod
    def default_state():
        return 'draft'

    @staticmethod
    def default_attempt():
        return 1

    @staticmethod
    def default_company():
        return Transaction().context.get('company')

    def get_rec_name(self, name):
        obj = self.building or self.property
        return ' '.join(filter(None, [self.number,
                    self.type.rec_name if self.type else None,
                    obj.rec_name if obj else None]))

    @classmethod
    def search_rec_name(cls, name, clause):
        _, operator, value = clause
        bool_op = 'AND' if operator.startswith('!') else 'OR'
        return [bool_op,
            ('number', operator, value),
            ('type.rec_name', operator, value),
            ('property.rec_name', operator, value),
            ('building.rec_name', operator, value),
            ]

    @classmethod
    def get_process(cls, inspections, name):
        """The running process of the inspection, else the last started
        one"""
        Process = Pool().get('real_estate.process')
        result = {i.id: None for i in inspections}
        running = {}
        for process in Process.search([
                    ('resource', 'in', [str(i) for i in inspections]),
                    ], order=[('start_date', 'ASC'), ('id', 'ASC')]):
            key = process.resource.id
            if process.state == 'running':
                running[key] = process.id
            result[key] = process.id
        result.update(running)
        return result

    def get_process_info(self, name):
        process = self.process
        if not process:
            return None
        return process.state if name == 'process_state' \
            else process.progress

    def get_process_tasks(self, name):
        return [t.id for t in self.process.tasks] if self.process else []

    @classmethod
    def set_process_tasks(cls, inspections, name, value):
        pass

    def get_overdue(self, name):
        today = Pool().get('ir.date').today()
        tolerance = self.type.tolerance_days or 0
        return bool(self.state in ['draft', 'scheduled', 'in_progress']
            and self.due_date
            + datetime.timedelta(days=tolerance) < today)

    @classmethod
    def search_overdue(cls, name, clause):
        _, operator, value = clause
        ids = [i.id for i in cls.search([
                    ('state', 'in', ['draft', 'scheduled', 'in_progress']),
                    ]) if i.get_overdue(name)]
        positive = (operator == '=') == bool(value)
        return [('id', 'in' if positive else 'not in', ids)]

    # ------------------------------------------------------------------
    # Creation from the plan (spec 4.1, draft)

    @classmethod
    def _line_objects(cls, plan, date):
        "Objects of the lines: rental units or equipment below the object"
        BaseObject = Pool().get('real_estate.base_object')
        type_ = plan.type
        if type_.line_granularity == 'none':
            return []
        root = plan.building or plan.property
        domain = [
            ('parent', 'child_of', [root.id]),
            ('id', '!=', root.id),
            ('state', '!=', 'deactivated'),
            ('type', '=',
                'object' if type_.line_granularity == 'unit'
                else 'equipment'),
            ]
        if type_.line_granularity == 'equipment' and type_.equipment_kind:
            domain.append(('equipment_kind', '=', type_.equipment_kind.id))
        domain += _decode(type_.line_filter)
        objects = BaseObject.search(domain)
        if type_.line_granularity == 'unit' and type_.equipment_kind:
            with_kind = {e.parent.id for e in BaseObject.search([
                        ('type', '=', 'equipment'),
                        ('equipment_kind', '=', type_.equipment_kind.id),
                        ('parent', 'in', [o.id for o in objects]),
                        ]) if e.parent}
            objects = [o for o in objects if o.id in with_kind]
        return objects

    @classmethod
    def _quantity(cls, obj, kind, date):
        """Expected quantity: measurement 'Number of items' of the
        equipment (of the kind below a rental unit) on the date"""
        pool = Pool()
        BaseObject = pool.get('real_estate.base_object')
        Measurement = pool.get('real_estate.measurement')
        ModelData = pool.get('ir.model.data')
        MeasurementType = pool.get('real_estate.measurement.type')
        m_type = MeasurementType(ModelData.get_id('real_estate',
                'measurement_re_number_of_items_type'))
        if obj.type == 'equipment':
            equipment = [obj]
        elif kind:
            equipment = BaseObject.search([
                    ('type', '=', 'equipment'),
                    ('equipment_kind', '=', kind.id),
                    ('parent', '=', obj.id),
                    ])
        else:
            return None
        values = [Measurement.get_total_value(e.id, m_type, date)
            for e in equipment]
        values = [v for v in values if v is not None]
        return float(sum(values)) if values else None

    @staticmethod
    def _result_values(checklist):
        "Results of a checklist as snapshot (spec 8.1)"
        if not checklist:
            return []
        return [{
                'item': item.id,
                'sequence': item.sequence,
                'section': item.section,
                'question': item.question,
                'answer_type': item.answer_type,
                'selection_values': item.selection_values,
                'unit': item.unit.id if item.unit else None,
                'min_value': item.min_value,
                'max_value': item.max_value,
                'mandatory': item.mandatory,
                'photo_on_nok': item.photo_on_nok,
                'create_defect_on_nok': item.create_defect_on_nok,
                'default_severity': item.default_severity,
                } for item in checklist.items]

    @classmethod
    def _line_values(cls, plan, date):
        """Values of the lines of an inspection of the plan: objects by
        scope, granularity, equipment kind and filter; vacant units on the
        date prefilled; results from the line checklist"""
        BaseObject = Pool().get('real_estate.base_object')
        type_ = plan.type
        lines = []
        with Transaction().set_context(occupancy_date=date):
            objects = BaseObject.browse(
                [o.id for o in cls._line_objects(plan, date)])
            for obj in objects:
                vacant = (obj.type == 'object'
                    and obj.occupancy_state == 'vacant')
                lines.append({
                        'base_object': obj.id,
                        'access_status': 'vacant' if vacant else 'accessed',
                        'qty_expected': cls._quantity(obj,
                            type_.equipment_kind, date),
                        'results': [('create',
                                cls._result_values(type_.line_checklist))],
                        })
        return lines

    @classmethod
    @ModelView.button
    def rebuild_lines(cls, inspections):
        """Rebuild the lines of draft inspections from the current
        equipment, equipment kind and line filter of the type"""
        pool = Pool()
        Line = pool.get('real_estate.inspection.line')
        Result = pool.get('real_estate.inspection.result')
        for inspection in inspections:
            if inspection.state != 'draft':
                raise ValidationError(gettext(
                        'real_estate.msg_inspection_rebuild_draft',
                        inspection=inspection.rec_name))
            if inspection.lines:
                Line.delete(list(inspection.lines))
            values = cls._line_values(inspection.plan, inspection.due_date)
            if values:
                cls.write([inspection], {'lines': [('create', values)]})
            inspection = cls(inspection.id)
            results = [r for l in inspection.lines for r in l.results]
            if results:
                Result.write(results, {'inspection': inspection.id})

    @classmethod
    def create_from_plans(cls, plans):
        """Create a draft inspection for each plan without an open one,
        with lines and results from the checklists (spec 4.1)"""
        to_create = []
        for plan in plans:
            if cls.search([('plan', '=', plan.id),
                        ('state', 'in', OPEN_STATES)], limit=1):
                continue
            type_ = plan.type
            date = plan.next_due_date
            lines = cls._line_values(plan, date)
            to_create.append({
                    'company': plan.company.id,
                    'plan': plan.id,
                    'type': type_.id,
                    'property': plan.property.id,
                    'building': plan.building.id if plan.building else None,
                    'due_date': date,
                    'contractor': (plan.contractor.id
                        if plan.contractor else None),
                    'header_results': [('create',
                            cls._result_values(type_.header_checklist))],
                    'lines': [('create', lines)],
                    })
        return cls.create(to_create)

    @classmethod
    def create(cls, vlist):
        pool = Pool()
        ModelData = pool.get('ir.model.data')
        Sequence = pool.get('ir.sequence')
        vlist = [v.copy() for v in vlist]
        with without_check_access():
            sequence = Sequence(ModelData.get_id('real_estate',
                    'sequence_inspection'))
            for values in vlist:
                if not values.get('number'):
                    values['number'] = sequence.get()
        inspections = super().create(vlist)
        # the results of the lines belong to the inspection as well
        Result = pool.get('real_estate.inspection.result')
        for inspection in inspections:
            line_results = [r for l in inspection.lines for r in l.results]
            if line_results:
                Result.write(line_results, {'inspection': inspection.id})
        return inspections

    # ------------------------------------------------------------------
    # Workflow (spec 4.1)

    @classmethod
    @ModelView.button
    def schedule(cls, inspections):
        """Schedule; answers 'not OK' entered before (e.g. while still
        editable in a draft) create their defects now"""
        Result = Pool().get('real_estate.inspection.result')
        cls._schedule(inspections)
        inspections = cls.browse([i.id for i in inspections])
        results = [r for i in inspections for r in i.header_results] + [
            r for i in inspections for l in i.lines for r in l.results]
        if results:
            Result._sync_defects(results)
        cls._check_processes(inspections)

    @classmethod
    @Workflow.transition('scheduled')
    def _schedule(cls, inspections):
        """Set the planned date and start the process of the type (anchor =
        planned date)"""
        pool = Pool()
        Date = pool.get('ir.date')
        Warning = pool.get('res.user.warning')
        Process = pool.get('real_estate.process')
        today = Date.today()
        for inspection in inspections:
            if not inspection.planned_date:
                raise ValidationError(gettext(
                        'real_estate.msg_inspection_planned_date',
                        inspection=inspection.rec_name))
            notice = inspection.type.notice_days or 0
            if notice and (inspection.planned_date - today).days < notice:
                key = Warning.format('inspection_notice', [inspection])
                if Warning.check(key):
                    raise InspectionNoticeWarning(key, gettext(
                            'real_estate.msg_inspection_notice_days',
                            inspection=inspection.rec_name, days=notice))
        for inspection in inspections:
            template = inspection.type.process_template
            if template:
                Process.start(template, inspection, today)

    @classmethod
    @ModelView.button
    @Workflow.transition('draft')
    def unschedule(cls, inspections):
        cls._cancel_processes(inspections)

    @classmethod
    @ModelView.button
    @Workflow.transition('in_progress')
    def start(cls, inspections):
        pass

    @classmethod
    @ModelView.button
    def done(cls, inspections):
        """Validate (spec 4.3), set done, update the plan (spec 5); without
        required approval approved at once"""
        cls._check_done(inspections)
        cls._set_done(inspections)
        inspections = cls.browse([i.id for i in inspections])
        cls._update_plans(inspections)
        auto = [i for i in inspections if not i.type.requires_approval]
        if auto:
            cls._set_approved(auto)
        cls._check_processes(inspections)

    @classmethod
    @Workflow.transition('done')
    def _set_done(cls, inspections):
        Date = Pool().get('ir.date')
        today = Date.today()
        for inspection in inspections:
            values = {}
            if not inspection.done_date:
                values['done_date'] = today
            if not inspection.overall_result:
                values['overall_result'] = inspection._compute_overall()
            if values:
                cls.write([inspection], values)

    def _compute_overall(self):
        defects = (any(r.is_nok for r in self.header_results)
            or any(l.result == 'defect' for l in self.lines))
        return 'ok_with_defects' if defects else 'ok'

    @classmethod
    def _update_plans(cls, inspections):
        Plan = Pool().get('real_estate.inspection.plan')
        for inspection in inspections:
            plan = inspection.plan
            values = {'last_done_date': inspection.done_date}
            next_due = plan.compute_next_due(inspection.done_date,
                due_date=inspection.due_date)
            if next_due:
                values['next_due_date'] = next_due
            Plan.write([plan], values)

    @classmethod
    def _check_done(cls, inspections):
        "Validation before done (spec 4.3)"
        pool = Pool()
        Warning = pool.get('res.user.warning')
        for inspection in inspections:
            type_ = inspection.type
            accessed = [l for l in inspection.lines
                if l.access_status == 'accessed']
            results = list(inspection.header_results) + [
                r for l in accessed for r in l.results]
            missing = [r for r in results if r.mandatory and not r.answered]
            if missing:
                raise ValidationError(gettext(
                        'real_estate.msg_inspection_mandatory',
                        inspection=inspection.rec_name,
                        items=', '.join(r.rec_name for r in missing[:5])))
            photos = [r for r in results if r.photo_on_nok and r.is_nok]
            with_photo = _attachments(photos)
            without = [r for r in photos if r.id not in with_photo]
            if without:
                raise ValidationError(gettext(
                        'real_estate.msg_inspection_photo',
                        inspection=inspection.rec_name,
                        items=', '.join(r.rec_name for r in without[:5])))
            not_inspected = [l for l in inspection.lines
                if l.result == 'not_inspected']
            no_reason = [l for l in not_inspected if not l.remarks]
            if no_reason:
                raise ValidationError(gettext(
                        'real_estate.msg_inspection_not_inspected_reason',
                        inspection=inspection.rec_name,
                        lines=', '.join(l.rec_name for l in no_reason[:5])))
            if type_.contractor_required and (not inspection.contractor
                    or not (inspection.external_report_number
                        or _attachments([inspection]))):
                raise ValidationError(gettext(
                        'real_estate.msg_inspection_contractor',
                        inspection=inspection.rec_name))
            if type_.requires_unit_access:
                early = [l for l in not_inspected
                    if (l.attempt or 1) < (type_.access_attempts or 1)]
                if early:
                    key = Warning.format('inspection_access', [inspection])
                    if Warning.check(key):
                        raise InspectionAccessWarning(key, gettext(
                                'real_estate.msg_inspection_access_attempts',
                                inspection=inspection.rec_name,
                                count=len(early)))

    @classmethod
    @ModelView.button
    @Workflow.transition('in_progress')
    def reopen(cls, inspections):
        """Reopen a done inspection: the plan is set back (next due date of
        this inspection, last execution of the previous one) and the
        process step 'done' is reopened"""
        Plan = Pool().get('real_estate.inspection.plan')
        for inspection in inspections:
            plan = inspection.plan
            if inspection.done_date and plan.last_done_date == \
                    inspection.done_date:
                previous = cls.search([
                        ('plan', '=', plan.id),
                        ('id', '!=', inspection.id),
                        ('state', 'in', ['done', 'approved']),
                        ], order=[('done_date', 'DESC')], limit=1)
                Plan.write([plan], {
                        'next_due_date': inspection.due_date,
                        'last_done_date': (previous[0].done_date
                            if previous else None),
                        })
        cls._reopen_process_steps(inspections, ['inspection_done'])

    @classmethod
    @ModelView.button
    @Workflow.transition('scheduled')
    def back_to_scheduled(cls, inspections):
        "Back to scheduled - the entries are kept"
        pass

    @classmethod
    @ModelView.button
    def unapprove(cls, inspections):
        """Take back the approval (approval group of the type or real
        estate administration): the archived report stays as attachment
        marked withdrawn"""
        pool = Pool()
        User = pool.get('res.user')
        ModelData = pool.get('ir.model.data')
        Attachment = pool.get('ir.attachment')
        groups = set(User.get_groups())
        admin = ModelData.get_id('real_estate', 'group_real_estate_admin')
        for inspection in inspections:
            group = inspection.type.approval_group
            if (Transaction().user and admin not in groups
                    and not (group and group.id in groups)):
                raise AccessError(gettext(
                        'real_estate.msg_inspection_unapprove_group',
                        inspection=inspection.rec_name))
        suffix = gettext('real_estate.msg_inspection_report_withdrawn')
        reports = [i.report for i in inspections if i.report]
        for report in reports:
            Attachment.write([report], {'name': f'{report.name} {suffix}'})
        cls._set_unapproved(inspections)
        cls._reopen_process_steps(inspections, ['inspection_approved'])

    @classmethod
    @Workflow.transition('done')
    def _set_unapproved(cls, inspections):
        cls.write(inspections, {
                'approved_by': None,
                'approved_date': None,
                'report': None,
                })

    @classmethod
    @ModelView.button
    @Workflow.transition('draft')
    def reactivate(cls, inspections):
        """Reactivate a cancelled inspection as draft (lines and entries
        are kept; scheduling starts a new process)"""
        pass

    @classmethod
    def _reopen_process_steps(cls, inspections, methods):
        """Reopen the done tasks of the process steps completed by the
        given conditions (and with them a done process)"""
        pool = Pool()
        Process = pool.get('real_estate.process')
        Task = pool.get('real_estate.task')
        processes = cls._processes(inspections, states=('running', 'done'))
        tasks = [t for p in processes for t in p.tasks
            if t.state == 'done' and t.template_step
            and t.template_step.completion == 'condition'
            and t.template_step.done_method in methods]
        if tasks:
            Task.write(tasks, {'state': 'open', 'done_date': None,
                    'done_by': None, 'result': None})
        done = [p for p in processes if p.state == 'done']
        if done and tasks:
            Process.reopen(Process.browse([p.id for p in done]))

    @classmethod
    @ModelView.button
    def all_ok(cls, inspections):
        """Set the open check items of the header and of the lines with
        access to OK"""
        pool = Pool()
        Line = pool.get('real_estate.inspection.line')
        Result = pool.get('real_estate.inspection.result')
        inspections = [i for i in inspections
            if i.state in ['scheduled', 'in_progress']]
        Result.set_ok([r for i in inspections for r in i.header_results])
        Line.all_ok([l for i in inspections for l in i.lines])

    @classmethod
    @ModelView.button
    def next_attempt(cls, inspections):
        """Next access attempt (spec 4.2): the lines without access get
        the next attempt"""
        Line = Pool().get('real_estate.inspection.line')
        for inspection in inspections:
            lines = [l for l in inspection.lines
                if l.access_status in ['no_access', 'refused']]
            if not lines:
                raise ValidationError(gettext(
                        'real_estate.msg_inspection_no_lines_without_access',
                        inspection=inspection.rec_name))
            attempt = (inspection.attempt or 1) + 1
            Line.write(lines, {'attempt': attempt, 'visit_date': None})
            cls.write([inspection], {'attempt': attempt})

    @classmethod
    @ModelView.button
    def approve(cls, inspections):
        "Approve (approval group of the type): protocol frozen (spec 4.1)"
        User = Pool().get('res.user')
        groups = set(User.get_groups())
        for inspection in inspections:
            group = inspection.type.approval_group
            if group and group.id not in groups:
                raise AccessError(gettext(
                        'real_estate.msg_inspection_approval_group',
                        inspection=inspection.rec_name,
                        group=group.rec_name))
        cls._set_approved(inspections)
        cls._check_processes(inspections)

    @classmethod
    @Workflow.transition('approved')
    def _set_approved(cls, inspections):
        pool = Pool()
        Date = pool.get('ir.date')
        Attachment = pool.get('ir.attachment')
        Report = pool.get('real_estate.inspection.report', type='report')
        cls.write(inspections, {
                'approved_by': Transaction().user,
                'approved_date': Date.today(),
                })
        for inspection in inspections:
            ext, content, _, name = Report.execute([inspection.id], {
                    'model': cls.__name__,
                    'original': True,
                    })
            attachment, = Attachment.create([{
                        'name': f'{name}.{ext}',
                        'resource': str(inspection),
                        'data': content,
                        }])
            # written below the check of locked records (state not yet
            # approved here)
            cls.write([inspection], {'report': attachment.id})

    @classmethod
    @ModelView.button
    @Workflow.transition('cancelled')
    def cancel(cls, inspections):
        for inspection in inspections:
            if not inspection.cancel_reason:
                raise ValidationError(gettext(
                        'real_estate.msg_inspection_cancel_reason',
                        inspection=inspection.rec_name))
        cls._cancel_processes(inspections)

    @classmethod
    def _processes(cls, inspections, states=('running',)):
        Process = Pool().get('real_estate.process')
        return Process.search([
                ('resource', 'in', [str(i) for i in inspections]),
                ('state', 'in', list(states)),
                ])

    @classmethod
    def _cancel_processes(cls, inspections):
        Process = Pool().get('real_estate.process')
        processes = cls._processes(inspections)
        if processes:
            # the inspection leads: only it may cancel its process
            with Transaction().set_context(_inspection_process_cancel=True):
                Process.cancel(processes)

    @classmethod
    def _check_processes(cls, inspections):
        "Complete the process steps waiting for the inspection at once"
        Process = Pool().get('real_estate.process')
        processes = cls._processes(inspections)
        if processes:
            Process.check(processes)

    # ------------------------------------------------------------------
    # Protection (spec 8.1)

    @classmethod
    def check_modification(cls, mode, inspections, values=None,
            external=False):
        super().check_modification(mode, inspections, values=values,
            external=external)
        if mode == 'delete':
            for inspection in inspections:
                if inspection.state not in ['draft', 'cancelled']:
                    raise AccessError(gettext(
                            'real_estate.msg_inspection_delete',
                            inspection=inspection.rec_name))
        elif mode == 'write' and external:
            for inspection in inspections:
                if inspection.state == 'approved':
                    raise AccessError(gettext(
                            'real_estate.msg_inspection_locked',
                            inspection=inspection.rec_name))

    @classmethod
    def copy(cls, inspections, default=None):
        default = default.copy() if default is not None else {}
        for name in ['number', 'done_date', 'approved_by', 'approved_date',
                'report', 'overall_result']:
            default.setdefault(name, None)
        default.setdefault('state', 'draft')
        return super().copy(inspections, default=default)


class InspectionParty(ModelSQL):
    "Inspection - Participant"
    __name__ = 'real_estate.inspection-party.party'

    inspection = fields.Many2One('real_estate.inspection', "Inspection",
        required=True, ondelete='CASCADE')
    party = fields.Many2One('party.party', "Party", required=True,
        ondelete='CASCADE')


def _check_inspection_processes(inspections):
    """Re-evaluate the processes of running inspections (conditional
    steps, done conditions)"""
    Inspection = Pool().get('real_estate.inspection')
    inspections = [i for i in inspections
        if i and i.state in ['scheduled', 'in_progress']]
    if inspections:
        Inspection._check_processes(Inspection.browse(
                [i.id for i in inspections]))


# fields of lines and results entered during the inspection
ENTRY_FIELDS = {'access_status', 'visit_date', 'attempt', 'qty_checked',
    'qty_ok', 'qty_replaced', 'remarks', 'value_ok', 'value_yes_no',
    'value_number', 'value_text', 'value_date', 'value_choice', 'comment'}


def _check_draft_entry(records, inspection_of, values):
    """Results are entered once the inspection is scheduled and until it
    is done (reopen to change)"""
    if not values or not (set(values) & ENTRY_FIELDS):
        return
    for record in records:
        inspection = inspection_of(record)
        if inspection and inspection.state == 'draft':
            raise AccessError(gettext(
                    'real_estate.msg_inspection_draft_entry',
                    inspection=inspection.rec_name))
        if inspection and inspection.state == 'done':
            raise AccessError(gettext(
                    'real_estate.msg_inspection_done_entry',
                    inspection=inspection.rec_name))


def _check_locked(records, inspection_of):
    "Lines and results of an approved inspection are read-only"
    for record in records:
        inspection = inspection_of(record)
        if inspection and inspection.state == 'approved':
            raise AccessError(gettext('real_estate.msg_inspection_locked',
                    inspection=inspection.rec_name))


class InspectionLine(ModelSQL, ModelView):
    "Inspection Line"
    __name__ = 'real_estate.inspection.line'

    _states = {'readonly': Eval('locked', False)}

    inspection = fields.Many2One('real_estate.inspection', "Inspection",
        required=True, ondelete='CASCADE')
    base_object = fields.Many2One('real_estate.base_object', "Object",
        required=True, ondelete='RESTRICT', states=_states,
        domain=[('type', 'in', ['object', 'equipment'])])
    unit = fields.Function(fields.Many2One('real_estate.base_object',
            "Rental Unit"), 'get_unit')
    tenant = fields.Function(fields.Many2One('party.party', "Tenant"),
        'get_tenant')
    access_status = fields.Selection(ACCESS_STATES, "Access", required=True,
        sort=False, states=_states)
    visit_date = fields.Date("Visit Date", states=_states)
    attempt = fields.Integer("Attempt", states=_states)
    qty_expected = fields.Float("Expected", digits=(16, 0), readonly=True,
        help="Measurement 'Number of items' of the equipment on the due "
             "date.")
    qty_checked = fields.Integer("Checked", states=_states)
    qty_ok = fields.Integer("OK", states=_states)
    qty_replaced = fields.Integer("Replaced", states=_states)
    result = fields.Function(fields.Selection(LINE_RESULTS, "Result"),
        'get_result')
    results = fields.One2Many('real_estate.inspection.result', 'line',
        "Results", states=_states)
    remarks = fields.Text("Remarks", states=_states)
    letter_date = fields.Date("Letter Date", readonly=True,
        help="Date the letter to the tenant (no access) was created.")
    locked = fields.Function(fields.Boolean("Locked"), 'get_locked')
    inspection_state = fields.Function(fields.Selection(STATES,
            "Inspection State"), 'get_inspection_state')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._buttons.update({
            'all_ok': {
                'invisible': (Eval('locked', False)
                    | (Eval('access_status') != 'accessed')),
                'depends': ['locked', 'access_status'],
                },
            })

    @staticmethod
    def default_access_status():
        return 'accessed'

    @classmethod
    @ModelView.button
    def all_ok(cls, lines):
        """Set the open check items of the lines with access to OK and
        fill empty quantities checked/OK with the expected quantity and an
        empty visit date with today"""
        pool = Pool()
        Result = pool.get('real_estate.inspection.result')
        Date = pool.get('ir.date')
        lines = [l for l in lines if l.access_status == 'accessed'
            and l.inspection.state in ['scheduled', 'in_progress']]
        to_write = []
        for line in lines:
            values = {}
            if not line.visit_date:
                values['visit_date'] = Date.today()
            if line.qty_expected is not None:
                if line.qty_checked is None:
                    values['qty_checked'] = int(line.qty_expected)
                if line.qty_ok is None:
                    values['qty_ok'] = int(line.qty_expected)
            if values:
                to_write.extend(([line], values))
        if to_write:
            cls.write(*to_write)
        Result.set_ok([r for l in lines for r in l.results])

    @staticmethod
    def default_attempt():
        return 1

    def get_rec_name(self, name):
        return self.base_object.rec_name if self.base_object else ''

    @classmethod
    def search_rec_name(cls, name, clause):
        return [('base_object.rec_name',) + tuple(clause[1:])]

    def get_unit(self, name):
        obj = self.base_object
        while obj and obj.type != 'object':
            obj = obj.parent
        return obj.id if obj else None

    @classmethod
    def get_tenant(cls, lines, name):
        "Main tenant of the contract of the unit on the inspection date"
        Occupancy = Pool().get('real_estate.base_object.occupancy')
        result = {l.id: None for l in lines}
        for line in lines:
            unit = line.unit
            date = (line.visit_date or line.inspection.planned_date
                or line.inspection.due_date)
            if not unit or not date:
                continue
            for occ in Occupancy.search([
                        ('base_object', '=', unit.id),
                        ('start_date', '<=', date),
                        ['OR', ('end_date', '=', None),
                            ('end_date', '>=', date)],
                        ('contract', '!=', None),
                        ], limit=1):
                partner = occ.contract.contractual_partner
                result[line.id] = partner.id if partner else None
        return result

    def get_result(self, name):
        "Derived result (spec 4.2)"
        if self.access_status in ['vacant', 'not_required']:
            return 'ok'
        if self.access_status in ['no_access', 'refused']:
            return 'not_inspected'
        if any(r.is_nok for r in self.results) or (
                self.qty_checked is not None and self.qty_ok is not None
                and self.qty_ok < self.qty_checked):
            return 'defect'
        if any(r.answered for r in self.results) or self.qty_checked:
            return 'ok'
        return None

    def get_locked(self, name):
        "Entry only while scheduled or in progress"
        return bool(self.inspection and self.inspection.state not in [
                'scheduled', 'in_progress'])

    def get_inspection_state(self, name):
        return self.inspection.state if self.inspection else None

    @classmethod
    def check_modification(cls, mode, lines, values=None, external=False):
        super().check_modification(mode, lines, values=values,
            external=external)
        if mode in ['write', 'delete'] and external:
            _check_locked(lines, lambda l: l.inspection)
        if mode == 'write' and external:
            _check_draft_entry(lines, lambda l: l.inspection, values)

    @classmethod
    def write(cls, *args):
        super().write(*args)
        values = args[1::2]
        if any(('access_status' in v or 'visit_date' in v) for v in values):
            _check_inspection_processes(
                {l.inspection for l in sum(args[::2], [])})


class InspectionResult(sequence_ordered(), ModelSQL, ModelView):
    "Inspection Result"
    __name__ = 'real_estate.inspection.result'

    _value_states = {'readonly': Eval('locked', False)}

    inspection = fields.Many2One('real_estate.inspection', "Inspection",
        ondelete='CASCADE')
    line = fields.Many2One('real_estate.inspection.line', "Line",
        ondelete='CASCADE')
    item = fields.Many2One('real_estate.inspection.checklist.item',
        "Check Item", readonly=True, ondelete='SET NULL')
    section = fields.Char("Section", readonly=True)
    question = fields.Char("Question", required=True, readonly=True)
    answer_type = fields.Selection([
            ('ok_nok_na', "OK / Not OK / N/A"),
            ('yes_no', "Yes / No"),
            ('number', "Number"),
            ('text', "Text"),
            ('date', "Date"),
            ('selection', "Selection"),
            ], "Answer Type", required=True, readonly=True)
    selection_values = fields.Text("Selection Values", readonly=True)
    unit = fields.Many2One('product.uom', "Unit", readonly=True)
    min_value = fields.Float("Minimum", readonly=True)
    max_value = fields.Float("Maximum", readonly=True)
    mandatory = fields.Boolean("Mandatory", readonly=True)
    photo_on_nok = fields.Boolean("Photo if Not OK", readonly=True)
    create_defect_on_nok = fields.Boolean("Defect if Not OK", readonly=True)
    default_severity = fields.Selection([(None, '')] + SEVERITIES,
        "Default Severity", readonly=True)
    value_ok = fields.Selection([
            (None, ''),
            ('ok', "OK"),
            ('nok', "Not OK"),
            ('na', "N/A"),
            ], "OK / Not OK", sort=False,
        states={
            'invisible': Eval('answer_type') != 'ok_nok_na',
            'readonly': Eval('locked', False),
            })
    value_yes_no = fields.Selection([
            (None, ''),
            ('yes', "Yes"),
            ('no', "No"),
            ], "Yes / No", sort=False,
        states={
            'invisible': Eval('answer_type') != 'yes_no',
            'readonly': Eval('locked', False),
            })
    value_number = fields.Float("Number",
        states={
            'invisible': Eval('answer_type') != 'number',
            'readonly': Eval('locked', False),
            })
    value_text = fields.Char("Text",
        states={
            'invisible': Eval('answer_type') != 'text',
            'readonly': Eval('locked', False),
            })
    value_date = fields.Date("Date",
        states={
            'invisible': Eval('answer_type') != 'date',
            'readonly': Eval('locked', False),
            })
    value_choice = fields.Selection('get_choices', "Choice",
        states={
            'invisible': Eval('answer_type') != 'selection',
            'readonly': Eval('locked', False),
            })
    answered = fields.Function(fields.Boolean("Answered"), 'get_answered')
    is_nok = fields.Function(fields.Boolean("Not OK"), 'get_is_nok')
    comment = fields.Text("Comment", states=_value_states)
    locked = fields.Function(fields.Boolean("Locked"), 'get_locked')

    @classmethod
    def set_ok(cls, results):
        """Answer the open items OK (ok_nok_na) resp. Yes (yes_no) - other
        answer types and answered items are left unchanged"""
        ok = [r for r in results
            if r.answer_type == 'ok_nok_na' and not r.value_ok]
        yes = [r for r in results
            if r.answer_type == 'yes_no' and not r.value_yes_no]
        to_write = []
        if ok:
            to_write.extend((ok, {'value_ok': 'ok'}))
        if yes:
            to_write.extend((yes, {'value_yes_no': 'yes'}))
        if to_write:
            cls.write(*to_write)

    @fields.depends('selection_values')
    def get_choices(self):
        values = [v.strip() for v in (self.selection_values or '').splitlines()
            if v.strip()]
        return [(None, '')] + [(v, v) for v in values]

    def get_rec_name(self, name):
        return ' / '.join(filter(None, [self.section, self.question]))

    def get_answered(self, name):
        field = ANSWER_FIELDS.get(self.answer_type)
        value = getattr(self, field, None) if field else None
        return value is not None and value != ''

    def get_is_nok(self, name):
        if self.answer_type == 'ok_nok_na':
            return self.value_ok == 'nok'
        if self.answer_type == 'yes_no':
            return self.value_yes_no == 'no'
        if self.answer_type == 'number' and self.value_number is not None:
            return bool((self.min_value is not None
                    and self.value_number < self.min_value)
                or (self.max_value is not None
                    and self.value_number > self.max_value))
        return False

    def get_locked(self, name):
        "Entry only while scheduled or in progress"
        inspection = self.inspection or (self.line and self.line.inspection)
        return bool(inspection
            and inspection.state not in ['scheduled', 'in_progress'])

    @classmethod
    def check_modification(cls, mode, results, values=None, external=False):
        super().check_modification(mode, results, values=values,
            external=external)
        if mode in ['write', 'delete'] and external:
            _check_locked(results,
                lambda r: r.inspection or (r.line and r.line.inspection))
        if mode == 'write' and external:
            _check_draft_entry(results,
                lambda r: r.inspection or (r.line and r.line.inspection),
                values)

    @classmethod
    def write(cls, *args):
        super().write(*args)
        results = sum(args[::2], [])
        cls._start_inspections(results)
        _check_inspection_processes({r.inspection for r in results
                if r.inspection})

    @classmethod
    def _start_inspections(cls, results):
        "The first entered result starts a scheduled inspection (4.1)"
        Inspection = Pool().get('real_estate.inspection')
        to_start = {r.inspection.id for r in cls.browse(results)
            if r.inspection and r.inspection.state == 'scheduled'
            and r.answered}
        if to_start:
            Inspection.start(Inspection.browse(list(to_start)))


#**********************************************************************
class InspectionPlanP2(metaclass=PoolMeta):
    __name__ = 'real_estate.inspection.plan'

    inspections = fields.One2Many('real_estate.inspection', 'plan',
        "Inspections", readonly=True)

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._buttons.update({
            'create_inspection': {
                'invisible': ~Eval('active', True),
                'depends': ['active'],
                },
            })

    @classmethod
    @ModelView.button_action('real_estate.act_inspection_form')
    def create_inspection(cls, plans):
        "Create the inspection now (independent of the lead time)"
        Inspection = Pool().get('real_estate.inspection')
        open_ = Inspection.search([
                ('plan', 'in', [p.id for p in plans]),
                ('state', 'in', OPEN_STATES),
                ], limit=1)
        if open_:
            raise ValidationError(gettext(
                    'real_estate.msg_inspection_plan_open',
                    plan=open_[0].plan.rec_name,
                    inspection=open_[0].rec_name))
        Inspection.create_from_plans(plans)

    @classmethod
    def create_due_inspections(cls, companies=None, date=None):
        """Scheduled task: create the inspections whose lead time is
        reached (spec 5) - at most one open per plan"""
        Date = Pool().get('ir.date')
        Inspection = Pool().get('real_estate.inspection')
        date = date or Date.today()
        domain = [('active', '=', True)]
        if companies:
            domain.append(('company', 'in', [c.id for c in companies]))
        due = [p for p in cls.search(domain)
            if p.next_due_date - datetime.timedelta(
                days=p.lead_time_days or 0) <= date]
        return Inspection.create_from_plans(due) if due else []


class Contract(metaclass=PoolMeta):
    __name__ = 'real_estate.contract'

    @classmethod
    def _cron_inspection_plans(cls, re_accounting, task=None):
        "Scheduled task 'inspection_plans': create the due inspections"
        pool = Pool()
        Company = pool.get('company.company')
        Plan = pool.get('real_estate.inspection.plan')
        companies = Company.search([('re_accounting', '=', re_accounting.id)])
        if companies:
            Plan.create_due_inspections(companies)


class Process(metaclass=PoolMeta):
    __name__ = 'real_estate.process'

    @classmethod
    def _check_inspection_leads(cls, processes):
        """The process of an inspection is cancelled resp. reactivated
        only by the inspection (cancel, back to draft, reactivate +
        schedule)"""
        if Transaction().context.get('_inspection_process_cancel'):
            return
        for process in processes:
            resource = process.resource
            if (resource and resource.__name__ == 'real_estate.inspection'
                    and resource.id is not None and resource.id >= 0):
                raise ValidationError(gettext(
                        'real_estate.msg_process_inspection_leads',
                        process=process.rec_name,
                        inspection=resource.rec_name))

    @classmethod
    def cancel(cls, processes):
        cls._check_inspection_leads(processes)
        super().cancel(processes)

    @classmethod
    def reactivate(cls, processes):
        cls._check_inspection_leads(processes)
        super().reactivate(processes)

    def _step_done_inspection_done(self):
        "The inspection (reference) is done or approved"
        resource = self.resource
        return bool(resource and resource.__name__ == 'real_estate.inspection'
            and resource.state in ['done', 'approved'])

    def _inspection(self):
        resource = self.resource
        if resource and resource.__name__ == 'real_estate.inspection':
            return resource

    def _step_done_inspection_attempt1_done(self):
        """First visit done: every line to visit has a visit date (or
        the inspection is done)"""
        inspection = self._inspection()
        if not inspection:
            return False
        if inspection.state in ['done', 'approved']:
            return True
        lines = [l for l in inspection.lines
            if l.access_status not in ['vacant', 'not_required']]
        return (inspection.state == 'in_progress'
            and all(l.visit_date for l in lines))

    def _step_done_inspection_attempt2_done(self):
        """Next attempt done: the lines of the next attempt have a visit
        date again (or the inspection is done)"""
        inspection = self._inspection()
        if not inspection:
            return False
        if inspection.state in ['done', 'approved']:
            return True
        lines = [l for l in inspection.lines if (l.attempt or 1) > 1]
        return bool(lines) and all(l.visit_date for l in lines)

    def _step_create_inspection_no_access(self):
        "Lines without access (no access, refused) - spec 4.2"
        inspection = self._inspection()
        return bool(inspection and any(l.access_status in [
                        'no_access', 'refused'] for l in inspection.lines))

    def _step_create_inspection_has_defects(self):
        """A finding of severity major or critical: a not OK result whose
        item creates a defect - spec 4.2"""
        inspection = self._inspection()
        if not inspection:
            return False
        results = list(inspection.header_results) + [
            r for l in inspection.lines for r in l.results]
        return any(r.is_nok and r.create_defect_on_nok
            and r.default_severity in ['critical', 'major']
            for r in results)

    def _step_done_inspection_approved(self):
        "The inspection (reference) is approved"
        resource = self.resource
        return bool(resource and resource.__name__ == 'real_estate.inspection'
            and resource.state == 'approved')


class BaseObjectP2(metaclass=PoolMeta):
    __name__ = 'real_estate.base_object'

    property_inspections = fields.One2Many('real_estate.inspection',
        'property', "Inspections", readonly=True,
        states={'invisible': Eval('type') != 'property'})
    building_inspections = fields.One2Many('real_estate.inspection',
        'building', "Inspections", readonly=True,
        states={'invisible': Eval('type') != 'building'})
    inspection_lines = fields.One2Many('real_estate.inspection.line',
        'base_object', "Inspection Lines", readonly=True,
        states={'invisible': ~Eval('type').in_(['object', 'equipment'])})


class InspectionReport(Report):
    """Inspection report (Prüfprotokoll, spec 6.3) - marked ENTWURF before
    the approval"""
    __name__ = 'real_estate.inspection.report'

    @classmethod
    def get_context(cls, records, header, data):
        pool = Pool()
        ContractReport = pool.get('real_estate.contract.report',
            type='report')
        Inspection = pool.get('real_estate.inspection')
        Line = pool.get('real_estate.inspection.line')
        Result = pool.get('real_estate.inspection.result')
        context = super().get_context(records, header, data)
        context['format_value'] = ContractReport.format_value

        def labels(Model, field):
            return dict(Model.fields_get([field])[field]['selection'])
        context['overall_results'] = labels(Inspection, 'overall_result')
        context['access_states'] = labels(Line, 'access_status')
        context['line_results'] = labels(Line, 'result')
        context['ok_values'] = labels(Result, 'value_ok')
        context['yes_no_values'] = labels(Result, 'value_yes_no')
        context['marks'] = {r.id: '' if r.state == 'approved' else 'ENTWURF'
            for r in records}
        Defect = pool.get('real_estate.inspection.defect')
        context['severities'] = labels(Defect, 'severity')
        context['defect_states'] = labels(Defect, 'state')

        def answer(result):
            if result.answer_type == 'ok_nok_na':
                return context['ok_values'].get(result.value_ok) or ''
            if result.answer_type == 'yes_no':
                return context['yes_no_values'].get(result.value_yes_no) or ''
            field = ANSWER_FIELDS.get(result.answer_type)
            value = getattr(result, field, None) if field else None
            if value is None:
                return ''
            if result.answer_type == 'number':
                text = ContractReport.format_value(value)
                return ' '.join(filter(None, [text,
                            result.unit.symbol if result.unit else None]))
            return ContractReport.format_value(value)
        context['answer'] = answer
        return context


#**********************************************************************
# Phase P3: tenant notice and letter to tenants without access

def _complete_steps(inspections, wiz_name):
    """Process steps with this action are done as well when it is run on
    the inspection itself (not from the task)"""
    Task = Pool().get('real_estate.task')
    Task.complete_by_action(inspections,
        {'type': 'ir.action.wizard', 'wiz_name': wiz_name})


def _archive(Report, records, data=None):
    "Render the report for the records and attach it to each of them"
    Attachment = Pool().get('ir.attachment')
    ext, content, _, name = Report.execute([r.id for r in records],
        dict({'model': records[0].__name__}, **(data or {})))
    return Attachment.create([{
                'name': f'{name}.{ext}',
                'resource': str(record),
                'data': content,
                } for record in records])


class InspectionNoticeCreate(Wizard):
    "Create Tenant Notice"
    __name__ = 'real_estate.inspection.notice.create'

    start_state = 'archive'
    archive = StateTransition()
    print_ = StateReport('real_estate.inspection.notice')

    def transition_archive(self):
        """Archive the notice as proof of the notice date (spec 6.2)"""
        pool = Pool()
        Inspection = pool.get('real_estate.inspection')
        Report = pool.get('real_estate.inspection.notice', type='report')
        Date = pool.get('ir.date')
        inspections = [i for i in self.records
            if i.state in ['scheduled', 'in_progress']]
        if not inspections:
            raise ValidationError(gettext(
                    'real_estate.msg_inspection_notice_state'))
        attachments = _archive(Report, inspections)
        for inspection, attachment in zip(inspections, attachments):
            Inspection.write([inspection], {
                    'notice': attachment.id,
                    'notice_date': inspection.notice_date or Date.today(),
                    })
        _complete_steps(inspections, 'real_estate.inspection.notice.create')
        return 'print_'

    def do_print_(self, action):
        ids = [r.id for r in self.records]
        return action, {'ids': ids, 'id': ids[0],
            'model': 'real_estate.inspection'}


class InspectionAccessLetterCreate(Wizard):
    "Create Letters to Tenants without Access"
    __name__ = 'real_estate.inspection.access_letter.create'

    start_state = 'archive'
    archive = StateTransition()
    print_ = StateReport('real_estate.inspection.access_letter')

    def _lines(self):
        return [l for i in self.records for l in i.lines
            if l.access_status in ['no_access', 'refused']]

    def transition_archive(self):
        pool = Pool()
        Line = pool.get('real_estate.inspection.line')
        Report = pool.get('real_estate.inspection.access_letter',
            type='report')
        Date = pool.get('ir.date')
        lines = self._lines()
        if not lines:
            raise ValidationError(gettext(
                    'real_estate.msg_inspection_no_lines_without_access',
                    inspection=', '.join(r.rec_name for r in self.records)))
        _archive(Report, self.records)
        Line.write(lines, {'letter_date': Date.today()})
        _complete_steps(self.records,
            'real_estate.inspection.access_letter.create')
        return 'print_'

    def do_print_(self, action):
        ids = [r.id for r in self.records]
        return action, {'ids': ids, 'id': ids[0],
            'model': 'real_estate.inspection'}


class InspectionNoticeReport(Report):
    "Tenant notice of an inspection (spec 6.2)"
    __name__ = 'real_estate.inspection.notice'

    @classmethod
    def get_context(cls, records, header, data):
        pool = Pool()
        ContractReport = pool.get('real_estate.contract.report',
            type='report')
        context = super().get_context(records, header, data)
        context['format_value'] = ContractReport.format_value

        def buildings(inspection):
            if inspection.building:
                return [inspection.building]
            BaseObject = pool.get('real_estate.base_object')
            found = BaseObject.search([
                    ('parent', 'child_of', [inspection.property.id]),
                    ('type', '=', 'building'),
                    ])
            return found or [inspection.property]
        context['buildings'] = buildings
        return context


class InspectionAccessLetterReport(Report):
    """Letter to the tenants of the lines without access (one page per
    line)"""
    __name__ = 'real_estate.inspection.access_letter'

    @classmethod
    def get_context(cls, records, header, data):
        pool = Pool()
        ContractReport = pool.get('real_estate.contract.report',
            type='report')
        context = super().get_context(records, header, data)
        context['format_value'] = ContractReport.format_value
        context['letters'] = [(i, l, l.tenant,
                l.tenant.address_get(type='invoice') if l.tenant else None)
            for i in records for l in i.lines
            if l.access_status in ['no_access', 'refused']]
        return context


#**********************************************************************
# Phase P4: defects (spec 3.3, 4.4)
DEFECT_STATES = [
    ('open', "Open"),
    ('in_progress', "In Progress"),
    ('fixed', "Fixed"),
    ('verified', "Verified"),
    ('cancelled', "Cancelled"),
    ]
DEFECT_OPEN = ['open', 'in_progress', 'fixed']
# fields of a defect of an approved inspection that stay editable
DEFECT_UNLOCKED = {'state', 'fixed_date', 'verified_date', 'verified_by',
    'verified_in', 'follow_up_task', 'responsible_party', 'deadline',
    'cost_category'}


class InspectionDefect(Workflow, ModelSQL, ModelView):
    "Inspection Defect"
    __name__ = 'real_estate.inspection.defect'

    _states = {'readonly': ~Eval('state').in_(['open', 'in_progress'])}

    company = fields.Many2One('company.company', "Company", required=True,
        readonly=True)
    inspection = fields.Many2One('real_estate.inspection', "Inspection",
        required=True, ondelete='RESTRICT',
        states={'readonly': Eval('id', -1) >= 0})
    plan = fields.Many2One('real_estate.inspection.plan', "Inspection Plan",
        readonly=True, ondelete='SET NULL')
    property = fields.Many2One('real_estate.base_object', "Property",
        readonly=True, ondelete='RESTRICT')
    building = fields.Many2One('real_estate.base_object', "Building",
        readonly=True, ondelete='RESTRICT')
    line = fields.Many2One('real_estate.inspection.line', "Line",
        ondelete='SET NULL',
        domain=[('inspection', '=', Eval('inspection', -1))],
        states=_states)
    result = fields.Many2One('real_estate.inspection.result', "Result",
        readonly=True, ondelete='SET NULL')
    base_object = fields.Many2One('real_estate.base_object', "Object",
        ondelete='RESTRICT', states=_states,
        help="Building, rental unit or equipment concerned.")
    description = fields.Text("Description", required=True, states=_states)
    severity = fields.Selection(SEVERITIES, "Severity", required=True,
        sort=False, states=_states)
    detected_date = fields.Date("Detected on", required=True,
        states=_states)
    deadline = fields.Date("Deadline",
        states={'readonly': Eval('state').in_(['verified', 'cancelled'])},
        help="Detection date plus the days of the severity of the "
             "inspection type; none for notes.")
    responsible_party = fields.Many2One('party.party', "Responsible",
        states={'readonly': Eval('state').in_(['verified', 'cancelled'])},
        help="Contractor or person who fixes the defect.")
    follow_up_task = fields.Many2One('real_estate.task', "Follow-up Task",
        readonly=True, ondelete='SET NULL')
    state = fields.Selection(DEFECT_STATES, "State", readonly=True,
        required=True, sort=False)
    fixed_date = fields.Date("Fixed on",
        states={'readonly': Eval('state') != 'fixed'})
    verified_date = fields.Date("Verified on", readonly=True)
    verified_by = fields.Many2One('res.user', "Verified by", readonly=True)
    verified_in = fields.Many2One('real_estate.inspection', "Verified in",
        domain=[('plan', '=', Eval('plan', -1))],
        states={'readonly': Eval('state') != 'fixed'},
        help="Inspection in which the fix was checked.")
    cost_category = fields.Selection([
            ('unknown', "Unknown"),
            ('maintenance', "Maintenance"),
            ('operating_costs', "Operating Costs"),
            ], "Cost Category", required=True, sort=False)
    overdue = fields.Function(fields.Boolean("Overdue"),
        'get_overdue', searcher='search_overdue')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._order = [('deadline', 'ASC NULLS LAST'), ('id', 'ASC')]
        cls._transitions |= {
            ('open', 'in_progress'),
            ('open', 'fixed'),
            ('in_progress', 'fixed'),
            ('fixed', 'verified'),
            ('fixed', 'in_progress'),
            ('open', 'cancelled'),
            ('in_progress', 'cancelled'),
            ('cancelled', 'open'),
            }
        cls._buttons.update({
            'start': {
                'invisible': Eval('state') != 'open',
                'depends': ['state'],
                },
            'fix': {
                'invisible': ~Eval('state').in_(['open', 'in_progress']),
                'depends': ['state'],
                },
            'verify': {
                'invisible': Eval('state') != 'fixed',
                'depends': ['state'],
                },
            'reject': {
                'invisible': Eval('state') != 'fixed',
                'depends': ['state'],
                },
            'cancel': {
                'invisible': ~Eval('state').in_(['open', 'in_progress']),
                'depends': ['state'],
                },
            'reopen': {
                'invisible': Eval('state') != 'cancelled',
                'depends': ['state'],
                },
            })

    @staticmethod
    def default_state():
        return 'open'

    @staticmethod
    def default_cost_category():
        return 'unknown'

    @staticmethod
    def default_severity():
        return 'minor'

    @staticmethod
    def default_detected_date():
        return Pool().get('ir.date').today()

    @staticmethod
    def default_company():
        return Transaction().context.get('company')

    def get_rec_name(self, name):
        text = (self.description or '').splitlines()[0][:60] \
            if self.description else ''
        obj = self.base_object or self.building or self.property
        return ' - '.join(filter(None, [obj.rec_name if obj else None,
                    text]))

    @classmethod
    def search_rec_name(cls, name, clause):
        _, operator, value = clause
        bool_op = 'AND' if operator.startswith('!') else 'OR'
        return [bool_op,
            ('description', operator, value),
            ('base_object.rec_name', operator, value),
            ('inspection.rec_name', operator, value),
            ]

    @staticmethod
    def compute_deadline(type_, severity, date):
        "Deadline by the severity of the inspection type (spec 4.4)"
        if not date or severity == 'note' or not type_:
            return None
        days = getattr(type_, f'defect_days_{severity}', None)
        return date + datetime.timedelta(days=days) \
            if days is not None else None

    @fields.depends('inspection', 'severity', 'detected_date', 'deadline',
        '_parent_inspection.type')
    def on_change_severity(self):
        if self.inspection:
            self.deadline = self.compute_deadline(self.inspection.type,
                self.severity, self.detected_date)

    @fields.depends(methods=['on_change_severity'])
    def on_change_detected_date(self):
        self.on_change_severity()

    def get_overdue(self, name):
        today = Pool().get('ir.date').today()
        return bool(self.state in ['open', 'in_progress'] and self.deadline
            and self.deadline < today)

    @classmethod
    def search_overdue(cls, name, clause):
        _, operator, value = clause
        today = Pool().get('ir.date').today()
        domain = [('state', 'in', ['open', 'in_progress']),
            ('deadline', '<', today)]
        positive = (operator == '=') == bool(value)
        return domain if positive else ['NOT', domain]

    @classmethod
    def create(cls, vlist):
        Inspection = Pool().get('real_estate.inspection')
        vlist = [v.copy() for v in vlist]
        for values in vlist:
            inspection = Inspection(values['inspection'])
            values.setdefault('company', inspection.company.id)
            values['plan'] = inspection.plan.id
            values['property'] = inspection.property.id
            values['building'] = (inspection.building.id
                if inspection.building else None)
            if not values.get('base_object'):
                values['base_object'] = (inspection.building
                    or inspection.property).id
            if 'deadline' not in values:
                values['deadline'] = cls.compute_deadline(inspection.type,
                    values.get('severity', 'minor'),
                    values.get('detected_date') or Pool().get(
                        'ir.date').today())
        defects = super().create(vlist)
        cls._create_tasks(defects)
        return defects

    @classmethod
    def _create_tasks(cls, defects):
        "Follow-up task for every defect from severity minor (spec 4.4)"
        Task = Pool().get('real_estate.task')
        Date = Pool().get('ir.date')
        for defect in defects:
            if defect.severity == 'note' or defect.follow_up_task:
                continue
            task = Task.create_for(defect, 'inspection_defect',
                defect.deadline or Date.today(),
                name=defect.rec_name, description=defect.description,
                company=defect.company)
            if task:
                cls.write([defect], {'follow_up_task': task.id})

    @classmethod
    @ModelView.button
    @Workflow.transition('in_progress')
    def start(cls, defects):
        pass

    @classmethod
    @ModelView.button
    @Workflow.transition('fixed')
    def fix(cls, defects):
        Task = Pool().get('real_estate.task')
        Date = Pool().get('ir.date')
        for defect in defects:
            if not defect.fixed_date:
                cls.write([defect], {'fixed_date': Date.today()})
        tasks = [d.follow_up_task for d in defects
            if d.follow_up_task and d.follow_up_task.state == 'open']
        if tasks:
            Task.done(tasks)

    @classmethod
    @ModelView.button
    @Workflow.transition('verified')
    def verify(cls, defects):
        Date = Pool().get('ir.date')
        values = {
            'verified_date': Date.today(),
            'verified_by': Transaction().user,
            }
        inspection_id = Transaction().context.get('inspection')
        if inspection_id:
            values['verified_in'] = inspection_id
        cls.write(defects, values)

    @classmethod
    @ModelView.button
    @Workflow.transition('in_progress')
    def reject(cls, defects):
        "The fix was not sufficient: back to in progress"
        cls.write(defects, {'fixed_date': None})

    @classmethod
    @ModelView.button
    @Workflow.transition('cancelled')
    def cancel(cls, defects):
        Task = Pool().get('real_estate.task')
        tasks = [d.follow_up_task for d in defects
            if d.follow_up_task and d.follow_up_task.state == 'open']
        if tasks:
            for task in tasks:
                if not task.result:
                    Task.write([task], {'result': gettext(
                                'real_estate.msg_inspection_defect_cancelled')})
            Task.cancel(tasks)

    @classmethod
    @ModelView.button
    @Workflow.transition('open')
    def reopen(cls, defects):
        cls.write(defects, {'follow_up_task': None})
        cls._create_tasks(cls.browse([d.id for d in defects]))

    @classmethod
    def check_modification(cls, mode, defects, values=None, external=False):
        super().check_modification(mode, defects, values=values,
            external=external)
        if not external:
            return
        if mode == 'delete':
            for defect in defects:
                if defect.inspection.state == 'approved':
                    raise AccessError(gettext(
                            'real_estate.msg_inspection_locked',
                            inspection=defect.inspection.rec_name))
        elif mode == 'write' and values and set(values) - DEFECT_UNLOCKED:
            _check_locked(defects, lambda d: d.inspection)


class InspectionP4(metaclass=PoolMeta):
    __name__ = 'real_estate.inspection'

    defects = fields.One2Many('real_estate.inspection.defect', 'inspection',
        "Defects", states={'readonly': Eval('state') == 'cancelled'})
    previous_defects = fields.Function(fields.One2Many(
            'real_estate.inspection.defect', None,
            "Open Defects of Previous Inspections",
            readonly=True,
            # verified from here: the inspection is "verified in"
            context={'inspection': Eval('id', -1)}, depends={'id'}),
        'get_previous_defects', setter='set_previous_defects')

    @classmethod
    def get_previous_defects(cls, inspections, name):
        "Not verified defects of earlier inspections of the plan (4.4)"
        Defect = Pool().get('real_estate.inspection.defect')
        result = {i.id: [] for i in inspections}
        for inspection in inspections:
            if not inspection.plan or inspection.id is None:
                continue
            result[inspection.id] = [d.id for d in Defect.search([
                        ('plan', '=', inspection.plan.id),
                        ('inspection', '!=', inspection.id),
                        ('state', 'in', DEFECT_OPEN),
                        ])]
        return result

    @classmethod
    def set_previous_defects(cls, inspections, name, value):
        pass

    @classmethod
    def copy(cls, inspections, default=None):
        default = default.copy() if default is not None else {}
        default.setdefault('defects', None)
        return super().copy(inspections, default=default)

    def _compute_overall(self):
        if any(d.severity == 'critical' and d.state != 'cancelled'
                for d in self.defects):
            return 'not_ok'
        if any(d.state != 'cancelled' for d in self.defects):
            return 'ok_with_defects'
        return super()._compute_overall()


class InspectionResultP4(metaclass=PoolMeta):
    __name__ = 'real_estate.inspection.result'

    defects = fields.One2Many('real_estate.inspection.defect', 'result',
        "Defects", readonly=True)

    @classmethod
    def write(cls, *args):
        super().write(*args)
        cls._sync_defects(sum(args[::2], []))

    @classmethod
    def _sync_defects(cls, results):
        """A not OK answer of an item with 'create_defect_on_nok' creates a
        defect; withdrawn, the still open defect is cancelled (4.4)"""
        Defect = Pool().get('real_estate.inspection.defect')
        to_create, to_cancel = [], []
        for result in cls.browse(results):
            if not result.create_defect_on_nok:
                continue
            inspection = result.inspection or (
                result.line and result.line.inspection)
            if not inspection or inspection.state not in [
                    'scheduled', 'in_progress']:
                continue
            active = [d for d in result.defects
                if d.state not in ['cancelled']]
            if result.is_nok and not active:
                obj = (result.line.base_object if result.line
                    else inspection.building or inspection.property)
                to_create.append({
                        'inspection': inspection.id,
                        'line': result.line.id if result.line else None,
                        'result': result.id,
                        'base_object': obj.id,
                        'description': '\n'.join(filter(None, [
                                    ' / '.join(filter(None, [
                                                result.section,
                                                result.question])),
                                    result.comment])),
                        'severity': result.default_severity or 'minor',
                        })
            elif not result.is_nok:
                to_cancel += [d for d in active if d.state == 'open']
        if to_create:
            Defect.create(to_create)
        if to_cancel:
            Defect.cancel(to_cancel)
        if to_create or to_cancel:
            _check_inspection_processes({r.inspection
                    for r in cls.browse(results) if r.inspection})


class InspectionLineP4(metaclass=PoolMeta):
    __name__ = 'real_estate.inspection.line'

    defects = fields.One2Many('real_estate.inspection.defect', 'line',
        "Defects", readonly=True)

    def get_result(self, name):
        result = super().get_result(name)
        if result == 'ok' and any(d.state != 'cancelled'
                for d in self.defects):
            return 'defect'
        return result


class ProcessP4(metaclass=PoolMeta):
    __name__ = 'real_estate.process'

    def _step_create_inspection_has_defects(self):
        "Also by recorded defects of severity major or critical"
        inspection = self._inspection()
        if inspection and any(d.severity in ['critical', 'major']
                and d.state != 'cancelled' for d in inspection.defects):
            return True
        return super()._step_create_inspection_has_defects()


class BaseObjectP4(metaclass=PoolMeta):
    __name__ = 'real_estate.base_object'

    property_defects = fields.One2Many('real_estate.inspection.defect',
        'property', "Open Defects", readonly=True,
        filter=[('state', 'in', DEFECT_OPEN)],
        states={'invisible': Eval('type') != 'property'})
    building_defects = fields.One2Many('real_estate.inspection.defect',
        'building', "Open Defects", readonly=True,
        filter=[('state', 'in', DEFECT_OPEN)],
        states={'invisible': Eval('type') != 'building'})
    object_defects = fields.One2Many('real_estate.inspection.defect',
        'base_object', "Open Defects", readonly=True,
        filter=[('state', 'in', DEFECT_OPEN)],
        states={'invisible': ~Eval('type').in_(['object', 'equipment'])})


class TaskRule(metaclass=PoolMeta):
    __name__ = 'real_estate.task.rule'

    def _date_inspection_overdue(self, records, today):
        "Inspections not finished: due date plus tolerance of the type"
        return [(r, r.due_date + datetime.timedelta(
                    days=r.type.tolerance_days or 0))
            for r in records if r.__name__ == 'real_estate.inspection'
            and r.state in ['draft', 'scheduled', 'in_progress']]

    def _date_defect_overdue(self, records, today):
        "Defects open or in progress: their deadline"
        return [(r, r.deadline) for r in records
            if r.__name__ == 'real_estate.inspection.defect'
            and r.state in ['open', 'in_progress'] and r.deadline]
