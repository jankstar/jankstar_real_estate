"""
Demodaten für das Tryton-Modul real_estate erzeugen.

Startjahr: Parameter --year (Vorgabe: aktuelles Jahr - 1). Alle Daten
werden relativ zum Startjahr gebildet ("01.01." = 01.01. des Startjahres).

Das Skript legt folgende Objekte an:

  Wirtschaftseinheit 1: "Musterstraße 1-4"
  Wirtschaftseinheit 2: "Musterstraße 5-8"

  Je Wirtschaftseinheit:
  - 4 Gebäude (Building), je mit einer Bemessung:
      Bruttogeschossfläche 3.500 m² ab 01.01. des Startjahres
  - Je Gebäude 1 Gewerbefläche (Rental Object, Type of Use: commercial, Use: retail):
      - Einzelhandel XX (EG): Erdgeschoss (floor=0), Sequenz 5
      - Bemessung: Gewerbefläche 140 m²
      - 1 Zähler (Equipment, e_type: meters, Anlagenart: Zähler (Kaltwasser),
        Code cold_water_meter, Einheit: m³, Faktor: 1, Is Counter: ja):
          - Initialablesung 0 m³ zum 01.01. des Startjahres
          - Ablesung zum 30.04. des Startjahres mit zufälligem Verbrauch zwischen 20 und 40 m³
  - Je Gebäude 4 Wohnungen (Rental Object, Type of Use: residential, Use: apartment):
      - Wohnung XX (1.OG links):  2 Räume, 57 m² Wohnfläche, 54 m² Heizfläche
      - Wohnung XX (1.OG rechts): 3 Räume, 83 m² Wohnfläche, 80 m² Heizfläche
      - Wohnung XX (2.OG links):  2 Räume, 57 m² Wohnfläche, 54 m² Heizfläche
      - Wohnung XX (2.OG rechts): 3 Räume, 83 m² Wohnfläche, 80 m² Heizfläche
      - Heizfläche = Wohnfläche - 3 m² (die Wohnfläche zählt den 6 m² großen,
        unbeheizten Balkon zur Hälfte, also 3 m², mit)
      - 1 Zähler (Equipment, e_type: meters, Anlagenart: Zähler (Kaltwasser),
        Code cold_water_meter, Einheit: m³, Faktor: 1, Is Counter: ja):
          - Initialablesung 0 m³ zum 01.01. des Startjahres
          - Ablesung zum 30.04. des Startjahres mit zufälligem Verbrauch zwischen 20 und 40 m³
  - Kellernummer der Wohnungen: "K" + Wohnungsnummer (K01–K16).
  - Je Gebäude 1 Hausstrom-Zähler "Hausstrom Zähler <Hausnr.>" am Gebäude
    (Equipment, e_type: meters, Einheit kWh, Anlagenart Zähler (Strom),
    Code electricity_meter, über die XML-ID), Initialablesung 0 kWh zum 01.01.
    und Ablesung zum 30.04. des Startjahres (1.500-3.000 kWh), mit
      - MeLo-ID (33 Zeichen): "DE" + 6 Ziffern Netzbetreiber (fiktiv 000123)
        + 5 Ziffern Postleitzahl (14163) + 20 Ziffern Zählpunktnummer
        (fortlaufend),
      - MaLo-ID (11 Ziffern): "5" + 9 Ziffern fortlaufend + Prüfziffer nach
        BDEW (Ziffern an ungeraden Stellen + 2 x Ziffern an geraden Stellen
        der Stellen 1-10, Prüfziffer = Abstand zum nächsten Vielfachen von
        10); Selbsttest mit Beispielen der BDEW beim Start.
    Die Wasserzähler bleiben ohne MeLo-/MaLo-ID.
  - Eichung an allen Zählern: Gültigkeit 5 Jahre, "Eichfrist bis" nach dem
    Vorschlag des Moduls (31.12. von Eichjahr + 5); Datum der letzten
    Eichung gestaffelt 1-3 Jahre vor heute; die ersten beiden Zähler
    (Hausstrom Zähler 1, Wasser Zähler EH01) mit Eichung vor 5 Jahren, so
    dass die Eichfrist in den nächsten 3 Monaten endet (Aufgabenregel O03;
    liegt kein 31.12. in diesem Zeitraum, Eichfrist = heute + 2 Monate).
    Die Rauchwarnmelder sind keine Zähler und haben keine Eichung.
  - Die Wohnungsnummern zählen je Wirtschaftseinheit durch (01–16).
  - Die Einzelhandelsnummern zählen je Wirtschaftseinheit durch (01–04).
  - Die Zähler-ID wird automatisch generiert (Format: Z-<Startjahr>-<Nr>, Beispiel für das Startjahr 2025: Z-2025-0001).
  - 1 Grundstück (Land) direkt unter der Wirtschaftseinheit mit 4 Stellplätzen
      (Type of Use: residential, Use: parking), Stellplatznummern 01–04.

  Prüfungen (Rauchwarnmelder, Prüfpläne):
  - Je Wohnung 1 Anlage "Rauchwarnmelder WE XX" (Equipment, Anlagenart
    Rauchwarnmelder) mit Bemessung "Anzahl" = Anzahl der Räume (2 bzw. 3)
    ab 01.01. des Startjahres.
  - Je Gebäude 2 Prüfpläne: "Jährliche Objektbegehung" (fällig 01.04. des
    Folgejahres) und "Rauchwarnmelderprüfung" (fällig 15.05. des
    Folgejahres, Wartung durch
    Eigentümer) - sofern die Standard-Prüfarten (Codes "walkthrough",
    "smoke_detector") vorhanden sind. Verantwortlicher: der Benutzer des
    Mitarbeiters "Verwalter 1" (verwalter_1), admin nur als Rückfall; Auftragnehmer: Lieferant
    "B&O GmbH" aus demo_kreditor.py (fehlt er, nur ein Hinweis);
    zuletzt erledigt: ein Intervall vor der ersten Fälligkeit (Feld im
    Client schreibgeschützt, direkt geschrieben).

  Wirtschaftseinheiten: angespannter Wohnungsmarkt und Kappung 15 %
  (Landesverordnung Berlin) ab 01.01. des Startjahres, ohne Ende.

  Optionssätze (am Ende, nach beiden Wirtschaftseinheiten):
  - Einmal die Optionssatzermittlung (Assistent "Optionssätze aktualisieren",
    real_estate.option_rate_update.wizard) für beide Wirtschaftseinheiten mit
    Stichtag 01.01. des Startjahres (Beginn), gültig ab diesem Tag: Wirtschaftseinheit
    und Gebäude dynamisch nach Nutzfläche, Grundstück fest 0 %, Mietobjekte
    fest (Wohnung/Stellplatz 0 %, Gewerbe 100 %).

  Vorab (vor den Wirtschaftseinheiten):
  - 2 Partner mit je einem Mitarbeiter der Company (ab 01.01. des Startjahres):
    "Verwalter 1" und "Hausmeister 1" (vorhandene gleichnamige Partner bzw.
    Mitarbeiter werden wiederverwendet), mit der Partei-Rolle
    'Mitarbeiter' (real_estate.party.role_number, Nummer 20000,
    Standarddaten core/party.xml; fehlt sie, nur eine Warnung).
  - Beide werden jeder Wirtschaftseinheit als Partner zum Objekt zugeordnet
    (Rolle Verwalter bzw. Hausmeister, gültig ab 01.01. des Startjahres) - Grundlage der
    Zuständigkeit von Aufgaben über die Partnerrolle.
  - Direkt danach die Benutzer (ohne Passwort, Gesellschaft und erlaubte
    Gesellschaften = Company, Sprache Deutsch, Gruppen über die XML-ID):
      - verwalter_1 "Verwalter 1", Mitarbeiter Verwalter 1, Gruppen Real
        Estate Administration, Real Estate Object, Accounting, Party
        Administration;
      - hausmeister_1 "Hausmeister 1", Mitarbeiter Hausmeister 1, Gruppen
        Real Estate View, Real Estate Object.
    Ein vorhandener Benutzer mit gleichem Login wird nicht geändert (fehlt
    ihm der Mitarbeiter, nur ein Hinweis). Am Ende ein Hinweis: Passwort von
    Hand setzen.

Das Skript ist idempotent: es bricht ab, wenn eine Property mit dem Namen
"Musterstraße 1-4" oder "Musterstraße 5-8" in der Zieldatenbank bereits vorhanden ist.

Exit-Codes: 0 = ausgeführt, 1 = Fehler, 2 = falscher Aufruf (argparse),
3 = Daten vorhanden, nichts angelegt (EXIT_EXISTS; demo_run.py zeigt den
Schritt als "übersprungen").

Nutzungsklassen (real_estate.use_class) werden per Sequenznummer gesucht
(sprachunabhängig): Apartment=10, Retail=30, Parking=50.

Anlagenart (real_estate.equipment.kind) und Prüfarten
(real_estate.inspection.type) werden per Code gesucht, die Bemessung
"Anzahl" (Number of items) per Sequenznummer 50.

Partnerrollen (real_estate.object_party.role) werden per Sequenznummer
gesucht (sprachunabhängig): Hausmeister=10, Verwalter=20.

Bemessungstypen (real_estate.measurement.type) werden per Sequenznummer
gesucht (sprachunabhängig): Usable Space=5, Wohnfläche=10, Gewerbefläche=15,
Anzahl Räume=20, Heizfläche=25, Bruttogeschossfläche [BHF]=30.

Verwendung:
    python tests/demo_immo.py --database <Datenbankname> [--config <trytond.conf>] [--year <Startjahr>]
"""

