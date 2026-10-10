'Comparative rent (§§ 558-558b BGB) - procedure of the adjustment run (spezifikation-anpassungslauf.md 10)'
import datetime
from decimal import ROUND_HALF_UP, Decimal

from dateutil.relativedelta import relativedelta

from trytond.i18n import gettext
from trytond.model import ModelView, fields
from trytond.model.exceptions import ValidationError
from trytond.modules.currency.fields import Monetary
from trytond.modules.product import price_digits
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Eval
from trytond.transaction import Transaction
from trytond.wizard import Button, StateTransition, StateView, Wizard

from .adjustment_run import PROCEDURES, AdjustmentProcedure
from .contract_type import CAP_EXCLUDED_PROCEDURES
from .rent_survey import _apartment

# Rent unchanged for 15 months at the effective date, request at the
# earliest one year after the last increase (§ 558 para. 1 BGB)
WAITING_MONTHS = 15
LOCK_MONTHS = 12
# Period of the cap (§ 558 para. 3 BGB)
CAP_YEARS = 3
# A calculation of the rent survey is used for one year at most (V07)
CALCULATION_MONTHS = 12
OPEN = ('draft', 'approved', 'declared')
# Announced requests count for the lock of one year (V04)
REQUESTED = ('declared', 'done', 'refused')


def _cent(value):
    return Decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def effective_date(receipt_date):
    """Effective date of a consented increase: start of the third calendar
    month after the receipt of the request (§ 558b para. 1 BGB)"""
    if not receipt_date:
        return None
    return receipt_date.replace(day=1) + relativedelta(months=3)


def earliest_first(date):
    "First day of the month on or after 'date'"
    if date.day == 1:
        return date
    return date.replace(day=1) + relativedelta(months=1)


def comparative_cap(comparative, base, excluded, cap_percent):
    """New rent of the comparative rent procedure (spec 10.4): the cap
    is the rent three years before plus the cap percentage plus the
    increases not counted (modernisation, operating costs) - the new rent
    is the lower of comparative rent and cap. Returns (cap amount, new
    amount, 'comparative' or 'cap')."""
    cap = _cent(base * (1 + Decimal(cap_percent) / 100) + excluded)
    if cap < comparative:
        return cap, cap, 'cap'
    return cap, _cent(comparative), 'comparative'


def chain_history(chain, valid_from):
    """History of a term chain for the comparative rent (spec 10.3,
    10.4). 'chain' is a list of (start date, amount, excluded) ordered by
    start - 'excluded' marks a term created by a modernisation or
    operating cost adjustment (§§ 559, 560 BGB). Returns (last change,
    amount three years before 'valid_from', sum of the excluded increases
    within these three years): the last change ignores the excluded
    increases; without any change it is the start of the chain."""
    if not chain:
        return None, None, Decimal(0)
    last_change = chain[0][0]
    excluded_sum = Decimal(0)
    cap_date = valid_from - relativedelta(years=CAP_YEARS)
    for (_, amount_before, _), (start, amount, excluded) in zip(
            chain, chain[1:]):
        if amount == amount_before or start > valid_from:
            continue
        if excluded:
            if start > cap_date:
                excluded_sum += amount - amount_before
        else:
            last_change = start
    base = chain[0][1]
    for start, amount, _ in chain:
        if start <= cap_date:
            base = amount
    return last_change, base, excluded_sum


#**********************************************************************
class ContractRentAdjustment(metaclass=PoolMeta):
    __name__ = 'real_estate.contract.rent_adjustment'

    def comparative_valid_from(self, declaration_date=None,
            receipt_date=None):
        """Effective date of a comparative rent adjustment - before the
        receipt is confirmed a preview from the declaration date + the
        receipt days of the real estate accounting"""
        received = receipt_date
        if not received and declaration_date:
            received = declaration_date + datetime.timedelta(
                days=self._receipt_days())
        return effective_date(received)

    def last_request_date(self):
        "Declaration date of the last announced request (V04)"
        dates = [a.declaration_date for a in self.adjustments
            if a.state in REQUESTED and a.declaration_date]
        return max(dates) if dates else None


