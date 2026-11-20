"""
Einstellungen einer neuen Datenbank für die Demodaten herstellen.

Zweck:
    Erster Schritt der Demodaten (demo_run.py, Schritt "setup"). Setzt die
    Einstellungen, die von der Gesellschaft abhängen und nicht mit den
    Daten-XML kommen, mit den Werten der Testdatenbank (Bestandsaufnahme
    S5a, specs/bloecke/Q8-demo-daten.md Kap. 4.5). Setzt nur leere Felder
    und legt nur Fehlendes an; ein abweichender vorhandener Wert bleibt und
    wird als Hinweis ausgegeben.

Voraussetzungen (von Hand):
    Datenbank mit aktiviertem Modul real_estate, Gesellschaft (ID 1, Partei
    ID 1, z. B. ImmoBau GmbH), Kontenrahmen aus der Vorlage
    "Kontenrahmen der Wohnungswirtschaft (WoWi)" (real_estate.wowi_root)
    für die Gesellschaft angelegt.

Prüfungen zu Beginn (Abbruch mit Exit-Code 1):
    P1  Gesellschaft ID 1 mit Partei ID 1.
    P2  Das Wurzelkonto der Gesellschaft hat die Vorlage real_estate.wowi_root.

Ablauf:
    E1  Partei der Gesellschaft: Konten Forderungen 2000 / Verbindlichkeiten
        4420, Steuerregeln Kunde/Lieferant "... Unternehmen in der EU (mit
        USt-ID)", Zahlungsbedingungen Kunde "03 Tage netto" / Lieferant
        "Net 15 days", Kunden- und Lieferantenwährung EUR, Sprache Deutsch,
        Anrede "Sehr geehrte Damen und Herren".
    E2  Gesellschaft: RE-Rechnungswesen = re_accounting_default.
    E3  Rechnungswesen / Einstellungen: Standardkonten Forderungen 2000,
        Verbindlichkeiten 4420, Ertrag 6000, Aufwand 8050.
    E4  Konto und Konto Abrechnungseinheit an den sechs Vertragsarten,
        Prozessvorlagen Einzug/Auszug/Mieterwechsel am Gewerbemietvertrag,
        Konto an den neun Konditionsarten, Konto je Kostenart (20),
        14 Aufgabenregeln aktiv, Gesellschaft an 16 Aufgabenregeln, sieben
        Cron-Aufträge an re_accounting_default, Gesellschaft am Cron
        "Immobilien: tägliche Aufgabe" (cron_real_estate_daily). Die Werte
        des Preisindex VPI-DE lädt demo_contracts.py (CSV-Datei und "Werte
        abrufen"); demo_setup.py braucht kein Netz.
    E4a Zuordnung Konditionsart <-> Vertragsart (15 Zuordnungen).
    E5  Strikte Nummernkreise, je Jahr fünf (Buchungssatz, Lieferantenrechnung,
        Kundenrechnung, Lieferantenrechnung Storno, Kundenrechnung Storno):
        Die fünf aus core/basic_de.xml (sequence_strict_10/20/30/29/39,
        Name "2025/<n> - ...", Präfix 25<n>) erhalten die Gesellschaft (nur
        wenn leer) und gelten für das Jahr in ihrem Namen. Für jedes übrige
        Jahr von Startjahr bis Startjahr + 2 legt das Skript fünf neue nach
        demselben Muster an: Name "<Jahr>/<n> - <Bezeichnung>", Präfix
        <JJ><n>, Polsterung 5, Schritt 1, gleicher Typ, Gesellschaft;
        vorhanden ist ein Nummernkreis, wenn einer mit diesem Namen und Typ
        für die Gesellschaft existiert.
    E6  Geschäftsjahre Startjahr bis Startjahr + 2: Name = Jahr,
        01.01.-31.12., Nummernkreis der Buchungen <Jahr>/1, eine Zeile
        Rechnungsnummernkreise ohne Periode (<Jahr>/2, /4, /3, /5), danach
        12 Monatsperioden (Standard create_period). Ein vorhandenes
        Geschäftsjahr bleibt; fehlen ihm Perioden oder Rechnungsnummernkreise,
        werden sie ergänzt.
    Der Benutzer admin wird nicht geändert.

    Datensätze aus den Daten-XML werden über ihre XML-ID gesucht
    (ir.model.data), Konten über ihre Nummer (code) in der Gesellschaft,
    Steuerregeln über ihre Vorlage, die Währung über den Code EUR, die
    Sprache über den Code de, Cron-Aufträge über ihre Aufgabe (task).

Verwendung:
    python tests/demo_setup.py --database <Datenbankname> [--config <trytond.conf>] [--year <Startjahr>]

    --year  Startjahr der Demodaten (Vorgabe: aktuelles Jahr - 1); Geschäftsjahre
            und Nummernkreise für Startjahr bis Startjahr + 2

Ausgabe:
    je Einstellung eine Zeile "angelegt", "gesetzt", "vorhanden" oder
    "Hinweis" (vorhandener Wert weicht ab oder Feld fehlt, bleibt
    unverändert).

Exit-Codes:
    0 = etwas angelegt oder gesetzt, 1 = Prüfung P1/P2 nicht erfüllt oder
    Fehler, 2 = falscher Aufruf (argparse), 3 = alles vorhanden, nichts
    angelegt oder gesetzt (EXIT_EXISTS; demo_run.py zeigt den Schritt als
    "übersprungen").
"""

