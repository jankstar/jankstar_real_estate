'Modernisation (§§ 559-559e BGB) - procedure of the adjustment run (spezifikation-modernisierung.md 5, 6)'
import datetime
from decimal import ROUND_HALF_UP, Decimal

from dateutil.relativedelta import relativedelta

from trytond.i18n import gettext
from trytond.model import ModelSQL, fields
from trytond.model.exceptions import ValidationError
from trytond.modules.currency.fields import Monetary
from trytond.modules.product import price_digits
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Eval
from trytond.transaction import Transaction

from .adjustment_run import PROCEDURES, AdjustmentProcedure
from .contract_comparative_rent import _amount, _term_chain
from .contract_index_rent import LETTERS
from .contract_report import IndexAdjustmentLetterReport

OPEN = ('draft', 'approved', 'declared')
# measures of the run
RUN_MEASURE_STATES = ['completed']


def _cent(value):
    return Decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


#**********************************************************************
# Pure functions (spec 6.5, 6.6)

def modernisation_valid_from(receipt_date, extended=False, months=6):
    """Effective date of a modernisation increase: start of the third
    calendar month after the receipt of the declaration (§ 559b para. 2
    BGB), postponed by 'months' (6) when extended"""
    if not receipt_date:
        return None
    valid_from = receipt_date.replace(day=1) + relativedelta(months=3)
    if extended:
        valid_from += relativedelta(months=months)
    return valid_from


def extension_reason(trivial, announced, receipt_date, defective, increase,
        announced_increase, tolerance_percent):
    """Reason of the extension by 6 months (§ 559b para. 2 sentence 2 BGB,
    D-M6) or None: 'missing' - the measure was not announced or the
    receipt of the announcement is not captured (not for a trivial
    measure), 'defective' - flag of the unit, 'exceeded' - the increase is
    more than 'tolerance_percent' above the announced one"""
    if not trivial:
        if not announced or not receipt_date:
            return 'missing'
        if defective:
            return 'defective'
    if (not trivial and increase is not None
            and announced_increase is not None
            and Decimal(increase) > Decimal(announced_increase)
            * (1 + Decimal(tolerance_percent) / 100)):
        return 'exceeded'
    return None


def previous_increases(history, valid_from, years):
    """Increases after § 559/§ 559c/§ 559e of the apartment within the
    'years' before 'valid_from' (spec 6.5). 'history' is a list of
    (effective date, monthly increase, heating) - returns (all, heating)"""
    start = valid_from - relativedelta(years=years)
    total = heating_total = Decimal(0)
    for date, amount, heating in history:
        if date and start < date <= valid_from:
            total += Decimal(amount or 0)
            if heating:
                heating_total += Decimal(amount or 0)
    return total, heating_total


def termination_deadline(receipt_date):
    """Special termination after a modernisation increase (§ 561 BGB):
    until the end of the second month after the receipt"""
    if not receipt_date:
        return None
    return (receipt_date.replace(day=1) + relativedelta(months=3)
        - datetime.timedelta(days=1))


