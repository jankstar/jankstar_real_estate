"""BVED interface: service provider configuration, object number mapping,
and the export/import runs that exchange fixed-width records (see
bved_records.py) with an external Messdienstleister for operating-cost
settlement (see rechercheergebnis-bved-schnittstelle.md /
spezifikation-tryton-bved-modul.md)."""
import datetime
import json
from decimal import Decimal

from trytond.model import (
    ModelSQL, ModelView, Unique, Workflow, fields)
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

    @classmethod
    def default_bved_version(cls):
        return '3.10'

    @classmethod
    def default_transport_type(cls):
        return 'manual'

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

    name = fields.Function(fields.Char("Name"), 'on_change_with_name')

    object_numbers = fields.One2Many('real_estate.bved.object_number',
        'provider_assignment', "Object Numbers")

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
        fields.Char("Provider Key"), 'on_change_with_l_provider_key')
    l_street = fields.Function(
        fields.Char("Street"), 'on_change_with_l_street')
    l_country = fields.Function(
        fields.Many2One('country.country', "Country"),
        'on_change_with_l_country')
    l_postal_code = fields.Function(
        fields.Char("Postal Code"), 'on_change_with_l_postal_code')
    l_city = fields.Function(
        fields.Char("City"), 'on_change_with_l_city')
    l_period_start = fields.Function(
        fields.Date("Period Start"), 'on_change_with_l_period_start')
    l_period_end = fields.Function(
        fields.Date("Period End"), 'on_change_with_l_period_end')
    l_vat_flag = fields.Function(
        fields.Selection([
            ('3', 'No VAT shown'),
            ('4', 'Net (fully opted for VAT)'),
            ('5', 'Per M-Satz field 25 (mixed/per user)'),
            ], "VAT Treatment", sort=False,
            help="Derived from the option rate of the billing units "
            "covered by this assignment: 100% option rate -> '4', 0% -> "
            "'3', anything in between -> '5' (decided per user via the "
            "M-Satz field)."),
        'on_change_with_l_vat_flag')
    l_weg_flag = fields.Function(
        fields.Boolean("WEG (Cash Basis)",
            help="Derived from the calculation method of the covered "
            "billing units: 'Cash basis' (WEG billing) sets this flag, "
            "'Accrual basis' (rental apartment) does not."),
        'on_change_with_l_weg_flag')
    l_non_residential_flag = fields.Function(
        fields.Boolean(">50% Commercial (§8)",
            help="True if any covered billing unit has its own "
            "'Non-residential building >50% commercial (§8)' flag set "
            "(CO2 Costs tab of the billing unit)."),
        'on_change_with_l_non_residential_flag')
    l_co2_landlord_share_percent = fields.Function(
        fields.Numeric("CO2 Landlord Share (%)", digits=(5, 2),
            help="Taken from the landlord share of the heating cost "
            "settlement unit (bved_fuel_data) among the covered billing "
            "units, if any."),
        'on_change_with_l_co2_landlord_share_percent')

    gross_floor_area_measurement_type = fields.Many2One(
        'real_estate.measurement.type', "Gross Floor Area Measurement Type",
        ondelete='RESTRICT',
        help="Which measurement type to sum (across every object covered "
             "by a billing unit assigned here, each counted once even if "
             "covered by several billing units) for L-Satz field 18 "
             "(Gesamtfläche). Leave empty to omit this Kann-Feld.")
    l_total_area = fields.Function(
        fields.Numeric("Total Area", digits=(16, 2)),
        'on_change_with_l_total_area')

    vacancy_risk_flag = fields.Boolean(
        "Vacancy Risk Surcharge",
        help="L-Satz field 13 (Kennzeichen Umlageausfallwagnis) - not "
             "derivable from any existing data, enter manually.")
    vacancy_risk_percent = fields.Numeric(
        "Vacancy Risk Surcharge (%)", digits=(5, 2),
        states={'invisible': ~Eval('vacancy_risk_flag', False)},
        help="L-Satz field 14 - percentage, only relevant if the "
             "surcharge flag above is set.")
    labor_share_flag = fields.Boolean(
        "Disclose Labor Share",
        help="L-Satz field 15 (Kennzeichen Ausweisung Lohnanteil) - not "
             "derivable from any existing data, enter manually.")
    energy_improvement_flag = fields.Boolean(
        "Energy Improvement (§9)",
        help="L-Satz field 20 - legal fact about the building, not "
             "derivable from any existing data, enter manually.")
    heat_supply_flag = fields.Boolean(
        "Heat Supply (§9)",
        help="L-Satz field 21 - legal fact about the building, not "
             "derivable from any existing data, enter manually.")
    heat_connection_2023_flag = fields.Boolean(
        "District Heating Connection since 2023",
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
        units - an object covered by several of them (different cost
        categories/years) is counted once, using the latest end_date."""
        result = {}
        for bu in billing_units:
            for obj_id in bu.bved_covered_object_ids():
                if obj_id not in result or bu.end_date > result[obj_id]:
                    result[obj_id] = bu.end_date
        return result

    @classmethod
    def _total_area(cls, billing_units, measurement_type):
        if not measurement_type:
            return None
        Measurement = Pool().get('real_estate.measurement')
        total = 0.0
        for obj_id, end_date in cls._covered_objects_with_end_date(
                billing_units).items():
            rows = Measurement.search([
                ('base_object', '=', obj_id),
                ('m_type', '=', measurement_type.id),
                ('valid_from', '<=', end_date),
                ], order=[('valid_from', 'DESC')], limit=1)
            if rows:
                total += rows[0].value
        return Decimal(str(total)) if total else Decimal(0)

    @staticmethod
    def _co2_landlord_share(billing_units):
        """CO2 landlord share (%), taken from the billing unit that owns
        the settlement unit actually externally billed via BVED
        (bved_fuel_data=True) - the co2 share fields are aggregated per
        billing unit (across all of its co2_kostaufg-referencing
        settlement units), not a single value per property, so the
        billing unit of the heating-cost unit relevant to this L-Satz is
        used as the representative value."""
        for bu in billing_units:
            if any(su.bved_fuel_data for su in (bu.settlement_units or [])):
                return (bu.co2_commercial_landlord_share
                    if bu.co2_commercial_landlord_share is not None
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

    @fields.depends('provider_assignment',
        '_parent_provider_assignment.base_object')
    def on_change_with_scope_object(self, name=None):
        return (self.provider_assignment.base_object
            if self.provider_assignment else None)


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
            ('end_date', '<=', Eval('cutoff_date')),
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

    name = fields.Function(fields.Char("Name"), 'on_change_with_name')

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
        Occupancy = pool.get('real_estate.base_object.occupancy')
        ObjectParty = pool.get('real_estate.object_party')
        ModelData = pool.get('ir.model.data')

        owner_role_id = ModelData.get_id(
            'real_estate', 'object_party_owner_role')
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
                obj = mapping.base_object
                Occupancy.refresh([obj])
                entries = Occupancy.search([
                    ('base_object', '=', obj.id),
                    ('start_date', '<=', bu.end_date),
                    ['OR', ('end_date', '=', None),
                        ('end_date', '>=', bu.start_date)],
                    ], order=[('start_date', 'ASC')]) or [None]

                owners = ObjectParty.search([
                    ('base_object', '=', obj.id),
                    ('role', '=', owner_role_id),
                    ['OR', ('valid_to', '=', None),
                        ('valid_to', '>=', bu.start_date)],
                    ('valid_from', '<=', bu.end_date),
                    ])
                owner = owners[0].party if owners else None
                owner_address = owner.address_get() if owner else None

                for entry in entries:
                    values = {
                        'customer_number': assignment.customer_number,
                        'provider_key': self.provider.bved_key,
                        'provider_reference': self._provider_reference(
                            bu, mapping.external_unit_number),
                        'internal_reference': mapping.internal_reference,
                        'address_flag': 1,
                        'vat_treatment_flag': 0,
                        'vacancy_risk_calc_flag': 0,
                        'vacancy_flag': 0,
                        'tenant_change_fee_flag': 0,
                        }
                    if owner:
                        values['owner_name1'] = owner.name[:35]
                        if owner_address:
                            values['owner_street'] = _first_line(
                                owner_address.street)[:35]
                            values['owner_country'] = (
                                owner_address.country.code3
                                if owner_address.country else '')
                            values['owner_postal_code'] = (
                                owner_address.postal_code or '')
                            values['owner_city'] = owner_address.city or ''

                    # Nutzungszeitraum is set regardless of occupancy state -
                    # a vacancy period still needs a period so the provider
                    # can compute the (owner-borne) Grundkosten share for
                    # it; only the tenant-specific fields below depend on
                    # an actual rented+contract entry.
                    if entry:
                        values['occupancy_start'] = max(
                            entry.start_date, bu.start_date)
                        values['occupancy_end'] = (
                            min(entry.end_date, bu.end_date)
                            if entry.end_date else bu.end_date)
                    else:
                        values['occupancy_start'] = bu.start_date
                        values['occupancy_end'] = bu.end_date

                    tenant_party = None
                    if entry and entry.state == 'rented' and entry.contract:
                        tenant_party = entry.contract.contractual_partner
                    if tenant_party:
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
                        warnings = []
                        konto, blz = _bank_fields(
                            tenant_party, warnings, 'Mieter')
                        values['bank_account_number'] = konto
                        values['bank_code'] = blz
                        for warning in warnings:
                            self._log(warning)
                        values['debtor_name1'] = values.get('tenant_name1', '')
                        values['debtor_street'] = values.get('tenant_street', '')
                        values['debtor_country'] = values.get('tenant_country', '')
                        values['debtor_postal_code'] = values.get(
                            'tenant_postal_code', '')
                        values['debtor_city'] = values.get('tenant_city', '')
                    else:
                        values['vacancy_flag'] = 1

                    if company_party:
                        values['provider_org_name1'] = company_party.name[:35]
                        if company_address:
                            values['provider_org_street'] = _first_line(
                                company_address.street)[:35]
                            values['provider_org_country'] = (
                                company_address.country.code3
                                if company_address.country else '')
                            values['provider_org_postal_code'] = (
                                company_address.postal_code or '')
                            values['provider_org_city'] = (
                                company_address.city or '')

                    lines.append(bved_records.pack('M', values))

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
                        'primary_energy_factor': su.bved_primary_energy_factor,
                        }
                    # B-Satz fuel/heat data is maintained directly on the
                    # settlement unit (see above) - there are no meters for
                    # this in the system, so the per-meter fields (Feld
                    # 28-33: Zählerart/Gerätenummer/Verbrauch/Zählerstände)
                    # are Kann-Felder that simply stay empty.
                    lines.append(bved_records.pack('B', base_values))

            if 'K' in record_types:
                for su in settlement_units:
                    invoice_lines = InvoiceLine.search([
                        ('settlement_unit', '=', su.id),
                        ('invoice.state', '!=', 'cancelled'),
                        ])
                    for line in invoice_lines:
                        cost_key = (
                            su.type.bved_cost_key if su.type else None)
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

    name = fields.Function(fields.Char("Name"), 'on_change_with_name')

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
