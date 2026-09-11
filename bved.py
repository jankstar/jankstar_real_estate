"""BVED interface: service provider configuration, object number mapping,
and the export/import runs that exchange fixed-width records (see
bved_records.py) with an external Messdienstleister for operating-cost
settlement (see rechercheergebnis-bved-schnittstelle.md /
spezifikation-tryton-bved-modul.md)."""
import datetime
import json
from decimal import Decimal

from trytond.model import (
    ModelSQL, ModelView, Unique, Workflow, fields, sequence_ordered)
from trytond.model.exceptions import ValidationError
from trytond.i18n import gettext
from trytond.pool import Pool
from trytond.pyson import Bool, Eval, If
from trytond.transaction import Transaction

from . import bved_records


def _first_line(text):
    return (text or '').splitlines()[0] if text else ''


def _fmt_amount(value):
    return '{:,.2f}'.format(float(value)).replace(',', 'T').replace(
        '.', ',').replace('T', '.')


def _valid_overlap_domain(start_date, end_date):
    """Domain fragment selecting valid_from/valid_to rows whose validity
    window overlaps [start_date, end_date] - used to find the BvedObjectNumber
    rows relevant to a given billing period."""
    return [
        ('valid_from', '<=', end_date),
        ['OR', ('valid_to', '=', None), ('valid_to', '>=', start_date)],
        ]


def _bank_fields(party, warnings, role_label):
    """Return (kontonummer, blz) for the M-Satz Feld 55/56 from the party's
    first active IBAN bank account, or (None, None) if none is usable -
    appends a human-readable note to `warnings` in that case. A German IBAN
    (DE + 20 digits) is deterministically converted back to the classic
    Kontonummer (last 10 digits) / Bankleitzahl (digits 5-12), since Feld
    55/56 (18/15 chars) predate SEPA and are too short for a full IBAN."""
    if not party:
        return None, None
    for account in (getattr(party, 'bank_accounts_used', None) or []):
        for number in (account.numbers or []):
            if number.type != 'iban':
                continue
            iban = (number.number or '').replace(' ', '').upper()
            if iban.startswith('DE') and len(iban) == 22 and iban[2:].isdigit():
                return iban[12:22], iban[4:12]
            warnings.append(
                'Keine deutsche IBAN bei %s "%s" (%s) - Bankfelder '
                'bleiben leer.' % (role_label, party.rec_name, iban))
            return None, None
    warnings.append(
        'Keine Bankverbindung (IBAN) bei %s "%s" gefunden - Bankfelder '
        'bleiben leer.' % (role_label, party.rec_name))
    return None, None


#**********************************************************************
class BvedUnit(ModelSQL, ModelView):
    "BVED Unit"
    __name__ = 'real_estate.bved.unit'
    __rec_name__ = 'name'

    code = fields.Char("Code", required=True, size=3,
        help="BVED Tabelle 'E' key, e.g. '010'.")

    description = fields.Char("Description", required=True,
        help="BVED Tabelle 'E' description, e.g. 'm² Wohnfläche'.")

    name = fields.Function(fields.Char("Name"), 'on_change_with_name',
        searcher='search_name')

    measurement_type = fields.Many2One(
        'real_estate.measurement.type', "Measurement Type",
        ondelete='RESTRICT',
        help="Which real_estate measurement type this BVED unit "
             "corresponds to, e.g. 'Wohnfläche' for '010 - m² "
             "Wohnfläche'. Used to resolve M-Satz fields 36-41 "
             "(Schlüssel/Anteil Umlage 1-3) from the BVED provider "
             "assignment's 'M-Satz Schlüssel Umlage 1/2/3' fields.")

    @classmethod
    def __setup__(cls):
        super().__setup__()
        table = cls.__table__()
        cls._sql_constraints = [
            ('code_uniq', Unique(table, table.code),
                'real_estate.msg_bved_unit_code_unique'),
            ]
        cls._order.insert(0, ('code', 'ASC'))

    @fields.depends('code', 'description')
    def on_change_with_name(self, name=None):
        if self.code and self.description:
            return f"{self.code} - {self.description}"
        return self.code or self.description

    @classmethod
    def search_name(cls, name, clause):
        return ['OR',
            ('code',) + tuple(clause[1:]),
            ('description',) + tuple(clause[1:]),
            ]


#**********************************************************************
class BvedServiceProvider(ModelSQL, ModelView):
    "BVED Service Provider"
    __name__ = 'real_estate.bved.service_provider'
    __rec_name__ = 'name'

    party = fields.Many2One('party.party', "Party", required=True,
        ondelete='CASCADE')

    name = fields.Function(fields.Char("Name"), 'on_change_with_name',
        searcher='search_name')

    bved_key = fields.Char("BVED Key", size=2, required=True,
        help="2-character code from BVED Tabelle 'U' identifying the "
             "settlement company (e.g. '40' for ista). The full table is "
             "maintained by the BVED e.V. and changes over time, so it is "
             "not enforced as a selection here - see the current PDF at "
             "bved.info.")

    bved_version = fields.Selection([
            ('3.10', '3.10'),
            ], "BVED Version", required=True, sort=False)

    transport_type = fields.Selection([
            ('manual', 'Manual (File Download/Upload)'),
            ('email', 'Email'),
            ('sftp', 'SFTP'),
            ('webservice_api', 'Webservice API'),
            ], "Transport Type", required=True, sort=False,
        help="Only 'Manual' is implemented; the other options are "
             "reserved for a future automated transport layer.")

    transport_config = fields.Text("Transport Configuration",
        states={'invisible': Eval('transport_type') == 'manual'},
        depends=['transport_type'])

    field7_mode = fields.Selection([
            ('1', 'Nutzer'),
            ('2', 'Eigentümer'),
            ('3', 'Eigentümer/Nutzer'),
            ('4', 'Leistungsnehmer'),
            ], "M-Satz Field 7 (Address Type)", required=True, sort=False,
        help="M-Satz Feld 7 (Kennzeichen Adressfeld) - written into "
             "every M-Satz record generated for this provider, and "
             "controls which address block(s) get filled: 'Nutzer' -> "
             "fields 8-15 from the occupying contract's own party; "
             "'Eigentümer' -> fields 16-23 per 'Eigentümer-Regel'; "
             "'Eigentümer/Nutzer' -> both; 'Leistungsnehmer' -> fields "
             "59-66 per 'Leistungsnehmer-Regel'.")

    owner_rule = fields.Selection([
            ('', ''),
            ('company', 'Gesellschaft ist Eigentümer'),
            ('role', 'Eigentümer über Rolle'),
            ], "Eigentümer-Regel", sort=False,
        states={
            'invisible': ~Eval('field7_mode').in_(['2', '3']),
            'required': Eval('field7_mode').in_(['2', '3']),
            },
        help="'Gesellschaft ist Eigentümer': M-Satz fields 16-23 (and, "
             "if 'M-Satz Leistungsgeber-Regel' is 'Leistungsgeber wie "
             "Eigentümer', fields 42-49 too) are filled from the "
             "company party. 'Eigentümer über Rolle': filled via "
             "'Owner Role' below instead.")

    owner_role = fields.Many2One(
        'real_estate.object_party.role', "Owner Role",
        ondelete='RESTRICT',
        states={
            'invisible': ~((Eval('field7_mode').in_(['2', '3']))
                & (Eval('owner_rule') == 'role')),
            'required': ((Eval('field7_mode').in_(['2', '3']))
                & (Eval('owner_rule') == 'role')),
            },
        help="Which real_estate.object_party role counts as the "
             "'Eigentümer' for this provider's M-Satz fields 16-23 "
             "(Owner name/address) - looked up via the object's own "
             "ancestor chain (rental object -> building/land -> "
             "property) as of the billing period's end date. Falls back "
             "to the module's built-in 'Owner' role if left empty.")

    tenant_rule = fields.Selection([
            ('', ''),
            ('tenant', 'Mieter'),
            ('role', 'über Partner-Rolle'),
            ], "Leistungsnehmer-Regel", sort=False,
        states={
            'invisible': Eval('field7_mode') != '4',
            'required': Eval('field7_mode') == '4',
            },
        help="'Mieter': M-Satz fields 59-66 (Leistungsnehmer) are "
             "filled the same way as the Nutzer block (the occupying "
             "contract's own party). 'über Partner-Rolle': filled via "
             "'Rolle Leistungsnehmer' below instead.")

    tenant_role = fields.Many2One(
        'real_estate.object_party.role', "Rolle Leistungsnehmer",
        ondelete='RESTRICT',
        states={
            'invisible': ~((Eval('field7_mode') == '4')
                & (Eval('tenant_rule') == 'role')),
            'required': ((Eval('field7_mode') == '4')
                & (Eval('tenant_rule') == 'role')),
            },
        help="Which real_estate.object_party role counts as the "
             "'Leistungsnehmer' for M-Satz fields 59-66 - looked up the "
             "same way as 'Owner Role' (object ancestor chain, as of "
             "the billing period's end date).")

    provider_org_rule = fields.Selection([
            ('owner', 'Leistungsgeber wie Eigentümer'),
            ('role', 'über Partner-Rolle'),
            ], "M-Satz Leistungsgeber-Regel", required=True, sort=False,
        help="How M-Satz fields 42-49 (Leistungsgeber name/address) are "
             "filled - independent of 'M-Satz Field 7 (Address Type)'. "
             "'Leistungsgeber wie Eigentümer': same party/address as "
             "resolved for the Eigentümer block (via 'Eigentümer-Regel' "
             "above, regardless of whether field 7 actually selects "
             "'Eigentümer'). 'über Partner-Rolle': filled via 'Rolle "
             "Leistungsgeber' below instead.")

    provider_org_role = fields.Many2One(
        'real_estate.object_party.role', "Rolle Leistungsgeber",
        ondelete='RESTRICT',
        states={
            'invisible': Eval('provider_org_rule') != 'role',
            'required': Eval('provider_org_rule') == 'role',
            },
        help="Which real_estate.object_party role counts as the "
             "'Leistungsgeber' for M-Satz fields 42-49 - looked up the "
             "same way as 'Owner Role' (object ancestor chain, as of "
             "the billing period's end date).")

    tax_id_type = fields.Selection(
        'get_identification_types', "Tax ID Identification Type",
        sort=False,
        help="Which party.identifier type on the company party "
             "(Leistungsgeber) provides the value for M-Satz field 51 "
             "(USt-ID-Nr. oder Steuernummer) - field 50 (see 'M-Satz "
             "Field 50 (Tax ID Flag)') is written alongside it when a "
             "matching identifier is found. Fields 50/51 stay unset if "
             "left empty, or if the company party has no identifier of "
             "this type.")

    tax_id_flag = fields.Selection([
            ('', ''),
            ('1', 'USt-ID-Nr.'),
            ('2', 'Steuernummer'),
            ], "M-Satz Field 50 (Tax ID Flag)", sort=False,
        states={
            'invisible': ~Bool(Eval('tax_id_type')),
            'required': Bool(Eval('tax_id_type')),
            },
        help="M-Satz Feld 50 (Kennzeichen USt-ID/Steuernummer) - "
             "whether the value configured via 'Tax ID Identification "
             "Type' (field 51) is a USt-ID-Nr. (1) or a Steuernummer "
             "(2). Written into field 50 whenever field 51 is (i.e. a "
             "matching party.identifier is found).")

    tax_rate_flag = fields.Selection([
            ('', ''),
            ('1', 'Regelsteuersatz'),
            ('2', 'ermäßigt'),
            ], "M-Satz Field 52 (Tax Rate Flag)", sort=False,
        help="M-Satz Feld 52 (Kennzeichen Steuersatz) - written "
             "unchanged into every M-Satz record of this provider. "
             "Left blank leaves field 52 unset (Kann-Feld).")

    invoice_number_flag = fields.Selection([
            ('', ''),
            ('0', 'keine Rechnung §14 UStG'),
            ('1', 'aus Feld 54'),
            ('2', 'vom Abrechnungsunternehmen erstellt'),
            ], "M-Satz Field 53 (Invoice Number Flag)", sort=False,
        help="M-Satz Feld 53 (Kennzeichen Rechnungsnummer) - written "
             "unchanged into every M-Satz record of this provider. "
             "'aus Feld 54' additionally requires 'Rechnungsnummer-"
             "Regel' below to fill field 54 itself. Left blank leaves "
             "fields 53/54 unset (Kann-Felder).")

    invoice_number_rule = fields.Selection([
            ('', ''),
            ('contract', 'Nr. Mietvertrag'),
            ('object', 'Nr. Mietobjekt'),
            ('settlement_result', 'ID Settlement result'),
            ], "Rechnungsnummer-Regel", sort=False,
        states={
            'invisible': Eval('invoice_number_flag') != '1',
            'required': Eval('invoice_number_flag') == '1',
            },
        help="How M-Satz field 54 (Rechnungsnummer) is filled when "
             "field 53 is 'aus Feld 54': 'Nr. Mietvertrag' - the "
             "occupying contract's own contract_number; 'Nr. "
             "Mietobjekt' - the rental object's own object_number; 'ID "
             "Settlement result' - the id of the matching "
             "real_estate.settlement_result record (same contract/"
             "object, billing unit period overlapping the M-Satz "
             "period).")

    direct_debit_flag = fields.Selection([
            ('', ''),
            ('0', 'keine Abbuchungserlaubnis'),
            ('1', 'Abbuchungserlaubnis'),
            ], "M-Satz Field 58 (Payment Type Flag)", sort=False,
        help="M-Satz Feld 58 (Kennzeichen Zahlungsart) - written "
             "unchanged into every M-Satz record of this provider.")

    @staticmethod
    def get_identification_types():
        pool = Pool()
        Identifier = pool.get('party.identifier')
        return Identifier.get_types()

    @classmethod
    def default_bved_version(cls):
        return '3.10'

    @classmethod
    def default_transport_type(cls):
        return 'manual'

    @classmethod
    def default_owner_role(cls):
        pool = Pool()
        ModelData = pool.get('ir.model.data')
        try:
            return ModelData.get_id(
                'real_estate', 'object_party_owner_role')
        except KeyError:
            return None

    @staticmethod
    def default_field7_mode():
        return '1'

    @staticmethod
    def default_owner_rule():
        return 'role'

    @staticmethod
    def default_tenant_rule():
        return 'tenant'

    @staticmethod
    def default_provider_org_rule():
        return 'owner'

    @staticmethod
    def default_tax_id_flag():
        return '2'

    @staticmethod
    def default_direct_debit_flag():
        return '0'

    @fields.depends('party')
    def on_change_with_name(self, name=None):
        return self.party.rec_name if self.party else None

    @classmethod
    def search_name(cls, name, clause):
        return [('party.rec_name',) + tuple(clause[1:])]


