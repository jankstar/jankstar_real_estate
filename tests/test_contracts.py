"""
Demodaten für Mietverträge im Tryton-Modul real_estate erzeugen.

Voraussetzung: Die Immobiliendaten aus test_immo.py müssen bereits in der
Datenbank vorhanden sein (Properties "Musterstraße 1-4" und "Musterstraße 5-8").

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WOHNUNGSMIETVERTRÄGE (type_of_use='residential')
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Je Wirtschaftseinheit (16 Wohnungen, 4 Stellplätze):

  - 15 von 16 Wohnungen erhalten je einen Wohnungsmietvertrag;
    1 Wohnung bleibt zufällig leer (kein Vertrag).
  - Vertragspartner "Mieter N" (N zählt über beide WE durch):
      Sprache Deutsch, Adresse Musterstraße 1, 14163 Berlin, DE
  - Vertragsart: erste ContractType für type_of_use 'residential'
  - Startdatum: 01.01.2025
  - Je Vertrag 1 ContractItem (sequence=10) mit der zugeordneten Wohnung
  - 3 Konditionen je Wohnungsvertrag, monatlich, absoluter Betrag (Menge 1).
    Der Betrag wird aus einem zufälligen Preis je m² × Wohnfläche der
    Wohnung berechnet (57 m² bzw. 83 m² aus test_immo.py):
      - Apartment rent (sequence=1000): 11,00–16,00 EUR/m²
      - Betriebskosten (sequence=2000):  3,00– 4,00 EUR/m²
      - Heizkosten     (sequence=3000):  3,00– 4,00 EUR/m²
    Die Konditionsarten haben keine Bemessung (m_type) mehr, sondern nur
    eine informative Bemessung (info_m_type) - der Wert je m² wird in der
    Kondition nur zurückgerechnet angezeigt.
  - Alle Verträge werden aktiviert (→ running).
  - 3 Verträge werden zufällig gekündigt:
      - Kündigung 1: Vertragsende 31.05.2025, Eingang Kündigung 28.02.2025
      - Kündigung 2: Vertragsende 31.07.2025, Eingang Kündigung 30.04.2025
      - Kündigung 3: Vertragsende 30.11.2025, Eingang Kündigung 31.08.2025
  - Für Kündigung 1: Folgevertrag ab 01.06.2025 (neuer Mieter, gleiche Wohnung)
  - Für Kündigung 2: Folgevertrag ab 16.09.2025 (neuer Mieter, gleiche Wohnung)
  - Staffelmieten (§ 557a BGB): bis zu 3 laufende, nicht gekündigte
    Wohnungsverträge je WE erhalten eine Mietanpassung mit Verfahren
    "Staffelmiete" auf ihre Miet-Kondition (sequence=1000): Rhythmus 12
    Monate, 5 Staffeln, Vereinbarung zum Vertragsbeginn, Schriftform; je
    Vertrag eine andere Eingabeart der Erhöhung (+30,00 EUR absolut,
    +0,40 EUR/m² über die informative Fläche, +3 % vom Ausgangsbetrag).
    Die Staffelkonditionen werden per "Generieren" angelegt. Das Verfahren
    "Staffelmiete" wird dafür an der Vertragsart (residential) und der
    Konditionsart 1000 zugelassen, falls noch nicht vorhanden.

  Stellplätze (4 je WE, zufällig auf Wohnungsmieter verteilt):
    2x als zusätzliches ContractItem im vorhandenen Wohnungsvertrag:
        - ContractItem sequence=20, Kondition Miete Stellplatz sequence=40: 50,00 EUR
    2x als eigener Stellplatz-Einzelvertrag (gleicher Mieter, gleiche Adresse):
        - ContractItem sequence=10, Kondition Miete Stellplatz sequence=10: 50,00 EUR

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GEWERBEMIETVERTRÄGE (type_of_use='commercial')
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Vertragsart: ContractType sequence=50 für type_of_use 'commercial' (Gewerbemietevertrag)
  Startdatum: 01.01.2025, alle Verträge werden aktiviert (→ running).
  Steuer auf alle Konditionen: USt. 19% Umsatzsteuer voller Satz Waren Inland

  Musterstraße 1-4 — 1 Sammelvertrag für alle 4 Gewerbeflächen:
    - Vertragspartner: "Gewerbemieter 1"
    - 1 ContractItem (sequence=10, Label "Gewerbeflächen EG")
      mit allen 4 Gewerbeobjekten (ContractItemObject)
    - 3 Konditionen, monatlich, absoluter Betrag (Menge 1) auf Basis der
      Gesamtfläche 4 × 140 m² = 560 m², Verteilung auf Objekte
      (object_distribution) "nach Info-Fläche" statt Default "gleichanteilig":
        - Gewerbemiete    (sequence=8000): 25,00 EUR/m²
        - Betriebskosten  (sequence=2000): zufällig 3,00–4,00 EUR/m²
        - Heizkosten      (sequence=3000): zufällig 3,00–4,00 EUR/m²

  Musterstraße 5-8 — je 1 Einzelvertrag pro Gewerbefläche (4 Verträge):
    - Vertragspartner: "Gewerbemieter 2–5"
    - Je 1 ContractItem (sequence=10) mit dem zugeordneten Gewerbeobjekt
    - 3 Konditionen je Vertrag, monatlich, absoluter Betrag (Menge 1)
      auf Basis 140 m²:
        - Gewerbemiete    (sequence=8000): 25,00 EUR/m²
        - Betriebskosten  (sequence=2000): zufällig 3,00–4,00 EUR/m²
        - Heizkosten      (sequence=3000): zufällig 3,00–4,00 EUR/m²

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HINWEISE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  - Idempotenz: Abbruch wenn Party "Mieter 1" bereits existiert.
  - UseClass wird per Sequenznummer gesucht (sprachunabhängig):
      Apartment=10, Parking=50, Retail=30
  - Konditionen werden immer absolut angelegt (Menge 1, Einzelpreis =
    Preis je m² × Fläche, auf 2 Nachkommastellen gerundet). Die Fläche
    wird aus den Bemessungen der Objekte gelesen (Wohnfläche sequence=10,
    Gewerbefläche sequence=15, sprachunabhängig per sequence gesucht).

Verwendung:
    python tests/test_contracts.py --database <Datenbankname> [--config <trytond.conf>]
"""

