'Option Rate Update Wizard'
from trytond.model import ModelView, fields
from trytond.pool import Pool
from trytond.pyson import Eval
from trytond.transaction import Transaction
from trytond.wizard import Button, StateTransition, StateView, Wizard


#**********************************************************************
class OptionRateUpdateStart(ModelView):
    'Option Rate Update - Start'
    __name__ = 'real_estate.option_rate_update.start'

    company = fields.Many2One('company.company', 'Company', required=True)
    base_objects = fields.Many2Many(
        'real_estate.base_object', None, None, 'Base Objects',
        domain=[
            ('company', '=', Eval('company', -1)),
            ('type', 'in', ('property', 'building', 'land', 'object')),
            ],
        help="Selected properties/buildings/land are expanded to include "
             "their building/land/rental object descendants. If left "
             "empty, all properties of the company are selected.")
    cutoff_date = fields.Date('Cut-off Date', required=True,
        help="The new option rate is dated on the first day of this "
             "month.")

    @staticmethod
    def default_company():
        User = Pool().get('res.user')
        user = User(Transaction().user)
        return user.company.id if user.company else None

    @staticmethod
    def default_cutoff_date():
        return Pool().get('ir.date').today()


#**********************************************************************
class OptionRateUpdateConfirm(ModelView):
    'Option Rate Update - Confirm'
    __name__ = 'real_estate.option_rate_update.confirm'

    cutoff_date = fields.Date('Cut-off Date', readonly=True)
    effective_date = fields.Date('Effective Date', readonly=True)
    n_base_objects = fields.Integer('Base Objects Selected', readonly=True)
    n_expanded = fields.Integer('Total Objects to Process', readonly=True)


#**********************************************************************
class OptionRateUpdateResult(ModelView):
    'Option Rate Update - Result'
    __name__ = 'real_estate.option_rate_update.result'

    n_created = fields.Integer('Created', readonly=True)
    n_updated = fields.Integer('Updated', readonly=True)
    n_unchanged = fields.Integer('Unchanged', readonly=True)
    n_skipped = fields.Integer('Skipped', readonly=True)
    message = fields.Text('Details', readonly=True)


#**********************************************************************
class OptionRateUpdateWizard(Wizard):
    'Option Rate Update Wizard'
    __name__ = 'real_estate.option_rate_update.wizard'

    start = StateView('real_estate.option_rate_update.start',
        'real_estate.option_rate_update_start_view_form', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('OK', 'confirm', 'tryton-ok', True),
        ])
    confirm = StateView('real_estate.option_rate_update.confirm',
        'real_estate.option_rate_update_confirm_view_form', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('Process', 'do_update', 'tryton-ok', True),
        ])
    do_update = StateTransition()
    result = StateView('real_estate.option_rate_update.result',
        'real_estate.option_rate_update_result_view_form', [
            Button('Close', 'end', 'tryton-ok', True),
        ])

    def _effective_selection(self):
        """Selection to process: the explicitly chosen base objects, or - if
        none is set - all properties of the selected company."""
        base_objects = list(self.start.base_objects)
        if not base_objects:
            BaseObject = Pool().get('real_estate.base_object')
            base_objects = BaseObject.search([
                ('type', '=', 'property'),
                ('company', '=', self.start.company.id),
                ])
        return base_objects

    def default_confirm(self, fields):
        pool = Pool()
        OptionRate = pool.get('real_estate.option_rate')
        base_objects = self._effective_selection()
        expanded = OptionRate._expand_selection(base_objects)
        return {
            'cutoff_date': self.start.cutoff_date,
            'effective_date': self.start.cutoff_date.replace(day=1),
            'n_base_objects': len(base_objects),
            'n_expanded': len(expanded),
        }

    def transition_do_update(self):
        pool = Pool()
        OptionRate = pool.get('real_estate.option_rate')
        base_objects = self._effective_selection()
        counts, log = OptionRate.process_update(
            base_objects, self.start.cutoff_date)
        self.result.n_created = counts['created']
        self.result.n_updated = counts['updated']
        self.result.n_unchanged = counts['unchanged']
        self.result.n_skipped = counts['skipped']
        self.result.message = '\n'.join(log)
        return 'result'

    def default_result(self, fields):
        return {
            'n_created': self.result.n_created,
            'n_updated': self.result.n_updated,
            'n_unchanged': self.result.n_unchanged,
            'n_skipped': self.result.n_skipped,
            'message': self.result.message,
        }