#**********************************************************************
class BvedProviderAssignment(ModelSQL, ModelView):
    "BVED Provider Assignment"
    __name__ = 'real_estate.bved.provider_assignment'
    __rec_name__ = 'name'

    base_object = fields.Many2One('real_estate.base_object',
        "Property/Building", required=True, ondelete='CASCADE',
        domain=[('type', 'in', ('property', 'building'))],
        help="The property (whole Wirtschaftseinheit) or a single "
             "building within it that this provider/Liegenschaftsnummer "
             "covers. Use the property node itself when one "
             "Liegenschaftsnummer covers the entire complex (the common "
             "case); use a building node only when that building "
             "genuinely has its own, different Liegenschaftsnummer (e.g. "
             "a different provider per building).")

    provider = fields.Many2One('real_estate.bved.service_provider',
        "Provider", required=True, ondelete='RESTRICT')

    customer_number = fields.Char("BVED Customer Number", required=True,
        help="A-Satz field 3 (\"Kunden-Nr.\") - the customer number this "
             "company has with the BVED provider (Nummer des Kunden beim "
             "Abrechnungsunternehmen).")

    external_property_number = fields.Char(
        "BVED Property Number", size=9, required=True,
        help="9-digit property number the BVED provider assigned to this "
             "property/building (\"Ordnungsbegriff Abrechnungsunternehmen\").")

    valid_from = fields.Date("Valid From", required=True)
    valid_to = fields.Date("Valid To")

    company = fields.Function(
        fields.Many2One('company.company', "Company"),
        'on_change_with_company', searcher='search_company')

    name = fields.Function(fields.Char("Name"), 'on_change_with_name',
        searcher='search_name')

    object_numbers = fields.One2Many('real_estate.bved.object_number',
        'provider_assignment', "Object Numbers")

    # --- M-Satz allocation keys 1-3 (fields 36-41): each maps to a
    # real_estate.bved.unit (BVED Tabelle 'E' code + real_estate
    # measurement type). For every M-Satz row of a rental object under
    # this assignment, field 36/38/40 (Schlüssel Umlage N) gets the
    # unit's own code, and field 37/39/41 (Anteil Umlage N) gets the
    # object's own measurement value for the unit's measurement_type -
    # see BvedObjectNumber._m_satz_values().
    allocation1_unit = fields.Many2One(
        'real_estate.bved.unit', "M-Satz Allocation Key 1",
        ondelete='RESTRICT',
        help="Fields 36/37 (Schlüssel/Anteil Umlage 1).")
    allocation2_unit = fields.Many2One(
        'real_estate.bved.unit', "M-Satz Allocation Key 2",
        ondelete='RESTRICT',
        help="Fields 38/39 (Schlüssel/Anteil Umlage 2).")
    allocation3_unit = fields.Many2One(
        'real_estate.bved.unit', "M-Satz Allocation Key 3",
        ondelete='RESTRICT',
        help="Fields 40/41 (Schlüssel/Anteil Umlage 3).")

    tenant_change_fee_flag = fields.Selection([
            ('0', 'keine Umlage'),
            ('1', 'Umlage'),
            ], "M-Satz Field 68 (Tenant Change Fee Flag)", required=True,
        sort=False,
        help="M-Satz Feld 68 (Kennzeichen Umlage Nutzerwechselgebühr) - "
             "written unchanged into every M-Satz record generated for "
             "this provider assignment.")

    @staticmethod
    def default_tenant_change_fee_flag():
        return '0'

    # --- L-Satz preview: derived (Function) and manual fields, so the
    # user can see how the L-Satz for this property/building would come
    # out without waiting for an actual export. The preview always uses
    # the most recently completed calendar year (period_start/period_end
    # below) across ALL billing units currently assigned here - the real
    # export in _build_l_m_records() recomputes the same underlying
    # helpers per specific billing unit and its own period instead, so
    # the preview and the real export can differ if a billing unit's
    # actual period doesn't align with a plain calendar year.
    l_provider_key = fields.Function(
        fields.Char("4. Provider Key"), 'on_change_with_l_provider_key')
    l_street = fields.Function(
        fields.Char("7. Street"), 'on_change_with_l_street')
    l_country = fields.Function(
        fields.Many2One('country.country', "8. Country"),
        'on_change_with_l_country')
    l_postal_code = fields.Function(
        fields.Char("9. Postal Code"), 'on_change_with_l_postal_code')
    l_city = fields.Function(
        fields.Char("10. City"), 'on_change_with_l_city')
    l_period_start = fields.Function(
        fields.Date("11. Period Start"), 'on_change_with_l_period_start')
    l_period_end = fields.Function(
        fields.Date("11. Period End"), 'on_change_with_l_period_end')
    l_vat_flag = fields.Function(
        fields.Selection([
            ('3', 'No VAT shown'),
            ('4', 'Net (fully opted for VAT)'),
            ('5', 'Per M-Satz field 25 (mixed/per user)'),
            ], "6. VAT Treatment", sort=False,
            help="Derived from the option rate of the billing units "
            "covered by this assignment: 100% option rate -> '4', 0% -> "
            "'3', anything in between -> '5' (decided per user via the "
            "M-Satz field)."),
        'on_change_with_l_vat_flag')
    l_weg_flag = fields.Function(
        fields.Boolean("17. WEG (Cash Basis)",
            help="Derived from the calculation method of the covered "
            "billing units: 'Cash basis' (WEG billing) sets this flag, "
            "'Accrual basis' (rental apartment) does not."),
        'on_change_with_l_weg_flag')
    l_non_residential_flag = fields.Function(
        fields.Boolean("19. >50% Commercial (§8)",
            help="True if any covered billing unit has its own "
            "'Non-residential building >50% commercial (§8)' flag set "
            "(CO2 Costs tab of the billing unit)."),
        'on_change_with_l_non_residential_flag')
    l_co2_landlord_share_percent = fields.Function(
        fields.Numeric("22. CO2 Landlord Share (%)", digits=(5, 2),
            help="Taken from the heating cost billing unit "
            "(bved_fuel_data) among the covered billing units, if any: "
            "its 'Commercial Landlord Share' if its own "
            "'Non-residential building >50% commercial (§8)' flag is "
            "set, else its 'Landlord Share' (residential emission-per-m² "
            "tier table)."),
        'on_change_with_l_co2_landlord_share_percent')

    gross_floor_area_measurement_type = fields.Many2One(
        'real_estate.measurement.type', "Gross Floor Area Measurement Type",
        ondelete='RESTRICT',
        domain=[('types', '=', ['object'])],
        help="Which measurement type to sum (across every rental object "
             "of a billing unit assigned here, per "
             "BillingUnit.covered_rental_objects() - i.e. every object "
             "with a settlement result, same as that billing unit's own "
             "'Rental Objects' tab; falling back to every object covered "
             "by one of its settlement units if no settlement result "
             "exists yet; each object counted once even if covered by "
             "several billing units) for L-Satz field 18 (Gesamtfläche), "
             "as of each billing unit's own end date. Must be an "
             "object-level measurement type (e.g. 'Usable Space') - a "
             "building-level type such as 'Gross floor area' can never "
             "have a value on an individual rental object and would "
             "always sum to 0. Leave empty to omit this Kann-Feld.")
    l_total_area = fields.Function(
        fields.Numeric("18. Total Area", digits=(16, 2)),
        'on_change_with_l_total_area')

    vacancy_risk_flag = fields.Boolean(
        "13. Vacancy Risk Surcharge",
        help="L-Satz field 13 (Kennzeichen Umlageausfallwagnis) - not "
             "derivable from any existing data, enter manually. Also "
             "used, unchanged, for M-Satz field 26 (Kennzeichen "
             "Umlageausfallwagnis).")
    vacancy_risk_percent = fields.Numeric(
        "14. Vacancy Risk Surcharge (%)", digits=(5, 2),
        states={'invisible': ~Eval('vacancy_risk_flag', False)},
        help="L-Satz field 14 - percentage, only relevant if the "
             "surcharge flag above is set.")
    labor_share_flag = fields.Boolean(
        "15. Disclose Labor Share",
        help="L-Satz field 15 (Kennzeichen Ausweisung Lohnanteil) - not "
             "derivable from any existing data, enter manually.")
    energy_improvement_flag = fields.Boolean(
        "20. Energy Improvement (§9)",
        help="L-Satz field 20 - legal fact about the building, not "
             "derivable from any existing data, enter manually.")
    heat_supply_flag = fields.Boolean(
        "21. Heat Supply (§9)",
        help="L-Satz field 21 - legal fact about the building, not "
             "derivable from any existing data, enter manually.")
    heat_connection_2023_flag = fields.Boolean(
        "23. District Heating Connection since 2023",
        help="L-Satz field 23 - legal fact about the building, not "
             "derivable from any existing data, enter manually.")

    @classmethod
    def __setup__(cls):
        super().__setup__()
        table = cls.__table__()
        cls._sql_constraints += [
            ('base_object_provider_valid_from_uniq',
                Unique(table, table.base_object, table.provider,
                    table.valid_from),
                'real_estate.msg_bved_provider_assignment_unique'),
            ]

    @fields.depends('base_object', '_parent_base_object.company')
    def on_change_with_company(self, name=None):
        return self.base_object.company if self.base_object else None

    @classmethod
    def search_company(cls, name, clause):
        return [('base_object.company',) + tuple(clause[1:])]

    @fields.depends('base_object', 'provider', 'external_property_number',
        '_parent_base_object.rec_name')
    def on_change_with_name(self, name=None):
         return '%s / %s / %s' % (
             self.base_object.rec_name if self.base_object else '?',
             self.provider.rec_name if self.provider else '?',
             self.external_property_number if self.external_property_number else '?')

    @classmethod
    def search_name(cls, name, clause):
        _, operator, value = clause
        return ['OR',
            ('base_object.rec_name', operator, value),
            ('provider.rec_name', operator, value),
            ('external_property_number', operator, value),
            ]

    def _billing_units(self):
        if not self.id:
            return []
        return Pool().get('real_estate.billing_unit').search([
            ('bved_provider_assignment', '=', self.id)])

    @staticmethod
    def _last_full_year():
        today = datetime.date.today()
        return (datetime.date(today.year - 1, 1, 1),
            datetime.date(today.year - 1, 12, 31))

    @classmethod
    def _vat_flag(cls, billing_units, date):
        """VAT treatment (L-Satz field 6) derived from the Optionssatz
        (real_estate.option_rate) of the given billing units as of
        `date`. '4' if all units are at 100% (net/fully opted), '3' if
        all are at 0% (no VAT shown), '5' otherwise (mixed, or
        undetermined - shown per M-Satz field 25/user instead)."""
        OptionRate = Pool().get('real_estate.option_rate')
        fractions = []
        for bu in billing_units:
            fraction = OptionRate.get_current_rate_fraction(
                'billing_unit', bu, date)
            if fraction is None:
                continue
            fractions.append(fraction)
        if not fractions:
            return '5'
        if all(f == 1 for f in fractions):
            return '4'
        if all(f == 0 for f in fractions):
            return '3'
        return '5'

    @staticmethod
    def _covered_objects_with_end_date(billing_units):
        """{base_object_id: latest end_date} across the given billing
        units' own rental objects - an object covered by several billing
        units (different cost categories/years) is counted once, using
        the latest end_date.

        The object set itself is always determined by the billing unit
        (BillingUnit.covered_rental_objects()) - never re-derived here:
        settlement_result_objects() (same as the "Rental Objects" tab)
        when available, else the objects covered by its settlement units
        if no settlement result exists yet."""
        result = {}
        for bu in billing_units:
            for obj in bu.covered_rental_objects():
                if obj.id not in result or bu.end_date > result[obj.id]:
                    result[obj.id] = bu.end_date
        return result

    @classmethod
    def _total_area(cls, billing_units, measurement_type):
        if not measurement_type:
            return None
        Measurement = Pool().get('real_estate.measurement')
        total = 0.0
        for obj_id, end_date in cls._covered_objects_with_end_date(
                billing_units).items():
            value = Measurement.get_total_value(obj_id, measurement_type, end_date)
            if value:
                total += value
        return Decimal(str(total)) if total else Decimal(0)

    @staticmethod
    def _co2_landlord_share(billing_units):
        """CO2 landlord share (%), taken from the billing unit that owns
        the settlement unit actually externally billed via BVED
        (bved_fuel_data=True) - the co2 share fields are aggregated per
        billing unit (across all of its co2_kostaufg-referencing
        settlement units), not a single value per property, so the
        billing unit of the heating-cost unit relevant to this L-Satz is
        used as the representative value.

        Which of that billing unit's two CO2 share fields to use follows
        its own non_residential_flag (§8, same flag that also drives
        which of the two is shown on its CO2 Costs tab): True ->
        co2_commercial_landlord_share (flat, configured share), False ->
        co2_landlord_share (residential emission-per-m² tier table)."""
        for bu in billing_units:
            if any(su.bved_fuel_data for su in (bu.settlement_units or [])):
                return (bu.co2_commercial_landlord_share
                    if bu.non_residential_flag
                    else bu.co2_landlord_share)
        return None

    @fields.depends('provider')
    def on_change_with_l_provider_key(self, name=None):
        return self.provider.bved_key if self.provider else None

    @fields.depends('base_object', '_parent_base_object.address')
    def on_change_with_l_street(self, name=None):
        address = self.base_object.address if self.base_object else None
        return address.street_single_line if address else None

    @fields.depends('base_object', '_parent_base_object.address')
    def on_change_with_l_country(self, name=None):
        address = self.base_object.address if self.base_object else None
        return address.country if address else None

    @fields.depends('base_object', '_parent_base_object.address')
    def on_change_with_l_postal_code(self, name=None):
        address = self.base_object.address if self.base_object else None
        return address.postal_code if address else None

    @fields.depends('base_object', '_parent_base_object.address')
    def on_change_with_l_city(self, name=None):
        address = self.base_object.address if self.base_object else None
        return address.city if address else None

    def on_change_with_l_period_start(self, name=None):
        return self._last_full_year()[0]

    def on_change_with_l_period_end(self, name=None):
        return self._last_full_year()[1]

    @fields.depends('id')
    def on_change_with_l_vat_flag(self, name=None):
        return self._vat_flag(
            self._billing_units(), self._last_full_year()[1])

    @fields.depends('id')
    def on_change_with_l_weg_flag(self, name=None):
        return any(
            bu.calculation_method == 'WEG_billing'
            for bu in self._billing_units())

    @fields.depends('id')
    def on_change_with_l_non_residential_flag(self, name=None):
        return any(
            bu.non_residential_flag for bu in self._billing_units())

    @fields.depends('id')
    def on_change_with_l_co2_landlord_share_percent(self, name=None):
        return self._co2_landlord_share(self._billing_units())

    @fields.depends('id', 'gross_floor_area_measurement_type')
    def on_change_with_l_total_area(self, name=None):
        return self._total_area(
            self._billing_units(), self.gross_floor_area_measurement_type)


