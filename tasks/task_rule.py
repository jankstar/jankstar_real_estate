'Task rules (Aufgabenregeln) - spezifikation-wiedervorlage.md 5, phase C'
import datetime
import logging

from dateutil.relativedelta import relativedelta

from trytond.i18n import gettext
from trytond.model import DeactivableMixin, ModelSQL, ModelView, fields
from trytond.model.exceptions import ValidationError
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Eval, PYSONDecoder
from trytond.transaction import Transaction

logger = logging.getLogger(__name__)

# Path from a reference model to its company (rule company filter)
COMPANY_PATHS = {
    'real_estate.contract': 'company',
    'real_estate.contract.party': 'contract.company',
    'real_estate.contract.rent_adjustment': 'contract.company',
    'real_estate.contract.term.adjustment': 'term_old.contract.company',
    'real_estate.base_object': 'company',
    'real_estate.billing_unit': 'property.company',
    }

# Named date methods (spec 5.3): name -> label; implemented as
# TaskRule._date_<name>(records, today) -> [(record, reference date)]
DATE_METHODS = [
    'billing_deadline',
    'meter_reading_due',
    'index_values_stale',
    'no_follow_up_contract',
    'state_since',
    'cron_overdue',
    'inspection_overdue',
    'defect_overdue',
    ]


def _decode(domain):
    return PYSONDecoder({}).decode(domain) if domain else []


