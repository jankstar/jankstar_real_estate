'Real Estate Cron Task'
from trytond.model import ModelSQL, ModelView, Unique, fields
from trytond.model.exceptions import ValidationError
from trytond.i18n import gettext
from trytond.pyson import Bool, Eval


class CronTask(ModelSQL, ModelView):
    "Real Estate Cron Task"
    __name__ = 'real_estate.cron_task'

    re_accounting = fields.Many2One('real_estate.re_accounting',
        'Real Estate Accounting', required=True, ondelete='CASCADE')
    task = fields.Selection('get_tasks', 'Task', required=True, sort=False)
    valid_from = fields.Date('Valid From',
        help="The task never runs before this date. If left empty, no "
             "lower bound applies. If the task has never run yet and "
             "today is already past this date, it becomes due right away "
             "(using today, not this date, as its first run). For "
             "'Interval (Months)' scheduling, this date also anchors the "
             "day-of-month of every recurrence - e.g. 15.03.2026 with "
             "Interval (Months) = 1 runs on 15.03., 15.04., 15.05., ... "
             "and stays aligned to the 15th even if a run is delayed.")
    valid_until = fields.Date('Valid Until',
        help="If set and today is after this date, the task no longer "
             "runs - the row stays configured, it is just no longer "
             "executed. If left empty, no upper bound applies.")
    interval_days = fields.Integer('Interval (Days)',
        states={'readonly': Bool(Eval('schedule_day_of_month'))
            | Bool(Eval('interval_months'))},
        help="The task is run again only after at least this many days "
             "have passed since its last run (checked daily). Ignored if "
             "'Interval (Months)' or 'Run on Day of Month' is set. Not "
             "required if one of those two is set instead.")
    interval_months = fields.Integer('Interval (Months)',
        states={'readonly': Bool(Eval('schedule_day_of_month'))},
        help="Alternative to 'Interval (Days)' for longer, calendar-based "
             "intervals (e.g. 6 for a half-yearly run): the task is run "
             "again once at least this many calendar months have passed "
             "since its last run. If 'Valid From' is also set, "
             "recurrences fall on its exact day-of-month (see 'Valid "
             "From'); otherwise months are counted as a plain year/month "
             "difference to the last run, without day-of-month alignment. "
             "Takes priority over 'Interval (Days)' if set. Ignored if "
             "'Run on Day of Month' is set.")
    schedule_day_of_month = fields.Integer('Run on Day of Month',
        help="If set, the task runs (at most) once a month, on or after "
             "this calendar day (1-31, capped to the last day of shorter "
             "months) - instead of following 'Interval (Days)'/'Interval "
             "(Months)'. Used e.g. by 'Book Contract Cash Flow' to book on "
             "a fixed day such as the 15th.")
    horizon_months_ahead = fields.Integer('Booking Horizon (Months Ahead)',
        states={'invisible': Eval('task') != 'book_contract_cash_flow'},
        help="Used by 'Book Contract Cash Flow': books everything due up "
             "to the end of the month that is this many months after the "
             "run date - e.g. 1 run on 15.07 books due items up to "
             "31.08.")
    invoice_state = fields.Selection([
        ('draft', 'Draft'),
        ('posted', 'Posted'),
        ], 'Invoice State', sort=False,
        states={'invisible': Eval('task') != 'book_contract_cash_flow'},
        help="Used by 'Book Contract Cash Flow'.\n"
             "Draft: invoices are saved as draft.\n"
             "Posted: invoices are posted immediately after creation.")
    future_contracts_horizon_days = fields.Integer(
        'Future Contracts Horizon (Days Ahead)',
        states={'invisible': Eval('task') != 'update_contract_cash_flow'},
        help="Used by 'Update Contract Cash Flow' to decide which "
             "not-yet-started contracts to include in a given run: a "
             "contract is included once its start date is within this "
             "many days from the run date. Already-running or already-"
             "ended contracts are unaffected by this value - they are "
             "always included or excluded regardless. Note this does NOT "
             "control how far ahead cash flow itself is recalculated - "
             "that is always exactly 1 year from today (see "
             "contract_term.py:_re_calc_year), fixed and not configurable "
             "here.")
    last_run = fields.Date('Last Run', states={'readonly': True})
    active = fields.Boolean('Active')

    name = fields.Function(fields.Char('Name'), 'on_change_with_name')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        t = cls.__table__()
        cls._sql_constraints = [
            ('re_accounting_task_unique',
                Unique(t, t.re_accounting, t.task),
                'real_estate.msg_cron_task_unique'),
            ]

    @classmethod
    def validate(cls, tasks):
        super().validate(tasks)
        for task in tasks:
            if (task.schedule_day_of_month is not None
                    and not (1 <= task.schedule_day_of_month <= 31)):
                raise ValidationError(gettext(
                    'real_estate.msg_cron_task_invalid_day',
                    name=task.rec_name))
            if task.interval_months is not None and task.interval_months < 1:
                raise ValidationError(gettext(
                    'real_estate.msg_cron_task_invalid_interval_months',
                    name=task.rec_name))
            if (task.interval_days is None and task.interval_months is None
                    and task.schedule_day_of_month is None):
                raise ValidationError(gettext(
                    'real_estate.msg_cron_task_no_schedule',
                    name=task.rec_name))
            if (task.valid_from and task.valid_until
                    and task.valid_until < task.valid_from):
                raise ValidationError(gettext(
                    'real_estate.msg_cron_task_valid_until_before_from',
                    name=task.rec_name))

    @classmethod
    def default_active(cls):
        return True

    @classmethod
    def default_horizon_months_ahead(cls):
        return 1

    @classmethod
    def default_invoice_state(cls):
        return 'draft'

    @classmethod
    def default_future_contracts_horizon_days(cls):
        return 60

    @classmethod
    def get_tasks(cls):
        return [
            ('update_contract_status', 'Update Contract Status'),
            ('update_contract_cash_flow', 'Update Contract Cash Flow'),
            ('book_contract_cash_flow', 'Book Contract Cash Flow'),
            ('update_option_rate', 'Update Option Rate'),
        ]

    @fields.depends('task')
    def on_change_with_name(self, name=None):
        return dict(self.get_tasks()).get(self.task, self.task or '')