def _term_chain(term):
    "Terms of the chain of 'term': same contract, term type and item"
    Term = Pool().get('real_estate.contract.term')
    return Term.search([
            ('contract', '=', term.contract.id),
            ('term_type', '=', term.term_type.id),
            ('reference_item', '=',
                term.reference_item.id if term.reference_item else None),
            ], order=[('valid_from', 'ASC'), ('id', 'ASC')])


def _amount(term):
    return _cent(Decimal(str(term.quantity or 0))
        * (term.unit_price or Decimal(0)))


def _history(chain, valid_from):
    "chain_history() of the stored terms of a chain"
    Adjustment = Pool().get('real_estate.contract.term.adjustment')
    excluded = {a.term_new.id for a in Adjustment.search([
                ('term_new', 'in', [t.id for t in chain]),
                ('state', '=', 'done'),
                ])
        if a.procedure in CAP_EXCLUDED_PROCEDURES or a.settlement_result}
    return chain_history([(t.valid_from, _amount(t), t.id in excluded)
            for t in chain], valid_from)


def _apartments(term):
    item = term.reference_item
    objects = list(item.objects) if item else []
    return objects, [o for o in objects if _apartment(o)]


#**********************************************************************
class ComparativeRentProcedure(AdjustmentProcedure):
    "Comparative rent (§§ 558-558b BGB) - spezifikation-anpassungslauf.md 10"
    code = 'comparative_rent'
    consent = 'consent'

    @classmethod
    def _candidates(cls, run, terms=None):
        """Current terms of the chains allowing the comparative rent:
        running contracts of the filters, contract type and term type,
        monthly rhythm, use class of the rental units (F15)"""
        pool = Pool()
        Term = pool.get('real_estate.contract.term')
        UseClass = pool.get('real_estate.use_class')
        domain = [
            ('contract.company', '=', run.company.id),
            ('contract.state', '=', 'running'),
            ('contract.c_type.adjustment_procedures', 'in',
                ['comparative_rent']),
            ('term_type.adjustment_procedures', 'in', ['comparative_rent']),
            ('rhythm_type', '=', 'monthly'),
            ('rhythm', '=', 1),
            ]
        if run.properties:
            domain.append(('contract.property', 'in',
                    [p.id for p in run.properties]))
        if run.contracts:
            domain.append(('contract', 'in', [c.id for c in run.contracts]))
        if terms is not None:
            domain.append(('id', 'in', [t.id for t in terms]))
        chains = {}
        for term in Term.search(domain,
                order=[('valid_from', 'ASC'), ('id', 'ASC')]):
            key = (term.contract.id, term.term_type.id,
                term.reference_item.id if term.reference_item else None)
            chains[key] = term
        result = []
        for term in chains.values():
            chain = _term_chain(term)
            current = chain[-1]
            if terms is None and current != term:
                continue
            objects, _ = _apartments(current)
            if not UseClass.allows(objects, 'comparative_rent'):
                continue
            result.append((current, chain))
        return result

    @classmethod
    def select(cls, run, terms=None):
        pool = Pool()
        RentAdjustment = pool.get('real_estate.contract.rent_adjustment')
        Adjustment = pool.get('real_estate.contract.term.adjustment')
        Calculation = pool.get('real_estate.rent_survey.calculation')
        declaration_date = run.declaration_date or run.key_date
        check_labels = dict(Adjustment.fields_get(['check_state'])
            ['check_state']['selection'])
        counts = dict.fromkeys(['agreements', 'created', 'excluded'], 0)
        lines = []
        # agreements with an adjustment cancelled in this run are excluded
        skip = {a.rent_adjustment.id for a in run.adjustments
            if a.state == 'cancelled' and a.rent_adjustment} \
            if terms is None else set()

        def protocol(term, message_id, **kwargs):
            lines.append(gettext('real_estate.' + message_id,
                    term=f'{term.contract.rec_name} / '
                    f'{term.rec_name.strip()}', **kwargs))

        for term, chain in cls._candidates(run, terms):
            counts['agreements'] += 1
            chain_ids = [t.id for t in chain]
            agreements = RentAdjustment.search([
                    ('term', 'in', chain_ids),
                    ('state', '!=', 'closed'),
                    ])
            # V01: no graduated or index rent, not locked
            agreed = [a for a in agreements
                if a.procedure in ('graduated_rent', 'index_rent')]
            if agreed or term.graduated_locked:
                counts['excluded'] += 1
                protocol(term, 'msg_comparative_line_agreed',
                    agreement=agreed[0].rec_name if agreed else '-')
                continue
            agreement = next((a for a in agreements
                    if a.procedure == 'comparative_rent'
                    and a.state == 'active'), None)
            if agreement and agreement.id in skip:
                counts['excluded'] += 1
                protocol(term, 'msg_adjustment_run_line_excluded_term')
                continue
            # V02: no open adjustment
            open_ = [a for a in (agreement.adjustments if agreement else [])
                if a.state in OPEN]
            if open_:
                counts['excluded'] += 1
                protocol(term, 'msg_comparative_line_open',
                    adjustment=open_[0].rec_name)
                continue
            # V05: exactly one apartment
            objects, apartments = _apartments(term)
            if len(objects) != 1 or len(apartments) != 1:
                counts['excluded'] += 1
                protocol(term, 'msg_comparative_line_apartments',
                    count=len(objects))
                continue
            apartment, = apartments
            valid_from = effective_date(declaration_date
                + datetime.timedelta(days=cls._receipt_days(term)))
            # V06: contract not ended before the effective date
            end = term.contract.get_effective_end_date()
            if end and end < valid_from:
                counts['excluded'] += 1
                protocol(term, 'msg_comparative_line_end',
                    end=end.strftime('%d.%m.%Y'))
                continue
            # V03: rent unchanged for 15 months
            last_change, _, _ = _history(chain, valid_from)
            earliest = earliest_first(
                last_change + relativedelta(months=WAITING_MONTHS))
            if valid_from < earliest:
                counts['excluded'] += 1
                protocol(term, 'msg_comparative_line_waiting',
                    last_change=last_change.strftime('%d.%m.%Y'),
                    earliest=earliest.strftime('%d.%m.%Y'))
                continue
            # V04: last request at least one year before
            last_request = (agreement.last_request_date()
                if agreement else None)
            if last_request and declaration_date < last_request \
                    + relativedelta(months=LOCK_MONTHS):
                counts['excluded'] += 1
                protocol(term, 'msg_comparative_line_lock',
                    last_request=last_request.strftime('%d.%m.%Y'))
                continue
            # D2: agreement per term chain
            if not agreement:
                agreement, = RentAdjustment.create([{
                            'contract': term.contract.id,
                            'procedure': 'comparative_rent',
                            'term': chain[0].id,
                            'valid_from': chain[0].valid_from,
                            'state': 'active',
                            }])
            calculation = None
            # D3: calculation of the rent survey on the key date
            if run.create_calculations:
                calculation, = Calculation.calculate_for([{
                            'company': run.company.id,
                            'base_object': apartment.id,
                            'key_date': run.key_date,
                            'contract': term.contract.id,
                            'term': term.id,
                            'rent_adjustment': agreement.id,
                            }])
            adjustment, = Adjustment.create([{
                        'rent_adjustment': agreement.id,
                        'term_old': term.id,
                        'run': run.id,
                        'declaration_date': declaration_date,
                        'planned_quantity': term.quantity,
                        'calculation': (calculation.id
                            if calculation else None),
                        }])
            Adjustment.write([adjustment], adjustment._compute())
            adjustment = Adjustment(adjustment.id)
            counts['created'] += 1
            protocol(term, 'msg_comparative_line_created',
                state=check_labels.get(adjustment.check_state, ''),
                amount=(adjustment.planned_amount
                    if adjustment.planned_amount is not None else '-'))
            if adjustment.check_message:
                lines.extend(f'    {line}'
                    for line in adjustment.check_message.splitlines())
        if not counts['agreements']:
            lines.append(gettext('real_estate.msg_comparative_line_none'))
        return counts, lines

    @staticmethod
    def _receipt_days(term):
        company = term.contract.company
        re_accounting = company.re_accounting if company else None
        if re_accounting and re_accounting.receipt_days is not None:
            return re_accounting.receipt_days
        return 3