import argparse
import datetime
import random
import sys
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from proteus import Model, Wizard, config

# Exit code "data exist, nothing created" (demo_run.py shows the step as
# skipped); 0 = done, 1 = error, 2 = wrong call (argparse)
EXIT_EXISTS = 3

# Users of the demo employees (Q9 A3): login, name of the employee party and
# groups by XML-ID; created without password (set by hand)
STAFF_USERS = [
    ('verwalter_1', 'Verwalter 1', [
        'real_estate.group_real_estate_admin',
        'real_estate.group_real_estate_object',
        'account.group_account',
        'party.group_party_admin',
        ]),
    ('hausmeister_1', 'Hausmeister 1', [
        'real_estate.group_real_estate_view',
        'real_estate.group_real_estate_object',
        ]),
    ]

# Start year of the demo data (--year, default: current year - 1); set from
# the parameter in main() via set_start_year()
START_YEAR = datetime.date.today().year - 1
START_DATE = datetime.date(START_YEAR, 1, 1)


def set_start_year(year: int) -> None:
    """Dates of the demo data relative to the start year."""
    global START_YEAR, START_DATE
    START_YEAR = year
    START_DATE = datetime.date(year, 1, 1)

# Party role 'Employees' (core/party.xml) - looked up by number
EMPLOYEE_ROLE_NUMBER = 20000

