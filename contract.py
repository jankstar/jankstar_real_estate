from trytond.model import (sequence_ordered, 
    DeactivableMixin, Index, ModelSQL, ModelView, Workflow, fields, Unique, Check,
    sum_tree, tree)
from trytond.model.exceptions import ValidationError
from trytond.i18n import gettext
from trytond.cache import Cache
from trytond.report import Report
from trytond.pool import Pool
from trytond.transaction import Transaction
from trytond.pyson import Bool, Eval, If, PYSONEncoder, TimeDelta, Equal
from trytond.pool import PoolMeta
from trytond import backend, config
from trytond.i18n import lazy_gettext
from trytond.modules.company import CompanyReport
from trytond.modules.product import price_digits
from sql import Column
from trytond.modules.currency.fields import Monetary
from trytond.modules.account.tax import TaxableMixin
from trytond.tools import (
    cached_property, firstline, grouped_slice, reduce_ids, slugify,
    sqlite_apply_types)

from sql import Null
from sql.aggregate import Sum
from sql.conditionals import Coalesce

from dateutil.relativedelta import relativedelta

from . import base_object
import logging
from decimal import Decimal


logger = logging.getLogger(__name__)


class Quantitative(fields.Numeric):
    """
    Define a numeric field with unit (``decimal``).
    """
    def __init__(self, string='', unit=None, digits=None, help='',
            required=False, readonly=False, domain=None, states=None,
            on_change=None, on_change_with=None, depends=None, context=None,
            loading='eager'):
        '''
        :param unit: the name of the Many2One field which stores
            the unit
        '''
        if unit:
            if depends is None:
                depends = set()
            else:
                depends = set(depends)
            depends.add(unit)
        super().__init__(string=string, digits=digits, help=help,
            required=required, readonly=readonly, domain=domain, states=states,
            on_change=on_change, on_change_with=on_change_with,
            depends=depends, context=context, loading=loading)
        self.unit = unit

    def definition(self, model, language):
        definition = super().definition(model, language)
        definition['symbol'] = self.unit
        definition['quantitative'] = True
        return definition


