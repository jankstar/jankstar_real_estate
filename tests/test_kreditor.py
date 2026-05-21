"""
Kreditoren (Lieferanten-Partner) für Demodaten im Tryton-Modul real_estate anlegen.

Das Skript legt folgende party.party-Datensätze als Kreditoren an:

  - Land Berlin          (Grundsteuer)
      Klosterstraße 47, 10179 Berlin
  - Berliner Wasserbetriebe (Wasserrechnung)
      Neue Jüdenstraße 1, 10179 Berlin
  - BSR                  (Straßenreinigung und Müll)
      Ringbahnstraße 96, 12103 Berlin

Jede Party erhält:
  - Kategorie 'Lieferant' (falls in der DB vorhanden)
  - Eine Rechnungsadresse (invoice=True) und Lieferadresse (delivery=True)

Das Skript ist idempotent: es bricht ab, wenn "Land Berlin" als Party
bereits in der Datenbank existiert.

Verwendung:
    python tests/test_kreditor.py --database <Datenbankname> [--config <trytond.conf>]
"""

import argparse
import sys

from proteus import Model, config

KREDITOREN = [
    {
        'name': 'Land Berlin',
        'comment': 'Grundsteuer',
        'street_name': 'Klosterstraße',
        'building_number': '47',
        'postal_code': '10179',
        'city': 'Berlin',
    },
    {
        'name': 'Berliner Wasserbetriebe',
        'comment': 'Wasserrechnung',
        'street_name': 'Neue Jüdenstraße',
        'building_number': '1',
        'postal_code': '10179',
        'city': 'Berlin',
    },
    {
        'name': 'BSR',
        'comment': 'Straßenreinigung und Müll',
        'street_name': 'Ringbahnstraße',
        'building_number': '96',
        'postal_code': '12103',
        'city': 'Berlin',
    },
]


def connect(database: str, cfg_file: str | None) -> None:
    if cfg_file:
        config.set_trytond(database=database, config_file=cfg_file)
    else:
        config.set_trytond(database=database)


def get_country_de():
    Country = Model.get('country.country')
    results = Country.find([('code', '=', 'DE')])
    return results[0] if results else None


def get_lang_de():
    Lang = Model.get('ir.lang')
    results = Lang.find([('code', '=', 'de')])
    return results[0] if results else None


def get_supplier_category():
    Category = Model.get('party.category')
    results = Category.find([('name', 'ilike', '%lieferant%')])
    return results[0] if results else None


def create_kreditor(data: dict, country, lang, category) -> None:
    Party = Model.get('party.party')
    Address = Model.get('party.address')

    party = Party()
    party.name = data['name']
    if lang:
        party.lang = lang
    if hasattr(party, 'supplier') :
        party.supplier = True
    party.save()

    if party.addresses:
        address = party.addresses[0]
    else:
        address = Address()
        address.party = party

    address.street_name = data['street_name']
    if data.get('building_number'):
        address.building_number = data['building_number']
    address.postal_code = data['postal_code']
    address.city = data['city']
    if country:
        address.country = country
    address.invoice = True
    address.delivery = True
    address.save()

    print(
        f'  Kreditor: {party.name} (id={party.id})'
        f' — {data["street_name"]} {data.get("building_number", "")},'
        f' {data["postal_code"]} {data["city"]}'
        f'  [{data["comment"]}]'
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True, help='Tryton-Datenbankname')
    parser.add_argument('--config', default=None, help='Pfad zur trytond.conf')
    args = parser.parse_args()

    connect(args.database, args.config)

    # Idempotenz: abbrechen, wenn "Land Berlin" bereits existiert
    Party = Model.get('party.party')
    if Party.find([('name', '=', 'Land Berlin')]):
        print('Party "Land Berlin" existiert bereits. Abbruch.')
        return

    country = get_country_de()
    lang = get_lang_de()
    category = get_supplier_category()

    print('Lege Kreditoren an ...')
    for data in KREDITOREN:
        create_kreditor(data, country, lang, category)

    print('Fertig.')


if __name__ == '__main__':
    main()
