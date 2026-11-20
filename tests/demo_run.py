"""
Ablaufskript für die Demodaten: startet die Skripte demo_*.py nacheinander.

Zweck:
    Baut die Demodaten auf einer neuen Datenbank in einem festen Ablauf auf -
    erst die Stammdaten, dann Monat für Monat periodische Buchung,
    Eingangsrechnungen und Zahlungen, danach die Mietspiegel-Zuordnung und
    optional die Modernisierung. Jeder Schritt läuft als eigener Prozess mit
    demselben Python (sys.executable), die Ausgabe des Skripts läuft durch.

Voraussetzungen (von Hand, bis demo_setup.py existiert):
    Datenbank mit aktiviertem Modul real_estate, Gesellschaft, Kontenrahmen,
    Geschäftsjahr mit Perioden und Nummernkreisen für die gebuchten Monate,
    Konten an den Kostenarten (Grundsteuer 8910, Heizung 8002, übrige 8000).

Ablauf (Schrittnamen für --only/--skip):
    Stammdaten:    kreditor, immo, contracts, billing_unit
    je Monat von --from bis --to, Monat für Monat:
                   contract_moves, invoices, payment
                   (jeweils mit --year/--month des Monats)
    danach:        rent_survey, modernisation (nur mit --modernisation oder
                   in --only)

    Die Stammdaten-Skripte und rent_survey erhalten --year = Startjahr
    (demo_kreditor.py und demo_modernisation.py haben kein --year). Die
    Monate laufen der Reihe nach, weil die periodische Buchung einen Vertrag
    mit Ende vor dem gebuchten Monat überspringt.

Parameter:
    --database          Datenbank (Pflicht)
    --config            trytond.conf (optional, wird weitergereicht)
    --year              Startjahr (Vorgabe: aktuelles Jahr - 1)
    --from, --to        Monate im Format JJJJ-MM (Vorgabe: Januar bis
                        Dezember des Startjahres); --from <= --to
    --only, --skip      kommagetrennte Schrittnamen (nicht beide zugleich)
    --modernisation     demo_modernisation.py am Ende mitlaufen lassen
    --execute           an demo_modernisation.py weiterreichen
    --continue-on-error nach einem Fehler weitermachen (Vorgabe: Abbruch
                        beim ersten Fehler)
    --dry-run           nur die Befehle in der Reihenfolge ausgeben

Monate nach dem Startjahr:
    zulässig. Eingangsrechnungen finden aber nur Kostensammler, wenn für das
    Jahr Abrechnungseinheiten bestehen (demo_billing_unit.py legt sie für das
    Startjahr an, sonst "Duplicate for Next Period"); demo_invoices.py warnt
    dann und lässt die Belege offen.

Exit-Codes der Skripte:
    0 = ausgeführt, 1 = Fehler, 2 = falscher Aufruf (argparse),
    3 = Daten vorhanden, nichts angelegt (Stammdaten-Skripte, EXIT_EXISTS).
    demo_run.py zeigt 3 als "übersprungen (Daten vorhanden)", wertet es
    nicht als Fehler und läuft weiter.

Wiederholbarkeit:
    Die Stammdaten-Skripte brechen ab, wenn ihre Daten schon vorhanden sind
    ("... existiert bereits. Abbruch (Exit-Code 3).") - demo_run.py zeigt
    den Schritt als übersprungen und läuft weiter. Ein erneuter Lauf, z. B.
    für weitere Monate, geht daher ohne --skip; die Stammdaten mit
    --skip kreditor,immo,contracts,billing_unit auszulassen, bleibt möglich
    (spart die Verbindungen). Die Monatsschritte sind wiederholbar: contract_moves bucht nichts
    doppelt, invoices überspringt vorhandene Rechnungen, payment zahlt nur
    offene Posten. rent_survey überspringt vorhandene Zuordnungen,
    modernisation bricht ab, wenn die Maßnahme existiert.

Verwendung:
    python tests/demo_run.py --database <Datenbankname> [--config <trytond.conf>] [--year <Startjahr>]
        [--from JJJJ-MM] [--to JJJJ-MM] [--only <Schritte> | --skip <Schritte>]
        [--modernisation [--execute]] [--continue-on-error] [--dry-run]

Beispiele (Startjahr 2025):
    python tests/demo_run.py --database demo
    python tests/demo_run.py --database demo --to 2025-03
    python tests/demo_run.py --database demo --from 2025-04 --to 2025-06 \\
        --skip kreditor,immo,contracts,billing_unit,rent_survey
    python tests/demo_run.py --database demo --dry-run
"""