#**********************************************************************
class BvedObjectNumber(ModelSQL, ModelView):
    "BVED Object Number Mapping"
    __name__ = 'real_estate.bved.object_number'

    provider_assignment = fields.Many2One(
        'real_estate.bved.provider_assignment', "Provider Assignment",
        required=True, ondelete='CASCADE')

    scope_object = fields.Function(
        fields.Many2One('real_estate.base_object', "Scope"),
        'on_change_with_scope_object')

    base_object = fields.Many2One('real_estate.base_object', "Object",
        required=True, ondelete='CASCADE',
        domain=[
            ('type', '=', 'object'),
            If(Bool(Eval('scope_object')),
                ('parent', 'child_of', [Eval('scope_object', -1)], 'parent'),
                ()),
            ])

    external_unit_number = fields.Char(
        "External Unit Number", size=4,
        help="4-digit unit number - together with the property's 9-digit "
             "Liegenschaftsnummer forms the 13-digit Ordnungsbegriff "
             "Abrechnungsunternehmen (A-/M-Satz field 5).")

    internal_reference = fields.Char("Internal Reference", required=True,
        help="Stable identifier used as \"Ordnungsbegriff des "
             "Auftraggebers\" (Kennung Nutzer beim Auftraggeber) in every "
             "BVED record referencing this unit. "
             "A renumbering by the provider (e.g. after a renovation) "
             "should close this row's valid_to and add a new dated row, "
             "rather than overwriting internal_reference in place - "
             "otherwise already-imported historical D-Satz lines "
             "referencing the old number can no longer be resolved.")

    valid_from = fields.Date("Valid From", required=True)
    valid_to = fields.Date("Valid To")

    @classmethod
    def __setup__(cls):
        super().__setup__()
        table = cls.__table__()
        cls._sql_constraints += [
            ('assignment_object_valid_from_uniq',
                Unique(table, table.provider_assignment, table.base_object,
                    table.valid_from),
                'real_estate.msg_bved_object_number_object_unique'),
            ('assignment_reference_valid_from_uniq',
                Unique(table, table.provider_assignment,
                    table.internal_reference, table.valid_from),
                'real_estate.msg_bved_object_number_reference_unique'),
            ]
        cls._buttons.update({
                'refresh_m_satz_preview': {},
                })

    @fields.depends('provider_assignment',
        '_parent_provider_assignment.base_object')
    def on_change_with_scope_object(self, name=None):
        return (self.provider_assignment.base_object
            if self.provider_assignment else None)

    def _find_party_by_role(self, ObjectParty, role_id, as_of_date):
        """Search real_estate.object_party for `role_id`, valid exactly
        on `as_of_date` (valid_from <= as_of_date and (no valid_to or
        valid_to >= as_of_date) - a point-in-time check, not an overlap
        with a period), walking up from this mapping's own base_object
        through its ancestor chain (rental object -> building/land ->
        property) until a match is found or the top of the tree is
        reached. Returns the party, or None if none of the ancestors has
        a matching role assignment. Generic - used for the Eigentümer
        (owner_role), Leistungsnehmer (tenant_role), and Leistungsgeber
        (provider_org_role) lookups alike, see _m_satz_values()."""
        if role_id is None:
            return None
        node = self.base_object
        while node:
            owners = ObjectParty.search([
                ('base_object', '=', node.id),
                ('role', '=', role_id),
                ('valid_from', '<=', as_of_date),
                ['OR', ('valid_to', '=', None),
                    ('valid_to', '>=', as_of_date)],
                ])
            if owners:
                return owners[0].party
            node = node.parent
        return None

    def _area_share_by_mode(self, mode, as_of_date):
        """Shared by _heating_base_share() (fields 27/69) and
        _hotwater_base_share() (fields 30/70): the direct measurement
        value of this mapping's base_object for the
        heating_area_measurement_type configured on the (first, if
        several) settlement unit with heating_billing_mode = `mode`
        ('central_heating' or 'central_hot_water') belonging to this
        object's property, as of `as_of_date`. This is the object's raw
        Bemessung (e.g. its living area in m²) - deliberately NOT
        time-weighted by occupancy (unlike cost_share.area_share, which
        drives the actual cost allocation and is prorated by
        time_share/time_total) and NOT affected by the
        heating_consumption_share_percent/heating_area_share_percent
        split - fields 27/30 always report the object's plain
        measurement value, independent of any occupancy period or
        cost-distribution outcome. Does not require 'Compute Value
        Shares' to have been run.

        Returns (share, key): `share` is the measurement value (None if
        no qualifying settlement unit has a
        heating_area_measurement_type set, or the object has no
        matching measurement recorded). `key` is the BVED Tabelle 'E'
        code of the real_estate.bved.unit whose own measurement_type
        matches that measurement type; None if none is mapped."""
        pool = Pool()
        SettlementUnit = pool.get('real_estate.settlement_unit')
        BvedUnit = pool.get('real_estate.bved.unit')
        Measurement = pool.get('real_estate.measurement')
        obj = self.base_object
        if not obj.property:
            return None, None
        units = SettlementUnit.search([
            ('billing_unit.property', '=', obj.property.id),
            ('heating_billing_mode', '=', mode),
            ])
        measurement_type = None
        for su in units:
            if su.heating_area_measurement_type:
                measurement_type = su.heating_area_measurement_type
                break
        if not measurement_type:
            return None, None
        mval = Measurement.get_total_value(
            obj.id, measurement_type, as_of_date)
        share = Decimal(str(round(mval, 2))) if mval is not None else None
        key = None
        bved_units = BvedUnit.search([
            ('measurement_type', '=', measurement_type.id)], limit=1)
        if bved_units:
            key = bved_units[0].code
        return share, key

    def _heating_base_share(self, as_of_date):
        """Fields 27/69 (Heizung Grundanteil / Schlüssel Grundanteile
        Heizung) - see _area_share_by_mode()."""
        return self._area_share_by_mode('central_heating', as_of_date)

    def _hotwater_base_share(self, as_of_date):
        """Fields 30/70 (Warmwasser Grundanteil / Schlüssel Grundanteile
        Warmwasser) - see _area_share_by_mode()."""
        return self._area_share_by_mode('central_hot_water', as_of_date)

    def _allocation_shares(self, as_of_date):
        """Fields 36-41 (Schlüssel/Anteil Umlage 1-3): for each of the
        provider assignment's three 'M-Satz Allocation Key' slots that
        is set, return (code, share) where `code` is the
        real_estate.bved.unit's own BVED Tabelle 'E' code and `share`
        is this mapping's own base_object's measurement value (as of
        `as_of_date`) for the unit's mapped measurement_type - or
        (code, None) if the unit has no measurement_type mapped, or
        None entirely for an unset slot. Always returns exactly 3
        entries (one per slot, in order)."""
        pool = Pool()
        Measurement = pool.get('real_estate.measurement')
        assignment = self.provider_assignment
        obj = self.base_object
        units = (
            (assignment.allocation1_unit, assignment.allocation2_unit,
                assignment.allocation3_unit) if assignment else (None, None, None))
        results = []
        for unit in units:
            if not unit:
                results.append(None)
                continue
            share = None
            if unit.measurement_type:
                mval = Measurement.get_total_value(
                    obj.id, unit.measurement_type, as_of_date)
                if mval is not None:
                    share = Decimal(str(round(mval, 2)))
            results.append((unit.code, share))
        return results

    m_satz_lines = fields.One2Many(
        'real_estate.bved.object_number.m_satz_line', 'object_number',
        "M-Satz Preview", readonly=True,
        help="Read-only preview of this object's M-Satz data (BVED "
             "Nutzer/Eigentümer record) for the most recently completed "
             "calendar year (same period as the L-Satz preview on the "
             "provider assignment), one line per occupancy segment - "
             "uses the exact same computation as the real export "
             "(_m_satz_values()). Click 'Refresh M-Satz Preview' to "
             "(re)compute.")

    def _m_satz_values(
            self, period_start, period_end, provider,
            company_party=None, company_address=None, warnings=None,
            refresh_occupancy=True):
        """Return the list of M-Satz value dicts (same keys as
        bved_records.pack('M', ...) expects) for this mapping's
        base_object over [period_start, period_end] - one dict per
        occupancy segment overlapping the period. Shared by the real
        export (BvedExport._build_l_m_records()) and this record's own
        m_satz_preview, so they can never diverge.

        Field 7 (Kennzeichen Adressfeld) is written from
        `provider.field7_mode` ('1'=Nutzer, '2'=Eigentümer,
        '3'=Eigentümer/Nutzer, '4'=Leistungsnehmer) and controls which
        address block(s) get filled:

        - '1'/'3': fields 8-15 (Nutzer) from the occupying contract's
          own party (entry.contract.contractual_partner).
        - '2'/'3': fields 16-23 (Eigentümer) per `provider.owner_rule`
          - 'company': the company party/address (`company_party`/
            `company_address`); 'role': `provider.owner_role`, resolved
            via _find_party_by_role() walking this mapping's own
            base_object up its ancestor chain (rental object ->
            building/land -> property), valid exactly as of
            `period_end`.
        - '4': fields 59-66 (Leistungsnehmer) per `provider.tenant_rule`
          - 'tenant': same as the Nutzer party; 'role':
            `provider.tenant_role`, resolved the same way as the owner
            role (as of `period_end`).

        Fields 42-49 (Leistungsgeber) are filled independently of field
        7, per `provider.provider_org_rule` - 'owner': the same
        party/address resolved for the Eigentümer block above
        (regardless of whether field 7 is actually '2'/'3'); 'role':
        `provider.provider_org_role`, resolved the same way.

        `refresh_occupancy` controls whether occupancy is recomputed
        first (Occupancy.refresh() - deletes and recreates rows, a
        write). The real export needs this to guarantee up-to-date
        data; a plain preview getter (invoked from read(), which runs in
        a read-only transaction) must pass False, or it errors out
        against a read-only database connection."""
        if warnings is None:
            warnings = []
        pool = Pool()
        Occupancy = pool.get('real_estate.base_object.occupancy')
        ObjectParty = pool.get('real_estate.object_party')
        OptionRate = pool.get('real_estate.option_rate')
        Identifier = pool.get('party.identifier')
        SettlementResult = pool.get('real_estate.settlement_result')

        obj = self.base_object
        assignment = self.provider_assignment

        field7_mode = provider.field7_mode if provider else '1'
        owner_rule = provider.owner_rule if provider else 'role'
        tenant_rule = provider.tenant_rule if provider else 'tenant'
        provider_org_rule = provider.provider_org_rule if provider else 'owner'

        # Eigentümer (fields 16-23, and the source for 'Leistungsgeber
        # wie Eigentümer' below) - resolved once for the whole call,
        # analogous to the pre-existing owner lookup.
        if owner_rule == 'company':
            owner_party, owner_address = company_party, company_address
        else:
            owner_role_id = provider.owner_role.id if (
                provider and provider.owner_role) else None
            owner_party = self._find_party_by_role(
                ObjectParty, owner_role_id, period_end)
            owner_address = owner_party.address_get() if owner_party else None

        # Leistungsgeber (fields 42-49) - independent of field 7.
        if provider_org_rule == 'role':
            provider_org_role_id = provider.provider_org_role.id if (
                provider and provider.provider_org_role) else None
            org_party = self._find_party_by_role(
                ObjectParty, provider_org_role_id, period_end)
            org_address = org_party.address_get() if org_party else None
        else:
            org_party, org_address = owner_party, owner_address

        # Leistungsnehmer (fields 59-66) via role - only used for field
        # 7 = '4' and tenant_rule = 'role'; the 'tenant' sub-choice
        # depends on the occupancy entry and is resolved per segment
        # below instead.
        debtor_role_party = None
        if field7_mode == '4' and tenant_rule == 'role':
            tenant_role_id = provider.tenant_role.id if (
                provider and provider.tenant_role) else None
            debtor_role_party = self._find_party_by_role(
                ObjectParty, tenant_role_id, period_end)

        if refresh_occupancy:
            Occupancy.refresh([obj])
        entries = Occupancy.search([
            ('base_object', '=', obj.id),
            ('start_date', '<=', period_end),
            ['OR', ('end_date', '=', None), ('end_date', '>=', period_start)],
            ], order=[('start_date', 'ASC')]) or [None]

        prop_no = ((assignment.external_property_number if assignment else '')
            or '').rjust(9, '0')[:9]
        unit_no = (self.external_unit_number or '0000').rjust(4, '0')[:4]
        provider_reference = prop_no + unit_no

        rows = []
        for entry in entries:
            values = {
                'customer_number':
                    assignment.customer_number if assignment else None,
                'provider_key': provider.bved_key if provider else None,
                'provider_reference': provider_reference,
                'internal_reference': self.internal_reference,
                'address_flag': int(field7_mode),
                'vacancy_risk_calc_flag': (
                    1 if assignment and assignment.vacancy_risk_flag else 0),
                'vacancy_flag': 0,
                'tenant_change_fee_flag': (
                    int(assignment.tenant_change_fee_flag)
                    if assignment and assignment.tenant_change_fee_flag
                    else 0),
                }
            if field7_mode in ('2', '3') and owner_party:
                values['owner_name1'] = owner_party.name[:35]
                if owner_address:
                    values['owner_street'] = _first_line(
                        owner_address.street)[:35]
                    values['owner_country'] = (
                        owner_address.country.code3
                        if owner_address.country else '')
                    values['owner_postal_code'] = (
                        owner_address.postal_code or '')
                    values['owner_city'] = owner_address.city or ''

            # Nutzungszeitraum is set regardless of occupancy state - a
            # vacancy period still needs a period so the provider can
            # compute the (owner-borne) Grundkosten share for it; only
            # the tenant-specific fields below depend on an actual
            # rented+contract entry.
            if entry:
                values['occupancy_start'] = max(entry.start_date, period_start)
                values['occupancy_end'] = (
                    min(entry.end_date, period_end)
                    if entry.end_date else period_end)
            else:
                values['occupancy_start'] = period_start
                values['occupancy_end'] = period_end

            # Field 25 (Kennzeichen MwSt): 0 = kein Ausweis if the
            # object's own Optionssatz is 0% (or unknown), else
            # 1 = gewerbl. Vermietung - evaluated as of this segment's
            # own occupancy_end, per the object itself (not the billing
            # unit), since option rate can be set individually per
            # rental object.
            fraction = OptionRate.get_current_rate_fraction(
                'base_object', obj, values['occupancy_end'])
            values['vat_treatment_flag'] = 1 if fraction else 0

            # Fields 27/30 (Heizung/Warmwasser Grundanteil): the object's
            # own, direct measurement value (not time-weighted, not
            # affected by the consumption/area allocation split) for the
            # heating_area_measurement_type of its central-heating/
            # -hot-water settlement unit, if any.
            heating_base_share, heating_base_key = self._heating_base_share(
                values['occupancy_end'])
            if heating_base_share is not None:
                values['heating_base_share'] = heating_base_share
                if heating_base_key:
                    values['heating_base_key'] = heating_base_key

            hotwater_base_share, hotwater_base_key = self._hotwater_base_share(
                values['occupancy_end'])
            if hotwater_base_share is not None:
                values['hotwater_base_share'] = hotwater_base_share
                if hotwater_base_key:
                    values['hotwater_base_key'] = hotwater_base_key

            # Fields 36-41 (Schlüssel/Anteil Umlage 1-3): key from the
            # provider assignment's 'M-Satz Allocation Key 1/2/3', share
            # from this object's own measurement value for the key's
            # mapped measurement type (see BvedUnit/_allocation_shares()).
            for i, entry_ in enumerate(
                    self._allocation_shares(values['occupancy_end']),
                    start=1):
                if entry_ is None:
                    continue
                code, share = entry_
                values[f'allocation{i}_key'] = code
                if share is not None:
                    values[f'allocation{i}_share'] = share

            tenant_party = None
            if entry and entry.state == 'rented' and entry.contract:
                tenant_party = entry.contract.contractual_partner
            if tenant_party:
                if field7_mode in ('1', '3'):
                    values['tenant_name1'] = tenant_party.name[:35]
                    t_address = tenant_party.address_get()
                    if t_address:
                        values['tenant_street'] = _first_line(
                            t_address.street)[:35]
                        values['tenant_country'] = (
                            t_address.country.code3
                            if t_address.country else '')
                        values['tenant_postal_code'] = (
                            t_address.postal_code or '')
                        values['tenant_city'] = t_address.city or ''
                konto, blz = _bank_fields(tenant_party, warnings, 'Mieter')
                values['bank_account_number'] = konto
                values['bank_code'] = blz
            else:
                values['vacancy_flag'] = 1

            # Leistungsnehmer (fields 59-66): only for field 7 = '4',
            # per 'Leistungsnehmer-Regel' ('tenant': same party as the
            # Nutzer block above; 'role': the role-based lookup resolved
            # once for the whole call, see debtor_role_party above).
            if field7_mode == '4':
                debtor_party = (
                    tenant_party if tenant_rule == 'tenant'
                    else debtor_role_party)
                if debtor_party:
                    values['debtor_name1'] = debtor_party.name[:35]
                    d_address = debtor_party.address_get()
                    if d_address:
                        values['debtor_street'] = _first_line(
                            d_address.street)[:35]
                        values['debtor_country'] = (
                            d_address.country.code3
                            if d_address.country else '')
                        values['debtor_postal_code'] = (
                            d_address.postal_code or '')
                        values['debtor_city'] = d_address.city or ''

            # Leistungsgeber (fields 42-49) - independent of field 7,
            # resolved once for the whole call, see org_party above.
            if org_party:
                values['provider_org_name1'] = org_party.name[:35]
                if org_address:
                    values['provider_org_street'] = _first_line(
                        org_address.street)[:35]
                    values['provider_org_country'] = (
                        org_address.country.code3
                        if org_address.country else '')
                    values['provider_org_postal_code'] = (
                        org_address.postal_code or '')
                    values['provider_org_city'] = (
                        org_address.city or '')

            # Fields 50/51 (Kennzeichen USt-ID/Steuernummer, USt-ID-Nr.
            # oder Steuernummer): the company party's own
            # party.identifier of the type configured on the provider
            # as 'Tax ID Identification Type' - always the company
            # party specifically (not org_party, which may resolve to a
            # different role-based party). Field 50 comes from the
            # provider's own 'M-Satz Field 50 (Tax ID Flag)' catalog
            # selection (falls back to 2=Steuernummer if unset, e.g. on
            # a provider configured before this field existed).
            if company_party and provider and provider.tax_id_type:
                tax_identifiers = Identifier.search([
                    ('party', '=', company_party.id),
                    ('type', '=', provider.tax_id_type),
                    ], limit=1)
                if tax_identifiers:
                    values['tax_id_flag'] = (
                        int(provider.tax_id_flag)
                        if provider.tax_id_flag else 2)
                    values['tax_id'] = tax_identifiers[0].code[:16]

            # Field 52 (Kennzeichen Steuersatz): written unchanged from
            # the provider's own catalog selection, if set.
            if provider and provider.tax_rate_flag:
                values['tax_rate_flag'] = int(provider.tax_rate_flag)

            # Fields 53/54 (Kennzeichen Rechnungsnummer / Rechnungs-
            # nummer): field 53 from the provider's own catalog
            # selection; field 54 only when field 53 is '1' (aus Feld
            # 54), per 'Rechnungsnummer-Regel'.
            if provider and provider.invoice_number_flag:
                values['invoice_number_flag'] = int(
                    provider.invoice_number_flag)
                if provider.invoice_number_flag == '1':
                    invoice_number = None
                    contract = entry.contract if entry else None
                    if provider.invoice_number_rule == 'contract':
                        if contract:
                            invoice_number = contract.contract_number
                    elif provider.invoice_number_rule == 'object':
                        invoice_number = obj.object_number
                    elif provider.invoice_number_rule == 'settlement_result':
                        results = SettlementResult.search([
                            ('base_object', '=', obj.id),
                            ('contract', '=', contract.id if contract else None),
                            ('billing_unit.start_date', '<=', period_end),
                            ('billing_unit.end_date', '>=', period_start),
                            ], limit=1)
                        if results:
                            invoice_number = str(results[0].id)
                    if invoice_number:
                        values['invoice_number'] = invoice_number[:25]

            # Field 58 (Kennzeichen Zahlungsart): written unchanged from
            # the provider's own catalog selection, if set.
            if provider and provider.direct_debit_flag:
                values['direct_debit_flag'] = int(provider.direct_debit_flag)

            rows.append(values)
        return rows

    @classmethod
    @ModelView.button
    def refresh_m_satz_preview(cls, object_numbers):
        """(Re)compute m_satz_lines from _m_satz_values() for the most
        recently completed calendar year - deletes any existing preview
        lines for each object number first, so re-clicking after a
        tenant change or a year rollover always reflects the current
        data (unlike the L-Satz scalar preview fields, this one is a
        real stored O2M and therefore does not update itself merely by
        being viewed - see the read-only-transaction note on
        _m_satz_values())."""
        pool = Pool()
        Line = pool.get('real_estate.bved.object_number.m_satz_line')
        BvedProviderAssignment = pool.get(
            'real_estate.bved.provider_assignment')
        period_start, period_end = BvedProviderAssignment._last_full_year()
        for mapping in object_numbers:
            existing = Line.search([('object_number', '=', mapping.id)])
            if existing:
                Line.delete(existing)
            assignment = mapping.provider_assignment
            provider = assignment.provider if assignment else None
            company_party = None
            company_address = None
            company = assignment.company if assignment else None
            if company:
                company_party = company.party
                company_address = company_party.address_get()
            rows = mapping._m_satz_values(
                period_start, period_end, provider, company_party,
                company_address, refresh_occupancy=True)
            to_create = []
            for index, row in enumerate(rows, start=1):
                values = dict(row)
                values['object_number'] = mapping.id
                values['sequence'] = index * 10
                values['vacancy_flag'] = bool(values.get('vacancy_flag'))
                values['record_type'] = bved_records.DEFAULTS['M']['satzart']
                values['arge_version'] = (
                    bved_records.DEFAULTS['M']['arge_version'])
                to_create.append(values)
            if to_create:
                Line.create(to_create)


