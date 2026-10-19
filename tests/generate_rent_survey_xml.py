"""
Erzeugt rent_survey_berlin.xml (Standarddaten "Berliner Mietspiegel 2026")
aus den Tabellenfeldern und Merkmalen der CSV-Dateien.

Baut den Mietspiegel in einer temporären SQLite-Testdatenbank auf (Version
2026, Klassifizierungsmerkmale Wohnlage und Bezugsfertigkeit, Import der
189 Tabellenfelder aus tests/mietspiegel_berlin_2026_felder.csv und der 86
Merkmale der Orientierungshilfe aus tests/mietspiegel_berlin_2026_merkmale.csv,
Prüfung) und schreibt alle Datensätze als XML-Records mit noupdate="1" in
rent_survey_berlin.xml im Modulverzeichnis. Beim Aufbau einer neuen
Datenbank legt trytond-admin den Mietspiegel damit gleich an (für alle
Unternehmen); spätere Änderungen in der Oberfläche bleiben bei einem
Modul-Update erhalten.

Nach einer Änderung der CSV-Dateien oder der Konstanten unten erneut
ausführen:

    TRYTOND_DATABASE_URI=sqlite:// DB_NAME=:memory: \\
        python tests/generate_rent_survey_xml.py

Die CSV-Dateien wurden aus den amtlichen PDF-Dokumenten (Berliner
Mietspiegel 2026, Berliner Mietspiegeltabelle 2026) übernommen und sind vor
produktiver Nutzung am Original zu prüfen.
"""
import datetime
import os
from decimal import Decimal
from xml.sax.saxutils import escape, quoteattr

os.environ.setdefault('TRYTOND_DATABASE_URI', 'sqlite://')
os.environ.setdefault('DB_NAME', ':memory:')

from trytond.tests.test_tryton import (  # noqa: E402
    activate_module, with_transaction)
from trytond.pool import Pool  # noqa: E402
from trytond.transaction import Transaction  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUTPUT = os.path.join(os.path.dirname(HERE), 'rent_survey_berlin.xml')
CELLS_FILE = os.path.join(HERE, 'mietspiegel_berlin_2026_felder.csv')
FEATURES_FILE = os.path.join(HERE, 'mietspiegel_berlin_2026_merkmale.csv')
PREFIX = 'rent_survey_berlin'

SURVEY = 'Berliner Mietspiegel'
VALID_FROM = datetime.date(2026, 5, 28)
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
SOURCE_DOCUMENT = ('https://www.mietspiegel.berlin.de - Berliner '
    'Mietspiegel 2026 (Stand 05/2026), Berliner Mietspiegeltabelle 2026')

# Models in loading order with the xml id suffix of a record
MODELS = [
    ('real_estate.rent_survey', lambda r: ''),
    ('real_estate.rent_survey.version', lambda r: '_2026'),
    ('real_estate.rent_survey.version-measurement.type',
        lambda r: f'_2026_mtype_{r.measurement_type.sequence}'),
    ('real_estate.rent_survey.dimension', lambda r: f'_dim_{r.code}'),
    ('real_estate.rent_survey.dimension.class',
        lambda r: f'_class_{r.dimension.code}_{r.code}'),
    ('real_estate.rent_survey.group', lambda r: f'_group_{r.code}'),
    ('real_estate.rent_survey.feature', lambda r: f'_feature_{r.code}'),
    ('real_estate.rent_survey.feature-class',
        lambda r: f'_feature_{r.feature.code}_class_'
        f'{r.class_.dimension.code}_{r.class_.code}'),
    ('real_estate.rent_survey.feature-feature',
        lambda r: f'_feature_{r.feature.code}_excl_{r.other.code}'),
    ('real_estate.rent_survey.cell', lambda r: f'_cell_{r.code}'),
    ('real_estate.rent_survey.cell-class',
        lambda r: f'_cell_{r.cell.code}_class_'
        f'{r.class_.dimension.code}_{r.class_.code}'),
    ]
