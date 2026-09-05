'CO2KostAufG'
from decimal import Decimal

from trytond.model import (
    DeactivableMixin, ModelSQL, ModelView, fields, sequence_ordered)
from trytond.model.exceptions import ValidationError
from trytond.i18n import gettext
from trytond.pool import Pool

from . import base_object
from . import bved_records


#**********************************************************************
class Co2KostAufg(base_object.re_sequence_ordered(), ModelSQL, ModelView):
    "CO2KostAufG"
    __name__ = 'real_estate.co2_kostaufg'
    __rec_name__ = 'name'

    name = fields.Char("Name", required=True)

    company = fields.Function(fields.Many2One('company.company', 'Company'),
        'on_change_with_company', searcher='search_company')

    property = fields.Many2One('real_estate.base_object', "Property",
        required=True, ondelete='CASCADE',
        domain=[('type', '=', 'property')])

    consumptions = fields.One2Many(
        'real_estate.co2_kostaufg.consumption', 'parent', "Consumption Data")

    @classmethod
    def default_sequence(cls):
        return 10

    @fields.depends('property', '_parent_property.company')
    def on_change_with_company(self, name=None):
        return self.property.company if self.property else None

    @classmethod
    def search_company(cls, name, clause):
        return [('property.company',) + tuple(clause[1:])]


#**********************************************************************
class Co2KostAufgConsumption(DeactivableMixin, sequence_ordered(), ModelSQL, ModelView):
    "CO2KostAufG Consumption Data"
    __name__ = 'real_estate.co2_kostaufg.consumption'

    parent = fields.Many2One('real_estate.co2_kostaufg', "CO2KostAufG",
        required=True, ondelete='CASCADE')

    split = fields.Boolean("Split",
        help="Set automatically when this record was created by "
             "splitting an original consumption record at a settlement "
             "period boundary (\"Compute Value Shares\").")

    date_from = fields.Date("Date From", required=True)
    date_to = fields.Date("Date To", required=True)

    consumption_kwh = fields.Numeric("Consumption (kWh)", digits=(16, 2),
        required=True)

    co2_kg_per_kwh = fields.Numeric("CO2 (kg per kWh)", digits=(8, 5),
        required=True)

    co2_emission_kg = fields.Numeric("CO2 Emission (kg)", digits=(16, 3),
        help="Pre-filled as Consumption x CO2 (kg per kWh) when those "
             "fields change; can be overridden, e.g. with the supplier's "
             "own figure.")

    co2_price_ct_per_kwh = fields.Numeric("CO2 Price (ct per kWh)",
        digits=(8, 4), required=True)

    vat_rate = fields.Numeric("VAT Rate (%)", digits=(5, 2), required=True,
        domain=[
            ('vat_rate', '>=', 0),
            ('vat_rate', '<=', 100),
            ])

    co2_cost_net = fields.Numeric("CO2 Cost (net)", digits=(16, 2),
        help="Pre-filled as Consumption x CO2 Price when those fields "
             "change; can be overridden, e.g. with the supplier's own "
             "invoice amount.")

    co2_cost_gross = fields.Numeric("CO2 Cost (gross)", digits=(16, 2),
        help="Pre-filled as CO2 Cost (net) x (1 + VAT Rate); can be "
             "overridden, e.g. with the supplier's own invoice amount.")

    energy_mix = fields.One2Many(
        'real_estate.co2_kostaufg.consumption.energy_mix', 'consumption',
        "Energy Mix",
        help="Breakdown of this delivery's energy sources for BVED K-Satz "
             "fields 22-39 (up to 6 entries). Belongs here rather than on "
             "the settlement unit, since it is a property of one specific "
             "delivery/period (like co2_kg_per_kwh above), not of the "
             "whole billing period.")

    @classmethod
    def default_vat_rate(cls):
        return Decimal(0)

    @classmethod
    def default_split(cls):
        return False

    @fields.depends(
        'consumption_kwh', 'co2_kg_per_kwh', 'co2_price_ct_per_kwh',
        'vat_rate', 'co2_emission_kg', 'co2_cost_net', 'co2_cost_gross')
    def on_change_consumption_kwh(self):
        self._update_co2_emission_kg()
        self._update_co2_cost()

    @fields.depends('consumption_kwh', 'co2_kg_per_kwh', 'co2_emission_kg')
    def on_change_co2_kg_per_kwh(self):
        self._update_co2_emission_kg()

    @fields.depends(
        'consumption_kwh', 'co2_price_ct_per_kwh', 'vat_rate',
        'co2_cost_net', 'co2_cost_gross')
    def on_change_co2_price_ct_per_kwh(self):
        self._update_co2_cost()

    @fields.depends(
        'consumption_kwh', 'co2_price_ct_per_kwh', 'vat_rate',
        'co2_cost_net', 'co2_cost_gross')
    def on_change_vat_rate(self):
        self._update_co2_cost()

    @fields.depends(
        'consumption_kwh', 'co2_price_ct_per_kwh', 'vat_rate',
        'co2_cost_net', 'co2_cost_gross')
    def on_change_co2_cost_net(self):
        self._update_co2_cost()

    @fields.depends(
        'consumption_kwh', 'co2_price_ct_per_kwh', 'vat_rate',
        'co2_cost_net', 'co2_cost_gross')
    def on_change_co2_cost_gross(self):
        self._update_co2_cost()

    def _update_co2_emission_kg(self):
        # Only pre-fill while still empty - once set (by this pre-fill or
        # by the user directly), later changes to consumption/factor must
        # not silently overwrite it again.
        if (self.co2_emission_kg is None
                and self.consumption_kwh is not None
                and self.co2_kg_per_kwh is not None):
            self.co2_emission_kg = (
                self.consumption_kwh * self.co2_kg_per_kwh
                ).quantize(Decimal('0.001'))

    def _update_co2_cost(self):
        # Only pre-fill while still empty; once set (by this pre-fill or
        # by the user directly), later changes must not silently
        # overwrite it again.
        if self.consumption_kwh is not None and self.co2_price_ct_per_kwh is not None:
            net = (self.consumption_kwh * self.co2_price_ct_per_kwh
                / Decimal(100)).quantize(Decimal('0.01'))
            self.co2_cost_net = net
            if self.vat_rate is not None:
                self.co2_cost_gross = (
                    net * (1 + self.vat_rate / Decimal(100))
                    ).quantize(Decimal('0.01'))


