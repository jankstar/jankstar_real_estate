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
from trytond.wizard import (
    Button, StateReport, StateTransition, StateView, Wizard)
from trytond.transaction import Transaction, check_access, without_check_access

from sql import Null
from sql.aggregate import Sum
from sql.conditionals import Coalesce

from dateutil.relativedelta import relativedelta

from . import base_object
import logging
from decimal import Decimal
import datetime
import calendar

import pdb

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
class ContractLog(ModelSQL, ModelView):
    "Contract log obj"
    __name__ = 'real_estate.contract.log'

    contract = fields.Many2One('real_estate.contract', 'Contract', required=True, ondelete='CASCADE')
    event = fields.Char('Event', required=True)
    description = fields.Text('Description')
    create_date = fields.DateTime('Create Date', readonly=True)
    create_uid = fields.Many2One('res.user', 'User', readonly=True)

#**********************************************************************
class Contract(Workflow, DeactivableMixin, base_object.re_sequence_ordered(), ModelSQL, ModelView):
    "Base Object - base class for contracts"
    __name__ = 'real_estate.contract'
    __rec_name__ = 'name'
    __history__ = True

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

    name = fields.Function(fields.Char("Name"), 
                                    'on_change_with_name', 
                                    searcher='name_search'
                                    )    

    state = fields.Selection([
            ('draft', 'Draft'),
            ('running', 'Running'),
            ('terminated', 'Terminated'),
            ], "State", sort=False,
            #states={ 'readonly': True, },
            )
    
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

    cash_flow = fields.Function(
        fields.One2Many('real_estate.contract.term.cash_flow', 'contract',
                        'Cash Flow',)
        ,'on_change_with_cash_flow',)



    @classmethod
    def get_term_types_of_use(cls):
        pool = Pool()
        BaseObject = pool.get('real_estate.base_object')
        return BaseObject.fields_get(['type_of_use'])['type_of_use']['selection']

    @classmethod
    def default_company(cls):
        return Transaction().context.get('company')

    @fields.depends('terms')
    def on_change_with_cash_flow(self,name=None):
        return sorted([cash_flow_line for term in self.terms for cash_flow_line in term.cash_flow],
                        key=lambda line: (line.document_date, line.posting_date, line.name))


    def add_log(self, event, description=None):
        pool = Pool()
        ContractLog = pool.get('real_estate.contract.log')
        ContractLog.create([{
            'contract': self.id,
            'event': event,
            'description': description or '',
        }])
        print(f'contract {self.id}, event {event}, description {description}')

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
            return max(term.sequence for term in self.terms) + self.c_type.step_term
        return self.c_type.step_term if self.c_type else 1

    @fields.depends('items', 'c_type')
    def on_change_with_next_item_sequence(self, name=None):
        if self.items and self.c_type:
            return max(item.sequence for item in self.items) + self.c_type.step_item
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
    def on_change_with_name(self, name=None):
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
    def name_search(cls, name, clause):
        if clause[1].startswith('!') or clause[1].startswith('not '):
            bool_op = 'AND'
        else:
            bool_op = 'OR'

        return [bool_op,
            ('contract_number',) + tuple(clause[1:]),
            ('contractual_partner.name',) + tuple(clause[1:]),
        ]   

    def _create_moves(self, terms, date):
        #pdb.set_trace()  # Breakpoint

        self.add_log('process', f'start quere contract {self.id} at {date}')
        if not terms:
            self.add_log('process', f'stop quere contract {self.id} at {date} - no terms')
            return
        
        pool = Pool()
        Invoice = pool.get('account.invoice')
        InvoiceLine = pool.get('account.invoice.line')


        line_vals = []
        for term_id in terms:

            term = next(
                    (obj for obj in self.terms if obj.id == term_id),
                    None,)
            if term :
                taxes = set()
                for tax in term.taxes:
                    taxes.add(tax)
                
                lCount = 0 #maximum 12 x term per loop
                while lCount < 12 \
                and term.valid_from <= date \
                and term.last_document_date != term.next_document_date \
                and term.next_document_date <= date:
                    #only valid next document date calulate by rhythm

                    lCount += 1
                    line_vals.append(
                        InvoiceLine(
                            type='line',
                            company=self.company.id,                        
                            description=f'{term.next_document_date:%Y/%m/%d} / {term.name}',
                            quantity=term.quantity,
                            unit=term.unit,
                            unit_price=term.unit_price,
                            account=term.account.id,
                            taxes=list(taxes),
                            contract=self,
                            term=term    
                        )
                    )

                    term.last_posting_date = date
                    term.last_document_date = term.next_document_date
                    term.next_document_date = term.on_change_with_next_document_date()
                    term.next_due_date = term.on_change_with_next_due_date()
                    term.save()


        line_vals.sort(key=lambda ele: ele.description)

        #pdb.set_trace()  # Breakpoint
        if len(line_vals) > 0:
            invoice = Invoice(
                company=self.company.id,
                type=self.c_type.invoice_type,
                party=self.contractual_partner.id,
                invoice_date=date,
                accounting_date=date,
                payment_term_date=date,
                invoice_address=self.invoice_address,
                currency=self.currency.id,
                journal=self.c_type.account_journal.id,
                account=self.contractual_partner.account_receivable.id,
                payment_term=self.payment_term.id,
                description=self.c_type.mark if self.c_type.mark else self.c_type.name,
                reference=self.contract_number,
                lines=line_vals,
                contract=self
            )
            

            #pdb.set_trace()  # Breakpoint

            #invoices = Invoice.create([invoice_vals])
            #invoice, = invoices
            Invoice.save([invoice])
            self.add_log('process',f'contract {self.id} / invoice {invoice.id} posted.')

        else:
            self.add_log('process',f'contract {self.id} - no term computed')



    @classmethod
    def create_moves(cls, contracts, date, re_calc=False):
        """
        Creates all account move on contract before a date.
        """

        transaction = Transaction()
        context = transaction.context
        #pdb.set_trace()  # Breakpoint

        for contract in contracts:
            contract.add_log('process',f'start "create_moves" with date {date}')
            if contract.state != 'running':
                contract.add_log('process',f'contract state {contract.state} - finished')
                exit
            if contract.start_date > date:
                contract.add_log('process',f'contract start_date {contract.start_date} - finished')
                exit                

            process_terms = []
            for term in contract.terms:
                # calculate doc and due date for constrains
                term.next_document_date = term.on_change_with_next_document_date()
                term.next_due_date = term.on_change_with_next_due_date()
                if re_calc:
                    contract.add_log('process',f'term {term.name} with re-calc')
                    term.re_calc()
                term.save()

                if term.next_document_date <= date \
                    and term.next_document_date  != term.last_document_date \
                    and term.total_amount != 0:
                    contract.add_log('process',f'term {term.name} with total amount {term.total_amount}')

                    process_terms.append(term.id)

            if len(process_terms) > 0:
                with transaction.set_context(
                    queue_batch=context.get('queue_batch', True)):
                    #cls.__queue__._create_moves(contract, process_terms, date)
                    pass

            contract.add_log('process',f'"create_moves" finished')
            contract.save()

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
class ContractTermCashFlow( ModelView, ModelSQL, metaclass=PoolMeta):
    __name__ = 'real_estate.contract.term.cash_flow'


    status = fields.Selection(
        [('draft', 'Draft'),
         ('done','Done')], 
         "Status", sort=False, required=True, 
         states={'readonly': True,})

    name = fields.Function(fields.Char("Name"), 
                                    'on_change_with_name', 
                                    #searcher='name_search'
                                    )    


    posting_date = fields.Date('Posting Date', 
        states={'readonly': True,})
    document_date = fields.Date('Document Date', 
        states={'readonly': True,})
    due_date = fields.Date('Due Date', 
        states={'readonly': True,})    

    contract = fields.Function(fields.Many2One(
        'real_estate.contract', 'Contract',
        ), 'on_change_with_contract')

    invoice = fields.Function(fields.Many2One(
        'account.invoice', "Invoice",
        ), 'on_change_with_invoice')

    term = fields.Many2One(
        'real_estate.contract.term', 'Term',required=True,
        states={'readonly': True,})

    invoice_line = fields.Many2One(
        'account.invoice.line', 'Invoice Line',
        states={'readonly': True,})


    property = fields.Function(fields.Many2One('real_estate.base_object','Property'),
        'on_change_with_property')

    company = fields.Function(fields.Many2One('company.company','Company'),
        'on_change_with_company')

    quantity = fields.Function(fields.Float(
        "Quantity", digits='unit',
        ), 'on_change_with_quantity')

    unit = fields.Function(fields.Many2One('product.uom', 'Unit',
            ), 'on_change_with_unit')
    
    unit_price = fields.Function(Monetary(
        "Unit Price", currency='currency', digits=price_digits,
        ), 'on_change_with_unit_price')

    amount = fields.Function(Monetary(
        "Amount", currency='currency', digits='currency',
        ), 'on_change_with_amount')

    tax_amount = fields.Function(Monetary(
            "Tax", currency='currency', digits='currency'),
        'get_amount_and_tax', )

    total_amount = fields.Function(Monetary(
            "Total", currency='currency', digits='currency'),
        'get_amount_and_tax', )    

    currency = fields.Function(fields.Many2One(
        'currency.currency', "Currency", 
        # states={'readonly': True,},
        ), 'on_change_with_currency')


    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._order = [('document_date','ASC'),('posting_date', 'ASC')] + cls._order

    @classmethod
    def default_status(cls):
        return 'draft'

    @fields.depends('term')
    def on_change_with_contract(self, name=None):
        if self.term:
            return self.term.contract
        return None

    @fields.depends('term')
    def on_change_with_property(self, name=None):
        if self.term and self.term.contract:
            return self.term.contract.property
        return None
    
    @fields.depends('term')
    def on_change_with_company(self, name=None):
        if self.term and self.term.contract:
            return self.term.contract.company
        return None

    @fields.depends('invoice_line')
    def on_change_with_invoice(self, name=None):
        if self.invoice_line:
            return self.invoice_line.invoice
        return None

    @fields.depends('term', 'invoice_line')
    def on_change_with_name(self, name=None):
        if self.invoice_line:
            return f"{self.invoice_line.description}"
        elif self.term:
            return f'{self.term.next_document_date:%Y/%m/%d} / {self.term.name}'
        return f" - "   

    @fields.depends('term', 'invoice_line')
    def on_change_with_quantity(self, name=None):
        if self.invoice_line:
            return self.invoice_line.quantity
        elif self.term:
            return self.term.quantity
        return 0
    
    @fields.depends('term', 'invoice_line')
    def on_change_with_unit(self, name=None):
        if self.invoice_line:
            return self.invoice_line.unit
        elif self.term:
            return self.term.unit
        return None
    
    @fields.depends('term', 'invoice_line')
    def on_change_with_unit_price(self, name=None):
        if self.invoice_line:
            return self.invoice_line.unit_price
        elif self.term:
            return self.term.unit_price
        return Decimal(0)

    @fields.depends('quantity', 'unit_price', 'currency' )
    def on_change_with_amount(self, name=None):
        amount = (Decimal(str(self.quantity or 0))
            * (self.unit_price or Decimal(0)))
        if self.currency:
            return self.currency.round(amount)
        return amount


    def _get_invouce_line_taxes(self)-> dict:
        """ Return the taxes applied on taxes from invoice line"""
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
        if self.invoice_line:
            tax_lines = Tax.compute(
                self.invoice_line.taxes,
                self.unit_price or 0,
                self.quantity or Decimal(0),
                self.invoice_line.taxes_date or Date.today(),
                )
            tax_amt = sum(line['amount'] for line in tax_lines)
            tax_amount = self.currency.round(tax_amt)
            total_amount = self.currency.round(amount + tax_amt)
        return {
            'untaxed_amount': untaxed_amount,
            'tax_amount': tax_amount,
            'total_amount': total_amount,
            }

    @fields.depends('term', 'invoice_line', 'amount')
    def get_amount_and_tax(self, names=None):
        total_amount = Decimal(0)
        tax_amount = Decimal(0)
        if self.invoice_line:
            my_tax = self._get_invouce_line_taxes()
            tax_amount = my_tax['tax_amount'] or Decimal(0)
            total_amount = self.amount + tax_amount

        elif self.term:
            total_amount = self.term.total_amount
            tax_amount = self.term.tax_amount

        result =  {
            'tax_amount': tax_amount,
            'total_amount': total_amount,
            }
        for key in list(result.keys()):
            if key not in names:
                del result[key]
        return result

    @fields.depends('term', 'invoice_line')
    def on_change_with_currency(self, name=None):
        if self.invoice_line and self.invoice_line.currency:
            return self.invoice_line.currency
        elif self.term and self.term.contract and self.term.contract.currency:
            return self.term.contract.currency
        return None

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

    mark = fields.Char("Mark", help='Periodic posting Mark')


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
            return self.object.name + ' ( ' + self.object.object_number + ' )'
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

    reference_item = fields.Many2One('real_estate.contract.item', 'Reference Item',
            domain=[ ('contract', '=', Eval('contract', -1)),
                    ],)
                                        

    valid_from = fields.Date('Valide from', required=True)
    valid_to = fields.Date('Valid to',
         states={
            'readonly': ((Eval('rhythm', -1) == 0)),
            })
    
    last_posting_date = fields.Function(fields.Date('Last Posting Date', 
        states={'readonly': True,})
        ,'on_change_with_last_posting_date')
    last_document_date = fields.Function(fields.Date('Last Document Date', 
        states={'readonly': True,})
        ,'on_change_with_last_document_date')

    next_document_date = fields.Function(fields.Date('Next Document Date', 
        states={'readonly': True,})
        ,'on_change_with_next_document_date')
    
    next_due_date = fields.Function(fields.Date('Next Due Date', 
        states={'readonly': True,})
        , 'on_change_with_next_due_date'
        )

   
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

    cash_flow = fields.One2Many('real_estate.contract.term.cash_flow', 'term',
            'Cash Flow',
        order=[
            ('posting_date', 'ASC NULLS FIRST'),   # Primärsortierung
            ('document_date', 'ASC NULLS FIRST'),  # Sekundärsortierung
        ],            
            states={
                'readonly': True,
                'invisible': (Eval('len(lines)', 0) == 0),
            })


    @classmethod
    def get_rhythm_type(cls):
        pool = Pool()
        Object = pool.get('real_estate.contract.term.type')
        return Object.fields_get(['rhythm_type'])['rhythm_type']['selection']

    def re_calc(self):
        """ Re-calculate next document/due date by rhythm and last posting date """

        # def _finde_invoice_line(line_id):
        #     for e in self.cash_flow:
        #         if e.invoice_line == line_id:
        #             return e.invoice_line
        #     return None

        pool = Pool()
        # first add missing cash flow entries for existing invoice lines
        InvoiceLine = pool.get('account.invoice.line')
        CashFlow = pool.get('real_estate.contract.term.cash_flow')
        invoice_lines = InvoiceLine.search([('term', '=', self.id)])
        for invoice_line in invoice_lines:
            #pdb.set_trace()  # Breakpoint
            is_found = next((True for e in self.cash_flow if e.invoice_line == invoice_line.id), None)
            #is_found = _finde_invoice_line(invoice_line.id)
            if not is_found:
                cash_flow = CashFlow(
                    status='done',
                    posting_date=invoice_line.invoice.accounting_date,
                    document_date=invoice_line.invoice.invoice_date,
                    due_date=invoice_line.invoice.payment_term_date,
                    contract=self.contract.id,
                    invoice=invoice_line.invoice.id,
                    term=self.id,
                    invoice_line=invoice_line.id,
                    property=self.contract.property.id if self.contract else None,
                    company=self.contract.company.id if self.contract else None,
                    quantity=invoice_line.quantity,
                    unit=invoice_line.unit.id if invoice_line.unit else None,
                    unit_price=invoice_line.unit_price,
                    )
                cash_flow.save()
                #self.cash_flow = self.on_change_with_cash_flow() # ensure term cash flow is up to date

        # then remove draft cash flow entries
        for cash_flow in self.cash_flow:
            if cash_flow.status == 'draft':
                CashFlow.delete([cash_flow])

        # finally recalculate next document/due date
        today = datetime.date.today()
        today_plus_year = today.replace(year=today.year + 1)        
        my_last_document_date = self.last_document_date
        my_next_document_date = self._next_document_date(calc_document_date=my_last_document_date)
        while my_last_document_date != my_next_document_date and self.total_amount != 0 \
            and (not self.valid_from or my_next_document_date >= self.valid_from) \
            and (not self.valid_to or my_next_document_date <= self.valid_to) \
            and my_next_document_date <= today_plus_year:
                
                cash_flow = ContractTermCashFlow(
                    status='draft',
                    #posting_date=invoice_line.accounting_date,
                    document_date=my_next_document_date,
                    #due_date=invoice_line.payment_term_date,
                    contract=self.contract.id,
                    #invoice=invoice_line.invoice.id,
                    term=self.id,
                    #invoice_line=invoice_line.id,
                    property=self.contract.property.id if self.contract else None,
                    company=self.contract.company.id if self.contract else None,
                    quantity=invoice_line.quantity,
                    unit=invoice_line.unit.id if invoice_line.unit else None,
                    unit_price=invoice_line.unit_price,
                    )
                cash_flow.save()     

                my_last_document_date = my_next_document_date
                my_next_document_date = self._next_document_date(calc_document_date=my_last_document_date)                




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

        result =  {
            'untaxed_amount': untaxed_amount,
            'tax_amount': tax_amount,
            'total_amount': total_amount,
            }
        for key in list(result.keys()):
            if key not in names:
                del result[key]
        return result
    
    @fields.depends('cash_flow')
    def on_change_with_last_document_date(self, name=None):
        if self.cash_flow:
            done_cash_flows = [cf for cf in self.cash_flow if cf.status == 'done' and cf.document_date is not None]
            if done_cash_flows:
                return max(cf.document_date for cf in done_cash_flows)
        return None
    
    @fields.depends('cash_flow')
    def on_change_with_last_posting_date(self, name=None):
        if self.cash_flow:
            done_cash_flows = [cf for cf in self.cash_flow if cf.status == 'done' and cf.posting_date is not None]
            if done_cash_flows:
                return max(cf.posting_date for cf in done_cash_flows)
        return None

    @fields.depends('contract', 'sequence')
    def on_change_with_sequence(self, name=None):
        if (self.sequence != None and self.sequence != 0):
            return self.sequence
        
        if self.contract != None and self.contract.next_term_sequence:
            return self.contract.next_term_sequence
        
        return self.contract.c_type.step_term if self.contract and self.contract.c_type else 1


    @fields.depends('taxes', 'unit_price', 'quantity', 'currency', 'taxes_date')
    def on_change_with_untaxed_amount(self, name=None):
        result = self._get_taxes()
        print("on_change_with_untaxed_amount:", result)
        return result['untaxed_amount'] or Decimal(0)


    @fields.depends(methods=['on_change_with_untaxed_amount'])
    def on_change_with_tax_amount(self, name=None):
        result = self._get_taxes()
        return result['tax_amount'] or Decimal(0)
    
    @fields.depends(methods=['on_change_with_untaxed_amount'])
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
    def on_change_with_next_due_date(self, name=None):
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
    def _next_document_date(self, calc_document_date=None):
        def _check_valid_to(i_date):
            """ next doc date must between valid_fromn/valid_to"""
            if ( self.valid_to != None and self.valid_to > i_date ) \
                or (self.contract.end_date != None and self.contract.end_date > i_date ):
                return self.last_document_date
            else: 
                return i_date

        my_document_Date = calc_document_date if calc_document_date != None else self.last_document_date

        if my_document_Date != None:
            if self.rhythm_type == 'monthly':
                return _check_valid_to(my_document_Date + relativedelta(months=self.rhythm))
            
            elif self.rhythm_type == 'weekly':
                return _check_valid_to(my_document_Date + relativedelta(weeks=self.rhythm))

            elif self.rhythm_type == 'daily':
                if self.rhythm % 365 == 0:
                    # for full years
                    return _check_valid_to(my_document_Date + relativedelta(year=int(self.rhythm / 365)))
                if self.rhythm % 30 == 0:
                    # for full months
                    return _check_valid_to(my_document_Date+ relativedelta(months=int(self.rhythm / 30)))
                # else for days exactly
                return _check_valid_to(my_document_Date + relativedelta(days=self.rhythm)) 
            
            elif self.rhythm_type == 'quarterly':
                return _check_valid_to(my_document_Date + relativedelta(months=self.rhythm * 3))
            
            elif self.rhythm_type == 'annually':
                return _check_valid_to(my_document_Date + relativedelta(years= self.rhythm))
        
        return self.valid_from
    

    @fields.depends('rhythm','valid_from', 'last_document_date', 'rhythm_type',
                    'unit_price')
    def on_change_with_next_document_date(self, name=None):
        return self._next_document_date()

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
        """ Set the quantity from the latest measurement of the referenced item 
            per next_document_date"""
        if self.term_type and self.term_type.m_type and self.reference_item:
            ref_item = Pool().get('real_estate.contract.item')(self.reference_item)
            if ref_item.object and ref_item.object.measurements:
                # Get the latest measurement before or on the valid_from date
                meas_sorted = sorted(ref_item.object.measurements, key=lambda x: x['valid_from'], reverse=True)
                for meas in meas_sorted:
                    if meas.m_type == self.term_type.m_type \
                        and meas.valid_from <= self.next_document_date :
                        self.quantity = meas.value


    @fields.depends('term_type', 'reference_item', 'next_document_date', 'valid_from')
    def on_change_with_quantity(self, name=None):
        if self.term_type and self.term_type.m_type and self.reference_item:
            ref_item = Pool().get('real_estate.contract.item')(self.reference_item)
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
    def on_change_with_reference_item(self, name=None):
        if self.reference_item == None \
          and self.contract and len(self.contract.items) > 0:
            sorted_items = sorted(self.contract.items, key=lambda x: ( x.valid_from ), reverse=True)

            for item in sorted_items:
                if item.valid_from <= self.valid_from and (item.valid_to == None or item.valid_to >= self.valid_from):
                    return item
        return self.reference_item

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