# Stored fields not written (dated check text, audit fields)
SKIP_FIELDS = {'id', 'create_uid', 'create_date', 'write_uid', 'write_date',
    'check_result'}


def build():
    "Create the rent survey like a user (classes, CSV import, check)"
    pool = Pool()
    Survey = pool.get('real_estate.rent_survey')
    Version = pool.get('real_estate.rent_survey.version')
    Dimension = pool.get('real_estate.rent_survey.dimension')
    Group = pool.get('real_estate.rent_survey.group')
    Import = pool.get('real_estate.rent_survey.import', type='wizard')
    # the records of an existing rent_survey_berlin.xml
    Survey.delete(Survey.search([('name', '=', SURVEY)]))
    survey, = Survey.create([{'name': SURVEY, 'municipality': 'Berlin'}])
    version, = Version.create([{'survey': survey.id,
                'name': 'Berliner Mietspiegel 2026',
                'valid_from': VALID_FROM,
                'survey_date': datetime.date(2025, 9, 1),
                'kind': 'qualified', 'method': 'table',
                'group_percent': Decimal(20), 'group_netting': True,
                'round_digits': 2, 'rent_definition': RENT_DEFINITION,
                'source_document': SOURCE_DOCUMENT}])
    Dimension.create([{'version': version.id, 'code': 'location',
                'name': 'Wohnlage', 'level': 'property',
                'source': 'manual', 'sequence': 10,
                'classes': [('create', [
                            {'code': code, 'name': name, 'sequence': i}
                            for i, (code, name) in enumerate(LOCATIONS, 1)])],
                }, {'version': version.id, 'code': 'age',
                'name': 'Bezugsfertigkeit', 'level': 'building',
                'source': 'year_of_construction', 'sequence': 20,
                'classes': [('create', [{
                                'code': code, 'name': name, 'sequence': i,
                                'value_min': Decimal(low) if low else None,
                                'value_max': Decimal(high) if high else None,
                                'manual_only': manual}
                            for i, (code, name, low, high, manual)
                            in enumerate(AGES, 1)])],
                }])
    for kind, path in [('cells', CELLS_FILE), ('features', FEATURES_FILE)]:
        with open(path, encoding='utf-8') as file:
            content = file.read()
        session_id, _, _ = Import.create()
        with Transaction().set_context(active_model=Version.__name__,
                active_id=version.id, active_ids=[version.id]):
            data = {'start': {'kind': kind, 'replace': False,
                    'file_': content.encode('utf-8')}}
            preview = Import.execute(session_id, data, 'preview')
            problems = preview['view']['defaults'].get('problems')
            if problems:
                raise SystemExit(f'Import {kind}:\n{problems}')
            Import.execute(session_id, data, 'import_')
        Import.delete(session_id)
    for sequence, (code, name) in enumerate(GROUPS, 1):
        group, = Group.search([('version', '=', version.id),
                ('code', '=', code)])
        Group.write([group], {'name': name, 'sequence': sequence})
    Version.check([version])
    version = Version(version.id)
    print(f'Version "{version.name}": {len(version.cells)} Tabellenfelder, '
        f'{sum(len(g.features) for g in version.groups)} Merkmale in '
        f'{len(version.groups)} Gruppen')
    print('Prüfung: ' + ' / '.join(version.check_result.splitlines()))
    return survey


