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
from . import base_object
import logging


logger = logging.getLogger(__name__)

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
            'contracterm_type_tax', cls._table)
        super().__register__(module)


class ContractType(DeactivableMixin, base_object.re_sequence_ordered(), ModelSQL, ModelView):
    __name__ = 'real_estate.contract.type'

    name = fields.Char("Name", required=True, translate=True)
    types_of_use = fields.MultiSelection(
            'geterm_types_of_use', "Types",
            help="The type of object which can use this contract type.")    
    
    invoice_type = fields.Selection('get_invoice_types', 
                                    "Invoice Type", required=True,)

    account = fields.Many2One('account.account', 'Party Account', required=True,
        domain=[
            If(Eval('invoice_type') == 'out',
                ('type.receivable', '=', True),
                ('type.payable', '=', True)),
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

    @classmethod
    def geterm_types_of_use(cls):
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
class ContractItem(DeactivableMixin, ModelSQL, ModelView, metaclass=PoolMeta):
    "Contract Item"
    __name__ = 'real_estate.contract.item'
    __rec_name__ = 'name'
    
    contract = fields.Many2One('real_estate.contract', 'Contract', required=True,
         path='path', ondelete='CASCADE')
    object = fields.Many2One('real_estate.base_object', 'Object', required=True,
            domain=[('type', 'in', ('object',)),
                    ('type_of_use', '=', Eval('compute_type_of_use', -1)),
                    ('property', '=', Eval('compute_property', -1)),
                    ('company', '=', Eval('compute_company', -1)),
                    ],)
    valid_from = fields.Date('Valide from', required=True)
    valid_to = fields.Date('Valid to')

    name = fields.Function(fields.Char("Name"), 
                                'on_change_with_name', 
                                searcher='compute_name_search')   
    
    compute_property = fields.Function(fields.Many2One('real_estate.base_object','Property'),
        'on_change_with_compute_property')

    compute_company = fields.Function(fields.Many2One('company.company','Company'),
        'on_change_with_compute_company')

    compute_type_of_use = fields.Function(fields.Char("Type of Use"),
        'on_change_with_compute_type_of_use')

    currency = fields.Function(fields.Many2One('currency.currency',
        'Currency'), 'on_change_with_currency')

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
    def on_change_with_compute_property(self, name=None):
        if self.contract:
            return self.contract.property
        return None
    
    @fields.depends('contract')
    def on_change_with_currency(self, name=None):
        return self.contract.currency if self.contract else None

    @fields.depends('contract')
    def on_change_with_compute_company(self, name=None):
        if self.contract:
            return self.contract.company
        return None
    
    @fields.depends('contract')
    def on_change_with_compute_type_of_use(self, name=None):
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
    __rec_name__ = 'name'


    name = fields.Char("Name", required=True, translate=True)
    types_of_use = fields.MultiSelection(
            'geterm_types_of_use', "Types",
            help="The type of object which can use this contract term type.")    
    
    m_type = fields.Many2One('real_estate.measurement.type', "Measurement Type", 
        required=True,
        )

    account = fields.Many2One('account.account', 'Account',
        required=True,
        domain=['OR',
                ('type.revenue', '=', True),
                ('type.expense', '=', True),
                ('type.debt', '=', True),
                ],)

    monthly_rhythm = fields.Integer("Monthly Rhythm", required=True)

    @classmethod
    def default_monthly_rhythm(cls):
        return 1


    @classmethod
    def geterm_types_of_use(cls):
        pool = Pool()
        BaseObject = pool.get('real_estate.base_object')
        return BaseObject.fields_get(['type_of_use'])['type_of_use']['selection']

#**********************************************************************
class ContractTerm(DeactivableMixin, ModelSQL, ModelView):
    "Contract Term"
    __name__ = 'real_estate.contract.term'
    __rec_name__ = 'name'
    
    contract = fields.Many2One('real_estate.contract', 'Contract', required=True,
         path='path', ondelete='CASCADE')

    valid_from = fields.Date('Valide from', required=True)
    valid_to = fields.Date('Valid to',
         states={
            'readonly': ((Eval('monthly_rhythm', -1) == 0)),
            })
    
    last_posting_date = fields.Date('Last Posting Date', 
        states={'readonly': True,})
    last_document_date = fields.Date('Last Document Date', 
        states={'readonly': True,})

    next_document_date = fields.Date('Next Document Date', 
        states={'readonly': True,})
    next_due_date = fields.Date('Next Due Date', 
        states={'readonly': True,})

    term_type = fields.Many2One(
        'real_estate.contract.term.type', "Term Type", required=True,
       )

    name = fields.Function(fields.Char("Name"), 
                                'on_change_with_name', 
                                searcher='compute_name_search')   
    
    monthly_rhythm = fields.Integer("Monthly Rhythm", required=True,
        states={
            'invisible': (Eval('term_type', None) == None),
            },
        )


    compute_property = fields.Function(fields.Many2One('real_estate.base_object','Property'),
        'on_change_with_compute_property')

    compute_company = fields.Function(fields.Many2One('company.company','Company'),
        'on_change_with_compute_company')

    compute_type_of_use = fields.Function(fields.Char("Type of Use"),
        'on_change_with_compute_type_of_use')

    compute_currency = fields.Function(fields.Many2One('currency.currency',
        'Currency'),
        'on_change_with_currency')


    unit_price = Monetary(
        "Unit Price", currency='currency', digits=price_digits,
        states={
            'required': True,
            'readonly': (Eval('valid_to', None) != None),
            'invisible': (Eval('term_type', None) == None),
            })

    lines = fields.One2Many(
        'real_estate.contract.term.line', 'term', 'Lines',
        states={
            'readonly': True,
            'invisible': (Eval('len(lines)', 0) == 0),
            }
    )

    @fields.depends('next_document_date', 'contract', 'monthly_rhythm',
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
        
    @fields.depends('monthly_rhythm', 'valid_from', 'last_document_date', 
                    'unit_price')
    def on_change_with_next_document_date(self):
        if self.last_document_date == None:
            return self.valid_from
        else:
            ir_date = Pool().get('ir.date')
            return ir_date.add_months(
                self.last_document_date, self.monthly_rhythm)

    @fields.depends('term_type')
    def on_change_with_monthly_rhythm(self, name=None):
        if self.term_type and self.term_type.monthly_rhythm:
            return self.term_type.monthly_rhythm   
        else:
            return 1

    @fields.depends('term_type')
    def on_change_with_name(self, name=None):
        if self.term_type:
            if self.term_type.m_type:
                return f'{self.term_type.sequence} - {self.term_type.name}  ( {self.term_type.m_type.name} )'
            else:
                return f'{self.term_type.sequence} - {self.term_type.name}  ( - )'
        return f" - "

    @fields.depends('contract', 'valid_from', 
                    'compute_currency', 'compute_property', 'compute_company',
                    'compute_type_of_use')
    def on_change_contract(self, name=None):
        if self.contract != None and self.valid_from == None:
            self.valid_from = self.contract.start_date
        if self.contract:
            self.compute_currency = self.contract.currency
            self.compute_property = self.contract.property  
            self.compute_company = self.contract.company
            self.compute_type_of_use = self.contract.type_of_use       

    @fields.depends('contract')
    def on_change_with_currency(self, name=None):
        if self.contract:
            return self.contract.currency 
        return None
            
    @fields.depends('contract')
    def on_change_with_compute_property(self, name=None):
        if self.contract:
            return self.contract.property
        return None
    
    @fields.depends('contract')
    def on_change_with_compute_company(self, name=None):
        if self.contract:
            return self.contract.company
        return None
    
    @fields.depends('contract')
    def on_change_with_compute_type_of_use(self, name=None):
        if self.contract:
            return self.contract.type_of_use
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

   
    type_of_use = fields.Selection('geterm_types_of_use',
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
        states={
            'readonly': (Eval('state') != 'draft'),
            }
        )

    terms = fields.One2Many('real_estate.contract.term', 'contract', 'Terms',
        )


    @classmethod
    def geterm_types_of_use(cls):
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
        return Pool().get('ir.date').today().replace(day=1)    

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

    @fields.depends('c_type', 'property', 'sequence')
    def on_change_with_contract_number(self, name=None):
        if  self.c_type == None or self.property == None:
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
class ContractReport(CompanyReport):
    "Contract Context"
    __name__ = 'real_estate.contract.report'