#**********************************************************************
class Contract(Workflow, DeactivableMixin, base_object.re_sequence_ordered(), ModelSQL, ModelView):
    "Base Object - base class for contracts"
    __name__ = 'real_estate.contract'
    __rec_name__ = 'compute_name'

    company = fields.Many2One('company.company', "Company", required=True, ondelete='CASCADE',)
    property = fields.Many2One('real_estate.base_object', "Property", required=True, ondelete='CASCADE',
        states={
            'readonly': ( (Eval('state') != 'draft') ),
            'invisible': ( (Bool(Eval('c_type')) == False)),
            },                               
        domain=[
            ('company', '=', Eval('company', -1)),
            ('type', '=', 'property' ),],)

   
    type_of_use = fields.Selection('get_term_types_of_use',
        "Type of Use", 
        required=True, 
        sort=False,  
        states={
            'readonly': ( (Eval('state') != 'draft') | ( (Bool(Eval('c_type')) != False))),
            }
        )

    c_type = fields.Many2One(
        'real_estate.contract.type', "Contract Type", required=True,
        domain=[('types_of_use', 'in', Eval('type_of_use'))],
        states={
            'readonly': ( (Eval('state') != 'draft')),
            'invisible': ( (Bool(Eval('type_of_use', 0)) == False)),
            }
       )    


    currency = fields.Many2One('currency.currency',
        'Currency', 
        states={
            'readonly': True,
            },
            required=True,)

    start_date = fields.Date('Start Date', 
        states={
            'readonly': (Eval('terms', [0]) | (Eval('state') != 'draft')),
            },
        required=True,
        domain=[If(Bool(Eval('end_date')), ('start_date', '<=', Eval('end_date', None)),())],
        )
    
    end_date = fields.Date('End Date',
        states={
            'readonly': (Eval('terms', [0]) | (Eval('state') != 'draft')),
            },
        required=False,
        domain=[If(Bool(Eval('end_date')), ('end_date', '>=', Eval('start_date', None)),())],
        )
    
    contract_number = fields.Char("No",
        states={ 'readonly': True, })
    
    comment = fields.Text("Comment")

    date_of_signature = fields.Date('Date of Signature',)

    contractual_partner = fields.Many2One(
        'party.party', "Contractual Partner", required=True,
        states={
            'readonly': (Eval('terms', [0]) | (Eval('state') != 'draft')),
            },)
    invoice_address = fields.Many2One('party.address', 'Invoice Address',
        required=True, 
        #states=_states,
        domain=[('party', '=', Eval('contractual_partner', -1))])    

    payment_term = fields.Many2One(
        'account.invoice.payment_term', "Payment Term",
        ondelete='RESTRICT', 
        #states=_states
        )
    
    phone_partner = fields.Function(fields.Char("Phone Partner"),
        'get_phone_partner')

    compute_name = fields.Function(fields.Char("Name"), 
                                    'on_change_with_compute_name', 
                                    searcher='compute_name_search'
                                    )    

    state = fields.Selection([
            ('draft', 'Draft'),
            ('running', 'Running'),
            ('terminated', 'Terminated'),
            ], "State", sort=False,
            states={ 'readonly': True, },)
    
    items = fields.One2Many('real_estate.contract.item', 'contract', 'Items',
        order=[
            ('valid_from', 'ASC'),           # Primärsortierung
            ('valid_to', 'ASC NULLS LAST'),  # Sekundärsortierung
        ],
        states={
            'readonly': (Eval('state') != 'draft'),
            },
        )

    next_item_sequence = fields.Function(fields.Integer("Next Item Sequence",),
                                         'on_change_with_next_item_sequence',)

    terms = fields.One2Many('real_estate.contract.term', 'contract', 'Terms',
        order=[
            ('valid_from', 'ASC'),           # Primärsortierung
            ('sequence', 'ASC NULLS FIRST'),  # Sekundärsortierung
        ],
        states={            
            'readonly': ((Eval('items', []) == []) | (Eval('state') != 'draft')),
        },)
    
    next_term_sequence = fields.Function(fields.Integer("Next Term Sequence",),
                                         'on_change_with_next_term_sequence',)


    @classmethod
    def get_term_types_of_use(cls):
        pool = Pool()
        BaseObject = pool.get('real_estate.base_object')
        return BaseObject.fields_get(['type_of_use'])['type_of_use']['selection']

    @classmethod
    def default_company(cls):
        return Transaction().context.get('company')

    @staticmethod
    def default_state():
        return 'draft'
    
    @staticmethod
    def default_start_date():
        #first day of the current month
        return Pool().get('ir.date').today().replace(day=1)    

    @fields.depends('terms')
    def on_change_with_next_term_sequence(self, name=None):
        if self.terms and self.c_type:
            return (max(term.sequence for term in self.terms) % self.c_type.step_term ) + self.c_type.step_term
        return self.c_type.step_term if self.c_type else 1

    @fields.depends('items', 'c_type')
    def on_change_with_next_item_sequence(self, name=None):
        if self.items and self.c_type:
            return (max(item.sequence for item in self.items) % self.c_type.step_item ) + self.c_type.step_item
        return self.c_type.step_item if self.c_type else 1

    @fields.depends('contractual_partner', 'c_type')
    def on_change_contractual_partner(self, name=None):
        if self.contractual_partner:
            self.invoice_address = self.contractual_partner.address_get(type='invoice')
            #self.party_tax_identifier = self.contractual_partner.tax_identifier
            if self.c_type.invoice_type == 'out':
                #self.account = self.contractual_partner.account_receivable_used
                self.payment_term = self.contractual_partner.customer_payment_term
            elif self.c_type.invoice_type == 'in':
                #self.account = self.contractual_partner.account_payable_used
                self.payment_term = self.contractual_partner.supplier_payment_term
        else:
            self.invoice_address = None
            #self.account = None
            self.payment_term = None
            #self.party_tax_identifier = None


    @fields.depends('company')
    def on_change_with_currency(self, name=None):
        return self.company.currency if self.company else None


    @fields.depends('c_type', 'property', 'company')
    def on_change_with_sequence(self, name=None):
        if (self.sequence != None and self.sequence != 0):
            return self.sequence
        # Höchste Nummer + 1 für Vertragsart und Property
        if self.c_type != None and self.property != None and self.company != None:
            contracts = Pool().get('real_estate.contract').search([
                ('company', '=', self.company.id),
                ('c_type', '=', self.c_type.id),
                ('property', '=', self.property.id),
            ], order=[('sequence', 'DESC')], limit=1)

            return (contracts[0].sequence + 1 if contracts else 1)
        
        return 0

    @fields.depends('c_type', 'property', 'sequence')
    def on_change_with_contract_number(self, name=None):
        self.sequence = self.on_change_with_sequence() # ensure sequence is set
        if  self.c_type == None or self.property == None or not self.sequence:
            return f" - "        
        return f"{self.c_type.prefix}-{self.property.sequence}-{self.sequence}"
    
    @fields.depends('contract_number', 'contractual_partner')
    def on_change_with_compute_name(self, name=None):
        if not self.contract_number or not self.contractual_partner:
            return f" - "        
        return f"{self.contract_number} / {self.contractual_partner.name}"

    def get_address_partner(self, name=None):
        if self.contractual_partner:
            Party = Pool().get('party.party')
            party = Party(self.contractual_partner)
            if party and party.addresses: 
                return party.addresses[0].full_address.replace('\n', ' / ')
        return ''

    def get_phone_partner(self, name=None):
        if self.contractual_partner:
            Party = Pool().get('party.party')
            party = Party(self.contractual_partner)
            phone = party.contact_mechanism_get(types='phone')
            if phone:
                return phone.value.replace('\n', ' / ')
        return ''

    @classmethod
    def compute_name_search(cls, name, clause):
        if clause[1].startswith('!') or clause[1].startswith('not '):
            bool_op = 'AND'
        else:
            bool_op = 'OR'

        return [bool_op,
            ('contract_number',) + tuple(clause[1:]),
            ('contractual_partner.name',) + tuple(clause[1:]),
        ]   

