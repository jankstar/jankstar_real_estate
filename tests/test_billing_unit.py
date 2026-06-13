"""
Billing Units für die zwei Testimmobilien anlegen.

Je Wirtschaftseinheit werden zwei Billing Units angelegt:

  1. "Kalte Betriebskosten 2025" (calculation_method=rental_apartment)

     Alle Settlement Units verwenden Objekt-Regex "Wohnung|Einzelhandel",
     d.h. sowohl Wohnungen als auch Gewerbeflächen (Einzelhandel) werden
     als Abrechnungsobjekte einbezogen.

     Bemessungsbasierte Settlement Units (m_type=Wohnfläche, sequence=10):
       Für Wohnungen wird die Wohnfläche herangezogen; für Einzelhandel-
       Objekte greift der Fallback auf gleiche Einheit (m²), sodass die
       Gewerbefläche verwendet wird.

       100 Grundsteuer              — Bemessung Fläche m², Leerstand: Eigentümer
       110 Gebäudeversicherung      — Bemessung Fläche m², Leerstand: Eigentümer
       500 Straßenreinigung         — Bemessung Fläche m², Leerstand: Eigentümer
       510 Müllabfuhr               — Bemessung Fläche m², Leerstand: Eigentümer
       520 Hausreinigung            — Bemessung Fläche m², Leerstand: Eigentümer
       600 Gartenpflege             — Bemessung Fläche m², Leerstand: Eigentümer
       610 Hausstrom                — Bemessung Fläche m², Leerstand: Eigentümer
       620 Schornsteinfeger         — Bemessung Fläche m², Leerstand: Eigentümer
       700 Hausmeister              — Bemessung Fläche m², Leerstand: Eigentümer

     Verbrauchsbasierte Settlement Unit (Zähler-Regex "Wasser Zähler"):
       Die Regex trifft sowohl Wohnungszähler ("Wasser Zähler 01" …) als
       auch Einzelhandelszähler ("Wasser Zähler EH01" …).

       200 Wasserversorgung/Abwasser — Verbrauch m³, Leerstand: Eigentümer

  2. "Heizkosten 2025" (calculation_method=rental_apartment)
     Settlement Units (Objekt-Regex: "Wohnung|Einzelhandel"):
       300 Heizung (Brennstoff)     — externe Abrechnung
       310 Heizung (Wartung)        — externe Abrechnung

Voraussetzung: test_immo.py muss ausgeführt worden sein
(Properties "Musterstraße 1-4" und "Musterstraße 5-8").

Das Skript ist idempotent: es bricht ab, wenn für "Musterstraße 1-4"
bereits Billing Units vorhanden sind.

Verwendung:
    python tests/test_billing_unit.py --database <Datenbankname> [--config <trytond.conf>]
"""

import argparse
import datetime
import sys

from proteus import Model, config

START_DATE = datetime.date(2025, 1, 1)

# Sequences of cost types allocated by measurement (Wohnfläche, by_owner vacancy)
MEASUREMENT_SEQUENCES = [100, 110, 500, 510, 520, 600, 610, 620, 700]
# Water: allocated by consumption (m³)
WATER_SEQUENCE = 200
# Heating: external billing
HEAT_SEQUENCES = [300, 310]


# ---------------------------------------------------------------------------
# Verbindung
# ---------------------------------------------------------------------------

def connect(database: str, cfg_file: str | None):
    if cfg_file:
        return config.set_trytond(database=database, config_file=cfg_file)
    else:
        return config.set_trytond(database=database)


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def get_company():
    Company = Model.get('company.company')
    companies = Company.find([])
    if not companies:
        print('ERROR: Keine Company gefunden.', file=sys.stderr)
        sys.exit(1)
    if len(companies) > 1:
        print(f'Mehrere Companies gefunden, verwende: {companies[0].rec_name}')
    return companies[0]


def get_properties():
    BaseObject = Model.get('real_estate.base_object')
    props = []
    for name in ('Musterstraße 1-4', 'Musterstraße 5-8'):
        results = BaseObject.find([
            ('name', '=', name),
            ('type', '=', 'property'),
        ])
        if not results:
            print(f'ERROR: Property "{name}" nicht gefunden. '
                  'Bitte zuerst test_immo.py ausführen.', file=sys.stderr)
            sys.exit(1)
        props.append(results[0])
    return props


def get_cost_type(sequence: int):
    CostType = Model.get('real_estate.cost_type')
    results = CostType.find([('sequence', '=', sequence)])
    if not results:
        print(f'ERROR: CostType mit sequence={sequence} nicht gefunden.',
              file=sys.stderr)
        sys.exit(1)
    return results[0]


def get_measurement_type_living_space():
    MType = Model.get('real_estate.measurement.type')
    # sequence 10 = Living Space (Wohnfläche)
    results = MType.find([('sequence', '=', 10)])
    if not results:
        print('ERROR: MeasurementType "Wohnfläche" (sequence=10) nicht gefunden.',
              file=sys.stderr)
        sys.exit(1)
    return results[0]


def get_uom_m3():
    UoM = Model.get('product.uom')
    results = UoM.find([('symbol', '=', 'm³')])
    if not results:
        print('ERROR: UoM mit Symbol "m³" nicht gefunden.', file=sys.stderr)
        sys.exit(1)
    return results[0]


