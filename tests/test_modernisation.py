"""
Demo data for the modernisation (spezifikation-modernisierung.md).

Requires test_immo.py and test_contracts.py (properties "Musterstraße 1-4"
and "Musterstraße 5-8" with running residential contracts).

Creates on "Musterstraße 1-4":

  - Measure "Fassadendämmung Haus 2" (standard § 559, 8 %) for the second
    building: allocation by the measurement "Wohnfläche", cost lines per
    trade (facade insulation with 20 % maintenance share, windows with a
    maintenance amount, scaffolding without maintenance share, all + 19 %
    input tax), grant "BEG EM" 10,000 EUR. The measure is announced today
    (letters per rental unit), the receipt of the announcement is captured
    today, the work starts after the announcement period and is completed
    two months later. With a rent survey of the property (test_rent_survey
    .py) the measure gets the planned features "remove old heating / add
    insulation" for the building, is calculated (what if) before the
    announcement and the planned features are applied after the
    completion.
  - Adjustment run with the procedure Modernisation for this measure,
    selected and calculated (state "calculated") - approve, announce,
    receipts and execution are done in the client (or with --execute:
    approve and announce; the receipts and the execution stay manual).
  - If an apartment of the property is vacant: measure "Bad und
    Küche <unit>" as vacancy measure, comprehensive modernisation,
    completed and settled at once - basis of § 556e para. 2 / § 556f BGB in
    the check of the comparative rent of the new letting.

Before: the procedure "modernisation" is allowed for the term type 1000
(apartment rent) and the contract types of the selected tenancies, and the
cap measurement of the modernisation rule is set to "Wohnfläche" if empty.

Dates are relative to today: warnings of the module for dates in the
future are confirmed automatically.

The script is idempotent: it stops if the measure "Fassadendämmung Haus 2"
exists.

Usage:
    python tests/test_modernisation.py --database <database_name>
        [--config <trytond.conf>] [--execute]
"""

import argparse
import datetime
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from proteus import Model, config
from trytond.exceptions import UserWarning as TrytonUserWarning

PROPERTY = 'Musterstraße 1-4'
MEASURE = 'Fassadendämmung Haus 2'
LIVING_SPACE_SEQUENCE = 10      # measurement type "Wohnfläche"
RENT_TERM_SEQUENCE = 1000       # term type "Apartment rent"
INPUT_TAX = 'VSt. 19% Vorsteuer voll Waren Inland'
# planned features of the rent survey (Berliner Mietspiegel 2026) for the
# building after the modernisation: (feature code, action)
PLANNED_FEATURES = [('g_old_heating', 'remove'), ('g_insulation', 'add')]


def connect(database, cfg_file):
    if cfg_file:
        return config.set_trytond(database=database, config_file=cfg_file)
    return config.set_trytond(database=database)


def confirmed(function, *args, attempts=6):
    """Call and confirm the warnings of the module (res.user.warning with
    the key of the warning), then call again"""
    Warning_ = Model.get('res.user.warning')
    for _ in range(attempts):
        try:
            return function(*args)
        except TrytonUserWarning as warning:
            Warning_(user=config.get_config().user, name=warning.name,
                always=False).save()
    return function(*args)


def allow_procedure(record, procedure='modernisation'):
    procedures = list(record.adjustment_procedures or [])
    if procedure not in procedures:
        record.adjustment_procedures = procedures + [procedure]
        record.save()
        print(f'  procedure "{procedure}" allowed for "{record.name}"')


def prepare(living_space):
    "Allowed procedure (term type) and cap measurement of the rule"
    TermType = Model.get('real_estate.contract.term.type')
    Rule = Model.get('real_estate.modernisation.rule')
    MeasurementType = Model.get('real_estate.measurement.type')
    for term_type in TermType.find([('sequence', '=', RENT_TERM_SEQUENCE)]):
        allow_procedure(term_type)
    for rule in Rule.find([]):
        if not rule.cap_m_type:
            rule.cap_m_type = MeasurementType(living_space.id)
            rule.save()
            print(f'  cap measurement of the rule {rule.valid_from} set')


def fill_quantities(measure):
    "Units without a quantity (e.g. commercial units) get 0"
    Unit = Model.get('real_estate.modernisation.unit')
    for unit in measure.units:
        if unit.in_allocation and unit.allocation_quantity is None:
            unit = Unit(unit.id)
            unit.allocation_quantity = Decimal(0)
            unit.save()


