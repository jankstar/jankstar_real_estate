"""
Berliner Mietspiegel 2026 anlegen (und als Demodaten zuordnen).

Legt den Mietspiegel "Berliner Mietspiegel" mit der Version "Berliner
Mietspiegel 2026" an (gültig ab 28.05.2026, Erhebungsstichtag 01.09.2025,
qualifiziert, Tabellenmethode, 20 % je Merkmalgruppe, Gruppen werden
gegeneinander aufgerechnet):

  - Klassifizierungsmerkmale Wohnlage (einfach/mittel/gut, manuell laut
    Straßenverzeichnis, Ebene Wirtschaftseinheit) und Baualter (aus dem
    Baujahr des Gebäudes; 1973-1985 West, 1986-1990 West und 1973-1990
    Ost nur manuell, da abhängig vom Bezirk)
  - alle 189 Tabellenfelder der drei Mietspiegeltabellen 9.1-9.3 aus
    tests/mietspiegel_berlin_2026_felder.csv
  - die Orientierungshilfe für die Spanneneinordnung (Nr. 11) mit den
    Merkmalgruppen 1-5 sowie dem Abschlag für Minderausstattung (Nr. 9.4)
    aus tests/mietspiegel_berlin_2026_merkmale.csv

Beide CSV-Dateien wurden aus den amtlichen PDF-Dokumenten (Berliner
Mietspiegel 2026, Berliner Mietspiegeltabelle 2026) übernommen und sind vor
produktiver Nutzung am Original zu prüfen.

Ohne --only-survey werden zusätzlich Demodaten zugeordnet (setzt
test_immo.py voraus): Wirtschaftseinheit "Musterstraße 1-4" mit Wohnlage
mittel; je Gebäude Baujahr 1958 (falls leer), "Besonders ruhige Lage",
Fahrradraum, Wärmedämmung und Energieverbrauchskennwert 130 kWh/(m²a);
"Wohnung 01" mit Merkmalen der Gruppen 1-3 und eine Berechnung der
Vergleichsmiete zum heutigen Tag.

Das Skript ist idempotent: es bricht ab, wenn der Mietspiegel "Berliner
Mietspiegel" bereits existiert.

Verwendung:
    python tests/test_rent_survey.py --database <Datenbankname> [--config <trytond.conf>] [--only-survey | --demo-only] [--company <Name>]
"""

import argparse
import datetime
import os
from decimal import Decimal

from proteus import Model, Wizard, config

SURVEY = 'Berliner Mietspiegel'
PROPERTY = 'Musterstraße 1-4'
VALID_FROM = datetime.date(2026, 5, 28)
START_DATE = datetime.date(2025, 1, 1)
HERE = os.path.dirname(os.path.abspath(__file__))
CELLS_FILE = os.path.join(HERE, 'mietspiegel_berlin_2026_felder.csv')
FEATURES_FILE = os.path.join(HERE, 'mietspiegel_berlin_2026_merkmale.csv')

LOCATIONS = [('simple', 'einfach'), ('medium', 'mittel'), ('good', 'gut')]
# code, name, from year, to year (excl.), manual only
AGES = [
    ('to_1918', 'bis 1918', None, 1919, False),
    ('1919_1949', '1919 bis 1949', 1919, 1950, False),
    ('1950_1964', '1950 bis 1964', 1950, 1965, False),
    ('1965_1972', '1965 bis 1972', 1965, 1973, False),
    ('1973_1985_w', '1973 bis 1985 West', None, None, True),
    ('1986_1990_w', '1986 bis 1990 West', None, None, True),
    ('1973_1990_o', '1973 bis 1990 Ost (mit Wendewohnungen)', None, None,
        True),
    ('1991_2001', '1991 bis 2001 (ohne Wendewohnungen)', 1991, 2002, False),
    ('2002_2009', '2002 bis 2009', 2002, 2010, False),
    ('2010_2015', '2010 bis 2015', 2010, 2016, False),
    ('2016_2019', '2016 bis 2019', 2016, 2020, False),
    ('2020_2024', '2020 bis 2024', 2020, 2025, False),
    ]
GROUPS = [('1', 'Bad/WC/Gäste-WC'), ('2', 'Küche'), ('3', 'Wohnung'),
    ('4', 'Gebäude'), ('5', 'Wohnumfeld'),
    ('S', 'Abschlag Minderausstattung (Nr. 9.4)')]