import argparse
import datetime
import random
import sys
from decimal import Decimal

from proteus import Model, config

START_DATE = datetime.date(2025, 1, 1)
YEAR_END_DATE = datetime.date(2025, 12, 31)
PARKING_PRICE = Decimal('50.00')

# Role sequence for 'Main Tenant' (see contract_party.xml) - looked up by
# sequence rather than name, more robust against translations.
MAIN_TENANT_ROLE_SEQUENCE = 10

# (termination_date, receipt_of_notice) — notice 3 months before termination
TERMINATIONS = [
    (datetime.date(2025, 5, 31), datetime.date(2025, 2, 28)),
    (datetime.date(2025, 7, 31), datetime.date(2025, 4, 30)),
    (datetime.date(2025, 11, 30), datetime.date(2025, 8, 31)),
]


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


def get_properties():
    BaseObject = Model.get('real_estate.base_object')
    props = []
    for name in ('Musterstraße 1-4', 'Musterstraße 5-8'):
        results = BaseObject.find([
            ('name', '=', name),
            ('type', '=', 'property'),
        ])
        if not results:
            print(f'ERROR: Property "{name}" nicht gefunden. Bitte zuerst test_immo.py ausführen.',
                  file=sys.stderr)
            sys.exit(1)
        props.append(results[0])
    return props


def get_apartments(property_obj, uc_apartment):
    BaseObject = Model.get('real_estate.base_object')
    return BaseObject.find([
        ('property', '=', property_obj.id),
        ('type', '=', 'object'),
        ('use_class', '=', uc_apartment.id),
    ], order=[('sequence', 'ASC')])


def get_parking_spaces(property_obj, uc_parking):
    BaseObject = Model.get('real_estate.base_object')
    return BaseObject.find([
        ('property', '=', property_obj.id),
        ('type', '=', 'object'),
        ('use_class', '=', uc_parking.id),
    ], order=[('sequence', 'ASC')])


def get_retail_objects(property_obj, uc_retail):
    BaseObject = Model.get('real_estate.base_object')
    return BaseObject.find([
        ('property', '=', property_obj.id),
        ('type', '=', 'object'),
        ('use_class', '=', uc_retail.id),
    ], order=[('sequence', 'ASC')])


def get_admin_user():
    User = Model.get('res.user')
    admin_users = User.find([('login', '=', 'admin')])
    if not admin_users:
        print('WARNUNG: Benutzer "admin" nicht gefunden.', file=sys.stderr)
        return None
    return admin_users[0]


def get_measurement_type(name: str):
    MeasurementType = Model.get('real_estate.measurement.type')
    results = MeasurementType.find([('name', '=', name)])
    if not results:
        print(f'WARNUNG: Bemessungstyp "{name}" nicht gefunden.', file=sys.stderr)
        return None
    return results[0]


def get_measurement_type_by_sequence(sequence: int, label: str):
    MeasurementType = Model.get('real_estate.measurement.type')
    results = MeasurementType.find([('sequence', '=', sequence)], limit=1)
    if not results:
        print(f'WARNUNG: Bemessungstyp sequence={sequence} ("{label}") '
              f'nicht gefunden.', file=sys.stderr)
        return None
    return results[0]


def get_area(objects, m_type, fallback: Decimal = None) -> Decimal:
    """Sum the measurement value of m_type over the given objects - used to
    derive an absolute term amount from a price per m²."""
    total = Decimal(0)
    for obj in objects:
        value = get_measurement_value(obj, m_type)
        if value is None:
            if fallback is None:
                print(f'WARNUNG: Keine Bemessung "{m_type.name if m_type else "?"}" '
                      f'für {obj.name} gefunden.', file=sys.stderr)
                continue
            value = fallback
        total += Decimal(str(value))
    return total


