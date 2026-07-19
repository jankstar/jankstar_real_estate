'Contract Term, Tax, Cash Flow'
from trytond.model import (sequence_ordered,
    ModelSQL, ModelView, fields, Unique)
from trytond.model.exceptions import ValidationError
from trytond.i18n import gettext
from trytond.pool import Pool
from trytond.transaction import Transaction
from trytond.pyson import Eval, If
from trytond import backend
from trytond.modules.currency.fields import Monetary
from trytond.modules.account.tax import TaxableMixin
from trytond.modules.product import price_digits

from dateutil.relativedelta import relativedelta

import logging
import re
from decimal import Decimal
import datetime
import calendar

logger = logging.getLogger(__name__)

_re_calc_year = 1


class Quantitative(fields.Numeric):
    """
    Define a numeric field with unit (``decimal``).
    """
    def __init__(self, string='', unit=None, digits=None, help='',
            required=False, readonly=False, domain=None, states=None,
            on_change=None, on_change_with=None, depends=None, context=None,
            loading='eager'):
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
        backend.TableHandler.table_rename(
            'contrac_term_tax', cls._table)
        super().__register__(module)


#**********************************************************************
class ContractTermCashFlow(ModelView, ModelSQL):
    __name__ = 'real_estate.contract.term.cash_flow'

    state = fields.Selection(
        [('draft', 'Draft'),
         ('done', 'Done')],
         "State", sort=False, required=True,
         states={'readonly': True,})

    name = fields.Function(fields.Char("Name"),
                                    'on_change_with_name',
                                    searcher='name_search')

    create_moves_run_id = fields.Char('Create Moves Run ID', readonly=True)

    posting_date = fields.Date('Posting Date',
        states={'readonly': True,})
    document_date = fields.Date('Document Date',
        states={'readonly': True,})
    due_date = fields.Date('Due Date',
        states={'readonly': True,})

    contract = fields.Function(fields.Many2One(
        'real_estate.contract', 'Contract',
        ), 'on_change_with_contract', searcher='search_contract')

    invoice = fields.Function(fields.Many2One(
        'account.invoice', "Invoice",
        ), 'on_change_with_invoice', searcher='search_invoice')

    invoice_state = fields.Function(
        fields.Selection('get_invoice_states', "Invoice State"),
        'on_change_with_invoice_state', searcher='search_invoice_state')

    term = fields.Many2One(
        'real_estate.contract.term', 'Term', required=True,
        ondelete='CASCADE',
        states={'readonly': True,})

    invoice_line = fields.Many2One(
        'account.invoice.line', 'Invoice Line',
        states={'readonly': True,})

    property = fields.Function(fields.Many2One('real_estate.base_object', 'Property'),
        'on_change_with_property', searcher='search_property')

    base_object = fields.Function(fields.Many2One('real_estate.base_object', 'Object'),
        'on_change_with_base_object', searcher='search_base_object')

    company = fields.Function(fields.Many2One('company.company', 'Company'),
        'on_change_with_company', searcher='search_company')

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
        ), 'on_change_with_currency')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._order = [('document_date', 'ASC'), ('posting_date', 'ASC')] + cls._order

    @classmethod
    def default_state(cls):
        return 'draft'

    @classmethod
    def get_invoice_states(cls):
        pool = Pool()
        Invoice = pool.get('account.invoice')
        return Invoice.fields_get(['state'])['state']['selection']

    @fields.depends('term', '_parent_term.contract')
    def on_change_with_contract(self, name=None):
        if self.term:
            return self.term.contract
        return None

    @fields.depends('term', '_parent_term.contract')
    def on_change_with_property(self, name=None):
        if self.term and self.term.contract:
            return self.term.contract.property
        return None

    @fields.depends('invoice_line')
    def on_change_with_base_object(self, name=None):
        if self.invoice_line and self.invoice_line.base_object:
            return self.invoice_line.base_object
        return None

    @classmethod
    def search_base_object(cls, name, clause):
        return [('invoice_line.base_object',) + tuple(clause[1:])]

    @fields.depends('term', '_parent_term.contract')
    def on_change_with_company(self, name=None):
        if self.term and self.term.contract:
            return self.term.contract.company
        return None

    @fields.depends('invoice_line')
    def on_change_with_invoice(self, name=None):
        if self.invoice_line:
            return self.invoice_line.invoice
        return None

    @fields.depends('invoice')
    def on_change_with_invoice_state(self, name=None):
        if self.invoice:
            state = self.invoice.state
            if state == 'cancelled' and self.invoice.cancel_move:
                state = 'paid'
        else:
            state = 'draft'
        return state

    @fields.depends(
        'term', 'invoice_line',
        '_parent_term.name', '_parent_term.next_document_date')
    def on_change_with_name(self, name=None):
        if self.invoice_line:
            return f"{self.invoice_line.description}"
        elif self.term and self.document_date:
            return f'{self.document_date:%Y/%m/%d} / {self.term.name}'
        elif self.term:
            return f'{self.term.next_document_date:%Y/%m/%d} / {self.term.name}'
        return f" - "

    @classmethod
    def name_search(cls, name, clause):
        import calendar as cal
        _, operator, value = clause
        if operator.startswith('!') or operator.startswith('not '):
            bool_op = 'AND'
        else:
            bool_op = 'OR'

        domain = [bool_op,
            ('invoice_line.description',) + tuple(clause[1:]),
            ('term.term_type.name',) + tuple(clause[1:]),
            ('term.contract.contract_number',) + tuple(clause[1:]),
            ('term.contract.contractual_partner.name',) + tuple(clause[1:]),
        ]

        clean = value.strip('%') if isinstance(value, str) else ''
        m = re.match(r'^(\d{4})/(\d{2})(?:/(\d{2}))?$', clean)
        if m:
            try:
                year, month = int(m.group(1)), int(m.group(2))
                if m.group(3):
                    domain.append(
                        ('document_date', '=', datetime.date(year, month, int(m.group(3)))))
                else:
                    last_day = cal.monthrange(year, month)[1]
                    domain.append(['AND',
                        ('document_date', '>=', datetime.date(year, month, 1)),
                        ('document_date', '<=', datetime.date(year, month, last_day)),
                    ])
            except ValueError:
                pass

        return domain

    @classmethod
    def search_contract(cls, name, clause):
        return [('term.contract',) + tuple(clause[1:])]

    @classmethod
    def search_property(cls, name, clause):
        return [('term.contract.property',) + tuple(clause[1:])]

    @classmethod
    def search_company(cls, name, clause):
        return [('term.contract.company',) + tuple(clause[1:])]

    @classmethod
    def search_invoice(cls, name, clause):
        return [('invoice_line.invoice',) + tuple(clause[1:])]

    @classmethod
    def search_invoice_state(cls, name, clause):
        _, operator, value = clause
        if operator in ('=', '!=') and value == 'draft':
            if operator == '=':
                return ['OR',
                    ('invoice_line', '=', None),
                    ('invoice_line.invoice.state', '=', 'draft'),
                ]
            else:
                return ['AND',
                    ('invoice_line', '!=', None),
                    ('invoice_line.invoice.state', '!=', 'draft'),
                ]
        return [('invoice_line.invoice.state',) + tuple(clause[1:])]

    @fields.depends('term', 'invoice_line', '_parent_term.quantity')
    def on_change_with_quantity(self, name=None):
        if self.invoice_line:
            return self.invoice_line.quantity
        elif self.term:
            return self.term.quantity
        return 0

    @fields.depends('term', 'invoice_line', '_parent_term.unit')
    def on_change_with_unit(self, name=None):
        if self.invoice_line:
            return self.invoice_line.unit
        elif self.term:
            return self.term.unit
        return None

    @fields.depends('term', 'invoice_line', '_parent_term.unit_price')
    def on_change_with_unit_price(self, name=None):
        if self.invoice_line:
            return self.invoice_line.unit_price
        elif self.term:
            return self.term.unit_price
        return Decimal(0)

    @fields.depends('quantity', 'unit_price', 'currency', 'term', 'invoice_line')
    def on_change_with_amount(self, name=None):
        amount = (Decimal(str(self.quantity or 0))
            * (self.unit_price or Decimal(0)))
        if self.currency:
            return self.currency.round(amount)
        return amount

    def _get_invoice_line_taxes(self) -> dict:
        pool = Pool()
        Tax = pool.get('account.tax')
        Date = pool.get('ir.date')

        amount = (Decimal(str(self.quantity or 0))
            * (self.unit_price or Decimal(0)))
        untaxed_amount = self.currency.round(amount)
        tax_amount = untaxed_amount
        total_amount = untaxed_amount

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
            my_tax = self._get_invoice_line_taxes()
            tax_amount = my_tax['tax_amount'] or Decimal(0)
            total_amount = self.amount + tax_amount
        elif self.term:
            total_amount = self.term.total_amount
            tax_amount = self.term.tax_amount

        result = {
            'tax_amount': tax_amount,
            'total_amount': total_amount,
            }
        for key in list(result.keys()):
            if key not in names:
                del result[key]
        return result

    @fields.depends('term', 'invoice_line', '_parent_term.contract')
    def on_change_with_currency(self, name=None):
        if self.invoice_line and self.invoice_line.currency:
            return self.invoice_line.currency
        elif self.term and self.term.contract and self.term.contract.currency:
            return self.term.contract.currency
        return None


