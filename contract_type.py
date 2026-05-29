'Contract Type and Term Type'
from trytond.model import (sequence_ordered,
    DeactivableMixin, ModelSQL, ModelView, fields, Unique)
from trytond.pool import Pool
from trytond.pyson import Eval, If
from trytond import backend
from trytond.modules.product import price_digits

from . import base_object
import logging

logger = logging.getLogger(__name__)


#**********************************************************************
class ContractTypeTax(ModelSQL):
    __name__ = 'real_estate.contract.type.tax'

    c_type = fields.Many2One(
        'real_estate.contract.type', "Contract Type",
        ondelete='RESTRICT', required=True)

    tax = fields.Many2One('account.tax', 'Tax', ondelete='RESTRICT',
            required=True)

    @classmethod
    def __setup__(cls):
        super().__setup__()
        t = cls.__table__()
        cls._sql_constraints += [
            ('contracterm_type_tax_unique', Unique(t, t.c_type, t.tax),
                'real_estate_contract.msg_contracterm_type_tax_unique'),
            ]

    @classmethod
    def __register__(cls, module):
        backend.TableHandler.table_rename(
            'contrac_type_tax', cls._table)
        super().__register__(module)


#**********************************************************************
class ContractType(DeactivableMixin, base_object.re_sequence_ordered(), ModelSQL, ModelView):
    __name__ = 'real_estate.contract.type'

    name = fields.Char("Name", required=True, translate=True)
    types_of_use = fields.MultiSelection(
            'get_term_types_of_use', "Types",
            help="The type of object which can use this contract type.")

    invoice_type = fields.Selection('get_invoice_types',
                                    "Invoice Type", required=True,)

    account = fields.Many2One('account.account', 'Party Account',
        domain=[
            If(Eval('invoice_type') == 'out',
                ('type.receivable', '=', True),
                ('type.payable', '=', True)),
            ('closed', '!=', True),
            ('party_required', '=', True),
            ],
        help="Party account for invoice headers. "
             "Overrides the party's default receivable/payable account.")

    taxes = fields.Many2Many('real_estate.contract.type.tax',
        'c_type', 'tax', 'Default Term Taxes',
        order=[('tax.sequence', 'ASC'), ('tax.id', 'ASC')],
        domain=[('parent', '=', None),
                ['OR',
                    ('group', '=', None),
                    ('group.kind', 'in',
                       If(Eval('invoice_type') == 'out',
                           ['sale', 'both'],
                           ['purchase', 'both']))
                ],
            ],
        )

    account_journal = fields.Many2One('account.journal', 'Journal',
        domain=[('type', 'in', ('revenue', 'expense'))],
        required=True)

    account_billing_unit = fields.Many2One('account.account',
        'Operating Cost Clearing Account',
        domain=[
            ('closed', '!=', True),
            ('company', '=', Eval('context', {}).get('company', -1)),
            ],
        help="Credit account for operating costs in the settlement invoice.")

    prefix = fields.Char("Prefix", required=True)

    start_number = fields.Integer("Start Number", help='start contract number', required=True)

    step_item = fields.Integer("Step Item", help='step for item sequence', required=True)
    step_term = fields.Integer("Step Term", help='step for term sequence', required=True)

    mark = fields.Char("Mark", help='Periodic posting Mark')

    occupancy = fields.Boolean("Occupancy",
        help='If set, only one active contract per object is allowed at a time.')

    @classmethod
    def default_step_item(cls):
        return 10

    @classmethod
    def default_step_term(cls):
        return 10

    @classmethod
    def get_term_types_of_use(cls):
        pool = Pool()
        BaseObject = pool.get('real_estate.base_object')
        return BaseObject.fields_get(['type_of_use'])['type_of_use']['selection']

    @classmethod
    def get_invoice_types(cls):
        pool = Pool()
        AccountInvoice = pool.get('account.invoice')
        return AccountInvoice.fields_get(['type'])['type']['selection']


#**********************************************************************
class ContractTermType(DeactivableMixin, base_object.re_sequence_ordered(), ModelSQL, ModelView):
    __name__ = 'real_estate.contract.term.type'
    __rec_name__ = 'compute_name'

    name = fields.Char("Name", required=True, translate=True)
    types_of_use = fields.MultiSelection(
            'get_term_types_of_use', "Types",
            help="The type of object which can use this contract term type.")

    m_type = fields.Many2One('real_estate.measurement.type', "Measurement Type",
        )

    default_quantity = fields.Float('Default Quantity', digits=price_digits,)

    account = fields.Many2One('account.account', 'Account',
        domain=['OR',
                ('type.revenue', '=', True),
                ('type.expense', '=', True),
                ('type.debt', '=', True),
                ('type.deposit', '=', True),
                ])

    rhythm = fields.Integer("Rhythm (count)",)

    rhythm_type = fields.Selection([
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('annually', 'Annually'),
        ('one_time', 'One Time '),
        ], "Rhythm Type",
        sort=False,
        required=True,
        help="Defines the frequency of the term. 30 days for monthly, 90 days for quarterly, 365 days for annually."
    )

    rhythm_start = fields.Selection([
        (None, 'first day of month'),
        ('term_start', 'Day of term valid from date'),
        ('15th_month', '15th day of month'),
        ('month_end', 'last day of month'),
        ], "Rhythm Start",
        sort=False,
    )

    compute_name = fields.Function(fields.Char("Description"),
                                    'on_change_with_compute_name',
                                    searcher='compute_name_search'
                                    )

    @classmethod
    def default_rhythm(cls):
        return 1

    @classmethod
    def default_rhythm_type(cls):
        return 'monthly'

    @classmethod
    def get_term_types_of_use(cls):
        pool = Pool()
        BaseObject = pool.get('real_estate.base_object')
        return BaseObject.fields_get(['type_of_use'])['type_of_use']['selection']

    @fields.depends('name', 'm_type', 'sequence')
    def on_change_with_compute_name(self, name=None):
        if self.sequence:
            if self.m_type:
                return f'{self.sequence} - {self.name}  ( {self.m_type.name} )'
            else:
                return f'{self.sequence} - {self.name}  ( - )'
        return f' - {self.name}  ( - )'

    @classmethod
    def compute_name_search(cls, name, clause):
        if clause[1].startswith('!') or clause[1].startswith('not '):
            bool_op = 'AND'
        else:
            bool_op = 'OR'

        return [bool_op,
            ('name',) + tuple(clause[1:]),
            ('m_type.name',) + tuple(clause[1:]),
        ]
