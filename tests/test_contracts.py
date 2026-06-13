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
  - 3 Konditionen je Wohnungsvertrag, monatlich:
      - Apartment rent (sequence=1000): zufällig 11,00–16,00 EUR, Menge 1
      - Betriebskosten (sequence=2000): zufällig  3,00– 4,00 EUR, Menge 1
      - Heizkosten     (sequence=3000): zufällig  3,00– 4,00 EUR, Menge 1
  - Alle Verträge werden aktiviert (→ running).
  - 3 Verträge werden zufällig gekündigt:
      - Kündigung 1: Vertragsende 31.05.2025, Eingang Kündigung 28.02.2025
      - Kündigung 2: Vertragsende 31.07.2025, Eingang Kündigung 30.04.2025
      - Kündigung 3: Vertragsende 30.11.2025, Eingang Kündigung 31.08.2025
  - Für Kündigung 1: Folgevertrag ab 01.06.2025 (neuer Mieter, gleiche Wohnung)
  - Für Kündigung 2: Folgevertrag ab 16.09.2025 (neuer Mieter, gleiche Wohnung)

  Stellplätze (4 je WE, zufällig auf Wohnungsmieter verteilt):
    2x als zusätzliches ContractItem im vorhandenen Wohnungsvertrag:
        - ContractItem sequence=20, Kondition Miete Stellplatz sequence=40: 50,00 EUR
    2x als eigener Stellplatz-Einzelvertrag (gleicher Mieter, gleiche Adresse):
        - ContractItem sequence=10, Kondition Miete Stellplatz sequence=10: 50,00 EUR

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GEWERBEMIETVERTRÄGE (type_of_use='commercial')
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Vertragsart: erste ContractType für type_of_use 'commercial'
  Startdatum: 01.01.2025, alle Verträge werden aktiviert (→ running).
  Steuer auf alle Konditionen: USt. 19% Umsatzsteuer voller Satz Waren Inland

  Musterstraße 1-4 — 1 Sammelvertrag für alle 4 Gewerbeflächen:
    - Vertragspartner: "Gewerbemieter 1"
    - 1 ContractItem (sequence=10, Label "Gewerbeflächen EG")
      mit allen 4 Gewerbeobjekten (ContractItemObject)
    - 3 Konditionen, monatlich (Menge jeweils 4 × 140 m² = 560 m²):
        - Gewerbemiete    (sequence=8000): 25,00 EUR/m²
        - Betriebskosten  (sequence=2000): zufällig 3,00–4,00 EUR/m²
        - Heizkosten      (sequence=3000): zufällig 3,00–4,00 EUR/m²

  Musterstraße 5-8 — je 1 Einzelvertrag pro Gewerbefläche (4 Verträge):
    - Vertragspartner: "Gewerbemieter 2–5"
    - Je 1 ContractItem (sequence=10) mit dem zugeordneten Gewerbeobjekt
    - 3 Konditionen je Vertrag, monatlich (Menge jeweils 140 m²):
        - Gewerbemiete    (sequence=8000): 25,00 EUR/m²
        - Betriebskosten  (sequence=2000): zufällig 3,00–4,00 EUR/m²
        - Heizkosten      (sequence=3000): zufällig 3,00–4,00 EUR/m²

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HINWEISE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  - Idempotenz: Abbruch wenn Party "Mieter 1" bereits existiert.
  - UseClass wird per Sequenznummer gesucht (sprachunabhängig):
      Apartment=10, Parking=50, Retail=30
  - Für NK/HK-Konditionen bei Gewerbeverträgen wird die Menge explizit
    auf die Gewerbefläche gesetzt, da proteus on_change_with_quantity
    vor dem Setzen von reference_item feuert.

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
PARKING_PRICE = Decimal('50.00')

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