def get_term_type(sequence: int):
    TermType = Model.get('real_estate.contract.term.type')
    results = TermType.find([('sequence', '=', sequence)])
    if not results:
        print(f'WARNUNG: ContractTermType mit sequence={sequence} nicht gefunden '
              f'— term_types_of_use für diese Billing Unit wird nicht gesetzt.')
        return None
    return results[0]


# ---------------------------------------------------------------------------
# Billing Unit anlegen
# ---------------------------------------------------------------------------

def create_billing_unit(prop, description: str, term_type_ids: list) -> object:
    BillingUnit = Model.get('real_estate.billing_unit')
    bu = BillingUnit()
    bu.property = prop
    bu.start_date = START_DATE
    bu.calculation_method = 'rental_apartment'
    bu.billing_type = 'planned_billing'
    bu.description = description
    if term_type_ids:
        bu.term_types_of_use = [str(tid) for tid in term_type_ids]
    bu.save()
    print(f'  BillingUnit: "{bu.name}" id={bu.id}')
    return bu


def create_su_measurement(bu, cost_type, m_type) -> None:
    SU = Model.get('real_estate.settlement_unit')
    su = SU()
    su.billing_unit = bu
    su.type = cost_type
    su.sequence = cost_type.sequence
    su.allocation_rule = 'allocation_by_measurement'
    su.m_type = m_type
    su.vacancy = 'by_owner'
    su.reg_ex_object = 'Wohnung|Einzelhandel'
    su.save()
    print(f'    SU {su.sequence}: {cost_type.name} '
          f'→ Wohnfläche / Leerstand: Eigentümer '
          f'/ Objekt-Regex: "Wohnung|Einzelhandel"')


def create_su_consumption(bu, cost_type, meter_unit) -> None:
    SU = Model.get('real_estate.settlement_unit')
    su = SU()
    su.billing_unit = bu
    su.type = cost_type
    su.sequence = cost_type.sequence
    su.allocation_rule = 'allocation_by_consumption'
    su.meter_unit = meter_unit
    su.vacancy = 'by_owner'
    su.reg_ex_object = 'Wohnung|Einzelhandel'
    su.reg_ex_meter = 'Wasser Zähler'
    su.save()
    print(f'    SU {su.sequence}: {cost_type.name} '
          f'→ Verbrauch {meter_unit.symbol} / Leerstand: Eigentümer '
          f'/ Objekt-Regex: "Wohnung|Einzelhandel" / Zähler-Regex: "Wasser Zähler"')


def create_su_external(bu, cost_type) -> None:
    SU = Model.get('real_estate.settlement_unit')
    su = SU()
    su.billing_unit = bu
    su.type = cost_type
    su.sequence = cost_type.sequence
    su.allocation_rule = 'allocation_from_external_billing'
    su.reg_ex_object = 'Wohnung|Einzelhandel'
    su.save()
    print(f'    SU {su.sequence}: {cost_type.name} '
          f'→ externe Abrechnung / Objekt-Regex: "Wohnung|Einzelhandel"')


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True, help='Tryton-Datenbankname')
    parser.add_argument('--config', default=None, help='Pfad zur trytond.conf')
    args = parser.parse_args()

    connect(args.database, args.config)

    # Idempotenz
    BillingUnit = Model.get('real_estate.billing_unit')
    properties = get_properties()
    if BillingUnit.find([('property', '=', properties[0].id)]):
        print(f'Für Property "{properties[0].name}" sind bereits Billing Units '
              'vorhanden. Abbruch.')
        return

    # Stammdaten laden
    m_type_wfl = get_measurement_type_living_space()
    uom_m3 = get_uom_m3()

    ct_measurement = [get_cost_type(seq) for seq in MEASUREMENT_SEQUENCES]
    ct_water = get_cost_type(WATER_SEQUENCE)
    ct_heat = [get_cost_type(seq) for seq in HEAT_SEQUENCES]

    tt_bk = get_term_type(2000)    # Betriebskosten
    tt_hz = get_term_type(3000)    # Heizkosten

    print(f'Measurement Type: {m_type_wfl.name}')
    print(f'UoM: {uom_m3.symbol}')
    print()

    for prop in properties:
        print(f'{"=" * 60}')
        print(f'Property: {prop.name}')
        print(f'{"=" * 60}')

        # --- Billing Unit 1: Kalte Betriebskosten 2025 ---
        print('\n--- Kalte Betriebskosten 2025 ---')
        tt_ids_bk = [tt_bk.id] if tt_bk else []
        bu_bk = create_billing_unit(
            prop=prop,
            description='Kalte Betriebskosten 2025',
            term_type_ids=tt_ids_bk,
        )

        for ct in ct_measurement:
            create_su_measurement(bu_bk, ct, m_type_wfl)

        create_su_consumption(bu_bk, ct_water, uom_m3)

        # --- Billing Unit 2: Heizkosten 2025 ---
        print('\n--- Heizkosten 2025 ---')
        tt_ids_hz = [tt_hz.id] if tt_hz else []
        bu_hz = create_billing_unit(
            prop=prop,
            description='Heizkosten 2025',
            term_type_ids=tt_ids_hz,
        )

        for ct in ct_heat:
            create_su_external(bu_hz, ct)

        print()

    print('Fertig.')


if __name__ == '__main__':
    main()