# Globaler Zähler für eindeutige Meter-IDs innerhalb dieses Script-Laufs
_meter_id_counter = 0


def next_meter_id() -> str:
    global _meter_id_counter
    _meter_id_counter += 1
    return f'Z-{START_DATE.year}-{_meter_id_counter:04d}'


# Calibration (Eichung): validity 5 years; the module proposes "valid to"
# = 31.12. of the calibration year + validity (on_change)
CALIBRATION_YEARS = 5
_meter_counter = 0
# Electricity meters (Hausstrom): fictitious grid operator and postal code
# of the MeLo-ID
MELO_OPERATOR = '000123'
MELO_POSTAL_CODE = '14163'
_electricity_counter = 0
# Contractor of the inspection plans (demo_kreditor.py)
INSPECTION_CONTRACTOR = 'B&O GmbH'


def malo_check_digit(digits10: str) -> str:
    """Check digit of the MaLo-ID (BDEW): sum of the digits at odd
    positions + 2 x sum of the digits at even positions (positions 1-10);
    check digit = difference to the next multiple of 10 (0 if already a
    multiple)."""
    odd = sum(int(c) for c in digits10[0::2])
    even = sum(int(c) for c in digits10[1::2])
    return str((10 - (odd + 2 * even) % 10) % 10)


def malo_id(number: int) -> str:
    """MaLo-ID: 11 digits, first digit 1-9, 11th digit check digit."""
    base = f'5{number:09d}'
    return base + malo_check_digit(base)


def melo_id(number: int) -> str:
    """MeLo-ID (Zählpunktbezeichnung): 33 characters - 'DE', 6 digits grid
    operator, 5 digits postal code, 20 characters metering point number."""
    return f'DE{MELO_OPERATOR}{MELO_POSTAL_CODE}{number:020d}'


def _self_test_ids() -> None:
    # known valid MaLo-IDs of the BDEW examples
    assert malo_check_digit('4137355924') == '1'
    assert malo_check_digit('5123869678') == '1'
    for n in (1, 2, 99):
        value = malo_id(n)
        assert len(value) == 11 and value.isdigit() and value[0] != '0'
        assert value[-1] == malo_check_digit(value[:10])
        assert len(melo_id(n)) == 33 and melo_id(n).startswith('DE')


# the first meters created get a calibration that is due (rule O03)
DUE_METERS = 2


def calibration_values():
    """(date of the last calibration, valid to or None for the module's
    proposal). Staggered over the last 1-3 years, relative to today
    (rule O03 looks 3 months ahead of today); a due meter gets a
    calibration 5 years ago so that the validity ends within the next 3
    months - if no 31.12. lies in this window, 'valid to' is set to today
    + 2 months (may be overwritten, spezifikation-wiedervorlage.md 3.7)."""
    global _meter_counter
    _meter_counter += 1
    today = datetime.date.today()
    if _meter_counter <= DUE_METERS:
        year_end = datetime.date(today.year, 12, 31)
        date = datetime.date(today.year - CALIBRATION_YEARS, 6, 15)
        if today < year_end <= today + relativedelta(months=3):
            return date, None
        return date, today + relativedelta(months=2)
    years_back = 1 + _meter_counter % 3
    month = 1 + _meter_counter % 12
    return datetime.date(today.year - years_back, month, 15), None


def connect(database: str, cfg_file: str | None) -> None:
    if cfg_file:
        config.set_trytond(database=database, config_file=cfg_file)
    else:
        config.set_trytond(database=database)


def get_company():
    Company = Model.get('company.company')
    companies = Company.find([])
    if not companies:
        print('ERROR: Keine Company in der Datenbank gefunden.', file=sys.stderr)
        sys.exit(1)
    if len(companies) > 1:
        print('Mehrere Companies gefunden, verwende die erste:', companies[0].rec_name)
    return companies[0]


def get_measurement_type_by_sequence(sequence: int):
    # Per sequence gesucht (sprachunabhängig) - eine Namenssuche würde im
    # deutschen Sprachkontext des admin-Benutzers fehlschlagen, sobald für
    # einen Bemessungstyp keine deutsche Übersetzung hinterlegt ist.
    MeasurementType = Model.get('real_estate.measurement.type')
    results = MeasurementType.find([('sequence', '=', sequence)])
    if not results:
        print(f'ERROR: Bemessungstyp mit sequence={sequence} nicht gefunden.',
              file=sys.stderr)
        sys.exit(1)
    return results[0]


def create_base_object(
    name: str,
    obj_type: str,
    company,
    sequence: int,
    parent=None,
    type_of_use: str | None = None,
    use_class=None,
    floor: int | None = None,
    usable_space_type=None,
) -> object:
    BaseObject = Model.get('real_estate.base_object')
    obj = BaseObject()
    obj.name = name
    obj.type = obj_type
    obj.company = company
    obj.start_date = START_DATE
    obj.state = 'approved'
    obj.sequence = sequence
    if parent is not None:
        obj.parent = parent
    if type_of_use is not None:
        obj.type_of_use = type_of_use
    if use_class is not None:
        obj.use_class = use_class
    if floor is not None:
        obj.floor = floor

    if obj_type == 'building':
        obj.year_of_construction = '1920'
        obj.number_of_floors = 2

    # Option Rate (Optionssatz Vorsteuerabzug)
    if obj_type in ('property', 'building'):
        obj.option_rate_method = 'dynamic_measurement'
        if usable_space_type is not None:
            obj.option_measurement_type = usable_space_type
    elif obj_type == 'land':
        # land with parking spaces: no usable space, fixed 0 %
        obj.option_rate_method = 'fix_0'
    elif obj_type == 'object':
        obj.option_rate_method = (
            'fix_100' if type_of_use == 'commercial' else 'fix_0')

    if obj_type == 'property':
        # Berlin: tight housing market and reduced cap 15 % from the start
        # year on, without end (state regulations)
        obj.tight_market = True
        obj.tight_market_valid_from = START_DATE
        obj.reduced_cap = True
        obj.reduced_cap_valid_from = START_DATE

    obj.save()
    print(f'  Erstellt: [{obj_type:10}] {name} (id={obj.id})')
    return obj