#**********************************************************************
class ContractTypeTax(ModelSQL):
    __name__ = 'real_estate.contract.type.tax'
    c_type = fields.Many2One(
        'real_estate.contract.type', "Contract Type",
        ondelete='CASCADE', required=True)
    
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
        # Migration from 7.0: rename to standard name
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

    account = fields.Many2One('account.account', 'Party Account', required=True,
        domain=[
            If(Eval('invoice_type') == 'out',
                ('type.receivable', '=', True),
                ('type.payable', '=', True)),
            ('closed', '!=', True),
            ('party_required', '=', True),       #    
            ],
            )

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
    
    prefix = fields.Char("Prefix", required=True)

    start_number = fields.Integer("Start Number", help='start contract number',required=True)

    step_item = fields.Integer("Step Item", help='step for item sequence',required=True)
    step_term = fields.Integer("Step Term", help='step for term sequence',required=True)

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
class ContractTermLine(ModelSQL, ModelView):
    __name__ = 'real_estate.contract.term.line'
    
    term = fields.Many2One('real_estate.contract.term', 'Term', required=True,
        ondelete='CASCADE', readonly=True)
    date = fields.Date('Date', readonly=True)
    depreciation = Monetary(
        "Depreciation", currency='currency', digits='currency',
        required=True, readonly=True)
    acquired_value = Monetary(
        "Acquired Value", currency='currency', digits='currency',
        readonly=True)
    depreciable_basis = Monetary(
        "Depreciable Basis", currency='currency', digits='currency',
        readonly=True)
    actual_value = Monetary(
        "Actual Value", currency='currency', digits='currency', readonly=True)
    accumulated_depreciation = Monetary(
        "Accumulated Depreciation", currency='currency', digits='currency',
        readonly=True)
    move = fields.Many2One('account.move', 'Account Move', readonly=True)
    currency = fields.Function(fields.Many2One('currency.currency',
        'Currency'), 'on_change_with_currency')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls.__access__.add('term')
        cls._order.insert(0, ('date', 'ASC'))

    @fields.depends('term')
    def on_change_with_currency(self, name=None):
        return self.term.contract.currency if self.term else None
    
    