import argparse
import datetime
import os
import re
import shlex
import subprocess
import sys
import time

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))

# Exit code of a script: data exist, nothing created (see EXIT_EXISTS in the
# master data scripts) - shown as skipped, no error
EXIT_EXISTS = 3
STATUS = {0: 'ok', EXIT_EXISTS: 'übersprungen (Daten vorhanden)'}

MASTER_STEPS = ['kreditor', 'immo', 'contracts', 'billing_unit']
MONTH_STEPS = ['contract_moves', 'invoices', 'payment']
FINAL_STEPS = ['rent_survey', 'modernisation']
ALL_STEPS = MASTER_STEPS + MONTH_STEPS + FINAL_STEPS

# Script per step and whether it takes the start year (--year)
SCRIPTS = {
    'kreditor': ('demo_kreditor.py', False),
    'immo': ('demo_immo.py', True),
    'contracts': ('demo_contracts.py', True),
    'billing_unit': ('demo_billing_unit.py', True),
    'contract_moves': ('demo_contract_moves.py', None),
    'invoices': ('demo_invoices.py', None),
    'payment': ('demo_payment.py', None),
    'rent_survey': ('demo_rent_survey.py', True),
    'modernisation': ('demo_modernisation.py', False),
    }


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def parse_month(value: str):
    """'JJJJ-MM' -> (year, month)."""
    match = re.fullmatch(r'(\d{4})-(\d{2})', value or '')
    if not match or not 1 <= int(match.group(2)) <= 12:
        raise argparse.ArgumentTypeError(
            f'"{value}" ist kein Monat im Format JJJJ-MM')
    return int(match.group(1)), int(match.group(2))


def parse_steps(value: str):
    names = [n.strip() for n in value.split(',') if n.strip()]
    unknown = [n for n in names if n not in ALL_STEPS]
    if unknown:
        raise argparse.ArgumentTypeError(
            f'unbekannte Schritte: {", ".join(unknown)} '
            f'(möglich: {", ".join(ALL_STEPS)})')
    return names


def months(first, last):
    """All (year, month) from first to last, both included."""
    year, month = first
    while (year, month) <= last:
        yield year, month
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def build_steps(args):
    """List of (label, step name, command, hint) in the order of the run."""
    def selected(name):
        if args.only:
            return name in args.only
        if name in (args.skip or []):
            return False
        if name == 'modernisation':
            return args.modernisation
        return True

    def command(name, year=None, month=None):
        script, start_year = SCRIPTS[name]
        cmd = [sys.executable, os.path.join(TESTS_DIR, script),
            '--database', args.database]
        if args.config:
            cmd += ['--config', args.config]
        if start_year:
            cmd += ['--year', str(args.year)]
        if month is not None:
            cmd += ['--year', str(year), '--month', str(month)]
        if name == 'modernisation' and args.execute:
            cmd.append('--execute')
        return cmd

    steps = []
    for name in MASTER_STEPS:
        if selected(name):
            steps.append((name, name, command(name), None))
    for year, month in months(args.from_, args.to):
        for name in MONTH_STEPS:
            if not selected(name):
                continue
            hint = None
            if name == 'invoices' and year > args.year:
                hint = (f'Hinweis: {year} liegt nach dem Startjahr '
                    f'{args.year} - Eingangsrechnungen finden nur '
                    f'Kostensammler, wenn für {year} Abrechnungseinheiten '
                    f'bestehen (sonst warnt demo_invoices.py).')
            steps.append((f'{name} {year}-{month:02d}', name,
                    command(name, year, month), hint))
    for name in FINAL_STEPS:
        if selected(name):
            steps.append((name, name, command(name), None))
    return steps


