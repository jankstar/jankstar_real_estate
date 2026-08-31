"""
Kreditoren-Rechnungen (Lieferantenrechnungen) für Demodaten anlegen und buchen.

Voraussetzung: Die Kreditoren aus test_kreditor.py müssen bereits vorhanden sein
sowie test_immo.py und test_billing_unit.py (für Settlement-Unit-Zuordnung).

Das Skript legt folgende Rechnungen an und bucht sie (state=posted). Alle
Daten liegen im gewählten Kalenderjahr (Parameter --year, Default 2025):

  Land Berlin — 1 Rechnung:
    - Datum: 15.03.<year>
    - Position: "Grundsteuer <year>", 1 × 1.890,00 EUR, ohne Steuer
    - Konto: 8910 (Grundsteuer), Settlement Unit 100

  Allianz AG — 1 Rechnung:
    - Datum: 15.02.<year>
    - Position: "Gebäudeversicherung <year>", 1 × 7.801,00 EUR + 19 % VSt
    - Konto: 8020 (Andere Betriebskosten), Settlement Unit 110

  Berliner Wasserbetriebe — 6 Rechnungen, 2-monatlich zum 15. (Jan–Nov):
    - Position: "Wasserrechnung MM/YYYY", 1 × 2.166,00 EUR + 19 % VSt
    - Konto: 8020 (Andere Betriebskosten), Settlement Unit 200

  Gas AG — 6 Rechnungen, 2-monatlich zum 15. (Jan–Nov):
    - Position: "Gasrechnung MM/YYYY", 1 × 39.650,00 EUR + 19 % VSt
    - Konto: 8020 (Andere Betriebskosten), Settlement Unit 300

  BSR — 6 Rechnungen, 2-monatlich zum 15. (Jan–Nov):
    - Position 1: "Straßenreinigung", 1 × 433,00 EUR + 19 % VSt, Settlement Unit 500
    - Position 2: "Müll",             1 × 541,00 EUR + 19 % VSt, Settlement Unit 510

  Vattenfall — 6 Rechnungen, 2-monatlich zum 15. (Jan–Nov):
    - Position: "Hausstrom", 1 × 650,00 EUR + 19 % VSt, Settlement Unit 610

  Reinigung Müller / B&O — je 12 Rechnungen, monatlich zum 25.:
    - Hausreinigung 431,00 EUR + 19 % VSt (Settlement Unit 520)
    - Hausmeister   758,00 EUR + 19 % VSt (Settlement Unit 700)

  Gartenpflege GaLa — 1 Rechnung 15.02.<year>, 3.250,00 EUR + 19 % VSt (SU 600)
  Schornsteinfeger Krüger — 1 Rechnung 15.11.<year>, 1.950,00 EUR + 19 % VSt (SU 620)
  Vailand GmbH — 1 Rechnung 25.11.<year>, 3.860,00 EUR + 19 % VSt (SU 310)

Das Skript ist idempotent: bereits vorhandene Rechnungen (gleiche Party,
Datum und Referenz) werden übersprungen. Die Referenz enthält jeweils den
Property-Namen in eckigen Klammern, z.B. "Grundsteuer 2025 [Musterstraße 1-4]".
Da die Referenz das Jahr enthält, kann das Skript für ein weiteres Jahr
(z.B. --year 2026) erneut ausgeführt werden, ohne die Rechnungen des
Vorjahres zu duplizieren oder zu berühren — vorausgesetzt, es existiert
für dieses Jahr bereits eine passende Billing Unit je Cost Type
(siehe test_billing_unit.py bzw. "Duplicate for Next Period").

Verwendung:
    python tests/test_invoices.py --database <Datenbankname> [--config <trytond.conf>] [--year <Jahr>]
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


def get_settlement_unit(sequence: int, prop, invoice_date: datetime.date):
    """Findet die Settlement Unit, deren Billing Unit den invoice_date abdeckt.

    Ein Cost Type (sequence) kann je Property über mehrere Jahre hinweg
    mehrere Billing Units haben (z.B. 2025 und 2026) — daher muss zusätzlich
    zu sequence/property/state auch der Gültigkeitszeitraum der Billing Unit
    (start_date..end_date, per Modell immer exakt ein Jahr) zum Rechnungs-
    datum passen, sonst würde find()[0] beliebig eine davon treffen.
    """
    SettlementUnit = Model.get('real_estate.settlement_unit')
    results = SettlementUnit.find([
        ('sequence', '=', sequence),
        ('billing_unit.property', '=', prop.id),
        ('billing_unit.state', 'not in', ['draft', 'billed']),
        ('billing_unit.start_date', '<=', invoice_date),
        ('billing_unit.end_date', '>=', invoice_date),
    ])
    if not results:
        print(f'  WARNUNG: Settlement Unit Sequence {sequence} für Property {prop.name}'
              f' zum Datum {invoice_date} nicht gefunden (keine Billing Unit mit'
              f' passendem Zeitraum und Status draft/billed) — Feld wird nicht gesetzt.')
        return None
    if len(results) > 1:
        print(f'  WARNUNG: Settlement Unit Sequence {sequence} für Property {prop.name}'
              f' zum Datum {invoice_date} ist mehrdeutig ({len(results)} Treffer) —'
              f' verwende die erste.')
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
        property (optional), settlement_unit (optional).
    Ist settlement_unit gesetzt, wird billing_unit automatisch aus
    settlement_unit.billing_unit mit übernommen (InvoiceLine.validate()
    verlangt, dass beide gesetzt sind und zusammengehören).
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
        # if ld.get('property'):
        #     line.property = ld['property']
        if ld.get('settlement_unit'):
            line.settlement_unit = ld['settlement_unit']
            line.billing_unit = ld['settlement_unit'].billing_unit
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
    parser.add_argument('--year', type=int, default=2025,
        help='Kalenderjahr für alle Rechnungsdaten (Default: 2025)')
    args = parser.parse_args()
    year = args.year

    cfg = connect(args.database, args.config)

    company = get_company()
    # Buchhaltungsmodelle benötigen company im Transaktionskontext
    cfg._context['company'] = company.id

    tax_19 = get_purchase_tax_19()
    acc_grundsteuer = get_account('8910')  # Grundsteuer
    acc_kosten = get_account('8020')  # Kosten (Andere Betriebskosten)

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

        # Settlement Unit je Zeile wird jetzt individuell zum Rechnungsdatum
        # ermittelt (nicht mehr einmal pauschal je Property), da ein Cost
        # Type über mehrere Jahre hinweg mehrere Billing Units haben kann
        # (z.B. Grundsteuer Sequence 100 in 2025 und 2026).
        def su(sequence: int, invoice_date: datetime.date):
            return get_settlement_unit(sequence, prop, invoice_date)

        invoices_todo = []

        d = datetime.date(year, 3, 15)
        invoices_todo.append((
            d, land_berlin,
            f'Grundsteuer {year} {tag}',
            [{'description': f'Grundsteuer {year}', 'unit_price': Decimal('1890.00'),
              'account': acc_grundsteuer, 'taxes': [],
              'property': prop, 'settlement_unit': su(100, d)}],
        ))

        d = datetime.date(year, 2, 15)
        invoices_todo.append((
            d, allianz,
            f'Gebäudeversicherung {year} {tag}',
            [{'description': f'Gebäudeversicherung {year}', 'unit_price': Decimal('7801.00'),
              'account': acc_kosten, 'taxes': [tax_19],
              'property': prop, 'settlement_unit': su(110, d)}],
        ))

        for month in [1, 3, 5, 7, 9, 11]:
            d = datetime.date(year, month, 15)
            label = d.strftime('%m/%Y')
            invoices_todo.append((
                d, wasser,
                f'Wasserrechnung {label} {tag}',
                [{'description': f'Wasserrechnung {label}', 'unit_price': Decimal('2166.00'),
                  'account': acc_kosten, 'taxes': [tax_19],
                  'property': prop, 'settlement_unit': su(200, d)}],
            ))
            invoices_todo.append((
                d, gasag,
                f'Gasrechnung {label} {tag}',
                [{'description': f'Gasrechnung {label}', 'unit_price': Decimal('6630.00'),
                  'account': acc_kosten, 'taxes': [tax_19],
                  'property': prop, 'settlement_unit': su(300, d)}],
            ))

        for month in [1, 3, 5, 7, 9, 11]:
            d = datetime.date(year, month, 15)
            label = d.strftime('%m/%Y')
            invoices_todo.append((
                d, bsr,
                f'BSR {label} {tag}',
                [
                    {'description': 'Straßenreinigung', 'unit_price': Decimal('433.00'),
                     'account': acc_kosten, 'taxes': [tax_19],
                     'property': prop, 'settlement_unit': su(500, d)},
                    {'description': 'Müll', 'unit_price': Decimal('541.00'),
                     'account': acc_kosten, 'taxes': [tax_19],
                     'property': prop, 'settlement_unit': su(510, d)},
                ],
            ))
            invoices_todo.append((
                d, vattenfall,
                f'Vattenfall {label} {tag}',
                [
                    {'description': 'Hausstrom', 'unit_price': Decimal('650.00'),
                     'account': acc_kosten, 'taxes': [tax_19],
                     'property': prop, 'settlement_unit': su(610, d)},
                ],
            ))

        for month in [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]:
            d = datetime.date(year, month, 25)
            label = d.strftime('%m/%Y')
            invoices_todo.append((
                d, reinigung_mueller,
                f'Reinigung {label} {tag}',
                [
                    {'description': 'Hausreinigung', 'unit_price': Decimal('431.00'),
                     'account': acc_kosten, 'taxes': [tax_19],
                     'property': prop, 'settlement_unit': su(520, d)},
                ],
            ))
            invoices_todo.append((
                d, b_und_o,
                f'Hausmeister {label} {tag}',
                [
                    {'description': 'Hausmeister', 'unit_price': Decimal('758.00'),
                     'account': acc_kosten, 'taxes': [tax_19],
                     'property': prop, 'settlement_unit': su(700, d)},
                ],
            ))

        d = datetime.date(year, 2, 15)
        invoices_todo.append((
            d, gartenpflege,
            f'Gartenpflege {year} {tag}',
            [{'description': f'Gartenpflege {year}', 'unit_price': Decimal('3250.00'),
              'account': acc_kosten, 'taxes': [tax_19],
              'property': prop, 'settlement_unit': su(600, d)}],
        ))

        d = datetime.date(year, 11, 15)
        invoices_todo.append((
            d, schornsteinfeger,
            f'Schornsteinfeger {year} {tag}',
            [{'description': f'Schornsteinfeger {year}', 'unit_price': Decimal('1950.00'),
              'account': acc_kosten, 'taxes': [tax_19],
              'property': prop, 'settlement_unit': su(620, d)}],
        ))

        d = datetime.date(year, 11, 25)
        invoices_todo.append((
            d, vailand,
            f'Vailand {year} {tag}',
            [{'description': f'Vailand {year}', 'unit_price': Decimal('3860.00'),
              'account': acc_kosten, 'taxes': [tax_19],
              'property': prop, 'settlement_unit': su(310, d)}],
        ))

        invoices_todo.sort(key=lambda x: x[0])

        for invoice_date, party, reference, lines_data in invoices_todo:
            create_and_post_invoice(company, party, invoice_date, reference, lines_data)

    print('\nFertig.')


if __name__ == '__main__':
    main()
