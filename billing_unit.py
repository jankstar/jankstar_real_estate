'Billing Unit'
from trytond.model import (sequence_ordered,
    DeactivableMixin, ModelSQL, ModelView, Workflow, fields)
from trytond.model.exceptions import ValidationError
from trytond.exceptions import UserWarning
from trytond.i18n import gettext
from trytond.pool import Pool
from trytond.transaction import Transaction
from trytond.pyson import Bool, Eval, If
from trytond.modules.currency.fields import Monetary

from dateutil.relativedelta import relativedelta

import datetime
from decimal import Decimal, ROUND_HALF_UP

import logging

logger = logging.getLogger(__name__)


class InvalidCalculationMethod(ValidationError):
    pass
class InvalidExternalBillingRule(ValidationError):
    pass
class SelectionWarning(UserWarning):
    pass

#**********************************************************************
class CostCategoryGroup(DeactivableMixin, sequence_ordered(), ModelSQL, ModelView):
    "Cost Category Group, grouping of cost types for reporting and analysis purposes, e.g. heating, water, etc."
    __name__ = 'real_estate.cost_category_group'

    name = fields.Char("Name", required=True, translate=True)

#**********************************************************************
class CostType(DeactivableMixin, sequence_ordered(), ModelSQL, ModelView):
    """Cost Type, e.g. heating, water, common electricity, etc."""
    __name__ = 'real_estate.cost_type'

    name = fields.Char("Name", required=True, translate=True)
    comment = fields.Text("Comment")
    no_print = fields.Boolean("No Print")
    category_group = fields.Many2One(
        'real_estate.cost_category_group', "Category Group",
        ondelete='SET NULL')
    reading_pre_days = fields.Integer("Valid Reading Pre-Days",
        help="Days before the target date within which a meter reading is accepted.")
    reading_post_days = fields.Integer("Valid Reading Post-Days",
        help="Days after the target date within which a meter reading is accepted.")

    @staticmethod
    def default_reading_pre_days():
        return 7

    @staticmethod
    def default_reading_post_days():
        return 7