def update_option_rates(company, properties, cutoff_date) -> None:
    """Run the wizard 'Update Option Rates' once for the given properties
    (with their buildings, land and rental objects) as of cutoff_date - as a
    user would in the client; the new rates are valid from the first day of
    the month of cutoff_date."""
    BaseObject = Model.get('real_estate.base_object')
    wizard = Wizard('real_estate.option_rate_update.wizard')
    wizard.form.company = company
    wizard.form.cutoff_date = cutoff_date
    for prop in properties:
        # fresh instance per Many2Many entry (proteus _group issue)
        wizard.form.base_objects.append(BaseObject(prop.id))
    wizard.execute('confirm')
    print(f'  Stichtag {cutoff_date:%d.%m.%Y}, gültig ab '
          f'{wizard.form.effective_date:%d.%m.%Y}: '
          f'{wizard.form.n_expanded} Objekte')
    wizard.execute('do_update')
    result = wizard.form
    print(f'  Angelegt: {result.n_created}, geändert: {result.n_updated}, '
          f'unverändert: {result.n_unchanged}, übersprungen: '
          f'{result.n_skipped}')
    wizard.execute('end')


def create_measurement(base_object, m_type, value: float) -> None:
    Measurement = Model.get('real_estate.measurement')
    m = Measurement()
    m.base_object = base_object
    m.m_type = m_type
    m.value = value
    m.valid_from = START_DATE
    m.save()
    print(f'    Bemessung: {m_type.name} = {value} {m_type.unit.symbol}')


USE_CLASS_SEQUENCE = {
    'Apartment': 10,
    'Office': 20,
    'Retail': 30,
    'Warehouse': 40,
    'Parking': 50,
    'Garage': 60,
}


def get_use_class(name: str):
    UseClass = Model.get('real_estate.use_class')
    seq = USE_CLASS_SEQUENCE.get(name)
    if seq is None:
        print(f'ERROR: Unbekannte Nutzungsklasse "{name}".', file=sys.stderr)
        sys.exit(1)
    results = UseClass.find([('sequence', '=', seq)])
    if not results:
        print(f'ERROR: Nutzungsklasse sequence={seq} ("{name}") nicht gefunden.',
              file=sys.stderr)
        sys.exit(1)
    return results[0]


def get_uom(symbol: str):
    Uom = Model.get('product.uom')
    results = Uom.find([('symbol', '=', symbol)])
    if not results:
        results = Uom.find([('name', 'ilike', symbol)])
    if not results:
        print(f'ERROR: Einheit "{symbol}" nicht gefunden.', file=sys.stderr)
        sys.exit(1)
    return results[0]


def get_country(code: str):
    Country = Model.get('country.country')
    results = Country.find([('code', '=', code)])
    return results[0] if results else None


def create_re_address(street_number: int, country) -> object:
    Address = Model.get('real_estate.address')
    address = Address()
    address.street_unstructured = f'Musterstraße {street_number}'
    address.postal_code = '14163'
    address.city = 'Berlin'
    if country:
        address.country = country
    address.save()
    print(f'  Adresse:   Musterstraße {street_number}, 14163 Berlin angelegt (id={address.id})')
    return address


def create_meter(parent, name: str, sequence: int, company, uom, admin_user,
                 kind=None, electricity=False) -> None:
    BaseObject = Model.get('real_estate.base_object')
    obj = BaseObject()
    obj.name = name
    obj.type = 'equipment'
    obj.e_type = 'meters'
    obj.company = company
    obj.start_date = START_DATE
    obj.state = 'approved'
    obj.sequence = sequence
    obj.parent = parent
    obj.meter_unit = uom
    obj.meter_factor = 1.0
    obj.meter_is_counter = True
    if kind:
        obj.equipment_kind = kind
    # calibration: validity 5 years, "valid to" proposed by the module
    calibration_date, valid_to = calibration_values()
    obj.meter_calibration_years = CALIBRATION_YEARS
    obj.meter_calibration_date = calibration_date
    if valid_to:
        obj.meter_calibration_valid_to = valid_to
    ids = ''
    if electricity:
        global _electricity_counter
        _electricity_counter += 1
        obj.melo_id = melo_id(_electricity_counter)
        obj.malo_id = malo_id(_electricity_counter)
        ids = f', MeLo {obj.melo_id}, MaLo {obj.malo_id}'
    obj.save()

    meter_id = next_meter_id()
    MeterReading = Model.get('real_estate.meter_reading')
    reading = MeterReading()
    reading.base_object = obj
    reading.m_type = 'initial'
    reading.meter_id = meter_id
    reading.reading_date = START_DATE
    reading.reading_user = admin_user
    reading.value = Decimal(0)
    reading.save()

    # Ablesung 30.04. des Startjahres mit zufälligem Verbrauch zwischen 20
    # und 40 m³ (Hausstrom: 1.500 bis 3.000 kWh)
    verbrauch = Decimal(random.randint(1500, 3000) if electricity
        else random.randint(20, 40))
    reading2 = MeterReading()
    reading2.base_object = obj
    reading2.m_type = 'reading'
    reading2.meter_id = meter_id
    reading2.reading_date = datetime.date(START_YEAR, 4, 30)
    reading2.reading_user = admin_user
    reading2.value = verbrauch
    reading2.save()

    unit = 'kWh' if electricity else 'm³'
    print(f'    Zähler:    {name} (id={obj.id}, meter_id={meter_id}, '
          f'Verbrauch={verbrauch} {unit}, Eichung {calibration_date:%d.%m.%Y} '
          f'bis {obj.meter_calibration_valid_to:%d.%m.%Y}{ids})')