def random_price_per_m2(low: float, high: float) -> Decimal:
    return Decimal(str(round(random.uniform(low, high), 2)))


def absolute_amount(price_per_m2: Decimal, area: Decimal) -> Decimal:
    return (price_per_m2 * area).quantize(Decimal('0.01'))


def get_water_meter(base_object):
    BaseObject = Model.get('real_estate.base_object')
    results = BaseObject.find([
        ('parent', '=', base_object.id),
        ('type', '=', 'equipment'),
        ('e_type', '=', 'meters'),
    ], limit=1)
    return results[0] if results else None


def get_measurement_value(base_object, m_type):
    if m_type is None:
        return None
    Measurement = Model.get('real_estate.measurement')
    results = Measurement.find([
        ('base_object', '=', base_object.id),
        ('m_type', '=', m_type.id),
    ])
    return results[0].value if results else None


def get_contract_type(type_of_use: str = 'residential', sequence: int = None):
    ContractType = Model.get('real_estate.contract.type')
    domain = [('types_of_use', 'in', type_of_use)]
    if sequence is not None:
        domain.append(('sequence', '=', sequence))
    results = ContractType.find(domain, order=[('sequence', 'ASC')], limit=1)
    if not results:
        print(f'ERROR: Keine ContractType für type_of_use "{type_of_use}"'
              f'{f" sequence={sequence}" if sequence else ""} gefunden.',
              file=sys.stderr)
        sys.exit(1)
    return results[0]


def get_term_type(sequence: int):
    TermType = Model.get('real_estate.contract.term.type')
    results = TermType.find([('sequence', '=', sequence)])
    if not results:
        print(f'ERROR: ContractTermType mit sequence={sequence} nicht gefunden.',
              file=sys.stderr)
        sys.exit(1)
    return results[0]


# Graduated rents (Staffelmiete, § 557a BGB) of the demo data: per property
# up to three running apartment contracts get one, each with a different
# increase mode - (increase_mode, increase_value, percent_basis)
GRADUATED_RENTS = [
    ('absolute', Decimal('30.00'), None),
    ('per_area', Decimal('0.40'), None),
    ('percent', Decimal('3'), 'base'),
    ]
GRADUATED_RHYTHM_MONTHS = 12
GRADUATED_STEP_COUNT = 5


def allow_procedure(record, procedure: str) -> None:
    """Add a rent adjustment procedure to the allowed procedures of a
    contract type or term type (if missing)."""
    procedures = list(record.adjustment_procedures or [])
    if procedure not in procedures:
        record.adjustment_procedures = procedures + [procedure]
        record.save()
        print(f'  Verfahren "{procedure}" zugelassen für "{record.name}"')


def create_graduated_rent(contract, term, increase_mode, increase_value,
                          percent_basis=None):
    """Create a graduated rent (rent adjustment, procedure
    'graduated_rent') for the given base term and generate its steps."""
    RentAdjustment = Model.get('real_estate.contract.rent_adjustment')
    rent_adjustment = RentAdjustment()
    rent_adjustment.contract = contract
    rent_adjustment.procedure = 'graduated_rent'
    rent_adjustment.term = term
    rent_adjustment.rhythm_months = GRADUATED_RHYTHM_MONTHS
    rent_adjustment.step_count = GRADUATED_STEP_COUNT
    rent_adjustment.increase_mode = increase_mode
    rent_adjustment.increase_value = increase_value
    if percent_basis:
        rent_adjustment.percent_basis = percent_basis
    rent_adjustment.agreement_date = contract.start_date
    rent_adjustment.written_form = True
    rent_adjustment.save()
    rent_adjustment.click('generate')
    rent_adjustment.reload()
    amounts = [str(t.graduated_amount) for t in sorted(
            rent_adjustment.terms, key=lambda t: t.graduated_step)]
    print(f'  Staffelmiete Vertrag id={contract.id}: {increase_mode} '
          f'{increase_value} → {" / ".join(amounts)} EUR')
    return rent_adjustment


def create_party(name: str, country, lang):
    Party = Model.get('party.party')
    Address = Model.get('party.address')

    party = Party()
    party.name = name
    if lang:
        party.lang = lang
    party.save()

    if party.addresses:
        address = party.addresses[0]
    else:
        address = Address()
        address.party = party

    address.street_name = 'Musterstraße 1'
    address.postal_code = '14163'
    address.city = 'Berlin'
    if country:
        address.country = country
    address.delivery = True
    address.invoice = True
    address.save()

    print(f'  Vertragspartner: {name} (id={party.id})')
    return party, address


def get_main_tenant_role():
    # contractual_partner is now a Function field auto-filled from the
    # 'Main Tenant Role' party assignment (see contract_core.py); assign
    # the partner there instead of setting contractual_partner directly.
    Role = Model.get('real_estate.contract.party.role')
    results = Role.find([('sequence', '=', MAIN_TENANT_ROLE_SEQUENCE)])
    return results[0] if results else None