import argparse
import datetime
import sys

from proteus import Model, config

# Exit code "everything exists, nothing created or set" (demo_run.py shows
# the step as skipped); 0 = done, 1 = error, 2 = wrong call (argparse)
EXIT_EXISTS = 3

COMPANY_ID = 1
MODULE = 'real_estate'

# E1: party of the company
PARTY_RECEIVABLE = '2000'
PARTY_PAYABLE = '4420'
PARTY_CUSTOMER_TAX_RULE = 'real_estate.wowi_tax_rule_sale_EU_USTID'
PARTY_SUPPLIER_TAX_RULE = 'real_estate.wowi_tax_rule_purchase_EU_USTID'
PARTY_CUSTOMER_PAYMENT_TERM = 'real_estate.payment_term_net3'
PARTY_SUPPLIER_PAYMENT_TERM = 'account_invoice.payment_term_net15'
PARTY_CURRENCY = 'EUR'
PARTY_LANG = 'de'
PARTY_SALUTATION = 'Sehr geehrte Damen und Herren'
PARTY_SALUTATION_DEFAULT_EN = 'Dear Sir or Madam'

# E3: default accounts of the accounting configuration
CONFIG_ACCOUNTS = [
    ('default_account_receivable', '2000'),
    ('default_account_payable', '4420'),
    ('default_category_account_revenue', '6000'),
    ('default_category_account_expense', '8050'),
    ]

# E4: contract types (XML id, party account, settlement account)
CONTRACT_TYPE_ACCOUNTS = [
    ('contract_rental_agreement_type', '2000', '6010'),
    ('contract_parking_space_lease_agreement_type', '2000', '6010'),
    ('contract_debit_costs_agreement_type', '2300', '6010'),
    ('contract_credit_costs_agreement_type', '4420', '8290'),
    ('contract_commercial_lease_agreement_type', '2000', '6010'),
    ('contract_condominium_fee_agreement_type', '2000', '6010'),
    ]
# E4: process templates of the commercial lease agreement
COMMERCIAL_PROCESS_TEMPLATES = [
    ('start_process_template', 'process_template_move_in'),
    ('termination_process_template', 'process_template_move_out'),
    ('partner_change_process_template', 'process_template_partner_change'),
    ]
# E4: term types (XML id, account)
TERM_TYPE_ACCOUNTS = [
    ('contract_term_type_apartment_rent', '6000'),
    ('contract_term_type_rent_reduction', '6090'),
    ('contract_term_type_subletting_surcharge', '6020'),
    ('contract_term_type_parking_space_rent', '6004'),
    ('contract_term_type_rent_deposit', '4391'),
    ('contract_term_type_operating_costs', '4310'),
    ('contract_term_type_heating_costs', '4310'),
    ('contract_term_type_commercial_rent', '6002'),
    ('contract_term_type_service_charge', '6000'),
    ]