def records_of(survey):
    "Records of the rent survey per model in loading order"
    pool = Pool()
    Version = pool.get('real_estate.rent_survey.version')
    version_ids = [v.id for v in survey.versions]
    domains = {
        'real_estate.rent_survey': [('id', '=', survey.id)],
        'real_estate.rent_survey.version': [('survey', '=', survey.id)],
        # the version gets its default measurement types on creation
        'real_estate.rent_survey.version-measurement.type': [
            ('version', 'in', version_ids),
            ('measurement_type', 'not in',
                Version.default_measurement_types()),
            ],
        'real_estate.rent_survey.dimension': [
            ('version', 'in', version_ids)],
        'real_estate.rent_survey.dimension.class': [
            ('dimension.version', 'in', version_ids)],
        'real_estate.rent_survey.group': [('version', 'in', version_ids)],
        'real_estate.rent_survey.feature': [
            ('group.version', 'in', version_ids)],
        'real_estate.rent_survey.feature-class': [
            ('feature.group.version', 'in', version_ids)],
        'real_estate.rent_survey.feature-feature': [
            ('feature.group.version', 'in', version_ids)],
        'real_estate.rent_survey.cell': [('version', 'in', version_ids)],
        'real_estate.rent_survey.cell-class': [
            ('cell.version', 'in', version_ids)],
        }
    for model, suffix in MODELS:
        Model = pool.get(model)
        yield model, suffix, Model.search(domains[model],
            order=[('id', 'ASC')])


def xml_value(field, value, xml_ids, module_ids):
    "XML field element for the value - None to skip it"
    if value is None or value == '':
        return None
    name = field.name
    if field._type == 'many2one':
        key = (value.__name__, value.id)
        if key in xml_ids:
            return f'<field name="{name}" ref="{xml_ids[key]}"/>'
        if key in module_ids:
            return f'<field name="{name}" ref="{module_ids[key]}"/>'
        raise SystemExit(f'No xml id for {key} ({field.model_name})')
    if isinstance(value, bool):
        return f'<field name="{name}" eval="{value}"/>'
    if isinstance(value, Decimal):
        return f'<field name="{name}" eval="Decimal(\'{value}\')"/>'
    if isinstance(value, (int, float)):
        return f'<field name="{name}" eval="{value!r}"/>'
    if isinstance(value, datetime.date):
        return (f'<field name="{name}" eval="datetime.date('
            f'{value.year}, {value.month}, {value.day})"/>')
    if isinstance(value, (list, tuple)):
        return f'<field name="{name}" eval={quoteattr(repr(list(value)))}/>'
    return f'<field name="{name}">{escape(str(value))}</field>'


@with_transaction()
def main():
    from trytond.model import fields
    pool = Pool()
    ModelData = pool.get('ir.model.data')
    survey = build()
    module_ids = {(d.model, d.db_id): d.fs_id for d in ModelData.search([
                ('module', '=', 'real_estate'),
                ('fs_id', 'not like', f'{PREFIX}%'),
                ])}
    xml_ids = {}
    out = ['<?xml version="1.0"?>',
        '<!-- Generated by tests/generate_rent_survey_xml.py from',
        '     tests/mietspiegel_berlin_2026_felder.csv and',
        '     tests/mietspiegel_berlin_2026_merkmale.csv - do not edit by',
        '     hand, change the CSV files resp. the generator and run it',
        '     again. Berliner Mietspiegel 2026 for all companies, loaded once',
        '     (noupdate): changes in the client are kept on module updates.',
        '     Values taken from the official PDF documents, to be checked',
        '     against the original before productive use. -->',
        '<tryton>', '    <data noupdate="1">']
    count = 0
    for model, suffix, records in records_of(survey):
        Model = pool.get(model)
        stored = [f for n, f in Model._fields.items()
            if n not in SKIP_FIELDS
            and not isinstance(f, (fields.Function, fields.One2Many,
                    fields.Many2Many))]
        for record in records:
            xml_id = PREFIX + suffix(record)
            if xml_id in xml_ids.values():
                raise SystemExit(f'Duplicate xml id {xml_id}')
            xml_ids[(model, record.id)] = xml_id
            out.append(f'        <record model="{model}" id="{xml_id}">')
            for field in sorted(stored, key=lambda f: f.name):
                line = xml_value(field, getattr(record, field.name),
                    xml_ids, module_ids)
                if line:
                    out.append('            ' + line)
            out.append('        </record>')
            count += 1
    out += ['    </data>', '</tryton>', '']
    with open(OUTPUT, 'w', encoding='utf-8') as file:
        file.write('\n'.join(out))
    print(f'{count} Datensätze → {OUTPUT}')


if __name__ == '__main__':
    activate_module('real_estate')
    main()