def create_smoke_detector(apt, nr: int, count: int, company, kind, t_items):
    """Rauchwarnmelder der Wohnung als eine Anlage mit Bemessung "Anzahl"
    (spezifikation-pruefungen.md 2)"""
    BaseObject = Model.get('real_estate.base_object')
    obj = BaseObject()
    obj.name = f'Rauchwarnmelder WE {nr:02d}'
    obj.type = 'equipment'
    obj.e_type = 'technical_building_equipment,'
    obj.equipment_kind = kind
    obj.company = company
    obj.start_date = START_DATE
    obj.state = 'approved'
    obj.sequence = 20
    obj.parent = apt
    obj.save()
    create_measurement(obj, t_items, float(count))
    print(f'    Anlage:    {obj.name} ({count} Melder)')


def create_inspection_plans(prop, company, responsible=None,
        contractor=None) -> None:
    """Prüfpläne je Gebäude für die Standard-Prüfarten (Begehung,
    Rauchwarnmelder) mit Verantwortlichem, Auftragnehmer und zuletzt
    erledigt (ein Intervall vor der nächsten Fälligkeit)"""
    Type = Model.get('real_estate.inspection.type')
    Plan = Model.get('real_estate.inspection.plan')
    BaseObject = Model.get('real_estate.base_object')
    plans = [
        # due in the year after the start year
        ('walkthrough', datetime.date(START_YEAR + 1, 4, 1), False),
        ('smoke_detector', datetime.date(START_YEAR + 1, 5, 15), True),
        ]
    buildings = BaseObject.find([
            ('parent', '=', prop.id), ('type', '=', 'building')])
    for code, due, owner_maintains in plans:
        types = Type.find([('code', '=', code)])
        if not types:
            print(f'WARNUNG: Prüfart "{code}" nicht gefunden - keine Pläne.')
            continue
        for building in buildings:
            plan = Plan()
            plan.company = company
            plan.type = types[0]
            plan.property = prop
            plan.building = building
            plan.interval = types[0].interval
            plan.interval_unit = types[0].interval_unit
            plan.interval_basis = types[0].interval_basis
            plan.preferred_month = types[0].preferred_month
            plan.lead_time_days = types[0].lead_time_days
            plan.owner_maintains = owner_maintains
            plan.next_due_date = due
            if responsible:
                plan.responsible_user = responsible
            if contractor:
                plan.contractor = contractor
            plan.save()
            # "Last Done" is read-only in the client (set when an inspection
            # is completed) - written directly, as the date before the
            # first due date of the plan
            last_done = previous_due(due, types[0])
            Plan.write([plan], {'last_done_date': last_done},
                config.get_config().context)
        print(f'  Prüfpläne: {types[0].name} für {len(buildings)} Gebäude '
              f'(zuletzt erledigt {last_done:%d.%m.%Y})')


def previous_due(due, inspection_type):
    """Due date one interval before 'due' (interval of the inspection
    type in months or years)."""
    interval = inspection_type.interval or 1
    unit = {'day': 'days', 'week': 'weeks', 'month': 'months',
        'year': 'years'}.get(inspection_type.interval_unit, 'years')
    return due - relativedelta(**{unit: interval})


def get_responsible_user(administrator, admin_user):
    """User of the employee "Verwalter 1" (verwalter_1, see
    create_staff_users) - admin only as a fallback."""
    User = Model.get('res.user')
    Employee = Model.get('company.employee')
    employees = Employee.find([('party', '=', administrator.id)])
    if employees:
        users = User.find([('employees', 'in', [e.id for e in employees])])
        if users:
            return users[0]
    print(f'  Hinweis: kein Benutzer zum Mitarbeiter {administrator.name} - '
          f'Verantwortlicher der Prüfpläne: {admin_user.login}')
    return admin_user


def get_by_xml_id(model: str, xml_id: str):
    """Record of the data XML by its XML-ID - None if it is missing."""
    ModelData = Model.get('ir.model.data')
    try:
        record_id = ModelData.get_id(xml_id, config.get_config().context)
    except Exception:
        return None
    return Model.get(model)(record_id)


