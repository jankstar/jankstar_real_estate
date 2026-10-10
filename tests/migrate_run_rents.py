"""
Test migration: set the rent of the contracts of an adjustment run to
about a given rent per m² (default 6.00 EUR/m²) from the contract start -
to test the comparative rent procedure with rents below the rent survey.

For every adjustment of the run (e.g. 'AL-2026-0001') the rent term
(term_old) gets a new unit price. A run without adjustments (draft, reset)
takes the candidates of its filters instead: current monthly rent terms of
running contracts of its properties/contracts whose contract type and term
type allow the comparative rent, without an active index rent:

- term with an area as quantity (quantity > 1, e.g. 57 m²): unit price =
  rent per m² (± spread, fixed per contract);
- term with an absolute amount (quantity 1): unit price = rent per m² ×
  living space of the apartment (from the comparative rent calculation of
  the adjustment, else from the measurement 'Living Space').

The rent per m² varies per contract within ± spread (default 0.20 EUR),
derived from the contract number - so a repeated run sets the same values
(idempotent). Only the current (open) rent term is changed; earlier terms
of the chain (with 'Valid to') are reported and left unchanged, proteus
does not write fields that are read-only in the client.

Warning: the unit price is changed on terms that may already be booked -
the posted invoices stay as they are (test data only). Warnings of the
module (booked values) are confirmed automatically.

With --recalculate the run is calculated again afterwards (state
'selected' or 'calculated'), otherwise press 'Calculate' in the run.

Usage:
    python tests/migrate_run_rents.py --database <database_name>
        [--config <trytond.conf>] [--run AL-2026-0001] [--rent 6.00]
        [--spread 0.20] [--recalculate] [--dry-run]
"""

import argparse
import hashlib
from decimal import ROUND_HALF_UP, Decimal

from proteus import Model, config
from trytond.exceptions import UserWarning as TrytonUserWarning

LIVING_SPACE_SEQUENCE = 10   # measurement type 'Wohnfläche' (see test_immo.py)
CENT = Decimal('0.01')
PRICE = Decimal('0.0001')


def connect(database: str, cfg_file: str | None):
    if cfg_file:
        return config.set_trytond(database=database, config_file=cfg_file)
    return config.set_trytond(database=database)


def rent_per_sqm(contract_number: str, rent: Decimal,
        spread: Decimal) -> Decimal:
    "Rent per m² within ± spread, fixed per contract number"
    digest = hashlib.sha256(contract_number.encode('utf-8')).digest()
    share = Decimal(digest[0]) / Decimal(255)          # 0 ... 1
    return (rent - spread + 2 * spread * share).quantize(
        CENT, rounding=ROUND_HALF_UP)


def living_space(adjustment, term):
    "Living space of the apartment: calculation, else measurement"
    if adjustment and adjustment.calculation and adjustment.calculation.area:
        return Decimal(str(adjustment.calculation.area))
    objects = (list(term.reference_item.objects)
        if term.reference_item else [])
    if len(objects) != 1:
        return None
    apartment, = objects
    MeasurementType = Model.get('real_estate.measurement.type')
    Measurement = Model.get('real_estate.measurement')
    types = MeasurementType.find([('sequence', '=', LIVING_SPACE_SEQUENCE)])
    if not types:
        return None
    values = Measurement.find([
            ('base_object', '=', apartment.id),
            ('m_type', '=', types[0].id),
            ], order=[('valid_from', 'DESC')], limit=1)
    return Decimal(str(values[0].value)) if values else None


def chain_terms(term):
    "Rent terms of the chain: same contract, term type and item"
    Term = Model.get('real_estate.contract.term')
    return Term.find([
            ('contract', '=', term.contract.id),
            ('term_type', '=', term.term_type.id),
            ('reference_item', '=',
                term.reference_item.id if term.reference_item else None),
            ], order=[('valid_from', 'ASC')])


def save_confirmed(record, attempts=5):
    """Save and confirm the warnings of the module (e.g. booked values):
    a raised UserWarning is acknowledged by a res.user.warning record with
    its key, then the save is repeated"""
    Warning_ = Model.get('res.user.warning')
    for _ in range(attempts):
        try:
            record.save()
            return
        except TrytonUserWarning as warning:
            Warning_(user=config.get_config().user, name=warning.name,
                always=False).save()
    record.save()


