"""
Offene Forderungen der Testmieter/Gewerbemieter als Zahlungseingang und offene
Verbindlichkeiten der Testkreditoren als Zahlungsausgang buchen und
ausgleichen.

Buchungssatz Forderungen (Zahlungseingang) je Vertragspartner:
    Soll 2740 Bank  an  Haben <Forderungskonto> + Partner

Buchungssatz Verbindlichkeiten (Zahlungsausgang) je Kreditor:
    Soll <Verbindlichkeitenkonto> + Partner  an  Haben 2740 Bank

Beide Konten werden automatisch aus den offenen Buchungszeilen ermittelt
(account.type.receivable bzw. account.type.payable = True). Nach dem Buchen
werden jeweils alle offenen Posten auf dem Partnerkonto ausgeglichen
(reconcile).

Das Skript ist idempotent: Parteien ohne offene Forderungs-/
Verbindlichkeitszeilen werden übersprungen.

Voraussetzung Forderungen: test_contracts.py muss ausgeführt worden sein und
der Wizard "CreateContractMoves" muss mindestens einmal gelaufen sein, sodass
gebuchte (posted) Ausgangsrechnungen für die Testpartner vorhanden sind.

Voraussetzung Verbindlichkeiten: test_kreditor.py und test_invoices.py müssen
ausgeführt worden sein; die von test_invoices.py angelegten Rechnungen bleiben
im Status "draft" und müssen vor diesem Skript manuell gebucht (posted)
werden, sonst existieren keine offenen Verbindlichkeitszeilen.

Verwendung:
    python tests/test_payment.py --database <Datenbankname> [--config <trytond.conf>]
"""

import argparse
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


def get_account(code: str):
    Account = Model.get('account.account')
    results = Account.find([('code', '=', code)])
    if not results:
        print(f'ERROR: Konto mit Code "{code}" nicht gefunden.', file=sys.stderr)
        sys.exit(1)
    return results[0]


def get_journal():
    Journal = Model.get('account.journal')
    for jtype in ('cash', 'statement', 'general'):
        results = Journal.find([('type', '=', jtype)])
        if results:
            return results[0]
    print('ERROR: Kein verwendbares Journal gefunden (cash/statement/general).',
          file=sys.stderr)
    sys.exit(1)


def get_period(date, company):
    Period = Model.get('account.period')
    periods = Period.find([
        ('start_date', '<=', date),
        ('end_date', '>=', date),
        ('fiscalyear.company', '=', company.id),
        ('type', '=', 'standard'),
    ])
    if not periods:
        print(f'ERROR: Keine Buchungsperiode für {date} gefunden.', file=sys.stderr)
        sys.exit(1)
    return periods[0]


def get_test_parties():
    Party = Model.get('party.party')
    parties = Party.find(
        ['OR',
            [('name', 'ilike', 'Mieter %')],
            [('name', 'ilike', 'Gewerbemieter %')],
        ],
        order=[('name', 'ASC')])
    if not parties:
        print('ERROR: Keine Testpartner ("Mieter N" / "Gewerbemieter N") gefunden. '
              'Bitte zuerst test_contracts.py ausführen.', file=sys.stderr)
        sys.exit(1)
    return parties


def get_open_receivable_lines(party):
    """Find all unreconciled posted receivable lines for a party."""
    MoveLine = Model.get('account.move.line')
    return MoveLine.find([
        ('party', '=', party.id),
        ('account.type.receivable', '=', True),
        ('reconciliation', '=', None),
        ('move.state', '=', 'posted'),
    ])


def get_open_payable_lines(party):
    """Find all unreconciled posted payable lines for a party."""
    MoveLine = Model.get('account.move.line')
    return MoveLine.find([
        ('party', '=', party.id),
        ('account.type.payable', '=', True),
        ('reconciliation', '=', None),
        ('move.state', '=', 'posted'),
    ])


def get_creditor_parties():
    """All parties that currently have at least one open (unreconciled,
    posted) payable move line."""
    MoveLine = Model.get('account.move.line')
    Party = Model.get('party.party')
    lines = MoveLine.find([
        ('account.type.payable', '=', True),
        ('reconciliation', '=', None),
        ('move.state', '=', 'posted'),
        ('party', '!=', None),
    ])
    party_ids = sorted({line.party.id for line in lines})
    if not party_ids:
        return []
    return Party.find([('id', 'in', party_ids)], order=[('name', 'ASC')])


# ---------------------------------------------------------------------------
# Buchung und Ausgleich
# ---------------------------------------------------------------------------

def book_payment(company, party, open_lines, acc_bank, journal):
    """
    Erstellt einen Buchungssatz Bank an Forderungen für den Mieter.
    Das Forderungskonto wird aus den offenen Zeilen ermittelt.
    Gibt die Haben-Zeile auf dem Forderungskonto zurück (für den Ausgleich).
    """
    Move = Model.get('account.move')
    MoveLine = Model.get('account.move.line')

    total = sum((line.debit - line.credit) for line in open_lines)
    if total <= Decimal('0'):
        print(f'  {party.name}: Saldo nicht positiv ({total:.2f}) — übersprungen.')
        return None, None

    # Receivable account from the open lines (all lines should share the same account)
    recv_account = open_lines[0].account

    payment_date = max(line.date for line in open_lines)
    period = get_period(payment_date, company)
    description = f'Zahlungseingang {party.name}'

    move = Move()
    move.company = company
    move.journal = journal
    move.date = payment_date
    move.period = period
    move.description = description
    move.save()

    bank_line = MoveLine()
    bank_line.move = move
    bank_line.account = acc_bank
    bank_line.debit = total
    bank_line.credit = Decimal('0')
    bank_line.description = description
    bank_line.save()

    recv_line = MoveLine()
    recv_line.move = move
    recv_line.account = recv_account
    recv_line.party = party
    recv_line.debit = Decimal('0')
    recv_line.credit = total
    recv_line.description = description
    recv_line.save()

    Move(move.id).click('post')

    posted_recv_lines = MoveLine.find([
        ('move', '=', move.id),
        ('account', '=', recv_account.id),
    ])
    if not posted_recv_lines:
        print(f'  ERROR: Haben-Zeile auf {recv_account.code} nach Buchung nicht gefunden '
              f'(Move id={move.id}).', file=sys.stderr)
        return None, None

    print(f'  Konto: {recv_account.code} {recv_account.name}')
    print(f'  Gebucht: {total:.2f} EUR am {payment_date} '
          f'(Move id={move.id}, Journal: {journal.name})')
    return posted_recv_lines[0], payment_date


