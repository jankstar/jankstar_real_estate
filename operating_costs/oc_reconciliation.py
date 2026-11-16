'''Operating cost reconciliation (Betriebskostenabstimmung): per property and
billing period the confirmed assignments, the distribution, the billing and
the cost reclassification are compared with the postings - specification:
specs/spezifikation-betriebskostenzuordnung.md 8'''
import datetime
import json
from decimal import Decimal

from trytond.i18n import gettext
from trytond.model import ModelSQL, ModelView, Unique, fields
from trytond.model.exceptions import ValidationError
from trytond.modules.currency.fields import Monetary
from trytond.pool import Pool
from trytond.pyson import Eval
from trytond.report import Report
from trytond.transaction import Transaction

from . import oc_reclass

ZERO = Decimal(0)

CHECK_STATES = [
    (None, ""),
    ('ok', "OK"),
    ('hints', "Hints"),
    ]

SECTIONS = [
    ('settlement_unit', "Settlement Unit"),
    ('owner', "Owner, Not Allocable"),
    ('other_period', "To Other Periods"),
    ('unassigned', "Not or Not Confirmed Assigned"),
    ('without_property', "Without Property"),
    ('billing_unit', "Billing Unit"),
    ('result', "Settlement Result"),
    ]

COST_SECTIONS = ['settlement_unit', 'owner', 'other_period', 'unassigned',
    'without_property']
BILLING_SECTIONS = ['billing_unit', 'result']


def distribution(assigned, direct, passed_on, shares, total_gross,
        total_net):
    """Columns of a settlement unit (8.2) - pure function.

    assigned: confirmed assignments (gross), direct: part of it assigned
    directly (contract / booked on a rental object), passed_on: costs passed
    on to (-) or received from (+) other settlement units, shares: list of
    (amount, net, tenant) of the cost shares - amount net (option rate 100 %)
    or gross, tenant False for vacancy and flat rate; total_gross/total_net:
    actual costs of the distributing settlement unit.
    Returns the dict tenants, vacancy, commercial_tax, not_distributed."""
    tenants = vacancy = commercial_tax = ZERO
    factor = (Decimal(total_gross) / Decimal(total_net)
        if total_net else Decimal(1))
    for amount, net, tenant in shares:
        amount = amount or ZERO
        if tenant:
            tenants += amount
        else:
            vacancy += amount
        if net:
            commercial_tax += amount * (factor - 1)
    commercial_tax = commercial_tax.quantize(Decimal('0.01'))
    return {
        'tenants': tenants,
        'vacancy': vacancy,
        'commercial_tax': commercial_tax,
        'not_distributed': (assigned + passed_on - direct - tenants
            - vacancy - commercial_tax),
        }


def account_check(booked, reclassified, owner, not_distributed, pending,
        other_periods_out, other_periods_in, unassigned):
    """Account check of the property (8.4) in booked amounts - pure
    function; pending: distributed costs of billing units not billed yet
    (not reclassified yet). Returns rest, expected and difference."""
    rest = booked - reclassified
    expected = (owner + not_distributed + pending + other_periods_out
        - other_periods_in + unassigned)
    return {
        'rest': rest,
        'expected': expected,
        'difference': rest - expected,
        }


def booked_of(line):
    "Booked amount of an assignment line: its share of the document booking"
    document = line.document
    booked = document.amount_booked or ZERO
    if document.amount_net:
        return booked * (line.amount_net or ZERO) / document.amount_net
    if document.amount_gross:
        return booked * (line.amount_gross or ZERO) / document.amount_gross
    return ZERO


