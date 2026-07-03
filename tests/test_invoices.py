"""
Kreditoren-Rechnungen (Lieferantenrechnungen) für Demodaten anlegen und buchen.

Voraussetzung: Die Kreditoren aus test_kreditor.py müssen bereits vorhanden sein
sowie test_immo.py und test_billing_unit.py (für Settlement-Unit-Zuordnung).

Das Skript legt folgende Rechnungen an und bucht sie (state=posted):

  Land Berlin — 1 Rechnung:
    - Datum: 15.03.2025
    - Position: "Grundsteuer 2025", 1 × 1.890,00 EUR, ohne Steuer
    - Konto: 7680 (Grundsteuer), Settlement Unit 100

  Allianz AG — 1 Rechnung:
    - Datum: 15.02.2025
    - Position: "Gebäudeversicherung 2025", 1 × 7.801,00 EUR + 19 % VSt
    - Konto: 5130, Settlement Unit 110

  Berliner Wasserbetriebe — 6 Rechnungen, 2-monatlich zum 15. (Jan–Nov 2025):
    - Position: "Wasserrechnung MM/YYYY", 1 × 2.166,00 EUR + 19 % VSt
    - Konto: 5130, Settlement Unit 200

  Gas AG — 6 Rechnungen, 2-monatlich zum 15. (Jan–Nov 2025):
    - Position: "Gasrechnung MM/YYYY", 1 × 39.650,00 EUR + 19 % VSt
    - Konto: 5130, Settlement Unit 300

  BSR — 6 Rechnungen, 2-monatlich zum 15. (Jan–Nov 2025):
    - Position 1: "Straßenreinigung", 1 × 433,00 EUR + 19 % VSt, Settlement Unit 500
    - Position 2: "Müll",             1 × 541,00 EUR + 19 % VSt, Settlement Unit 510

  Vattenfall — 6 Rechnungen, 2-monatlich zum 15. (Jan–Nov 2025):
    - Position: "Hausstrom", 1 × 650,00 EUR + 19 % VSt, Settlement Unit 610

  Reinigung Müller / B&O — je 12 Rechnungen, monatlich zum 25.:
    - Hausreinigung 431,00 EUR + 19 % VSt (Settlement Unit 520)
    - Hausmeister   758,00 EUR + 19 % VSt (Settlement Unit 700)

  Gartenpflege GaLa — 1 Rechnung 15.02.2025, 3.250,00 EUR + 19 % VSt (SU 600)
  Schornsteinfeger Krüger — 1 Rechnung 15.11.2025, 1.950,00 EUR + 19 % VSt (SU 620)
  Vailand GmbH — 1 Rechnung 25.11.2025, 3.860,00 EUR + 19 % VSt (SU 310)

Das Skript ist idempotent: bereits vorhandene Rechnungen (gleiche Party,
Datum und Referenz) werden übersprungen. Die Referenz enthält jeweils den
Property-Namen in eckigen Klammern, z.B. "Grundsteuer 2025 [Musterstraße 1-4]".

Verwendung:
    python tests/test_invoices.py --database <Datenbankname> [--config <trytond.conf>]
"""

import argparse
import datetime
import sys
from decimal import Decimal

from proteus import Model, config


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
        print('ERROR: Keine Company in der Datenbank gefunden.', file=sys.stderr)
        sys.exit(1)
    if len(companies) > 1:
        print(f'Mehrere Companies gefunden, verwende: {companies[0].rec_name}')
    return companies[0]


def get_party(name: str):
    Party = Model.get('party.party')
    results = Party.find([('name', '=', name)])
    if not results:
        print(f'ERROR: Party "{name}" nicht gefunden. Bitte zuerst test_kreditor.py ausführen.',
              file=sys.stderr)
        sys.exit(1)
    return results[0]


def get_account(code: str):
    Account = Model.get('account.account')
    results = Account.find([('code', '=', code)])
    if not results:
        print(f'ERROR: Konto mit Code "{code}" nicht gefunden.', file=sys.stderr)
        sys.exit(1)
    return results[0]


def get_properties():
    BaseObject = Model.get('real_estate.base_object')
    results = BaseObject.find(
        [('type', '=', 'property')],
        order=[('sequence', 'ASC')])
    if not results:
        print('ERROR: Keine Properties gefunden. Bitte zuerst test_immo.py ausführen.',
              file=sys.stderr)
        sys.exit(1)
    return results


def get_settlement_unit(sequence: int, prop):
    SettlementUnit = Model.get('real_estate.settlement_unit')
    results = SettlementUnit.find([
        ('sequence', '=', sequence),
        ('billing_unit.property', '=', prop.id),
        ('billing_unit.state', 'not in', ['draft', 'billed']),
    ])
    if not results:
        print(f'  WARNUNG: Settlement Unit Sequence {sequence} für Property {prop.name}'
              f' nicht gefunden oder Billing Unit im Status draft/billed — Feld wird nicht gesetzt.')
        return None
    return results[0]