#**********************************************************************
class ContractItem(sequence_ordered(), ModelSQL, ModelView, metaclass=PoolMeta):
    "Contract Item"
    __name__ = 'real_estate.contract.item'
    __rec_name__ = 'name'
    
    contract = fields.Many2One('real_estate.contract', 'Contract', required=True,
         path='path', ondelete='CASCADE')
    object = fields.Many2One('real_estate.base_object', 'Object', required=True,
            domain=[('type', 'in', ('object',)),
                    ('type_of_use', '=', Eval('type_of_use', -1)),
                    ('property', '=', Eval('property', -1)),
                    ('company', '=', Eval('company', -1)),
                    ],)
    valid_from = fields.Date('Valide from', required=True)
    valid_to = fields.Date('Valid to')

    name = fields.Function(fields.Char("Name"), 
                                'on_change_with_name', 
                                searcher='compute_name_search')   
    
    property = fields.Function(fields.Many2One('real_estate.base_object','Property'),
        'on_change_with_property')

    company = fields.Function(fields.Many2One('company.company','Company'),
        'on_change_with_company')

    type_of_use = fields.Function(fields.Char("Type of Use"),
        'on_change_with_type_of_use')

    currency = fields.Function(fields.Many2One('currency.currency',
        'Currency'), 'on_change_with_currency')


    @fields.depends('contract', 'sequence')
    def on_change_with_sequence(self, name=None):
        if (self.sequence != None and self.sequence != 0):
            return self.sequence
        
        if self.contract != None and self.contract.next_item_sequence:
            return self.contract.next_item_sequence
        
        return self.contract.c_type.step_item if self.contract and self.contract.c_type else 1
    
    @fields.depends('object')
    def on_change_with_name(self, name=None):
        if self.object:
            return self.object.name + ' / ' + self.object.object_number
        return f" - "

    @fields.depends('contract', 'valid_from')
    def on_change_contract(self, name=None):
        if self.contract != None and self.valid_from == None:
            self.valid_from = self.contract.start_date
            
    @fields.depends('contract')
    def on_change_with_property(self, name=None):
        if self.contract:
            return self.contract.property
        return None
    
    @fields.depends('contract')
    def on_change_with_currency(self, name=None):
        return self.contract.currency if self.contract else None

    @fields.depends('contract')
    def on_change_with_company(self, name=None):
        if self.contract:
            return self.contract.company
        return None
    
    @fields.depends('contract')
    def on_change_with_type_of_use(self, name=None):
        if self.contract:
            return self.contract.type_of_use
        return None

    @classmethod
    def compute_name_search(cls, name, clause):
        if clause[1].startswith('!') or clause[1].startswith('not '):
            bool_op = 'AND'
        else:
            bool_op = 'OR'

        return [bool_op,
            ('object.name',) + tuple(clause[1:]),
            ('object.object_number',) + tuple(clause[1:]),
        ]   