#**********************************************************************
class ModernisationProcedure(AdjustmentProcedure):
    "Modernisation (§§ 559-559e BGB) - spezifikation-modernisierung.md 5"
    code = 'modernisation'

    @classmethod
    def select(cls, run, terms=None):
        """One adjustment per rental unit of the measures of the run with a
        rent term allowing the procedure (D-M1) - exclusions with a reason
        in the protocol; the rent adjustment 'modernisation' per term
        chain is created by the selection"""
        pool = Pool()
        RentAdjustment = pool.get('real_estate.contract.rent_adjustment')
        Adjustment = pool.get('real_estate.contract.term.adjustment')
        UseClass = pool.get('real_estate.use_class')
        if not run.modernisations:
            raise ValidationError(gettext(
                    'real_estate.msg_modernisation_run_measures',
                    run=run.rec_name))
        check_labels = dict(Adjustment.fields_get(['check_state'])
            ['check_state']['selection'])
        reason_labels = dict(pool.get('real_estate.modernisation.unit')
            .fields_get(['exclusion_reason'])['exclusion_reason']
            ['selection'])
        declaration_date = run.declaration_date or run.key_date
        counts = dict.fromkeys(['agreements', 'created', 'excluded'], 0)
        lines = []
        skip = {a.modernisation_unit.id for a in run.adjustments
            if a.state == 'cancelled' and a.modernisation_unit} \
            if terms is None else set()

        def protocol(unit, message_id, **kwargs):
            counts['excluded'] += 1
            lines.append(gettext('real_estate.' + message_id,
                    unit=f'{unit.modernisation.number} / '
                    f'{unit.object.rec_name}', **kwargs))

        for measure in run.modernisations:
            if measure.state not in RUN_MEASURE_STATES:
                lines.append(gettext(
                        'real_estate.msg_modernisation_line_state',
                        modernisation=measure.rec_name))
                continue
            for unit in measure.units:
                contract = unit.contract
                if run.properties and (not contract
                        or contract.property not in run.properties):
                    continue
                if run.contracts and contract not in run.contracts:
                    continue
                current = _term_chain(unit.term)[-1] if unit.term else None
                if terms is not None and current not in terms:
                    continue
                counts['agreements'] += 1
                if unit.excluded:
                    protocol(unit, 'msg_modernisation_line_excluded',
                        reason=reason_labels.get(unit.exclusion_reason,
                            unit.exclusion_reason or '-'))
                    continue
                if not contract or not current:
                    protocol(unit, 'msg_modernisation_line_no_term')
                    continue
                if unit.id in skip:
                    protocol(unit, 'msg_adjustment_run_line_excluded_term')
                    continue
                # D-M1: contract type, term type and use class
                objects = (list(current.reference_item.objects)
                    if current.reference_item else [])
                if ('modernisation' not in (contract.c_type.adjustment_procedures
                            or [] if contract.c_type else [])
                        or 'modernisation' not in (
                            current.term_type.adjustment_procedures or [])
                        or not UseClass.allows(objects, 'modernisation')):
                    protocol(unit, 'msg_modernisation_line_not_allowed',
                        term=current.rec_name.strip())
                    continue
                others = Adjustment.search([
                        ('modernisation_unit', '=', unit.id),
                        ('state', 'not in', ['cancelled', 'refused']),
                        ])
                if others:
                    protocol(unit, 'msg_modernisation_line_exists',
                        adjustment=others[0].rec_name)
                    continue
                chain = _term_chain(current)
                agreements = RentAdjustment.search([
                        ('term', 'in', [t.id for t in chain]),
                        ('procedure', '=', 'modernisation'),
                        ('state', '!=', 'closed'),
                        ], limit=1)
                if agreements:
                    agreement, = agreements
                else:
                    agreement, = RentAdjustment.create([{
                                'contract': contract.id,
                                'procedure': 'modernisation',
                                'term': chain[0].id,
                                'valid_from': chain[0].valid_from,
                                'state': 'active',
                                }])
                adjustment, = Adjustment.create([{
                            'rent_adjustment': agreement.id,
                            'term_old': current.id,
                            'run': run.id,
                            'modernisation_unit': unit.id,
                            'declaration_date': declaration_date,
                            'planned_quantity': current.quantity,
                            }])
                Adjustment.write([adjustment], adjustment._compute())
                adjustment = Adjustment(adjustment.id)
                counts['created'] += 1
                lines.append(gettext(
                        'real_estate.msg_modernisation_line_created',
                        unit=f'{measure.number} / {unit.object.rec_name}',
                        state=check_labels.get(adjustment.check_state, ''),
                        amount=(adjustment.difference_amount
                            if adjustment.difference_amount is not None
                            else '-')))
                if adjustment.check_message:
                    lines.extend(f'    {line}'
                        for line in adjustment.check_message.splitlines())
        if not counts['agreements']:
            lines.append(gettext('real_estate.msg_modernisation_line_none'))
        return counts, lines


PROCEDURES[ModernisationProcedure.code] = ModernisationProcedure
LETTERS['modernisation'] = 'real_estate.modernisation.increase_letter'


