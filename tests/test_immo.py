"""
Demodaten für das Tryton-Modul real_estate erzeugen.

Das Skript legt folgende Objekte an:
  - 1 Immobilie (Property) "Musterstraße 1", Startdatum 01.01.2026, Status: approved
  - 1 Gebäude (Building) als Kind der Immobilie mit einer Bemessung:
      Bruttogeschossfläche 3.500 m² ab 01.01.2026
  - 4 Wohnungen (Rental Object, Type of Use: residential, Use: apartment)
      als Kinder des Gebäudes:
      - Wohnung 01 (EG links):  2 Räume, 57 m² Wohnfläche
      - Wohnung 02 (EG rechts): 3 Räume, 83 m² Wohnfläche
      - Wohnung 03 (OG links):  2 Räume, 57 m² Wohnfläche
      - Wohnung 04 (OG rechts): 3 Räume, 83 m² Wohnfläche
  - Je Wohnung 1 Zähler (Equipment, e_type: meters, Einheit: m³, Faktor: 1,
      Is Counter: ja) mit:
      - Initialablesung 0 m³ zum 01.01.2026
      - Ablesung zum 30.04.2026 mit zufälligem Verbrauch zwischen 20 und 40 m³
      Die Zähler-ID wird automatisch generiert (Format: Z-<Jahr>-<Nr>, z.B. Z-2026-0001).

Das Skript ist idempotent: es bricht ab, wenn eine Property mit dem Namen
"Musterstraße 1" in der Zieldatenbank bereits vorhanden ist.

Voraussetzung: Der Benutzer "admin" muss in Tryton auf die Sprache Deutsch
gestellt sein, da sonst die Bemessungstypen (z.B. "Bruttogeschossfläche [BHF]",
"Anzahl Räume", "Wohnfläche") nicht per Namen gefunden werden.

Verwendung:
    python tests/test_immo.py --database <Datenbankname> [--config <trytond.conf>]
"""

import argparse
import datetime
import random
import sys
from decimal import Decimal

from proteus import Model, config

START_DATE = datetime.date(2026, 1, 1)

# Globaler Zähler für eindeutige Meter-IDs innerhalb dieses Script-Laufs
_meter_id_counter = 0


def next_meter_id() -> str:
    global _meter_id_counter
    _meter_id_counter += 1
    return f'Z-{START_DATE.year}-{_meter_id_counter:04d}'


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


def get_measurement_type(name: str):
    MeasurementType = Model.get('real_estate.measurement.type')
    results = MeasurementType.find([('name', '=', name)])
    if not results:
        print(f'ERROR: Bemessungstyp "{name}" nicht gefunden.', file=sys.stderr)
        sys.exit(1)
    return results[0]