def create_contract(company, property_obj, c_type, currency,
                    partner, invoice_address, sequence: int,
                    type_of_use: str = 'residential'):
    Contract = Model.get('real_estate.contract')
    contract = Contract()
    contract.company = company
    contract.property = property_obj
    contract.type_of_use = type_of_use
    contract.c_type = c_type
    contract.currency = currency
    contract.start_date = START_DATE
    contract.sequence = sequence
    main_tenant_role = get_main_tenant_role()
    if main_tenant_role:
        assignment = contract.parties.new()
        assignment.party = partner
        assignment.role = main_tenant_role
        assignment.valid_from = START_DATE
        assignment.invoice_address = invoice_address
    else:
        print('  Warning: "Main Tenant" role not found (sequence='
              f'{MAIN_TENANT_ROLE_SEQUENCE}) - contractual_partner will '
              'stay empty until it is assigned manually.')
    contract.save()
    print(f'  Vertrag:         id={contract.id}, Sequenz={sequence}')
    return contract


def create_contract_item(contract, obj, sequence: int):
    ContractItem = Model.get('real_estate.contract.item')
    ContractItemObject = Model.get('real_estate.contract.item.object')
    item = ContractItem()
    item.contract = contract
    item.label = obj.name
    item.valid_from = START_DATE
    item.sequence = sequence
    item.save()

    item_obj = ContractItemObject()
    item_obj.item = item
    item_obj.object = obj
    item_obj.save()

    print(f'    Item:          "{obj.name}" ab {START_DATE}')
    return item


def record_meter_reading(contract, reading_date, t_wfl, admin_user):
    """Record a water meter reading (Messbeleg) for the rental object(s) of a
    contract, dated on the given reading_date (contract termination or
    start of a new tenancy). The consumption is computed linearly over
    time: 10 m³/year per 100 m² of living area."""
    MeterReading = Model.get('real_estate.meter_reading')
    seen_object_ids = set()
    for item in contract.items:
        for obj in item.objects:
            if obj.id in seen_object_ids:
                continue
            seen_object_ids.add(obj.id)

            meter = get_water_meter(obj)
            if meter is None:
                continue

            area = get_measurement_value(obj, t_wfl)
            if area is None:
                print(f'    WARNUNG: Keine Wohnflächen-Bemessung für "{obj.name}" '
                      f'gefunden – Ablesung übersprungen.', file=sys.stderr)
                continue

            last = MeterReading.find(
                [('base_object', '=', meter.id)],
                order=[('reading_date', 'DESC')], limit=1)
            if not last:
                print(f'    WARNUNG: Keine vorherige Ablesung für Zähler '
                      f'"{meter.name}" gefunden – Ablesung übersprungen.',
                      file=sys.stderr)
                continue
            last_reading = last[0]

            days_elapsed = (reading_date - last_reading.reading_date).days
            if days_elapsed <= 0:
                continue

            annual_consumption = Decimal(str(area)) / Decimal(100) * Decimal(10)
            consumption = annual_consumption * Decimal(days_elapsed) / Decimal(365)
            new_value = (last_reading.value + consumption).quantize(Decimal('1'))

            reading = MeterReading()
            reading.base_object = meter
            reading.m_type = 'reading'
            reading.meter_id = last_reading.meter_id
            reading.reading_date = reading_date
            reading.reading_user = admin_user
            reading.value = new_value
            reading.save()
            print(f'    Messbeleg: Zähler "{meter.name}" '
                  f'{last_reading.value} → {new_value} m³ '
                  f'(+{consumption:.1f} m³ seit {last_reading.reading_date})')


def record_year_end_reading(contract, target_date, admin_user):
    """Record a year-end water meter reading (Ablesung) for the rental
    object(s) of a contract that is still running on target_date. The value
    is extrapolated linearly from the last two known readings of the meter,
    i.e. at the same daily rate as the most recent recorded consumption."""
    MeterReading = Model.get('real_estate.meter_reading')
    seen_object_ids = set()
    for item in contract.items:
        for obj in item.objects:
            if obj.id in seen_object_ids:
                continue
            seen_object_ids.add(obj.id)

            meter = get_water_meter(obj)
            if meter is None:
                continue

            history = MeterReading.find(
                [('base_object', '=', meter.id)],
                order=[('reading_date', 'DESC')], limit=2)
            if len(history) < 2:
                print(f'    WARNUNG: Zu wenige Ablesungen für Zähler '
                      f'"{meter.name}" – Jahresendablesung übersprungen.',
                      file=sys.stderr)
                continue
            last_reading, prev_reading = history[0], history[1]

            if last_reading.reading_date >= target_date:
                continue

            interval_days = (last_reading.reading_date - prev_reading.reading_date).days
            if interval_days <= 0:
                continue

            daily_rate = (last_reading.value - prev_reading.value) / Decimal(interval_days)
            days_elapsed = (target_date - last_reading.reading_date).days
            new_value = (last_reading.value + daily_rate * Decimal(days_elapsed)).quantize(Decimal('1'))

            reading = MeterReading()
            reading.base_object = meter
            reading.m_type = 'reading'
            reading.meter_id = last_reading.meter_id
            reading.reading_date = target_date
            reading.reading_user = admin_user
            reading.value = new_value
            reading.save()
            print(f'    Jahresendablesung: Zähler "{meter.name}" '
                  f'{last_reading.value} → {new_value} m³ '
                  f'(Rate {daily_rate:.3f} m³/Tag seit {last_reading.reading_date})')