#**********************************************************************
class OcReconciliation(ModelSQL, ModelView):
    "Operating Cost Reconciliation"
    __name__ = 'real_estate.oc_reconciliation'

    company = fields.Many2One('company.company', "Company", required=True,
        states={'readonly': Eval('id', -1) >= 0})
    property = fields.Many2One('real_estate.base_object', "Property",
        required=True,
        domain=[
            ('type', '=', 'property'),
            ('company', '=', Eval('company', -1)),
            ],
        states={'readonly': Eval('id', -1) >= 0})
    start_date = fields.Date("Start Date", required=True,
        states={'readonly': Eval('id', -1) >= 0},
        help="Start of the billing period - all billing units of the "
             "property with this start are reconciled together.")
    end_date = fields.Date("End Date", readonly=True)
    billing_units = fields.Function(fields.Many2Many(
            'real_estate.billing_unit', None, None, "Billing Units"),
        'get_billing_units', searcher='search_billing_units')
    currency = fields.Function(fields.Many2One('currency.currency',
            "Currency"), 'on_change_with_currency')
    computed_at = fields.DateTime("Computed at", readonly=True)
    computed_by = fields.Many2One('res.user', "Computed by", readonly=True)
    check_state = fields.Selection(CHECK_STATES, "Check State",
        readonly=True)
    protocol = fields.Text("Protocol", readonly=True)
    cost_lines = fields.One2Many('real_estate.oc_reconciliation.line',
        'reconciliation', "Settlement Units", readonly=True,
        filter=[('section', 'in', COST_SECTIONS)])
    billing_lines = fields.One2Many('real_estate.oc_reconciliation.line',
        'reconciliation', "Billing", readonly=True,
        filter=[('section', 'in', BILLING_SECTIONS)])
    booked = Monetary("Booked on the Property", currency='currency',
        digits='currency', readonly=True,
        help="Documents booked on the property with a date in the period "
             "(booked amount).")
    reclassified = Monetary("Reclassified", currency='currency',
        digits='currency', readonly=True,
        help="Credit cost lines of the cost reclassifications on the "
             "property.")
    rest = Monetary("Rest on the Property", currency='currency',
        digits='currency', readonly=True)
    owner_booked = Monetary("Owner", currency='currency',
        digits='currency', readonly=True)
    not_distributed_booked = Monetary("Not Distributed",
        currency='currency', digits='currency', readonly=True)
    pending_booked = Monetary("Not Reclassified Yet", currency='currency',
        digits='currency', readonly=True,
        help="Distributed costs of the billing units not billed yet - "
             "reclassified with the billing.")
    other_periods_out = Monetary("To Other Periods", currency='currency',
        digits='currency', readonly=True,
        help="Assignments of documents of this period to settlement units "
             "of other periods.")
    other_periods_in = Monetary("From Other Periods", currency='currency',
        digits='currency', readonly=True,
        help="Assignments to the settlement units of this period of "
             "documents dated outside the period.")
    unassigned_booked = Monetary("Not Assigned", currency='currency',
        digits='currency', readonly=True)
    expected = Monetary("Expected Rest", currency='currency',
        digits='currency', readonly=True)
    difference = Monetary("Difference", currency='currency',
        digits='currency', readonly=True,
        help="Rounding of the option rate (E29): mixed rate of the original "
             "invoices against the rate at the billing date - information "
             "only.")
    tax_remaining = Monetary("Input Tax on the Property",
        currency='currency', digits='currency', readonly=True,
        help="Deducted input tax of the documents less the input tax "
             "relieved by the reclassification - information only.")

    @classmethod
    def __setup__(cls):
        super().__setup__()
        t = cls.__table__()
        cls._sql_constraints += [
            ('property_start_unique', Unique(t, t.property, t.start_date),
                'real_estate.msg_oc_reconciliation_unique'),
            ]
        cls._order = [('start_date', 'DESC'), ('property', 'ASC'),
            ('id', 'DESC')]
        cls._buttons.update({
                'compute': {},
                })

    @classmethod
    def default_company(cls):
        return Transaction().context.get('company')

    @fields.depends('company')
    def on_change_with_currency(self, name=None):
        return self.company.currency.id if self.company else None

    @fields.depends('property', 'start_date')
    def on_change_property(self):
        "Propose the start of the latest billing period of the property"
        if not self.property or self.start_date:
            return
        BillingUnit = Pool().get('real_estate.billing_unit')
        units = BillingUnit.search([
                ('property', '=', self.property.id),
                ], order=[('start_date', 'DESC')], limit=1)
        if units:
            self.start_date = units[0].start_date

    def get_rec_name(self, name):
        return f"{self.property.rec_name} {self.start_date}"

    @classmethod
    def search_rec_name(cls, name, clause):
        return [('property.rec_name',) + tuple(clause[1:])]

    def _billing_units(self):
        BillingUnit = Pool().get('real_estate.billing_unit')
        if not self.property or not self.start_date:
            return []
        return BillingUnit.search([
                ('property', '=', self.property.id),
                ('start_date', '=', self.start_date),
                ], order=[('description', 'ASC'), ('id', 'ASC')])

    def get_billing_units(self, name):
        return [b.id for b in self._billing_units()]

    @classmethod
    def search_billing_units(cls, name, clause):
        BillingUnit = Pool().get('real_estate.billing_unit')
        units = BillingUnit.search([('id',) + tuple(clause[1:])
                if clause[0] == name else
                (clause[0][len(name) + 1:],) + tuple(clause[1:])])
        pairs = {(b.property.id, b.start_date) for b in units}
        if not pairs:
            return [('id', '=', -1)]
        return ['OR'] + [[('property', '=', p), ('start_date', '=', s)]
            for p, s in sorted(pairs)]

    @classmethod
    @ModelView.button
    def compute(cls, reconciliations):
        pool = Pool()
        Line = pool.get('real_estate.oc_reconciliation.line')
        Date = pool.get('ir.date')
        for reconciliation in reconciliations:
            Line.delete(list(reconciliation.cost_lines)
                + list(reconciliation.billing_lines))
            values, lines, hints = reconciliation._compute()
            for sequence, line in enumerate(lines, 1):
                line['sequence'] = sequence * 10
                line['reconciliation'] = reconciliation.id
            Line.create(lines)
            values.update({
                    'computed_at': datetime.datetime.now(),
                    'computed_by': Transaction().user,
                    'check_state': 'hints' if hints else 'ok',
                    'protocol': '\n'.join(hints) if hints else gettext(
                        'real_estate.msg_oc_reconciliation_ok',
                        date=str(Date.today())),
                    })
            cls.write([reconciliation], values)

    def _compute(self):
        """Values of the reconciliation, its lines and the hints"""
        pool = Pool()
        Document = pool.get('real_estate.oc_document')
        AssignmentLine = pool.get('real_estate.oc_document.line')
        CostType = pool.get('real_estate.cost_type')

        units = self._billing_units()
        if not units:
            raise ValidationError(gettext(
                    'real_estate.msg_oc_reconciliation_no_billing_unit',
                    property=self.property.rec_name,
                    date=str(self.start_date)))
        start = self.start_date
        end = max(u.end_date for u in units)
        prop = self.property
        sus = [su for u in units for su in u.settlement_units]
        su_ids = {su.id for su in sus}
        hints, lines = [], []

        def in_period(document):
            return document.date and start <= document.date <= end

        confirmed = AssignmentLine.search([
                ('document.property', '=', prop.id),
                ('document.state', '=', 'confirmed'),
                ])
        documents = Document.search([
                ('property', '=', prop.id),
                ('date', '>=', start),
                ('date', '<=', end),
                ])
        on_property = [d for d in documents
            if not d.base_object or d.base_object.type == 'property']

        # Part 1 - settlement units
        lines_by_su = {}
        for line in confirmed:
            if line.settlement_unit and line.settlement_unit.id in su_ids:
                lines_by_su.setdefault(line.settlement_unit.id, []
                    ).append(line)
        received = {}
        for su in sus:
            ref = su.reference_settlement_unit
            if (su.allocation_rule == 'allocation_via_cost_collector'
                    and ref and ref.id in su_ids):
                received.setdefault(ref.id, []).append(su)
        results = {}
        for unit in units:
            for result in _results(unit):
                results[(unit.id, unit._result_key(result))] = result

        def is_direct(line):
            return (line.target == 'contract'
                or bool(line.document.base_object
                    and line.document.base_object.type == 'object'))
        def own_basis(su):
            "Costs distributed by the settlement unit itself (gross)"
            return sum((l.amount_gross or ZERO for s in [su]
                    + received.get(su.id, [])
                    for l in lines_by_su.get(s.id, []) if not is_direct(l)),
                ZERO)

        # external billing: the results of the billing unit are the
        # distribution, shared by the settlement units by their costs
        external_basis = {}
        for su in sus:
            if (su.billing_unit.external_billing
                    and su.allocation_rule != 'allocation_via_cost_collector'):
                external_basis[su.billing_unit.id] = (
                    external_basis.get(su.billing_unit.id, ZERO)
                    + own_basis(su))
        not_distributed_booked = pending_booked = ZERO
        for su in sus:
            su_lines = lines_by_su.get(su.id, [])
            assigned = sum((l.amount_gross or ZERO for l in su_lines), ZERO)
            direct = sum((l.amount_gross or ZERO for l in su_lines
                    if is_direct(l)), ZERO)
            outside = sum((l.amount_gross or ZERO for l in su_lines
                    if not in_period(l.document)), ZERO)
            sources = received.get(su.id, [])
            passing = (su.allocation_rule == 'allocation_via_cost_collector'
                and su.reference_settlement_unit
                and su.reference_settlement_unit.id in su_ids)
            if passing:
                passed_on = -(assigned - direct)
                shares = []
            else:
                passed_on = sum((sum((l.amount_gross or ZERO
                                for l in lines_by_su.get(s.id, [])
                                if not is_direct(l)), ZERO)
                        for s in sources), ZERO)
                shares = []
                basis_total = external_basis.get(su.billing_unit.id)
                if su.billing_unit.external_billing and basis_total:
                    part = own_basis(su) / basis_total
                    for key, result in results.items():
                        if key[0] != su.billing_unit.id:
                            continue
                        flat = bool(result.term and result.term.term_type
                            and result.term.term_type.oc_processing
                            == 'flat_rate')
                        amount = ((result.actual_costs or ZERO)
                            - (result.direct_costs or ZERO)) * part
                        shares.append((amount.quantize(Decimal('0.01')),
                                False, bool(result.contract) and not flat))
                for cs in (su.cost_shares
                        if not su.billing_unit.external_billing else []):
                    result = results.get((su.billing_unit.id, unit_key(cs)))
                    flat = bool(result and result.term
                        and result.term.term_type
                        and result.term.term_type.oc_processing
                        == 'flat_rate')
                    net = su._net_object(cs.base_object, cs.end_date)
                    shares.append((cs.actual_costs or ZERO, bool(net),
                            bool(cs.contract) and not flat))
            columns = distribution(assigned, direct, passed_on, shares,
                (su.actual_costs_gross or ZERO)
                + (su.actual_costs_gross_from_references or ZERO),
                (su.actual_costs_net or ZERO)
                + (su.actual_costs_net_from_references or ZERO))
            not_distributed = columns['not_distributed']
            # booked ratio of the lines distributed by this unit on the
            # property (documents booked on a rental object stay there)
            basis = [l for s in [su] + sources
                for l in lines_by_su.get(s.id, [])
                if not is_direct(l)
                and (not l.document.base_object
                    or l.document.base_object.type == 'property')]
            gross = sum((l.amount_gross or ZERO for l in basis), ZERO)
            booked = sum((booked_of(l) for l in basis), ZERO)
            ratio = (booked / gross) if gross else Decimal(1)
            nd_booked = ZERO if passing else not_distributed * ratio
            not_distributed_booked += nd_booked
            if su.billing_unit.state != 'billed':
                pending_booked += sum((booked_of(l) for l in su_lines
                        if _on_property(l)), ZERO) - nd_booked
            state = 'ok'
            # cents of the separate gross and net distributions
            tolerance = Decimal('0.01') * len(shares)
            if (abs(not_distributed) > tolerance
                    and su.allocation_rule != 'no_allocation'):
                state = 'hint'
                hints.append(gettext(
                        'real_estate.msg_oc_reconciliation_not_distributed',
                        settlement_unit=su.rec_name,
                        amount=_fmt(not_distributed, self.company.currency)))
            lines.append({
                    'section': 'settlement_unit',
                    'name': su.rec_name,
                    'settlement_unit': su.id,
                    'billing_unit': su.billing_unit.id,
                    'assigned': assigned,
                    'assigned_net': sum((l.amount_net or ZERO
                            for l in su_lines), ZERO),
                    'direct': direct,
                    'passed_on': passed_on,
                    'tenants': columns['tenants'],
                    'vacancy': columns['vacancy'],
                    'commercial_tax': columns['commercial_tax'],
                    'not_distributed': not_distributed,
                    'outside_period': outside,
                    'state': state,
                    'record_ids': _ids(oc_lines=su_lines,
                        documents=[l.document for l in su_lines],
                        cost_shares=list(su.cost_shares)),
                    })

        owner = [l for l in confirmed if l.target == 'property'
            and in_period(l.document)]
        lines.append(_simple_line('owner', gettext(
                    'real_estate.msg_oc_reconciliation_owner'), owner))
        other = [l for l in confirmed
            if l.target in ('settlement_unit', 'contract')
            and in_period(l.document)
            and (not l.settlement_unit or l.settlement_unit.id not in su_ids)]
        lines.append(_simple_line('other_period', gettext(
                    'real_estate.msg_oc_reconciliation_other_period'),
                other))
        unassigned = [d for d in documents if d.state != 'confirmed']
        if unassigned:
            hints.append(gettext(
                    'real_estate.msg_oc_reconciliation_unassigned',
                    count=len(unassigned)))
        lines.append({
                'section': 'unassigned',
                'name': gettext(
                    'real_estate.msg_oc_reconciliation_unassigned_name'),
                'assigned': sum((d.amount_gross or ZERO
                        for d in unassigned), ZERO),
                'assigned_net': sum((d.amount_net or ZERO
                        for d in unassigned), ZERO),
                'state': 'hint' if unassigned else 'ok',
                'record_ids': _ids(documents=unassigned),
                })
        without = Document.search([
                ('company', '=', self.company.id),
                ('property', '=', None),
                ('date', '>=', start),
                ('date', '<=', end),
                ])
        if without:
            hints.append(gettext(
                    'real_estate.msg_oc_reconciliation_without_property',
                    count=len(without)))
        lines.append({
                'section': 'without_property',
                'name': gettext(
                    'real_estate.msg_oc_reconciliation_without_property_name'
                    ),
                'assigned': sum((d.amount_gross or ZERO
                        for d in without), ZERO),
                'assigned_net': sum((d.amount_net or ZERO
                        for d in without), ZERO),
                'state': 'hint' if without else 'ok',
                'record_ids': _ids(documents=without),
                })

        # Part 2 - billing and reclassification
        with Transaction().set_context(active_test=False):
            account_ids = CostType.oc_account_ids(self.company.id)
        reclassified = tax_relief = ZERO
        for unit in units:
            unit_lines, unit_reclassified, unit_relief = (
                self._billing_lines(unit, prop, account_ids, hints))
            lines.extend(unit_lines)
            reclassified += unit_reclassified
            tax_relief += unit_relief

        # Account check of the property (booked amounts)
        booked = sum((d.amount_booked or ZERO for d in on_property), ZERO)
        owner_booked = sum((booked_of(l) for l in owner
                if _on_property(l)), ZERO)
        out_booked = sum((booked_of(l) for l in other if _on_property(l)),
            ZERO)
        in_booked = sum((booked_of(l) for su_lines in lines_by_su.values()
                for l in su_lines
                if _on_property(l) and not in_period(l.document)), ZERO)
        unassigned_booked = sum((d.amount_booked or ZERO
                for d in unassigned if d in on_property), ZERO)
        currency = self.company.currency
        check = account_check(booked, reclassified, owner_booked,
            currency.round(not_distributed_booked),
            currency.round(pending_booked), out_booked, in_booked,
            unassigned_booked)
        deducted = sum(((d.amount_gross or ZERO) - (d.amount_booked or ZERO)
                for d in on_property if d.invoice_line), ZERO)
        values = {
            'end_date': end,
            'booked': currency.round(booked),
            'reclassified': currency.round(reclassified),
            'rest': currency.round(check['rest']),
            'owner_booked': currency.round(owner_booked),
            'not_distributed_booked': currency.round(
                not_distributed_booked),
            'pending_booked': currency.round(pending_booked),
            'other_periods_out': currency.round(out_booked),
            'other_periods_in': currency.round(in_booked),
            'unassigned_booked': currency.round(unassigned_booked),
            'expected': currency.round(check['expected']),
            'difference': currency.round(check['difference']),
            'tax_remaining': currency.round(deducted - tax_relief),
            }
        return values, lines, hints

    def _billing_lines(self, unit, prop, account_ids, hints):
        """Lines of part 2 for the billing unit 'unit', the amount
        reclassified off the property and the input tax relieved there"""
        pool = Pool()
        Moves = pool.get('real_estate.billing_unit.moves')
        Tax = pool.get('account.tax')
        SettlementUnit = pool.get('real_estate.settlement_unit')
        results = _results(unit)
        records = Moves.search([('billing_unit', '=', unit.id)])
        by_result = {}
        for record in records:
            if record.settlement_result:
                by_result.setdefault(record.settlement_result.id, []
                    ).append(record)
        billed = unit.state == 'billed'
        expected = {}
        if billed and results:
            dates = [r.moves_reclass.date for r in records
                if r.moves_reclass]
            date = dates[0] if dates else pool.get('ir.date').today()
            currency = unit.property.company.currency
            for result_id, per_group in unit._reclass_shares(
                    results).items():
                result = next(r for r in results if r.id == result_id)
                net_obj = (SettlementUnit._net_object(
                        result.base_object, date)
                    if result.base_object else False)
                total = ZERO
                for (_, tax_ids), net in per_group.items():
                    if not net:
                        continue
                    taxes = Tax.browse(list(tax_ids))
                    computed = (Tax.compute(taxes, net, 1, date)
                        if taxes else [])
                    total += oc_reclass.reclass_amounts(net,
                        [(c['tax'], currency.round(c['amount']))
                            for c in computed],
                        0, 1 if net_obj else 0)['debit_cost']
                expected[result_id] = total
        unit_lines = []
        reclassified = relief = ZERO
        sum_result = sum_billed = sum_reclass = sum_expected = ZERO
        diff_total = ZERO
        for result in results:
            res_records = by_result.get(result.id, [])
            invoice_lines = [r.moves_actual_costs for r in res_records
                if r.moves_actual_costs and r.moves_actual_costs.invoice
                and r.moves_actual_costs.invoice.state in ('posted', 'paid')]
            amount_billed = sum((l.amount or ZERO for l in invoice_lines),
                ZERO)
            moves = [r.moves_reclass for r in res_records
                if r.moves_reclass and r.moves_reclass.state == 'posted']
            amount_reclass = ZERO
            for move in moves:
                for line in move.lines:
                    if line.account.id not in account_ids:
                        continue
                    obj = getattr(line, 'base_object', None)
                    if obj and obj.id == prop.id:
                        reclassified += line.credit - line.debit
                        for tax_line in line.tax_lines:
                            if tax_line.type == 'base' and tax_line.tax:
                                for c in Tax.compute([tax_line.tax],
                                        -tax_line.amount, 1, move.date):
                                    relief += prop.company.currency.round(
                                        c['amount'])
                    elif obj:
                        amount_reclass += line.debit - line.credit
            flat = bool(result.term and result.term.term_type
                and result.term.term_type.oc_processing == 'flat_rate')
            tenant = bool(result.contract) and not flat
            costs = result.actual_costs or ZERO
            difference = ZERO
            if billed:
                if tenant:
                    difference += costs - amount_billed
                difference += expected.get(result.id, ZERO) - amount_reclass
            state = 'hint' if difference else 'ok'
            unit_lines.append({
                    'section': 'result',
                    'name': result.rec_name,
                    'billing_unit': unit.id,
                    'settlement_result': result.id,
                    'contract': result.contract.id if result.contract
                    else None,
                    'base_object': result.base_object.id
                    if result.base_object else None,
                    'result_costs': costs,
                    'billed': amount_billed,
                    'reclass_expected': expected.get(result.id, ZERO),
                    'reclassified': amount_reclass,
                    'difference': difference,
                    'state': state,
                    'record_ids': _ids(results=[result],
                        moves=moves + [l.invoice.move for l in invoice_lines
                            if l.invoice.move],
                        cost_shares=[]),
                    })
            sum_result += costs
            sum_billed += amount_billed
            sum_reclass += amount_reclass
            sum_expected += expected.get(result.id, ZERO)
            diff_total += difference
        if not billed:
            hints.append(gettext(
                    'real_estate.msg_oc_reconciliation_not_billed',
                    billing_unit=unit.rec_name))
        elif diff_total or any(l['difference'] for l in unit_lines):
            hints.append(gettext(
                    'real_estate.msg_oc_reconciliation_billing_difference',
                    billing_unit=unit.rec_name))
        head = {
            'section': 'billing_unit',
            'name': unit.rec_name,
            'billing_unit': unit.id,
            'result_costs': sum_result,
            'billed': sum_billed,
            'reclass_expected': sum_expected,
            'reclassified': sum_reclass,
            'difference': diff_total,
            'state': ('hint' if not billed
                or any(l['state'] == 'hint' for l in unit_lines) else 'ok'),
            'record_ids': _ids(results=results),
            }
        return [head] + unit_lines, reclassified, relief