#**********************************************************************
class BillingUnit(Workflow, DeactivableMixin, sequence_ordered(), ModelSQL, ModelView):
    """Billing Unit, e.g. operating cost settlement for a year, WEG annual statement, etc."""
    __name__ = 'real_estate.billing_unit'
    __rec_name__ = 'name'

    company = fields.Function(fields.Many2One('company.company', 'Company'),
        'on_change_with_company')

    property = fields.Many2One('real_estate.base_object',
        "Property", required=True, path='path', ondelete='CASCADE',
        states={
            'readonly': Eval('state') != 'draft',
            },
        domain=[
            ('type', '=', 'property'),],)

    collective_billing = fields.Function(fields.Boolean('Collective Billing'),
        'on_change_with_collective_billing')

    is_next_billing = fields.Function(fields.Boolean('Is Next Billing'),
        'on_change_with_is_next_billing')

    start_date = fields.Date('Start Date',
        states={
            'readonly': ((Eval('state') != 'draft')),
            },
        required=True,
        domain=[If(Bool(Eval('end_date')), ('start_date', '<=', Eval('end_date', None)), ())],
        )

    end_date = fields.Function(fields.Date('End Date'),
        'on_change_with_end_date', searcher='search_end_date')

    calculation_method = fields.Selection([
        ('rental_apartment', 'Rental Apartment'),
        ('WEG_billing', 'WEG Billing'),
        ], "Calculation Method", sort=False,
        states={'readonly': Eval('state') != 'draft'},
        help=(
            "Rental Apartment: Operating cost settlement for residential tenancies under §§ 1–2 BetrKV. "
            "Cost shares are allocated to tenants based on floor area, consumption, or number of occupants. "
            "Advance payments made by tenants are offset; the result is a credit or additional charge per tenant.\n"
            "WEG Billing: Annual statement for condominium owner associations under § 28 WEG. "
            "Total costs are distributed among owners according to their co-ownership shares (MEA). "
            "Paid maintenance fees are offset; reserve fund contributions and non-allocable costs "
            "remain with the individual owner."
        ),
        )

    external_billing = fields.Boolean('External Billing',
        states={'readonly': Eval('state') != 'draft'},
        help=(
            "If set, all settlement units must use 'Allocation from external billing'. "
            "The allocation rule on each settlement unit is locked accordingly."
        ))

    billing_type = fields.Selection([
        ('planned_billing', 'Planned Billing'),
        ('actual_billing', 'Actual Billing'),
        ], "Billing Type", sort=False,
        states={'readonly': Eval('state') != 'draft'},
        help=(
            "Planned Billing: Settlement based on all invoice lines that have not been cancelled, "
            "including amounts that are still open (unpaid). "
            "Suitable for operating cost settlements where all costs incurred in a period are to be "
            "taken into account regardless of payment receipt.\n"
            "Actual Billing: Only invoice lines that have actually been paid (status 'paid') are included. "
            "Suitable for WEG annual statements or cash-based accounting where only "
            "payments actually received form the basis for settlement."
        ),
        )


    currency = fields.Function(fields.Many2One('currency.currency', 'Currency'), 'on_change_with_currency')

    description = fields.Char('Description', required=True)

    name = fields.Function(fields.Char("Name"), 'on_change_with_name',
        searcher='name_search')

    state = fields.Selection([
            ('draft', 'Draft'),
            ('approved', 'Approved'),
            ('selection', 'Selection'),
            ('value_share', 'Value Share'),
            ('ready_for_billing', 'Ready for Billing'),
            ('billed', 'Billed'),
            ], "State", sort=False,
            )

    sub_state = fields.Function(fields.Selection('get_sub_states', "Sub State"), 'on_change_with_sub_state')

    term_types_of_use = fields.MultiSelection(
            'get_term_types_of_use', "Term Types",
            help="The term type which can use this billing unit.")

    settlement_units = fields.One2Many('real_estate.settlement_unit', 'billing_unit', 'Settlement Units',
            states={'readonly': Eval('state') != 'draft'},
            )

    invoice_lines = fields.Function(fields.One2Many('account.invoice.line', None, 'Invoice Lines'),
        'on_change_with_invoice_lines', setter='set_invoice_lines')

    cost_shares = fields.Function(fields.One2Many('real_estate.cost_share', None, 'Cost Shares'),
        'on_change_with_cost_shares', setter='set_cost_shares')

    cash_flow_lines = fields.Function(fields.One2Many('real_estate.contract.term.cash_flow', None, 'Advanced Payment'),
        'on_change_with_cash_flow_lines', setter='set_cash_flow_lines')

    settlment_results = fields.One2Many('real_estate.settlement_result', 'billing_unit', 'Settlement Results')

    moves = fields.One2Many('real_estate.billing_unit.moves', 'billing_unit', 'Moves')

    billing_run_id = fields.Char('Billing Run ID', readonly=True)

    sum_planned_costs = fields.Function(
        Monetary('Sum Planned Costs', currency='currency', digits='currency'),
        'on_change_with_sum_planned_costs')

    sum_actual_costs = fields.Function(
        Monetary('Sum Actual Costs', currency='currency', digits='currency'),
        'on_change_with_sum_actual_costs')

    sum_actual_cost_by_owner = fields.Function(
        Monetary('Sum Actual Cost by Owner', currency='currency', digits='currency'),
        'on_change_with_sum_actual_cost_by_owner')

    sum_actual_cost_by_allocation = fields.Function(
        Monetary('Sum Actual Cost by Allocation', currency='currency', digits='currency'),
        'on_change_with_sum_actual_cost_by_allocation')

    sum_advanced_payment = fields.Function(
        Monetary('Sum Advanced Payment', currency='currency', digits='currency'),
        'on_change_with_sum_advanced_payment')

    sum_refund_receivable = fields.Function(
        Monetary('Sum Refund/Receivable', currency='currency', digits='currency'),
        'on_change_with_sum_refund_receivable')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._transitions |= set((
            ('draft', 'approved'),
            ('approved', 'selection'),
            ('selection', 'value_share'),
            ('value_share', 'ready_for_billing'),
            ('ready_for_billing', 'billed'),
            ('ready_for_billing', 'value_share'),
            ('ready_for_billing', 'selection'),
            ('billed', 'value_share'),
            ))

        cls._buttons.update({
                'approved': {
                    'invisible': ~Eval('state').in_(['draft']),
                    'depends': ['state'],
                    },
                'selection': {
                    'invisible': Eval('state').in_(['draft', 'billed']),
                    'depends': ['state'],
                    },
                'compute_value_shares_button': {
                    'invisible': ~Eval('state').in_(
                        ['selection', 'value_share', 'ready_for_billing']),
                    'depends': ['state'],
                    },
                'compute_settlement_result': {
                    'invisible': ~Eval('state').in_(
                        ['value_share', 'ready_for_billing']),
                    'depends': ['state'],
                    },
                'check_ready_for_billing': {
                    'invisible': ~(Eval('state') == 'value_share'),
                    'depends': ['state'],
                    },
                'billing_wizard': {
                    'invisible': ~(Eval('state') == 'ready_for_billing') | Bool(Eval('collective_billing')),
                    'depends': ['state', 'collective_billing'],
                    },
                'cancel': {
                    'invisible': ~Eval('state').in_(['billed']) | Bool(Eval('collective_billing')),
                    'depends': ['state', 'collective_billing'],
                    },
                })

    @classmethod
    def delete(cls, billing_units):
        for billing_unit in billing_units:
            if billing_unit.state != 'draft':
                raise ValidationError(gettext(
                    'real_estate.msg_billing_unit_delete_not_draft',
                    name=billing_unit.name,
                    state=billing_unit.state))
        super().delete(billing_units)

    @classmethod
    @ModelView.button
    @Workflow.transition('approved')
    def approved(cls, billing_units):
        for billing_unit in billing_units:
            if not billing_unit.settlement_units:
                raise ValidationError(gettext(
                    "real_estate.msg_settlement_units_error").format(
                    billing_unit.name))
            if not billing_unit.term_types_of_use:
                raise ValidationError(gettext(
                    "real_estate.msg_term_types_of_use").format(
                    billing_unit.name))
            billing_unit.add_log('state_change',
                'billing unit state changed to approved')
            billing_unit.state = 'approved'
            billing_unit.save()

    @classmethod
    @ModelView.button
    def selection(cls, billing_units):
        pool = Pool()
        SettlementUnit = pool.get('real_estate.settlement_unit')
        SettlementResult = pool.get('real_estate.settlement_result')
        Warning = pool.get('res.user.warning')

        for billing_unit in billing_units:
            if billing_unit.state in ('draft', 'billed'):
                raise ValidationError(gettext(
                    'real_estate.msg_selection_invalid_state',
                    name=billing_unit.name,
                    state=billing_unit.state))

            existing_results = SettlementResult.search([
                ('billing_unit', '=', billing_unit.id)])
            if existing_results:
                key = Warning.format('selection_reset', [billing_unit])
                if Warning.check(key):
                    raise SelectionWarning(key, gettext(
                        'real_estate.msg_selection_reset_warning',
                        name=billing_unit.name))
                SettlementResult.delete(existing_results)
                billing_unit.add_log('selection',
                    f'Deleted {len(existing_results)} settlement result(s)'
                    f' before re-selection.')

            for su in billing_unit.settlement_units:
                su.selection()
            sus = SettlementUnit.browse(
                [su.id for su in billing_unit.settlement_units])
            # no_allocation SUs create no cost_shares (sub_state stays
            # 'preparation') — they count as done for the transition check.
            all_selection = all(
                su.sub_state == 'selection'
                or su.allocation_rule == 'no_allocation'
                for su in sus)
            if all_selection and billing_unit.state in ('approved', 'selection',
                    'value_share'):
                billing_unit.add_log('state_change',
                    'billing unit state changed to selection')
                billing_unit.state = 'selection'
            billing_unit.save()

    @classmethod
    @ModelView.button
    def compute_value_shares_button(cls, billing_units):
        pool = Pool()
        SettlementUnit = pool.get('real_estate.settlement_unit')
        SettlementResult = pool.get('real_estate.settlement_result')
        Warning = pool.get('res.user.warning')

        for billing_unit in billing_units:
            existing_results = SettlementResult.search([
                ('billing_unit', '=', billing_unit.id)])
            if existing_results:
                key = Warning.format('value_share_reset', [billing_unit])
                if Warning.check(key):
                    raise SelectionWarning(key, gettext(
                        'real_estate.msg_value_share_reset_warning',
                        name=billing_unit.name))
                SettlementResult.delete(existing_results)
                billing_unit.add_log('compute_value_shares',
                    f'Deleted {len(existing_results)} settlement result(s)'
                    f' before recomputing value shares.')

            for su in billing_unit.settlement_units:
                su.compute_value_shares()
            sus = SettlementUnit.browse(
                [su.id for su in billing_unit.settlement_units])
            # Check explicitly for error sub_state before setting value_share
            error_sus = [su for su in sus if su.sub_state == 'error']
            if error_sus:
                billing_unit.add_log('compute_value_shares',
                    f'Cannot set value_share: {len(error_sus)} settlement unit(s) '
                    f'have sub_state error: '
                    + ', '.join(su.name or str(su.id) for su in error_sus))
                billing_unit.save()
                continue
            # no_allocation SUs never reach sub_state 'value_share' — treat as done
            all_value_share = all(
                su.sub_state == 'value_share'
                or su.allocation_rule == 'no_allocation'
                for su in sus)
            if all_value_share:
                billing_unit.add_log('state_change',
                    'billing unit state changed to value_share')
                billing_unit.state = 'value_share'
            billing_unit.save()

    @classmethod
    def _check_chronological_order(cls, billing_units, check_collective=False):
        by_property = {}
        for bu in billing_units:
            by_property.setdefault(bu.property.id, []).append(bu)

        for prop_id, units in by_property.items():
            prop = units[0].property
            all_units = cls.search([('property', '=', prop_id)])
            min_start = min(u.start_date for u in units)

            blocking = [u for u in all_units
                        if u.start_date < min_start and u.state != 'billed']
            if blocking:
                raise ValidationError(gettext(
                    'real_estate.msg_billing_unit_chronological_order',
                    names=', '.join(u.name for u in blocking)))

            if check_collective and prop.collective_billing:
                same_start = [u for u in all_units
                              if u.start_date == min_start and u.state != 'billed']
                missing = [u for u in same_start
                           if u.id not in {b.id for b in units}]
                if missing:
                    raise ValidationError(gettext(
                        'real_estate.msg_billing_unit_collective_required',
                        names=', '.join(u.name for u in missing)))

    @classmethod
    def _check_invoices_posted(cls, billing_units):
        """Verify all invoices in the settlement period are posted.

        cash_flow_lines: advance payment invoices from contracts.
        invoice_lines:   operating cost invoices from settlement units.
        Raises ValidationError listing each unposted invoice.
        """
        CashFlowLine = Pool().get('real_estate.contract.term.cash_flow')

        for bu in billing_units:
            seen_invoices = set()
            lines_info = []

            # Advance payment lines: use _cash_flow_base_domain() (shared logic)
            # and search only for unposted states — cash_flow_lines already
            # filters for posted/paid so we must query the complement separately.
            base_domain = bu._cash_flow_base_domain()
            if base_domain is not None:
                unposted_cf = CashFlowLine.search(
                    base_domain + [('invoice_state', 'in', ['draft', 'validated'])])
                for line in unposted_cf:
                    inv = line.invoice
                    inv_key = inv.id if inv else id(line)
                    if inv_key in seen_invoices:
                        continue
                    seen_invoices.add(inv_key)
                    contract_num = (line.term.contract.contract_number
                        if line.term and line.term.contract else '?')
                    if inv:
                        inv_num = inv.number or inv.reference or f'ID {inv.id}'
                        inv_state = inv.state
                    else:
                        inv_num = '—'
                        inv_state = line.invoice_state or 'draft'
                    date_str = (f'{line.document_date:%Y-%m-%d}'
                        if line.document_date else '?')
                    lines_info.append(
                        f'  {contract_num} / {date_str}'
                        f' / {inv_num} [{inv_state}]')

            # Operating cost invoice lines: use bu.invoice_lines directly
            for line in (bu.invoice_lines or []):
                inv = line.invoice if line.invoice else None
                if not inv or inv.state in ('posted', 'paid', 'cancelled'):
                    continue
                if inv.id in seen_invoices:
                    continue
                seen_invoices.add(inv.id)
                su_name = (line.settlement_unit.name
                    if line.settlement_unit else '?')
                inv_num = inv.number or inv.reference or f'ID {inv.id}'
                date_str = (f'{inv.invoice_date:%Y-%m-%d}'
                    if inv.invoice_date else '?')
                lines_info.append(
                    f'  {su_name} / {date_str}'
                    f' / {inv_num} [{inv.state}]')

            if not lines_info:
                continue

            raise ValidationError(gettext(
                'real_estate.msg_billing_unit_invoices_not_posted',
                name=bu.name,
                details='\n'.join(lines_info)))

    @classmethod
    @ModelView.button
    @Workflow.transition('ready_for_billing')
    def check_ready_for_billing(cls, billing_units):
        """Validate billing unit is fully ready for billing and set state accordingly.

        Checks: all invoices posted, settlement results exist, no zero actual
        costs, and settlement result sum matches cost share sum.
        """
        pool = Pool()
        SettlementResult = pool.get('real_estate.settlement_result')

        cls._check_invoices_posted(billing_units)

        for bu in billing_units:
            # Check all settlement units have sub_state 'value_share' (no_allocation exempt)
            error_sus = [su for su in (bu.settlement_units or [])
                if su.sub_state == 'error']
            if error_sus:
                details = '\n'.join(
                    f'  {su.name or str(su.id)}' for su in error_sus)
                raise ValidationError(gettext(
                    'real_estate.msg_billing_unit_settlement_unit_errors',
                    name=bu.name, details=details))

            not_value_share = [su for su in (bu.settlement_units or [])
                if su.sub_state not in ('value_share',)
                and (su.allocation_rule or '') != 'no_allocation']
            if not_value_share:
                details = '\n'.join(
                    f'  {su.name or str(su.id)} [{su.sub_state or "?"}]'
                    for su in not_value_share)
                raise ValidationError(gettext(
                    'real_estate.msg_billing_unit_settlement_units_not_ready',
                    name=bu.name, details=details))

            results = SettlementResult.search([
                ('billing_unit', '=', bu.id),
                ('state', '=', 'approved'),
            ])

            if not results:
                raise ValidationError(gettext(
                    'real_estate.msg_billing_unit_no_settlement_results',
                    name=bu.name))

            zero_results = [
                r for r in results
                if not r.actual_costs or r.actual_costs == Decimal(0)
            ]
            if zero_results:
                details = '\n'.join(
                    '  ' + (r.contract.rec_name if r.contract
                        else (r.base_object.rec_name if r.base_object else '?'))
                    for r in zero_results)
                raise ValidationError(gettext(
                    'real_estate.msg_billing_unit_zero_actual_costs',
                    name=bu.name,
                    details=details))

            if not bu.external_billing:
                sr_sum = sum(r.actual_costs or Decimal(0) for r in results)
                cs_sum = sum(
                    cs.actual_costs or Decimal(0)
                    for cs in bu._get_cost_shares())
                if sr_sum != cs_sum:
                    raise ValidationError(gettext(
                        'real_estate.msg_billing_unit_sum_mismatch',
                        name=bu.name,
                        sr_sum=str(sr_sum),
                        bu_sum=str(cs_sum)))

    @classmethod
    @ModelView.button_action('real_estate.wizard_billing_unit')
    def billing_wizard(cls, billing_units):
        pass

    @classmethod
    @Workflow.transition('billed')
    def billing(cls, billing_units, invoice_state='draft', invoice_date=None):
        pool = Pool()
        Invoice = pool.get('account.invoice')
        InvoiceLine = pool.get('account.invoice.line')
        AccountMove = pool.get('account.move')
        AccountMoveLine = pool.get('account.move.line')
        SettlementResult = pool.get('real_estate.settlement_result')
        BillingUnitMoves = pool.get('real_estate.billing_unit.moves')
        AccountConfiguration = pool.get('account.configuration')
        CashFlowLine = pool.get('real_estate.contract.term.cash_flow')
        Date = pool.get('ir.date')

        cls._check_chronological_order(billing_units, check_collective=True)

        # Determine scope: if collective_billing, expand to all BUs with same start_date
        scope_units = list(billing_units)
        if billing_units and billing_units[0].property.collective_billing:
            prop = billing_units[0].property
            min_start = min(bu.start_date for bu in billing_units)
            all_same_start = cls.search([
                ('property', '=', prop.id),
                ('start_date', '=', min_start),
                ('state', '!=', 'billed'),
            ])
            not_ready = [bu for bu in all_same_start
                if bu.state != 'ready_for_billing']
            if not_ready:
                raise ValidationError(gettext(
                    'real_estate.msg_billing_unit_not_ready',
                    name=prop.rec_name,
                    next_date=str(min_start),
                    details='\n'.join(
                        f'  {bu.name} [{bu.state}]' for bu in not_ready)))
            scope_units = all_same_start

        billing_run_id = (
            f"{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"
            f"-U{Transaction().user}")

        # Refuse billing if any settlement unit has error sub_state
        error_units = [bu for bu in scope_units if bu.sub_state == 'error']
        if error_units:
            raise ValidationError(gettext(
                'real_estate.msg_billing_unit_has_errors',
                names=', '.join(bu.name for bu in error_units)))

        # Verify all advance payment invoices in the settlement period are posted
        cls._check_invoices_posted(scope_units)

        cls.write(scope_units, {'billing_run_id': billing_run_id})

        billing_date = invoice_date or Date.today()
        config = AccountConfiguration(1)

        # Collect all approved settlement results for scope_units
        all_results = SettlementResult.search([
            ('billing_unit', 'in', [bu.id for bu in scope_units]),
            ('state', '=', 'approved'),
        ])

        # Group by contract (or base_object for vacancy)
        by_contract = {}
        vacancy_results = []
        for result in all_results:
            if result.contract:
                key = result.contract.id
                by_contract.setdefault(key, []).append(result)
            else:
                vacancy_results.append(result)

        # --- Process contracts ---
        for contract_id, results in by_contract.items():
            contract = results[0].contract
            c_type = contract.c_type

            total_actual = sum(r.actual_costs or Decimal(0) for r in results)
            total_advanced = sum(r.advanced_payment or Decimal(0) for r in results)
            refund_receivable = total_actual - total_advanced

            # Skip if truly nothing to post
            if total_actual == Decimal(0) and total_advanced == Decimal(0):
                SettlementResult.write(results, {'state': 'billed'})
                continue

            invoice_type = c_type.invoice_type

            if invoice_type == 'out':
                header_account = (
                    c_type.account.id
                    if c_type.account
                    else contract.contractual_partner.account_receivable.id
                    if contract.contractual_partner.account_receivable
                    else config.default_account_receivable.id)
            else:
                header_account = (
                    c_type.account.id
                    if c_type.account
                    else contract.contractual_partner.account_payable.id
                    if contract.contractual_partner.account_payable
                    else config.default_account_payable.id)

            invoice_lines = []
            moves_by_result = {}  # result.id -> (adv_line, cost_line)

            # Two lines per settlement result: advance payment dissolution + actual costs
            for r in results:
                r_advanced = r.advanced_payment or Decimal(0)
                r_actual   = r.actual_costs or Decimal(0)
                period_r   = (f"{r.start_date} – {r.end_date}"
                              if r.start_date and r.end_date else '')
                obj_name   = (r.base_object.rec_name
                              if r.base_object else r.billing_unit.name)
                term_taxes = ([t.id for t in r.term.taxes]
                              if r.term and r.term.taxes else [])

                # Line 1: Advance payment dissolution
                adv_line = None
                if r_advanced != Decimal(0) and r.term and r.term.account:
                    adv_amount = -r_advanced if invoice_type == 'out' else r_advanced
                    adv_line = InvoiceLine(
                        type='line',
                        company=contract.company.id,
                        party=contract.contractual_partner.id,
                        invoice_type=invoice_type,
                        description=f"{r.term.name} — Advance Payment {period_r}",
                        quantity=Decimal(1),
                        unit_price=adv_amount,
                        account=r.term.account.id,
                        taxes=term_taxes,
                        currency=contract.currency.id,
                        contract=contract.id,
                        term=r.term.id,
                        billing_unit=r.billing_unit.id,
                        base_object=r.base_object.id if r.base_object else None,
                        assignment_control='settlement_result_contract',
                    )
                    adv_line.save()
                    invoice_lines.append(adv_line)

                # Line 2: Actual costs (revenue/expense account from ContractType)
                cost_line = None
                if r_actual != Decimal(0) and c_type.account_billing_unit:
                    cost_amount = r_actual if invoice_type == 'out' else -r_actual
                    cost_line = InvoiceLine(
                        type='line',
                        company=contract.company.id,
                        party=contract.contractual_partner.id,
                        invoice_type=invoice_type,
                        description=f"{obj_name} — {c_type.oc_mark or 'Operating Costs'} {period_r}",
                        quantity=Decimal(1),
                        unit_price=cost_amount,
                        account=c_type.account_billing_unit.id,
                        taxes=term_taxes,
                        currency=contract.currency.id,
                        contract=contract.id,
                        billing_unit=r.billing_unit.id,
                        base_object=r.base_object.id if r.base_object else None,
                        assignment_control='settlement_result_contract',
                    )
                    cost_line.save()
                    invoice_lines.append(cost_line)

                moves_by_result[r.id] = (adv_line, cost_line)

            if not invoice_lines:
                SettlementResult.write(results, {'state': 'billed'})
                continue

            period_str = (f"{min(r.start_date for r in results if r.start_date)}"
                          f" – {max(r.end_date for r in results if r.end_date)}")

            invoice = Invoice(
                company=contract.company.id,
                type=invoice_type,
                party=contract.contractual_partner.id,
                invoice_date=billing_date,
                journal=c_type.account_journal.id,
                account=header_account,
                invoice_address=contract.invoice_address,
                currency=contract.currency.id,
                payment_term=(contract.payment_term.id
                              if contract.payment_term else None),
                description=f"{c_type.oc_mark or 'Operating Cost Settlement'} {period_str}",
                reference=contract.contract_number,
                lines=invoice_lines,
                contract=contract,
            )
            Invoice.save([invoice])
            if invoice_state == 'posted':
                Invoice.post([invoice])

            for r in results:
                adv_line, cost_line = moves_by_result.get(r.id, (None, None))
                base = {
                    'billing_unit': r.billing_unit.id,
                    'settlement_result': r.id,
                    'property': r.billing_unit.property.id,
                    'contract': contract.id,
                    'billing_run_id': billing_run_id,
                }
                if adv_line:
                    BillingUnitMoves.create([{
                        **base,
                        'moves_advanced_payment': adv_line.id,
                    }])
                if cost_line:
                    BillingUnitMoves.create([{
                        **base,
                        'moves_actual_costs': cost_line.id,
                    }])

            SettlementResult.write(results, {
                'state': 'billed',
                'invoice': invoice.id,
            })

            for bu in scope_units:
                bu.add_log('billing',
                    f"Invoice {invoice.id} created for contract "
                    f"{contract.contract_number} ({invoice_type}).")

        # --- Process vacancy (no contract) ---
        if vacancy_results:
            vacancy_account = config.re_account_allocation_by_owner
            vacancy_journal = config.re_journal_billing

            if vacancy_account and vacancy_journal:
                for r in vacancy_results:
                    actual = r.actual_costs or Decimal(0)
                    if actual == Decimal(0):
                        SettlementResult.write([r], {'state': 'billed'})
                        continue

                    period = Pool().get('account.period')
                    period_rec = period.find(
                        r.billing_unit.property.company.id, date=billing_date)

                    obj_name = (r.base_object.rec_name
                        if r.base_object else r.billing_unit.name)
                    move = AccountMove(
                        journal=vacancy_journal.id,
                        date=billing_date,
                        period=period_rec,
                        company=r.billing_unit.property.company.id,
                        description=(
                            f"Vacancy Cost — {r.billing_unit.name}"),
                    )
                    AccountMove.save([move])

                    debit_line = AccountMoveLine(
                        move=move.id,
                        account=vacancy_account.id,
                        debit=actual,
                        credit=Decimal(0),
                        description=f"Vacancy — {obj_name}",
                        base_object=r.base_object.id if r.base_object else None,
                        assignment_control='settlement_result_vacant',
                    )
                    credit_line = AccountMoveLine(
                        move=move.id,
                        account=vacancy_account.id,
                        debit=Decimal(0),
                        credit=actual,
                        description=f"Vacancy — {r.billing_unit.name}",
                        billing_unit=r.billing_unit.id,
                        assignment_control='settlement_result_vacant',
                    )
                    AccountMoveLine.save([debit_line, credit_line])
                    AccountMove.post([move])

                    BillingUnitMoves.create([{
                        'billing_unit': r.billing_unit.id,
                        'settlement_result': r.id,
                        'property': r.billing_unit.property.id,
                        'moves_alloc_by_owner': credit_line.id,
                        'billing_run_id': billing_run_id,
                    }])

                    SettlementResult.write([r], {'state': 'billed'})

            else:
                # No configuration — just mark as billed
                SettlementResult.write(vacancy_results, {'state': 'billed'})

        for bu in scope_units:
            bu.add_log('billing', 'Billing completed.')

    @classmethod
    @ModelView.button
    @Workflow.transition('value_share')
    def cancel(cls, billing_units):
        pool = Pool()
        Invoice = pool.get('account.invoice')
        SettlementResult = pool.get('real_estate.settlement_result')
        BillingUnitMoves = pool.get('real_estate.billing_unit.moves')

        # Expand scope for collective billing (same property, same start_date, state billed)
        scope_units = list(billing_units)
        if billing_units and billing_units[0].property.collective_billing:
            prop = billing_units[0].property
            min_start = min(bu.start_date for bu in billing_units)
            scope_units = cls.search([
                ('property', '=', prop.id),
                ('start_date', '=', min_start),
                ('state', '=', 'billed'),
            ])

        # Collect all invoices linked via BillingUnitMoves
        all_moves = BillingUnitMoves.search([
            ('billing_unit', 'in', [bu.id for bu in scope_units]),
        ])
        invoice_ids = set()
        for m in all_moves:
            if m.moves_advanced_payment and m.moves_advanced_payment.invoice:
                invoice_ids.add(m.moves_advanced_payment.invoice.id)
            if m.moves_actual_costs and m.moves_actual_costs.invoice:
                invoice_ids.add(m.moves_actual_costs.invoice.id)

        # Cancel invoices
        if invoice_ids:
            invoices = Invoice.browse(list(invoice_ids))
            Invoice.cancel(invoices)

        # Delete BillingUnitMoves
        BillingUnitMoves.delete(all_moves)

        # Reset SettlementResults
        results = SettlementResult.search([
            ('billing_unit', 'in', [bu.id for bu in scope_units]),
            ('state', '=', 'billed'),
        ])
        if results:
            SettlementResult.write(results, {'state': 'approved', 'invoice': None})

        # Transition all scope units back to value_share
        cls.write(scope_units, {'state': 'value_share'})
        for bu in scope_units:
            bu.add_log('cancel', 'Billing cancelled.')

    @classmethod
    @ModelView.button
    def compute_settlement_result(cls, billing_units):
        """Compute settlement result based on cost shares and cash flow lines of all settlement units.
        Checks chronological order before processing.
        For each unique combination of contract and base_object, create a settlement result record with
        aggregated planned and actual costs, and allocated advanced payment and refund/receivable amounts."""
        cls._check_chronological_order(billing_units)
        # Reset ready_for_billing back to value_share before recomputing
        ready_units = [bu for bu in billing_units if bu.state == 'ready_for_billing']
        if ready_units:
            cls.write(ready_units, {'state': 'value_share'})
        pool = Pool()
        SettlementResult = pool.get('real_estate.settlement_result')
        CostShare = pool.get('real_estate.cost_share')
        CashFlowLine = pool.get('real_estate.contract.term.cash_flow')
        for billing_unit in billing_units:
            if billing_unit.state not in ('value_share',):
                raise ValidationError(
                    f"Billing unit {billing_unit.name} is not in state 'value_share'.")
            existing = SettlementResult.search(
                [('billing_unit', '=', billing_unit.id)])
            # For external billing: preserve manually entered costs before delete
            preserved_costs = {}
            if existing and billing_unit.external_billing:
                for r in existing:
                    k = (r.contract.id if r.contract else None,
                         r.base_object.id if r.base_object else None)
                    preserved_costs[k] = (
                        r.actual_costs, r.planned_costs)
            if existing:
                SettlementResult.delete(existing)
            groups = {}
            for cs in billing_unit._get_cost_shares():
                if cs.contract:
                    key = ('contract', cs.contract.id,
                        cs.base_object.id if cs.base_object else None)
                elif cs.base_object:
                    key = ('object', cs.base_object.id)
                else:
                    key = None
                if key not in groups:
                    groups[key] = {
                        'contract': cs.contract if cs.contract else None,
                        'base_object': cs.base_object if cs.base_object else None,
                        'start_date': cs.start_date,
                        'end_date': cs.end_date,
                        'planned_costs': Decimal(0),
                        'actual_costs': Decimal(0),
                    }
                g = groups[key]
                if cs.start_date and (
                        g['start_date'] is None or cs.start_date < g['start_date']):
                    g['start_date'] = cs.start_date
                if cs.end_date and (
                        g['end_date'] is None or cs.end_date > g['end_date']):
                    g['end_date'] = cs.end_date
                g['planned_costs'] += cs.planned_costs or Decimal(0)
                g['actual_costs'] += cs.actual_costs or Decimal(0)
            advanced_by_contract = {}
            terms_by_contract = {}
            for line in (billing_unit.cash_flow_lines or []):
                if line.contract:
                    cid = line.contract.id
                    advanced_by_contract[cid] = (
                        advanced_by_contract.get(cid, Decimal(0))
                        + (line.amount or Decimal(0)))
                    if line.term:
                        terms_by_contract.setdefault(cid, set()).add(line.term.id)

            # a) Check for draft invoice items in the settlement period.
            # Reset previous draft-error markers so the check is re-runnable.
            prev_draft_errors = CostShare.search([
                ('settlement_unit.billing_unit', '=', billing_unit.id),
                ('state', '=', 'error'),
                ('error_message', 'like', '[draft]%'),
            ])
            if prev_draft_errors:
                CostShare.write(prev_draft_errors, {
                    'state': 'value_share',
                    'error_message': '',
                })
            all_contract_ids = list({
                cs.contract.id
                for su in billing_unit.settlement_units
                for cs in su.cost_shares
                if cs.contract
            })
            if all_contract_ids:
                draft_domain = [
                    ('term.contract', 'in', all_contract_ids),
                    ('invoice_state', '=', 'draft'),
                ]
                if billing_unit.start_date:
                    draft_domain.append(
                        ('document_date', '>=', billing_unit.start_date))
                if billing_unit.end_date:
                    draft_domain.append(
                        ('document_date', '<=', billing_unit.end_date))
                if billing_unit.term_types_of_use:
                    draft_domain.append(('term.term_type', 'in',
                        [int(t) for t in billing_unit.term_types_of_use]))
                draft_lines = CashFlowLine.search(draft_domain)
                if draft_lines:
                    draft_contract_ids = {
                        dl.contract.id for dl in draft_lines if dl.contract}
                    period_str = (
                        f"{billing_unit.start_date} - {billing_unit.end_date}")
                    for su in billing_unit.settlement_units:
                        error_shares = [
                            cs for cs in su.cost_shares
                            if cs.contract
                            and cs.contract.id in draft_contract_ids
                        ]
                        if error_shares:
                            CostShare.write(error_shares, {
                                'state': 'error',
                                'error_message': (
                                    f'[draft] Draft items in period {period_str}.'
                                    f' Please post or delete before settlement.'),
                            })
                    billing_unit.add_log('compute_settlement_result',
                        f'[draft] {len(draft_lines)} draft item(s) found for '
                        f'{len(draft_contract_ids)} contract(s) in {period_str}.')

            contract_actual_totals = {}
            contract_object_count = {}
            for key, g in groups.items():
                if key and key[0] == 'contract':
                    cid = key[1]
                    contract_actual_totals[cid] = (
                        contract_actual_totals.get(cid, Decimal(0))
                        + g['actual_costs'])
                    contract_object_count[cid] = (
                        contract_object_count.get(cid, 0) + 1)
            for key, g in groups.items():
                contract_id = g['contract'].id if g['contract'] else None
                base_object_id = g['base_object'].id if g['base_object'] else None
                if contract_id:
                    total_adv = advanced_by_contract.get(contract_id, Decimal(0))
                    total_actual = contract_actual_totals.get(contract_id, Decimal(0))
                    if total_actual > 0:
                        adv = (total_adv * g['actual_costs'] / total_actual).quantize(
                            Decimal('0.01'), rounding=ROUND_HALF_UP)
                    else:
                        n = contract_object_count.get(contract_id, 1)
                        adv = (total_adv / n).quantize(
                            Decimal('0.01'), rounding=ROUND_HALF_UP)
                    refund = g['actual_costs'] - adv
                else:
                    adv = None
                    refund = None
                term_ids = terms_by_contract.get(contract_id, set()) if contract_id else set()
                term_id = term_ids.pop() if len(term_ids) == 1 else None
                # Restore externally entered costs if available
                if billing_unit.external_billing and preserved_costs:
                    pk = (contract_id, base_object_id)
                    if pk in preserved_costs:
                        prev_actual, prev_planned = preserved_costs[pk]
                        if prev_actual is not None:
                            g['actual_costs'] = prev_actual
                        if prev_planned is not None:
                            g['planned_costs'] = prev_planned
                        refund = (g['actual_costs'] - adv
                            if adv is not None else None)
                result = SettlementResult(
                    billing_unit=billing_unit.id,
                    contract=contract_id,
                    base_object=base_object_id,
                    term=term_id,
                    start_date=g['start_date'],
                    end_date=g['end_date'],
                    planned_costs=g['planned_costs'],
                    actual_costs=g['actual_costs'],
                    advanced_payment=adv,
                    refund_receivable=refund,
                )
                result.save()
            billing_unit.add_log('compute_settlement_result',
                f'Settlement results computed: {len(groups)} records created.')

    @staticmethod
    def default_state():
        return 'draft'

    @staticmethod
    def default_calculation_method():
        return 'rental_apartment'

    @staticmethod
    def default_billing_type():
        return 'planned_billing'

    @staticmethod
    def default_external_billing():
        return False

    @fields.depends('external_billing', 'settlement_units')
    def on_change_external_billing(self):
        if self.external_billing:
            for su in (self.settlement_units or []):
                su.allocation_rule = 'allocation_from_external_billing'

    @staticmethod
    def get_sub_states():
        pool = Pool()
        CostShare = pool.get('real_estate.cost_share')
        return CostShare.fields_get(['state'])['state']['selection']

    @fields.depends('settlement_units')
    def on_change_with_sub_state(self, name=None):
        if self.settlement_units:
            states = set(settlement_unit.sub_state for settlement_unit in self.settlement_units)
            if len(states) == 1:
                return states.pop()
            elif 'error' in states:
                return 'error'
            elif 'selection' in states:
                return 'selection'
            elif 'value_share' in states:
                return 'value_share'
        return None

    @fields.depends('settlement_units')
    def on_change_with_invoice_lines(self, name=None):
        invoice_lines = []
        for settlement_unit in self.settlement_units:
            invoice_lines.extend(settlement_unit.invoice_lines)
        return invoice_lines

    @fields.depends('settlement_units')
    def on_change_with_cost_shares(self, name=None):
        CostShare = Pool().get('real_estate.cost_share')
        su_ids = [su.id for su in (self.settlement_units or []) if su.id]
        if not su_ids:
            return []
        return CostShare.search([('settlement_unit', 'in', su_ids)])

    def _cash_flow_base_domain(self):
        """Return the base search domain for cash flow lines of this billing unit.

        Covers: contracts from cost shares, billing period, term types of use.
        Does NOT include an invoice_state filter — callers add that themselves.
        Returns None when no contracts are found (nothing to search).
        """
        CostShare = Pool().get('real_estate.cost_share')
        su_ids = [su.id for su in (self.settlement_units or []) if su.id]
        contract_ids = list({
            cs.contract.id
            for cs in CostShare.search([('settlement_unit', 'in', su_ids)])
            if cs.contract
        } if su_ids else set())
        if not contract_ids:
            return None
        domain = [('term.contract', 'in', contract_ids)]
        if self.term_types_of_use:
            domain.append(('term.term_type', 'in',
                [int(t) for t in self.term_types_of_use]))
        if self.start_date:
            domain.append(('document_date', '>=', self.start_date))
        if self.end_date:
            domain.append(('document_date', '<=', self.end_date))
        return domain

    @fields.depends('settlement_units', 'start_date', 'end_date',
            'term_types_of_use', 'billing_type')
    def on_change_with_cash_flow_lines(self, name=None):
        """Return posted/paid cash flow lines for this billing unit.

        planned_billing: posted and paid lines (excludes drafts and cancellations).
        actual_billing:  paid lines only."""
        CashFlowLine = Pool().get('real_estate.contract.term.cash_flow')
        domain = self._cash_flow_base_domain()
        if domain is None:
            return []
        if self.billing_type == 'actual_billing':
            domain.append(('invoice_state', '=', 'paid'))
        else:
            domain.append(('invoice_state', 'in', ['posted', 'paid']))
        return CashFlowLine.search(domain)

    @classmethod
    def set_invoice_lines(cls, records, name, value):
        pass

    @classmethod
    def set_cost_shares(cls, records, name, value):
        pass

    @classmethod
    def set_cash_flow_lines(cls, records, name, value):
        pass

    def _get_cost_shares(self):
        """Returns all cost_shares across settlement_units, or [] if guard fails."""
        if self.state == 'draft':
            return []
        shares = [
            cs
            for su in (self.settlement_units or [])
            for cs in su.cost_shares
        ]
        return shares

    @fields.depends('state', 'settlement_units', 'external_billing', 'settlment_results')
    def on_change_with_sum_planned_costs(self, name=None):
        if self.external_billing:
            return sum(
                (r.planned_costs or Decimal(0))
                for r in (self.settlment_results or []))
        shares = self._get_cost_shares()
        if not shares:
            return Decimal(0)
        return sum((cs.planned_costs or Decimal(0)) for cs in shares)

    @fields.depends('state', 'settlement_units', 'external_billing', 'settlment_results')
    def on_change_with_sum_actual_costs(self, name=None):
        if self.external_billing:
            return sum(
                (r.actual_costs or Decimal(0))
                for r in (self.settlment_results or []))
        shares = self._get_cost_shares()
        if not shares:
            return Decimal(0)
        return sum((cs.actual_costs or Decimal(0)) for cs in shares)

    @fields.depends('state', 'settlement_units', 'external_billing', 'settlment_results')
    def on_change_with_sum_actual_cost_by_owner(self, name=None):
        """Cost shares without contract = costs borne by owner (vacancy/object)."""
        if self.external_billing:
            return sum(
                (r.actual_costs or Decimal(0))
                for r in (self.settlment_results or [])
                if not r.contract)
        shares = self._get_cost_shares()
        if not shares:
            return Decimal(0)
        return sum(
            (cs.actual_costs or Decimal(0))
            for cs in shares
            if not cs.contract
        )

    @fields.depends('state', 'settlement_units', 'external_billing', 'settlment_results')
    def on_change_with_sum_actual_cost_by_allocation(self, name=None):
        """Cost shares with contract = costs allocated to tenants."""
        if self.external_billing:
            return sum(
                (r.actual_costs or Decimal(0))
                for r in (self.settlment_results or [])
                if r.contract)
        shares = self._get_cost_shares()
        if not shares:
            return Decimal(0)
        return sum(
            (cs.actual_costs or Decimal(0))
            for cs in shares
            if cs.contract
        )

    @fields.depends('state', 'settlement_units', 'cash_flow_lines')
    def on_change_with_sum_advanced_payment(self, name=None):
        if not self._get_cost_shares():
            return Decimal(0)
        return sum(
            (line.amount or Decimal(0))
            for line in (self.cash_flow_lines or [])
        )

    @fields.depends('state', 'settlement_units', 'cash_flow_lines',
            'external_billing', 'settlment_results')
    def on_change_with_sum_refund_receivable(self, name=None):
        """Positive = tenant owes additional payment; negative = refund due to tenant."""
        if self.external_billing:
            return sum(
                (r.refund_receivable or Decimal(0))
                for r in (self.settlment_results or []))
        shares = self._get_cost_shares()
        if not shares:
            return Decimal(0)
        allocation = sum(
            (cs.actual_costs or Decimal(0))
            for cs in shares
            if cs.contract
        )
        advanced = sum(
            (line.amount or Decimal(0))
            for line in (self.cash_flow_lines or [])
        )
        return allocation - advanced

    @fields.depends('property')
    def on_change_with_company(self, name=None):
        return self.property.company if self.property else None

    @fields.depends('property')
    def on_change_with_collective_billing(self, name=None):
        return bool(self.property.collective_billing) if self.property else False

    @fields.depends('state', 'start_date', 'property')
    def on_change_with_is_next_billing(self, name=None):
        if self.state not in ('value_share', 'ready_for_billing') \
                or not self.start_date or not self.property:
            return False
        dates = [
            bu.start_date
            for bu in (self.property.billing_units or [])
            if bu.state != 'billed' and bu.start_date
        ]
        next_date = min(dates) if dates else None
        return next_date is not None and self.start_date == next_date

    @classmethod
    def view_attributes(cls):
        return super().view_attributes() + [
            ('/tree', 'visual',
                If(Eval('is_next_billing', False), 'success', ''),
                ['is_next_billing']),
        ]

    def pre_validate(self):
        super().pre_validate()
        self.check_calculation_method()
        self.check_external_billing_rule()

    def check_external_billing_rule(self):
        for su in (self.settlement_units or []):
            if self.external_billing:
                if su.allocation_rule != 'allocation_from_external_billing':
                    raise InvalidExternalBillingRule(
                        f"Settlement unit '{su.rec_name}': allocation rule must be "
                        f"'Allocation from external billing' when external billing is set on the billing unit.")
            else:
                if su.allocation_rule == 'allocation_from_external_billing':
                    raise InvalidExternalBillingRule(
                        f"Settlement unit '{su.rec_name}': allocation rule "
                        f"'Allocation from external billing' is only allowed when external billing is set on the billing unit.")

    @fields.depends('calculation_method', 'start_date')
    def check_calculation_method(self, name=None):
        if self.calculation_method == 'WEG_billing' and (self.start_date.month != 1 or self.start_date.day != 1):
            raise InvalidCalculationMethod(gettext("real_estate.msg_invalid_calculation_method").format(
                self.start_date))

    @fields.depends('start_date')
    def on_change_with_end_date(self, name=None):
        if self.start_date:
            return self.start_date - relativedelta(days=1) + relativedelta(years=1)
        return None

    @classmethod
    def search_end_date(cls, name, clause):
        _, operator, value = clause
        if value is None:
            return [('start_date', operator, None)]
        # end_date = start_date + 1 year - 1 day  →  start_date = end_date + 1 day - 1 year
        start_value = value + relativedelta(days=1) - relativedelta(years=1)
        return [('start_date', operator, start_value)]

    @fields.depends(methods=['_check_calculation_method_notify'])
    def on_change_notify(self):
        notifications = super().on_change_notify()
        notifications.extend(self._check_calculation_method_notify())
        return notifications

    @fields.depends('calculation_method', 'start_date')
    def _check_calculation_method_notify(self):
        if self.calculation_method == 'WEG_billing' and (self.start_date.month != 1 or self.start_date.day != 1):
            logger.warning(f"Invalid calculation method for billing unit {self.id}: start date {self.start_date} is not the first day of the year.")
            yield ('warning',
                   gettext("real_estate.msg_invalid_calculation_method").format(
                       self.start_date))

    @classmethod
    def get_term_types_of_use(cls):
        pool = Pool()
        TermType = pool.get('real_estate.contract.term.type')
        term_types = TermType.search([])
        if term_types:
            result = [(str(ele.id), ele.name) for ele in term_types]
            return result
        return []

    @classmethod
    def search_name(cls, name, offset=0, limit=None, order=None):
        pool = Pool()
        BaseObject = pool.get('real_estate.base_object')
        return BaseObject.search_name(name, offset, limit, order)

    @staticmethod
    def default_start_date():
        return Pool().get('ir.date').today().replace(day=1)

    @fields.depends('start_date', 'end_date', 'description')
    def on_change_with_name(self, name=None):
        if self.start_date and self.end_date:
            return f"{self.description} - {self.start_date} / {self.end_date}"
        return f" ? "

    @fields.depends('company')
    def on_change_with_currency(self, name=None):
        return self.company.currency if self.company else None

    @classmethod
    def name_search(cls, name, clause):
        if clause[1].startswith('!') or clause[1].startswith('not '):
            bool_op = 'AND'
        else:
            bool_op = 'OR'

        return [bool_op,
            ('property.name',) + tuple(clause[1:]),
        ]

    def add_log(self, event, description=None):
        pool = Pool()
        CostLog = pool.get('real_estate.billing_unit.log')
        CostLog.create([{
            'billing_unit': self.id,
            'event': event,
            'description': description or '',
        }])