def get_purchase_tax_19():
    """Vorsteuer 19 % — sucht exakt nach 'VSt. 19% Vorsteuer voll Waren Inland'."""
    Tax = Model.get('account.tax')
    results = Tax.find([('name', '=', 'VSt. 19% Vorsteuer voll Waren Inland')])
    if not results:
        print('ERROR: Steuer "VSt. 19% Vorsteuer voll Waren Inland" nicht gefunden.',
              file=sys.stderr)
        sys.exit(1)
    return results[0]




# ---------------------------------------------------------------------------
# Rechnung anlegen und buchen
# ---------------------------------------------------------------------------

def create_and_post_invoice(
    company,
    party,
    invoice_date: datetime.date,
    reference: str,
    lines_data: list,
) -> None:
    """
    lines_data: Liste von Dicts mit Schlüsseln:
        description (str), unit_price (Decimal), account, taxes (list),
        property (optional), settlement_unit (optional)
    """

    Invoice = Model.get('account.invoice')

    if Invoice.find([
        ('type', '=', 'in'),
        ('party', '=', party.id),
        ('invoice_date', '=', invoice_date),
        ('reference', '=', reference),
        ('state', '!=', 'cancelled'),
    ]):
        print(f'  Übersprungen:  {party.name:30s} | {invoice_date} | {reference}')
        return

    InvoiceLine = Model.get('account.invoice.line')
    Tax = Model.get('account.tax')
    lines = []
    for ld in lines_data:

        line = InvoiceLine()
        #line.invoice = invoice
        line.company = company
        line.party = party
        line.invoice_type = 'in'
        line.type = 'line'
        line.description = ld['description']
        line.quantity = Decimal('1')
        line.unit_price = ld['unit_price']
        line.account = ld['account']
        if ld.get('taxes'):
            # Jede Steuer als frische Instanz laden, damit _group None bleibt
            line.taxes.extend(Tax(t.id) for t in ld['taxes'])
        if ld.get('property'):
            line.property = ld['property']
        if ld.get('settlement_unit'):
            line.settlement_unit = ld['settlement_unit']
        line.save()
        lines.append(line)

    if not lines:
        print(f'  WARNUNG: Keine Zeilen für Rechnung {reference} — Rechnung wird nicht angelegt.')
        return

    invoice = Invoice()
    invoice.type = 'in'
    invoice.company = company
    invoice.party = party
    invoice.invoice_date = invoice_date
    invoice.accounting_date = invoice_date
    invoice.reference = reference
    invoice.description = reference
    invoice.lines.extend(lines)
    invoice.save()



    netto = sum(ld['unit_price'] for ld in lines_data)
    print(
        f'  Gespeichert: {party.name:30s} | {invoice_date} | {reference:35s}'
        f' | Netto {netto:8.2f} EUR'
    )


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True, help='Tryton-Datenbankname')
    parser.add_argument('--config', default=None, help='Pfad zur trytond.conf')
    args = parser.parse_args()

    cfg = connect(args.database, args.config)

    company = get_company()
    # Buchhaltungsmodelle benötigen company im Transaktionskontext
    cfg._context['company'] = company.id

    tax_19 = get_purchase_tax_19()
    acc_7680 = get_account('7680')  # Grundsteuer
    acc_5130 = get_account('5130')  # Kosten

    print(f'Verwende Steuer: {tax_19.name} (rate={tax_19.rate})')

    land_berlin = get_party('Land Berlin')
    allianz = get_party('Allianz AG')
    wasser = get_party('Berliner Wasserbetriebe')
    bsr = get_party('BSR')
    reinigung_mueller = get_party('Reinigung Müller GmbH')
    b_und_o = get_party('B&O GmbH')
    gartenpflege = get_party('Gartenpflege GaLa')
    schornsteinfeger = get_party('Schornsteinfeger Krüger')
    vailand = get_party('Vailand GmbH')
    vattenfall = get_party('Vattenfall GmbH')
    gasag = get_party('Gas AG')

    properties = get_properties()
    print(f'{len(properties)} Properties gefunden: {", ".join(p.name for p in properties)}')

    for prop in properties:
        tag = f'[{prop.name}]'
        print(f'\nLege Rechnungen an für: {prop.name} ...')

        su_100 = get_settlement_unit(100, prop)   # Grundsteuer
        su_110 = get_settlement_unit(110, prop)   # Gebäudeversicherung
        su_200 = get_settlement_unit(200, prop)   # Wasserkosten
        su_300 = get_settlement_unit(300, prop)   # Heizkosten
        su_310 = get_settlement_unit(310, prop)   # Heizung/Wartung
        su_500 = get_settlement_unit(500, prop)   # Straßenreinigung
        su_510 = get_settlement_unit(510, prop)   # Müll
        su_520 = get_settlement_unit(520, prop)   # Hausreinigung
        su_600 = get_settlement_unit(600, prop)   # Gartenpflege
        su_610 = get_settlement_unit(610, prop)   # Hausstrom
        su_620 = get_settlement_unit(620, prop)   # Schornsteinfeger
        su_700 = get_settlement_unit(700, prop)   # Hausmeister

        invoices_todo = []

        invoices_todo.append((
            datetime.date(2025, 3, 15), land_berlin,
            f'Grundsteuer 2025 {tag}',
            [{'description': 'Grundsteuer 2025', 'unit_price': Decimal('1890.00'),
              'account': acc_7680, 'taxes': [],
              'property': prop, 'settlement_unit': su_100}],
        ))

        invoices_todo.append((
            datetime.date(2025, 2, 15), allianz,
            f'Gebäudeversicherung 2025 {tag}',
            [{'description': 'Gebäudeversicherung 2025', 'unit_price': Decimal('7801.00'),
              'account': acc_5130, 'taxes': [tax_19],
              'property': prop, 'settlement_unit': su_110}],
        ))

        for month in [1, 3, 5, 7, 9, 11]:
            d = datetime.date(2025, month, 15)
            label = d.strftime('%m/%Y')
            invoices_todo.append((
                d, wasser,
                f'Wasserrechnung {label} {tag}',
                [{'description': f'Wasserrechnung {label}', 'unit_price': Decimal('2166.00'),
                  'account': acc_5130, 'taxes': [tax_19],
                  'property': prop, 'settlement_unit': su_200}],
            ))
            invoices_todo.append((
                d, gasag,
                f'Gasrechnung {label} {tag}',
                [{'description': f'Gasrechnung {label}', 'unit_price': Decimal('660.00'),
                  'account': acc_5130, 'taxes': [tax_19],
                  'property': prop, 'settlement_unit': su_300}],
            ))

        for month in [1, 3, 5, 7, 9, 11]:
            d = datetime.date(2025, month, 15)
            label = d.strftime('%m/%Y')
            invoices_todo.append((
                d, bsr,
                f'BSR {label} {tag}',
                [
                    {'description': 'Straßenreinigung', 'unit_price': Decimal('433.00'),
                     'account': acc_5130, 'taxes': [tax_19],
                     'property': prop, 'settlement_unit': su_500},
                    {'description': 'Müll', 'unit_price': Decimal('541.00'),
                     'account': acc_5130, 'taxes': [tax_19],
                     'property': prop, 'settlement_unit': su_510},
                ],
            ))
            invoices_todo.append((
                d, vattenfall,
                f'Vattenfall {label} {tag}',
                [
                    {'description': 'Hausstrom', 'unit_price': Decimal('650.00'),
                     'account': acc_5130, 'taxes': [tax_19],
                     'property': prop, 'settlement_unit': su_610},
                ],
            ))

        for month in [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]:
            d = datetime.date(2025, month, 25)
            label = d.strftime('%m/%Y')
            invoices_todo.append((
                d, reinigung_mueller,
                f'Reinigung {label} {tag}',
                [
                    {'description': 'Hausreinigung', 'unit_price': Decimal('431.00'),
                     'account': acc_5130, 'taxes': [tax_19],
                     'property': prop, 'settlement_unit': su_520},
                ],
            ))
            invoices_todo.append((
                d, b_und_o,
                f'Hausmeister {label} {tag}',
                [
                    {'description': 'Hausmeister', 'unit_price': Decimal('758.00'),
                     'account': acc_5130, 'taxes': [tax_19],
                     'property': prop, 'settlement_unit': su_700},
                ],
            ))

        invoices_todo.append((
            datetime.date(2025, 2, 15), gartenpflege,
            f'Gartenpflege 2025 {tag}',
            [{'description': 'Gartenpflege 2025', 'unit_price': Decimal('3250.00'),
              'account': acc_5130, 'taxes': [tax_19],
              'property': prop, 'settlement_unit': su_600}],
        ))

        invoices_todo.append((
            datetime.date(2025, 11, 15), schornsteinfeger,
            f'Schornsteinfeger 2025 {tag}',
            [{'description': 'Schornsteinfeger 2025', 'unit_price': Decimal('1950.00'),
              'account': acc_5130, 'taxes': [tax_19],
              'property': prop, 'settlement_unit': su_620}],
        ))

        invoices_todo.append((
            datetime.date(2025, 11, 25), vailand,
            f'Vailand 2025 {tag}',
            [{'description': 'Vailand 2025', 'unit_price': Decimal('3860.00'),
              'account': acc_5130, 'taxes': [tax_19],
              'property': prop, 'settlement_unit': su_310}],
        ))

        invoices_todo.sort(key=lambda x: x[0])

        for invoice_date, party, reference, lines_data in invoices_todo:
            create_and_post_invoice(company, party, invoice_date, reference, lines_data)

    print('\nFertig.')


if __name__ == '__main__':
    main()