def terminate_contract(contract, termination_date, receipt_date, t_wfl, admin_user):
    contract.state = 'terminated'
    contract.terminated_by_type = 'tenant'
    contract.receipt_of_termination_notice = receipt_date
    contract.termination_date = termination_date
    contract.termination_notice = ''
    contract.save()
    print(f'  Vertrag id={contract.id} → terminated per {termination_date} '
          f'(Eingang Kündigung: {receipt_date})')
    record_meter_reading(contract, termination_date, t_wfl, admin_user)


def create_followup_contract(terminated_contract, company, property_obj, c_type,
                             currency, partner, invoice_address, start_date, sequence,
                             t_wfl, admin_user):
    """Create a follow-up contract copying all items and terms from the predecessor."""
    Contract = Model.get('real_estate.contract')
    ContractItem = Model.get('real_estate.contract.item')
    ContractItemObject = Model.get('real_estate.contract.item.object')
    ContractTerm = Model.get('real_estate.contract.term')

    contract = Contract()
    contract.company = company
    contract.property = property_obj
    contract.type_of_use = terminated_contract.type_of_use
    contract.c_type = c_type
    contract.currency = currency
    contract.start_date = start_date
    contract.sequence = sequence
    main_tenant_role = get_main_tenant_role()
    if main_tenant_role:
        assignment = contract.parties.new()
        assignment.party = partner
        assignment.role = main_tenant_role
        assignment.valid_from = start_date
        assignment.invoice_address = invoice_address
    contract.save()
    print(f'  Folgevertrag: id={contract.id}, Start={start_date}')

    # Copy items; track old_item.id → new_item for term reference mapping
    item_map = {}
    for old_item in terminated_contract.items:
        new_item = ContractItem()
        new_item.contract = contract
        new_item.label = old_item.label
        new_item.valid_from = start_date
        new_item.sequence = old_item.sequence
        new_item.save()
        for obj in old_item.objects:
            new_obj = ContractItemObject()
            new_obj.item = new_item
            new_obj.object = Model.get('real_estate.base_object')(obj.id)
            new_obj.save()
        item_map[old_item.id] = new_item
        label = old_item.label or '–'
        print(f'    Item: "{label}" ab {start_date}')

    # Copy terms with reference_item mapped to new items
    for old_term in terminated_contract.terms:
        new_term = ContractTerm()
        new_term.contract = contract
        new_term.term_type = old_term.term_type
        new_term.valid_from = start_date
        new_term.rhythm = old_term.rhythm
        new_term.rhythm_type = old_term.rhythm_type
        new_term.rhythm_start = old_term.rhythm_start
        new_term.quantity = old_term.quantity
        new_term.unit_price = old_term.unit_price
        new_term.sequence = old_term.sequence
        if old_term.reference_item:
            new_term.reference_item = item_map.get(old_term.reference_item.id)
        new_term.save()
        print(f'    Kondition: {old_term.term_type.name}, '
              f'EP={old_term.unit_price} EUR')

    # Übergabe-Ablesung bei Mietbeginn – nicht für Verträge, die (wie alle
    # Erstverträge) am START_DATE beginnen, dafür existiert bereits die
    # initiale Ablesung aus test_immo.py.
    if start_date != START_DATE:
        record_meter_reading(contract, start_date, t_wfl, admin_user)

    return contract


def create_contract_item_multi(contract, objects: list, label: str, sequence: int):
    """Create a ContractItem with multiple ContractItemObjects."""
    ContractItem = Model.get('real_estate.contract.item')
    ContractItemObject = Model.get('real_estate.contract.item.object')
    item = ContractItem()
    item.contract = contract
    item.label = label
    item.valid_from = START_DATE
    item.sequence = sequence
    item.save()
    for obj in objects:
        item_obj = ContractItemObject()
        item_obj.item = item
        item_obj.object = obj
        item_obj.save()
    print(f'    Item:          "{label}" mit {len(objects)} Objekt(en) ab {START_DATE}')
    return item


def get_tax(name: str):
    Tax = Model.get('account.tax')
    results = Tax.find([('name', '=', name)])
    if not results:
        print(f'WARNUNG: Steuer "{name}" nicht gefunden – wird nicht zugeordnet.',
              file=sys.stderr)
        return None
    return results[0]