#**********************************************************************
class BillingUnitLog(ModelSQL, ModelView):
    "Billing Unit log obj"
    __name__ = 'real_estate.billing_unit.log'

    billing_unit = fields.Many2One('real_estate.billing_unit', 'Billing Unit', required=True, ondelete='CASCADE')
    event = fields.Char('Event', required=True)
    description = fields.Text('Description')
    create_date = fields.DateTime('Create Date', readonly=True)
    create_uid = fields.Many2One('res.user', 'User', readonly=True)

    log_date = fields.Function(fields.Date('Date'), 'get_log_date',
        searcher='search_log_date')

    property = fields.Function(
        fields.Many2One('real_estate.base_object', 'Property'),
        'on_change_with_property', searcher='search_property')

    company = fields.Function(
        fields.Many2One('company.company', 'Company'),
        'on_change_with_company', searcher='search_company')

    def get_log_date(self, name):
        if self.create_date:
            return self.create_date.date()
        return None

    @classmethod
    def search_log_date(cls, name, clause):
        _, operator, value = clause
        if value is None:
            return [('create_date', operator, None)]
        if isinstance(value, datetime.date) and not isinstance(value, datetime.datetime):
            if operator == '>=':
                value = datetime.datetime.combine(value, datetime.time.min)
            elif operator == '<=':
                value = datetime.datetime.combine(value, datetime.time.max)
            elif operator == '=':
                return ['AND',
                    ('create_date', '>=', datetime.datetime.combine(value, datetime.time.min)),
                    ('create_date', '<=', datetime.datetime.combine(value, datetime.time.max)),
                ]
        return [('create_date', operator, value)]

    @fields.depends('billing_unit')
    def on_change_with_property(self, name=None):
        if self.billing_unit and self.billing_unit.property:
            return self.billing_unit.property
        return None

    @fields.depends('billing_unit')
    def on_change_with_company(self, name=None):
        if self.billing_unit and self.billing_unit.property:
            return self.billing_unit.property.company
        return None

    @classmethod
    def search_property(cls, name, clause):
        return [('billing_unit.property',) + tuple(clause[1:])]

    @classmethod
    def search_company(cls, name, clause):
        return [('billing_unit.property.company',) + tuple(clause[1:])]