RENT_DEFINITION = (
    'Nettokaltmiete je m² Wohnfläche und Monat: ohne Kosten für '
    'Sammelheizung und Warmwasserversorgung, ohne kalte Betriebskosten, '
    'ohne Möblierungs- und Untermietzuschläge, ohne Zuschläge für die '
    'Nutzung zu anderen als Wohnzwecken. Gilt für nicht preisgebundene '
    'Wohnungen in Mehrfamilienhäusern (mind. 3 Wohnungen), bezugsfertig bis '
    '31.12.2024, mit Sammelheizung, Bad und WC in der Wohnung; nicht für '
    'selbstgenutztes Wohneigentum, Ein-/Zweifamilien- und Reihenhäuser, '
    'Wohnungen mit WC außerhalb der Wohnung und preisgebundene Wohnungen. '
    'Wohnlage laut Straßenverzeichnis (Amtsblatt vom 28.05.2026). Die '
    'Orientierungshilfe (Nr. 11) und der Abschlag für Minderausstattung '
    '(Nr. 9.4) gehören nicht zum qualifizierten Teil.')

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


def run_import(version, kind, path):
    with open(path, encoding='utf-8') as file:
        content = file.read()
    wizard = Wizard('real_estate.rent_survey.import', [version])
    wizard.form.kind = kind
    wizard.form.file_ = content.encode('utf-8')
    wizard.form.replace = False
    wizard.execute('preview')
    if wizard.form.problems:
        raise SystemExit(f'Import {kind}:\n{wizard.form.problems}')
    print(f'  Import {os.path.basename(path)}: '
        f'{wizard.form.preview.splitlines()[0]}')
    wizard.execute('import_')


def create_survey(company):
    Survey = Model.get('real_estate.rent_survey')
    Version = Model.get('real_estate.rent_survey.version')
    Dimension = Model.get('real_estate.rent_survey.dimension')
    Class = Model.get('real_estate.rent_survey.dimension.class')
    Group = Model.get('real_estate.rent_survey.group')
    survey = Survey(name=SURVEY, municipality='Berlin', company=company)
    survey.save()
    version = Version(survey=survey, name='Berliner Mietspiegel 2026',
        valid_from=VALID_FROM, survey_date=datetime.date(2025, 9, 1),
        kind='qualified', method='table', group_percent=Decimal(20),
        group_netting=True, round_digits=2,
        rent_definition=RENT_DEFINITION,
        source_document='https://www.mietspiegel.berlin.de - Berliner '
        'Mietspiegel 2026 (Stand 05/2026), Berliner Mietspiegeltabelle 2026')
    version.save()
    # parent first, children saved separately (proteus O2M pattern)
    location = Dimension(version=version, code='location', name='Wohnlage',
        level='property', source='manual', sequence=10)
    location.save()
    for sequence, (code, name) in enumerate(LOCATIONS, 1):
        Class(dimension=location, code=code, name=name,
            sequence=sequence).save()
    age = Dimension(version=version, code='age', name='Bezugsfertigkeit',
        level='building', source='year_of_construction', sequence=20)
    age.save()
    for sequence, (code, name, low, high, manual) in enumerate(AGES, 1):
        Class(dimension=age, code=code, name=name, sequence=sequence,
            value_min=Decimal(low) if low else None,
            value_max=Decimal(high) if high else None,
            manual_only=manual).save()
    version.reload()
    run_import(version, 'cells', CELLS_FILE)
    run_import(version, 'features', FEATURES_FILE)
    for sequence, (code, name) in enumerate(GROUPS, 1):
        group, = Group.find([('version', '=', version.id),
                ('code', '=', code)])
        group.name = name
        group.sequence = sequence
        group.save()
    version.click('check')
    version.reload()
    print(f'  Version "{version.name}": {len(version.cells)} Tabellenfelder, '
        f'{sum(len(g.features) for g in version.groups)} Merkmale in '
        f'{len(version.groups)} Gruppen')
    print('  Prüfung: ' + ' / '.join(version.check_result.splitlines()))
    return survey


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
    parser.add_argument('--only-survey', action='store_true',
        help='Nur den Mietspiegel anlegen, keine Demodaten zuordnen')
    parser.add_argument('--demo-only', action='store_true',
        help='Nur die Demodaten dem vorhandenen Mietspiegel zuordnen')
    parser.add_argument('--company', default=None,
        help='Name des Unternehmens (Default: das erste)')
    args = parser.parse_args()
    connect(args.database, args.config)

    Survey = Model.get('real_estate.rent_survey')
    existing = Survey.find([('name', '=', SURVEY)])
    if args.demo_only:
        if not existing:
            raise SystemExit(f'Mietspiegel "{SURVEY}" nicht gefunden.')
        demo(existing[0])
        return
    if existing:
        print(f'Mietspiegel "{SURVEY}" existiert bereits. Abbruch '
            '(Demodaten zuordnen mit --demo-only).')
        return
    Company = Model.get('company.company')
    companies = Company.find([('party.name', '=', args.company)]
        if args.company else [])
    if not companies:
        raise SystemExit('Kein Unternehmen gefunden.')
    print(f'Mietspiegel "{SURVEY}" ({companies[0].rec_name})')
    survey = create_survey(companies[0])
    if not args.only_survey:
        demo(survey)


if __name__ == '__main__':
    main()
