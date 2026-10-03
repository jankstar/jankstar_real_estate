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

    receipt_days = fields.Integer("Receipt Days (Index Rent)",
        domain=[('receipt_days', '>=', 0)],
        help="Days from the declaration date to the expected receipt by "
             "the tenant - only a preview of the effective date of an "
             "index rent adjustment, the actual receipt has to be "
             "confirmed.")

    deposit_task_months = fields.Integer("Months until Deposit Settlement",
        domain=[('deposit_task_months', '>=', 0)],
        help="Months after the end of a contract (move-out) until the task "
             "'Settle deposit' of the move-out process is due.")

    re_payment_term_billing = fields.Many2One(
        'account.invoice.payment_term', 'Operating Cost Billing Payment Term',
        help="Default payment term for operating cost settlement invoices, "
             "used when the contract itself has no payment term set.")

    co2_landlord_share_commercial = fields.Numeric(
        'CO2 Landlord Share (Commercial) (%)', digits=(5, 2),
        domain=[
            ('co2_landlord_share_commercial', '>=', 0),
            ('co2_landlord_share_commercial', '<=', 100),
            ],
        help="Default CO2 cost landlord share (0-100%) for commercial "
             "properties, which are not covered by the residential "
             "10-tier distribution model (real_estate.co2_emission_share).")

    cron_tasks = fields.One2Many('real_estate.cron_task', 're_accounting',
        'Cron Tasks')

    @classmethod
    def default_sequence(cls):
        return 10

    @classmethod
    def default_name(cls):
        return 'Real Estate Accounting'

    @classmethod
    def default_receipt_days(cls):
        return 3

    @classmethod
    def default_deposit_task_months(cls):
        return 6
