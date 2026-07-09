'Billing Unit Wizards'
from trytond.model import ModelView, fields
from trytond.model.exceptions import ValidationError
from trytond.i18n import gettext
from trytond.pool import Pool
from trytond.transaction import Transaction
from trytond.pyson import Eval
from trytond.wizard import (
    Button, StateTransition, StateView, Wizard)
from trytond.transaction import check_access, without_check_access

import datetime
import calendar


#**********************************************************************
class BillingUnitStart(ModelView):
    'Billing Unit - Start'
    __name__ = 'real_estate.billing_unit.start'

    date = fields.Date('to Date', required=True)
    company = fields.Many2One('company.company', 'Company', required=True)
    invoice_date = fields.Date('Invoice Date', required=True)
    invoice_date_in_past = fields.Boolean('Invoice Date in Past', readonly=True)
    invoice_state = fields.Selection([
        ('draft', 'Draft'),
        ('posted', 'Posted'),
        ], 'Invoice State')
    execute_in_queue = fields.Boolean('Execute in queue',
        help="If checked, billing will be processed in the background queue.")
    propertys = fields.Many2Many(
        'real_estate.base_object', None, None, 'Filter Properties',
        domain=[
            ('company', '=', Eval('company', -1)),
            ('type', '=', 'property'),
        ],
    )
    billing_units = fields.Many2Many(
        'real_estate.billing_unit', None, None, 'Filter Billing Units',
        help="Optional: restrict billing to these billing units. "
             "With collective billing active, all billing units of the "
             "same property and start date are always processed together.",
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
        last_day = calendar.monthrange(today.year, today.month)[1]
        return datetime.date(today.year, today.month, last_day)

    @staticmethod
    def default_company():
        user = Pool().get('res.user')(Transaction().user)
        return user.company.id if user.company else None

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

    @classmethod
    def default_propertys(cls):
        context = Transaction().context
        active_id = context.get('active_id')
        active_model = context.get('active_model')
        if active_id and active_model == 'real_estate.base_object':
            return [active_id]
        return []

    @classmethod
    def default_billing_units(cls):
        context = Transaction().context
        active_id = context.get('active_id')
        active_model = context.get('active_model')
        if active_id and active_model == 'real_estate.billing_unit':
            return [active_id]
        return []


#**********************************************************************
class BillingUnitConfirm(ModelView):
    'Billing Unit - Confirm'
    __name__ = 'real_estate.billing_unit.confirm'

    billing_units_count = fields.Integer('Matching Billing Units', readonly=True)
    date = fields.Date('Up to Date', readonly=True)
    invoice_state = fields.Char('Invoice State', readonly=True)
    execute_in_queue = fields.Boolean('Execute in Queue', readonly=True)
    n_properties = fields.Integer('Properties Filter', readonly=True)
    n_billing_units = fields.Integer('Billing Units Filter', readonly=True)


#**********************************************************************
class BillingUnitResult(ModelView):
    'Billing Unit - Result'
    __name__ = 'real_estate.billing_unit.result'

    billing_units_count = fields.Integer('Billing Units', readonly=True)
    mode = fields.Char('Mode', readonly=True)
    message = fields.Text('Details', readonly=True)


#**********************************************************************
class BillingUnitWizard(Wizard):
    'Billing Unit Wizard'
    __name__ = 'real_estate.billing_unit.wizard'

    start = StateView('real_estate.billing_unit.start',
        'real_estate.billing_unit_start_view_form', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('OK', 'confirm', 'tryton-ok', True),
        ])
    confirm = StateView('real_estate.billing_unit.confirm',
        'real_estate.billing_unit_confirm_view_form', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('Process', 'do_billing', 'tryton-ok', True),
        ])
    do_billing = StateTransition()
    result = StateView('real_estate.billing_unit.result',
        'real_estate.billing_unit_result_view_form', [
            Button('Close', 'end', 'tryton-ok', True),
        ])

    def _get_billing_unit_ids(self):
        """Return explicit BU id set from start.billing_units, or None if not set."""
        if self.start.billing_units:
            return {bu.id for bu in self.start.billing_units}
        return None

    def _resolve_property_ids(self, bu_id_filter):
        """Resolve property IDs from explicit BU filter or domain search."""
        pool = Pool()
        BillingUnit = pool.get('real_estate.billing_unit')

        if bu_id_filter is not None:
            units = BillingUnit.browse(list(bu_id_filter))
        else:
            domain = [('state', '=', 'ready_for_billing')]
            if self.start.propertys:
                domain.append(('property', 'in',
                    [p.id for p in self.start.propertys]))
            if self.start.date:
                domain.append(('start_date', '<=', self.start.date))
            units = BillingUnit.search(domain)

        prop_ids = list({bu.property.id for bu in units if bu.property})
        return prop_ids, len(units)

    def default_confirm(self, fields):
        invoice_labels = {'draft': 'Draft', 'posted': 'Posted'}
        bu_id_filter = self._get_billing_unit_ids()
        prop_ids, count = self._resolve_property_ids(bu_id_filter)
        return {
            'billing_units_count': count,
            'date': self.start.date,
            'invoice_state': invoice_labels.get(
                self.start.invoice_state or 'draft',
                self.start.invoice_state or 'draft'),
            'execute_in_queue': self.start.execute_in_queue,
            'n_properties': len(self.start.propertys) if self.start.propertys else 0,
            'n_billing_units': len(self.start.billing_units) if self.start.billing_units else 0,
        }

    @without_check_access
    def transition_do_billing(self):
        pool = Pool()
        BaseObject = pool.get('real_estate.base_object')
        with check_access():
            bu_id_filter = self._get_billing_unit_ids()
            prop_ids, count = self._resolve_property_ids(bu_id_filter)

            if prop_ids:
                BaseObject.call_billing(
                    prop_ids,
                    list(bu_id_filter) if bu_id_filter is not None else None,
                    self.start.execute_in_queue,
                    self.start.invoice_state or 'draft',
                    self.start.invoice_date)

            self.result.billing_units_count = count
            if count == 0:
                self.result.mode = 'No matching billing units found'
                self.result.message = (
                    'No billing units in state "Ready for Billing" matched '
                    f'the selected filters (up to {self.start.date}).')
            elif self.start.execute_in_queue:
                self.result.mode = 'Queued'
                self.result.message = (
                    f'{count} billing unit(s) queued for background processing.')
            else:
                self.result.mode = 'Completed'
                self.result.message = (
                    f'{count} billing unit(s) processed.')
        return 'result'

    def default_result(self, fields):
        return {
            'billing_units_count': self.result.billing_units_count,
            'mode': self.result.mode,
            'message': self.result.message,
        }