#**********************************************************************
class BvedObjectNumberMSatzLine(sequence_ordered(), ModelSQL, ModelView):
    """BVED Object Number M-Satz Preview Line - one row per occupancy
    segment, holding every M-Satz field 1-70 (see the BVED spec's
    Nutzersatz table) for review before an actual export. Generated by
    BvedObjectNumber.refresh_m_satz_preview() from
    BvedObjectNumber._m_satz_values() - never edited directly (all
    fields readonly), and safe to delete/regenerate at any time."""
    __name__ = 'real_estate.bved.object_number.m_satz_line'

    object_number = fields.Many2One(
        'real_estate.bved.object_number', "Object Number",
        required=True, ondelete='CASCADE')

    # Fields 1-6: identification (same for every line of one mapping)
    record_type = fields.Char("1. Record Type", readonly=True)
    arge_version = fields.Char("2. ARGE Version", readonly=True)
    customer_number = fields.Char("3. Customer Number", readonly=True)
    provider_key = fields.Char("4. Provider Key", readonly=True)
    provider_reference = fields.Char("5. Provider Reference", readonly=True)
    internal_reference = fields.Char("6. Internal Reference", readonly=True)

    # Fields 7-15: address flag + tenant (Nutzer)
    address_flag = fields.Integer("7. Address Flag", readonly=True,
        help="1=Nutzer, 2=Eigentümer, 3=Eigentümer/Nutzer, "
             "4=Leistungsnehmer - from the provider's 'M-Satz Field 7 "
             "(Address Type)', written unchanged into every M-Satz "
             "record of that provider.")
    tenant_name1 = fields.Char("8. Tenant Name 1", readonly=True,
        help="Filled only when the provider's 'M-Satz Field 7' is "
             "'Nutzer' or 'Eigentümer/Nutzer'.")
    tenant_name2 = fields.Char("9. Tenant Name 2", readonly=True)
    tenant_name3 = fields.Char("10. Tenant Name 3", readonly=True)
    tenant_name4 = fields.Char("11. Tenant Name 4", readonly=True)
    tenant_street = fields.Char("12. Tenant Street", readonly=True)
    tenant_country = fields.Char("13. Tenant Country", readonly=True)
    tenant_postal_code = fields.Char("14. Tenant Postal Code", readonly=True)
    tenant_city = fields.Char("15. Tenant City", readonly=True)

    # Fields 16-23: owner (Eigentümer)
    owner_name1 = fields.Char("16. Owner Name 1", readonly=True,
        help="Filled only when the provider's 'M-Satz Field 7' is "
             "'Eigentümer' or 'Eigentümer/Nutzer', per "
             "'Eigentümer-Regel'.")
    owner_name2 = fields.Char("17. Owner Name 2", readonly=True)
    owner_name3 = fields.Char("18. Owner Name 3", readonly=True)
    owner_name4 = fields.Char("19. Owner Name 4", readonly=True)
    owner_street = fields.Char("20. Owner Street", readonly=True)
    owner_country = fields.Char("21. Owner Country", readonly=True)
    owner_postal_code = fields.Char("22. Owner Postal Code", readonly=True)
    owner_city = fields.Char("23. Owner City", readonly=True)

    # Field 24: Wohnzeitraum (split into start/end)
    occupancy_start = fields.Date("24. Occupancy Start", readonly=True)
    occupancy_end = fields.Date("24. Occupancy End", readonly=True)

    # Fields 25-35: VAT / vacancy risk / heating-hotwater-coldwater shares
    vat_treatment_flag = fields.Integer(
        "25. VAT Treatment Flag", readonly=True,
        help="0 = kein Ausweis if the object's own Optionssatz is 0% (or "
             "unknown) as of this segment's occupancy_end, else "
             "1 = gewerbl. Vermietung.")
    vacancy_risk_calc_flag = fields.Integer(
        "26. Vacancy Risk Calc Flag", readonly=True,
        help="0 = kein, 1 = Berechnung - taken from the provider "
             "assignment's own L-Satz field 13 ('Vacancy Risk "
             "Surcharge', vacancy_risk_flag).")
    heating_base_share = fields.Numeric(
        "27. Heating Base Share", digits=(8, 2), readonly=True,
        help="The object's own measurement value for the 'Area "
             "Measurement Type (Heating Cost Split)' of its "
             "central-heating settlement unit, if any - the object's "
             "plain Bemessung, not time-weighted and not affected by "
             "the consumption/area allocation split.")
    heating_advance_gross = fields.Numeric(
        "28. Heating Advance (gross)", digits=(8, 2), readonly=True)
    heating_advance_net = fields.Numeric(
        "29. Heating Advance (net)", digits=(8, 2), readonly=True)
    hotwater_base_share = fields.Numeric(
        "30. Hot Water Base Share", digits=(8, 2), readonly=True,
        help="The object's own measurement value for the 'Area "
             "Measurement Type (Heating Cost Split)' of its "
             "central-hot-water settlement unit, if any - the object's "
             "plain Bemessung, not time-weighted and not affected by "
             "the consumption/area allocation split.")
    hotwater_advance_gross = fields.Numeric(
        "31. Hot Water Advance (gross)", digits=(8, 2), readonly=True)
    hotwater_advance_net = fields.Numeric(
        "32. Hot Water Advance (net)", digits=(8, 2), readonly=True)
    coldwater_base_share = fields.Numeric(
        "33. Cold Water Base Share", digits=(8, 2), readonly=True)
    coldwater_advance_gross = fields.Numeric(
        "34. Cold Water Advance (gross)", digits=(8, 2), readonly=True)
    coldwater_advance_net = fields.Numeric(
        "35. Cold Water Advance (net)", digits=(8, 2), readonly=True)

    # Fields 36-41: allocation keys/shares - from the provider
    # assignment's 'M-Satz Allocation Key 1/2/3' (real_estate.bved.unit)
    # and this object's own measurement value for the unit's mapped
    # measurement type, see BvedObjectNumber._allocation_shares().
    allocation1_key = fields.Char("36. Allocation 1 Key", readonly=True,
        help="Tabelle 'E' code of the provider assignment's 'M-Satz "
             "Allocation Key 1', if set.")
    allocation1_share = fields.Numeric(
        "37. Allocation 1 Share", digits=(8, 2), readonly=True,
        help="This object's measurement value for the measurement type "
             "mapped to 'M-Satz Allocation Key 1'.")
    allocation2_key = fields.Char("38. Allocation 2 Key", readonly=True,
        help="Tabelle 'E' code of the provider assignment's 'M-Satz "
             "Allocation Key 2', if set.")
    allocation2_share = fields.Numeric(
        "39. Allocation 2 Share", digits=(8, 2), readonly=True,
        help="This object's measurement value for the measurement type "
             "mapped to 'M-Satz Allocation Key 2'.")
    allocation3_key = fields.Char("40. Allocation 3 Key", readonly=True,
        help="Tabelle 'E' code of the provider assignment's 'M-Satz "
             "Allocation Key 3', if set.")
    allocation3_share = fields.Numeric(
        "41. Allocation 3 Share", digits=(8, 2), readonly=True,
        help="This object's measurement value for the measurement type "
             "mapped to 'M-Satz Allocation Key 3'.")

    # Fields 42-49: provider organization (Leistungsgeber)
    provider_org_name1 = fields.Char("42. Provider Org Name 1", readonly=True,
        help="Filled per the provider's 'M-Satz Leistungsgeber-Regel' - "
             "independent of 'M-Satz Field 7'.")
    provider_org_name2 = fields.Char("43. Provider Org Name 2", readonly=True)
    provider_org_name3 = fields.Char("44. Provider Org Name 3", readonly=True)
    provider_org_name4 = fields.Char("45. Provider Org Name 4", readonly=True)
    provider_org_street = fields.Char(
        "46. Provider Org Street", readonly=True)
    provider_org_country = fields.Char(
        "47. Provider Org Country", readonly=True)
    provider_org_postal_code = fields.Char(
        "48. Provider Org Postal Code", readonly=True)
    provider_org_city = fields.Char("49. Provider Org City", readonly=True)

    # Fields 50-58: tax / invoice / bank / payment
    tax_id_flag = fields.Integer("50. Tax ID Flag", readonly=True,
        help="1 = USt-ID-Nr., 2 = Steuernummer (field 51) - from the "
             "provider's own 'M-Satz Field 50 (Tax ID Flag)', written "
             "whenever the provider's 'Tax ID Identification Type' "
             "matches an identifier on the company party.")
    tax_id = fields.Char("51. Tax ID", readonly=True,
        help="The company party's own party.identifier code for the "
             "type configured on the provider's 'Tax ID Identification "
             "Type'.")
    tax_rate_flag = fields.Integer("52. Tax Rate Flag", readonly=True,
        help="1 = Regelsteuersatz, 2 = ermäßigt - from the provider's "
             "own 'M-Satz Field 52 (Tax Rate Flag)'.")
    invoice_number_flag = fields.Integer(
        "53. Invoice Number Flag", readonly=True,
        help="0 = keine Rechnung §14 UStG, 1 = aus Feld 54, "
             "2 = vom Abrechnungsunternehmen erstellt - from the "
             "provider's own 'M-Satz Field 53 (Invoice Number Flag)'.")
    invoice_number = fields.Char("54. Invoice Number", readonly=True,
        help="Filled only when field 53 is 1 (aus Feld 54), per the "
             "provider's 'Rechnungsnummer-Regel'.")
    bank_account_number = fields.Char(
        "55. Bank Account Number", readonly=True)
    bank_code = fields.Char("56. Bank Code", readonly=True)
    company_flag = fields.Integer("57. Company Flag", readonly=True)
    direct_debit_flag = fields.Integer("58. Direct Debit Flag", readonly=True,
        help="0 = keine Abbuchungserlaubnis, 1 = Abbuchungserlaubnis - "
             "from the provider's own 'M-Satz Field 58 (Payment Type "
             "Flag)'.")

    # Fields 59-66: debtor (Leistungsnehmer)
    debtor_name1 = fields.Char("59. Debtor Name 1", readonly=True,
        help="Filled only when the provider's 'M-Satz Field 7' is "
             "'Leistungsnehmer', per 'Leistungsnehmer-Regel'.")
    debtor_name2 = fields.Char("60. Debtor Name 2", readonly=True)
    debtor_name3 = fields.Char("61. Debtor Name 3", readonly=True)
    debtor_name4 = fields.Char("62. Debtor Name 4", readonly=True)
    debtor_street = fields.Char("63. Debtor Street", readonly=True)
    debtor_country = fields.Char("64. Debtor Country", readonly=True)
    debtor_postal_code = fields.Char("65. Debtor Postal Code", readonly=True)
    debtor_city = fields.Char("66. Debtor City", readonly=True)

    # Fields 67-70
    vacancy_flag = fields.Boolean("67. Vacancy Flag", readonly=True)
    tenant_change_fee_flag = fields.Integer(
        "68. Tenant Change Fee Flag", readonly=True,
        help="0 = keine Umlage, 1 = Umlage - from the provider "
             "assignment's own 'M-Satz Field 68 (Tenant Change Fee "
             "Flag)'.")
    heating_base_key = fields.Char("69. Heating Base Key", readonly=True,
        help="Tabelle 'E' code of the real_estate.bved.unit mapped to "
             "the settlement unit's 'Area Measurement Type (Heating "
             "Cost Split)' - the measurement field 27 is expressed in.")
    hotwater_base_key = fields.Char("70. Hot Water Base Key", readonly=True,
        help="Tabelle 'E' code of the real_estate.bved.unit mapped to "
             "the settlement unit's 'Area Measurement Type (Heating "
             "Cost Split)' - the measurement field 30 is expressed in.")