#**********************************************************************
class ContractTermAdjustmentRun(metaclass=PoolMeta):
    __name__ = 'real_estate.contract.term.adjustment.run'

    _modernisation = Eval('procedure') == 'modernisation'

    modernisations = fields.Many2Many(
        'real_estate.contract.term.adjustment.run-modernisation', 'run',
        'modernisation', "Modernisations",
        domain=[
            ('company', '=', Eval('company', -1)),
            ('state', 'in', RUN_MEASURE_STATES),
            ],
        states={
            'invisible': ~_modernisation,
            'readonly': Eval('state') != 'draft',
            },
        help="Completed modernisations whose rental units are selected.")

    @classmethod
    def update_state(cls, runs):
        "A done modernisation run settles its measures"
        super().update_state(runs)
        Modernisation = Pool().get('real_estate.modernisation')
        measures = [m for r in cls.browse([r.id for r in runs])
            if r.procedure == 'modernisation' and r.state == 'done'
            for m in r.modernisations if m.state == 'completed']
        if measures:
            Modernisation.settle(measures)


class ContractTermAdjustmentRunModernisation(ModelSQL):
    "Adjustment Run - Modernisation"
    __name__ = 'real_estate.contract.term.adjustment.run-modernisation'

    run = fields.Many2One('real_estate.contract.term.adjustment.run', "Run",
        required=True, ondelete='CASCADE')
    modernisation = fields.Many2One('real_estate.modernisation',
        "Modernisation", required=True, ondelete='CASCADE')