def create_staff_users(company, lang) -> list:
    """Users of the demo employees (STAFF_USERS) without password. An
    existing user with the same login is not changed; a hint is printed if
    it lacks the employee. Returns the logins of the created users."""
    created = []
    User = Model.get('res.user')
    Group = Model.get('res.group')
    Party = Model.get('party.party')
    Employee = Model.get('company.employee')
    Company = Model.get('company.company')
    for login, name, group_xml_ids in STAFF_USERS:
        parties = Party.find([('name', '=', name)])
        employees = Employee.find([
            ('party', 'in', [p.id for p in parties]),
            ('company', '=', company.id)]) if parties else []
        employee = employees[0] if employees else None
        with config.get_config().set_context(active_test=False):
            users = User.find([('login', '=', login)])
        if users:
            user = users[0]
            print(f'  Benutzer:  {login} vorhanden (id={user.id}), '
                  'nicht geändert')
            if employee and employee.id not in [
                    e.id for e in user.employees]:
                print(f'  Hinweis: Benutzer {login} ohne Mitarbeiter '
                      f'{name} - bitte von Hand zuordnen.')
            continue
        if not employee:
            print(f'  Hinweis: Mitarbeiter {name} fehlt - Benutzer {login} '
                  'nicht angelegt.')
            continue
        user = User(login=login, name=name)
        user.companies.append(Company(company.id))
        user.company = Company(company.id)
        user.employees.append(Employee(employee.id))
        user.employee = Employee(employee.id)
        # res.user.language only allows translatable languages
        if lang and lang.translatable:
            user.language = lang
        elif lang:
            print(f'  Hinweis: Sprache {lang.name} nicht übersetzbar '
                  f'geladen - Benutzer {login} ohne Sprache.')
        missing = []
        for xml_id in group_xml_ids:
            group = get_by_xml_id('res.group', xml_id)
            if group:
                user.groups.append(Group(group.id))
            else:
                missing.append(xml_id)
        user.save()
        created.append(login)
        print(f'  Benutzer:  {login} angelegt (id={user.id}, ohne Passwort, '
              f'Gruppen: {", ".join(g.name for g in user.groups)})')
        if missing:
            print(f'  Hinweis: Gruppen nicht gefunden: {", ".join(missing)}')
    return created


def get_contractor():
    """Contractor of the inspection plans: supplier of demo_kreditor.py
    (runs before this script in demo_run.py) - None with a hint."""
    Party = Model.get('party.party')
    parties = Party.find([('name', '=', INSPECTION_CONTRACTOR)])
    if not parties:
        print(f'  Hinweis: Lieferant "{INSPECTION_CONTRACTOR}" fehlt '
              '(demo_kreditor.py vorher ausführen) - Prüfpläne ohne '
              'Auftragnehmer.')
        return None
    return parties[0]


def get_role_by_sequence(sequence: int):
    """Partnerrolle sprachunabhängig per Sequenznummer suchen
    (Hausmeister=10, Verwalter=20, siehe object_party.xml)."""
    Role = Model.get('real_estate.object_party.role')
    roles = Role.find([('sequence', '=', sequence)])
    if not roles:
        print(f'ERROR: Partnerrolle mit sequence={sequence} nicht gefunden.',
              file=sys.stderr)
        sys.exit(1)
    return roles[0]


def get_role_number(number: int, label: str):
    """Party role (real_estate.party.role_number) by its number -
    language independent; None with a warning when it is missing."""
    RoleNumber = Model.get('real_estate.party.role_number')
    results = RoleNumber.find([('number', '=', number)])
    if not results:
        print(f'  Warnung: Partei-Rolle {label} (Nummer {number}) nicht '
              'gefunden - Parteien bleiben ohne Partei-Rolle.')
        return None
    return results[0]


def get_or_create_staff(name: str, company, role_number=None):
    """Partner mit Mitarbeiter der Company anlegen - vorhandene gleichnamige
    Partner bzw. Mitarbeiter werden wiederverwendet. Die Partei-Rolle wird
    nur gesetzt, wenn der Partner noch keine hat."""
    Party = Model.get('party.party')
    Employee = Model.get('company.employee')
    parties = Party.find([('name', '=', name)])
    if parties:
        party = parties[0]
        print(f'  Partner:   {name} vorhanden (id={party.id})')
        if role_number and not party.role_number:
            party.role_number = role_number
            party.save()
    else:
        party = Party(name=name)
        if role_number:
            party.role_number = role_number
        party.save()
        print(f'  Partner:   {name} angelegt (id={party.id})')
    employees = Employee.find([
        ('party', '=', party.id), ('company', '=', company.id)])
    if employees:
        print(f'  Mitarbeiter: {name} vorhanden (id={employees[0].id})')
    else:
        employee = Employee(party=party, company=company,
            start_date=START_DATE)
        employee.save()
        print(f'  Mitarbeiter: {name} angelegt (id={employee.id})')
    return party


def assign_role(prop, party, role) -> None:
    """Partner als Partner zum Objekt mit der Rolle zuordnen (ab START_DATE)."""
    ObjectParty = Model.get('real_estate.object_party')
    assignment = ObjectParty(base_object=prop, party=party, role=role)
    assignment.valid_from = START_DATE
    assignment.save()
    print(f'  Rolle:     {role.name} = {party.name}')


def create_land_with_parking(prop_name: str, prop, company, sequence: int,
                             uc_parking, usable_space_type=None) -> None:
    """Create one land entry with 4 parking spaces under the given property."""
    land = create_base_object(
        name=f'{prop_name} – Grundstück',
        obj_type='land',
        company=company,
        sequence=sequence,
        parent=prop,
        usable_space_type=usable_space_type,
    )
    for i in range(1, 5):
        sp = create_base_object(
            name=f'Stellplatz {i:02d}',
            obj_type='object',
            company=company,
            sequence=i * 10,
            parent=land,
            type_of_use='residential',
            use_class=uc_parking,
        )
        sp.parking_nr = f'{i:02d}'
        sp.save()