#**********************************************************************
class BvedExportBillingUnit(ModelSQL):
    "BVED Export - Billing Unit"
    __name__ = 'real_estate.bved.export-billing_unit'

    export = fields.Many2One('real_estate.bved.export', "Export",
        ondelete='CASCADE', required=True)
    billing_unit = fields.Many2One('real_estate.billing_unit',
        "Billing Unit", ondelete='CASCADE', required=True)


#**********************************************************************
class BvedExport(Workflow, ModelSQL, ModelView):
    "BVED Export"
    __name__ = 'real_estate.bved.export'
    __rec_name__ = 'name'

    provider = fields.Many2One(
        'real_estate.bved.service_provider', "Provider", required=True,
        ondelete='RESTRICT',
        states={'readonly': Eval('state') != 'draft'})

    cutoff_date = fields.Date("Cutoff Date", required=True,
        states={'readonly': Eval('state') != 'draft'},
        help="Only billing units whose period has already ended on or "
             "before this date are eligible for export - matches the "
             "BVED rhythm (export happens once a property's billing year "
             "is fully over, so its K-Satz cost data is complete; a "
             "still-running period may still see tenant/object changes "
             "and should not be exported yet). Defaults to 31 December "
             "of the previous year.")

    billing_units = fields.Many2Many(
        'real_estate.bved.export-billing_unit', 'export', 'billing_unit',
        "Billing Units",
        states={'readonly': Eval('state') != 'draft'},
        domain=[
            ('bved_provider_assignment.provider', '=', Eval('provider', -1)),
            ('external_billing', '=', True),
            ('end_date', '<=', Eval('cutoff_date', None)),
            ],
        depends=['provider', 'cutoff_date'],
        help="Defaults to every billing unit currently assigned to the "
             "selected provider whose period has ended by the cutoff "
             "date; deselect any that should not be part of this export "
             "run, or add further ones (all must have this same "
             "provider and an end date on or before the cutoff date).")

    company = fields.Function(
        fields.Many2One('company.company', "Company"),
        'on_change_with_company', searcher='search_company')

    name = fields.Function(fields.Char("Name"), 'on_change_with_name',
        searcher='search_name')

    state = fields.Selection([
            ('draft', 'Draft'),
            ('generated', 'Generated'),
            ('sent', 'Sent'),
            ], "State", sort=False, readonly=True)

    export_date = fields.DateTime("Export Date", readonly=True)

    export_date_date = fields.Function(
        fields.Date("Export Date"), 'on_change_with_export_date_date')

    export_date_time = fields.Function(
        fields.Time("Export Time"), 'on_change_with_export_date_time')

    record_types = fields.MultiSelection([
            ('A', 'A-Satz (Zuordnung)'),
            ('L', 'L-Satz (Liegenschaft)'),
            ('M', 'M-Satz (Nutzer/Eigentümer)'),
            ('B', 'B-Satz (Brennstoff/Verbrauch)'),
            ('K', 'K-Satz (Kosten)'),
            ], "Record Types",
        states={'readonly': Eval('state') != 'draft'})

    activity_log = fields.Text("Log", readonly=True)

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._transitions |= set((
            ('draft', 'generated'),
            ('generated', 'sent'),
            ))
        cls._buttons.update({
                'generate': {
                    'invisible': Eval('state') != 'draft',
                    'depends': ['state'],
                    },
                'mark_sent': {
                    'invisible': Eval('state') != 'generated',
                    'depends': ['state'],
                    },
                })

    @classmethod
    def default_state(cls):
        return 'draft'

    @classmethod
    def default_record_types(cls):
        return ['A', 'L', 'M', 'B', 'K']

    @classmethod
    def default_cutoff_date(cls):
        today = datetime.date.today()
        return datetime.date(today.year - 1, 12, 31)

    def _default_billing_units(self):
        """Every billing unit assigned to the selected provider whose
        period has already ended by the cutoff date - the user can still
        deselect some or add further ones (all must share this provider
        and end on or before the cutoff date, enforced by the field's own
        domain)."""
        if self.provider and self.cutoff_date:
            BillingUnit = Pool().get('real_estate.billing_unit')
            return BillingUnit.search([
                ('bved_provider_assignment.provider', '=', self.provider.id),
                ('external_billing', '=', True),
                ('end_date', '<=', self.cutoff_date),
                ])
        return []

    @fields.depends('provider', 'cutoff_date', 'billing_units')
    def on_change_provider(self):
        self.billing_units = self._default_billing_units()

    @fields.depends('provider', 'cutoff_date', 'billing_units')
    def on_change_cutoff_date(self):
        self.billing_units = self._default_billing_units()

    @fields.depends('billing_units')
    def on_change_with_company(self, name=None):
        for bu in (self.billing_units or []):
            if bu.property:
                return bu.property.company
        return None

    @classmethod
    def search_company(cls, name, clause):
        return [('billing_units.property.company',) + tuple(clause[1:])]

    @fields.depends('provider', 'billing_units', 'export_date', 'state')
    def on_change_with_name(self, name=None):
        return '%s / %d Billing Unit(s) / %s' % (
            self.provider.rec_name if self.provider else '?',
            len(self.billing_units or []),
            self.export_date or self.state)

    @classmethod
    def search_name(cls, name, clause):
        _, operator, value = clause
        return ['OR',
            ('provider.rec_name', operator, value),
            ('state', operator, value),
            ]

    @fields.depends('export_date')
    def on_change_with_export_date_date(self, name=None):
        return self.export_date.date() if self.export_date else None

    @fields.depends('export_date')
    def on_change_with_export_date_time(self, name=None):
        return self.export_date.time() if self.export_date else None

    def _log(self, text):
        stamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        entry = '[%s] %s' % (stamp, text)
        self.activity_log = ('%s\n%s' % (self.activity_log, entry)) if self.activity_log else entry

    @staticmethod
    def _provider_reference(bu, external_unit_number=None):
        assignment = bu.bved_provider_assignment
        prop_no = ((assignment.external_property_number if assignment else '')
            or '').rjust(9, '0')[:9]
        unit_no = (external_unit_number or '0000').rjust(4, '0')[:4]
        return prop_no + unit_no

    def _ensure_object_numbers(self, bu):
        pool = Pool()
        ObjectNumber = pool.get('real_estate.bved.object_number')
        assignment = bu.bved_provider_assignment

        existing = ObjectNumber.search([
            ('provider_assignment', '=', assignment.id),
            ] + _valid_overlap_domain(bu.start_date, bu.end_date))
        existing_object_ids = {mapping.base_object.id for mapping in existing}
        # Only objects actually covered by at least one of this billing
        # unit's settlement units (each one's own reg_ex_object scoping
        # applies) get an object number - e.g. a parking space with no
        # heating settlement unit never gets a cost share/settlement
        # result internally, so giving it one here would produce an
        # M-Satz/A-Satz entry that can never be matched on D-Satz import.
        relevant_object_ids = bu.bved_covered_object_ids()
        # Numbering is scoped per assignment (property/building), not per
        # billing unit, and counts ALL-TIME (not just currently-valid
        # rows) so a renumbered/closed mapping's external_unit_number is
        # never reused by a later one.
        next_no = ObjectNumber.search_count([
            ('provider_assignment', '=', assignment.id),
            ]) + 1
        to_create = []
        for obj_id in relevant_object_ids:
            if obj_id in existing_object_ids:
                continue
            to_create.append({
                'provider_assignment': assignment.id,
                'base_object': obj_id,
                'external_unit_number': str(next_no).rjust(4, '0'),
                'internal_reference': 'OBJ-%d' % obj_id,
                'valid_from': bu.start_date,
                })
            next_no += 1
        if to_create:
            new_ones = ObjectNumber.create(to_create)
            self._log(
                'Objektnummern-Mapping: %d neue Zuordnung(en) automatisch '
                'angelegt (%s).' % (
                    len(new_ones),
                    ', '.join(m.base_object.rec_name for m in new_ones)))

    def _build_a_records(self, files):
        pool = Pool()
        ObjectNumber = pool.get('real_estate.bved.object_number')
        lines = []
        for bu in self.billing_units:
            assignment = bu.bved_provider_assignment
            mappings = ObjectNumber.search([
                ('provider_assignment', '=', assignment.id),
                ('base_object', 'in', bu.bved_covered_object_ids()),
                ] + _valid_overlap_domain(bu.start_date, bu.end_date),
                order=[('external_unit_number', 'ASC')])
            lines.extend(bved_records.pack('A', {
                    'customer_number': assignment.customer_number,
                    'provider_key': self.provider.bved_key,
                    'provider_reference': self._provider_reference(
                        bu, mapping.external_unit_number),
                    'internal_reference': mapping.internal_reference,
                    }) for mapping in mappings)
        if lines:
            files[bved_records.bved_filename('A', datetime.datetime.now())] = lines

    def _build_l_m_records(self, files, record_types):
        pool = Pool()
        ObjectNumber = pool.get('real_estate.bved.object_number')
        lines = []

        # One L-/M-Satz block per billing unit. Note: if two billing
        # units in this export share the same property (e.g. separate
        # "Heizkosten"/"Kaltwasser" units), the property's L-Satz is
        # emitted once per billing unit - deduplication is left to the
        # provider's own matching, to keep this loop simple.
        for bu in self.billing_units:
            prop = bu.property
            assignment = bu.bved_provider_assignment

            if 'L' in record_types:
                address = prop.address
                vat_flag = assignment._vat_flag([bu], bu.end_date)
                non_residential = bu.non_residential_flag
                lines.append(bved_records.pack('L', {
                    'customer_number': assignment.customer_number,
                    'provider_key': self.provider.bved_key,
                    'provider_reference': self._provider_reference(bu),
                    'vat_flag': vat_flag,
                    'street': address.street_single_line if address else '',
                    'country': (address.country.code3
                        if address and address.country else ''),
                    'postal_code': address.postal_code if address else '',
                    'city': address.city if address else '',
                    'object_number': assignment.external_property_number,
                    'period_start': bu.start_date,
                    'period_end': bu.end_date,
                    'currency': bu.currency.code if bu.currency else 'EUR',
                    'weg_flag':
                        1 if bu.calculation_method == 'WEG_billing' else 0,
                    'total_area': assignment._total_area(
                        [bu], assignment.gross_floor_area_measurement_type),
                    'non_residential_flag': 1 if non_residential else 0,
                    'vacancy_risk_flag':
                        1 if assignment.vacancy_risk_flag else 0,
                    'vacancy_risk_percent': assignment.vacancy_risk_percent,
                    'labor_share_flag':
                        1 if assignment.labor_share_flag else 0,
                    'energy_improvement_flag':
                        1 if assignment.energy_improvement_flag else 0,
                    'heat_supply_flag':
                        1 if assignment.heat_supply_flag else 0,
                    'co2_landlord_share_percent':
                        assignment._co2_landlord_share([bu]),
                    'heat_connection_2023_flag':
                        1 if assignment.heat_connection_2023_flag else 0,
                    }))

            if 'M' not in record_types:
                continue

            company_party = prop.company.party
            company_address = company_party.address_get()
            mappings = ObjectNumber.search([
                ('provider_assignment', '=', assignment.id),
                ('base_object', 'in', bu.bved_covered_object_ids()),
                ] + _valid_overlap_domain(bu.start_date, bu.end_date))
            for mapping in mappings:
                warnings = []
                rows = mapping._m_satz_values(
                    bu.start_date, bu.end_date, self.provider,
                    company_party, company_address, warnings)
                for warning in warnings:
                    self._log(warning)
                lines.extend(bved_records.pack('M', v) for v in rows)

        if lines:
            files[bved_records.bved_filename('L', datetime.datetime.now())] = lines

    def _build_b_k_records(self, files, record_types):
        pool = Pool()
        InvoiceLine = pool.get('account.invoice.line')
        lines = []

        for bu in self.billing_units:
            assignment = bu.bved_provider_assignment
            settlement_units = [
                su for su in bu.settlement_units
                if su.allocation_rule == 'allocation_from_external_billing']

            if 'B' in record_types:
                for su in settlement_units:
                    if not su.bved_fuel_data:
                        continue
                    base_values = {
                        'customer_number': assignment.customer_number,
                        'provider_key': self.provider.bved_key,
                        'provider_reference': self._provider_reference(bu),
                        'currency': bu.currency.code if bu.currency else 'EUR',
                        'period_start': bu.start_date,
                        'period_end': bu.end_date,
                        'fuel_type': su.bved_fuel_type,
                        'heating_value': su.bved_heating_value,
                        'fuel_indicator_flag': su.bved_fuel_indicator,
                        'stock_start_date': su.bved_stock_start_date,
                        'stock_start_quantity': su.bved_stock_start_quantity,
                        'stock_start_amount_gross':
                            su.bved_stock_start_amount_gross,
                        'stock_start_amount_net': su.bved_stock_start_amount_net,
                        'stock_end_date': su.bved_stock_end_date,
                        'stock_end_quantity': su.bved_stock_end_quantity,
                        'stock_end_amount_gross': su.bved_stock_end_amount_gross,
                        'stock_end_amount_net': su.bved_stock_end_amount_net,
                        'ww_temperature': su.bved_ww_temperature,
                        'ww_consumption_m3': su.bved_ww_consumption_m3,
                        'ww_percentage': su.bved_ww_percentage,
                        'ww_meter_start': su.bved_ww_meter_start,
                        'ww_meter_end': su.bved_ww_meter_end,
                        'supply_heating1_start':
                            su.bved_supply_period_heating_1_start,
                        'supply_heating1_end':
                            su.bved_supply_period_heating_1_end,
                        'supply_heating2_start':
                            su.bved_supply_period_heating_2_start,
                        'supply_heating2_end':
                            su.bved_supply_period_heating_2_end,
                        'supply_ww1_start': su.bved_supply_period_ww_1_start,
                        'supply_ww1_end': su.bved_supply_period_ww_1_end,
                        'supply_ww2_start': su.bved_supply_period_ww_2_start,
                        'supply_ww2_end': su.bved_supply_period_ww_2_end,
                        'meter_type': su.bved_meter_type,
                        'meter_unit': (
                            su.bved_meter_measurement_unit.code
                            if su.bved_meter_measurement_unit else None),
                        'meter_number': su.bved_meter_number,
                        'consumption': su.bved_meter_consumption,
                        'meter_reading_start': su.bved_meter_reading_start,
                        'meter_reading_end': su.bved_meter_reading_end,
                        'primary_energy_factor': su.bved_primary_energy_factor,
                        }
                    # Feld 10-22 (Bestandsführung) and Feld 28-34 (Zähler)
                    # are mutually exclusive on the form (bved_fuel_rule),
                    # but both sets of keys are always packed here - the
                    # unused group's fields are simply left empty by the
                    # user and pack() writes them blank/zero as usual.
                    lines.append(bved_records.pack('B', base_values))

            if 'K' in record_types:
                for su in settlement_units:
                    # Cost/invoice lines are not only booked directly on
                    # su - a settlement unit using 'allocation_via_cost_
                    # collector' with su as its reference_settlement_unit
                    # (e.g. a second fuel supplier feeding the same
                    # heating settlement unit) can carry its own invoice
                    # lines too. Each keeps its own cost type's
                    # bved_cost_key, since the invoices may classify
                    # differently even though they all feed the same
                    # externally-billed unit.
                    source_units = [su] + [
                        other for other in bu.settlement_units
                        if other.allocation_rule == 'allocation_via_cost_collector'
                        and other.reference_settlement_unit
                        and other.reference_settlement_unit.id == su.id]
                    for source_su in source_units:
                        invoice_lines = InvoiceLine.search([
                            ('settlement_unit', '=', source_su.id),
                            ('invoice.state', '!=', 'cancelled'),
                            ])
                        for line in invoice_lines:
                            cost_key = (
                                source_su.type.bved_cost_key
                                if source_su.type else None)
                            estg = getattr(line, 'estg_35a', '') or ''
                            labor_pct = getattr(
                                line, 'estg_35a_labor_share_percent', None)
                            gross = line.total_amount
                            labor_amount = None
                            if labor_pct is not None and gross is not None:
                                labor_amount = (
                                    gross * labor_pct / Decimal(100)
                                    ).quantize(Decimal('0.01'))
                            lines.append(bved_records.pack('K', {
                                'customer_number': assignment.customer_number,
                                'provider_key': self.provider.bved_key,
                                'provider_reference': self._provider_reference(bu),
                                'cost_type_key': cost_key,
                                'uniform_cost_flag': 'E',
                                'invoice_date': line.invoice_date,
                                'quantity': getattr(
                                    line, 'bved_fuel_quantity', None),
                                'amount_gross': gross,
                                'amount_net': line.amount,
                                'tax_service_type_key':
                                    bved_records.ESTG35A_TO_TABLE_L.get(estg, '00'),
                                'labor_share_amount': labor_amount,
                                'fuel_indicator_flag':
                                    1 if getattr(line, 'bved_fuel_type', None)
                                    else 0,
                                }))

                    for consumption in su._co2_consumption_rows():
                        energy_mix = sorted(
                            consumption.energy_mix,
                            key=lambda row: row.sequence or 0)[:6]
                        k_values = {
                            'customer_number': assignment.customer_number,
                            'provider_key': self.provider.bved_key,
                            'provider_reference': self._provider_reference(bu),
                            'uniform_cost_flag': 'E',
                            'co2_emission_quantity': consumption.co2_emission_kg,
                            'co2_cost_gross': consumption.co2_cost_gross,
                            'co2_cost_net': consumption.co2_cost_net,
                            }
                        for i, mix in enumerate(energy_mix, start=1):
                            k_values['energy_source_%d' % i] = mix.energy_source
                            k_values['energy_share_%d' % i] = mix.share_percent
                            k_values['energy_emission_factor_%d' % i] = (
                                mix.emission_factor)
                        lines.append(bved_records.pack('K', k_values))

        if lines:
            files[bved_records.bved_filename('B', datetime.datetime.now())] = lines

    @classmethod
    @ModelView.button
    @Workflow.transition('generated')
    def generate(cls, exports):
        pool = Pool()
        Attachment = pool.get('ir.attachment')

        for export in exports:
            if not export.provider:
                raise ValidationError(gettext(
                    'real_estate.msg_bved_export_missing_provider',
                    name=export.rec_name))
            if not export.billing_units:
                raise ValidationError(gettext(
                    'real_estate.msg_bved_export_no_billing_units',
                    name=export.rec_name))
            for bu in export.billing_units:
                assignment = bu.bved_provider_assignment
                if not assignment:
                    raise ValidationError(gettext(
                        'real_estate.msg_bved_export_missing_assignment',
                        name=bu.name))
                if assignment.provider != export.provider:
                    raise ValidationError(gettext(
                        'real_estate.msg_bved_export_provider_mismatch',
                        name=bu.name, provider=assignment.provider.rec_name,
                        export_provider=export.provider.rec_name))
                address = bu.property.address
                if not (address and address.postal_code and address.city
                        and address.country):
                    raise ValidationError(gettext(
                        'real_estate.msg_bved_export_missing_address',
                        name=bu.property.rec_name))
                export._ensure_object_numbers(bu)

            record_types = export.record_types or []
            files = {}
            if 'A' in record_types:
                export._build_a_records(files)
            if 'L' in record_types or 'M' in record_types:
                export._build_l_m_records(files, record_types)
            if 'B' in record_types or 'K' in record_types:
                export._build_b_k_records(files, record_types)

            attachments = []
            for filename, lines in files.items():
                content = ('\r\n'.join(lines) + '\r\n').encode(
                    'iso-8859-1', errors='replace')
                attachments.append(Attachment(
                    resource=str(export),
                    name=filename,
                    data=content,
                    ))
            if attachments:
                Attachment.save(attachments)
                export._log('%d Datei(en) erzeugt: %s' % (
                    len(attachments),
                    ', '.join(a.name for a in attachments)))
            else:
                export._log('Keine Datei erzeugt (keine Datensätze für die '
                    'gewählten Satzarten).')

            export.export_date = datetime.datetime.now()
            export.state = 'generated'
            export.save()

    @classmethod
    @ModelView.button
    @Workflow.transition('sent')
    def mark_sent(cls, exports):
        for export in exports:
            export.state = 'sent'
            export._log('Als versendet markiert (Versand erfolgt außerhalb der App).')
            export.save()