def unit_key(cost_share):
    "Key of the settlement result of a cost share (BillingUnit._result_key)"
    if cost_share.contract:
        return ('contract', cost_share.contract.id,
            cost_share.base_object.id if cost_share.base_object else None)
    if cost_share.base_object:
        return ('object', cost_share.base_object.id)
    return None


def _results(unit):
    return Pool().get('real_estate.settlement_result').search([
            ('billing_unit', '=', unit.id),
            ], order=[('id', 'ASC')])


def _on_property(line):
    obj = line.document.base_object
    return not obj or obj.type == 'property'


def _simple_line(section, name, assignment_lines):
    return {
        'section': section,
        'name': name,
        'assigned': sum((l.amount_gross or ZERO for l in assignment_lines),
            ZERO),
        'assigned_net': sum((l.amount_net or ZERO
                for l in assignment_lines), ZERO),
        'state': 'ok',
        'record_ids': _ids(oc_lines=assignment_lines,
            documents=[l.document for l in assignment_lines]),
        }


def _ids(**records):
    return json.dumps({k: sorted({r.id for r in v})
            for k, v in records.items()})


def _fmt(amount, currency):
    "Amount in the format of the language of the context"
    Lang = Pool().get('ir.lang')
    return Lang.get().currency(amount, currency, grouping=True)