def create_building(house_nr: int, building_seq: int, prop, company,
                    country, t_bgf, t_raume, t_wfl, t_gwfl, t_heiz, uom_m3, admin_user,
                    apt_start_nr: int, uc_apartment,
                    retail_start_nr: int, uc_retail,
                    usable_space_type=None, smoke_kind=None,
                    t_items=None, cold_water_kind=None, uom_kwh=None,
                    electricity_kind=None) -> tuple:
    """Create one building with 1 retail space (EG) and 4 apartments (1.OG/2.OG).
    Returns (next_apt_nr, next_retail_nr)."""
    address = create_re_address(house_nr, country)

    building = create_base_object(
        name=f'Musterstraße {house_nr} – Hauptgebäude',
        obj_type='building',
        company=company,
        sequence=building_seq,
        parent=prop,
        usable_space_type=usable_space_type,
    )
    building.address = address
    building.save()
    create_measurement(building, t_bgf, 3500.0)
    # house electricity meter of the building with MeLo-ID and MaLo-ID
    create_meter(building, f'Hausstrom Zähler {house_nr}', sequence=90,
                 company=company, uom=uom_kwh, admin_user=admin_user,
                 kind=electricity_kind, electricity=True)

    # Retail space on floor 0 (EG)
    retail = create_base_object(
        name=f'Einzelhandel {retail_start_nr:02d} (EG)',
        obj_type='object',
        company=company,
        sequence=5,
        parent=building,
        type_of_use='commercial',
        use_class=uc_retail,
        floor=0,
    )
    create_measurement(retail, t_gwfl, 140.0)
    create_meter(retail, f'Wasser Zähler EH{retail_start_nr:02d}', sequence=10,
                 company=company, uom=uom_m3, admin_user=admin_user,
                 kind=cold_water_kind)

    # 4 apartments on floors 1 and 2: (floor, side, rooms, area)
    apt_layout = [
        (1, 'links',  2, 57.0),
        (1, 'rechts', 3, 83.0),
        (2, 'links',  2, 57.0),
        (2, 'rechts', 3, 83.0),
    ]
    floor_label = {1: '1.OG', 2: '2.OG'}
    for i, (floor, seite, rooms, area) in enumerate(apt_layout):
        nr = apt_start_nr + i
        apt_name = f'Wohnung {nr:02d} ({floor_label[floor]} {seite})'
        apt = create_base_object(
            name=apt_name,
            obj_type='object',
            company=company,
            sequence=(i + 1) * 10,
            parent=building,
            type_of_use='residential',
            use_class=uc_apartment,
            floor=floor,
        )
        apt.basement_nr = f'K{nr:02d}'
        apt.save()
        create_measurement(apt, t_raume, float(rooms))
        create_measurement(apt, t_wfl, area)
        # Wohnfläche includes half of the 6 m² balcony (3 m²), which is
        # unheated - Heizfläche is therefore 3 m² smaller than Wohnfläche.
        create_measurement(apt, t_heiz, area - 3.0)
        create_meter(apt, f'Wasser Zähler {nr:02d}', sequence=10,
                     company=company, uom=uom_m3, admin_user=admin_user,
                     kind=cold_water_kind)
        if smoke_kind and t_items:
            create_smoke_detector(apt, nr, rooms, company, smoke_kind,
                t_items)

    return apt_start_nr + 4, retail_start_nr + 1


