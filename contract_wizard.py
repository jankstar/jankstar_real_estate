'Contract Wizards and Reports'
from trytond.model import ModelView, fields
from trytond.pool import Pool
from trytond.transaction import Transaction
from trytond.pyson import Eval
from trytond.wizard import (
    Button, StateTransition, StateView, Wizard)
from trytond.report import Report
from trytond.transaction import check_access, without_check_access

from dateutil.relativedelta import relativedelta

import re
import datetime
import calendar


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
        self.start.contract.save()
        Contract._refresh_occupancy_for_contracts([self.start.contract])
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
class CreateMovesStart(ModelView):
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
    def default_execute_in_queue():
        return True


#**********************************************************************
class CreateMoves(Wizard):
    """Wizard to create moves for contracts until given date, with option to 
    re-calculate next document/due date by rhythm and last posting date before move creation"""
    __name__ = 'real_estate.contract.create_moves'
    start = StateView('real_estate.contract.create_moves.start',
        'real_estate.contract_create_moves_start_view_form', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('OK', 'create_moves', 'tryton-ok', True),
            ])
    create_moves = StateTransition()

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
                contract_ids = [c.id for c in self.start.contracts]
                search_domain.append(('id', 'in', contract_ids))

            Contract = pool.get('real_estate.contract')
            contract_ids = Contract.search(search_domain)

            if contract_ids:
                Contract.call_create_moves(
                    contract_ids, self.start.date, self.start.action,
                    self.start.execute_in_queue, self.start.invoice_state or 'draft',
                    self.start.invoice_date)
        return 'end'


#**********************************************************************
class ContractReport(Report):
    "Contract Context"
    __name__ = 'real_estate.contract.report'

    @classmethod
    def _format(cls, value):
        if value is None:
            return ''
        if type(value) == str:
            return value
        if type(value) == bool:
            return str(value)
        if type(value) == int:
            return str(value)
        if type(value) == float:
            return cls.format_number(value, None)
        if type(value) == datetime.date:
            return cls.format_date(value)
        if type(value) == datetime.datetime:
            return cls.format_datetime(value)
        return value

    @classmethod
    def get_context(cls, records, header, data):
        context = super().get_context(records, header, data)
        context['_format'] = cls._format
        return context

#**********************************************************************
class ContractAnnex4Report(Report):
    "Contract Annex 4 – Betriebskostenaufstellung"
    __name__ = 'real_estate.contract.annex4.report'

    @classmethod
    def _format(cls, value):
        if value is None:
            return ''
        if type(value) == str:
            return value
        if type(value) == bool:
            return str(value)
        if type(value) == int:
            return str(value)
        if type(value) == float:
            return cls.format_number(value, None)
        if type(value) == datetime.date:
            return cls.format_date(value)
        if type(value) == datetime.datetime:
            return cls.format_datetime(value)
        return value

    @classmethod
    def _allocation_label(cls, su):
        rule = su.allocation_rule or 'no_allocation'
        if rule == 'allocation_by_measurement' and su.m_type:
            return su.m_type.name
        elif rule == 'allocation_by_consumption':
            if su.meter_unit:
                return 'nach Verbrauch (%s, HeizkostenV)' % su.meter_unit.symbol
            return 'nach Verbrauch (HeizkostenV)'
        elif rule == 'allocation_per_rental_unit':
            return 'je Wohneinheit'
        return '—'

    @classmethod
    def _betrKV_nr(cls, comment):
        if not comment:
            return ''
        m = re.search(r'Nr\.\s*(\d+[a-z]?)', comment)
        return ('Nr. ' + m.group(1)) if m else ''

    @classmethod
    def get_context(cls, records, header, data):
        context = super().get_context(records, header, data)
        pool = Pool()
        BillingUnit = pool.get('real_estate.billing_unit')
        record = context['record']
        context['_format'] = cls._format

        bk_groups = []
        if record.property:
            billing_units = BillingUnit.search([
                ('property', '=', record.property.id),
                ('state', 'not in', ['draft', 'billed']),
            ], order=[('start_date', 'DESC')], limit=1)

            if billing_units:
                bu = billing_units[0]
                sus = [
                    su for su in bu.settlement_units
                    if su.type and not su.type.no_print
                ]
                sus.sort(key=lambda su: (
                    su.type.category_group.sequence
                    if su.type.category_group else 9999,
                    su.type.sequence or 0,
                ))

                current_grp_name = None
                for su in sus:
                    grp = su.type.category_group
                    grp_name = grp.name if grp else '(Sonstige)'
                    if grp_name != current_grp_name:
                        bk_groups.append({'name': grp_name, 'rows': []})
                        current_grp_name = grp_name
                    bk_groups[-1]['rows'].append({
                        'betrKV_nr': cls._betrKV_nr(su.type.comment),
                        'name': su.type.name or '',
                        'allocation': cls._allocation_label(su),
                    })

        context['bk_groups'] = bk_groups
        return context