#**********************************************************************
class ContractTermType(DeactivableMixin, base_object.re_sequence_ordered(), ModelSQL, ModelView):
    __name__ = 'real_estate.contract.term.type'
    __rec_name__ = 'compute_name'


    name = fields.Char("Name", required=True, translate=True)
    types_of_use = fields.MultiSelection(
            'geterm_types_of_use', "Types",
            help="The type of object which can use this contract term type.")    
    
    m_type = fields.Many2One('real_estate.measurement.type', "Measurement Type", 
        )
    
    default_quantity = fields.Float('Default Quantity',digits=price_digits,)

    account = fields.Many2One('account.account', 'Account',
        required=True,
        domain=['OR',
                ('type.revenue', '=', True), #Erträge (GuV)
                ('type.expense', '=', True), #Aufwand (GuV)
                ('type.debt', '=', True),    #Darlehen/Kredit (Bilanz) 
                ('type.deposit', '=', True), #Anzahlungen (Bilanz)
                #'AND',            
                #('closed', '!=', True),
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
    def geterm_types_of_use(cls):
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

#**********************************************************************
class ContractTermTax(ModelSQL):
    __name__ = 'real_estate.contract.term.tax'
    term = fields.Many2One(
        'real_estate.contract.term', "Contract Term",
        ondelete='CASCADE', required=True)
    
    tax = fields.Many2One('account.tax', 'Tax', ondelete='RESTRICT',
            required=True)

    @classmethod
    def __setup__(cls):
        super().__setup__()
        t = cls.__table__()
        cls._sql_constraints += [
            ('contracterm_term_tax_unique', Unique(t, t.term, t.tax),
                'real_estate_contract.msg_contracterm_term_tax_unique'),
            ]

    @classmethod
    def __register__(cls, module):
        # Migration from 7.0: rename to standard name
        backend.TableHandler.table_rename(
            'contrac_term_tax', cls._table)
        super().__register__(module)

#**********************************************************************
class ContractTerm(sequence_ordered(), ModelSQL, ModelView, TaxableMixin):
    "Contract Term"
    __name__ = 'real_estate.contract.term'
    __rec_name__ = 'name'
    
    contract = fields.Many2One('real_estate.contract', 'Contract', required=True,
         path='path', ondelete='CASCADE')

    name = fields.Function(fields.Char("Name"), 
                                'on_change_with_name', 
                                searcher='compute_name_search')   

    term_type = fields.Many2One(
        'real_estate.contract.term.type', "Term Type", required=True,
       )

    referenc_property = fields.Many2One('real_estate.contract.item', 'Reference Property',
            domain=[ ('contract', '=', Eval('contract', -1)),
                    ],)
                                        

    valid_from = fields.Date('Valide from', required=True)
    valid_to = fields.Date('Valid to',
         states={
            'readonly': ((Eval('rhythm', -1) == 0)),
            })
    
    last_posting_date = fields.Date('Last Posting Date', 
        states={'readonly': True,})
    last_document_date = fields.Date('Last Document Date', 
        states={'readonly': True,})

    next_document_date = fields.Date('Next Document Date', 
        states={'readonly': True,})
    next_due_date = fields.Date('Next Due Date', 
        states={'readonly': True,})

   
    rhythm = fields.Integer("Rhythm (count)",
        states={
            'invisible': (Eval('term_type', None) == None),
            },
        )

    rhythm_type = fields.Selection('get_rhythm_type', "Rhythm Type",
        sort=False,
        required=True,
        states={
            'invisible': (Eval('term_type', None) == None),
            },
        )

    property = fields.Function(fields.Many2One('real_estate.base_object','Property'),
        'on_change_with_property')

    company = fields.Function(fields.Many2One('company.company','Company'),
        'on_change_with_company')

    type_of_use = fields.Function(fields.Char("Type of Use"),
        'on_change_with_type_of_use')

    currency = fields.Function(fields.Many2One('currency.currency',
        'Currency'),
        'on_change_with_currency')

    invoice_type = fields.Function(fields.Char("Invoice Type"),
        'on_change_with_invoice_type')

    account = fields.Many2One('account.account', 'Account',
        ondelete='RESTRICT',
        states={
            'invisible': (Eval('term_type', None) == None),
            'readonly': True,
            },)
    
    quantity = Quantitative(
        "Quantity", unit='unit',digits='unit',
         states={
            'required': True,
            'readonly': (Eval('valid_to', None) != None),
            'invisible': (Eval('term_type', None) == None),
            })

    unit = fields.Many2One('product.uom', 'Unit', ondelete='RESTRICT',
        states={
            'invisible': (Eval('term_type', None) == None),
            'readonly': True,
            },)
    
    unit_price = Monetary(
        "Unit Price", currency='currency', digits=price_digits,
        states={
            'required': True,
            'readonly': (Eval('valid_to', None) != None),
            'invisible': (Eval('term_type', None) == None),
            })

    amount = fields.Function(Monetary(
            "Amount", currency='currency', digits='currency',
          states={
            'invisible': (Eval('term_type', None) == None),
            'readonly': True,
            },),'get_amount')

    untaxed_amount = fields.Function(Monetary(
            "Untaxed", currency='currency', digits='currency'),
        'get_amount_and_tax', )

    tax_amount = fields.Function(Monetary(
            "Tax", currency='currency', digits='currency'),
        'get_amount_and_tax', )

    total_amount = fields.Function(Monetary(
            "Total", currency='currency', digits='currency'),
        'get_amount_and_tax', )

    taxes = fields.Many2Many('real_estate.contract.term.tax',
        'term', 'tax', 'Taxes',
        order=[('tax.sequence', 'ASC'), ('tax.id', 'ASC')],
        domain=[('parent', '=', None), ['OR',
                ('group', '=', None),
                ('group.kind', 'in',
                        If(Eval('invoice_type', None) != None,
                            ['sale', 'both'],
                            ['purchase', 'both'])  
                    )],
            #('company', '=', Eval('company', -1)),
            ],
        #states={
        #    'readonly': True | ~Bool(Eval('account')),
        #    },
        depends={'invoice'})
    taxes_deductible_rate = fields.Numeric(
        "Taxes Deductible Rate", digits=(None, 10),
        domain=[
            ('taxes_deductible_rate', '>=', 0),
            ('taxes_deductible_rate', '<=', 1),
            ],
        states={
            'invisible': (
                (Eval('invoice_type') != 'in')),
            })
    taxes_date = fields.Date(
        "Taxes Date",
        states={
            'readonly': True,
            },
        help="The date at which the taxes are computed.\n"
        "Leave empty for the accounting date.")

    lines = fields.One2Many(
        'real_estate.contract.term.line', 'term', 'Lines',
        states={
            'readonly': True,
            'invisible': (Eval('len(lines)', 0) == 0),
            }
    )


    @classmethod
    def get_rhythm_type(cls):
        pool = Pool()
        Object = pool.get('real_estate.contract.term.type')
        return Object.fields_get(['rhythm_type'])['rhythm_type']['selection']

    def _get_taxes(self)-> dict:
        """ Return the taxes applied on this term """
        pool = Pool()
        Tax = pool.get('account.tax')
        Date = pool.get('ir.date')
        
        # Compute untaxed amount
        amount = (Decimal(str(self.quantity or 0))
            * (self.unit_price or Decimal(0)))
        untaxed_amount = self.currency.round(amount)
        tax_amount = untaxed_amount
        total_amount = untaxed_amount

        # Compute taxes
        tax_lines = Tax.compute(
            self.taxes,
            self.unit_price or 0,
            self.quantity or Decimal(0),
            self.taxes_date or Date.today(),
            )
        tax_amt = sum(line['amount'] for line in tax_lines)
        tax_amount = self.currency.round(tax_amt)
        total_amount = self.currency.round(amount + tax_amt)
        return {
            'untaxed_amount': untaxed_amount,
            'tax_amount': tax_amount,
            'total_amount': total_amount,
            }
    
    @classmethod
    def get_amount_and_tax(cls, terms, names):
        untaxed_amount = {i.id: i.currency.round(Decimal(0)) for i in terms}
        tax_amount = untaxed_amount.copy()
        total_amount = untaxed_amount.copy()

        for term in terms:
            if term.term_type:
                result = term._get_taxes()
                untaxed_amount[term.id] = result['untaxed_amount'] or Decimal(0)
                tax_amount[term.id] = result['tax_amount'] or Decimal(0)
                total_amount[term.id] = result['total_amount'] or Decimal(0)

        result = {
            'untaxed_amount': untaxed_amount,
            'tax_amount': tax_amount,
            'total_amount': total_amount,
            }
        for key in list(result.keys()):
            if key not in names:
                del result[key]
        return result

    @fields.depends('contract', 'sequence')
    def on_change_with_sequence(self, name=None):
        if (self.sequence != None and self.sequence != 0):
            return self.sequence
        
        if self.contract != None and self.contract.next_term_sequence:
            return self.contract.next_term_sequence
        
        return self.contract.c_type.step_term if self.contract and self.contract.c_type else 1


    @fields.depends('taxes', 'unit_price', 'quantity', 'currency', 'taxes_date')
    def on_change_with_untexed_amount(self, name=None):
        result = self._get_taxes()
        print("on_change_with_untexed_amount:", result)
        return result['untexed_amount'] or Decimal(0)


    @fields.depends(methods=['on_change_with_untexed_amount'])
    def on_change_with_tax_amount(self, name=None):
        result = self._get_taxes()
        return result['tax_amount'] or Decimal(0)
    
    @fields.depends(methods=['on_change_with_untexed_amount'])
    def on_change_with_total_amount(self, name=None):
        result = self._get_taxes()
        print("on_change_with_total_amount:", result)
        return result['total_amount'] or Decimal(0)

    @fields.depends(
        'term_type', 'quantity', 'unit_price', 'currency', 'contract',
        'taxes_deductible_rate', 
        #'invoice','_parent_invoice.currency',  
        'taxes',
        #'_parent_invoice.type', 'invoice_type',
        methods=['_get_taxes'])
    def on_change_with_amount(self, name=None):
        if self.term_type and self.contract and self.contract.c_type:
            amount = (Decimal(str(self.quantity or 0))
                * (self.unit_price or Decimal(0)))
            if ( self.contract.c_type.invoice_type == 'in'
                    and self.taxes_deductible_rate is not None
                    and self.taxes_deductible_rate != 1):
                with Transaction().set_context(_deductible_rate=1):
                    tax_amount = sum(
                        t.amount for t in self._get_taxes().values())
                non_deductible_amount = (
                    tax_amount * (1 - self.taxes_deductible_rate))
                amount += non_deductible_amount
            if self.currency:
                return self.currency.round(amount)
            return amount
        return Decimal(0)

    @fields.depends(methods=['on_change_with_amount'])
    def get_amount(self, name=None):
        if self.term_type:
            return self.on_change_with_amount()
        else:
            return Decimal(0)


    @fields.depends('next_document_date', 'contract', 'rhythm','rhythm_type',
                    'unit_price')
    def on_change_with_next_due_date(self):
        if self.contract and self.contract.payment_term \
            and self.next_document_date and self.unit_price:
            payment_term = Pool().get('account.invoice.payment_term')
            term = payment_term(self.contract.payment_term)
            term_lines = term.compute(
                self.unit_price, self.contract.currency, self.next_document_date)
            return term_lines[-1][0] if term_lines else self.next_document_date
        else:
            return self.next_document_date
        
    @fields.depends('rhythm','valid_from', 'last_document_date', 'rhythm_type',
                    'unit_price')
    def on_change_with_next_document_date(self):
        if self.last_document_date != None:
            if self.rhythm_type == 'monthly':
                return self.last_document_date + relativedelta(months=self.rhythm)
            
            elif self.rhythm_type == 'weekly':
                return self.last_document_date + relativedelta(weeks=self.rhythm)

            elif self.rhythm_type == 'daily':
                if self.rhythm % 365 == 0:
                    # for full years
                    return self.last_document_date + relativedelta(year=int(self.rhythm / 365))
                if self.rhythm % 30 == 0:
                    # for full months
                    return self.last_document_date + relativedelta(months=int(self.rhythm / 30))
                # else for days exactly
                return self.last_document_date + relativedelta(days=self.rhythm) 
            
            elif self.rhythm_type == 'quarterly':
                return self.last_document_date + relativedelta(months=self.rhythm * 3)
            
            elif self.rhythm_type == 'annually':
                return self.last_document_date + relativedelta(years= self.rhythm)
        
        return self.valid_from

    @fields.depends('term_type')
    def on_change_with_rhythm(self, name=None):
        if self.term_type and self.term_type.rhythm:
            return self.term_type.rhythm   
        else:
            return 1

    @fields.depends('term_type')
    def on_change_with_rhythm_type(self, name=None):
        if self.term_type and self.term_type.rhythm_type:
            return self.term_type.rhythm_type   
        else:
            return 'monthly'

    @fields.depends('term_type')
    def on_change_with_name(self, name=None):
        if self.term_type:
            if self.term_type.m_type:
                return f'{self.term_type.sequence} - {self.term_type.name}  ( {self.term_type.m_type.name} )'
            else:
                return f'{self.term_type.sequence} - {self.term_type.name}  ( - )'
        return f" - "

    @fields.depends('term_type')
    def on_change_with_unit(self, name=None):
        if self.term_type and self.term_type.m_type:
            return self.term_type.m_type.unit
        uom = Pool().get('product.uom')
        default_uom, = uom.search([('name', '=', 'Unit')], limit=1)
        if default_uom:
            return default_uom.id
        return None
    
    def _calc_quantity(self):
        """ Set the quantity from the latest measurement of the referenced property 
            per next_document_date"""
        if self.term_type and self.term_type.m_type and self.referenc_property:
            ref_item = Pool().get('real_estate.contract.item')(self.referenc_property)
            if ref_item.object and ref_item.object.measurements:
                # Get the latest measurement before or on the valid_from date
                meas_sorted = sorted(ref_item.object.measurements, key=lambda x: x['valid_from'], reverse=True)
                for meas in meas_sorted:
                    if meas.m_type == self.term_type.m_type \
                        and meas.valid_from <= self.next_document_date :
                        self.quantity = meas.value


    @fields.depends('term_type', 'referenc_property', 'next_document_date', 'valid_from')
    def on_change_with_quantity(self, name=None):
        if self.term_type and self.term_type.m_type and self.referenc_property:
            ref_item = Pool().get('real_estate.contract.item')(self.referenc_property)
            if ref_item.object and ref_item.object.measurements:
                # Get the latest measurement before or on the valid_from date
                meas_sorted = sorted(ref_item.object.measurements, key=lambda x: x['valid_from'], reverse=True)
                for meas in meas_sorted:
                    if meas.m_type == self.term_type.m_type \
                        and meas.valid_from <= self.next_document_date :
                        return meas.value
        
        if self.term_type and self.term_type.default_quantity:
            return self.term_type.default_quantity
        
        return Decimal(0)


    @fields.depends('contract', 'taxes', 'term_type')
    def on_change_with_taxes(self, name=None):
        if self.contract and self.term_type and len(self.taxes) == 0:
            ContractTermTypeTax = Pool().get('real_estate.contract.type.tax')
            taxes = ContractTermTypeTax.search([
                ('c_type', '=', self.contract.c_type.id),
                ])
            print("\n*****\n --> Taxes from contract type:", taxes)
            #if taxes:
            #    Modell_term_tax= Pool().get('real_estate.contract.term.tax')
            #    new_taxes = [Modell_term_tax.create([{'term': self.id, 'tax': tax.tax.id}]) for tax in taxes]
            #    return new_taxes
        return self.taxes

    @fields.depends('contract', 'valid_from', 
                    'currency', 'property', 'company',
                    'type_of_use')
    def on_change_contract(self, name=None):
        if self.contract != None and self.valid_from == None:
            self.valid_from = self.contract.start_date
        if self.contract:
            self.currency = self.contract.currency
            self.property = self.contract.property  
            self.company = self.contract.company
            self.type_of_use = self.contract.type_of_use       

    @fields.depends('contract')
    def on_change_with_currency(self, name=None):
        if self.contract:
            return self.contract.currency 
        return None
    
    @fields.depends('contract', 'valid_from', 'valid_to')
    def on_change_with_referenc_property(self, name=None):
        if self.referenc_property == None \
          and self.contract and len(self.contract.items) > 0:
            sorted_items = sorted(self.contract.items, key=lambda x: ( x.valid_from ), reverse=True)

            for item in sorted_items:
                if item.valid_from <= self.valid_from and (item.valid_to == None or item.valid_to >= self.valid_from):
                    return item
        return self.referenc_property

    @fields.depends('contract')
    def on_change_with_invoice_type(self, name=None):
        if self.contract and self.contract.c_type:
            return self.contract.c_type.invoice_type 
        return None

            
    @fields.depends('contract')
    def on_change_with_property(self, name=None):
        if self.contract:
            return self.contract.property
        return None
    
    @fields.depends('contract')
    def on_change_with_company(self, name=None):
        if self.contract:
            return self.contract.company
        return None
    
    @fields.depends('contract')
    def on_change_with_type_of_use(self, name=None):
        if self.contract:
            return self.contract.type_of_use
        return None
    
    @fields.depends('term_type')
    def on_change_with_account(self, name=None):
        if self.term_type and self.term_type.account:
            return self.term_type.account
        return None

    @classmethod
    def compute_name_search(cls, name, clause):
        if clause[1].startswith('!') or clause[1].startswith('not '):
            bool_op = 'AND'
        else:
            bool_op = 'OR'
        if cls.term_type:
            return [bool_op,
                ('self.term_type.name',) + tuple(clause[1:]),
                ('self.term_type.m_type.name',) + tuple(clause[1:]),
            ]  
        return []


    
#**********************************************************************
class ContractReport(CompanyReport):
    "Contract Context"
    __name__ = 'real_estate.contract.report'


