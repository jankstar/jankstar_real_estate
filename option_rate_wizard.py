'Option Rate Update Wizard'
from trytond.model import ModelView, fields
from trytond.pool import Pool
from trytond.wizard import Button, StateTransition, StateView, Wizard


#**********************************************************************
class OptionRateUpdateStart(ModelView):
    'Option Rate Update - Start'
    __name__ = 'real_estate.option_rate_update.start'

    base_objects = fields.Many2Many(
        'real_estate.base_object', None, None, 'Base Objects',
        domain=[('type', 'in', ('property', 'building', 'land', 'object'))],
        help="Selected properties/buildings/land are expanded to include "
             "their building/land/rental object descendants.")
    billing_units = fields.Many2Many(
        'real_estate.billing_unit', None, None, 'Billing Units',
        help="Selected billing units are expanded to include their "
             "settlement units.")
    settlement_units = fields.Many2Many(
        'real_estate.settlement_unit', None, None, 'Settlement Units')
    cutoff_date = fields.Date('Cut-off Date', required=True,
        help="The new option rate is dated on the first day of this "
             "month.")

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
    n_billing_units = fields.Integer('Billing Units Selected', readonly=True)
    n_settlement_units = fields.Integer(
        'Settlement Units Selected', readonly=True)
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

    def default_confirm(self, fields):
        pool = Pool()
        OptionRate = pool.get('real_estate.option_rate')
        expanded = OptionRate._expand_selection(
            list(self.start.base_objects),
            list(self.start.billing_units),
            list(self.start.settlement_units))
        return {
            'cutoff_date': self.start.cutoff_date,
            'effective_date': self.start.cutoff_date.replace(day=1),
            'n_base_objects': len(self.start.base_objects),
            'n_billing_units': len(self.start.billing_units),
            'n_settlement_units': len(self.start.settlement_units),
            'n_expanded': len(expanded),
        }

    def transition_do_update(self):
        pool = Pool()
        OptionRate = pool.get('real_estate.option_rate')
        counts, log = OptionRate.process_update(
            list(self.start.base_objects),
            list(self.start.billing_units),
            list(self.start.settlement_units),
            self.start.cutoff_date)
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