#**********************************************************************
class OcReconciliationLine(ModelSQL, ModelView):
    "Operating Cost Reconciliation Line"
    __name__ = 'real_estate.oc_reconciliation.line'

    reconciliation = fields.Many2One('real_estate.oc_reconciliation',
        "Reconciliation", required=True, ondelete='CASCADE')
    sequence = fields.Integer("Sequence")
    section = fields.Selection(SECTIONS, "Section", readonly=True)
    name = fields.Char("Name", readonly=True)
    state = fields.Selection([
            ('ok', "OK"),
            ('hint', "Hint"),
            ], "State", readonly=True)
    settlement_unit = fields.Many2One('real_estate.settlement_unit',
        "Settlement Unit", readonly=True)
    billing_unit = fields.Many2One('real_estate.billing_unit',
        "Billing Unit", readonly=True)
    settlement_result = fields.Many2One('real_estate.settlement_result',
        "Settlement Result", readonly=True)
    contract = fields.Many2One('real_estate.contract', "Contract",
        readonly=True)
    base_object = fields.Many2One('real_estate.base_object',
        "Rental Object", readonly=True)
    currency = fields.Function(fields.Many2One('currency.currency',
            "Currency"), 'get_currency')
    assigned = Monetary("Assigned", currency='currency', digits='currency',
        readonly=True, help="Confirmed assignments (gross).")
    assigned_net = Monetary("Assigned Net", currency='currency',
        digits='currency', readonly=True)
    direct = Monetary("Thereof Direct", currency='currency',
        digits='currency', readonly=True,
        help="Assigned to a contract or booked on a rental object.")
    passed_on = Monetary("Passed On", currency='currency',
        digits='currency', readonly=True,
        help="Passed on to (-) or received from (+) other settlement units "
             "(allocation via cost collector).")
    tenants = Monetary("Distributed to Tenants", currency='currency',
        digits='currency', readonly=True)
    vacancy = Monetary("Vacancy / Flat Rate", currency='currency',
        digits='currency', readonly=True)
    commercial_tax = Monetary("Thereof Input Tax Commercial",
        currency='currency', digits='currency', readonly=True,
        help="Difference gross - net of the cost shares distributed net.")
    not_distributed = Monetary("Not Distributed", currency='currency',
        digits='currency', readonly=True)
    outside_period = Monetary("From Other Periods", currency='currency',
        digits='currency', readonly=True,
        help="Part of the assignments whose document is dated outside the "
             "period.")
    result_costs = Monetary("Result Costs", currency='currency',
        digits='currency', readonly=True)
    billed = Monetary("Billed", currency='currency', digits='currency',
        readonly=True, help="Actual cost lines of the posted billing "
        "invoices.")
    reclass_expected = Monetary("Reclassification Expected",
        currency='currency', digits='currency', readonly=True)
    reclassified = Monetary("Reclassified", currency='currency',
        digits='currency', readonly=True,
        help="Debit cost lines of the reclassification on the rental "
             "object (booked amount).")
    difference = Monetary("Difference", currency='currency',
        digits='currency', readonly=True)
    record_ids = fields.Text("Records", readonly=True)
    documents = fields.Function(fields.Many2Many('real_estate.oc_document',
            None, None, "Documents"), 'get_records')
    oc_lines = fields.Function(fields.Many2Many(
            'real_estate.oc_document.line', None, None, "Assignments"),
        'get_records')
    cost_shares = fields.Function(fields.Many2Many('real_estate.cost_share',
            None, None, "Cost Shares"), 'get_records')
    results = fields.Function(fields.Many2Many(
            'real_estate.settlement_result', None, None,
            "Settlement Results"), 'get_records')
    moves = fields.Function(fields.Many2Many('account.move', None, None,
            "Moves"), 'get_records')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._order = [('reconciliation', 'ASC'), ('sequence', 'ASC'),
            ('id', 'ASC')]

    def get_currency(self, name):
        return self.reconciliation.currency.id

    def get_records(self, name):
        try:
            data = json.loads(self.record_ids or '{}')
        except ValueError:
            return []
        return data.get(name, [])