PROCEDURES[ComparativeRentProcedure.code] = ComparativeRentProcedure


#**********************************************************************
class ContractTermAdjustment(metaclass=PoolMeta):
    __name__ = 'real_estate.contract.term.adjustment'

    _comparative = Eval('procedure') == 'comparative_rent'
    _states_comparative = {'invisible': ~_comparative, 'readonly': True}

    calculation = fields.Many2One('real_estate.rent_survey.calculation',
        "Comparative Rent Calculation", ondelete='RESTRICT',
        states=_states_comparative,
        help="Accepted calculation of the rent survey - basis of the "
             "request.")
    calculation_object = fields.Function(fields.Many2One(
            'real_estate.base_object', "Apartment"),
        'get_calculation_object')
    comparative_amount = Monetary("Comparative Rent", currency='currency',
        digits='currency', states=_states_comparative,
        help="Local comparative rent per month: accepted rent per m² × "
             "living space.")
    cap_base_amount = Monetary("Rent 3 Years before", currency='currency',
        digits='currency', states=_states_comparative,
        help="Rent of the chain three years before the effective date "
             "(for a younger contract the initial rent).")
    cap_excluded_amount = Monetary("Increases not Counted",
        currency='currency', digits='currency', states=_states_comparative,
        help="Increases for modernisation and operating costs (§§ 559, 560 "
             "BGB) within the three years - not counted for the cap.")
    cap_percent = fields.Numeric("Cap (%)", digits=(16, 2),
        states=_states_comparative,
        help="20 %, 15 % with a regulation for the property (§ 558 para. 3 "
             "BGB).")
    cap_amount = Monetary("Cap Limit", currency='currency',
        digits='currency', states=_states_comparative,
        help="Highest rent by the cap: rent three years before × (1 + cap) "
             "+ increases not counted.")
    limited_by = fields.Selection([
            (None, ''),
            ('comparative', "Comparative Rent"),
            ('cap', "Cap"),
            ], "Limited by", states=_states_comparative)
    calculation_text = fields.Text("Calculation", readonly=True,
        states={'invisible': ~_comparative})

    @classmethod
    def view_attributes(cls):
        return super().view_attributes() + [
            ('//page[@id="page_comparative"]', 'states',
                {'invisible': ~cls._comparative}, ['procedure']),
            ]

    def get_calculation_object(self, name):
        if self.procedure != 'comparative_rent' or not self.term_old:
            return None
        _, apartments = _apartments(self.term_old)
        return apartments[0].id if len(apartments) == 1 else None

    def _accepted_calculation(self, declaration_date):
        """Accepted calculation of the apartment (V07): key date not after
        the declaration date and not older than one year - the linked
        one, else the latest"""
        Calculation = Pool().get('real_estate.rent_survey.calculation')
        apartment = self.calculation_object
        if not apartment or not declaration_date:
            return None
        earliest = declaration_date - relativedelta(
            months=CALCULATION_MONTHS)

        def usable(calculation):
            return (calculation.state == 'accepted'
                and calculation.base_object == apartment
                and earliest < calculation.key_date <= declaration_date)
        if self.calculation and usable(self.calculation):
            return self.calculation
        calculations = Calculation.search([
                ('base_object', '=', apartment.id),
                ('state', '=', 'accepted'),
                ('key_date', '<=', declaration_date),
                ('key_date', '>', earliest),
                ], order=[('key_date', 'DESC'), ('id', 'DESC')], limit=1)
        return calculations[0] if calculations else None

    def _comparative_compute(self):
        """Comparative rent with cap (spec 10.4) and checks V03, V04, V06,
        V07-V12 - for the declaration date, after the receipt for the
        actual effective date"""
        Lang = Pool().get('ir.lang')
        lang = Lang.get()
        agreement = self.rent_adjustment
        term = self.term_old
        contract = term.contract
        run = self.run
        findings = []

        def add(code, level, message_id, **kwargs):
            findings.append((code, level, gettext(
                        'real_estate.' + message_id, **kwargs)))

        def num(value):
            return lang.format_number(value, 2) if value is not None else '-'

        def date(value):
            return value.strftime('%d.%m.%Y') if value else '-'

        declaration_date = self.declaration_date or (
            run.declaration_date or run.key_date if run else None)
        valid_from = agreement.comparative_valid_from(declaration_date,
            self.receipt_date)
        values = {
            'planned_valid_from': valid_from,
            'planned_quantity': term.quantity,
            'direction': 'increase',
            'planned_amount': None,
            'planned_unit_price': None,
            'comparative_amount': None,
            'cap_base_amount': None,
            'cap_excluded_amount': None,
            'cap_percent': None,
            'cap_amount': None,
            'limited_by': None,
            'calculation_text': None,
            }
        amount_old = _amount(term)
        # V06: running contract, not ended before the effective date
        end = contract.get_effective_end_date()
        if contract.state != 'running' or (
                end and valid_from and end < valid_from):
            add('V06', 'error', 'msg_comparative_contract',
                contract=contract.rec_name, end=date(end))
        # V03, V04: waiting period and lock of one year
        chain = _term_chain(term)
        last_change, base, excluded = (_history(chain, valid_from)
            if valid_from else (None, None, Decimal(0)))
        if last_change:
            earliest = earliest_first(
                last_change + relativedelta(months=WAITING_MONTHS))
            if valid_from < earliest:
                add('V03', 'error', 'msg_comparative_waiting',
                    last_change=date(last_change), earliest=date(earliest),
                    valid_from=date(valid_from))
        others = [a for a in agreement.adjustments if a.id != self.id
            and a.state in REQUESTED and a.declaration_date]
        if others and declaration_date:
            last_request = max(a.declaration_date for a in others)
            if declaration_date < last_request + relativedelta(
                    months=LOCK_MONTHS):
                add('V04', 'error', 'msg_comparative_lock',
                    last_request=date(last_request))
        # V11: net rent only
        if term.term_type.oc_processing != 'none':
            add('V11', 'error', 'msg_comparative_operating_costs',
                term_type=term.term_type.rec_name)
        # V12: booked periods from the effective date
        booked_to = term.get_booked_to()
        if valid_from and booked_to and booked_to >= valid_from:
            add('V12', 'warning', 'msg_comparative_booked',
                booked_to=date(booked_to), valid_from=date(valid_from))
        # V07: accepted calculation
        calculation = self._accepted_calculation(declaration_date)
        if not calculation:
            add('V07', 'error', 'msg_comparative_calculation',
                apartment=(self.calculation_object.rec_name
                    if self.calculation_object else '-'),
                date=date(declaration_date))
            return self._finish_compute(values, findings,
                self.manual_amount, amount_old)
        values['calculation'] = calculation.id
        # V08: accepted with warnings or not qualified cell
        if (calculation.check_state == 'warning'
                or (calculation.cell and not calculation.cell.qualified)):
            add('V08', 'warning', 'msg_comparative_calculation_warning',
                calculation=calculation.rec_name)
        comparative = calculation.comparative_rent
        cap_percent = contract.property.cap_percent(valid_from)
        cap, new, limited_by = comparative_cap(comparative, base,
            excluded, cap_percent)
        quantity = Decimal(str(term.quantity or 0))
        values.update({
                'comparative_amount': comparative,
                'cap_base_amount': base,
                'cap_excluded_amount': excluded,
                'cap_percent': cap_percent,
                'cap_amount': cap,
                'limited_by': limited_by,
                'planned_amount': new,
                'planned_unit_price': ((new / quantity).quantize(
                        Decimal(10) ** -price_digits[1],
                        rounding=ROUND_HALF_UP) if quantity else None),
                })
        # V10: the cap applies
        if limited_by == 'cap':
            add('V10', 'ok', 'msg_comparative_cap',
                cap=num(cap), comparative=num(comparative))
        # V09: increase (at least the minimum of the run)
        minimum = max(run.min_increase_amount or Decimal(0),
            _cent(amount_old * (run.min_increase_percent or Decimal(0))
                / 100)) if run else Decimal(0)
        if new - amount_old <= 0 or new - amount_old < minimum:
            add('V09', 'error', 'msg_comparative_no_increase',
                new=num(new), old=num(amount_old), minimum=num(minimum))
        values['calculation_text'] = gettext(
            'real_estate.msg_comparative_calculation_text',
            calculation=calculation.rec_name,
            rent_per_sqm=num(calculation.accepted_rent_per_sqm),
            area=num(calculation.area), comparative=num(comparative),
            valid_from=date(valid_from),
            cap_date=date(valid_from - relativedelta(years=CAP_YEARS)),
            base=num(base), percent=num(cap_percent), excluded=num(excluded),
            cap=num(cap), old=num(amount_old), new=num(new),
            last_change=date(last_change))
        return self._finish_compute(values, findings, self.manual_amount,
            amount_old)

    def _execute_comparative(self, employee):
        """Execute a consented comparative rent adjustment (spec 10.6):
        split of the term from the effective date with the consented
        amount, recalculation of the cash flow and contract log"""
        pool = Pool()
        Term = pool.get('real_estate.contract.term')
        Contract = pool.get('real_estate.contract')
        Date = pool.get('ir.date')
        Task = pool.get('real_estate.task')
        name = self.rec_name
        agreement = self.rent_adjustment
        if not self.receipt_date or self.consent_state not in (
                'consented', 'partially_consented'):
            raise ValidationError(gettext(
                    'real_estate.msg_comparative_consent_missing',
                    adjustment=name))
        if agreement.current_term != self.term_old:
            raise ValidationError(gettext(
                    'real_estate.msg_index_adjustment_term_changed',
                    adjustment=name,
                    term=self.term_old.rec_name.strip()))
        valid_from = effective_date(self.receipt_date)
        contract = self.term_old.contract
        end = contract.get_effective_end_date()
        if contract.state != 'running' or (end and end < valid_from):
            raise ValidationError(gettext(
                    'real_estate.msg_comparative_contract',
                    contract=contract.rec_name,
                    end=end.strftime('%d.%m.%Y') if end else '-'))
        amount = (self.consented_amount
            if self.consent_state == 'partially_consented'
            else self.planned_amount)
        quantity = Decimal(str(self.planned_quantity
                or self.term_old.quantity or 0))
        unit_price = ((amount / quantity).quantize(
                Decimal(10) ** -price_digits[1], rounding=ROUND_HALF_UP)
            if quantity else amount)
        new_term = Term._split(self.term_old, valid_from, unit_price,
            self.planned_quantity)
        Contract._re_calc_terms([contract])
        self.__class__.write([self], {
                'term_new': new_term.id,
                'planned_valid_from': valid_from,
                'executed_by': employee.id if employee else None,
                'executed_date': Date.today(),
                })
        contract.add_log('comparative_rent', gettext(
                'real_estate.msg_comparative_log',
                amount_old=self.amount_old, amount_new=amount,
                comparative=self.comparative_amount, cap=self.cap_amount,
                valid_from=valid_from.strftime('%d.%m.%Y'),
                receipt=self.receipt_date.strftime('%d.%m.%Y'),
                consent=dict(self.fields_get(['consent_state'])
                    ['consent_state']['selection'])[self.consent_state]))
        Task.close_for(self, 'comparative_consent')