def create_measure(prop, building, living_space, tax, today):
    Modernisation = Model.get('real_estate.modernisation')
    BaseObject = Model.get('real_estate.base_object')
    MeasurementType = Model.get('real_estate.measurement.type')
    Cost = Model.get('real_estate.modernisation.cost')
    Fund = Model.get('real_estate.modernisation.fund')
    Tax = Model.get('account.tax')
    Unit = Model.get('real_estate.modernisation.unit')
    start = today + relativedelta(months=3, days=7)
    measure = Modernisation(name=MEASURE, property=prop,
        measure_types=['1'], variant='standard_559',
        description='Wärmedämmverbundsystem 16 cm an allen Fassaden, '
            'Austausch der Fenster gegen Wärmeschutzverglasung (Uw 0,9)',
        energy_saving_note='Einsparung nach Pauschalwerten der '
            'Bekanntmachung zu § 555c Abs. 3 BGB',
        planned_start=start, planned_duration='ca. 2 Monate',
        expected_operating_costs='keine Änderung der Betriebskosten '
            'zu erwarten')
    measure.allocation_key = 'measurement'
    measure.allocation_m_type = MeasurementType(living_space.id)
    measure.allocation_note = 'Verteilung nach Wohnfläche der Mietobjekte'
    measure.buildings.append(BaseObject(building.id))
    measure.save()
    measure.click('compute_units')
    for description, amount, mode, value in [
            ('Fassadendämmung', '52000', 'percent', '20'),
            ('Fenster', '21000', 'amount', '4000'),
            ('Gerüst', '6000', 'none', None)]:
        cost = Cost(modernisation=measure, description=description,
            state='planned', amount=Decimal(amount), maintenance_mode=mode,
            maintenance_value=Decimal(value) if value else None)
        cost.tax = Tax(tax.id)
        cost.save()
    Fund(modernisation=measure, kind='grant', source='BEG EM (BAFA)',
        amount=Decimal('10000')).save()
    measure.reload()
    fill_quantities(measure)
    measure.reload()
    plan_features(measure, prop, building)
    measure.click('take_over')
    measure.reload()
    confirmed(measure.click, 'announce')
    measure.reload()
    print(f'  {measure.number} announced on {measure.announcement_date}')
    for unit in measure.units:
        if unit.contract and not unit.excluded:
            unit = Unit(unit.id)
            unit.announcement_receipt_date = today
            confirmed(unit.save)
            print(f'    {unit.object.name}: expected increase '
                f'{unit.announced_increase} EUR')
    measure.reload()
    measure.actual_start = start
    measure.save()
    confirmed(measure.click, 'start')
    measure.reload()
    # actual costs = planned costs
    for cost in measure.cost_lines:
        cost = Cost(cost.id)
        cost.state = 'actual'
        cost.save()
    measure.reload()
    measure.actual_end = start + relativedelta(months=2)
    measure.save()
    confirmed(measure.click, 'complete')
    measure.reload()
    print(f'  {measure.number} completed on {measure.actual_end} '
        f'({measure.state})')
    if measure.planned_values:
        measure.click('apply_planned_values')
        measure.reload()
        print(f'  planned features applied on {measure.planned_values_applied}'
            f' (valid from {measure.actual_end})')
    return measure


def plan_features(measure, prop, building):
    """Planned features of the rent survey (what if) and calculation - only
    with a rent survey of the property (test_rent_survey.py)"""
    PlannedValue = Model.get('real_estate.modernisation.planned_value')
    Feature = Model.get('real_estate.rent_survey.feature')
    BaseObject = Model.get('real_estate.base_object')
    if not prop.rent_survey:
        print('  no rent survey - planned features skipped')
        return
    for code, action in PLANNED_FEATURES:
        features = [f for f in Feature.find([('code', '=', code)])
            if f.group.version.survey.id == prop.rent_survey.id]
        if not features:
            continue
        planned = PlannedValue(modernisation=measure,
            object=BaseObject(building.id), kind='feature', action=action)
        planned.survey_feature = features[-1]
        planned.save()
    measure.reload()
    measure.click('calculate')
    measure.reload()
    for line in measure.calculations:
        if line.comparative_after is not None:
            print(f'    {line.object.name}: § 559 +{line.increase}, '
                f'comparative rent {line.comparative_before} -> '
                f'{line.comparative_after}, § 558 {line.new_rent_558}')


def create_run(measure, execute):
    Run = Model.get('real_estate.contract.term.adjustment.run')
    Modernisation = Model.get('real_estate.modernisation')
    Adjustment = Model.get('real_estate.contract.term.adjustment')
    date = measure.actual_end + datetime.timedelta(days=10)
    ContractType = Model.get('real_estate.contract.type')
    # the procedure has to be allowed for the contract types of the units
    for c_type_id in {u.contract.c_type.id for u in measure.units
            if u.contract and u.contract.c_type and not u.excluded}:
        allow_procedure(ContractType(c_type_id))
    run = Run(procedure='modernisation', name=f'Modernisierung {MEASURE}',
        key_date=date, declaration_date=date)
    run.modernisations.append(Modernisation(measure.id))
    run.save()
    run.click('select')
    run.click('calculate')
    run.reload()
    print(f'  run {run.run_id}: {run.summary}')
    for adjustment in run.adjustments:
        print(f'    {adjustment.rec_name}: {adjustment.amount_old} -> '
            f'{adjustment.planned_amount} EUR ({adjustment.check_state})')
        if adjustment.check_state == 'warning':
            adjustment = Adjustment(adjustment.id)
            adjustment.approval_reason = 'Demodaten'
            adjustment.save()
    if execute:
        run.reload()
        run.click('approve')
        run.reload()
        confirmed(run.click, 'declare')
        run.reload()
        print(f'  run {run.run_id} announced ({run.state}) - capture the '
            f'receipts in the tab "Receipts / Consents" and execute')
    return run


