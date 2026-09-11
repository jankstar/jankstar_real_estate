'Settlement Unit'
from trytond.model import (
    DeactivableMixin, ModelSQL, ModelView, fields)
from trytond.model.exceptions import ValidationError
from trytond.exceptions import UserError
from trytond.i18n import gettext
from trytond.pool import Pool
from trytond.transaction import Transaction
from trytond.pyson import Bool, Eval, If
from trytond.modules.currency.fields import Monetary

import re
import datetime
from decimal import Decimal, ROUND_HALF_UP

from . import base_object
from . import bved_records


#**********************************************************************
class SettlementUnit(DeactivableMixin, base_object.re_sequence_ordered(), ModelSQL, ModelView):
    """Settlement Unit, e.g. cost allocation for a specific cost type and period within a billing unit."""
    __name__ = 'real_estate.settlement_unit'
    __rec_name__ = 'name'

    property = fields.Function(fields.Many2One('real_estate.base_object', 'Property'),
        'on_change_with_property', searcher='search_property')

    company = fields.Function(fields.Many2One('company.company', 'Company'),
        'on_change_with_company')

    billing_unit = fields.Many2One('real_estate.billing_unit', 'Billing Unit',
        required=True, ondelete='CASCADE',
        states={'readonly': Eval('state').in_(['ready_for_billing', 'billed'])},
        )

    start_date = fields.Function(fields.Date('Start Date'), 'on_change_with_start_date')

    end_date = fields.Function(fields.Date('End Date'), 'on_change_with_end_date')

    state = fields.Function(fields.Selection('get_states', "State"), 'on_change_with_state')

    sub_state = fields.Function(fields.Selection('get_sub_states', "Sub State"), 'get_sub_state')

    type = fields.Many2One(
        'real_estate.cost_type', "Cost Type", required=True, on_change='on_change_type',
        states={'readonly': Eval('state').in_(['ready_for_billing', 'billed'])})

    comment = fields.Text("Comment",
        states={'readonly': Eval('state').in_(['ready_for_billing', 'billed'])})

    predecessor = fields.Many2One('real_estate.settlement_unit', "Predecessor",
        readonly=True)

    name = fields.Function(fields.Char("Name"), 'on_change_with_name',
        searcher='name_search')

    planned_costs = Monetary('Planned Costs', currency='currency', digits='currency',
        states={'readonly': Eval('state').in_(['ready_for_billing', 'billed'])},
        )

    actual_costs = Monetary('Actual Costs', currency='currency', digits='currency',
        states={'readonly': Eval('state').in_(['ready_for_billing', 'billed'])},
        )

    currency = fields.Function(fields.Many2One('currency.currency', 'Currency'), 'on_change_with_currency')

    billing_unit_external_billing = fields.Function(
        fields.Boolean('External Billing (BU)'),
        'on_change_with_billing_unit_external_billing')

    allocation_rule = fields.Selection([
            ('no_allocation', 'No allocation'),
            ('allocation_by_measurement', 'Allocation by measurement'),
            ('allocation_by_consumption', 'Allocation by consumption'),
            ('allocation_per_rental_unit', 'Allocation per rental unit'),
            ('allocation_from_external_billing', 'Allocation from external billing'),
            ('allocation_via_cost_collector', 'Allocation via cost collector'),
            ], "Allocation Rule", sort=False,
            states={
                'readonly': Eval('state').in_(['ready_for_billing', 'billed']),
            },
            help="'Allocation via cost collector': this settlement unit "
                 "determines no rental objects of its own - it always uses "
                 "those of the 'Reference Settlement Unit' - and generates "
                 "no cost shares/settlement results itself. Its planned/"
                 "actual costs are added to the reference settlement unit's "
                 "'Planned Costs From References'/'Actual Costs From "
                 "References' instead, where the actual cost allocation "
                 "takes place. Also selectable on a billing unit with "
                 "external billing, as an alternative to 'Allocation from "
                 "external billing'.",
            )

    reference_settlement_unit = fields.Many2One(
        'real_estate.settlement_unit', "Reference Settlement Unit",
        ondelete='RESTRICT',
        domain=[
            ('billing_unit', '=', Eval('billing_unit', -1)),
            ('id', '!=', Eval('id', -1)),
            ('allocation_rule', '!=', 'allocation_via_cost_collector'),
            ],
        states={
            'invisible': Eval('allocation_rule') != 'allocation_via_cost_collector',
            'required': Eval('allocation_rule') == 'allocation_via_cost_collector',
            'readonly': Eval('state').in_(['ready_for_billing', 'billed']),
            },
        depends=['billing_unit', 'allocation_rule'],
        help="The settlement unit (of the same billing unit) that "
             "actually performs the cost allocation for this unit's "
             "costs. Must not itself use 'Allocation via cost collector' "
             "(chaining is not allowed).")

    planned_costs_from_references = fields.Function(
        Monetary("Planned Costs From References", currency='currency',
            digits='currency',
            help="Sum of 'Planned Costs' of all settlement units of this "
                 "billing unit that reference this settlement unit via "
                 "'Allocation via cost collector'."),
        'get_costs_from_references')

    actual_costs_from_references = fields.Function(
        Monetary("Actual Costs From References", currency='currency',
            digits='currency',
            help="Sum of 'Actual Costs' of all settlement units of this "
                 "billing unit that reference this settlement unit via "
                 "'Allocation via cost collector'."),
        'get_costs_from_references')

    vacancy = fields.Selection([
        ('no_allocation', 'No allocation (all cost allocated by tenant)'),
        ('by_owner', 'Allocation by owner'),
        ], "Allocation During Vacancy", sort=False,
        states={
            'invisible': Eval('allocation_rule').in_(
                ['no_allocation', 'allocation_via_cost_collector']),
            'readonly': Eval('state').in_(['ready_for_billing', 'billed']),
            },
        )

    m_type = fields.Many2One(
        'real_estate.measurement.type', "Measurement Type",
        domain=[('types', '=', ['object'])],
        states={
            'invisible': Eval('allocation_rule') != 'allocation_by_measurement',
            'required': Eval('allocation_rule') == 'allocation_by_measurement',
            'readonly': Eval('state').in_(['ready_for_billing', 'billed']),
            })

    meter_unit = fields.Many2One('product.uom', "Unit",
        states={
            'invisible': Eval('allocation_rule') != 'allocation_by_consumption',
            'required': Eval('allocation_rule') == 'allocation_by_consumption',
            'readonly': Eval('state').in_(['ready_for_billing', 'billed']),
            })

    reg_ex_object = fields.Char("Reg. Ex. Object",
        help="Regular expression to find the object. For Example '[1-9/ ]*Apartement[1-9()# ]*' to find the object with name contains '100/100 Apartement #45'.",
        states={
            'invisible': Eval('allocation_rule').in_(
                ['no_allocation', 'allocation_via_cost_collector']),
            })

    reg_ex_meter = fields.Char("Reg. Ex. Meter",
        help="Regular expression to find the meter. For Example '[1-9/ ]*Electricity[1-9a-Z()# ]*' to find the meter with name contains '556 Electricity Meter'.",
        states={
            'invisible': Eval('allocation_rule') != 'allocation_by_consumption',
            })

    proportional_calculation = fields.Selection([
            ('none', 'None'),
            ('linear_interpolation', 'Linear interpolation'),
            ('degree_day', 'Weather-dependent (degree-day)'),
            ], "Calculate proportionally", sort=False,
            states={
                'invisible': Eval('allocation_rule') != 'allocation_by_consumption',
                'required': Eval('allocation_rule') == 'allocation_by_consumption',
                'readonly': Eval('state') != 'draft',
                })

    objects = fields.Function(fields.One2Many('real_estate.base_object', None, 'Objects',
                                              readonly=True,
        states={
            'invisible': Eval('allocation_rule') == 'no_allocation',
            }
        ), 'on_change_with_objects',
        setter='set_objects',
        )

    meters = fields.Function(fields.One2Many('real_estate.base_object', None, 'Meters',
                                              readonly=True,
        states={
            'invisible': ((Eval('allocation_rule') != 'allocation_by_consumption') | (Eval('state') == 'billed')),
            }
        ), 'on_change_with_meters',
        setter='set_meters',
        )

    measurements = fields.Function(fields.One2Many('real_estate.measurement', None, 'Measurements',
                                              readonly=True,
        states={
            'invisible': ((Eval('allocation_rule') != 'allocation_by_measurement') | (Eval('state') == 'billed')),
            }
        ), 'on_change_with_measurements',
        setter='set_measurements',
        )

    cost_shares = fields.One2Many('real_estate.cost_share', 'settlement_unit', 'Cost Shares',
        states={
            'readonly': True,
            'invisible': ((Bool(Eval('cost_shares', 0)) == False) | (Eval('state') == 'draft')),
            },
        )

    value_total = fields.Float('Value to Total', digits=(16, 4),
        states={'readonly': True}
        )

    time_total = fields.Function(fields.Integer('Time Total (days)'),
        'on_change_with_time_total')

    invoice_lines = fields.Function(fields.One2Many('account.invoice.line', 'settlement_unit', 'Invoice Lines'),
        'on_change_with_invoice_lines', setter='set_invoice_lines')

    option_rate_method = fields.Selection([
            ('fix_0', 'Fix: Option Rate 0.0 %'),
            ('fix_100', 'Fix: Option Rate 100.0 %'),
            ('fix_value', 'Fix: Option Rate by Value'),
            ('dynamic_measurement', 'Dynamic Measurement'),
            ], "Option Rate Method", required=True, sort=False)

    option_measurement_type = fields.Many2One(
        'real_estate.measurement.type', "Option Measurement Type",
        ondelete='RESTRICT',
        help="If a measurement group is selected, all its child "
             "measurement types are summed per rental object.",
        states={
            'invisible': Eval('option_rate_method') != 'dynamic_measurement',
            'required': Eval('option_rate_method') == 'dynamic_measurement',
            })

    option_rate_value = fields.Numeric(
        "Option Rate Value", digits=(5, 2),
        domain=[
            ('option_rate_value', '>=', 0),
            ('option_rate_value', '<=', 100),
            ],
        states={
            'invisible': Eval('option_rate_method') != 'fix_value',
            'required': Eval('option_rate_method') == 'fix_value',
            })

    option_rates = fields.One2Many('real_estate.option_rate', 'settlement_unit',
        "Option Rates")

    purchase_taxes_expense = fields.Function(
        fields.Boolean("Purchase Taxes as Expense"),
        'on_change_with_purchase_taxes_expense')

    co2_kostaufg = fields.Many2One('real_estate.co2_kostaufg',
        "CO2KostAufG Reference", ondelete='RESTRICT',
        domain=[('property', '=', Eval('property', -1))],
        states={'readonly': Eval('state').in_(['ready_for_billing', 'billed'])},
        depends=['property'])

    co2_consumption = fields.Function(
        fields.One2Many('real_estate.co2_kostaufg.consumption', None,
            "Consumption Records", readonly=True,
            help="All consumption records of the referenced CO2KostAufG "
                 "that overlap the settlement period (billing unit "
                 "period).",
            states={'invisible': ~Eval('co2_kostaufg')}),
        'on_change_with_co2_consumption', setter='set_co2_consumption')

    # --- Heizkostenabrechnung (HeizkostenV §7/§8): the split between
    # consumption-based and area-based allocation for a central heating
    # or hot water system. Independent of allocation_rule/m_type above
    # (which govern how THIS settlement unit's own costs are allocated
    # per tenant) - this is the legally mandated consumption/area split
    # ratio for the heating cost statement itself.
    heating_billing_mode = fields.Selection([
        ('none', 'Not Applicable'),
        ('central_heating', 'Central Heating System'),
        ('central_hot_water', 'Central Hot Water System'),
        ], "Heating Cost Billing", sort=False,
        states={'readonly': Eval('state').in_(['ready_for_billing', 'billed'])})

    heating_consumption_share_percent = fields.Numeric(
        "Consumption Allocation Share (%)", digits=(5, 2),
        domain=[
            If(Eval('heating_billing_mode').in_(
                ['central_heating', 'central_hot_water']),
                [('heating_consumption_share_percent', '>=', 50),
                    ('heating_consumption_share_percent', '<=', 70)],
                []),
            ],
        states={
            'invisible': ~Eval('heating_billing_mode').in_(
                ['central_heating', 'central_hot_water']),
            'required': Eval('heating_billing_mode').in_(
                ['central_heating', 'central_hot_water']),
            'readonly': Eval('state').in_(['ready_for_billing', 'billed']),
            },
        help="HeizkostenV §7/§8: percentage of heating/hot water cost "
             "allocated by consumption. Must be between 50% and 70% "
             "(statutory range). The remaining percentage "
             "('Anteil nach Flächenumlage') is allocated by area and "
             "computed automatically as 100% minus this value.")

    heating_area_share_percent = fields.Function(
        fields.Numeric("Area Allocation Share (%)", digits=(5, 2),
            states={
                'invisible': ~Eval('heating_billing_mode').in_(
                    ['central_heating', 'central_hot_water']),
                }),
        'on_change_with_heating_area_share_percent')

    heating_area_measurement_type = fields.Many2One(
        'real_estate.measurement.type', "Area Measurement Type "
        "(Heating Cost Split)",
        ondelete='RESTRICT',
        domain=[('types', '=', ['object'])],
        states={
            'invisible': ~Eval('heating_billing_mode').in_(
                ['central_heating', 'central_hot_water']),
            'required': Eval('heating_billing_mode').in_(
                ['central_heating', 'central_hot_water']),
            'readonly': Eval('state').in_(['ready_for_billing', 'billed']),
            },
        help="Which object-level measurement type to use for the "
             "'Anteil nach Flächenumlage' portion of the heating cost "
             "split (HeizkostenV §7/§8).")

    total_value_consumption = fields.Float(
        "Total Value Consumption", digits=(16, 4),
        states={
            'invisible': ~Eval('heating_billing_mode').in_(
                ['central_heating', 'central_hot_water']),
            'readonly': True,
            },
        help="Sum of 'Verbrauch (Anteil)' across all cost shares of this "
             "settlement unit. Computed by 'Compute Value Shares' on the "
             "billing unit.")

    total_value_area = fields.Float(
        "Total Value Area", digits=(16, 4),
        states={
            'invisible': ~Eval('heating_billing_mode').in_(
                ['central_heating', 'central_hot_water']),
            'readonly': True,
            },
        help="Sum of 'Fläche (Anteil)' across all cost shares of this "
             "settlement unit. Computed by 'Compute Value Shares' on the "
             "billing unit.")

    bved_fuel_data = fields.Boolean("BVED Fuel Data (B-Satz)",
        states={'readonly': Eval('state').in_(['ready_for_billing', 'billed'])},
        help="Enable to enter B-Satz fuel/stock data on this settlement "
             "unit for BVED export (typically the heating cost unit of an "
             "externally billed billing unit).")

    bved_fuel_type = fields.Selection(
        'get_bved_fuel_types', "BVED Fuel Type", sort=False,
        states={'invisible': ~Eval('bved_fuel_data')},
        help="BVED Tabelle 'B'.")

    bved_heating_value = fields.Numeric(
        "Heating Value (kWh per unit)", digits=(7, 4),
        states={'invisible': ~Eval('bved_fuel_data')},
        help="Mandatory once a fuel type is selected.")

    bved_stock_start_date = fields.Date("Stock Start Date",
        states={'invisible': ~Eval('bved_fuel_data')})
    bved_stock_start_quantity = fields.Numeric(
        "Stock Start Quantity", digits=(8, 3),
        states={'invisible': ~Eval('bved_fuel_data')})
    bved_stock_start_amount_gross = fields.Numeric(
        "Stock Start Amount (gross)", digits=(8, 2),
        states={'invisible': ~Eval('bved_fuel_data')})
    bved_stock_start_amount_net = fields.Numeric(
        "Stock Start Amount (net)", digits=(8, 2),
        states={'invisible': ~Eval('bved_fuel_data')})

    bved_stock_end_date = fields.Date("Stock End Date",
        states={'invisible': ~Eval('bved_fuel_data')})
    bved_stock_end_quantity = fields.Numeric(
        "Stock End Quantity", digits=(8, 3),
        states={'invisible': ~Eval('bved_fuel_data')})
    bved_stock_end_amount_gross = fields.Numeric(
        "Stock End Amount (gross)", digits=(8, 2),
        states={'invisible': ~Eval('bved_fuel_data')})
    bved_stock_end_amount_net = fields.Numeric(
        "Stock End Amount (net)", digits=(8, 2),
        states={'invisible': ~Eval('bved_fuel_data')})

    bved_ww_temperature = fields.Numeric(
        "Hot Water Temperature (avg. °C)", digits=(2, 2),
        states={'invisible': ~Eval('bved_fuel_data')})
    bved_ww_consumption_m3 = fields.Numeric(
        "Hot Water Consumption (m³)", digits=(6, 3),
        states={'invisible': ~Eval('bved_fuel_data')})
    bved_ww_percentage = fields.Numeric(
        "Hot Water Percentage (flat rate)", digits=(2, 2),
        states={'invisible': ~Eval('bved_fuel_data')})
    bved_ww_meter_start = fields.Numeric(
        "Hot Water Meter Start", digits=(6, 3),
        states={'invisible': ~Eval('bved_fuel_data')})
    bved_ww_meter_end = fields.Numeric(
        "Hot Water Meter End", digits=(6, 3),
        states={'invisible': ~Eval('bved_fuel_data')})

    bved_supply_period_heating_1_start = fields.Date(
        "1st Supply Period Heating (Start)",
        states={'invisible': ~Eval('bved_fuel_data')})
    bved_supply_period_heating_1_end = fields.Date(
        "1st Supply Period Heating (End)",
        states={'invisible': ~Eval('bved_fuel_data')})
    bved_supply_period_heating_2_start = fields.Date(
        "2nd Supply Period Heating (Start)",
        states={'invisible': ~Eval('bved_fuel_data')})
    bved_supply_period_heating_2_end = fields.Date(
        "2nd Supply Period Heating (End)",
        states={'invisible': ~Eval('bved_fuel_data')})
    bved_supply_period_ww_1_start = fields.Date(
        "1st Supply Period Hot Water (Start)",
        states={'invisible': ~Eval('bved_fuel_data')})
    bved_supply_period_ww_1_end = fields.Date(
        "1st Supply Period Hot Water (End)",
        states={'invisible': ~Eval('bved_fuel_data')})
    bved_supply_period_ww_2_start = fields.Date(
        "2nd Supply Period Hot Water (Start)",
        states={'invisible': ~Eval('bved_fuel_data')})
    bved_supply_period_ww_2_end = fields.Date(
        "2nd Supply Period Hot Water (End)",
        states={'invisible': ~Eval('bved_fuel_data')})

    bved_primary_energy_factor = fields.Numeric(
        "Primary Energy Factor", digits=(1, 2),
        states={'invisible': ~Eval('bved_fuel_data')},
        help="Required (mandatory in the standard) when the fuel type is "
             "district heating (Fernwärme).")

    @staticmethod
    def get_bved_fuel_types():
        return [('', '')] + bved_records.as_selection(bved_records.TABLE_B)

    @staticmethod
    def default_bved_fuel_data():
        return False

    @classmethod
    def delete(cls, settlement_units):
        for su in settlement_units:
            if su.billing_unit and su.billing_unit.state != 'draft':
                raise ValidationError(gettext(
                    'real_estate.msg_settlement_unit_delete_not_draft',
                    name=su.name,
                    state=su.billing_unit.state))
        super().delete(settlement_units)

    @classmethod
    def view_attributes(cls):
        return super().view_attributes() + [
            ('//page[@id="page_measurements"]', 'states', {
                'invisible': Eval('allocation_rule') != 'allocation_by_measurement',
            }),
            ('//page[@id="page_meters"]', 'states', {
                'invisible': Eval('allocation_rule') != 'allocation_by_consumption',
            }),
            ('//page[@id="page_option_rate"]', 'states', {
                'invisible': Bool(Eval('purchase_taxes_expense', False)),
            }),
            ('//page[@id="page_bved_fuel"]', 'states', {
                'invisible': ~Eval('bved_fuel_data'),
            }),
            ('/tree', 'visual',
                If(Eval('sub_state', '') == 'error', 'danger', ''),
                ['sub_state']),
        ]

    @classmethod
    def default_proportional_calculation(cls):
        return 'none'

    @classmethod
    def default_option_rate_value(cls):
        return 0.0

    @classmethod
    def default_option_rate_method(cls):
        return 'fix_0'

    @classmethod
    def default_company(cls):
        return Transaction().context.get('company')

    @classmethod
    def default_allocation_rule(cls):
        return 'no_allocation'

    @staticmethod
    def default_vacancy():
        return 'no_allocation'

    @staticmethod
    def default_heating_billing_mode():
        return 'none'

    @fields.depends('heating_consumption_share_percent')
    def on_change_with_heating_area_share_percent(self, name=None):
        if self.heating_consumption_share_percent is None:
            return None
        return Decimal(100) - self.heating_consumption_share_percent

    @staticmethod
    def default_option_rate_method():
        return 'fix_0'

    @fields.depends('company', '_parent_company.purchase_taxes_expense')
    def on_change_with_purchase_taxes_expense(self, name=None):
        if self.company:
            return self.company.purchase_taxes_expense
        return False

    @staticmethod
    def get_states():
        pool = Pool()
        BillingUnit = pool.get('real_estate.billing_unit')
        return BillingUnit.fields_get(['state'])['state']['selection']

    @staticmethod
    def get_sub_states():
        pool = Pool()
        CostShare = pool.get('real_estate.cost_share')
        return CostShare.fields_get(['state'])['state']['selection']

    @fields.depends('billing_unit', '_parent_billing_unit.external_billing')
    def on_change_with_billing_unit_external_billing(self, name=None):
        if self.billing_unit:
            return bool(self.billing_unit.external_billing)
        return False

    @fields.depends('type', 'sequence')
    def on_change_type(self):
        if self.type and not self.sequence:
            self.sequence = self.type.sequence

    @fields.depends('billing_unit', 'allocation_rule', '_parent_billing_unit.external_billing')
    def on_change_billing_unit(self):
        if self.billing_unit and self.billing_unit.external_billing:
            self.allocation_rule = 'allocation_from_external_billing'

    @fields.depends('billing_unit', '_parent_billing_unit.state')
    def on_change_with_state(self, name=None):
        return self.billing_unit.state if self.billing_unit else None

    def get_sub_state(self, name):
        if getattr(self, 'allocation_rule', None) in (
                'no_allocation', 'allocation_via_cost_collector'):
            return 'no_allocation'
        if self.cost_shares:
            states = set(cs.state for cs in self.cost_shares)
            if len(states) == 1:
                return states.pop()
            elif 'error' in states:
                return 'error'
            elif 'selection' in states:
                return 'selection'
            elif 'estimated_value_share' in states:
                return 'estimated_value_share'
            elif 'value_share' in states:
                return 'value_share'
        elif getattr(self, 'vacancy', None) == 'no_allocation':
            return 'no_allocation'
        return 'preparation'

    @fields.depends('cost_shares', 'allocation_rule', 'vacancy')
    def on_change_with_sub_state(self, name=None):
        return self.get_sub_state(name)

    @fields.depends('billing_unit', '_parent_billing_unit.property')
    def on_change_with_property(self, name=None):
        return self.billing_unit.property if self.billing_unit else None

    @classmethod
    def search_property(cls, name, clause):
        return [('billing_unit.' + clause[0],) + tuple(clause[1:])]

    @fields.depends('billing_unit', '_parent_billing_unit.property')
    def on_change_with_company(self, name=None):
        return self.billing_unit.property.company if self.billing_unit else None

    @fields.depends(
        'billing_unit', 'reg_ex_object', 'allocation_rule', 'state', 'cost_shares',
        'reference_settlement_unit',
        '_parent_billing_unit.company', '_parent_billing_unit.property',
        '_parent_reference_settlement_unit.objects')
    def on_change_with_objects(self, name=None):
        if self.allocation_rule == 'allocation_via_cost_collector':
            return (list(self.reference_settlement_unit.objects)
                if self.reference_settlement_unit else [])
        if self.state == 'billed':
            # Once billed, the objects actually covered by this settlement
            # unit are the ones that ended up with a cost share, not
            # whatever the live reg_ex_object search matches today.
            objects = []
            seen_ids = set()
            for cost_share in self.cost_shares:
                if cost_share.base_object and cost_share.base_object.id not in seen_ids:
                    seen_ids.add(cost_share.base_object.id)
                    objects.append(cost_share.base_object)
            return objects
        objects = []
        if self.billing_unit and self.allocation_rule != 'no_allocation':
            objects = Pool().get('real_estate.base_object').search([
                ('company', '=', self.billing_unit.company),
                ('property', '=', self.billing_unit.property),
                ('type', '=', 'object'),
                ('state', '=', 'approved'),
            ])
            if self.reg_ex_object:
                pattern = re.compile(self.reg_ex_object)
                objects = [item for item in objects if pattern.search(item.name)]
        return objects

    @fields.depends(
        'billing_unit', 'reg_ex_meter', 'allocation_rule', 'objects', 'meter_unit',
        '_parent_billing_unit.company', '_parent_billing_unit.property')
    def on_change_with_meters(self, name=None):
        meters = []
        if self.billing_unit and self.objects and self.allocation_rule == 'allocation_by_consumption':
            meters = Pool().get('real_estate.base_object').search([
                ('company', '=', self.billing_unit.company),
                ('property', '=', self.billing_unit.property),
                ('parent', 'in', [obj.id for obj in self.objects]),
                ('type', '=', 'equipment'),
                ('e_type', '=', 'meters'),
                ('meter_unit', '=', self.meter_unit),
                ('state', '=', 'approved'),
            ])
            if self.reg_ex_meter:
                pattern = re.compile(self.reg_ex_meter)
                meters = [item for item in meters if pattern.search(item.name)]
        return meters

    @fields.depends(
        'billing_unit', 'm_type', 'allocation_rule', 'objects',
        '_parent_billing_unit.company', '_parent_billing_unit.property')
    def on_change_with_measurements(self, name=None):
        measurements = []
        if self.billing_unit and self.objects and self.allocation_rule == 'allocation_by_measurement':
            pool = Pool()
            MeasurementType = pool.get('real_estate.measurement.type')
            effective_ids = MeasurementType.get_effective_ids(self.m_type)
            if effective_ids:
                measurements = pool.get('real_estate.measurement').search([
                    ('base_object', 'in', [obj.id for obj in self.objects]),
                    ('m_type', 'in', effective_ids),
                ], order=[('base_object', 'ASC'), ('valid_from', 'DESC')])
        return measurements

    def on_change_with_invoice_lines(self, name=None):
        invoice_lines = Pool().get('account.invoice.line').search([
            ('settlement_unit', '=', self.id),
            ('invoice.state', '!=', 'cancelled'),
        ])
        return invoice_lines

    def _split_co2_consumption(self):
        """Split real co2_kostaufg.consumption rows so their boundaries
        align with this settlement unit's period [start_date, end_date].
        Called from compute_value_shares() ("Compute Value Shares").
        Only ever splits an EXISTING row into two rows that together
        reproduce that row's own totals exactly (linear interpolation by
        day count) - never invents data for a period with no row."""
        if not self.co2_kostaufg or not self.start_date or not self.end_date:
            return
        self._split_co2_consumption_at(self.start_date)
        self._split_co2_consumption_at(
            self.end_date + datetime.timedelta(days=1))

    def _split_co2_consumption_at(self, cut_date):
        """Split every (active) co2_kostaufg.consumption row of
        self.co2_kostaufg whose own [date_from, date_to] strictly
        contains cut_date (date_from < cut_date <= date_to - i.e.
        cut_date is not already a boundary) into two new rows:
        [date_from, cut_date - 1 day] and [cut_date, date_to]. Amounts
        (consumption_kwh, co2_emission_kg, co2_cost_net, co2_cost_gross)
        are interpolated pro-rata by day count so the two new rows sum
        back exactly to the original row's own values (the second part
        is computed as the remainder, not independently rounded, to
        avoid rounding drift); rate fields (co2_kg_per_kwh,
        co2_price_ct_per_kwh, vat_rate) are copied unchanged onto both.
        Both new rows get split=True; the original row is deactivated
        (soft-deleted via `active`), never physically deleted."""
        pool = Pool()
        Consumption = pool.get('real_estate.co2_kostaufg.consumption')
        rows = Consumption.search([
            ('parent', '=', self.co2_kostaufg.id),
            ('date_from', '<', cut_date),
            ('date_to', '>=', cut_date),
            ])
        if not rows:
            return
        day_before_cut = cut_date - datetime.timedelta(days=1)

        def split_amount(value, fraction, digits):
            if value is None:
                return None, None
            first = (value * fraction).quantize(Decimal(1).scaleb(-digits))
            return first, value - first

        new_vlist = []
        for row in rows:
            total_days = (row.date_to - row.date_from).days + 1
            first_days = (day_before_cut - row.date_from).days + 1
            first_fraction = Decimal(first_days) / Decimal(total_days)

            consumption_first, consumption_second = split_amount(
                row.consumption_kwh, first_fraction, 2)
            emission_first, emission_second = split_amount(
                row.co2_emission_kg, first_fraction, 3)
            cost_net_first, cost_net_second = split_amount(
                row.co2_cost_net, first_fraction, 2)
            cost_gross_first, cost_gross_second = split_amount(
                row.co2_cost_gross, first_fraction, 2)

            common = {
                'parent': row.parent.id,
                'co2_kg_per_kwh': row.co2_kg_per_kwh,
                'co2_price_ct_per_kwh': row.co2_price_ct_per_kwh,
                'vat_rate': row.vat_rate,
                'split': True,
                }
            new_vlist.append(dict(common,
                date_from=row.date_from, date_to=day_before_cut,
                consumption_kwh=consumption_first,
                co2_emission_kg=emission_first,
                co2_cost_net=cost_net_first,
                co2_cost_gross=cost_gross_first))
            new_vlist.append(dict(common,
                date_from=cut_date, date_to=row.date_to,
                consumption_kwh=consumption_second,
                co2_emission_kg=emission_second,
                co2_cost_net=cost_net_second,
                co2_cost_gross=cost_gross_second))
        Consumption.create(new_vlist)
        Consumption.write(list(rows), {'active': False})

    def _co2_consumption_rows(self):
        """Consumption rows of self.co2_kostaufg overlapping the
        settlement period [start_date, end_date]."""
        if not self.co2_kostaufg or not self.start_date or not self.end_date:
            return []
        Consumption = Pool().get('real_estate.co2_kostaufg.consumption')
        return Consumption.search([
            ('parent', '=', self.co2_kostaufg.id),
            ('date_from', '<=', self.end_date),
            ('date_to', '>=', self.start_date),
            ])

    @fields.depends(
        'co2_kostaufg', 'start_date', 'end_date', 'billing_unit',
        '_parent_billing_unit.start_date', '_parent_billing_unit.end_date')
    def on_change_with_co2_consumption(self, name=None):
        return self._co2_consumption_rows()

    @classmethod
    def get_costs_from_references(cls, records, names):
        result = {name: {r.id: Decimal(0) for r in records} for name in names}
        referencing = cls.search([
            ('reference_settlement_unit', 'in', [r.id for r in records]),
            ])
        for su in referencing:
            ref_id = su.reference_settlement_unit.id
            if 'planned_costs_from_references' in result:
                result['planned_costs_from_references'][ref_id] += (
                    su.planned_costs or Decimal(0))
            if 'actual_costs_from_references' in result:
                result['actual_costs_from_references'][ref_id] += (
                    su.actual_costs or Decimal(0))
        return result

    @classmethod
    def set_objects(cls, objects, name, value):
        pass

    @classmethod
    def set_meters(cls, meters, name, value):
        pass

    @classmethod
    def set_measurements(cls, measurements, name, value):
        pass

    @classmethod
    def set_invoice_lines(cls, records, name, value):
        pass

    @classmethod
    def set_co2_consumption(cls, records, name, value):
        pass

    @classmethod
    def validate_fields(cls, units, field_names):
        super().validate_fields(units, field_names)
        # field_names is None on create() (check everything); on write()
        # it lists only the fields actually being written (check only if
        # a relevant one changed).
        check_all = field_names is None
        check_allocation = check_all or 'allocation_rule' in field_names
        check_reference = (check_all or check_allocation
            or 'reference_settlement_unit' in field_names)
        if not (check_allocation or check_reference):
            return
        for su in units:
            if check_allocation and su.billing_unit:
                if su.billing_unit.external_billing:
                    if su.allocation_rule not in (
                            'allocation_from_external_billing',
                            'allocation_via_cost_collector'):
                        raise ValidationError(gettext(
                            'real_estate.msg_settlement_unit_allocation_rule_required_external',
                            name=su.rec_name))
                else:
                    if su.allocation_rule == 'allocation_from_external_billing':
                        raise ValidationError(gettext(
                            'real_estate.msg_settlement_unit_allocation_rule_not_allowed_external',
                            name=su.rec_name))
            if check_reference and su.allocation_rule == 'allocation_via_cost_collector':
                ref = su.reference_settlement_unit
                if not ref:
                    raise ValidationError(gettext(
                        'real_estate.msg_settlement_unit_reference_required',
                        name=su.rec_name))
                elif (ref.id == su.id
                        or ref.allocation_rule == 'allocation_via_cost_collector'
                        or (su.billing_unit and ref.billing_unit
                            and ref.billing_unit.id != su.billing_unit.id)):
                    raise ValidationError(gettext(
                        'real_estate.msg_settlement_unit_reference_invalid',
                        name=su.rec_name))

    @fields.depends('type', 'sequence')
    def on_change_with_sequence(self, name=None):
        sequence = getattr(self, 'sequence', None)
        return self.type.sequence if (self.type and not sequence) else sequence

    @fields.depends('billing_unit', '_parent_billing_unit.start_date')
    def on_change_with_start_date(self, name=None):
        return self.billing_unit.start_date if self.billing_unit else None

    @fields.depends('billing_unit', '_parent_billing_unit.end_date')
    def on_change_with_end_date(self, name=None):
        return self.billing_unit.end_date if self.billing_unit else None

    @fields.depends('type', 'sequence')
    def on_change_with_name(self, name=None):
        return f"{self.sequence} - {self.type.name}" if self.type else f"{self.sequence} - ? "

    @fields.depends('company', 'billing_unit', '_parent_billing_unit.property')
    def on_change_with_currency(self, name=None):
        return self.company.currency if self.company else None

    @fields.depends(
        'start_date', 'end_date', 'billing_unit',
        '_parent_billing_unit.start_date', '_parent_billing_unit.end_date')
    def on_change_with_time_total(self, name=None):
        if self.start_date and self.end_date:
            return (self.end_date - self.start_date).days + 1
        return None

    def selection(self):
        """Select objects and contracts for billing using the occupancy table."""
        if self.state != 'approved' and self.state != 'selection' and self.state != 'value_share':
            raise ValidationError(gettext(
                'real_estate.msg_settlement_unit_selection_invalid_state',
                name=self.rec_name, state=self.state))

        CostShare = Pool().get('real_estate.cost_share')
        if self.cost_shares:
            CostShare.delete(list(self.cost_shares))

        if self.allocation_rule in ('no_allocation', 'allocation_via_cost_collector'):
            self.billing_unit.add_log('selection',
                f'Settlement unit {self.id}: {self.allocation_rule}'
                f' — selection skipped.')
            return


        Occupancy = Pool().get('real_estate.base_object.occupancy')
        is_weg = self.billing_unit.calculation_method == 'WEG_billing'
        bu_start = self.billing_unit.start_date
        bu_end = self.billing_unit.end_date
        object_count = 0

        for object in self.objects:
            if not (object.state == 'approved'
                    and object.start_date <= bu_end
                    and (object.end_date is None or object.end_date >= bu_start)):
                continue
            object_count += 1

            Occupancy.refresh([object])

            occ_domain = [
                ('base_object', '=', object.id),
                ('start_date', '<=', bu_end),
                ['OR', ('end_date', '=', None), ('end_date', '>=', bu_start)],
            ]

            if is_weg:
                entries = Occupancy.search(
                    occ_domain + [('state', '=', 'rented')],
                    order=[('start_date', 'DESC')], limit=1)
                if not entries:
                    self.billing_unit.add_log('selection_error',
                        f'Settlement unit {self.id}: no rented occupancy found'
                        f' for object {object.id}.')
                else:
                    cost_share = CostShare(
                        settlement_unit=self.id,
                        contract=entries[0].contract.id if entries[0].contract else None,
                        base_object=object.id,
                        start_date=bu_start,
                        end_date=bu_end,
                        state='selection',
                    )
                    cost_share.save()
            else:
                entries = Occupancy.search(occ_domain, order=[('start_date', 'ASC')])
                by_owner = self.vacancy == 'by_owner'
                rented = any(e.state == 'rented' for e in entries)
                if not rented and not (any(e.state == 'vacant' for e in entries) and by_owner):
                    self.billing_unit.add_log('selection_error',
                        f'Settlement unit {self.id}: no rented occupancy found'
                        f' for object {object.id}.')
                else:
                    for occ in entries:
                        share_start = max(occ.start_date, bu_start)
                        if occ.end_date:
                            share_end = min(occ.end_date, bu_end) if bu_end else occ.end_date
                        else:
                            share_end = bu_end

                        if occ.state == 'rented':
                            cost_share = CostShare(
                                settlement_unit=self.id,
                                contract=occ.contract.id if occ.contract else None,
                                base_object=object.id,
                                start_date=share_start,
                                end_date=share_end,
                                state='selection',
                            )
                            cost_share.save()
                        elif occ.state == 'vacant' and by_owner:
                            cost_share = CostShare(
                                settlement_unit=self.id,
                                contract=None,
                                base_object=object.id,
                                start_date=share_start,
                                end_date=share_end,
                                state='selection',
                            )
                            cost_share.save()
                            self.billing_unit.add_log('vacancy_selection',
                                f'Settlement unit {self.id}: vacancy cost share created'
                                f' for object {object.id} from {share_start} to {share_end}.')

        self.billing_unit.add_log('selection',
            f'Settlement unit {self.id} selection completed: {object_count} objects processed.')
        self.save()

    def selection_actual_costs(self):
        """Sum amount + tax of all invoice lines assigned to this settlement unit
        and write the result into actual_costs."""
        pool = Pool()
        InvoiceLine = pool.get('account.invoice.line')
        lines = InvoiceLine.search([
            ('settlement_unit', '=', self.id),
            ('invoice.state', '!=', 'cancelled'),
        ])
        actual = Decimal(0)
        for line in lines:
            amount = line.amount or Decimal(0)
            if self.property and self.property.billing_as == 'commercial':
                actual += amount
            else:
                # line.tax_amount is InvoiceLine's own computed field and
                # already accounts for taxes_deductible_rate - recomputing
                # the tax from unit_price here would double-count the
                # non-deductible share, which is already folded into
                # line.amount by core.
                actual += amount + (line.tax_amount or Decimal(0))
        self.actual_costs = actual.quantize(Decimal('0.01'))
        self.save()

    def compute_value_shares(self):
        """Compute value_share on each CostShare based on allocation_rule,
        then write value_total as the sum on this SettlementUnit."""
        self._split_co2_consumption()
        self.selection_actual_costs()
        for cost_share in self.cost_shares:
            if cost_share.state == 'error':
                cost_share.state = 'selection'
                cost_share.error_message = None
                cost_share.save()
        pool = Pool()
        Measurement = pool.get('real_estate.measurement')
        BaseObject = pool.get('real_estate.base_object')
        MeterReading = pool.get('real_estate.meter_reading')

        if self.allocation_rule in ('no_allocation', 'allocation_via_cost_collector'):
            return

        if self.allocation_rule == 'allocation_from_external_billing':
            self._compute_value_shares_external()
            return

        if (self.allocation_rule == 'allocation_by_consumption'
                and self.proportional_calculation == 'degree_day'):
            raise UserError(gettext(
                'real_estate.msg_degree_day_not_implemented',
                name=self.name))

        total = 0.0
        _unit = 0.0001

        # --- first pass: collect raw values without saving ---
        pending = []
        for cost_share in self.cost_shares:
            if not cost_share.base_object:
                continue

            value = None
            error_msg = None

            if self.allocation_rule == 'allocation_by_measurement':
                mval = Measurement.get_total_value(
                    cost_share.base_object.id, self.m_type, cost_share.end_date)
                if mval is not None:
                    value = (mval * cost_share.time_share / self.time_total
                             if self.time_total else mval)
                else:
                    error_msg = (
                        f'No measurement for {cost_share.base_object.rec_name}'
                        f' type {self.m_type.name} on {cost_share.end_date}')

            elif self.allocation_rule == 'allocation_by_consumption':
                # Vacancy (no contract): consumption = 0, no reading required.
                if not cost_share.contract:
                    value = 0.0
                else:
                    meter_domain = [
                        ('parent', '=', cost_share.base_object.id),
                        ('type', '=', 'equipment'),
                        ('e_type', '=', 'meters'),
                        ('meter_unit', '=', self.meter_unit.id),
                        ('state', '=', 'approved'),
                    ]
                    meters = BaseObject.search(meter_domain)
                    if self.reg_ex_meter:
                        pattern = re.compile(self.reg_ex_meter)
                        meters = [m for m in meters if pattern.search(m.name or '')]

                    if self.proportional_calculation == 'linear_interpolation':
                        consumption = 0.0
                        found = False
                        for meter in meters:
                            factor = float(meter.meter_factor or 1)
                            try:
                                end_rdg = MeterReading.set_interpolation_reading(
                                    meter, cost_share.end_date)
                                if meter.meter_is_counter:
                                    start_rdg = MeterReading.set_interpolation_reading(
                                        meter, cost_share.start_date)
                                    consumption += (
                                        float(end_rdg.value or 0)
                                        - float(start_rdg.value or 0)
                                    ) * factor
                                else:
                                    consumption += float(end_rdg.value or 0) * factor
                                found = True
                            except UserError as exc:
                                error_msg = exc.message
                                break

                        if found and error_msg is None:
                            value = consumption

                    else:  # 'none' (default): nearest reading within a tolerance window
                        pre_days = (self.type.reading_pre_days
                                    if self.type and self.type.reading_pre_days is not None
                                    else 7)
                        post_days = (self.type.reading_post_days
                                     if self.type and self.type.reading_post_days is not None
                                     else 7)

                        def _closest_reading(meter_id, target_date):
                            """Return the reading closest to target_date within the
                            window, considering all reading types (including
                            estimates and previously interpolated values)."""
                            lo = target_date - datetime.timedelta(days=pre_days)
                            hi = target_date + datetime.timedelta(days=post_days)
                            rdgs = MeterReading.search([
                                ('base_object', '=', meter_id),
                                ('reading_date', '>=', lo),
                                ('reading_date', '<=', hi),
                            ])
                            if not rdgs:
                                return None
                            return min(rdgs, key=lambda r: abs((r.reading_date - target_date).days))

                        # Predecessor vacancy: cost share for same object ending
                        # the day before this one's start_date with no contract.
                        cs_by_obj = sorted(
                            [c for c in self.cost_shares
                             if c.base_object and c.base_object.id == cost_share.base_object.id],
                            key=lambda c: c.start_date or datetime.date.min)
                        predecessor = None
                        for c in cs_by_obj:
                            if c.end_date and cost_share.start_date:
                                if c.end_date < cost_share.start_date:
                                    predecessor = c
                                else:
                                    break

                        consumption = 0.0
                        found = False
                        for meter in meters:
                            factor = float(meter.meter_factor or 1)
                            if meter.meter_is_counter:
                                end_rdg = _closest_reading(meter.id, cost_share.end_date)
                                start_rdg = _closest_reading(meter.id, cost_share.start_date)
                                # If no start reading and predecessor is a vacancy,
                                # try the reading at the start of that vacancy.
                                if start_rdg is None and predecessor and not predecessor.contract:
                                    start_rdg = _closest_reading(meter.id, predecessor.start_date)
                                if not end_rdg:
                                    error_msg = gettext(
                                        'real_estate.msg_no_end_reading',
                                        name=cost_share.base_object.rec_name,
                                        date=str(cost_share.end_date),
                                        pre=pre_days, post=post_days)
                                    break
                                if not start_rdg:
                                    error_msg = gettext(
                                        'real_estate.msg_no_start_reading',
                                        name=cost_share.base_object.rec_name,
                                        date=str(cost_share.start_date),
                                        pre=pre_days, post=post_days)
                                    break
                                consumption += (
                                    float(end_rdg.value or 0)
                                    - float(start_rdg.value or 0)
                                ) * factor
                                found = True
                            else:
                                rdg = _closest_reading(meter.id, cost_share.end_date)
                                if not rdg:
                                    error_msg = gettext(
                                        'real_estate.msg_no_end_reading',
                                        name=cost_share.base_object.rec_name,
                                        date=str(cost_share.end_date),
                                        pre=pre_days, post=post_days)
                                    break
                                consumption += float(rdg.value or 0) * factor
                                found = True

                        if found:
                            value = consumption

            elif self.allocation_rule == 'allocation_per_rental_unit':
                value = (cost_share.time_share / self.time_total
                         if self.time_total else 1.0)

            pending.append((cost_share, value, error_msg))

        # --- rounding and correction for time-weighted rules ---
        if self.allocation_rule in ('allocation_by_measurement',
                                    'allocation_per_rental_unit'):
            ok_rows = [(cs, v) for cs, v, _ in pending if v is not None]
            if ok_rows:
                rounded = [(cs, round(v, 4)) for cs, v in ok_rows]
                exact_sum = sum(v for _, v in ok_rows)
                rounded_sum = sum(v for _, v in rounded)
                diff = round(exact_sum - rounded_sum, 4)
                if diff > 0:
                    n = round(diff / _unit)
                    rounded.sort(key=lambda r: r[1])
                    for i in range(n):
                        cs, v = rounded[i % len(rounded)]
                        rounded[i % len(rounded)] = (cs, round(v + _unit, 4))
                elif diff < 0:
                    n = round(-diff / _unit)
                    rounded.sort(key=lambda r: r[1], reverse=True)
                    for i in range(n):
                        cs, v = rounded[i % len(rounded)]
                        rounded[i % len(rounded)] = (cs, round(v - _unit, 4))
                corrected = {id(cs): v for cs, v in rounded}
                pending = [
                    (cs, corrected[id(cs)] if v is not None else None, em)
                    for cs, v, em in pending
                ]
        else:
            pending = [
                (cs, round(v, 4) if v is not None else None, em)
                for cs, v, em in pending
            ]

        # --- second pass: save ---
        for cost_share, value, error_msg in pending:
            if value is not None:
                cost_share.value_share = value
                if cost_share.state in ('selection', 'estimated_value_share'):
                    cost_share.state = 'value_share'
                total += value
            else:
                cost_share.state = 'error'
                cost_share.error_message = error_msg
            cost_share.save()

        self.value_total = total
        self.save()

        self._compute_heizkostenv_split()

        CostShare = pool.get('real_estate.cost_share')
        vt = Decimal(str(total)) if total else Decimal(0)

        cost_shares = CostShare.search(
            [('settlement_unit', '=', self.id),
             ('state', '=', 'value_share')])

        def _distribute(su_amount):
            """Return list of (cost_share, rounded_amount) summing to su_amount."""
            _cent = Decimal('0.01')
            rows = []
            for cs in cost_shares:
                if not cs.value_share or not vt:
                    raw = Decimal(0)
                else:
                    vs = Decimal(str(cs.value_share))
                    raw = su_amount * vs / vt
                rows.append([cs, raw.quantize(_cent, rounding=ROUND_HALF_UP)])
            diff = (su_amount - sum(r[1] for r in rows)).quantize(_cent)
            if diff and rows:
                # Prefer cost shares with an actual (non-zero) value_share
                # to absorb the rounding remainder - a cost share with zero
                # consumption/measurement (e.g. a vacancy period with no
                # meter reading change) must never end up with a non-zero
                # cost purely due to rounding. Only fall back to all rows
                # if every row has value_share 0 (nothing else to put the
                # remainder on).
                adjustable = [r for r in rows if r[0].value_share] or rows
                n = int(abs(diff) / _cent)
                if diff > 0:
                    adjustable.sort(key=lambda r: r[1])
                    for i in range(n):
                        adjustable[i % len(adjustable)][1] += _cent
                else:
                    adjustable.sort(key=lambda r: r[1], reverse=True)
                    for i in range(n):
                        adjustable[i % len(adjustable)][1] -= _cent
            return rows

        total_planned = ((self.planned_costs or Decimal(0))
            + (self.planned_costs_from_references or Decimal(0)))
        total_actual = ((self.actual_costs or Decimal(0))
            + (self.actual_costs_from_references or Decimal(0)))
        planned_rows = _distribute(total_planned)
        actual_rows = _distribute(total_actual)

        actual_by_id = {r[0].id: r[1] for r in actual_rows}
        for cost_share, planned_amount in planned_rows:
            cost_share.planned_costs = planned_amount
            cost_share.actual_costs = actual_by_id.get(cost_share.id, Decimal(0))
            cost_share.save()

    def _compute_heizkostenv_split(self):
        """HeizkostenV split (heating_billing_mode = central_heating /
        central_hot_water): compute the raw consumption/area component
        values needed for the legally mandated Verbrauchsumlage/
        Flächenumlage split - independent of this settlement unit's own
        allocation_rule, and a no-op unless heating_billing_mode is set.

        - cost_share.area_share: value of heating_area_measurement_type
          for the cost share's object, weighted by
          time_share / self.time_total (same weighting as
          allocation_by_measurement) - computed for every cost share.
        - cost_share.consumption_share: only when allocation_rule is
          'allocation_by_consumption' - the raw consumption value the
          main computation above wrote into value_share is moved here
          instead (value_share is reset to 0), since for a
          HeizkostenV-split unit the raw consumption is no longer, on
          its own, the cost-distribution basis stored in value_share.

        self.total_value_consumption / self.total_value_area are the
        sum of these two fields across all of this unit's cost shares.
        """
        if self.heating_billing_mode not in (
                'central_heating', 'central_hot_water'):
            return
        Measurement = Pool().get('real_estate.measurement')
        total_consumption = 0.0
        total_area = 0.0
        for cost_share in self.cost_shares:
            if not cost_share.base_object:
                continue
            if self.allocation_rule == 'allocation_by_consumption':
                cost_share.consumption_share = cost_share.value_share or 0.0
                cost_share.value_share = 0.0
                total_consumption += cost_share.consumption_share
            if self.heating_area_measurement_type:
                mval = Measurement.get_total_value(
                    cost_share.base_object.id,
                    self.heating_area_measurement_type, cost_share.end_date)
                if mval is not None:
                    area = round(
                        mval * cost_share.time_share / self.time_total
                        if self.time_total else mval, 4)
                    cost_share.area_share = area
                    total_area += area
            cost_share.save()
        self.total_value_consumption = round(total_consumption, 4)
        self.total_value_area = round(total_area, 4)
        self.save()

    def _compute_value_shares_external(self):
        """For allocation_from_external_billing.

        Two modes depending on billing_unit.external_billing:

        False (classic): actual_costs and planned_costs must be entered manually
        on each CostShare. Missing value → error state.

        True (BU-level external): costs stay zero on CostShares; time-based
        value_share is calculated so proportions are available for reporting.
        Actual costs are entered later directly on SettlementResult via
        export/import.
        """
        CostShare = Pool().get('real_estate.cost_share')
        cost_shares = CostShare.search([('settlement_unit', '=', self.id)])

        bu_external = (self.billing_unit.external_billing
            if self.billing_unit else False)

        if bu_external:
            # BU-level external: CostShare amounts stay zero (no internal
            # per-apartment allocation). actual_costs on the SettlementUnit
            # is already set by selection_actual_costs() from invoices —
            # do NOT overwrite it here.
            for cs in cost_shares:
                cs.value_share = 0.0
                cs.actual_costs = Decimal(0)
                cs.planned_costs = Decimal(0)
                cs.state = 'value_share'
                cs.error_message = ''
                cs.save()
            combined_actual = ((self.actual_costs or Decimal(0))
                + (self.actual_costs_from_references or Decimal(0)))
            self.planned_costs = self.planned_costs_from_references or Decimal(0)
            self.value_total = float(combined_actual)
            self.save()
            self._compute_heizkostenv_split()
        else:
            # Classic mode: values must be entered per CostShare
            total_actual = Decimal(0)
            total_planned = Decimal(0)
            has_error = False
            for cs in cost_shares:
                if cs.actual_costs is None:
                    cs.state = 'error'
                    cs.error_message = 'No actual costs entered for external billing.'
                    cs.save()
                    has_error = True
                    continue
                cs.state = 'value_share'
                cs.error_message = ''
                cs.save()
                total_actual += cs.actual_costs or Decimal(0)
                total_planned += cs.planned_costs or Decimal(0)
            if not has_error:
                self.actual_costs = total_actual
                self.planned_costs = total_planned
                self.value_total = float(total_actual)
                self.save()
                self._compute_heizkostenv_split()

    def billing(self, selection_on=False):
        if self.state == 'billed':
            raise ValidationError(gettext(
                'real_estate.msg_settlement_unit_already_billed',
                name=self.rec_name))
        if self.state != 'draft':
            raise ValidationError(gettext(
                'real_estate.msg_settlement_unit_billing_invalid_state',
                name=self.rec_name, state=self.state))

        if selection_on:
            if self.allocation_rule not in (
                    'no_allocation', 'allocation_via_cost_collector'):
                self.selection()

    @classmethod
    def name_search(cls, name, clause):
        if clause[1].startswith('!') or clause[1].startswith('not '):
            bool_op = 'AND'
        else:
            bool_op = 'OR'

        return [bool_op,
            ('type.name',) + tuple(clause[1:]),
            ('property.name',) + tuple(clause[1:]),
            ('comment',) + tuple(clause[1:]),
        ]

#********************************************************************
class SettlementUnitContext(ModelView):
    'Settlement Unit Context'
    __name__ = 'real_estate.settlement_unit.context'

    company = fields.Many2One('company.company', 'Company', required=True)
    property = fields.Many2One('real_estate.base_object', 'Property',
        domain=[
            ('type', '=', 'property'),
            ('company', '=', Eval('company', -1)),
        ])

    @classmethod
    def default_company(cls):
        return Transaction().context.get('company')