#**********************************************************************
class ContractTermCashFlowContext(ModelView):
    'Contract Term Cash Flow Context'
    __name__ = 'real_estate.contract.term.cash_flow.context'

    company = fields.Many2One('company.company', 'Company', required=True)
    property = fields.Many2One('real_estate.base_object', 'Property',
        domain=[
            ('type', '=', 'property'),
            ('company', '=', Eval('company', -1)),
        ])
    contract = fields.Many2One('real_estate.contract', 'Contract',
        domain=[
            ('company', '=', Eval('company', -1)),
            If(Eval('property', None),
                [('property', '=', Eval('property', None))],
                []),
        ])
    from_date = fields.Date('From Date')
    to_date = fields.Date('To Date')

    @classmethod
    def default_company(cls):
        return Transaction().context.get('company')

    @classmethod
    def default_from_date(cls):
        today = Pool().get('ir.date').today()
        return today.replace(month=1, day=1)

    @classmethod
    def default_to_date(cls):
        return Pool().get('ir.date').today()


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
            ondelete='RESTRICT',
            domain=[('contract', '=', Eval('contract', -1)),
                    ],
            help=("Newly assigned objects only appear here after saving the contract. "
                  "If a recently added object is missing, save first (Ctrl+S), "
                  "then add the term."))

    valid_from = fields.Date('Valid from', required=True)
    valid_to = fields.Date('Valid to',
         states={
            'readonly': ((Eval('rhythm', -1) == 0)),
            })

    last_posting_date = fields.Function(fields.Date('Last Posting Date',
        states={'readonly': True,})
        , 'on_change_with_last_posting_date')
    last_document_date = fields.Function(fields.Date('Last Document Date',
        states={'readonly': True,})
        , 'on_change_with_last_document_date')

    next_document_date = fields.Function(fields.Date('Next Document Date',
        states={'readonly': True,})
        , 'on_change_with_next_document_date')

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

    rhythm_start = fields.Selection('get_rhythm_start', "Rhythm Start",
        sort=False,
        states={
            'invisible': (Eval('term_type', None) == None),
            },
        )

    property = fields.Function(fields.Many2One('real_estate.base_object', 'Property'),
        'on_change_with_property')

    company = fields.Function(fields.Many2One('company.company', 'Company'),
        'on_change_with_company')

    type_of_use = fields.Function(fields.Char("Type of Use"),
        'on_change_with_type_of_use')

    currency = fields.Function(fields.Many2One('currency.currency',
        'Currency'),
        'on_change_with_currency')

    invoice_type = fields.Function(fields.Char("Invoice Type"),
        'on_change_with_invoice_type')

    term_type_m_type = fields.Function(
        fields.Many2One('real_estate.measurement.type', "Term Measurement Type"),
        'on_change_with_term_type_m_type')

    term_measurements = fields.Function(
        fields.One2Many('real_estate.measurement', None, "Measurements"),
        'get_term_measurements', setter='set_term_measurements')

    account = fields.Many2One('account.account', 'Account',
        ondelete='RESTRICT',
        states={
            'invisible': (Eval('term_type', None) == None),
            'readonly': True,
            },)

    quantity = Quantitative(
        "Quantity", unit='unit', digits='unit',
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
            },), 'get_amount')

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
            ],
        depends={'invoice_type'})
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
            ('posting_date', 'ASC NULLS FIRST'),
            ('document_date', 'ASC NULLS FIRST'),
        ],
        states={
                'readonly': True,
                'invisible': (Eval('cash_flow', []) == []),
            })

    ## special data term type with measurement
    _states_term_type_with_m_type= {
            'invisible': (Eval('term_type_m_type', None) == None),
            }

    @classmethod
    def view_attributes(cls):
        return super().view_attributes() + [
            ('/form/notebook/page[@id="page_measurements"]', 'states', cls._states_term_type_with_m_type),
            ]

    @classmethod
    def get_rhythm_type(cls):
        pool = Pool()
        Object = pool.get('real_estate.contract.term.type')
        return Object.fields_get(['rhythm_type'])['rhythm_type']['selection']

    @classmethod
    def get_rhythm_start(cls):
        pool = Pool()
        Object = pool.get('real_estate.contract.term.type')
        return Object.fields_get(['rhythm_start'])['rhythm_start']['selection']

    _RE_CALC_TERM_FIELDS = frozenset({
        'unit_price', 'quantity', 'rhythm', 'rhythm_type', 'rhythm_start',
        'valid_from', 'valid_to', 'term_type',
    })

    @classmethod
    def write(cls, *args):
        super().write(*args)
        if Transaction().context.get('_skip_re_calc'):
            return
        contract_ids = set()
        actions = iter(args)
        for records, values in zip(actions, actions):
            if cls._RE_CALC_TERM_FIELDS & set(values):
                for r in records:
                    if r.contract:
                        contract_ids.add(r.contract.id)
        if contract_ids:
            Contract = Pool().get('real_estate.contract')
            Contract._re_calc_terms(Contract.browse(list(contract_ids)))

    def re_calc(self):
        pool = Pool()
        InvoiceLine = pool.get('account.invoice.line')
        CashFlow = pool.get('real_estate.contract.term.cash_flow')
        invoice_lines = InvoiceLine.search([('term', '=', self.id), ('invoice.state', '!=', 'cancelled')])

        for cash_flow in self.cash_flow:
            CashFlow.delete([cash_flow])

        for invoice_line in invoice_lines:
            is_found = next((e for e in self.cash_flow if e.invoice_line == invoice_line.id), None)
            if is_found is None:
                cash_flow = CashFlow(
                    state='done',
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

            elif is_found is not None and invoice_line.invoice.state == 'cancelled':
                    CashFlow.delete([is_found])

        today = datetime.date.today()
        today_plus_year = today.replace(year=today.year + _re_calc_year)

        self.last_document_date = self.on_change_with_last_document_date()

        my_last_document_date = self.last_document_date
        my_next_document_date = self._next_document_date(calc_document_date=my_last_document_date)
        while my_next_document_date is not None \
            and (my_last_document_date is None or my_last_document_date < my_next_document_date) \
            and self.total_amount != 0 \
            and (not self.valid_from or my_next_document_date >= self.valid_from) \
            and (not self.valid_to or my_next_document_date <= self.valid_to) \
            and my_next_document_date <= today_plus_year:

                cash_flow = CashFlow(
                    state='draft',
                    document_date=my_next_document_date,
                    due_date=self._on_change_with_next_due_date(calc_document_date=my_next_document_date),
                    contract=self.contract.id,
                    term=self.id,
                    property=self.contract.property.id if self.contract else None,
                    company=self.contract.company.id if self.contract else None,
                    quantity=self.quantity,
                    unit=self.unit.id if self.unit else None,
                    unit_price=self.unit_price,
                    )
                cash_flow.save()

                my_last_document_date = my_next_document_date
                my_next_document_date = self._next_document_date(calc_document_date=my_last_document_date)

    def _get_taxes(self) -> dict:
        pool = Pool()
        Tax = pool.get('account.tax')
        Date = pool.get('ir.date')

        if not self.currency:
            return {
                'untaxed_amount': Decimal(0),
                'tax_amount': Decimal(0),
                'total_amount': Decimal(0),
                }

        amount = (Decimal(str(self.quantity or 0))
            * (self.unit_price or Decimal(0)))
        untaxed_amount = self.currency.round(amount)
        tax_amount = untaxed_amount
        total_amount = untaxed_amount

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

    @classmethod
    def validate_fields(cls, instances, fields):
        super().validate_fields(instances, fields)
        for term in instances:
            if 'valid_from' not in fields:
                continue
            if term.valid_from is None or term.contract is None:
                continue
            if term.contract.start_date and term.valid_from < term.contract.start_date:
                raise ValidationError(
                    gettext('real_estate.msg_term_valid_from_before_contract_start').format(
                        term.rec_name,
                        term.valid_from.isoformat(),
                        term.contract.start_date.isoformat()))
            if term.contract.get_effective_end_date() and term.valid_from > term.contract.get_effective_end_date():
                raise ValidationError(
                    gettext('real_estate.msg_term_valid_from_after_contract_end').format(
                        term.rec_name,
                        term.valid_from.isoformat(),
                        term.contract.get_effective_end_date().isoformat()))

    @fields.depends('cash_flow')
    def on_change_with_last_document_date(self, name=None):
        if self.cash_flow:
            done_cash_flows = [cf for cf in self.cash_flow if cf.state == 'done' and
                               (cf.invoice is None or cf.invoice.state != 'cancelled') and cf.document_date is not None]
            if done_cash_flows:
                return max(cf.document_date for cf in done_cash_flows)
        return None

    @fields.depends('cash_flow')
    def on_change_with_last_posting_date(self, name=None):
        if self.cash_flow:
            done_cash_flows = [cf for cf in self.cash_flow if cf.state == 'done' and
                               (cf.invoice is None or cf.invoice.state != 'cancelled') and cf.posting_date is not None]
            if done_cash_flows:
                return max(cf.posting_date for cf in done_cash_flows)
        return None

    @fields.depends(
        'contract', 'sequence',
        '_parent_contract.next_term_sequence', '_parent_contract.c_type')
    def on_change_with_sequence(self, name=None):
        if (self.sequence is not None and self.sequence != 0):
            return self.sequence

        if self.contract is not None and self.contract.next_term_sequence:
            return self.contract.next_term_sequence

        return self.contract.c_type.step_term if self.contract and self.contract.c_type else 1

    @fields.depends(
        'taxes', 'unit_price', 'quantity', 'currency', 'taxes_date', 'contract',
        '_parent_contract.currency')
    def on_change_with_untaxed_amount(self, name=None):
        result = self._get_taxes()
        return result['untaxed_amount'] or Decimal(0)

    @fields.depends(methods=['on_change_with_untaxed_amount'])
    def on_change_with_tax_amount(self, name=None):
        result = self._get_taxes()
        return result['tax_amount'] or Decimal(0)

    @fields.depends(methods=['on_change_with_untaxed_amount'])
    def on_change_with_total_amount(self, name=None):
        result = self._get_taxes()
        return result['total_amount'] or Decimal(0)

    @fields.depends(
        'term_type', 'quantity', 'unit_price', 'currency', 'contract',
        'taxes_deductible_rate',
        'taxes',
        '_parent_contract.c_type',
        methods=['_get_taxes'])
    def on_change_with_amount(self, name=None):
        if self.term_type and self.contract and self.contract.c_type:
            amount = (Decimal(str(self.quantity or 0))
                * (self.unit_price or Decimal(0)))
            if (self.contract.c_type.invoice_type == 'in'
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

    @fields.depends('next_document_date', 'contract', 'rhythm', 'rhythm_type',
                    'unit_price',
                    '_parent_contract.payment_term', '_parent_contract.currency')
    def _on_change_with_next_due_date(self, calc_document_date=None):
        if self.contract and self.contract.payment_term \
            and calc_document_date and self.unit_price:
            payment_term = Pool().get('account.invoice.payment_term')
            term = payment_term(self.contract.payment_term)
            term_lines = term.compute(
                self.unit_price, self.contract.currency, calc_document_date)
            return term_lines[-1][0] if term_lines else calc_document_date
        else:
            return calc_document_date

    @fields.depends('next_document_date', 'contract', 'rhythm', 'rhythm_type',
                    'unit_price',
                    '_parent_contract.payment_term', '_parent_contract.currency',
                    methods=['_on_change_with_next_due_date'])
    def on_change_with_next_due_date(self, name=None):
        return self._on_change_with_next_due_date(calc_document_date=self.next_document_date)

    @fields.depends('rhythm', 'valid_from', 'last_document_date', 'rhythm_type', 'rhythm_start', 'contract',
                    'unit_price', '_parent_contract.start_booking_date')
    def _next_document_date(self, calc_document_date=None):
        def _check_valid_to(i_date: datetime.date):
            if (self.valid_to is not None and self.valid_to < i_date and self.contract.start_booking_date < i_date) \
                or (self.contract.get_effective_end_date() is not None and self.contract.get_effective_end_date() < i_date):
                return self.last_document_date
            else:
                if self.rhythm_start == 'term_start' and i_date is not None:
                    return i_date.replace(day=self.valid_from.day)

                if self.rhythm_start == 'month_end' and i_date is not None:
                    return i_date.replace(day=1) + relativedelta(months=1) - datetime.timedelta(days=1)

                if self.rhythm_start == '15th_month' and i_date is not None:
                    return i_date.replace(day=15)

                return i_date.replace(day=1)

        my_document_Date = calc_document_date if calc_document_date is not None else self.last_document_date

        if my_document_Date is not None:
            if self.rhythm_type == 'monthly':
                return _check_valid_to(my_document_Date + relativedelta(months=self.rhythm))

            elif self.rhythm_type == 'weekly':
                return _check_valid_to(my_document_Date + relativedelta(weeks=self.rhythm))

            elif self.rhythm_type == 'daily':
                if self.rhythm % 365 == 0:
                    return _check_valid_to(my_document_Date + relativedelta(years=int(self.rhythm / 365)))
                if self.rhythm % 30 == 0:
                    return _check_valid_to(my_document_Date + relativedelta(months=int(self.rhythm / 30)))
                return _check_valid_to(my_document_Date + relativedelta(days=self.rhythm))

            elif self.rhythm_type == 'quarterly':
                return _check_valid_to(my_document_Date + relativedelta(months=self.rhythm * 3))

            elif self.rhythm_type == 'annually':
                return _check_valid_to(my_document_Date + relativedelta(years=self.rhythm))

        return self.contract.start_booking_date if (self.contract and self.contract.start_booking_date) else self.valid_from

    @fields.depends('rhythm', 'valid_from', 'last_document_date', 'rhythm_type',
                    'unit_price', 'contract', '_parent_contract.start_booking_date',
                    methods=['_next_document_date'])
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
    def on_change_with_rhythm_start(self, name=None):
        if self.term_type and self.term_type.rhythm_start:
            return self.term_type.rhythm_start
        else:
            return None

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
        results = uom.search([('name', '=', 'Unit')], limit=1)
        if results:
            return results[0].id
        return None

    def _calc_quantity(self):
        if self.term_type and self.term_type.m_type and self.reference_item:
            ref_item = Pool().get('real_estate.contract.item')(self.reference_item)
            total = self._sum_measurements(
                ref_item, self.term_type.m_type, self.next_document_date)
            if total is not None:
                self.quantity = total

    @fields.depends(
        'term_type', 'reference_item', 'next_document_date', 'valid_from',
        'contract', '_parent_contract.start_booking_date')
    def on_change_with_quantity(self, name=None):
        if self.term_type is not None and self.term_type.m_type is not None \
                and self.reference_item is not None:
            ref_item = Pool().get('real_estate.contract.item')(self.reference_item)
            total = self._sum_measurements(
                ref_item, self.term_type.m_type, self.next_document_date)
            if total is not None:
                return total

        if self.term_type and self.term_type.default_quantity:
            return self.term_type.default_quantity

        return Decimal(0)

    @staticmethod
    def _sum_measurements(ref_item, m_type, reference_date):
        """Sum the most recent valid measurement of m_type across all objects
        of the given ContractItem. Returns None when no object has a matching
        measurement so the caller can fall back to the default quantity.

        If m_type is a group, all child types are included in the search.
        If no exact m_type match is found on an object (and m_type is not a
        group), a fallback checks for any measurement with the same unit."""
        if not m_type:
            return None
        MeasurementType = Pool().get('real_estate.measurement.type')
        effective_ids = set(MeasurementType.get_effective_ids(m_type))
        m_type_unit = m_type.unit
        total = None
        for item_obj in (ref_item.objects or []):
            obj = item_obj.object
            if not obj or not obj.measurements:
                continue
            meas_sorted = sorted(
                obj.measurements, key=lambda x: x.valid_from, reverse=True)
            found = False
            for meas in meas_sorted:
                if (meas.m_type and meas.m_type.id in effective_ids and (
                        reference_date is None
                        or meas.valid_from <= reference_date)):
                    total = (total or Decimal(0)) + Decimal(str(meas.value))
                    found = True
                    break
            if not found and m_type_unit and not m_type.is_group:
                for meas in meas_sorted:
                    if (meas.m_type and meas.m_type.unit == m_type_unit and (
                            reference_date is None
                            or meas.valid_from <= reference_date)):
                        total = (total or Decimal(0)) + Decimal(str(meas.value))
                        break
        return total

    @fields.depends('contract', 'taxes', 'term_type', '_parent_contract.c_type')
    def on_change_with_taxes(self, name=None):
        if (self.contract and self.contract.c_type
                and self.term_type and len(self.taxes) == 0):
            ContractTermTypeTax = Pool().get('real_estate.contract.type.tax')
            type_taxes = ContractTermTypeTax.search([
                ('c_type', '=', self.contract.c_type.id),
                ])
            return [tt.tax for tt in type_taxes]
        return list(self.taxes)

    @fields.depends('contract', 'valid_from',
                    'currency', 'property', 'company',
                    'type_of_use',
                    '_parent_contract.start_date', '_parent_contract.currency',
                    '_parent_contract.property', '_parent_contract.company',
                    '_parent_contract.type_of_use')
    def on_change_contract(self, name=None):
        if self.contract is not None and self.valid_from is None:
            self.valid_from = self.contract.start_date
        if self.contract:
            self.currency = self.contract.currency
            self.property = self.contract.property
            self.company = self.contract.company
            self.type_of_use = self.contract.type_of_use

    @fields.depends('contract', '_parent_contract.currency')
    def on_change_with_currency(self, name=None):
        if self.contract:
            return self.contract.currency
        return None

    @fields.depends(
        'contract', 'valid_from', 'valid_to', 'reference_item',
        '_parent_contract.items')
    def on_change_with_reference_item(self, name=None):
        if getattr(self, 'reference_item', None) is None \
          and self.contract and self.contract.items:
            sorted_items = sorted(self.contract.items, key=lambda x: (x.valid_from), reverse=True)

            for item in sorted_items:
                if item.valid_from <= self.valid_from and (item.valid_to is None or item.valid_to >= self.valid_from):
                    return item
        return getattr(self, 'reference_item', None)

    @fields.depends('contract', '_parent_contract.c_type')
    def on_change_with_invoice_type(self, name=None):
        if self.contract and self.contract.c_type:
            return self.contract.c_type.invoice_type
        return None

    @fields.depends('contract', '_parent_contract.property')
    def on_change_with_property(self, name=None):
        if self.contract:
            return self.contract.property
        return None

    @fields.depends('contract', '_parent_contract.company')
    def on_change_with_company(self, name=None):
        if self.contract:
            return self.contract.company
        return None

    @fields.depends('contract', '_parent_contract.type_of_use')
    def on_change_with_type_of_use(self, name=None):
        if self.contract:
            return self.contract.type_of_use
        return None

    @fields.depends('term_type')
    def on_change_with_term_type_m_type(self, name=None):
        if self.term_type and self.term_type.m_type:
            return self.term_type.m_type.id
        return None

    @classmethod
    def get_term_measurements(cls, terms, name):
        pool = Pool()
        Measurement = pool.get('real_estate.measurement')
        result = {term.id: [] for term in terms}
        term_filters = {}
        all_obj_ids = set()
        all_m_type_ids = set()
        for term in terms:
            if not term.term_type or not term.term_type.m_type:
                continue
            if not term.reference_item:
                continue
            effective_ids = set(term.term_type.m_type.get_hierarchy_ids())
            obj_ids = [
                io.object.id
                for io in (term.reference_item.objects or [])
                if io.object
            ]
            if not obj_ids:
                continue
            term_filters[term.id] = (effective_ids, obj_ids)
            all_obj_ids.update(obj_ids)
            all_m_type_ids.update(effective_ids)
        if not all_obj_ids:
            return result
        measurements = Measurement.search([
            ('base_object', 'in', list(all_obj_ids)),
            ('m_type', 'in', list(all_m_type_ids)),
        ])
        meas_index = {}
        for m in measurements:
            meas_index.setdefault((m.m_type.id, m.base_object.id), []).append(m.id)
        for term_id, (effective_ids, obj_ids) in term_filters.items():
            meas_ids = []
            for obj_id in obj_ids:
                for m_type_id in effective_ids:
                    meas_ids.extend(meas_index.get((m_type_id, obj_id), []))
            result[term_id] = meas_ids
        return result

    @classmethod
    def set_term_measurements(cls, records, name, value):
        pass

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
        return [bool_op,
            ('term_type.name',) + tuple(clause[1:]),
            ('term_type.m_type.name',) + tuple(clause[1:]),
        ]