def show(cmd):
    """Command for the output, with the script path relative to the cwd."""
    shown = [os.path.basename(cmd[0])] + [
        os.path.relpath(c) if c.endswith('.py') else c for c in cmd[1:]]
    return ' '.join(shlex.quote(c) for c in shown)


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
        help=f'Startjahr der Demodaten (Default: aktuelles Jahr - 1 = '
             f'{default_year})')
    parser.add_argument('--from', dest='from_', type=parse_month,
        default=None, metavar='JJJJ-MM',
        help='erster Monat (Default: Januar des Startjahres)')
    parser.add_argument('--to', type=parse_month, default=None,
        metavar='JJJJ-MM',
        help='letzter Monat (Default: Dezember des Startjahres)')
    parser.add_argument('--only', type=parse_steps, default=None,
        metavar='SCHRITTE', help='nur diese Schritte (kommagetrennt)')
    parser.add_argument('--skip', type=parse_steps, default=None,
        metavar='SCHRITTE', help='diese Schritte auslassen (kommagetrennt)')
    parser.add_argument('--modernisation', action='store_true',
        help='demo_modernisation.py am Ende mitlaufen lassen')
    parser.add_argument('--execute', action='store_true',
        help='an demo_modernisation.py weiterreichen')
    parser.add_argument('--continue-on-error', action='store_true',
        help='nach einem Fehler mit dem nächsten Schritt weitermachen')
    parser.add_argument('--dry-run', action='store_true',
        help='nur die Befehle ausgeben, nichts starten')
    args = parser.parse_args()

    if args.only and args.skip:
        parser.error('--only und --skip nicht zugleich')
    args.from_ = args.from_ or (args.year, 1)
    args.to = args.to or (args.year, 12)
    if args.from_ > args.to:
        parser.error('--from liegt nach --to')
    runs_modernisation = (
        ('modernisation' in args.only) if args.only
        else args.modernisation and 'modernisation' not in (args.skip or []))
    if args.execute and not runs_modernisation:
        parser.error('--execute nur zusammen mit dem Schritt modernisation')

    steps = build_steps(args)
    print(f'Datenbank:  {args.database}')
    print(f'Startjahr:  {args.year}')
    print(f'Monate:     {args.from_[0]}-{args.from_[1]:02d} bis '
          f'{args.to[0]}-{args.to[1]:02d}')
    print(f'Schritte:   {len(steps)}'
          + (' (nur Ausgabe der Befehle)' if args.dry_run else ''))

    if args.dry_run:
        print()
        for i, (label, _, cmd, hint) in enumerate(steps, 1):
            print(f'[{i:3d}] {label:22} {show(cmd)}')
            if hint:
                print(f'      {hint}')
        return

    results = []
    failed = False
    for i, (label, _, cmd, hint) in enumerate(steps, 1):
        if failed and not args.continue_on_error:
            results.append((label, 'nicht gestartet', None, None))
            continue
        print(f'\n{"=" * 78}\n[{i}/{len(steps)}] {label}: {show(cmd)}\n'
              f'{"=" * 78}', flush=True)
        if hint:
            print(hint, flush=True)
        start = time.monotonic()
        code = subprocess.run(cmd).returncode
        duration = time.monotonic() - start
        status = STATUS.get(code, 'Fehler')
        print(f'--- {label}: {status}, Exit-Code {code}, {duration:.1f} s',
            flush=True)
        results.append((label, status, code, duration))
        if code not in STATUS:
            failed = True

    print(f'\n{"=" * 78}\nÜbersicht\n{"=" * 78}')
    for label, status, code, duration in results:
        detail = (f'Exit-Code {code}, {duration:.1f} s'
            if code is not None else '')
        print(f'  {label:22} {status:31} {detail}')
    if failed:
        print('\nMindestens ein Schritt ist fehlgeschlagen.')
        sys.exit(1)
    print('\nAlle Schritte ok bzw. übersprungen.')


if __name__ == '__main__':
    main()