#**********************************************************************
class ContractTermAdjustment(metaclass=PoolMeta):
    __name__ = 'real_estate.contract.term.adjustment'

    _mod = Eval('procedure') == 'modernisation'
    _states_mod = {'invisible': ~_mod, 'readonly': True}

    modernisation_unit = fields.Many2One('real_estate.modernisation.unit',
        "Rental Unit of the Modernisation", ondelete='RESTRICT',
        states=_states_mod)
    modernisation = fields.Function(fields.Many2One(
            'real_estate.modernisation', "Modernisation",
            states={'invisible': ~_mod}),
        'get_modernisation', searcher='search_modernisation')
    modernisation_area = fields.Numeric("Area (Cap)", digits=(16, 2),
        states=_states_mod,
        help="Area of the cap measurement of the modernisation rule.")
    modernisation_costs = Monetary("Costs of the Unit", currency='currency',
        digits='currency', states=_states_mod,
        help="Share of the costs before deductions (net or gross basis of "
             "the unit) - for the limit of the simplified procedure.")
    modernisation_allocable = Monetary("Allocable Costs",
        currency='currency', digits='currency', states=_states_mod)
    modernisation_annual = Monetary("Annual Amount", currency='currency',
        digits='currency', states=_states_mod)
    modernisation_monthly = Monetary("Monthly Amount (computed)",
        currency='currency', digits='currency', states=_states_mod,
        help="Annual amount / 12 before the cap.")
    modernisation_previous = Monetary("Previous Increases",
        currency='currency', digits='currency', states=_states_mod,
        help="Modernisation increases of the apartment within the cap "
             "period (6 years) before the effective date.")
    modernisation_cap = Monetary("Allowed by the Cap", currency='currency',
        digits='currency', states=_states_mod,
        help="3.00 €/m² (2.00 €/m² below a rent of 7.00 €/m²) within 6 "
             "years less the previous increases; heating 0.50 €/m².")
    modernisation_extension = fields.Selection([
            (None, ''),
            ('missing', "Announcement Missing"),
            ('defective', "Announcement Defective"),
            ('exceeded', "Increase above the Announced (> 10 %)"),
            ], "Extension by 6 Months", sort=False, states=_states_mod,
        help="The effective date is postponed by 6 months (§ 559b para. 2 "
             "BGB).")
    modernisation_text = fields.Text("Calculation", readonly=True,
        states={'invisible': ~_mod})
    termination_deadline = fields.Function(fields.Date(
            "Special Termination until",
            states={'invisible': ~_mod},
            help="The tenant may terminate until the end of the second "
                 "month after the receipt (§ 561 BGB)."),
        'get_termination_deadline')
    terminated_561 = fields.Boolean("Terminated (§ 561)",
        states={
            'invisible': ~_mod,
            'readonly': Eval('state') != 'declared',
            },
        help="The tenant terminated with the special termination right - "
             "the increase does not take effect, cancel the adjustment.")

    @classmethod
    def view_attributes(cls):
        return super().view_attributes() + [
            ('//page[@id="page_modernisation"]', 'states',
                {'invisible': ~cls._mod}, ['procedure']),
            ]

    def get_modernisation(self, name):
        unit = self.modernisation_unit
        return unit.modernisation.id if unit else None

    @classmethod
    def search_modernisation(cls, name, clause):
        return [('modernisation_unit.modernisation',) + tuple(clause[1:])]

    def get_termination_deadline(self, name):
        if self.procedure != 'modernisation':
            return None
        return termination_deadline(self.receipt_date)

    @classmethod
    def write(cls, *args):
        """Special termination period (§ 561 BGB): task after the receipt of
        the declaration - it stays open after the execution (the tenant may
        terminate until the end of the period), cancelled with the
        adjustment"""
        Task = Pool().get('real_estate.task')
        actions = iter(args)
        touched = []
        for records, values in zip(actions, actions):
            if {'receipt_date', 'state'} & set(values):
                touched.extend(r for r in records
                    if r.procedure == 'modernisation')
        super().write(*args)
        for record in cls.browse([r.id for r in touched]):
            if (record.state in ('declared', 'done')
                    and record.termination_deadline):
                task = Task.create_for(record, 'modernisation_termination',
                    record.termination_deadline)
                if task and task.due_date != record.termination_deadline:
                    Task.write([task],
                        {'due_date': record.termination_deadline})
            elif record.state in ('cancelled', 'refused'):
                Task.cancel_for(record, 'modernisation_termination')

    def _compute(self):
        if self.procedure == 'modernisation':
            return self._modernisation_compute()
        return super()._compute()

    def _effective_date(self):
        if self.procedure == 'modernisation':
            return self._modernisation_valid_from(self.planned_amount)
        return super()._effective_date()

    def _received(self):
        "Receipt date, before the receipt a preview from the declaration"
        received = self.receipt_date
        if not received and self.declaration_date:
            received = self.declaration_date + datetime.timedelta(
                days=self.rent_adjustment._receipt_days())
        return received

    def _extension(self, increase):
        unit = self.modernisation_unit
        measure = unit.modernisation
        rule = measure.rule
        return extension_reason(measure.trivial,
            bool(measure.announcement_date), unit.announcement_receipt_date,
            unit.announcement_defective, increase, unit.announced_increase,
            rule.extension_tolerance_percent if rule else 10)

    def _modernisation_valid_from(self, new_amount):
        unit = self.modernisation_unit
        if not unit:
            return self.planned_valid_from
        rule = unit.modernisation.rule
        increase = (new_amount - (self.amount_old or 0)
            if new_amount is not None else None)
        return modernisation_valid_from(self._received(),
            bool(self._extension(increase)),
            rule.extension_months if rule else 6)

    def _modernisation_history(self, unit):
        """Executed modernisation adjustments of the apartment (all
        contracts): (effective date, increase, heating, costs,
        simplified)"""
        adjustments = self.search([
                ('modernisation_unit.object', '=', unit.object.id),
                ('state', '=', 'done'),
                ('id', '!=', self.id or -1),
                ])
        return [(a.planned_valid_from,
                (a.planned_amount or 0) - (a.amount_old or 0),
                a.modernisation.variant == 'heating_559e',
                a.modernisation_costs or Decimal(0),
                a.modernisation.variant == 'simplified_559c')
            for a in adjustments]

    def _modernisation_compute(self):
        """Increase of the rental unit (spec 6.2-6.6) with checks
        E01-E14 - for the declaration date, after the receipt for the
        actual effective date"""
        pool = Pool()
        RentAdjustment = pool.get('real_estate.contract.rent_adjustment')
        Lang = pool.get('ir.lang')
        lang = Lang.get()
        findings = []

        def add(code, level, message_id, **kwargs):
            findings.append((code, level, gettext(
                        'real_estate.' + message_id, **kwargs)))

        def num(value):
            return lang.format_number(value, 2) if value is not None else '-'

        def date(value):
            return value.strftime('%d.%m.%Y') if value else '-'

        unit = self.modernisation_unit
        measure = unit.modernisation
        rule = measure.rule
        term = self.term_old
        contract = term.contract
        run = self.run
        if not self.declaration_date and run:
            self.declaration_date = run.declaration_date or run.key_date
        amount_old = _amount(term)
        values = {
            'planned_quantity': term.quantity,
            'direction': 'increase',
            'planned_amount': None,
            'planned_unit_price': None,
            'planned_valid_from': None,
            'modernisation_area': None,
            'modernisation_costs': None,
            'modernisation_allocable': None,
            'modernisation_annual': None,
            'modernisation_monthly': None,
            'modernisation_previous': None,
            'modernisation_cap': None,
            'modernisation_extension': None,
            'modernisation_text': None,
            }
        if not rule:
            add('E10', 'error', 'msg_modernisation_rule_missing',
                modernisation=measure.rec_name)
            return self._finish_compute(values, findings, self.manual_amount,
                amount_old)
        history = self._modernisation_history(unit)
        received = self._received()

        def allocation(valid_from):
            previous, previous_heating = previous_increases(
                [(d, a, h) for d, a, h, _, _ in history], valid_from,
                rule.cap_years)
            result = measure.allocation({unit.id: {
                        'rent': amount_old,
                        'previous': previous,
                        'previous_heating': previous_heating,
                        }}).get(unit.id)
            return result, previous

        valid_from = modernisation_valid_from(received)
        result, previous = allocation(valid_from) if valid_from else (
            None, Decimal(0))
        extension = self._extension(result['increase']) if result else None
        if extension and valid_from:
            valid_from = modernisation_valid_from(received, True,
                rule.extension_months)
            result, previous = allocation(valid_from)
        if not result or valid_from is None:
            add('E12', 'error', 'msg_modernisation_no_declaration',
                adjustment=self.rec_name)
            return self._finish_compute(values, findings, self.manual_amount,
                amount_old)
        area = measure.cap_areas().get(unit.id)
        increase = result['increase']
        new = amount_old + increase
        quantity = Decimal(str(term.quantity or 0))
        values.update({
                'planned_valid_from': valid_from,
                'planned_amount': new,
                'planned_unit_price': ((new / quantity).quantize(
                        Decimal(10) ** -price_digits[1],
                        rounding=ROUND_HALF_UP) if quantity else None),
                'modernisation_area': area,
                'modernisation_costs': result['costs'],
                'modernisation_allocable': result['allocable'],
                'modernisation_annual': result['annual'],
                'modernisation_monthly': result['monthly'],
                'modernisation_previous': previous,
                'modernisation_cap': result['cap'],
                'modernisation_extension': extension,
                })
        # E12: declaration only after the completion of the measure
        if (measure.state not in ('completed', 'settled')
                or not measure.actual_end
                or (self.declaration_date
                    and self.declaration_date < measure.actual_end)):
            add('E12', 'error', 'msg_modernisation_e12',
                modernisation=measure.rec_name,
                end=date(measure.actual_end))
        # E01: running residential contract on the effective date
        end = contract.get_effective_end_date()
        if (contract.type_of_use != 'residential'
                or contract.state != 'running'
                or (end and end < valid_from)):
            add('E01', 'error', 'msg_modernisation_e01',
                contract=contract.rec_name, end=date(end))
        chain = _term_chain(term)
        # E02: no running graduated rent (§ 557a para. 2 BGB)
        if term.graduated_locked or any(t.valid_from > term.valid_from
                for t in chain):
            add('E02', 'error', 'msg_modernisation_e02',
                term=term.rec_name.strip())
        # E03: index rent only for circumstances not attributable to the
        # landlord, never § 559e (§ 557b para. 2 BGB)
        index_rents = RentAdjustment.search([
                ('term', 'in', [t.id for t in chain]),
                ('procedure', '=', 'index_rent'),
                ('state', '=', 'active'),
                ], limit=1)
        if index_rents and (not measure.not_responsible
                or measure.variant == 'heating_559e'):
            add('E03', 'error', 'msg_modernisation_e03',
                index_rent=index_rents[0].rec_name)
        # E04: hardship objection (not with the simplified procedure)
        if measure.variant != 'simplified_559c' and unit.hardship_received:
            if unit.hardship_decision in (None, 'none'):
                add('E04', 'error', 'msg_modernisation_e04_open',
                    unit=unit.rec_name)
            elif unit.hardship_decision == 'accepted':
                add('E04', 'error', 'msg_modernisation_e04_accepted',
                    unit=unit.rec_name)
        # E05: cap applied
        if result['limited']:
            add('E05', 'ok', 'msg_modernisation_e05',
                computed=num(result['monthly']), cap=num(result['cap']))
        # E06 / E09: simplified procedure (§ 559c BGB)
        lock_start = valid_from - relativedelta(
            years=rule.simplified_lock_years)
        if measure.variant == 'simplified_559c':
            claimed = sum(c for d, _, _, c, _ in history
                if d and lock_start < d <= valid_from)
            if result['costs'] + claimed > rule.simplified_limit:
                add('E06', 'error', 'msg_modernisation_e06',
                    costs=num(result['costs']), claimed=num(claimed),
                    limit=num(rule.simplified_limit))
        locked = [d for d, _, _, _, simplified in history
            if simplified and d and lock_start < d <= valid_from]
        if locked:
            add('E09', 'error', 'msg_modernisation_e09',
                date=date(max(locked)))
        # E07: extension of the effective date
        if extension:
            labels = dict(self.fields_get(['modernisation_extension'])
                ['modernisation_extension']['selection'])
            add('E07', 'warning', 'msg_modernisation_e07',
                reason=labels.get(extension, extension),
                valid_from=date(valid_from))
        # E08: heating system (§ 559e BGB)
        if measure.variant == 'heating_559e':
            if not any(f.kind == 'grant' for f in measure.funds):
                add('E08', 'error', 'msg_modernisation_e08_grant')
            if not measure.heat_pump_jaz_proven:
                add('E08', 'ok', 'msg_modernisation_e08_jaz')
        # E10: area of the cap measurement
        if area is None:
            add('E10', 'error', 'msg_modernisation_e10',
                unit=unit.rec_name)
        # E11: termination after the announcement (§ 555e BGB)
        if unit.terminated:
            add('E11', 'error', 'msg_modernisation_e11',
                unit=unit.rec_name)
        # E13: no increase
        if increase <= 0:
            add('E13', 'error', 'msg_modernisation_e13')
        # E14: booked periods from the effective date
        booked_to = term.get_booked_to()
        if booked_to and booked_to >= valid_from:
            add('E14', 'warning', 'msg_modernisation_e14',
                booked_to=date(booked_to), valid_from=date(valid_from))
        variant = dict(measure.fields_get(['variant'])['variant']
            ['selection']).get(measure.variant, measure.variant)
        values['modernisation_text'] = gettext(
            'real_estate.msg_modernisation_calculation_text',
            modernisation=measure.rec_name, variant=variant,
            share=num(result['share'] * 100), costs=num(result['costs']),
            maintenance=num(result['maintenance']),
            grants=num(result['grants']),
            allocable=num(result['allocable']),
            rate=num(rule.rate_heating if measure.variant == 'heating_559e'
                else rule.rate_standard),
            annual=num(result['annual']), monthly=num(result['monthly']),
            area=num(area), previous=num(previous),
            cap=num(result['cap']), increase=num(increase),
            old=num(amount_old), new=num(new), valid_from=date(valid_from))
        return self._finish_compute(values, findings, self.manual_amount,
            amount_old)

    @classmethod
    def execute(cls, records):
        """Modernisation: split of the rent term from the effective date
        (D-M2) with the increase as share of the adjustment (D-M3)"""
        pool = Pool()
        User = pool.get('res.user')
        employee = User(Transaction().user).employee
        for record in records:
            if (record.procedure == 'modernisation'
                    and record.state == 'declared'):
                record._execute_modernisation(employee)
        super().execute(records)

    def _execute_modernisation(self, employee):
        pool = Pool()
        Term = pool.get('real_estate.contract.term')
        Contract = pool.get('real_estate.contract')
        Date = pool.get('ir.date')
        name = self.rec_name
        if not self.receipt_date:
            raise ValidationError(gettext(
                    'real_estate.msg_modernisation_receipt_missing',
                    adjustment=name))
        if self.terminated_561 or self.modernisation_unit.terminated:
            raise ValidationError(gettext(
                    'real_estate.msg_modernisation_terminated',
                    adjustment=name))
        if self.rent_adjustment.current_term != self.term_old:
            raise ValidationError(gettext(
                    'real_estate.msg_index_adjustment_term_changed',
                    adjustment=name,
                    term=self.term_old.rec_name.strip()))
        valid_from = self._modernisation_valid_from(self.planned_amount)
        contract = self.term_old.contract
        end = contract.get_effective_end_date()
        if contract.state != 'running' or (end and end < valid_from):
            raise ValidationError(gettext(
                    'real_estate.msg_modernisation_e01',
                    contract=contract.rec_name,
                    end=end.strftime('%d.%m.%Y') if end else '-'))
        new_term = Term._split(self.term_old, valid_from,
            self.planned_unit_price, self.planned_quantity)
        Contract._re_calc_terms([contract])
        self.__class__.write([self], {
                'term_new': new_term.id,
                'planned_valid_from': valid_from,
                'executed_by': employee.id if employee else None,
                'executed_date': Date.today(),
                })
        contract.add_log('modernisation', gettext(
                'real_estate.msg_modernisation_log',
                modernisation=self.modernisation.rec_name,
                amount_old=self.amount_old, amount_new=self.planned_amount,
                increase=self.planned_amount - (self.amount_old or 0),
                valid_from=valid_from.strftime('%d.%m.%Y'),
                receipt=self.receipt_date.strftime('%d.%m.%Y')))