# E4a: term type -> contract types
TERM_TYPE_CONTRACT_TYPES = [
    ('contract_term_type_apartment_rent', [
            'contract_rental_agreement_type']),
    ('contract_term_type_rent_reduction', [
            'contract_rental_agreement_type',
            'contract_parking_space_lease_agreement_type',
            'contract_commercial_lease_agreement_type']),
    ('contract_term_type_subletting_surcharge', [
            'contract_rental_agreement_type']),
    ('contract_term_type_parking_space_rent', [
            'contract_rental_agreement_type',
            'contract_parking_space_lease_agreement_type',
            'contract_debit_costs_agreement_type']),
    ('contract_term_type_rent_deposit', [
            'contract_rental_agreement_type']),
    ('contract_term_type_operating_costs', [
            'contract_rental_agreement_type',
            'contract_commercial_lease_agreement_type']),
    ('contract_term_type_heating_costs', [
            'contract_rental_agreement_type',
            'contract_commercial_lease_agreement_type']),
    ('contract_term_type_commercial_rent', [
            'contract_commercial_lease_agreement_type']),
    ('contract_term_type_service_charge', [
            'contract_condominium_fee_agreement_type']),
    ]
# E4: account per cost type (XML id, account)
COST_TYPE_ACCOUNTS = [
    ('cost_type_Grundsteuer', '8910'),
    ('cost_type_Gebäudeversicherung', '8000'),
    ('cost_type_Wasserversorgung', '8000'),
    ('cost_type_Heizung', '8002'),
    ('cost_type_Heizung_Wartung', '8002'),
    ('cost_type_warmwasser', '8002'),
    ('cost_type_Heizung_Warmwasser_verbunden', '8002'),
    ('cost_type_Aufzug', '8000'),
    ('cost_type_Sraßenreinigung', '8000'),
    ('cost_type_Muellabfuhr', '8000'),
    ('cost_type_Hausreinigung', '8000'),
    ('cost_type_Gartenpflege', '8000'),
    ('cost_type_Hausstrom', '8000'),
    ('cost_type_Schornsteinfeger', '8000'),
    ('cost_type_Hausmeister', '8000'),
    ('cost_type_Antennenanlage', '8000'),
    ('cost_type_Waeschepflege', '8000'),
    ('cost_type_Sonstiges', '8000'),
    ('cost_type_Verwaltungskosten', '8500'),
    ('cost_type_Instandhaltungsruecklage', '8050'),
    ]
# E4: task rules activated by hand in the test system (XML: inactive)
TASK_RULES_ACTIVE = ['v03', 'v08', 'm01', 'm05', 'm06', 'm07', 'm08',
    'b01', 'b02', 'o01', 'o03', 'o04', 'p01', 'p02']
# E4: task rules with the company (all except s02 and m09)
TASK_RULES_COMPANY = ['v02', 'v03', 'v07', 'v08', 'm01', 'm05', 'm06',
    'm07', 'm08', 'b01', 'b02', 'o01', 'o03', 'o04', 'p01', 'p02']
# E4: cron tasks of re_accounting_default (values as in the test system)
CRON_TASKS = [
    {'task': 'update_contract_status', 'interval_days': 1},
    {'task': 'update_contract_cash_flow', 'interval_months': 1},
    {'task': 'book_contract_cash_flow', 'interval_months': 1,
        'schedule_day_of_month': 25, 'invoice_state': 'posted'},
    {'task': 'update_option_rate', 'interval_months': 1,
        'schedule_day_of_month': 1},
    {'task': 'task_notify', 'interval_days': 1},
    {'task': 'task_rules', 'interval_days': 1},
    {'task': 'inspection_plans', 'interval_days': 1},
    ]
CRON_TASK_DEFAULTS = {'horizon_months_ahead': 1,
    'future_contracts_horizon_days': 60, 'invoice_state': 'draft'}

# E5: strict sequences of core/basic_de.xml (XML id, number in the name)
BASIC_SEQUENCES = [
    ('sequence_strict_10', 1),
    ('sequence_strict_20', 2),
    ('sequence_strict_30', 3),
    ('sequence_strict_29', 4),
    ('sequence_strict_39', 5),
    ]