def create_base_object(
    name: str,
    obj_type: str,
    company,
    sequence: int,
    parent=None,
    type_of_use: str | None = None,
    use_class: str | None = None,
    floor: int | None = None,
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
    obj.save()
    print(f'  Erstellt: [{obj_type:10}] {name} (id={obj.id})')
    return obj


def create_measurement(base_object, m_type, value: float) -> None:
    Measurement = Model.get('real_estate.measurement')
    m = Measurement()
    m.base_object = base_object
    m.m_type = m_type
    m.value = value
    m.valid_from = START_DATE
    m.save()
    print(f'    Bemessung: {m_type.name} = {value} {m_type.unit.symbol}')


def get_uom(symbol: str):
    Uom = Model.get('product.uom')
    results = Uom.find([('symbol', '=', symbol)])
    if not results:
        # Fallback: Suche nach Name
        results = Uom.find([('name', 'ilike', symbol)])
    if not results:
        print(f'ERROR: Einheit "{symbol}" nicht gefunden.', file=sys.stderr)
        sys.exit(1)
    return results[0]


def get_country(code: str):
    Country = Model.get('country.country')
    results = Country.find([('code', '=', code)])
    return results[0] if results else None


def create_re_address(country) -> object:
    Address = Model.get('real_estate.address')
    address = Address()
    address.street_unstructured = 'Musterstraße 1'
    address.postal_code = '14163'
    address.city = 'Berlin'
    if country:
        address.country = country
    address.save()
    print(f'  Adresse:   Musterstraße 1, 14163 Berlin angelegt (id={address.id})')
    return address


def create_meter(parent, name: str, sequence: int, company, uom, admin_user) -> None:
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

    # Ablesung 30.04.2026 mit zufälligem Verbrauch zwischen 20 und 40 m³
    verbrauch = Decimal(random.randint(20, 40))
    reading2 = MeterReading()
    reading2.base_object = obj
    reading2.m_type = 'reading'
    reading2.meter_id = meter_id
    reading2.reading_date = datetime.date(2026, 4, 30)
    reading2.reading_user = admin_user
    reading2.value = verbrauch
    reading2.save()

    print(f'    Zähler:    {name} (id={obj.id}, meter_id={meter_id}, Verbrauch={verbrauch} m³)')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True, help='Tryton-Datenbankname')
    parser.add_argument('--config', default=None, help='Pfad zur trytond.conf')
    args = parser.parse_args()

    connect(args.database, args.config)

    company = get_company()

    User = Model.get('res.user')
    admin_users = User.find([('login', '=', 'admin')])
    if not admin_users:
        print('ERROR: Benutzer "admin" nicht gefunden.', file=sys.stderr)
        sys.exit(1)
    admin_user = admin_users[0]

    BaseObject = Model.get('real_estate.base_object')

    # Idempotenz: abbrechen, wenn Objekt schon vorhanden
    existing = BaseObject.find([
        ('name', '=', 'Musterstraße 1'),
        ('type', '=', 'property'),
        ('company', '=', company.id),
    ])
    if existing:
        print(f'Property "Musterstraße 1" existiert bereits (id={existing[0].id}). Abbruch.')
        return

    # Einheit Kubikmeter vorab laden
    uom_m3 = get_uom('m³')

    # Bemessungstypen vorab laden
    t_bgf = get_measurement_type('Bruttogeschossfläche [BHF]')
    t_raume = get_measurement_type('Anzahl Räume')
    t_wfl = get_measurement_type('Wohnfläche')

    country_de = get_country('DE')
    if not country_de:
        print('WARNUNG: Land "DE" nicht gefunden – Adresse wird ohne Land angelegt.')

    print(f'Erzeuge Daten für Company "{company.rec_name}" ...')

    # Adresse (real_estate.address) für die Immobilie
    prop_address = create_re_address(country_de)

    # Immobilie (Property)
    prop = create_base_object(
        name='Musterstraße 1',
        obj_type='property',
        company=company,
        sequence=10,
    )
    prop.address = prop_address
    prop.save()

    # Gebäude
    building = create_base_object(
        name='Musterstraße 1 – Hauptgebäude',
        obj_type='building',
        company=company,
        sequence=10,
        parent=prop,
    )
    create_measurement(building, t_bgf, 3500.0)

    # 4 Wohnungen: (Name, Sequenz, Stockwerk, Seite, Nummer)
    apartments = [
        ('Wohnung 01 (EG links)',  10, 0, 'links',  1),
        ('Wohnung 02 (EG rechts)', 20, 0, 'rechts', 2),
        ('Wohnung 03 (OG links)',  30, 1, 'links',  3),
        ('Wohnung 04 (OG rechts)', 40, 1, 'rechts', 4),
    ]
    for apt_name, seq, floor, seite, nr in apartments:
        apt = create_base_object(
            name=apt_name,
            obj_type='object',
            company=company,
            sequence=seq,
            parent=building,
            type_of_use='residential',
            use_class='apartment',
            floor=floor,
        )
        if seite == 'links':
            create_measurement(apt, t_raume, 2.0)
            create_measurement(apt, t_wfl, 57.0)
        else:
            create_measurement(apt, t_raume, 3.0)
            create_measurement(apt, t_wfl, 83.0)
        create_meter(apt, f'Zähler {nr:02d}', sequence=10, company=company, uom=uom_m3, admin_user=admin_user)

    print('Fertig.')


if __name__ == '__main__':
    main()
