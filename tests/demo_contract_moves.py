"""
Periodische Buchung der Verträge für einen Monat (Demodaten).

Zweck:
    Bucht die Verträge eines Monats über den Assistenten "Buchungen erzeugen"
    (real_estate.contract.create_moves.wizard), so wie ein Benutzer im Client:
    Datum "bis" = letzter Tag des Monats, Rechnungsdatum = erster Tag des
    Monats, Aktion "Neu berechnen und Buchungen erzeugen", ohne Warteschlange,
    ohne Filter (alle laufenden und gekündigten Verträge der Gesellschaft).
    Es entstehen die Ausgangsrechnungen des Monats (Vorgabe: gebucht), und die
    Cash-Flow-Zeilen der Konditionen bis zum Monatsende stehen auf gebucht.

Voraussetzungen:
    demo_immo.py und demo_contracts.py (laufende Verträge), Geschäftsjahr mit
    Perioden und Nummernkreisen für den Monat. Für die Abrechnung der
    Betriebskosten zusätzlich demo_billing_unit.py.

Ablauf je Monat (monatlicher Demo-Ablauf):
    demo_contract_moves.py --year --month -> demo_invoices.py --year --month
    -> demo_payment.py --year --month

Ohne Warteschlange:
    execute_in_queue = False - der Assistent ruft Contract.create_moves direkt
    auf (Contract.call_create_moves), die Buchungen sind beim Ende des Skripts
    fertig; ein Queue-Worker wird nicht gebraucht.

Wiederholbarkeit:
    Ein zweiter Lauf für denselben Monat erzeugt keine doppelten Buchungen.
    Contract.create_moves bucht je Kondition nur Cash-Flow-Zeilen im Status
    Entwurf mit Belegdatum bis zum Datum "bis" und setzt sie auf gebucht; die
    Neuberechnung (ContractTerm.re_calc) baut die bereits gebuchten Zeilen aus
    den nicht stornierten Rechnungszeilen wieder als gebucht auf und plant
    nur Belegdaten nach dem letzten gebuchten. Ein Vertrag, dessen Ende vor
    dem Datum "bis" liegt, wird übersprungen - die Monate deshalb der Reihe
    nach buchen.

Verwendung:
    python tests/demo_contract_moves.py --database <Datenbankname> [--config <trytond.conf>] --month <1-12> [--year <Jahr>] [--state posted|draft]

    --year   Jahr des Monats (Vorgabe: aktuelles Jahr - 1)
    --month  Monat 1-12 (Pflicht)
    --state  Rechnungsstatus: posted (gebucht, Vorgabe) oder draft (Entwurf)
"""

import argparse
import calendar
import datetime
import sys

from proteus import Model, Wizard, config


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


def month_range(year: int, month: int):
    """First and last day of the month."""
    last_day = calendar.monthrange(year, month)[1]
    return datetime.date(year, month, 1), datetime.date(year, month, last_day)


def create_contract_moves(company, date_to, invoice_date, invoice_state):
    """Run the wizard 'Create Moves' once - as a user would in the client -
    and return its result form."""
    wizard = Wizard('real_estate.contract.create_moves.wizard')
    form = wizard.form
    form.company = company
    form.action = 're_calc_and_create'
    # on_change_date sets the invoice date to the first of a past month -
    # set it explicitly afterwards, so it also holds for the current month
    form.date = date_to
    form.invoice_date = invoice_date
    form.invoice_state = invoice_state
    form.execute_in_queue = False
    wizard.execute('confirm')
    print(f'  Passende Verträge: {wizard.form.contracts_count}')
    wizard.execute('create_moves')
    result = wizard.form
    values = {
        'contracts_count': result.contracts_count,
        'action': result.action,
        'mode': result.mode,
        'message': result.message,
        }
    wizard.execute('end')
    return values


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    default_year = datetime.date.today().year - 1
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--database', required=True, help='Tryton-Datenbankname')
    parser.add_argument('--config', default=None, help='Pfad zur trytond.conf')
    parser.add_argument('--year', type=int, default=default_year,
        help=f'Jahr des Monats (Default: aktuelles Jahr - 1 = {default_year})')
    parser.add_argument('--month', type=int, required=True,
        choices=range(1, 13), metavar='1-12', help='Monat (Pflicht)')
    parser.add_argument('--state', default='posted',
        choices=('posted', 'draft'),
        help='Rechnungsstatus: posted (gebucht, Default) oder draft (Entwurf)')
    args = parser.parse_args()

    first_day, last_day = month_range(args.year, args.month)
    state_label = {'posted': 'gebucht', 'draft': 'Entwurf'}[args.state]

    print(f'Datenbank:       {args.database}')
    print(f'Monat:           {first_day:%m/%Y} (bis {last_day:%d.%m.%Y}, '
          f'Rechnungsdatum {first_day:%d.%m.%Y})')
    print(f'Rechnungsstatus: {state_label} ({args.state})')

    cfg = connect(args.database, args.config)
    company = get_company()
    cfg._context['company'] = company.id
    print(f'Company:         {company.rec_name}')
    print()

    print('Buchungen erzeugen ...')
    try:
        result = create_contract_moves(
            company, last_day, first_day, args.state)
    except Exception as exc:
        print(f'ERROR: Buchungen erzeugen fehlgeschlagen: {exc}',
            file=sys.stderr)
        sys.exit(1)

    print(f'  Verträge:      {result["contracts_count"]}')
    print(f'  Aktion:        {result["action"]}')
    print(f'  Ausführung:    {result["mode"]}')
    if result['message']:
        print('  Meldung:')
        for line in result['message'].splitlines():
            print(f'    {line}')
    print('\nFertig.')


if __name__ == '__main__':
    main()
