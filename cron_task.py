'Real Estate Cron Task'
from trytond.model import ModelSQL, ModelView, Unique, fields


class CronTask(ModelSQL, ModelView):
    "Real Estate Cron Task"
    __name__ = 'real_estate.cron_task'

    re_accounting = fields.Many2One('real_estate.re_accounting',
        'Real Estate Accounting', required=True, ondelete='CASCADE')
    task = fields.Selection('get_tasks', 'Task', required=True, sort=False)
    interval_days = fields.Integer('Interval (Days)', required=True,
        help="The task is run again only after at least this many days "
             "have passed since its last run (checked daily).")
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
    def default_active(cls):
        return True

    @classmethod
    def default_interval_days(cls):
        return 1

    @classmethod
    def get_tasks(cls):
        return [
            ('terminate_expired',
                'Terminate Expired Fixed-Term Contracts'),
            ('create_moves_rolling', 'Rolling Move Creation'),
        ]

    @fields.depends('task')
    def on_change_with_name(self, name=None):
        return dict(self.get_tasks()).get(self.task, self.task or '')