def book_payable_payment(company, party, open_lines, acc_bank, journal):
    """
    Erstellt einen Buchungssatz Verbindlichkeiten an Bank für den Kreditor.
    Das Verbindlichkeitenkonto wird aus den offenen Zeilen ermittelt.
    Gibt die Soll-Zeile auf dem Verbindlichkeitenkonto zurück (für den
    Ausgleich).
    """
    Move = Model.get('account.move')
    MoveLine = Model.get('account.move.line')

    # A liability is a credit balance, opposite sign of a receivable.
    total = sum((line.credit - line.debit) for line in open_lines)
    if total <= Decimal('0'):
        print(f'  {party.name}: Saldo nicht positiv ({total:.2f}) — übersprungen.')
        return None, None

    # Payable account from the open lines (all lines should share the same account)
    payable_account = open_lines[0].account

    payment_date = max(line.date for line in open_lines)
    period = get_period(payment_date, company)
    description = f'Zahlungsausgang {party.name}'

    move = Move()
    move.company = company
    move.journal = journal
    move.date = payment_date
    move.period = period
    move.description = description
    move.save()

    payable_line = MoveLine()
    payable_line.move = move
    payable_line.account = payable_account
    payable_line.party = party
    payable_line.debit = total
    payable_line.credit = Decimal('0')
    payable_line.description = description
    payable_line.save()

    bank_line = MoveLine()
    bank_line.move = move
    bank_line.account = acc_bank
    bank_line.debit = Decimal('0')
    bank_line.credit = total
    bank_line.description = description
    bank_line.save()

    Move(move.id).click('post')

    posted_payable_lines = MoveLine.find([
        ('move', '=', move.id),
        ('account', '=', payable_account.id),
    ])
    if not posted_payable_lines:
        print(f'  ERROR: Soll-Zeile auf {payable_account.code} nach Buchung nicht gefunden '
              f'(Move id={move.id}).', file=sys.stderr)
        return None, None

    print(f'  Konto: {payable_account.code} {payable_account.name}')
    print(f'  Gebucht: {total:.2f} EUR am {payment_date} '
          f'(Move id={move.id}, Journal: {journal.name})')
    return posted_payable_lines[0], payment_date


def reconcile(open_lines, payment_line, date):
    Reconciliation = Model.get('account.move.reconciliation')
    MoveLine = Model.get('account.move.line')
    all_lines = [MoveLine(l.id) for l in open_lines] + [MoveLine(payment_line.id)]
    recon = Reconciliation()
    recon.date = date
    recon.lines.extend(all_lines)
    recon.save()


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
    cfg._context['company'] = company.id

    acc_bank = get_account('2740')
    journal = get_journal()

    tenants = get_test_parties()
    print(f'{len(tenants)} Testpartner gefunden (Mieter + Gewerbemieter). '
          f'Journal: {journal.name} ({journal.type})\n')

    booked = 0
    skipped = 0

    for party in tenants:
        open_lines = get_open_receivable_lines(party)
        if not open_lines:
            print(f'  {party.name}: keine offenen Forderungen — übersprungen.')
            skipped += 1
            continue

        total = sum((line.debit - line.credit) for line in open_lines)
        print(f'{party.name}: {len(open_lines)} offene Posten, Summe {total:.2f} EUR')

        payment_line, payment_date = book_payment(
            company, party, open_lines, acc_bank, journal,
        )
        if payment_line:
            reconcile(open_lines, payment_line, payment_date)
            print(f'  → Offene Posten ausgeglichen.')
            booked += 1
        else:
            skipped += 1

    print(f'\nForderungen fertig. Gebucht: {booked}, übersprungen: {skipped}.\n')

    creditors = get_creditor_parties()
    print(f'{len(creditors)} Kreditoren mit offenen Verbindlichkeiten gefunden.\n')

    booked_payable = 0
    skipped_payable = 0

    for party in creditors:
        open_lines = get_open_payable_lines(party)
        if not open_lines:
            print(f'  {party.name}: keine offenen Verbindlichkeiten — übersprungen.')
            skipped_payable += 1
            continue

        total = sum((line.credit - line.debit) for line in open_lines)
        print(f'{party.name}: {len(open_lines)} offene Posten, Summe {total:.2f} EUR')

        payment_line, payment_date = book_payable_payment(
            company, party, open_lines, acc_bank, journal,
        )
        if payment_line:
            reconcile(open_lines, payment_line, payment_date)
            print(f'  → Offene Posten ausgeglichen.')
            booked_payable += 1
        else:
            skipped_payable += 1

    print(f'\nVerbindlichkeiten fertig. Gebucht: {booked_payable}, '
          f'übersprungen: {skipped_payable}.')


if __name__ == '__main__':
    main()
