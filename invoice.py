from functools import total_ordering

from sql import Column

from trytond.i18n import lazy_gettext, gettext
from trytond.model import Index, Model, ModelSQL, fields
from trytond.pool import Pool, PoolMeta
from trytond.transaction import Transaction
 
from trytond.pyson import Bool, Eval, Id, If

import pdb


class Invoice(metaclass=PoolMeta):
    """Invoice extension for real estate"""
    __name__ = 'account.invoice'

    contract = fields.Many2One('real_estate.contract', 'Contract',
        states={
            'readonly': Eval('state') != 'draft',
            },
        domain=[
            ('company', '=', Eval('company', -1)),
            ]          
        )  # CODE COMMENT: Link to the real estate contract
    
    @classmethod
    def __setup__(cls):
        super(Invoice, cls).__setup__()
        table = cls.__table__()
        cls._sql_indexes.add(
            Index(table,
                (Column(table, 'contract'), Index.Range(order='ASC NULLS FIRST')),
                (table.id, Index.Range(order='ASC NULLS FIRST'))))  


#**********************************************************************
class InvoiceLine(metaclass=PoolMeta):
    """Invoice Line extension for real estate"""
    __name__ = 'account.invoice.line'

    contract = fields.Function(
        fields.Many2One('real_estate.contract', 'Contract'),
        'on_change_with_contract'
    )

    term = fields.Many2One(
        'real_estate.contract.term', 'Term',
        states={
        'readonly': Eval('invoice_state') != 'draft',
            },
         domain=[
             If(Bool(Eval('contract')),
            ('contract', '=', Eval('contract', -1)),
            ()),
            ]       
    )

    @classmethod
    def __setup__(cls):
        super(InvoiceLine, cls).__setup__()
        table = cls.__table__()
        cls._sql_indexes.add(
            Index(table,
                (Column(table, 'term'), Index.Range(order='ASC NULLS FIRST')),
                (table.id, Index.Range(order='ASC NULLS FIRST'))))  

    @fields.depends('company', 'invoice')
    def on_change_with_contract(self):
        if self.invoice and self.invoice.contract:
            return self.invoice.contract
        return None