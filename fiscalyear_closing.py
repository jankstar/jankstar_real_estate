'Year-end closing (Jahresabschluss) as process on the fiscal year'
import datetime

from trytond.model import fields
from trytond.pool import Pool, PoolMeta
from trytond.transaction import Transaction

from .process import _PROCESS_HISTORY, _PROCESS_OPEN


#**********************************************************************
class FiscalYear(metaclass=PoolMeta):
    "Fiscal year as reference object of the process 'year_end_closing'"
    __name__ = 'account.fiscalyear'

    processes_open = fields.One2Many('real_estate.process', 'resource',
        "Processes", filter=_PROCESS_OPEN, readonly=True)
    processes_history = fields.One2Many('real_estate.process', 'resource',
        "Processes", filter=_PROCESS_HISTORY, readonly=True)


#**********************************************************************
class Process(metaclass=PoolMeta):
    "Named step methods of the process 'year_end_closing'"
    __name__ = 'real_estate.process'

    def _fiscalyear(self):
        resource = self.resource
        if resource and resource.__name__ == 'account.fiscalyear':
            return resource
        return None

    def _step_done_fiscalyear_next_exists(self):
        "The fiscal year following the closed one exists"
        FiscalYear = Pool().get('account.fiscalyear')
        fiscalyear = self._fiscalyear()
        if not fiscalyear:
            return False
        return bool(FiscalYear.search([
                    ('company', '=', fiscalyear.company.id),
                    ('start_date', '=',
                        fiscalyear.end_date + datetime.timedelta(days=1)),
                    ], limit=1))

    def _step_done_fiscalyear_contract_moves_posted(self):
        """No draft cash flow line with a document date up to the end of the
        year on a running or terminated contract of the company - the
        periodic posting posts exactly these lines (terms with an amount of
        0 are not posted and do not count)"""
        CashFlow = Pool().get('real_estate.contract.term.cash_flow')
        fiscalyear = self._fiscalyear()
        if not fiscalyear:
            return False
        lines = CashFlow.search([
                ('state', '=', 'draft'),
                ('document_date', '<=', fiscalyear.end_date),
                ('term.contract.company', '=', fiscalyear.company.id),
                ('term.contract.state', 'in', ['running', 'terminated']),
                ])
        return not any(line.term.total_amount for line in lines)

    def _step_done_fiscalyear_no_drafts(self):
        "No draft moves and no draft or validated invoices in the year"
        pool = Pool()
        Move = pool.get('account.move')
        Invoice = pool.get('account.invoice')
        fiscalyear = self._fiscalyear()
        if not fiscalyear:
            return False
        if Move.search([
                    ('company', '=', fiscalyear.company.id),
                    ('state', '=', 'draft'),
                    ('date', '>=', fiscalyear.start_date),
                    ('date', '<=', fiscalyear.end_date),
                    ], limit=1):
            return False
        return not Invoice.search([
                ('company', '=', fiscalyear.company.id),
                ('state', 'in', ['draft', 'validated']),
                ('invoice_date', '>=', fiscalyear.start_date),
                ('invoice_date', '<=', fiscalyear.end_date),
                ], limit=1)

    def _step_done_fiscalyear_oc_documents_confirmed(self):
        "All operating cost documents of the year are confirmed"
        Document = Pool().get('real_estate.oc_document')
        fiscalyear = self._fiscalyear()
        if not fiscalyear:
            return False
        return not Document.search([
                ('company', '=', fiscalyear.company.id),
                ('state', '!=', 'confirmed'),
                ('date', '>=', fiscalyear.start_date),
                ('date', '<=', fiscalyear.end_date),
                ], limit=1)

    def _step_done_fiscalyear_closing_prepared(self):
        """An adjustment period in the year and a journal of type
        'situation' exist (balance non-deferral accounts)"""
        pool = Pool()
        Period = pool.get('account.period')
        Journal = pool.get('account.journal')
        fiscalyear = self._fiscalyear()
        if not fiscalyear:
            return False
        return bool(Period.search([
                    ('fiscalyear', '=', fiscalyear.id),
                    ('type', '=', 'adjustment'),
                    ], limit=1)
            and Journal.search([('type', '=', 'situation')], limit=1))

    def _step_done_fiscalyear_income_balanced(self):
        "All non-deferral (income statement) accounts are balanced to zero"
        pool = Pool()
        Account = pool.get('account.account')
        fiscalyear = self._fiscalyear()
        if not fiscalyear:
            return False
        currency = fiscalyear.company.currency
        with Transaction().set_context(fiscalyear=fiscalyear.id,
                date=None, cumulate=True, journal=None):
            accounts = Account.search([
                    ('company', '=', fiscalyear.company.id),
                    ('type', '!=', None),
                    ('deferral', '=', False),
                    ])
            return all(currency.is_zero(a.balance)
                for a in Account.browse(accounts))

    def _step_done_fiscalyear_periods_closed(self):
        "All periods of the year are closed"
        fiscalyear = self._fiscalyear()
        return bool(fiscalyear and fiscalyear.periods
            and all(p.state == 'closed' for p in fiscalyear.periods))

    def _step_done_fiscalyear_closed(self):
        "The fiscal year is closed"
        fiscalyear = self._fiscalyear()
        return bool(fiscalyear and fiscalyear.state == 'closed')