#**********************************************************************
class AdjustmentRunAddStart(ModelView):
    "Adjustment Run - Add Terms"
    __name__ = 'real_estate.contract.term.adjustment.run.add.start'

    run = fields.Many2One('real_estate.contract.term.adjustment.run', "Run",
        readonly=True)
    company = fields.Many2One('company.company', "Company", readonly=True)
    terms = fields.Many2Many('real_estate.contract.term', None, None,
        "Terms", required=True,
        domain=[
            ('contract.company', '=', Eval('company', -1)),
            ('contract.state', '=', 'running'),
            ],
        help="Terms to add to the run - the checks of the procedure apply "
             "as for the selection.")


class AdjustmentRunAdd(Wizard):
    "Adjustment Run - Add Terms"
    __name__ = 'real_estate.contract.term.adjustment.run.add'

    start = StateView('real_estate.contract.term.adjustment.run.add.start',
        'real_estate.adjustment_run_add_start_view_form', [
            Button("Cancel", 'end', 'tryton-cancel'),
            Button("Add", 'add', 'tryton-ok', default=True),
            ])
    add = StateTransition()

    def default_start(self, fields):
        return {
            'run': self.record.id,
            'company': self.record.company.id,
            }

    def transition_add(self):
        Run = Pool().get('real_estate.contract.term.adjustment.run')
        run = self.record
        if run.state not in ('selected', 'calculated'):
            return 'end'
        counts, lines = run.procedure_class.select(run,
            terms=list(self.start.terms))
        Run.write([run], {
                'protocol': run._log('msg_adjustment_run_added', lines,
                    created=counts.get('created', 0),
                    excluded=counts.get('agreements', 0)
                    - counts.get('created', 0)),
                })
        with Transaction().set_context(_skip_warnings=True):
            Run._check_processes([Run(run.id)])
        return 'end'