#**********************************************************************
class BvedImport(Workflow, ModelSQL, ModelView):
    "BVED Import"
    __name__ = 'real_estate.bved.import'
    __rec_name__ = 'name'

    provider = fields.Many2One('real_estate.bved.service_provider',
        "Provider", required=True, ondelete='RESTRICT',
        states={'readonly': Eval('state') != 'draft'})

    company = fields.Many2One('company.company', "Company", required=True,
        states={'readonly': Eval('state') != 'draft'})

    name = fields.Function(fields.Char("Name"), 'on_change_with_name',
        searcher='search_name')

    state = fields.Selection([
            ('draft', 'Draft'),
            ('parsed', 'Parsed'),
            ('matched', 'Matched'),
            ('processed', 'Processed'),
            ], "State", sort=False, readonly=True)

    processed_files = fields.Text("Processed Files", readonly=True)

    activity_log = fields.Text("Log", readonly=True)

    lines = fields.One2Many('real_estate.bved.import.line', 'import_',
        "Lines", readonly=True)

    line_summary = fields.Function(
        fields.Text("Lines Summary"), 'get_line_summary')

    # Which field to sum per record type, and the label suffix that makes
    # its meaning unambiguous: D-Satz total_costs_gross is already this
    # object's own total, but P-/E835-Satz also carry a repeated
    # property-wide pool value (p_total_gross / labor_share_total) - only
    # the *_share_* field is additive across lines and may be summed here.
    _SUMMARY_RECORD_TYPES = (
        ('D', 'D-Satz', 'total_costs_gross', ''),
        ('P', 'P-Satz', 'p_user_share_gross', ' (Nutzeranteil)'),
        ('E835', 'E835-Satz', 'user_share_amount', ' (Nutzeranteil)'),
        ('E898', 'E898-Satz', None, ''),
        )
    _SUMMARY_STATES = ('parsed', 'matched', 'applied', 'skipped', 'error')

    def get_line_summary(self, name=None):
        currency_code = (
            self.company.currency.code if self.company
                and self.company.currency else '')
        grouped = {}
        for line in self.lines:
            grouped.setdefault(
                (line.record_type, line.state), []).append(line)

        parts = []
        for record_type, label, amount_field, suffix in (
                self._SUMMARY_RECORD_TYPES):
            rows = []
            for state in self._SUMMARY_STATES:
                group = grouped.get((record_type, state))
                if not group:
                    continue
                if amount_field:
                    total = sum(
                        (getattr(line, amount_field) or Decimal(0))
                        for line in group)
                    amount_text = '  %s %s%s' % (
                        _fmt_amount(total), currency_code, suffix)
                else:
                    amount_text = ''
                rows.append('  %-8s %3d Zeile(n)%s' % (
                    state, len(group), amount_text))
            if rows:
                parts.append('%s:' % label)
                parts.extend(rows)
        return '\n'.join(parts) if parts else None

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._transitions |= set((
            ('draft', 'parsed'),
            ('parsed', 'parsed'),
            ('matched', 'parsed'),
            ('parsed', 'matched'),
            ('matched', 'matched'),
            ('matched', 'processed'),
            ))
        cls._buttons.update({
                'parse': {
                    # Re-parsing is allowed at any point before 'processed'
                    # - e.g. more response files (E898 PDFs) may arrive
                    # after the first Match, or a stale test attachment
                    # gets replaced. Every click rebuilds all not-yet-
                    # applied lines from scratch from whatever is
                    # currently attached; already-'applied' lines are
                    # never touched.
                    'invisible': Eval('state') == 'processed',
                    'depends': ['state'],
                    },
                'match': {
                    # Visible in both 'parsed' and already-'matched' state,
                    # since Match is meant to be re-runnable: fixing a
                    # missing object number/settlement result and clicking
                    # Match again must re-evaluate previously
                    # error/skipped lines, not just newly parsed ones.
                    'invisible': ~Eval('state').in_(['parsed', 'matched']),
                    'depends': ['state'],
                    },
                'apply': {
                    # Only after at least one successful Match run - not
                    # directly from 'parsed', which would let matching be
                    # skipped entirely.
                    'invisible': Eval('state') != 'matched',
                    'depends': ['state'],
                    },
                })

    @classmethod
    def default_state(cls):
        return 'draft'

    @classmethod
    def default_company(cls):
        return Transaction().context.get('company')

    @fields.depends('provider', 'state', '_parent_provider.name')
    def on_change_with_name(self, name=None):
        return '%s / %s' % (
            self.provider.rec_name if self.provider else '?', self.state)

    @classmethod
    def search_name(cls, name, clause):
        _, operator, value = clause
        return ['OR',
            ('provider.rec_name', operator, value),
            ('state', operator, value),
            ]

    def _log(self, text):
        stamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        entry = '[%s] %s' % (stamp, text)
        self.activity_log = ('%s\n%s' % (self.activity_log, entry)) if self.activity_log else entry

    @classmethod
    @ModelView.button
    @Workflow.transition('parsed')
    def parse(cls, imports):
        pool = Pool()
        Attachment = pool.get('ir.attachment')
        ImportLine = pool.get('real_estate.bved.import.line')

        for import_ in imports:
            # Full fresh snapshot on every click, not an incremental,
            # per-filename skip: re-running a demo/simulation script
            # produces a NEW file name each time (timestamp in the
            # name), so name-based dedup would never recognise it as
            # "already seen" and old lines for the same object would
            # pile up alongside the new ones. Deleting every not-yet-
            # applied line first and rebuilding from whatever is
            # currently attached means there is always exactly one line
            # per record actually present right now - no duplicates,
            # no manual cleanup needed. 'applied' lines (already written
            # into a settlement_result) are never touched.
            stale_lines = ImportLine.search([
                ('import_', '=', import_.id),
                ('state', '!=', 'applied'),
                ])
            if stale_lines:
                ImportLine.delete(stale_lines)

            attachments = Attachment.search([
                ('resource', '=', str(import_)),
                ])
            new_lines = []
            parsed_files = []
            for attachment in attachments:
                if not attachment.name:
                    continue
                record_type = None
                upper_name = attachment.name.upper()
                import_prefixes = {
                    rt: prefix for rt, prefix in bved_records.FILE_PREFIX.items()
                    if rt in ('D', 'E835', 'E898', 'P')}
                for rt, prefix in import_prefixes.items():
                    if upper_name.startswith(prefix):
                        record_type = rt
                        break
                if not record_type:
                    import_._log(
                        'Datei %s: keine Import-Satzart erkannt, '
                        'übersprungen.' % attachment.name)
                    continue
                content = (attachment.data or b'').decode(
                    'iso-8859-1', errors='replace')
                length = bved_records.RECORD_LENGTHS[record_type]
                sequence = 0
                for raw_line in content.splitlines():
                    if not raw_line.strip():
                        continue
                    sequence += 1
                    line = raw_line.ljust(length)[:length]
                    parsed = bved_records.unpack(record_type, line)
                    new_lines.append(ImportLine._from_parsed(
                        import_, record_type, sequence, raw_line, parsed))
                parsed_files.append(attachment.name)
            if new_lines:
                ImportLine.create(new_lines)
            import_.processed_files = '\n'.join(sorted(parsed_files))
            import_._log(
                '%d Datei(en) geparst: %s (%d Satz/Sätze, %d vorherige '
                'nicht-applied Zeile(n) ersetzt).' % (
                    len(parsed_files), ', '.join(parsed_files),
                    len(new_lines), len(stale_lines)))
            import_.save()

    @classmethod
    @ModelView.button
    @Workflow.transition('matched')
    def match(cls, imports):
        pool = Pool()
        ImportLine = pool.get('real_estate.bved.import.line')
        ObjectNumber = pool.get('real_estate.bved.object_number')
        SettlementResult = pool.get('real_estate.settlement_result')

        for import_ in imports:
            # Re-evaluate everything not yet applied, not just newly
            # parsed lines - so fixing a missing object number/settlement
            # result and clicking Match again actually re-checks
            # previously error/skipped lines too.
            lines = ImportLine.search([
                ('import_', '=', import_.id),
                ('state', 'in', ('parsed', 'matched', 'error', 'skipped')),
                ])
            matched_count = 0
            error_count = 0
            skipped_count = 0
            for line in lines:
                # "Letzter Tag Nutzungszeitraum" is an explicit Mussfeld
                # (M) per the BVED spec for E835-, E898- and P-Satz
                # (fields 15/9/7 respectively) - a delivery missing it is
                # a spec violation and must be flagged, not silently
                # matched against an arbitrary settlement_result. The
                # D-Satz table in the available spec transcript carries
                # no (M)/(K) annotation on this field at all, so no such
                # hard rule is applied to D here.
                if (line.record_type in ('E835', 'E898', 'P')
                        and not line.period_end_date):
                    ImportLine.write([line], {
                        'state': 'error',
                        'error_message':
                            'Kein "Letzter Tag Nutzungszeitraum" '
                            'angegeben - laut BVED-Standard ist dieses '
                            'Feld bei %s-Satz ein Mussfeld.'
                            % line.record_type,
                        })
                    error_count += 1
                    continue
                mapping_domain = [
                    ('internal_reference', '=', line.internal_reference),
                    ('provider_assignment.provider', '=', import_.provider.id),
                    ]
                if line.period_end_date:
                    mapping_domain += _valid_overlap_domain(
                        line.period_end_date, line.period_end_date)
                mappings = ObjectNumber.search(mapping_domain)
                if not mappings:
                    if line.is_empty():
                        ImportLine.write([line], {
                            'state': 'skipped',
                            'error_message':
                                'Keine Objektnummer-Zuordnung für "%s" '
                                'gefunden, aber Zeile enthält keine Werte '
                                '- übersprungen.' % line.internal_reference,
                            })
                        skipped_count += 1
                    else:
                        ImportLine.write([line], {
                            'state': 'error',
                            'error_message':
                                'Keine Objektnummer-Zuordnung für "%s" '
                                'gefunden.' % line.internal_reference,
                            })
                        error_count += 1
                    continue
                mapping = mappings[0]
                domain = [('base_object', '=', mapping.base_object.id)]
                if line.period_end_date:
                    domain += [
                        ('start_date', '<=', line.period_end_date),
                        ('end_date', '>=', line.period_end_date),
                        ]
                # An object can have concurrent externally-billed billing
                # units for different cost categories (e.g. Heizung via
                # Techem, Wasser via ista) - only keep results whose OWN
                # billing unit resolves to the SAME provider assignment as
                # this mapping, otherwise a D-Satz line could be applied
                # to the wrong settlement_result.
                results = [r for r in SettlementResult.search(domain)
                    if r.billing_unit
                    and r.billing_unit.bved_provider_assignment
                    and r.billing_unit.bved_provider_assignment.id
                        == mapping.provider_assignment.id]
                if not results:
                    if line.is_empty():
                        ImportLine.write([line], {
                            'state': 'skipped',
                            'error_message':
                                'Kein Abrechnungsergebnis für Objekt "%s" '
                                'im Zeitraum gefunden, aber Zeile enthält '
                                'keine Werte - übersprungen.'
                                % mapping.base_object.rec_name,
                            })
                        skipped_count += 1
                    else:
                        ImportLine.write([line], {
                            'state': 'error',
                            'error_message':
                                'Kein Abrechnungsergebnis für Objekt "%s" im '
                                'Zeitraum gefunden.' % mapping.base_object.rec_name,
                            })
                        error_count += 1
                    continue
                ImportLine.write([line], {
                    'matched_settlement_result': results[0].id,
                    'state': 'matched',
                    'error_message': None,
                    })
                matched_count += 1
            import_._log(
                'Match: %d zugeordnet, %d übersprungen (keine Werte), '
                '%d Fehler.' % (matched_count, skipped_count, error_count))
            import_.state = 'matched'
            import_.save()

    @classmethod
    @ModelView.button
    @Workflow.transition('processed')
    def apply(cls, imports):
        pool = Pool()
        ImportLine = pool.get('real_estate.bved.import.line')
        SettlementResult = pool.get('real_estate.settlement_result')
        Attachment = pool.get('ir.attachment')
        ObjectNumber = pool.get('real_estate.bved.object_number')
        BillingUnit = pool.get('real_estate.billing_unit')

        for import_ in imports:
            # Normally only 'matched' lines are (re-)processed. D-Satz
            # lines already 'applied' but whose result still carries
            # bved_state='validation_error' are re-evaluated too - a
            # fresh Apply click can then pick up a plausibility-check fix
            # (e.g. an advance-payment false positive) without needing to
            # re-parse/re-match the underlying data. Scoped to D-Satz only
            # so E898/E835/P are never reprocessed (E898 in particular
            # would otherwise re-copy its PDF attachment every time).
            lines = ImportLine.search([
                ('import_', '=', import_.id),
                ['OR',
                    ('state', '=', 'matched'),
                    ['AND',
                        ('state', '=', 'applied'),
                        ('record_type', '=', 'D'),
                        ('matched_settlement_result.bved_state', '=',
                            'validation_error'),
                        ],
                    ],
                ])
            applied = 0
            touched_bu_ids = set()

            # D-Satz: a provider may send one line per cost type (e.g.
            # Heizung + Warmwasser, distinguished by d_cost_key - BVED
            # Tabelle K) for the same object/period, all resolving to the
            # SAME settlement_result - since actual_costs there is the
            # total across the whole billing unit (all its settlement
            # units combined), DIFFERENT cost keys must be summed. Two
            # lines sharing the SAME cost key (including both empty/
            # unset, the common case when a provider does not populate
            # this Kann-Feld) are instead treated as a duplicate delivery
            # - e.g. an old and a newly generated response file both
            # still attached and re-parsed - and must NOT be summed, or
            # actual_costs silently doubles.
            d_groups = {}
            other_lines = []
            for line in lines:
                if line.record_type == 'D':
                    result = line.matched_settlement_result
                    group = d_groups.setdefault(
                        result.id, {'result': result, 'by_cost_key': {}})
                    group['by_cost_key'].setdefault(
                        line.d_cost_key, []).append(line)
                else:
                    other_lines.append(line)

            for group in d_groups.values():
                result = group['result']
                touched_bu_ids.add(result.billing_unit.id)
                messages = []
                all_lines = []
                total_gross = Decimal(0)
                advance_sum = Decimal(0)
                for cost_key, subset in group['by_cost_key'].items():
                    all_lines.extend(subset)
                    if len(subset) > 1:
                        messages.append(
                            'Mehrere D-Satz-Zeilen mit gleicher Kostenart-'
                            'Kennung "%s" für dasselbe Ergebnis (Zeile(n) '
                            '%s) - vermutlich doppelt eingelesen (z.B. '
                            'altes und neues Antwortfile beide noch '
                            'angehängt); nur die letzte Zeile wurde '
                            'gewertet.' % (
                                cost_key or '(keine)',
                                ', '.join(str(l.sequence) for l in subset)))
                    chosen = subset[-1]
                    total_gross += chosen.total_costs_gross or Decimal(0)
                    advance_sum += (
                        chosen.advance_payment_gross or Decimal(0))
                    if (chosen.total_costs_gross is not None
                            and chosen.advance_payment_gross is not None
                            and chosen.balance_gross is not None):
                        expected = (chosen.total_costs_gross
                            - chosen.advance_payment_gross)
                        if abs(expected - chosen.balance_gross) > Decimal(
                                '0.01'):
                            messages.append(
                                'Saldo-Kontrolle fehlgeschlagen für Zeile '
                                '%d (Gesamtkosten - Vorauszahlung != Saldo '
                                'laut D-Satz).' % chosen.sequence)
                    if (result.start_date and result.end_date
                            and chosen.period_end_date
                            and not (result.start_date
                                <= chosen.period_end_date <= result.end_date)):
                        messages.append(
                            'Letzter Tag Nutzungszeitraum (Zeile %d) liegt '
                            'außerhalb der Abrechnungsperiode.'
                            % chosen.sequence)
                # A reported sum of exactly 0 is treated as "this provider
                # does not report advance payments" rather than "confirmed
                # zero payment" - BVED's fixed-width numeric fields cannot
                # distinguish a genuinely blank field from a real 0.00, and
                # a real partial advance payment of exactly zero across
                # every cost key is not a realistic scenario worth
                # flagging.
                if (result.advanced_payment is not None and advance_sum != 0
                        and abs(result.advanced_payment - advance_sum)
                        > Decimal('0.01')):
                    messages.append(
                        'Vorauszahlung laut D-Satz (Summe %s über %d '
                        'Kostenart(en)) weicht vom intern berechneten '
                        'advanced_payment (%s) ab.'
                        % (advance_sum, len(group['by_cost_key']),
                            result.advanced_payment))
                result.actual_costs = total_gross
                result.on_change_actual_costs()
                result.bved_state = (
                    'validated' if not messages else 'validation_error')
                result.bved_check_message = (
                    '\n'.join(messages) if messages else None)
                result.bved_import_date = datetime.datetime.now()
                result.bved_import_line = all_lines[-1].id
                result.save()
                ImportLine.write(all_lines, {'state': 'applied'})
                applied += len(all_lines)

            for line in other_lines:
                result = line.matched_settlement_result
                touched_bu_ids.add(result.billing_unit.id)
                if line.record_type == 'E898':
                    if line.document_path:
                        basename = line.document_path.replace(
                            '\\', '/').rsplit('/', 1)[-1]
                        candidates = Attachment.search([
                            ('resource', '=', str(import_)),
                            ('name', 'ilike', '%%%s%%' % basename),
                            ])
                        if candidates:
                            Attachment.copy(
                                candidates, default={'resource': str(result)})
                        else:
                            import_._log(
                                'E898: referenzierte Datei "%s" nicht unter '
                                'den Anhängen gefunden.' % basename)
                    ImportLine.write([line], {'state': 'applied'})
                    applied += 1
                else:
                    # E835 / P-Satz: informational only (see plan) - no
                    # domain field exists to write these back to.
                    ImportLine.write([line], {'state': 'applied'})
                    applied += 1

            for bu_id in touched_bu_ids:
                bu = BillingUnit(bu_id)
                assignment = bu.bved_provider_assignment
                if not assignment:
                    continue
                mappings = ObjectNumber.search([
                    ('provider_assignment', '=', assignment.id),
                    ('base_object', 'in', bu.bved_covered_object_ids()),
                    ])
                covered = {
                    result.base_object.id
                    for result in SettlementResult.search([
                        ('billing_unit', '=', bu_id),
                        ('bved_state', 'in',
                            ('imported', 'validated', 'validation_error')),
                        ]) if result.base_object}
                missing = [
                    mapping.base_object.rec_name for mapping in mappings
                    if mapping.base_object.id not in covered]
                if missing:
                    import_._log(
                        'Vollständigkeit: %d Objekt(e) ohne D-Satz-Ergebnis: '
                        '%s' % (len(missing), ', '.join(missing)))

            import_._log('Apply: %d Zeile(n) verarbeitet.' % applied)
            import_.state = 'processed'
            import_.save()