def run_terms(run):
    """(adjustment, term) of the run - without adjustments the current
    rent terms of the run's filters (as the selection)"""
    Term = Model.get('real_estate.contract.term')
    RentAdjustment = Model.get('real_estate.contract.rent_adjustment')
    adjustments = [a for a in run.adjustments if a.state != 'cancelled']
    if adjustments:
        return [(a, Term(a.term_old.id)) for a in adjustments]
    domain = [
        ('contract.company', '=', run.company.id),
        ('contract.state', '=', 'running'),
        ('contract.c_type.adjustment_procedures', 'in',
            ['comparative_rent']),
        ('term_type.adjustment_procedures', 'in', ['comparative_rent']),
        ('rhythm_type', '=', 'monthly'),
        ('valid_to', '=', None),
        ]
    if run.properties:
        domain.append(('contract.property', 'in',
                [p.id for p in run.properties]))
    if run.contracts:
        domain.append(('contract', 'in', [c.id for c in run.contracts]))
    result = []
    for term in Term.find(domain):
        index_rents = RentAdjustment.find([
                ('contract', '=', term.contract.id),
                ('procedure', '=', 'index_rent'),
                ('state', '=', 'active'),
                ])
        if index_rents:
            print(f'  {term.contract.contract_number}: active index rent - '
                f'skipped')
            continue
        result.append((None, term))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--database', required=True,
        help='Tryton database name')
    parser.add_argument('--config', default=None,
        help='Path to trytond.conf')
    parser.add_argument('--run', default='AL-2026-0001',
        help='Number of the adjustment run (default AL-2026-0001)')
    parser.add_argument('--rent', default='6.00',
        help='Target rent per m² in EUR (default 6.00)')
    parser.add_argument('--spread', default='0.20',
        help='Variation per contract in EUR/m² (default 0.20)')
    parser.add_argument('--recalculate', action='store_true',
        help='Calculate the run again afterwards')
    parser.add_argument('--dry-run', action='store_true',
        help='Only show the new rents, change nothing')
    args = parser.parse_args()

    cfg = connect(args.database, args.config)
    rent = Decimal(args.rent)
    spread = Decimal(args.spread)

    Run = Model.get('real_estate.contract.term.adjustment.run')
    runs = Run.find([('run_id', '=', args.run)])
    if not runs:
        print(f'Adjustment run "{args.run}" not found. Aborting.')
        return
    run, = runs
    cfg._context['company'] = run.company.id
    print(f'Run {run.run_id} ({run.procedure}, state {run.state}): '
        f'{len(run.adjustments)} adjustments')

    changed = 0
    for adjustment, term in run_terms(run):
        contract = term.contract
        per_sqm = rent_per_sqm(contract.contract_number or str(contract.id),
            rent, spread)
        quantity = Decimal(str(term.quantity or 0))
        if quantity > 1:
            unit_price = per_sqm
            area = quantity
        else:
            area = living_space(adjustment, term)
            if not area:
                print(f'  {contract.contract_number}: no living space '
                    f'found - skipped')
                continue
            unit_price = (per_sqm * area).quantize(CENT,
                rounding=ROUND_HALF_UP)
        old_amount = (quantity * term.unit_price).quantize(CENT)
        new_amount = (quantity * unit_price).quantize(CENT,
            rounding=ROUND_HALF_UP)
        print(f'  {contract.contract_number}: {area} m², '
            f'{old_amount} -> {new_amount} EUR '
            f'({per_sqm} EUR/m², from {term.valid_from})')
        earlier = [t for t in chain_terms(term)
            if t.id != term.id and t.valid_from < term.valid_from]
        if earlier:
            print(f'    note: {len(earlier)} earlier rent term(s) of the '
                f'chain stay unchanged')
        if args.dry_run or term.unit_price == unit_price.quantize(PRICE):
            continue
        term.unit_price = unit_price.quantize(PRICE)
        save_confirmed(term)
        changed += 1

    print(f'{changed} rent terms changed.')
    if args.dry_run:
        print('Dry run - nothing saved.')
        return
    if args.recalculate:
        run = Run(run.id)
        if run.state in ('selected', 'calculated'):
            run.click('calculate')
            print(f'Run {run.run_id} calculated again.')
        else:
            print(f'Run {run.run_id} is in state {run.state} - not '
                f'calculated again.')
    else:
        print(f'Press "Calculate" in the run {run.run_id} to recompute '
            f'the adjustments.')


if __name__ == '__main__':
    main()