def create_contract_term(contract, term_type, reference_item,
                         unit_price: Decimal, sequence: int,
                         quantity: Decimal = Decimal(1),
                         taxes=None, price_per_m2: Decimal = None,
                         area: Decimal = None,
                         object_distribution: str = None) -> None:
    ContractTerm = Model.get('real_estate.contract.term')
    Tax = Model.get('account.tax')
    term = ContractTerm()
    term.contract = contract
    term.term_type = term_type
    term.reference_item = reference_item
    term.valid_from = START_DATE
    term.rhythm = 1
    term.rhythm_type = 'monthly'
    term.quantity = quantity
    term.unit_price = unit_price
    term.sequence = sequence
    if object_distribution:
        term.object_distribution = object_distribution
    term.save()
    if taxes:
        term = ContractTerm(term.id)
        term.taxes.extend([Tax(t.id) for t in taxes])
        term.save()
    tax_info = f', Steuer: {[t.name for t in taxes]}' if taxes else ''
    calc_info = (f' ({price_per_m2} EUR/m² × {area} m²)'
                 if price_per_m2 is not None and area is not None else '')
    print(f'    Kondition:     {term_type.name}, EP={unit_price} EUR'
          f'{calc_info}, Menge={quantity}, monatlich{tax_info}')


def create_commercial_terms(contract, item, area: Decimal,
                            tt_commercial, tt_nk, tt_hz,
                            rent_per_m2: Decimal, taxes,
                            object_distribution: str = None) -> None:
    """Commercial rent, operating and heating cost advance as absolute
    amounts (price per m² × area)."""
    for tt, price_m2, seq in (
            (tt_commercial, rent_per_m2, 10),
            (tt_nk, random_price_per_m2(3, 4), 20),
            (tt_hz, random_price_per_m2(3, 4), 30)):
        create_contract_term(
            contract, tt, item, absolute_amount(price_m2, area),
            sequence=seq, taxes=taxes, price_per_m2=price_m2, area=area,
            object_distribution=object_distribution)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True, help='Tryton-Datenbankname')
    parser.add_argument('--config', default=None, help='Pfad zur trytond.conf')
    args = parser.parse_args()

    connect(args.database, args.config)

    # Idempotenz
    Party = Model.get('party.party')
    if Party.find([('name', '=', 'Mieter 1')]):
        print('Party "Mieter 1" existiert bereits. Abbruch.')
        return

    company = get_company()
    currency = company.currency
    properties = get_properties()
    c_type = get_contract_type('residential')
    c_type_commercial = get_contract_type('commercial', sequence=50)

    uc_apartment = get_use_class('Apartment')
    uc_parking = get_use_class('Parking')
    uc_retail = get_use_class('Retail')

    tt_rent       = get_term_type(1000)  # Apartment rent

    # Graduated rent needs the procedure on contract type and term type
    allow_procedure(c_type, 'graduated_rent')
    allow_procedure(tt_rent, 'graduated_rent')
    tt_nk         = get_term_type(2000)  # Betriebskosten
    tt_hz         = get_term_type(3000)  # Heizkosten
    tt_parking    = get_term_type(1100)  # Miete Stellplatz
    tt_commercial = get_term_type(8000)  # Gewerbemiete

    t_wfl = get_measurement_type('Wohnfläche')
    # Area basis for the absolute term amounts (looked up by sequence,
    # language independent - see measurement.xml)
    t_living = get_measurement_type_by_sequence(10, 'Wohnfläche')
    t_commercial = get_measurement_type_by_sequence(15, 'Gewerbefläche')
    admin_user = get_admin_user()

    Country = Model.get('country.country')
    countries = Country.find([('code', '=', 'DE')])
    country = countries[0] if countries else None

    Lang = Model.get('ir.lang')
    langs = Lang.find([('code', '=', 'de')])
    de_lang = langs[0] if langs else None
    if not de_lang:
        print('WARNUNG: Sprache "de" nicht gefunden – Sprache wird nicht gesetzt.')

    print(f'Erzeuge Verträge für Company "{company.rec_name}" ...')

    mieter_nr = 1  # läuft über alle Wirtschaftseinheiten durch
    year_end_contracts = []  # Verträge, die zum 31.12.2025 noch laufen

    for prop in properties:
        print(f'\n{"=" * 60}')
        print(f'=== Wirtschaftseinheit: {prop.name} ===')
        print(f'{"=" * 60}')

        apartments = get_apartments(prop, uc_apartment)
        parking_spaces = get_parking_spaces(prop, uc_parking)

        if not apartments:
            print(f'WARNUNG: Keine Wohnungen unter {prop.name} gefunden.')
            continue

        if len(parking_spaces) < 4:
            print(f'WARNUNG: Weniger als 4 Stellplätze unter {prop.name} gefunden '
                  f'(gefunden: {len(parking_spaces)}).')

        # Zufällig 1 Wohnung leer lassen
        vacant_idx = random.randrange(len(apartments))
        print(f'\n  Leer bleibend: {apartments[vacant_idx].name} (Index {vacant_idx})')

        # Verträge für alle Wohnungen außer der leerstehenden
        contracts_this_prop = []
        contract_seq = 10
        for idx, apartment in enumerate(apartments):
            if idx == vacant_idx:
                print(f'\n  [LEER] {apartment.name} – kein Vertrag')
                continue

            print(f'\n--- Mieter {mieter_nr} / {apartment.name} ---')
            party, address = create_party(
                name=f'Mieter {mieter_nr}',
                country=country,
                lang=de_lang,
            )
            contract = create_contract(
                company=company,
                property_obj=prop,
                c_type=c_type,
                currency=currency,
                partner=party,
                invoice_address=address,
                sequence=contract_seq,
            )
            item = create_contract_item(contract, apartment, sequence=10)

            area = get_area([apartment], t_living)
            for tt, (low, high), seq in (
                    (tt_rent, (11, 16), 10),
                    (tt_nk, (3, 4), 20),
                    (tt_hz, (3, 4), 30)):
                price_m2 = random_price_per_m2(low, high)
                create_contract_term(
                    contract, tt, item, absolute_amount(price_m2, area),
                    sequence=seq, price_per_m2=price_m2, area=area)

            contracts_this_prop.append(contract)
            mieter_nr += 1
            contract_seq += 10

        # Stellplätze verteilen: 2x zu vorhandenem Vertrag, 2x neuer Einzelvertrag
        n_to_add = min(2, len(parking_spaces), len(contracts_this_prop))
        n_new = min(2, len(parking_spaces) - n_to_add,
                    len(contracts_this_prop) - n_to_add)
        total = n_to_add + n_new

        selected = random.sample(contracts_this_prop, total) if total else []
        add_to = selected[:n_to_add]
        new_for = selected[n_to_add:]

        print(f'\n--- Stellplatz zu vorhandenem Vertrag ({n_to_add}x) ---')
        for contract, parking in zip(add_to, parking_spaces[:n_to_add]):
            print(f'  Stellplatz "{parking.name}" → Vertrag id={contract.id}')
            parking_item = create_contract_item(contract, parking, sequence=20)
            create_contract_term(
                contract, tt_parking, parking_item,
                PARKING_PRICE, sequence=40,
            )

        parking_contracts = []
        print(f'\n--- Neuer Stellplatz-Einzelvertrag ({n_new}x) ---')
        for contract, parking in zip(new_for, parking_spaces[n_to_add:n_to_add + n_new]):
            partner = contract.contractual_partner
            address = contract.invoice_address
            print(f'  Stellplatz "{parking.name}" → neuer Vertrag '
                  f'für "{partner.rec_name}" (id={partner.id})')
            p_contract = create_contract(
                company=company,
                property_obj=prop,
                c_type=c_type,
                currency=currency,
                partner=partner,
                invoice_address=address,
                sequence=contract_seq,
            )
            contract_seq += 10
            parking_item = create_contract_item(p_contract, parking, sequence=10)
            create_contract_term(
                p_contract, tt_parking, parking_item,
                PARKING_PRICE, sequence=10,
            )
            parking_contracts.append(p_contract)

        all_contracts = contracts_this_prop + parking_contracts
        print(f'\n--- Verträge aktivieren ({len(all_contracts)}x) ---')
        for c in all_contracts:
            c.click('running')
            print(f'  Vertrag id={c.id} → running')
        year_end_contracts.extend(all_contracts)

        n_term = min(len(TERMINATIONS), len(all_contracts))
        to_terminate = random.sample(all_contracts, n_term)
        print(f'\n--- Verträge kündigen ({n_term}x) ---')
        for c, (term_date, receipt_date) in zip(to_terminate, TERMINATIONS):
            terminate_contract(c, term_date, receipt_date, t_wfl, admin_user)
            year_end_contracts.remove(c)

        # Follow-up contract for the 31.05.2025 termination
        if n_term > 0:
            pred = to_terminate[0]
            followup_start = TERMINATIONS[0][0] + datetime.timedelta(days=1)
            print(f'\n--- Folgevertrag für Kündigung {TERMINATIONS[0][0]} ---')
            party, address = create_party(
                name=f'Mieter {mieter_nr}',
                country=country,
                lang=de_lang,
            )
            mieter_nr += 1
            followup = create_followup_contract(
                terminated_contract=pred,
                company=company,
                property_obj=prop,
                c_type=c_type,
                currency=currency,
                partner=party,
                invoice_address=address,
                start_date=followup_start,
                sequence=contract_seq,
                t_wfl=t_wfl,
                admin_user=admin_user,
            )
            contract_seq += 10
            followup.click('running')
            print(f'  Folgevertrag id={followup.id} → running')
            year_end_contracts.append(followup)

        # Follow-up contract for the 31.07.2025 termination, starting 16.09.2025
        if n_term > 1:
            pred = to_terminate[1]
            followup_start = datetime.date(2025, 9, 16)
            print(f'\n--- Folgevertrag für Kündigung {TERMINATIONS[1][0]} ---')
            party, address = create_party(
                name=f'Mieter {mieter_nr}',
                country=country,
                lang=de_lang,
            )
            mieter_nr += 1
            followup = create_followup_contract(
                terminated_contract=pred,
                company=company,
                property_obj=prop,
                c_type=c_type,
                currency=currency,
                partner=party,
                invoice_address=address,
                start_date=followup_start,
                sequence=contract_seq,
                t_wfl=t_wfl,
                admin_user=admin_user,
            )
            contract_seq += 10
            followup.click('running')
            print(f'  Folgevertrag id={followup.id} → running')
            year_end_contracts.append(followup)

        # Graduated rents for up to three running (not terminated) apartment
        # contracts of this property
        candidates = [c for c in contracts_this_prop if c not in to_terminate]
        print(f'\n--- Staffelmieten ({min(len(GRADUATED_RENTS), len(candidates))}x) ---')
        for contract, (mode, value, basis) in zip(
                random.sample(candidates, min(len(GRADUATED_RENTS),
                        len(candidates))), GRADUATED_RENTS):
            contract.reload()
            rent_terms = [t for t in contract.terms
                if t.term_type.id == tt_rent.id]
            if rent_terms:
                create_graduated_rent(contract, rent_terms[0], mode, value,
                    basis)

    # --- Gewerbemietverträge ---
    print(f'\n{"=" * 60}')
    print('=== Gewerbemietverträge ===')
    print(f'{"=" * 60}')

    ust19 = get_tax('USt. 19% Umsatzsteuer voller Satz Waren Inland')
    commercial_taxes = [ust19] if ust19 else []

    gewerbe_mieter_nr = 1
    COMMERCIAL_RENT = Decimal('25.00')
    RETAIL_AREA = Decimal('140')

    # Property 1: alle 4 Gewerbeobjekte in einem einzigen Vertrag
    prop1 = properties[0]
    retail_p1 = get_retail_objects(prop1, uc_retail)
    print(f'\n--- {prop1.name}: 1 Gewerbevertrag für {len(retail_p1)} Objekte ---')

    gm_party, gm_address = create_party(
        name=f'Gewerbemieter {gewerbe_mieter_nr}',
        country=country,
        lang=de_lang,
    )
    gewerbe_mieter_nr += 1

    g_contract = create_contract(
        company=company,
        property_obj=prop1,
        c_type=c_type_commercial,
        currency=currency,
        partner=gm_party,
        invoice_address=gm_address,
        sequence=10,
        type_of_use='commercial',
    )
    g_item = create_contract_item_multi(
        g_contract, retail_p1,
        label='Gewerbeflächen EG',
        sequence=10,
    )
    area_total = get_area(retail_p1, t_commercial, fallback=RETAIL_AREA)
    # Several objects on one item: split the absolute amounts by commercial
    # space when booking (default would be equal shares)
    create_commercial_terms(g_contract, g_item, area_total,
                            tt_commercial, tt_nk, tt_hz,
                            COMMERCIAL_RENT, commercial_taxes,
                            object_distribution='info_measurement')
    g_contract.click('running')
    print(f'  Vertrag id={g_contract.id} → running')
    year_end_contracts.append(g_contract)

    # Property 2: je ein Gewerbevertrag pro Gewerbeobjekt
    prop2 = properties[1]
    retail_p2 = get_retail_objects(prop2, uc_retail)
    print(f'\n--- {prop2.name}: je 1 Gewerbevertrag pro Objekt ({len(retail_p2)}x) ---')

    g_contract_seq = 10
    for retail_obj in retail_p2:
        print(f'\n  Objekt: {retail_obj.name}')
        gm_party, gm_address = create_party(
            name=f'Gewerbemieter {gewerbe_mieter_nr}',
            country=country,
            lang=de_lang,
        )
        gewerbe_mieter_nr += 1

        g_contract = create_contract(
            company=company,
            property_obj=prop2,
            c_type=c_type_commercial,
            currency=currency,
            partner=gm_party,
            invoice_address=gm_address,
            sequence=g_contract_seq,
            type_of_use='commercial',
        )
        g_contract_seq += 10

        g_item = create_contract_item(g_contract, retail_obj, sequence=10)
        area = get_area([retail_obj], t_commercial, fallback=RETAIL_AREA)
        create_commercial_terms(g_contract, g_item, area,
                                tt_commercial, tt_nk, tt_hz,
                                COMMERCIAL_RENT, commercial_taxes)
        g_contract.click('running')
        print(f'  Vertrag id={g_contract.id} → running')
        year_end_contracts.append(g_contract)

    print(f'\n{"=" * 60}')
    print(f'=== Jahresendablesungen ({YEAR_END_DATE}) für laufende Verträge '
          f'({len(year_end_contracts)}x) ===')
    print(f'{"=" * 60}')
    for c in year_end_contracts:
        record_year_end_reading(c, YEAR_END_DATE, admin_user)

    print('\nFertig.')


if __name__ == '__main__':
    main()
