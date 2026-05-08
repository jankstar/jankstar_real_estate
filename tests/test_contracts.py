"""
Demodaten für Mietverträge im Tryton-Modul real_estate erzeugen.

Voraussetzung: Die Immobiliendaten aus test_immo.py müssen bereits in der
Datenbank vorhanden sein (Property "Musterstraße 1" mit Wohnungen).

Das Skript legt für die ersten 3 Wohnungen je folgende Objekte an:
  - 1 Vertragspartner (party.party): "Mieter 1" bis "Mieter 3"
      mit einer party.address "Musterstraße 1, Wohnung <Nr>"
  - 1 Mietvertrag (real_estate.contract):
      - Vertragsart: erste verfügbare ContractType für type_of_use 'residential'
      - Startdatum: 01.01.2026, Status: draft
      - Vertragspartner: der angelegte Mieter
      - Rechnungsadresse: die Adresse des Mieters
  - 1 ContractItem: Zuordnung der Wohnung zum Vertrag ab 01.01.2026
  - 2 Konditionen (ContractTerm) je Vertrag, mit Bezug zum ContractItem,
      Rhythmus monatlich (rhythm=1, rhythm_type='monthly'):
      - Apartment rent   (ContractTermType sequence=1000): zufälliger Einheitspreis zwischen 11,00 und 16,00
      - Betriebskosten   (ContractTermType sequence=2000): zufälliger Einheitspreis zwischen  3,00 und  4,00
      Die ContractTermTypes werden per sequence-Feld gesucht, nicht per Name.

Das Skript ist idempotent: es bricht ab, wenn "Mieter 1" als Party
bereits in der Datenbank existiert.

Verwendung:
    python tests/test_contracts.py --database <Datenbankname> [--config <trytond.conf>]
"""

import argparse
import datetime
import random
import sys
from decimal import Decimal

from proteus import Model, config

START_DATE = datetime.date(2026, 1, 1)


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


def get_property():
    BaseObject = Model.get('real_estate.base_object')
    results = BaseObject.find([
        ('name', '=', 'Musterstraße 1'),
        ('type', '=', 'property'),
    ])
    if not results:
        print('ERROR: Property "Musterstraße 1" nicht gefunden. Bitte zuerst test_immo.py ausführen.', file=sys.stderr)
        sys.exit(1)
    return results[0]


def get_apartments(property_obj, limit: int = 3):
    BaseObject = Model.get('real_estate.base_object')
    apartments = BaseObject.find([
        ('property', '=', property_obj.id),
        ('type', '=', 'object'),
        ('type_of_use', '=', 'residential'),
    ], order=[('sequence', 'ASC')], limit=limit)
    if len(apartments) < limit:
        print(f'ERROR: Weniger als {limit} Wohnungen unter der Property gefunden.', file=sys.stderr)
        sys.exit(1)
    return apartments


def get_contract_type():
    ContractType = Model.get('real_estate.contract.type')
    results = ContractType.find([
        ('types_of_use', 'in', 'residential'),
    ], order=[('sequence', 'ASC')], limit=1)
    if not results:
        print('ERROR: Keine ContractType für type_of_use "residential" gefunden.', file=sys.stderr)
        sys.exit(1)
    return results[0]


def create_party(name: str, street: str, city: str, country) -> object:
    Party = Model.get('party.party')
    Address = Model.get('party.address')

    party = Party()
    party.name = name
    party.save()

    address = Address()
    address.party = party
    address.street = street
    address.city = city
    if country:
        address.country = country
    address.save()

    print(f'  Vertragspartner: {name} (id={party.id}), Adresse: {street}, {city}')
    return party, address


def create_contract(company, property_obj, c_type, currency, partner, invoice_address, sequence: int) -> object:
    Contract = Model.get('real_estate.contract')
    contract = Contract()
    contract.company = company
    contract.property = property_obj
    contract.type_of_use = 'residential'
    contract.c_type = c_type
    contract.currency = currency
    contract.start_date = START_DATE
    contract.contractual_partner = partner
    contract.invoice_address = invoice_address
    contract.sequence = sequence
    contract.save()
    print(f'  Vertrag:         id={contract.id}, Sequenz={sequence}')
    return contract


def get_term_type(sequence: int):
    TermType = Model.get('real_estate.contract.term.type')
    results = TermType.find([('sequence', '=', sequence)])
    if not results:
        print(f'ERROR: ContractTermType mit sequence={sequence} nicht gefunden.', file=sys.stderr)
        sys.exit(1)
    return results[0]


def create_contract_term(contract, term_type, reference_item, unit_price: Decimal, sequence: int) -> None:
    ContractTerm = Model.get('real_estate.contract.term')
    term = ContractTerm()
    term.contract = contract
    term.term_type = term_type
    term.reference_item = reference_item
    term.valid_from = START_DATE
    term.rhythm = 1
    term.rhythm_type = 'monthly'
    term.quantity = Decimal(1)
    term.unit_price = unit_price
    term.sequence = sequence
    term.save()
    print(f'    Kondition:     {term_type.name}, Einheitspreis={unit_price}, monatlich')


def create_contract_item(contract, apartment, sequence: int):
    ContractItem = Model.get('real_estate.contract.item')
    item = ContractItem()
    item.contract = contract
    item.object = apartment
    item.valid_from = START_DATE
    item.sequence = sequence
    item.save()
    print(f'    Item:          Wohnung "{apartment.name}" ab {START_DATE}')
    return item


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True, help='Tryton-Datenbankname')
    parser.add_argument('--config', default=None, help='Pfad zur trytond.conf')
    args = parser.parse_args()

    connect(args.database, args.config)

    # Idempotenz: abbrechen, wenn Mieter 1 bereits existiert
    Party = Model.get('party.party')
    if Party.find([('name', '=', 'Mieter 1')]):
        print('Party "Mieter 1" existiert bereits. Abbruch.')
        return

    company = get_company()
    currency = company.currency
    property_obj = get_property()
    apartments = get_apartments(property_obj, limit=3)
    c_type = get_contract_type()
    tt_rent = get_term_type(1000)   # Apartment rent
    tt_nk = get_term_type(2000)     # Betriebskosten

    # Land aus Firmendaten übernehmen (für party.address), optional
    Country = Model.get('country.country')
    countries = Country.find([('code', '=', 'DE')])
    country = countries[0] if countries else None

    print(f'Erzeuge Verträge für Company "{company.rec_name}" ...')

    for i, apartment in enumerate(apartments, start=1):
        print(f'\n--- Mieter {i} / Wohnung: {apartment.name} ---')

        street = f'Musterstraße 1, {apartment.name}'
        party, address = create_party(
            name=f'Mieter {i}',
            street=street,
            city='Berlin',
            country=country,
        )

        contract = create_contract(
            company=company,
            property_obj=property_obj,
            c_type=c_type,
            currency=currency,
            partner=party,
            invoice_address=address,
            sequence=i * 10,
        )

        item = create_contract_item(
            contract=contract,
            apartment=apartment,
            sequence=10,
        )

        rent_price = Decimal(str(round(random.uniform(11, 16), 2)))
        nk_price = Decimal(str(round(random.uniform(3, 4), 2)))

        create_contract_term(
            contract=contract,
            term_type=tt_rent,
            reference_item=item,
            unit_price=rent_price,
            sequence=10,
        )
        create_contract_term(
            contract=contract,
            term_type=tt_nk,
            reference_item=item,
            unit_price=nk_price,
            sequence=20,
        )

    print('\nFertig.')


if __name__ == '__main__':
    main()