def get_contract_type(type_of_use: str = 'residential'):
    ContractType = Model.get('real_estate.contract.type')
    results = ContractType.find([
        ('types_of_use', 'in', type_of_use),
    ], order=[('sequence', 'ASC')], limit=1)
    if not results:
        print(f'ERROR: Keine ContractType für type_of_use "{type_of_use}" gefunden.',
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
    contract.contractual_partner = partner
    contract.invoice_address = invoice_address
    contract.sequence = sequence
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


def terminate_contract(contract, termination_date, receipt_date):
    contract.state = 'terminated'
    contract.terminated_by_type = 'tenant'
    contract.receipt_of_termination_notice = receipt_date
    contract.termination_date = termination_date
    contract.termination_notice = ''
    contract.save()
    print(f'  Vertrag id={contract.id} → terminated per {termination_date} '
          f'(Eingang Kündigung: {receipt_date})')


def create_followup_contract(terminated_contract, company, property_obj, c_type,
                             currency, partner, invoice_address, start_date, sequence):
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
    contract.contractual_partner = partner
    contract.invoice_address = invoice_address
    contract.sequence = sequence
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
        for old_obj in old_item.objects:
            new_obj = ContractItemObject()
            new_obj.item = new_item
            new_obj.object = Model.get('real_estate.base_object')(old_obj.object.id)
            new_obj.sequence = old_obj.sequence
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
                         taxes=None) -> None:
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
    term.save()
    if taxes:
        term = ContractTerm(term.id)
        term.taxes.extend([Tax(t.id) for t in taxes])
        term.save()
    tax_info = f', Steuer: {[t.name for t in taxes]}' if taxes else ''
    print(f'    Kondition:     {term_type.name}, EP={unit_price} EUR, '
          f'Menge={quantity}, monatlich{tax_info}')


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
    c_type_commercial = get_contract_type('commercial')

    uc_apartment = get_use_class('Apartment')
    uc_parking = get_use_class('Parking')
    uc_retail = get_use_class('Retail')

    tt_rent       = get_term_type(1000)  # Apartment rent
    tt_nk         = get_term_type(2000)  # Betriebskosten
    tt_hz         = get_term_type(3000)  # Heizkosten
    tt_parking    = get_term_type(1100)  # Miete Stellplatz
    tt_commercial = get_term_type(8000)  # Gewerbemiete

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

            rent_price = Decimal(str(round(random.uniform(11, 16), 2)))
            nk_price   = Decimal(str(round(random.uniform(3, 4), 2)))
            hz_price   = Decimal(str(round(random.uniform(3, 4), 2)))

            create_contract_term(contract, tt_rent, item, rent_price,   sequence=10)
            create_contract_term(contract, tt_nk,   item, nk_price,     sequence=20)
            create_contract_term(contract, tt_hz,   item, hz_price,     sequence=30)

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

        n_term = min(len(TERMINATIONS), len(all_contracts))
        to_terminate = random.sample(all_contracts, n_term)
        print(f'\n--- Verträge kündigen ({n_term}x) ---')
        for c, (term_date, receipt_date) in zip(to_terminate, TERMINATIONS):
            terminate_contract(c, term_date, receipt_date)

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
            )
            contract_seq += 10
            followup.click('running')
            print(f'  Folgevertrag id={followup.id} → running')

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
            )
            contract_seq += 10
            followup.click('running')
            print(f'  Folgevertrag id={followup.id} → running')

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
    qty_total = RETAIL_AREA * len(retail_p1)
    create_contract_term(g_contract, tt_commercial, g_item,
                         COMMERCIAL_RENT, sequence=10, quantity=qty_total,
                         taxes=commercial_taxes)
    create_contract_term(g_contract, tt_nk, g_item,
                         Decimal(str(round(random.uniform(3, 4), 2))),
                         sequence=20, quantity=qty_total,
                         taxes=commercial_taxes)
    create_contract_term(g_contract, tt_hz, g_item,
                         Decimal(str(round(random.uniform(3, 4), 2))),
                         sequence=30, quantity=qty_total,
                         taxes=commercial_taxes)
    g_contract.click('running')
    print(f'  Vertrag id={g_contract.id} → running')

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
        create_contract_term(g_contract, tt_commercial, g_item,
                             COMMERCIAL_RENT, sequence=10, quantity=RETAIL_AREA,
                             taxes=commercial_taxes)
        create_contract_term(g_contract, tt_nk, g_item,
                             Decimal(str(round(random.uniform(3, 4), 2))),
                             sequence=20, quantity=RETAIL_AREA,
                             taxes=commercial_taxes)
        create_contract_term(g_contract, tt_hz, g_item,
                             Decimal(str(round(random.uniform(3, 4), 2))),
                             sequence=30, quantity=RETAIL_AREA,
                             taxes=commercial_taxes)
        g_contract.click('running')
        print(f'  Vertrag id={g_contract.id} → running')

    print('\nFertig.')


if __name__ == '__main__':
    main()