def create_vacancy_measure(prop, living_space, today):
    "Comprehensive modernisation of a vacant apartment of the property"
    Modernisation = Model.get('real_estate.modernisation')
    BaseObject = Model.get('real_estate.base_object')
    MeasurementType = Model.get('real_estate.measurement.type')
    Occupancy = Model.get('real_estate.base_object.occupancy')
    Cost = Model.get('real_estate.modernisation.cost')
    Unit = Model.get('real_estate.modernisation.unit')
    vacant = None
    for obj in BaseObject.find([
                ('parent', 'child_of', [prop.id]),
                ('type', '=', 'object'),
                ('name', 'like', 'Wohnung%'),
                ]):
        rented = Occupancy.find([
                ('base_object', '=', obj.id),
                ('contract', '!=', None),
                ('start_date', '<=', today),
                ['OR', ('end_date', '=', None), ('end_date', '>=', today)],
                ])
        if not rented:
            vacant = obj
            break
    if not vacant:
        print('  no vacant apartment - vacancy measure skipped')
        return None
    measure = Modernisation(name=f'Bad und Küche {vacant.name}',
        property=prop, measure_types=['4', '5'], vacancy=True,
        comprehensive=True,
        comprehensive_note='Erneuerung von Bad, Küche, Elektrik, Böden '
            'und Heizkörpern - Aufwand rund ein Drittel eines Neubaus',
        description='Komplettsanierung der Wohnung im Leerstand')
    measure.allocation_key = 'measurement'
    measure.allocation_m_type = MeasurementType(living_space.id)
    measure.save()
    Unit(modernisation=measure, object=BaseObject(vacant.id),
        in_allocation=True, excluded=True, exclusion_reason='vacancy',
        allocation_quantity=Decimal(1)).save()
    Cost(modernisation=measure, description='Sanierung Wohnung',
        state='actual', amount=Decimal('42000'),
        maintenance_mode='percent', maintenance_value=Decimal('30')).save()
    measure.reload()
    measure.click('take_over')
    measure.reload()
    measure.actual_start = today - relativedelta(months=2)
    measure.save()
    measure.click('start')
    measure.reload()
    measure.actual_end = today - relativedelta(days=7)
    measure.save()
    measure.click('complete')
    measure.reload()
    unit = measure.units[0]
    print(f'  {measure.number} {measure.name}: {measure.state}, increase '
        f'per month {unit.expected_increase} EUR (new letting, § 556e '
        f'para. 2 BGB)')
    return measure


def main():
    parser = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--database', required=True,
        help='Tryton database name')
    parser.add_argument('--config', default=None,
        help='Path to trytond.conf')
    parser.add_argument('--execute', action='store_true',
        help='Approve and announce the adjustment run as well')
    args = parser.parse_args()

    cfg = connect(args.database, args.config)
    BaseObject = Model.get('real_estate.base_object')
    MeasurementType = Model.get('real_estate.measurement.type')
    Modernisation = Model.get('real_estate.modernisation')
    Tax = Model.get('account.tax')
    Date = Model.get('ir.date')

    props = BaseObject.find([('name', '=', PROPERTY),
            ('type', '=', 'property')])
    if not props:
        print(f'Property "{PROPERTY}" not found - run test_immo.py first.')
        return
    prop, = props
    cfg._context['company'] = prop.company.id
    if Modernisation.find([('name', '=', MEASURE)]):
        print(f'Measure "{MEASURE}" exists already. Aborting.')
        return
    living_space, = MeasurementType.find([
            ('sequence', '=', LIVING_SPACE_SEQUENCE)])
    taxes = Tax.find([('name', '=', INPUT_TAX),
            ('company', '=', prop.company.id)])
    if not taxes:
        print(f'Tax "{INPUT_TAX}" not found. Aborting.')
        return
    buildings = BaseObject.find([('parent', '=', prop.id),
            ('type', '=', 'building')], order=[('name', 'ASC')])
    if len(buildings) < 2:
        print('The property needs two buildings (test_immo.py). Aborting.')
        return
    today = Date.today({})

    print('Preparation')
    prepare(living_space)
    print(f'Measure {MEASURE}')
    measure = create_measure(prop, buildings[1], living_space, taxes[0],
        today)
    print('Adjustment run')
    create_run(measure, args.execute)
    print('Vacancy measure')
    create_vacancy_measure(prop, living_space, today)
    print('Done.')


if __name__ == '__main__':
    main()