# E6: invoice sequence fields -> number of the strict sequence
INVOICE_SEQUENCE_FIELDS = [
    ('in_invoice_sequence', 2),
    ('out_invoice_sequence', 3),
    ('in_credit_note_sequence', 4),
    ('out_credit_note_sequence', 5),
    ]

START_YEAR = datetime.date.today().year - 1


def set_start_year(year: int) -> None:
    global START_YEAR
    START_YEAR = year


# ---------------------------------------------------------------------------
# Verbindung und Ausgabe
# ---------------------------------------------------------------------------

def connect(database: str, cfg_file: str | None):
    if cfg_file:
        return config.set_trytond(database=database, config_file=cfg_file)
    return config.set_trytond(database=database)


class Report:
    """Collects the result of every setting."""

    def __init__(self):
        self.counts = {'angelegt': 0, 'gesetzt': 0, 'vorhanden': 0,
            'Hinweis': 0}

    def __call__(self, status, text):
        self.counts[status] += 1
        print(f'  {status:<10} {text}', flush=True)

    @property
    def changed(self):
        return self.counts['angelegt'] + self.counts['gesetzt']


report = Report()


def fail(message):
    print(f'ERROR: {message}', file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Suchen
# ---------------------------------------------------------------------------

def xml_record(model, xml_id):
    """Record of the data XML by its XML id ('module.fs_id' or fs_id of the
    module real_estate)."""
    if '.' not in xml_id:
        xml_id = f'{MODULE}.{xml_id}'
    ModelData = Model.get('ir.model.data')
    try:
        db_id = ModelData.get_id(xml_id, config.get_config().context)
    except Exception:
        fail(f'Datensatz {xml_id} ({model}) nicht gefunden - Modul '
            f'aktuell? (trytond-admin -u real_estate)')
    return Model.get(model)(db_id)


_accounts = {}


def account(code, company):
    if code not in _accounts:
        Account = Model.get('account.account')
        found = Account.find([
                ('company', '=', company.id),
                ('code', '=', code),
                ])
        if len(found) != 1:
            fail(f'Konto {code} in der Gesellschaft '
                f'{"nicht gefunden" if not found else "mehrfach"}.')
        _accounts[code] = found[0]
    return _accounts[code]


def label(record):
    if record is None:
        return '-'
    if record.__class__.__name__ == 'account.account':
        return f'{record.code} {record.name}'
    return record.rec_name


def set_m2o(record, field, value, text):
    """Set a Many2One only if empty. Returns True if set (record must be
    saved by the caller)."""
    current = getattr(record, field)
    if current is None:
        setattr(record, field, value)
        report('gesetzt', f'{text}: {label(value)}')
        return True
    if current.id == value.id:
        report('vorhanden', f'{text}: {label(current)}')
    else:
        report('Hinweis', f'{text}: {label(current)} (Vorgabe '
            f'{label(value)}, unverändert)')
    return False


# ---------------------------------------------------------------------------
# P1 / P2
# ---------------------------------------------------------------------------

def check_prerequisites():
    print('Prüfungen')
    Company = Model.get('company.company')
    companies = Company.find([('id', '=', COMPANY_ID)])
    if not companies:
        fail('P1: keine Gesellschaft mit der ID 1.')
    company, = companies
    if company.party.id != 1:
        fail(f'P1: die Partei der Gesellschaft hat die ID {company.party.id}, '
            f'erwartet 1.')
    print(f'  P1 ok     Gesellschaft ID 1: {company.rec_name} (Partei ID 1)')
    Account = Model.get('account.account')
    roots = Account.find([
            ('company', '=', company.id),
            ('parent', '=', None),
            ])
    if not roots:
        fail('P2: die Gesellschaft hat keinen Kontenrahmen.')
    template = xml_record('account.account.template', 'wowi_root')
    if len(roots) != 1 or not roots[0].template \
            or roots[0].template.id != template.id:
        fail('P2: der Kontenrahmen der Gesellschaft stammt nicht aus der '
            'Vorlage "Kontenrahmen der Wohnungswirtschaft (WoWi)".')
    print(f'  P2 ok     Kontenrahmen: {roots[0].name}')
    return company


# ---------------------------------------------------------------------------
# E1 - E3
# ---------------------------------------------------------------------------

def setup_party(company):
    print('E1 Partei der Gesellschaft')
    Party = Model.get('party.party')
    party = Party(company.party.id)
    TaxRule = Model.get('account.tax.rule')
    Currency = Model.get('currency.currency')
    Lang = Model.get('ir.lang')

    def tax_rule(xml_id):
        template = xml_record('account.tax.rule.template', xml_id)
        rules = TaxRule.find([
                ('company', '=', company.id),
                ('template', '=', template.id),
                ])
        if not rules:
            fail(f'Steuerregel aus der Vorlage {template.name} nicht '
                f'gefunden.')
        return rules[0]

    currency, = Currency.find([('code', '=', PARTY_CURRENCY)])
    lang, = Lang.find([('code', '=', PARTY_LANG)])
    changed = False
    for field, value, text in [
            ('account_receivable', account(PARTY_RECEIVABLE, company),
                'Konto Forderungen'),
            ('account_payable', account(PARTY_PAYABLE, company),
                'Konto Verbindlichkeiten'),
            ('customer_tax_rule', tax_rule(PARTY_CUSTOMER_TAX_RULE),
                'Steuerregel Kunde'),
            ('supplier_tax_rule', tax_rule(PARTY_SUPPLIER_TAX_RULE),
                'Steuerregel Lieferant'),
            ('customer_payment_term', xml_record(
                    'account.invoice.payment_term',
                    PARTY_CUSTOMER_PAYMENT_TERM), 'Zahlungsbedingung Kunde'),
            ('supplier_payment_term', xml_record(
                    'account.invoice.payment_term',
                    PARTY_SUPPLIER_PAYMENT_TERM),
                'Zahlungsbedingung Lieferant'),
            ('customer_currency', currency, 'Kundenwährung'),
            ('supplier_currency', currency, 'Lieferantenwährung'),
            ('lang', lang, 'Sprache'),
            ]:
        if field not in party._fields:
            # customer/supplier currency come with the modules sale/purchase
            report('Hinweis', f'{text}: Feld {field} nicht vorhanden '
                '(Modul sale/purchase nicht aktiviert), übersprungen')
            continue
        changed |= set_m2o(party, field, value, text)
    # the module default (msg_salutation) in English counts as not set
    if party.salutation in (None, '', PARTY_SALUTATION_DEFAULT_EN):
        party.salutation = PARTY_SALUTATION
        report('gesetzt', f'Anrede: {PARTY_SALUTATION}')
        changed = True
    elif party.salutation == PARTY_SALUTATION:
        report('vorhanden', f'Anrede: {party.salutation}')
    else:
        report('Hinweis', f'Anrede: {party.salutation} (Vorgabe '
            f'{PARTY_SALUTATION}, unverändert)')
    if changed:
        party.save()


def setup_company(company):
    print('E2 Rechnungswesen der Gesellschaft')
    Company = Model.get('company.company')
    company = Company(company.id)
    re_accounting = xml_record('real_estate.re_accounting',
        're_accounting_default')
    if set_m2o(company, 're_accounting', re_accounting, 'RE-Rechnungswesen'):
        company.save()


def setup_account_configuration(company):
    print('E3 Rechnungswesen / Einstellungen')
    Configuration = Model.get('account.configuration')
    configuration = Configuration(1)
    changed = False
    names = {
        'default_account_receivable': 'Standardkonto Forderungen',
        'default_account_payable': 'Standardkonto Verbindlichkeiten',
        'default_category_account_revenue': 'Standardkonto Ertrag',
        'default_category_account_expense': 'Standardkonto Aufwand',
        }
    for field, code in CONFIG_ACCOUNTS:
        changed |= set_m2o(configuration, field, account(code, company),
            names[field])
    if changed:
        configuration.save()


# ---------------------------------------------------------------------------
# E4 / E4a
# ---------------------------------------------------------------------------

def setup_contract_types(company):
    print('E4 Vertragsarten')
    for xml_id, party_code, billing_code in CONTRACT_TYPE_ACCOUNTS:
        c_type = xml_record('real_estate.contract.type', xml_id)
        name = f'{c_type.name} ({c_type.sequence})'
        changed = set_m2o(c_type, 'account', account(party_code, company),
            f'{name}: Konto')
        changed |= set_m2o(c_type, 'account_billing_unit',
            account(billing_code, company),
            f'{name}: Konto Abrechnungseinheit')
        if xml_id == 'contract_commercial_lease_agreement_type':
            for field, template_id in COMMERCIAL_PROCESS_TEMPLATES:
                changed |= set_m2o(c_type, field, xml_record(
                        'real_estate.process.template', template_id),
                    f'{name}: {c_type._fields[field]["string"]}')
        if changed:
            c_type.save()


def setup_term_types(company):
    print('E4 Konditionsarten')
    for xml_id, code in TERM_TYPE_ACCOUNTS:
        term_type = xml_record('real_estate.contract.term.type', xml_id)
        if set_m2o(term_type, 'account', account(code, company),
                f'{term_type.name} ({term_type.sequence}): Konto'):
            term_type.save()

    print('E4a Zuordnung Konditionsart - Vertragsart')
    ContractType = Model.get('real_estate.contract.type')
    for xml_id, c_type_ids in TERM_TYPE_CONTRACT_TYPES:
        term_type = xml_record('real_estate.contract.term.type', xml_id)
        wanted = [xml_record('real_estate.contract.type', c) for c in
            c_type_ids]
        current = {c.id for c in term_type.c_type}
        missing = [c for c in wanted if c.id not in current]
        name = f'{term_type.name} ({term_type.sequence})'
        for c_type in missing:
            # fresh instance, see proteus M2M pattern (no shared _group)
            term_type.c_type.append(ContractType(c_type.id))
            report('angelegt', f'{name} - {c_type.name} ({c_type.sequence})')
        present = [c for c in wanted if c.id in current]
        if present:
            report('vorhanden', f'{name} - ' + ', '.join(
                    f'{c.name} ({c.sequence})' for c in present))
        extra = current - {c.id for c in wanted}
        if extra:
            report('Hinweis', f'{name}: weitere Vertragsarten ' + ', '.join(
                    f'{c.name} ({c.sequence})' for c in term_type.c_type
                    if c.id in extra) + ' (unverändert)')
        if missing:
            term_type.save()


def setup_cost_types(company):
    print('E4 Kostenarten')
    for xml_id, code in COST_TYPE_ACCOUNTS:
        cost_type = xml_record('real_estate.cost_type', xml_id)
        if set_m2o(cost_type, 'account', account(code, company),
                f'{cost_type.name}: Konto'):
            cost_type.save()


def setup_task_rules(company):
    print('E4 Aufgabenregeln')
    for code in sorted(set(TASK_RULES_ACTIVE) | set(TASK_RULES_COMPANY),
            key=(TASK_RULES_COMPANY + TASK_RULES_ACTIVE).index):
        rule = xml_record('real_estate.task.rule', f'task_rule_{code}')
        name = f'{code.upper()} {rule.name}'
        changed = False
        if code in TASK_RULES_ACTIVE:
            if rule.active:
                report('vorhanden', f'{name}: aktiv')
            else:
                rule.active = True
                report('gesetzt', f'{name}: aktiv')
                changed = True
        if code in TASK_RULES_COMPANY:
            changed |= set_m2o(rule, 'company', company,
                f'{name}: Gesellschaft')
        if changed:
            rule.save()


def setup_cron(company):
    print('E4 Cron-Aufträge')
    CronTask = Model.get('real_estate.cron_task')
    re_accounting = xml_record('real_estate.re_accounting',
        're_accounting_default')
    for values in CRON_TASKS:
        values = dict(CRON_TASK_DEFAULTS, **values)
        with config.get_config().set_context(active_test=False):
            found = CronTask.find([
                    ('re_accounting', '=', re_accounting.id),
                    ('task', '=', values['task']),
                    ])
        if found:
            task = found[0]
            diffs = [f'{k} {getattr(task, k)} (Vorgabe {v})'
                for k, v in values.items() if getattr(task, k) != v]
            if diffs:
                report('Hinweis', f'{task.name}: ' + ', '.join(diffs)
                    + ' (unverändert)')
            else:
                report('vorhanden', task.name)
            continue
        task = CronTask(re_accounting=re_accounting)
        for key, value in values.items():
            setattr(task, key, value)
        task.save()
        report('angelegt', task.name)

    Company = Model.get('company.company')
    cron = xml_record('ir.cron', 'cron_real_estate_daily')
    text = 'Immobilien: tägliche Aufgabe (cron_real_estate_daily): Gesellschaft'
    if any(c.id == company.id for c in cron.companies):
        report('vorhanden', f'{text} {company.rec_name}')
    elif cron.companies:
        report('Hinweis', f'{text} ' + ', '.join(
                c.rec_name for c in cron.companies) + ' (unverändert)')
    else:
        cron.companies.append(Company(company.id))
        cron.save()
        report('gesetzt', f'{text} {company.rec_name}')


# ---------------------------------------------------------------------------
# E5 / E6
# ---------------------------------------------------------------------------

def setup_sequences(company):
    """Returns {year: {number: strict sequence}} for the start year and
    the two following years."""
    print('E5 Strikte Nummernkreise')
    Sequence = Model.get('ir.sequence.strict')
    Company = Model.get('company.company')
    years = range(START_YEAR, START_YEAR + 3)
    patterns = {}
    result = {}
    for xml_id, number in BASIC_SEQUENCES:
        sequence = xml_record('ir.sequence.strict', xml_id)
        year_text, rest = sequence.name.split('/', 1)
        label_text = rest.split(' - ', 1)[1]
        patterns[number] = (label_text, sequence.sequence_type)
        if set_m2o(sequence, 'company', Company(company.id),
                f'{sequence.name}: Gesellschaft'):
            sequence.save()
        year = int(year_text)
        if year in years:
            result.setdefault(year, {})[number] = sequence
    for year in years:
        for number, (label_text, sequence_type) in sorted(patterns.items()):
            if number in result.get(year, {}):
                continue
            name = f'{year}/{number} - {label_text}'
            found = Sequence.find([
                    ('name', '=', name),
                    ('sequence_type', '=', sequence_type.id),
                    ('company', '=', company.id),
                    ])
            if found:
                sequence = found[0]
                report('vorhanden', name)
            else:
                sequence = Sequence(name=name)
                sequence.sequence_type = sequence_type
                sequence.company = Company(company.id)
                sequence.prefix = f'{year % 100:02d}{number}'
                sequence.padding = 5
                sequence.number_increment = 1
                sequence.type = 'incremental'
                sequence.save()
                report('angelegt', f'{name} (Präfix {sequence.prefix})')
            result.setdefault(year, {})[number] = sequence
    return result


def setup_fiscalyears(company, sequences):
    print('E6 Geschäftsjahre')
    FiscalYear = Model.get('account.fiscalyear')
    Company = Model.get('company.company')
    SequenceStrict = Model.get('ir.sequence.strict')
    for year in range(START_YEAR, START_YEAR + 3):
        start = datetime.date(year, 1, 1)
        end = datetime.date(year, 12, 31)
        seqs = sequences[year]
        found = FiscalYear.find([
                ('company', '=', company.id),
                ('start_date', '<=', end),
                ('end_date', '>=', start),
                ])
        if found:
            fiscalyear = found[0]
            if (fiscalyear.start_date, fiscalyear.end_date) != (start, end):
                report('Hinweis', f'Geschäftsjahr {fiscalyear.name}: '
                    f'{fiscalyear.start_date:%d.%m.%Y}-'
                    f'{fiscalyear.end_date:%d.%m.%Y} (unverändert)')
            else:
                report('vorhanden', f'Geschäftsjahr {fiscalyear.name}')
            if fiscalyear.move_sequence.id != seqs[1].id:
                report('Hinweis', f'Geschäftsjahr {fiscalyear.name}: '
                    f'Nummernkreis Buchungen {fiscalyear.move_sequence.name} '
                    f'(Vorgabe {seqs[1].name}, unverändert)')
        else:
            fiscalyear = FiscalYear(name=str(year))
            fiscalyear.company = Company(company.id)
            fiscalyear.start_date = start
            fiscalyear.end_date = end
            fiscalyear.move_sequence = SequenceStrict(seqs[1].id)
            # default_invoice_sequences gives one empty line for a user
            line = (fiscalyear.invoice_sequences[0]
                if fiscalyear.invoice_sequences
                else fiscalyear.invoice_sequences.new())
            line.company = Company(company.id)
            for field, number in INVOICE_SEQUENCE_FIELDS:
                setattr(line, field, SequenceStrict(seqs[number].id))
            fiscalyear.save()
            report('angelegt', f'Geschäftsjahr {year} '
                f'(Buchungen {seqs[1].name}; Rechnungen ' + ', '.join(
                    seqs[n].name for _, n in INVOICE_SEQUENCE_FIELDS) + ')')
            fiscalyear = FiscalYear(fiscalyear.id)
            fiscalyear.click('create_period')
            fiscalyear = FiscalYear(fiscalyear.id)
            report('angelegt', f'Geschäftsjahr {fiscalyear.name}: '
                f'{len(fiscalyear.periods)} Monatsperioden')
            continue
        # invoice sequences: one line without period
        fiscalyear = FiscalYear(fiscalyear.id)
        lines = list(fiscalyear.invoice_sequences)
        if lines:
            line = lines[0]
            diffs = [f'{f} {getattr(line, f).name}'
                for f, n in INVOICE_SEQUENCE_FIELDS
                if getattr(line, f) and getattr(line, f).id != seqs[n].id]
            if diffs:
                report('Hinweis', f'Geschäftsjahr {fiscalyear.name}: '
                    'Rechnungsnummernkreise ' + ', '.join(diffs)
                    + ' (unverändert)')
            else:
                report('vorhanden', f'Geschäftsjahr {fiscalyear.name}: '
                    'Rechnungsnummernkreise')
        else:
            line = fiscalyear.invoice_sequences.new()
            line.company = Company(company.id)
            for field, number in INVOICE_SEQUENCE_FIELDS:
                setattr(line, field, SequenceStrict(seqs[number].id))
            fiscalyear.save()
            report('gesetzt', f'Geschäftsjahr {fiscalyear.name}: '
                'Rechnungsnummernkreise ' + ', '.join(
                    seqs[n].name for _, n in INVOICE_SEQUENCE_FIELDS))
        # periods
        fiscalyear = FiscalYear(fiscalyear.id)
        if fiscalyear.periods:
            report('vorhanden', f'Geschäftsjahr {fiscalyear.name}: '
                f'{len(fiscalyear.periods)} Perioden')
        else:
            fiscalyear.click('create_period')
            fiscalyear = FiscalYear(fiscalyear.id)
            report('angelegt', f'Geschäftsjahr {fiscalyear.name}: '
                f'{len(fiscalyear.periods)} Monatsperioden')


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
        help=f'Startjahr (Default: aktuelles Jahr - 1 = {default_year}); '
             'Geschäftsjahre Startjahr bis Startjahr + 2')
    args = parser.parse_args()
    set_start_year(args.year)

    print(f'Datenbank:  {args.database}')
    print(f'Startjahr:  {START_YEAR} (Geschäftsjahre {START_YEAR}-'
          f'{START_YEAR + 2})')
    cfg = connect(args.database, args.config)
    cfg._context['company'] = COMPANY_ID
    print()

    try:
        company = check_prerequisites()
        setup_party(company)
        setup_company(company)
        setup_account_configuration(company)
        setup_contract_types(company)
        setup_term_types(company)
        setup_cost_types(company)
        setup_task_rules(company)
        setup_cron(company)
        sequences = setup_sequences(company)
        setup_fiscalyears(company, sequences)
    except SystemExit:
        raise
    except Exception as exc:
        print(f'ERROR: {exc.__class__.__name__}: {exc}', file=sys.stderr)
        sys.exit(1)

    counts = report.counts
    print('\nErgebnis: ' + ', '.join(f'{v} {k}' for k, v in counts.items()))
    if not report.changed:
        print('Alles vorhanden, nichts angelegt oder gesetzt '
              f'(Exit-Code {EXIT_EXISTS}).')
        sys.exit(EXIT_EXISTS)
    print('Fertig.')


if __name__ == '__main__':
    main()