#**********************************************************************
class TaskRule(DeactivableMixin, ModelSQL, ModelView):
    "Task Rule"
    __name__ = 'real_estate.task.rule'

    name = fields.Char("Name", required=True, translate=True)
    company = fields.Many2One('company.company', "Company",
        help="Empty = all companies.")
    model = fields.Selection('get_models', "Reference Object", required=True)
    domain = fields.Char("Domain",
        help="Restriction of the records as PYSON domain (like the domain "
             "of an action), e.g. [[\"state\", \"=\", \"running\"]]. Empty "
             "= all records.")
    date_source = fields.Selection([
            ('field', "Date Field"),
            ('method', "Method"),
            ], "Date Source", required=True, sort=False)
    date_field = fields.Selection('get_date_fields', "Date Field",
        states={
            'invisible': Eval('date_source') != 'field',
            'required': Eval('date_source') == 'field',
            })
    date_method = fields.Selection('get_date_methods', "Method",
        sort=False,
        states={
            'invisible': Eval('date_source') != 'method',
            'required': Eval('date_source') == 'method',
            })
    offset_months = fields.Integer("Offset (Months)",
        help="Due date = reference date + offset (negative = before).")
    offset_days = fields.Integer("Offset (Days)")
    horizon_days = fields.Integer("Lead Time (Days)", required=True,
        domain=[('horizon_days', '>=', 0)],
        help="The task is created as soon as its due date is at most this "
             "many days ahead.")
    task_type = fields.Many2One('real_estate.task.type', "Task Type",
        required=True, ondelete='RESTRICT',
        domain=[('for_model', '=', Eval('model', ''))])
    name_template = fields.Char("Subject", translate=True,
        help="Subject of the tasks, %(record)s is replaced by the record - "
             "empty = name of the task type and the record.")
    done_domain = fields.Char("Done Condition",
        help="PYSON domain: open tasks of the rule are done automatically "
             "as soon as the record matches it. Records no longer matching "
             "the domain above are done as well.")
    on_date_change = fields.Selection([
            ('cancel', "Cancel and Create New"),
            ('done', "Done and Create New"),
            ], "On Changed Reference Date", required=True, sort=False,
        help="When the reference date of an open task changes (e.g. a "
             "new calibration was entered): cancel it or set it done, a "
             "new task is created for the new date.")
    description = fields.Text("Description", translate=True)
    last_run = fields.Date("Last Run", readonly=True)
    last_message = fields.Char("Last Result", readonly=True)

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._order.insert(0, ('name', 'ASC'))
        cls._buttons.update({
            'run_now': {},
            })

    @staticmethod
    def default_date_source():
        return 'field'

    @staticmethod
    def default_horizon_days():
        return 30

    @staticmethod
    def default_on_date_change():
        return 'cancel'

    @classmethod
    def get_models(cls):
        return Pool().get('real_estate.task').get_resources()

    @fields.depends('model')
    def get_date_fields(self):
        """Date fields of the reference model (also function fields, they
        are evaluated in Python)."""
        if not self.model:
            return [(None, '')]
        Model = Pool().get(self.model)
        result = [(None, '')]
        for name, field in sorted(Model._fields.items()):
            type_ = getattr(field, '_type', None)
            if type_ == 'date':
                result.append((name, f'{field.string} ({name})'))
        return result

    @classmethod
    def get_date_methods(cls):
        return [(None, '')] + [(name,
                gettext(f'real_estate.msg_task_rule_method_{name}'))
            for name in DATE_METHODS]

    @classmethod
    def validate_fields(cls, rules, field_names):
        super().validate_fields(rules, field_names)
        if field_names & {'domain', 'done_domain'}:
            for rule in rules:
                for value in (rule.domain, rule.done_domain):
                    try:
                        domain = _decode(value)
                        assert isinstance(domain, list)
                    except Exception:
                        raise ValidationError(gettext(
                                'real_estate.msg_task_rule_domain',
                                rule=rule.rec_name, domain=value))

    # ------------------------------------------------------------------
    # Run (spec 5.2)

    def _company_domain(self, companies):
        path = COMPANY_PATHS.get(self.model)
        if not path:
            return []
        ids = [c.id for c in companies] if companies else []
        if self.company:
            ids = [i for i in ids if i == self.company.id] if ids \
                else [self.company.id]
            if not ids:
                return None
        return [(path, 'in', ids)] if ids else []

    def _candidates(self, companies, today):
        "[(record, reference date)] of the rule"
        Model = Pool().get(self.model)
        company_domain = self._company_domain(companies)
        if company_domain is None:
            return []
        with Transaction().set_context(active_test=True):
            records = Model.search(_decode(self.domain) + company_domain)
        if self.date_source == 'method':
            return getattr(self, f'_date_{self.date_method}')(records, today)
        return [(r, getattr(r, self.date_field)) for r in records
            if getattr(r, self.date_field, None)]

    def _due_date(self, reference):
        return reference + relativedelta(months=self.offset_months or 0,
            days=self.offset_days or 0)

    def _key(self, record, reference):
        return f'{record}@{reference.isoformat()}'

    @classmethod
    def run(cls, rules, companies=None, date=None):
        """Create, close and renew the tasks of the rules - idempotent
        (one task per record and reference date). Errors of one rule are
        logged and do not stop the others. Returns {rule id: message}."""
        pool = Pool()
        Date = pool.get('ir.date')
        today = date or Date.today()
        result = {}
        for rule in rules:
            try:
                counts = rule._run(companies, today)
                message = gettext('real_estate.msg_task_rule_result',
                    **counts)
            except Exception as e:
                logger.exception('task rule %s failed', rule.id)
                message = f'{e.__class__.__name__}: {e}'
            result[rule.id] = message
            cls.write([rule], {'last_run': today,
                    'last_message': message[:250]})
        return result

    def _run(self, companies, today):
        pool = Pool()
        Task = pool.get('real_estate.task')
        Model = pool.get(self.model)
        counts = dict.fromkeys(['created', 'done', 'renewed'], 0)
        horizon = today + datetime.timedelta(days=self.horizon_days or 0)
        candidates = {str(r): (r, ref) for r, ref in
            self._candidates(companies, today)}
        done_ids = set()
        if self.done_domain and candidates:
            done_ids = {r.id for r in Model.search(_decode(self.done_domain)
                    + [('id', 'in', [r.id for r, _ in candidates.values()])])}
        origin = str(self)

        # Open tasks of the rule: done when the record no longer matches
        # or matches the done condition, renewed when the date changed
        for task in Task.search([
                    ('origin', '=', origin), ('state', '=', 'open')]):
            resource = str(task.resource) if task.resource else None
            candidate = candidates.get(resource)
            if (candidate is None
                    or (task.resource and task.resource.id in done_ids)):
                Task.write([task], {'result': gettext(
                            'real_estate.msg_task_rule_auto_done')})
                Task.done([task])
                counts['done'] += 1
                continue
            record, reference = candidate
            if task.origin_key != self._key(record, reference):
                Task.write([task], {'result': gettext(
                            'real_estate.msg_task_rule_date_changed')})
                if self.on_date_change == 'done':
                    Task.done([task])
                else:
                    Task.cancel([task])
                counts['renewed'] += 1

        # New tasks for records due within the lead time
        to_create = []
        for resource, (record, reference) in candidates.items():
            if record.id in done_ids:
                continue
            due = self._due_date(reference)
            if due > horizon:
                continue
            key = self._key(record, reference)
            if Task.search([('origin', '=', origin),
                        ('origin_key', '=', key)], limit=1):
                continue
            to_create.append(self._task_values(record, due, key))
        if to_create:
            Task.create(to_create)
            counts['created'] = len(to_create)
        return counts

    def _task_values(self, record, due, key):
        Task = Pool().get('real_estate.task')
        if self.name_template:
            try:
                name = self.name_template % {'record': record.rec_name}
            except (KeyError, ValueError, TypeError):
                name = f'{self.name_template} {record.rec_name}'
        else:
            name = f'{self.task_type.name}: {record.rec_name}'
        company = Task._resource_company(record) or self.company
        return {
            'company': company.id if company else
                Transaction().context.get('company'),
            'name': name,
            'task_type': self.task_type.id,
            'resource': str(record),
            'due_date': due,
            'description': self.description,
            'origin': str(self),
            'origin_key': key,
            'automatic': True,
            }

    @classmethod
    @ModelView.button
    def run_now(cls, rules):
        Company = Pool().get('company.company')
        company = Transaction().context.get('company')
        cls.run(rules, [Company(company)] if company else None)

    # ------------------------------------------------------------------
    # Named date methods (spec 5.3)

    def _date_billing_deadline(self, records, today):
        "Billing units not billed: end of the period + 12 months (§ 556)"
        return [(r, r.end_date + relativedelta(months=12)) for r in records
            if r.__name__ == 'real_estate.billing_unit'
            and r.state != 'billed' and r.end_date]

    def _date_meter_reading_due(self, records, today):
        """Properties whose meters lack a reading at the end of the
        billing period (day before the next billing start, +/- 7 days)"""
        pool = Pool()
        BaseObject = pool.get('real_estate.base_object')
        Reading = pool.get('real_estate.meter_reading')
        result = []
        for record in records:
            if (record.__name__ != 'real_estate.base_object'
                    or record.type != 'property'
                    or not record.next_billing_start_date):
                continue
            cutoff = record.next_billing_start_date - datetime.timedelta(
                days=1)
            meters = BaseObject.search([
                    ('parent', 'child_of', [record.id]),
                    ('type', '=', 'equipment'),
                    ('e_type', '=', 'meters'),
                    ])
            for meter in meters:
                if not Reading.search([
                            ('base_object', '=', meter.id),
                            ('reading_date', '>=', cutoff
                                - datetime.timedelta(days=7)),
                            ('reading_date', '<=', cutoff
                                + datetime.timedelta(days=7)),
                            ], limit=1):
                    result.append((record, cutoff))
                    break
        return result

    def _date_index_values_stale(self, records, today):
        """Price indices whose last final value is older than 2 months:
        expected next value = last month + 2 months"""
        limit = today.replace(day=1) - relativedelta(months=2)
        return [(r, r.last_value_month + relativedelta(months=2))
            for r in records if r.__name__ == 'real_estate.price_index'
            and r.last_value_month and r.last_value_month < limit]

    def _date_no_follow_up_contract(self, records, today):
        """Terminated contracts without a later contract for one of their
        objects: termination date"""
        Contract = Pool().get('real_estate.contract')
        result = []
        for contract in records:
            if (contract.__name__ != 'real_estate.contract'
                    or contract.state != 'terminated'):
                continue
            end = contract.get_effective_end_date()
            if not end:
                continue
            objects = {o.id for item in contract.items for o in item.objects}
            if not objects:
                continue
            others = Contract.search([
                    ('id', '!=', contract.id),
                    ('state', 'in', ['draft', 'running']),
                    ('items.objects', 'in', list(objects)),
                    ('start_date', '>', contract.start_date),
                    ], limit=1)
            if not others:
                result.append((contract, end))
        return result

    def _date_state_since(self, records, today):
        "Date of the last state transition (ir.model.log)"
        Log = Pool().get('ir.model.log')
        last = {}
        if records:
            for log in Log.search([
                        ('resource', 'in', [str(r) for r in records]),
                        ('event', '=', 'transition'),
                        ], order=[('create_date', 'ASC')]):
                last[str(log.resource)] = log.create_date.date()
        return [(r, last[str(r)]) for r in records if str(r) in last]

    def _date_cron_overdue(self, records, today):
        """Active scheduled tasks not run for their interval + 3 days:
        expected run"""
        result = []
        for task in records:
            if (task.__name__ != 'real_estate.cron_task' or not task.active
                    or not task.last_run):
                continue
            if task.interval_months:
                expected = task.last_run + relativedelta(
                    months=task.interval_months)
            elif task.interval_days:
                expected = task.last_run + datetime.timedelta(
                    days=task.interval_days)
            else:
                expected = task.last_run + relativedelta(months=1)
            if expected + datetime.timedelta(days=3) < today:
                result.append((task, expected))
        return result


#**********************************************************************
class Contract(metaclass=PoolMeta):
    __name__ = 'real_estate.contract'

    @classmethod
    def _cron_task_rules(cls, re_accounting, task=None):
        "Scheduled task 'task_rules': run all active task rules"
        pool = Pool()
        Company = pool.get('company.company')
        Rule = pool.get('real_estate.task.rule')
        companies = Company.search([('re_accounting', '=', re_accounting.id)])
        if companies:
            Rule.run(Rule.search([]), companies)