def main():
    default_year = datetime.date.today().year - 1
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True, help='Tryton-Datenbankname')
    parser.add_argument('--config', default=None, help='Pfad zur trytond.conf')
    parser.add_argument('--year', type=int, default=default_year,
        help=f'Startjahr der Demodaten (Default: aktuelles Jahr - 1 = '
             f'{default_year})')
    args = parser.parse_args()
    set_start_year(args.year)

    connect(args.database, args.config)

    company = get_company()

    User = Model.get('res.user')
    admin_users = User.find([('login', '=', 'admin')])
    if not admin_users:
        print('ERROR: Benutzer "admin" nicht gefunden.', file=sys.stderr)
        sys.exit(1)
    admin_user = admin_users[0]

    BaseObject = Model.get('real_estate.base_object')

    # Idempotenz: abbrechen, wenn eines der Objekte schon vorhanden ist
    for prop_name in ('Musterstraße 1-4', 'Musterstraße 5-8'):
        existing = BaseObject.find([
            ('name', '=', prop_name),
            ('type', '=', 'property'),
            ('company', '=', company.id),
        ])
        if existing:
            print(f'Property "{prop_name}" existiert bereits (id={existing[0].id}). Abbruch (Exit-Code 3).')
            sys.exit(EXIT_EXISTS)

    uom_m3 = get_uom('m³')
    ModelData = Model.get('ir.model.data')
    uom_kwh = Model.get('product.uom')(ModelData.get_id(
            'product.uom_energy_kwh', config.get_config().context))
    _self_test_ids()

    uc_apartment = get_use_class('Apartment')
    uc_parking = get_use_class('Parking')
    uc_retail = get_use_class('Retail')

    t_wfl = get_measurement_type_by_sequence(10)     # Wohnfläche
    t_gwfl = get_measurement_type_by_sequence(15)    # Gewerbefläche
    t_raume = get_measurement_type_by_sequence(20)   # Anzahl Räume
    t_heiz = get_measurement_type_by_sequence(25)    # Heizfläche
    t_bgf = get_measurement_type_by_sequence(30)     # Bruttogeschossfläche [BHF]
    t_usable_space = get_measurement_type_by_sequence(5)   # Usable Space
    t_items = get_measurement_type_by_sequence(50)   # Number of items (Anzahl)
    Kind = Model.get('real_estate.equipment.kind')
    smoke_kinds = Kind.find([('code', '=', 'smoke_detector')])
    smoke_kind = smoke_kinds[0] if smoke_kinds else None
    if not smoke_kind:
        print('WARNUNG: Anlagenart "smoke_detector" nicht gefunden - '
            'keine Rauchwarnmelder.')
    cold_water_kinds = Kind.find([('code', '=', 'cold_water_meter')])
    cold_water_kind = cold_water_kinds[0] if cold_water_kinds else None
    if not cold_water_kind:
        print('WARNUNG: Anlagenart "cold_water_meter" nicht gefunden - '
            'Wasserzähler ohne Anlagenart.')
    electricity_kind = get_by_xml_id(
        'real_estate.equipment.kind',
        'real_estate.equipment_kind_electricity_meter')
    if not electricity_kind:
        print('WARNUNG: Anlagenart "electricity_meter" nicht gefunden - '
            'Hausstrom-Zähler ohne Anlagenart.')
    langs = Model.get('ir.lang').find([('code', '=', 'de')])
    lang_de = langs[0] if langs else None

    country_de = get_country('DE')
    if not country_de:
        print('WARNUNG: Land "DE" nicht gefunden – Adressen werden ohne Land angelegt.')

    print(f'Erzeuge Daten für Company "{company.rec_name}" ...')

    # Verwalter und Hausmeister (Partner + Mitarbeiter) vorab anlegen
    print('\n=== Verwalter und Hausmeister ===')
    role_caretaker = get_role_by_sequence(10)
    role_administrator = get_role_by_sequence(20)
    employee_role = get_role_number(EMPLOYEE_ROLE_NUMBER, 'Mitarbeiter')
    administrator = get_or_create_staff(
        'Verwalter 1', company, employee_role)
    caretaker = get_or_create_staff('Hausmeister 1', company, employee_role)
    created_users = create_staff_users(company, lang_de)
    responsible = get_responsible_user(administrator, admin_user)
    contractor = get_contractor()

    building_args = dict(
        company=company, country=country_de,
        t_bgf=t_bgf, t_raume=t_raume, t_wfl=t_wfl, t_gwfl=t_gwfl, t_heiz=t_heiz,
        uom_m3=uom_m3, uom_kwh=uom_kwh, admin_user=admin_user,
        uc_apartment=uc_apartment, uc_retail=uc_retail,
        usable_space_type=t_usable_space,
        smoke_kind=smoke_kind, t_items=t_items,
        cold_water_kind=cold_water_kind, electricity_kind=electricity_kind,
    )

    # Wirtschaftseinheit 1: Musterstraße 1-4
    print('\n=== Wirtschaftseinheit: Musterstraße 1-4 ===')
    prop1 = create_base_object(
        name='Musterstraße 1-4', obj_type='property',
        company=company, sequence=10,
        usable_space_type=t_usable_space,
    )
    assign_role(prop1, administrator, role_administrator)
    assign_role(prop1, caretaker, role_caretaker)
    apt_nr = 1
    retail_nr = 1
    for house_nr, building_seq in [(1, 10), (2, 20), (3, 30), (4, 40)]:
        print(f'\n--- Gebäude Musterstraße {house_nr} ---')
        apt_nr, retail_nr = create_building(
            house_nr=house_nr, building_seq=building_seq,
            prop=prop1, apt_start_nr=apt_nr, retail_start_nr=retail_nr,
            **building_args,
        )
    print('\n--- Grundstück Musterstraße 1-4 ---')
    create_land_with_parking('Musterstraße 1-4', prop1, company, sequence=50,
                             uc_parking=uc_parking, usable_space_type=t_usable_space)
    create_inspection_plans(prop1, company, responsible, contractor)

    # Wirtschaftseinheit 2: Musterstraße 5-8
    print('\n=== Wirtschaftseinheit: Musterstraße 5-8 ===')
    prop2 = create_base_object(
        name='Musterstraße 5-8', obj_type='property',
        company=company, sequence=20,
        usable_space_type=t_usable_space,
    )
    assign_role(prop2, administrator, role_administrator)
    assign_role(prop2, caretaker, role_caretaker)
    apt_nr = 1
    retail_nr = 1
    for house_nr, building_seq in [(5, 10), (6, 20), (7, 30), (8, 40)]:
        print(f'\n--- Gebäude Musterstraße {house_nr} ---')
        apt_nr, retail_nr = create_building(
            house_nr=house_nr, building_seq=building_seq,
            prop=prop2, apt_start_nr=apt_nr, retail_start_nr=retail_nr,
            **building_args,
        )
    print('\n--- Grundstück Musterstraße 5-8 ---')
    create_land_with_parking('Musterstraße 5-8', prop2, company, sequence=50,
                             uc_parking=uc_parking, usable_space_type=t_usable_space)
    create_inspection_plans(prop2, company, responsible, contractor)

    # Optionssätze einmal zum Beginn ermitteln (Assistent "Optionssätze
    # aktualisieren")
    print('\n=== Optionssätze ===')
    update_option_rates(company, [prop1, prop2], START_DATE)

    print('\nFertig.')
    if created_users:
        print(
            '\nHINWEIS: Die Benutzer ' + ' und '.join(created_users)
            + ' haben kein Passwort und können sich\nerst anmelden, wenn es '
            'von Hand gesetzt ist ("Verwaltung > Benutzer >\nBenutzer", Feld '
            '"Passwort").')


if __name__ == '__main__':
    main()
