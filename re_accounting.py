'Real Estate Accounting Configuration'
from trytond.model import ModelSQL, ModelView, fields

from . import base_object


#**********************************************************************
class ReAccounting(base_object.re_sequence_ordered(), ModelSQL, ModelView):
    "Real Estate Accounting Configuration"
    __name__ = 'real_estate.re_accounting'

    name = fields.Char('Name', required=True)

    re_account_allocation_by_owner = fields.Many2One(
        'account.account', 'Vacancy Cost Account',
        domain=[
            ('closed', '!=', True),
            ],
        help="Account for vacancy cost postings (debit and credit side).")

    re_journal_billing = fields.Many2One(
        'account.journal', 'Operating Cost Settlement Journal',
        domain=[
            ('type', 'in', ('revenue', 'expense', 'general')),
            ],
        help="Journal used for direct GL postings in vacancy settlements.")

    re_payment_term_billing = fields.Many2One(
        'account.invoice.payment_term', 'Operating Cost Billing Payment Term',
        help="Default payment term for operating cost settlement invoices, "
             "used when the contract itself has no payment term set.")

    create_moves_horizon_days = fields.Integer(
        'Move Creation Horizon (Days)',
        help="Number of days ahead of today the 'Update Contract Cash "
             "Flow' cron task recalculates postings for.")

    cron_tasks = fields.One2Many('real_estate.cron_task', 're_accounting',
        'Cron Tasks')

    @classmethod
    def default_sequence(cls):
        return 10

    @classmethod
    def default_create_moves_horizon_days(cls):
        return 60

    @classmethod
    def default_name(cls):
        return 'Real Estate Accounting'
