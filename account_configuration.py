'Account Configuration extension for Real Estate'
from trytond.model import ModelSQL, fields
from trytond.modules.company.model import CompanyValueMixin
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Eval


#**********************************************************************
class AccountConfigurationRealEstate(ModelSQL, CompanyValueMixin):
    "Account Configuration Real Estate Values"
    __name__ = 'account.configuration.real_estate'

    re_account_allocation_by_owner = fields.Many2One(
        'account.account', 'Vacancy Cost Account',
        domain=[
            ('closed', '!=', True),
            ('company', '=', Eval('company', -1)),
            ])

    re_journal_billing = fields.Many2One(
        'account.journal', 'Operating Cost Settlement Journal',
        domain=[
            ('type', 'in', ('revenue', 'expense', 'general')),
            ])

    re_payment_term_billing = fields.Many2One(
        'account.invoice.payment_term', 'Operating Cost Billing Payment Term')


#**********************************************************************
class AccountConfiguration(metaclass=PoolMeta):
    "Account Configuration extension for Real Estate"
    __name__ = 'account.configuration'

    re_account_allocation_by_owner = fields.MultiValue(fields.Many2One(
        'account.account', 'Vacancy Cost Account',
        domain=[
            ('closed', '!=', True),
            ('company', '=', Eval('context', {}).get('company', -1)),
            ],
        help="Account for vacancy cost postings (debit and credit side)."))

    re_journal_billing = fields.MultiValue(fields.Many2One(
        'account.journal', 'Operating Cost Settlement Journal',
        domain=[
            ('type', 'in', ('revenue', 'expense', 'general')),
            ],
        help="Journal used for direct GL postings in vacancy settlements."))

    re_payment_term_billing = fields.MultiValue(fields.Many2One(
        'account.invoice.payment_term', 'Operating Cost Billing Payment Term',
        help="Default payment term for operating cost settlement invoices, "
             "used when the contract itself has no payment term set."))

    @classmethod
    def multivalue_model(cls, field):
        pool = Pool()
        if field in {'re_account_allocation_by_owner', 're_journal_billing',
                're_payment_term_billing'}:
            return pool.get('account.configuration.real_estate')
        return super().multivalue_model(field)
