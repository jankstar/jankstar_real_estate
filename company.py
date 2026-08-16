'Company extension for Real Estate'
from trytond.model import fields
from trytond.pool import PoolMeta


#**********************************************************************
class Company(metaclass=PoolMeta):
    "Company extension for Real Estate"
    __name__ = 'company.company'

    re_accounting = fields.Many2One('real_estate.re_accounting',
        'Real Estate Accounting',
        help="Real estate specific accounting configuration: vacancy cost "
             "account, operating cost settlement journal, and default "
             "payment term for operating cost billing.")