#**************************************************************
class CreateMovesStart(ModelView):
    __name__ = 'real_estate.contract.create_moves.start'
    date = fields.Date('Date')
    company = fields.Many2One('company.company', "Company", required=True, )
    re_calc = fields.Boolean('Re-calculate', 
        help="If checked, the moves will be re-created even if they already exist for the given date.")
    
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

#**********************************************************************
class CreateMoves(Wizard):
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
            Contract = pool.get('real_estate.contract')
            contracts = Contract.search([
                    ('state', '=', 'running'),
                    ('start_date', '<=', self.start.date)
                    ])
        contracts = Contract.browse(contracts)
        
        Contract.create_moves(contracts, self.start.date, self.start.re_calc)
        return 'end'

    
#**********************************************************************
class ContractReport(Report):
    "Contract Context"
    __name__ = 'real_estate.contract.report'


    @classmethod
    def _format(cls,value):
        if value is None:
            return ''
        if type(value) == str:
            return value
        if type(value) ==bool:
            return str(value)
        if type(value) ==int:
            return str(value)
        if type(value) ==float:
            return cls.format_number(value, None)
        if type(value) == datetime.date:
            return cls.format_date(value)
        if type(value) == datetime.datetime:
            return cls.format_datetime(value)
        return value

    @classmethod
    def get_context(cls, records, header, data):
        context = super().get_context(records, header, data)
        #context['footer'] =  context['record'].company.footer.split('\n') if context['record'] else []
        context['_format'] = cls._format
        return context
    