#**********************************************************************
class BillingUnitMoves(ModelSQL, ModelView):
    "Billing Unit Moves — references to generated postings per settlement result"
    __name__ = 'real_estate.billing_unit.moves'

    billing_unit = fields.Many2One('real_estate.billing_unit', 'Billing Unit',
        required=True, ondelete='CASCADE', states={'readonly': True})
    settlement_result = fields.Many2One('real_estate.settlement_result',
        'Settlement Result', ondelete='SET NULL', states={'readonly': True})
    property = fields.Many2One('real_estate.base_object', 'Property',
        domain=[('type', '=', 'property')], states={'readonly': True})
    contract = fields.Many2One('real_estate.contract', 'Contract',
        states={'readonly': True})
    moves_advanced_payment = fields.Many2One('account.invoice.line',
        'Advance Payment Line', ondelete='SET NULL', states={'readonly': True})
    moves_actual_costs = fields.Many2One('account.invoice.line',
        'Actual Costs Line', ondelete='SET NULL', states={'readonly': True})
    moves_alloc_by_owner = fields.Many2One('account.move.line',
        'Owner Allocation Line', ondelete='SET NULL', states={'readonly': True})

    billing_run_id = fields.Char('Billing Run ID', readonly=True)


#**********************************************************************
class BillingUnitContext(ModelView):
    'Billing Unit Context'
    __name__ = 'real_estate.billing_unit.context'

    company = fields.Many2One('company.company', 'Company', required=True)
    property = fields.Many2One('real_estate.base_object', 'Property',
        domain=[
            ('type', '=', 'property'),
            ('company', '=', Eval('company', -1)),
        ])

    @classmethod
    def default_company(cls):
        return Transaction().context.get('company')


class BillingUnitLogContext(ModelView):
    'Billing Unit Log Context'
    __name__ = 'real_estate.billing_unit.log.context'

    company = fields.Many2One('company.company', 'Company', required=True)
    property = fields.Many2One('real_estate.base_object', 'Property',
        domain=[
            ('type', '=', 'property'),
            ('company', '=', Eval('company', -1)),
        ])
    billing_unit = fields.Many2One('real_estate.billing_unit', 'Billing Unit',
        domain=[
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
class BillingUnitMovesContext(ModelView):
    'Billing Unit Moves Context'
    __name__ = 'real_estate.billing_unit.moves.context'

    company = fields.Many2One('company.company', 'Company', required=True)
    property = fields.Many2One('real_estate.base_object', 'Property',
        domain=[
            ('type', '=', 'property'),
            ('company', '=', Eval('company', -1)),
        ])
    billing_unit = fields.Many2One('real_estate.billing_unit', 'Billing Unit',
        domain=[
            If(Eval('property', None),
                [('property', '=', Eval('property', None))],
                []),
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
        today = Pool().get('ir.date').today()
        return today.replace(month=12, day=31)
