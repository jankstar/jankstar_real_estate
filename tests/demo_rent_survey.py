"""
Demodaten zum Berliner Mietspiegel 2026 zuordnen.

Der Mietspiegel "Berliner Mietspiegel" (Version 2026 mit Klassifizierungs-
merkmalen, 189 Tabellenfeldern und der Orientierungshilfe zur
Spanneneinordnung) ist Standarddatum des Moduls (rent_survey_berlin.xml,
erzeugt von tests/generate_rent_survey_xml.py aus
tests/mietspiegel_berlin_2026_felder.csv und ..._merkmale.csv) und wird beim
Aufbau der Datenbank angelegt - für alle Unternehmen.

Das Skript ordnet nur die Demodaten zu (setzt test_immo.py voraus):
Wirtschaftseinheit "Musterstraße 1-4" mit Wohnlage mittel; je Gebäude
Baujahr 1958 (falls leer), "Besonders ruhige Lage", Fahrradraum,
Wärmedämmung und Energieverbrauchskennwert 130 kWh/(m²a); "Wohnung 01" mit
Merkmalen der Gruppen 1-3 und eine Berechnung der Vergleichsmiete zum
heutigen Tag. Bereits vorhandene Zuordnungen werden übersprungen.

Verwendung:
    python tests/test_rent_survey.py --database <Datenbankname> [--config <trytond.conf>]
"""

import argparse
import datetime

from proteus import Model, config

SURVEY = 'Berliner Mietspiegel'
PROPERTY = 'Musterstraße 1-4'
VALID_FROM = datetime.date(2026, 5, 28)
START_DATE = datetime.date(2025, 1, 1)

DEMO_UNIT_FEATURES = ['b_wc_wall', 'b_towel', 'k_fitted', 'k_no_dishwasher',
    'w_balcony', 'w_windows']
DEMO_BUILDING_FEATURES = ['u_quiet', 'g_bike', 'g_insulation']


def connect(database, cfg_file):
    if cfg_file:
        return config.set_trytond(database=database, config_file=cfg_file)
    return config.set_trytond(database=database)


def energy_type():
    "Measurement type 'Energy Consumption Value' (sequence 70)"
    MeasurementType = Model.get('real_estate.measurement.type')
    types = MeasurementType.find([('sequence', '=', 70)], limit=1)
    if not types:
        raise SystemExit('Bemessungsart Energieverbrauchskennwert '
            '(Sequenz 70) fehlt - trytond-admin -u real_estate ausführen.')
    return types[0]


def assign(record, kind, codes, version):
    """Assign classes resp. features by code - via the selection fields
    (the code fields are read-only and not sent by proteus)"""
    Value = Model.get('real_estate.base_object.rent_survey_value')
    Class = Model.get('real_estate.rent_survey.dimension.class')
    Feature = Model.get('real_estate.rent_survey.feature')
    # assignments without code (e.g. from an aborted earlier run)
    broken = Value.find([('base_object', '=', record.id),
            ('class_code', '=', None), ('feature_code', '=', None)])
    if broken:
        Value.delete(broken)
    existing = {(v.dimension_code, v.class_code, v.feature_code)
        for v in Value.find([('base_object', '=', record.id)])}
    for code in codes:
        value = Value(base_object=record, kind=kind)
        if kind == 'feature':
            if (None, None, code) in existing:
                continue
            feature, = Feature.find([('code', '=', code),
                    ('group.version', '=', version.id)])
            value.survey_feature = Feature(feature.id)
        else:
            if (code[0], code[1], None) in existing:
                continue
            class_, = Class.find([('code', '=', code[1]),
                    ('dimension.code', '=', code[0]),
                    ('dimension.version', '=', version.id)])
            value.survey_class = Class(class_.id)
        value.save()


def demo(survey):
    BaseObject = Model.get('real_estate.base_object')
    version = survey.current_version
    if not version:
        print('  Keine heute gültige Version - keine Demodaten.')
        return
    props = BaseObject.find([('type', '=', 'property'),
            ('name', '=', PROPERTY)])
    if not props:
        print(f'  Property "{PROPERTY}" nicht gefunden - keine Demodaten '
            '(zuerst test_immo.py ausführen).')
        return
    prop, = props
    prop.rent_survey = survey
    prop.rent_survey_data = ('Wohnlage mittel laut Straßenverzeichnis '
        '(Beispiel)')
    prop.save()
    assign(prop, 'class', [('location', 'medium')], version)
    Measurement = Model.get('real_estate.measurement')
    energy = energy_type()
    buildings = BaseObject.find([('type', '=', 'building'),
            ('parent', 'child_of', [prop.id])])
    for building in buildings:
        if not building.year_of_construction:
            building.year_of_construction = '1958'
            building.save()
        assign(building, 'feature', DEMO_BUILDING_FEATURES, version)
        if not Measurement.find([('base_object', '=', building.id),
                    ('m_type', '=', energy.id)]):
            Measurement(base_object=building, m_type=energy,
                valid_from=START_DATE, value=130.0).save()
    print(f'  Demo: {prop.name} mit {len(buildings)} Gebäuden (Baujahr, '
        'Merkmale, Energieverbrauchskennwert 130 kWh/(m²a))')
    units = BaseObject.find([('type', '=', 'object'),
            ('parent', 'child_of', [prop.id]),
            ('name', 'like', 'Wohnung 01%')], limit=1)
    if not units:
        print('  "Wohnung 01" nicht gefunden - keine Berechnung.')
        return
    unit, = units
    assign(unit, 'feature', DEMO_UNIT_FEATURES, version)
    Calculation = Model.get('real_estate.rent_survey.calculation')
    calculation = Calculation(base_object=unit, company=unit.company,
        key_date=max(datetime.date.today(), VALID_FROM))
    calculation.save()
    calculation.click('calculate')
    calculation.reload()
    print(f'  Berechnung {unit.name}: Status {calculation.state}, '
        f'Prüfung {calculation.check_state}')
    print('    ' + '\n    '.join((calculation.protocol or '').splitlines()))
    if calculation.check_message:
        print('    ' + calculation.check_message)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--database', required=True)
    parser.add_argument('--config', default=None)
    args = parser.parse_args()
    connect(args.database, args.config)

    Survey = Model.get('real_estate.rent_survey')
    existing = Survey.find([('name', '=', SURVEY)])
    if not existing:
        raise SystemExit(f'Mietspiegel "{SURVEY}" nicht gefunden - er ist '
            'Standarddatum des Moduls (rent_survey_berlin.xml): '
            'trytond-admin -u real_estate ausführen.')
    demo(existing[0])


if __name__ == '__main__':
    main()