#**********************************************************************
class ModernisationUnit(metaclass=PoolMeta):
    __name__ = 'real_estate.modernisation.unit'

    adjustment = fields.Function(fields.Many2One(
            'real_estate.contract.term.adjustment', "Increase (Adjustment)"),
        'get_adjustment')
    adjustment_state = fields.Function(fields.Selection(
            'get_adjustment_states', "Increase State"),
        'get_adjustment')

    @classmethod
    def get_adjustment_states(cls):
        Adjustment = Pool().get('real_estate.contract.term.adjustment')
        return [(None, '')] + Adjustment.fields_get(['state'])['state'][
            'selection']

    @classmethod
    def get_adjustment(cls, units, names):
        Adjustment = Pool().get('real_estate.contract.term.adjustment')
        result = {n: {u.id: None for u in units} for n in names}
        latest = {}
        for adjustment in Adjustment.search([
                    ('modernisation_unit', 'in', [u.id for u in units]),
                    ], order=[('id', 'ASC')]):
            unit_id = adjustment.modernisation_unit.id
            # the latest adjustment, a cancelled one only without another
            if unit_id in latest and adjustment.state == 'cancelled':
                continue
            latest[unit_id] = adjustment
        for unit_id, adjustment in latest.items():
            if 'adjustment' in names:
                result['adjustment'][unit_id] = adjustment.id
            if 'adjustment_state' in names:
                result['adjustment_state'][unit_id] = adjustment.state
        return result