#**********************************************************************
class OcReconciliationReport(Report):
    "Operating cost reconciliation (report, phase 4b)"
    __name__ = 'real_estate.oc_reconciliation.report'

    @classmethod
    def get_context(cls, records, header, data):
        context = super().get_context(records, header, data)
        states = dict(CHECK_STATES)

        def amount(value):
            if value is None:
                return ''
            return cls.format_number(value, None, digits=2)

        def total(lines, name):
            # postings without property concern the whole company
            return sum((getattr(l, name) or ZERO for l in lines
                    if l.section != 'without_property'), ZERO)

        def check_state(record):
            return {'ok': "in Ordnung", 'hints': "Hinweise"}.get(
                record.check_state, states.get(record.check_state) or '')

        def check_rows(record):
            return [
                ("Gebucht an der Wirtschaftseinheit", record.booked, False),
                ("− umgebucht", record.reclassified, False),
                ("= Rest an der Wirtschaftseinheit", record.rest, True),
                ("Eigentümer, nicht umlagefähig", record.owner_booked,
                    False),
                ("+ nicht verteilt", record.not_distributed_booked, False),
                ("+ noch nicht umgebucht", record.pending_booked, False),
                ("+ in andere Zeiträume", record.other_periods_out, False),
                ("− aus anderen Zeiträumen", record.other_periods_in,
                    False),
                ("+ nicht zugeordnet", record.unassigned_booked, False),
                ("= erwarteter Rest", record.expected, True),
                ("Differenz (Rundung Optionssatz, nur Information)",
                    record.difference, True),
                ("Vorsteuer an der Wirtschaftseinheit (nur Information)",
                    record.tax_remaining, False),
                ]

        context['amount'] = amount
        context['total'] = total
        context['check_state'] = check_state
        context['check_rows'] = check_rows
        return context

