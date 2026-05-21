"""
Kreditoren-Rechnungen (Lieferantenrechnungen) für Demodaten anlegen und buchen.

Voraussetzung: Die Kreditoren aus test_kreditor.py müssen bereits vorhanden sein.

Das Skript legt folgende Rechnungen an und bucht sie (state=posted):

  Land Berlin — 1 Rechnung:
    - Datum: 15.03.2026
    - Position: "Grundsteuer 2026", 1 × 1.890,00 EUR, ohne Steuer
    - Konto: 7680 (Grundsteuer)

  Berliner Wasserbetriebe — 5 Rechnungen, monatlich zum 15. (Jan–Mai 2026):
    - Position: "Wasserrechnung MM/YYYY", 1 × 261,00 EUR + 19 % VSt
    - Konto: 5130

  BSR — 3 Rechnungen, alle 2 Monate zum 15. (Jan, Mrz, Mai 2026):
    - Position 1: "Straßenreinigung", 1 × 45,00 EUR + 19 % VSt, Konto 5130
    - Position 2: "Müll",             1 × 65,00 EUR + 19 % VSt, Konto 5130

Das Skript ist idempotent: es bricht ab, wenn bereits eine Lieferantenrechnung
für "Land Berlin" in der Datenbank vorhanden ist.

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


def get_property():
    BaseObject = Model.get('real_estate.base_object')
    results = BaseObject.find([
        ('sequence', '=', 10),
        ('type', '=', 'property'),
    ])
    if not results:
        print('ERROR: Property mit Sequence 10 nicht gefunden. Bitte zuerst test_immo.py ausführen.',
              file=sys.stderr)
        sys.exit(1)
    return results[0]


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
    acc_7680 = get_account('7680')
    acc_5130 = get_account('5130')

    prop = get_property()
    su_100 = get_settlement_unit(100, prop)   # Grundsteuer
    su_200 = get_settlement_unit(200, prop)   # Wasserkosten
    su_500 = get_settlement_unit(500, prop)   # Straßenreinigung
    su_510 = get_settlement_unit(510, prop)   # Müll

    print(f'Verwende Steuer: {tax_19.name} (rate={tax_19.rate})')

    land_berlin = get_party('Land Berlin')
    wasser = get_party('Berliner Wasserbetriebe')
    bsr = get_party('BSR')

    # Alle Rechnungen als Liste aufbauen und chronologisch sortieren
    invoices_todo = []

    invoices_todo.append((
        datetime.date(2026, 3, 15), land_berlin,
        'Grundsteuer 2026',
        [{'description': 'Grundsteuer 2026', 'unit_price': Decimal('1890.00'),
          'account': acc_7680, 'taxes': [],
          'property': prop, 'settlement_unit': su_100}],
    ))

    for month in range(1, 6):
        d = datetime.date(2026, month, 15)
        label = d.strftime('%m/%Y')
        invoices_todo.append((
            d, wasser,
            f'Wasserrechnung {label}',
            [{'description': f'Wasserrechnung {label}', 'unit_price': Decimal('261.00'),
              'account': acc_5130, 'taxes': [tax_19],
              'property': prop, 'settlement_unit': su_200}],
        ))

    for month in [1, 3, 5]:
        d = datetime.date(2026, month, 15)
        label = d.strftime('%m/%Y')
        invoices_todo.append((
            d, bsr,
            f'BSR {label}',
            [
                {'description': 'Straßenreinigung', 'unit_price': Decimal('45.00'),
                 'account': acc_5130, 'taxes': [tax_19],
                 'property': prop, 'settlement_unit': su_500},
                {'description': 'Müll', 'unit_price': Decimal('65.00'),
                 'account': acc_5130, 'taxes': [tax_19],
                 'property': prop, 'settlement_unit': su_510},
            ],
        ))

    invoices_todo.sort(key=lambda x: x[0])

    print('Lege Rechnungen an ...')
    for invoice_date, party, reference, lines_data in invoices_todo:
        create_and_post_invoice(company, party, invoice_date, reference, lines_data)

    print('Fertig.')


if __name__ == '__main__':
    main()