#**********************************************************************
class ModernisationIncreaseLetter(IndexAdjustmentLetterReport):
    """Declaration of a modernisation increase (§ 559b BGB, spec 8.2) - one
    letter per adjustment to all main tenants with the costs, deductions,
    allocation, calculation, cap, new rent, effective date and the special
    termination right (§ 561 BGB)"""
    __name__ = 'real_estate.modernisation.increase_letter'

    @classmethod
    def get_context(cls, records, header, data):
        pool = Pool()
        Modernisation = pool.get('real_estate.modernisation')
        context = super().get_context(records, header, data)
        labels = dict(Modernisation.fields_get(['measure_types'])
            ['measure_types']['selection'])
        keys = dict(Modernisation.fields_get(['allocation_key'])
            ['allocation_key']['selection'])
        variants = dict(Modernisation.fields_get(['variant'])['variant']
            ['selection'])
        measures, deadlines = {}, {}
        for record in records:
            unit = record.modernisation_unit
            measure = unit.modernisation if unit else None
            if not measure:
                continue
            measures[record.id] = {
                'measure': measure,
                'unit': unit,
                'types': [labels.get(t, t)
                    for t in (measure.measure_types or [])],
                'key': keys.get(measure.allocation_key,
                    measure.allocation_key),
                'variant': variants.get(measure.variant, measure.variant),
                'costs': measure.allocation_cost_lines(),
                'gross': not unit.vat_deductible,
                'rate': (measure.rule.rate_heating
                    if measure.variant == 'heating_559e'
                    else measure.rule.rate_standard)
                if measure.rule else None,
                }
            rule = measure.rule
            area = record.modernisation_area
            per_sqm = ((record.amount_old or 0) / area) if area else None
            measures[record.id]['cap_rate'] = ((rule.cap_low
                    if per_sqm is not None and per_sqm < rule.cap_threshold
                    else rule.cap_high) if rule else None)
            deadlines[record.id] = termination_deadline(record.receipt_date)
        context['measures'] = measures
        context['termination_until'] = deadlines
        return context