#**********************************************************************
class BvedImportLine(ModelSQL, ModelView):
    "BVED Import Line"
    __name__ = 'real_estate.bved.import.line'

    import_ = fields.Many2One('real_estate.bved.import', "Import",
        required=True, ondelete='CASCADE')

    sequence = fields.Integer("Sequence")

    record_type = fields.Selection([
            ('D', 'D-Satz'),
            ('E835', 'E835-Satz'),
            ('E898', 'E898-Satz'),
            ('P', 'P-Satz'),
            ], "Record Type", required=True, sort=False)

    raw_line = fields.Text("Raw Line", readonly=True)

    internal_reference = fields.Char("Internal Reference", readonly=True)

    base_object = fields.Function(
        fields.Many2One('real_estate.base_object', "Object"),
        'on_change_with_base_object')

    provider_assignment = fields.Function(
        fields.Many2One('real_estate.bved.provider_assignment',
            "Provider Assignment"),
        'on_change_with_provider_assignment')

    period_end_date = fields.Date(
        "Period End Date", readonly=True,
        help="Format TTMMJJ. Mandatory field on E835-, E898- and P-Satz.")

    # D-Satz
    d_cost_key = fields.Char(
        "Cost Type Key", readonly=True,
        help="BVED Kostenart-Kennung (Tabelle K) - distinguishes multiple "
        "D-Satz lines for the same object/period (e.g. Heizung vs. "
        "Warmwasser) from an accidental duplicate delivery of the same "
        "line.")
    total_costs_gross = fields.Numeric(
        "Total Costs (gross)", digits=(16, 2), readonly=True)
    total_costs_net = fields.Numeric(
        "Total Costs (net)", digits=(16, 2), readonly=True)
    advance_payment_gross = fields.Numeric(
        "Advance Payment (gross)", digits=(16, 2), readonly=True)
    advance_payment_net = fields.Numeric(
        "Advance Payment (net)", digits=(16, 2), readonly=True)
    balance_gross = fields.Numeric(
        "Balance (gross)", digits=(16, 2), readonly=True,
        help="Total costs minus advance payment.")
    balance_net = fields.Numeric(
        "Balance (net)", digits=(16, 2), readonly=True)
    co2_allocated_gross = fields.Numeric(
        "CO2 Cost Allocated (gross)", digits=(16, 2), readonly=True,
        help="Included in total costs.")
    co2_allocated_net = fields.Numeric(
        "CO2 Cost Allocated (net)", digits=(16, 2), readonly=True,
        help="Included in total costs.")
    co2_not_allocated_gross = fields.Numeric(
        "CO2 Cost Not Allocated (gross)", digits=(16, 2), readonly=True,
        help="NOT included in total costs.")
    co2_not_allocated_net = fields.Numeric(
        "CO2 Cost Not Allocated (net)", digits=(16, 2), readonly=True,
        help="NOT included in total costs.")

    # E835-Satz (§35a EStG) - informational, see plan.
    labor_share_total = fields.Numeric(
        "Labor Share Total", digits=(16, 2), readonly=True,
        help="Labor cost share included in the total invoice amount.")
    user_share_amount = fields.Numeric(
        "User Share Amount", digits=(16, 2), readonly=True,
        help="User's share of the labor cost portion.")
    user_share_percent = fields.Numeric(
        "User Share (%)", digits=(5, 2), readonly=True,
        help="User's percentage share of the total invoice amount.")

    # E898-Satz
    document_path = fields.Char("Document Path", readonly=True)
    document_type = fields.Char(
        "Document Type", readonly=True,
        help="HKA = Heizkostenabrechnung (heating cost statement), "
             "BKA = Betriebskostenabrechnung (operating cost statement), "
             "VDA = Verbrauchsdatenanalyse (consumption data analysis).")

    # P-Satz - informational, see plan.
    p_cost_key = fields.Char(
        "Cost Type Key", readonly=True,
        help="BVED Tabelle 'K' codes 901/902/910/911/912 "
             "(Energiepreisbremse cost types).")
    p_total_gross = fields.Numeric(
        "Total Amount (gross)", digits=(16, 2), readonly=True)
    p_total_net = fields.Numeric(
        "Total Amount (net)", digits=(16, 2), readonly=True)
    p_user_share_gross = fields.Numeric(
        "User Share (gross)", digits=(16, 2), readonly=True)
    p_user_share_percent = fields.Numeric(
        "User Share (%)", digits=(5, 2), readonly=True)

    raw_data = fields.Text("Raw Data (JSON)", readonly=True,
        help="Full field-by-field content of this record, for audit/debug "
             "beyond the typed fields above.")

    matched_settlement_result = fields.Many2One(
        'real_estate.settlement_result', "Settlement Result",
        ondelete='SET NULL', readonly=True)

    state = fields.Selection([
            ('parsed', 'Parsed'),
            ('matched', 'Matched'),
            ('applied', 'Applied'),
            ('skipped', 'Skipped'),
            ('error', 'Error'),
            ], "State", sort=False, readonly=True)

    error_message = fields.Char("Error Message", readonly=True)

    @classmethod
    def view_attributes(cls):
        return super().view_attributes() + [
            ('//page[@id="page_d"]', 'states', {
                'invisible': Eval('record_type') != 'D',
                }),
            ('//page[@id="page_e835"]', 'states', {
                'invisible': Eval('record_type') != 'E835',
                }),
            ('//page[@id="page_e898"]', 'states', {
                'invisible': Eval('record_type') != 'E898',
                }),
            ('//page[@id="page_p"]', 'states', {
                'invisible': Eval('record_type') != 'P',
                }),
            ]

    _FIELD_MAP = {
        'D': {
            'internal_reference': 'internal_reference',
            'period_end_date': 'period_end_date',
            'cost_type_key': 'd_cost_key',
            'total_costs_gross': 'total_costs_gross',
            'total_costs_net': 'total_costs_net',
            'advance_payment_gross': 'advance_payment_gross',
            'advance_payment_net': 'advance_payment_net',
            'balance_gross': 'balance_gross',
            'balance_net': 'balance_net',
            'co2_allocated_gross': 'co2_allocated_gross',
            'co2_allocated_net': 'co2_allocated_net',
            'co2_not_allocated_gross': 'co2_not_allocated_gross',
            'co2_not_allocated_net': 'co2_not_allocated_net',
            },
        'E835': {
            'internal_reference': 'internal_reference',
            'period_end_date': 'period_end_date',
            'labor_share_total': 'labor_share_total',
            'user_share_labor_amount': 'user_share_amount',
            'user_share_percent': 'user_share_percent',
            },
        'E898': {
            'internal_reference': 'internal_reference',
            'period_end_date': 'period_end_date',
            'document_path': 'document_path',
            'document_type': 'document_type',
            },
        'P': {
            'internal_reference': 'internal_reference',
            'period_end_date': 'period_end_date',
            'cost_type_key': 'p_cost_key',
            'total_amount_gross': 'p_total_gross',
            'total_amount_net': 'p_total_net',
            'user_share_amount': 'p_user_share_gross',
            'user_share_percent': 'p_user_share_percent',
            },
        }

    @classmethod
    def default_state(cls):
        return 'parsed'

    def _find_object_number(self):
        """Resolve this line's internal_reference to a BvedObjectNumber
        mapping (scoped to the import's provider), independent of whether
        Match has already run - lets the user jump to the real object/
        provider assignment for orientation even on a still-unmatched
        line."""
        if not self.internal_reference or not self.import_ \
                or not self.import_.provider:
            return None
        ObjectNumber = Pool().get('real_estate.bved.object_number')
        domain = [
            ('internal_reference', '=', self.internal_reference),
            ('provider_assignment.provider', '=', self.import_.provider.id),
            ]
        if self.period_end_date:
            domain += _valid_overlap_domain(
                self.period_end_date, self.period_end_date)
        mappings = ObjectNumber.search(domain, limit=1)
        return mappings[0] if mappings else None

    @fields.depends('internal_reference', 'period_end_date', 'import_',
        '_parent_import_.provider')
    def on_change_with_base_object(self, name=None):
        mapping = self._find_object_number()
        return mapping.base_object if mapping else None

    @fields.depends('internal_reference', 'period_end_date', 'import_',
        '_parent_import_.provider')
    def on_change_with_provider_assignment(self, name=None):
        mapping = self._find_object_number()
        return mapping.provider_assignment if mapping else None

    def is_empty(self):
        """True if this line carries no meaningful value at all (e.g. a
        D-/P-Satz row the provider sent for an object with nothing to
        report - a common no-op for objects, like parking spaces, that
        have no internal settlement result to match against). Such lines
        are skipped rather than flagged as errors when unmatched."""
        if self.record_type == 'D':
            return not (self.total_costs_gross or self.advance_payment_gross
                or self.balance_gross)
        if self.record_type == 'P':
            return not (self.p_total_gross or self.p_user_share_gross)
        if self.record_type == 'E835':
            return not (self.labor_share_total or self.user_share_amount)
        return False

    @classmethod
    def _from_parsed(cls, import_, record_type, sequence, raw_line, parsed):
        def _jsonable(value):
            if isinstance(value, Decimal):
                return str(value)
            if hasattr(value, 'isoformat'):
                return value.isoformat()
            return value

        values = {
            'import_': import_.id,
            'sequence': sequence,
            'record_type': record_type,
            'raw_line': raw_line,
            'state': 'parsed',
            'raw_data': json.dumps(
                {key: _jsonable(value) for key, value in parsed.items()},
                indent=2, ensure_ascii=False, sort_keys=True),
            }
        for source, dest in cls._FIELD_MAP.get(record_type, {}).items():
            if source == 'cost_type_key':
                values[dest] = (str(parsed.get(source))
                    if parsed.get(source) is not None else None)
            else:
                values[dest] = parsed.get(source)
        return values