#**********************************************************************
class Co2KostAufgConsumptionEnergyMix(sequence_ordered(), ModelSQL, ModelView):
    "CO2KostAufG Consumption Energy Mix"
    __name__ = 'real_estate.co2_kostaufg.consumption.energy_mix'

    consumption = fields.Many2One(
        'real_estate.co2_kostaufg.consumption', "Consumption",
        required=True, ondelete='CASCADE')

    energy_source = fields.Selection(
        'get_energy_sources', "Energy Source", required=True, sort=False)

    share_percent = fields.Numeric("Share (%)", digits=(2, 1), required=True,
        domain=[
            ('share_percent', '>=', 0),
            ('share_percent', '<=', 99.9),
            ])

    emission_factor = fields.Numeric(
        "CO2 Emission Factor (kg/kWh)", digits=(6, 3))

    @staticmethod
    def get_energy_sources():
        return bved_records.as_selection(bved_records.TABLE_M)


#**********************************************************************
class Co2EmissionShare(sequence_ordered(), ModelSQL, ModelView):
    "CO2 Emission Distribution"
    __name__ = 'real_estate.co2_emission_share'

    emission_limit = fields.Numeric("CO2 Emission (kg per m² per year)",
        digits=(16, 2), required=True,
        help="Exclusive upper threshold of this tier (the tier applies "
             "while the value stays below this limit). The highest "
             "configured tier (by sequence) is always treated as an "
             "open-ended 'and above' tier, regardless of its own stored "
             "limit value.")

    tenant_share = fields.Numeric("Tenant Share (%)", digits=(5, 2),
        required=True,
        domain=[
            ('tenant_share', '>=', 0),
            ('tenant_share', '<=', 100),
            ])

    landlord_share = fields.Numeric("Landlord Share (%)", digits=(5, 2),
        required=True,
        domain=[
            ('landlord_share', '>=', 0),
            ('landlord_share', '<=', 100),
            ])

    @classmethod
    def validate(cls, records):
        super().validate(records)
        for record in records:
            if record.tenant_share + record.landlord_share != Decimal(100):
                raise ValidationError(gettext(
                    'real_estate.msg_co2_emission_share_sum_100',
                    name=record.rec_name))

    @classmethod
    def get_share(cls, value):
        """Return the first Co2EmissionShare row (in sequence order) whose
        emission_limit is strictly greater than value. If value reaches or
        exceeds every configured limit, return the last row by sequence
        (open-ended top tier). Returns None if value is None or no rows
        are configured."""
        if value is None:
            return None
        rows = cls.search([])
        for row in rows:
            if value < row.emission_limit:
                return row
        return rows[-1] if rows else None
