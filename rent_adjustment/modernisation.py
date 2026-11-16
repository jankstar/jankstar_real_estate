'Modernisation (§§ 555b-555f, 559-559e BGB) - measure, costs, funds, rental units (spezifikation-modernisierung.md)'
import builtins
import datetime
from decimal import ROUND_HALF_UP, Decimal

from dateutil.relativedelta import relativedelta

from trytond.i18n import gettext
from trytond.model import ModelSQL, ModelView, Workflow, fields, sequence_ordered
from trytond.model.exceptions import ValidationError
from trytond.modules.currency.fields import Monetary
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Bool, Eval, If, PYSONEncoder
from trytond.report import Report
from trytond.transaction import Transaction, without_check_access
from trytond.wizard import (
    Button, StateAction, StateTransition, StateView, Wizard)
from trytond.exceptions import UserWarning as TrytonUserWarning

CENT = Decimal('0.01')

# Measures according to § 555b BGB (spec 2.1) - code -> label
MEASURE_TYPES = [
    ('1', "No. 1 - Saving final energy (energetic)"),
    ('1a', "No. 1a - Heating system according to GEG"),
    ('2', "No. 2 - Saving primary energy / climate protection"),
    ('3', "No. 3 - Reducing water consumption"),
    ('4', "No. 4 - Increasing the utility value"),
    ('4a', "No. 4a - First connection to fibre optics"),
    ('5', "No. 5 - Improving the general living conditions"),
    ('6', "No. 6 - Circumstances not attributable to the landlord"),
    ('7', "No. 7 - Creating new living space"),
    ]
# Measures without an increase according to § 559 BGB
NOT_ALLOCABLE = {'2', '7'}
VARIANTS = [
    ('standard_559', "Standard (§ 559, 8 %)"),
    ('simplified_559c', "Simplified (§ 559c)"),
    ('heating_559e', "Heating system (§ 559e, 10 %)"),
    ]
STATES = [
    ('planning', "Planning"),
    ('draft', "Draft"),
    ('announced', "Announced"),
    ('in_progress', "In Progress"),
    ('completed', "Completed"),
    ('settled', "Settled"),
    ('cancelled', "Cancelled"),
    ]
# state of the measure from which the planning values are frozen
EDITABLE = ['planning', 'draft']


def _cent(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def _end_of_next_month(date):
    "End of the month following the month of 'date'"
    if not date:
        return None
    return date.replace(day=1) + relativedelta(months=2) - datetime.timedelta(
        days=1)


#**********************************************************************
# Calculation (spec 6.1-6.5) - pure functions

def allocation_shares(units, key):
    """Share per unit key of the participating units: equal, or
    measurement/manual (quantity per unit, e.g. living space or number of
    windows - share = quantity / total). 'units' is a list of dicts with
    key, in_allocation, quantity."""
    participants = [u for u in units if u['in_allocation']]
    shares = {u['key']: Decimal(0) for u in units}
    if not participants:
        return shares
    if key == 'equal':
        for u in participants:
            shares[u['key']] = Decimal(1) / len(participants)
    else:
        total = sum(Decimal(u.get('quantity') or 0) for u in participants)
        if total:
            for u in participants:
                shares[u['key']] = Decimal(u.get('quantity') or 0) / total
    return shares


def compute_allocation(costs, funds, units, variant, key, rule,
        cost_factor=Decimal(1)):
    """Allocable costs, annual and monthly increase per unit (spec 6.1,
    6.2, 6.3, 6.5).

    costs: dicts net, tax, maintenance_mode ('none'/'percent'/'amount'),
        maintenance_value, unit (unit key or None)
    funds: dicts kind ('grant'/'third_party'/'loan_interest'), amount,
        annual_benefit, unit
    units: dicts key, area (for the cap, None = no cap), in_allocation,
        quantity, vat_deductible,
        rent (monthly rent before, None for a vacancy), previous
        (increases of the last years for the cap), previous_heating
    rule: dict of the modernisation rule (rates, flat rates, caps)
    Returns {unit key: dict}."""
    shares = allocation_shares(units, key)
    if variant == 'simplified_559c':
        flat = Decimal(rule['simplified_maintenance_percent']) / 100
    elif variant == 'heating_559e':
        flat = Decimal(rule['heating_maintenance_percent']) / 100
    else:
        flat = None
    rate = Decimal(rule['rate_heating'] if variant == 'heating_559e'
        else rule['rate_standard']) / 100
    result = {}
    for unit in units:
        key_ = unit['key']
        share = shares[key_]
        gross_basis = not unit.get('vat_deductible')
        costs_i = maintenance_i = Decimal(0)
        for cost in costs:
            if cost.get('unit') not in (None, key_):
                continue
            factor = Decimal(1) if cost.get('unit') == key_ else share
            net = Decimal(cost['net'] or 0)
            tax = Decimal(cost.get('tax') or 0)
            base = net + tax if gross_basis else net
            if flat is not None:
                maintenance = base * flat
            elif cost.get('maintenance_mode') == 'percent':
                maintenance = base * Decimal(
                    cost.get('maintenance_value') or 0) / 100
            elif cost.get('maintenance_mode') == 'amount':
                # entered net - on a gross basis with the tax ratio
                maintenance = Decimal(cost.get('maintenance_value') or 0)
                if gross_basis and net:
                    maintenance = maintenance * (net + tax) / net
            else:
                maintenance = Decimal(0)
            costs_i += base * factor
            maintenance_i += maintenance * factor
        grants_i = benefit_i = Decimal(0)
        for fund in funds:
            if fund.get('unit') not in (None, key_):
                continue
            factor = Decimal(1) if fund.get('unit') == key_ else share
            if fund['kind'] == 'loan_interest':
                benefit_i += Decimal(fund.get('annual_benefit') or 0) * factor
            else:
                grants_i += Decimal(fund.get('amount') or 0) * factor
        allocable = max(Decimal(0),
            (costs_i - maintenance_i) * cost_factor - grants_i)
        annual = max(Decimal(0), allocable * rate - benefit_i)
        monthly = _cent(annual / 12)
        # cap (§ 559 para. 3a, § 559e) on the area of the cap measurement
        # of the rule - without an area no cap
        area = unit.get('area')
        if area is None:
            cap = None
            capped = monthly
        else:
            area = Decimal(area)
            rent = unit.get('rent')
            per_sqm = (Decimal(rent) / area) if rent and area else None
            cap_rate = Decimal(rule['cap_low']
                if per_sqm is not None
                and per_sqm < Decimal(rule['cap_threshold'])
                else rule['cap_high'])
            cap = max(Decimal(0), _cent(area * cap_rate)
                - Decimal(unit.get('previous') or 0))
            if variant == 'heating_559e':
                cap = min(cap, max(Decimal(0), _cent(area * Decimal(
                                rule['cap_heating']))
                        - Decimal(unit.get('previous_heating') or 0)))
            capped = min(monthly, cap)
        result[key_] = {
            'share': share,
            'costs': _cent(costs_i),
            'maintenance': _cent(maintenance_i),
            'grants': _cent(grants_i),
            'allocable': _cent(allocable),
            'annual': _cent(annual),
            'monthly': monthly,
            'cap': cap,
            'increase': capped,
            'limited': capped < monthly,
            }
    return result


#**********************************************************************
class ModernisationRule(ModelSQL, ModelView):
    "Modernisation Rule"
    __name__ = 'real_estate.modernisation.rule'

    valid_from = fields.Date("Valid from", required=True,
        help="The rule applies to measures announced on or after this "
             "date.")
    rate_standard = fields.Numeric("Rate (%)", digits=(16, 2),
        required=True, help="§ 559 para. 1 BGB.")
    rate_heating = fields.Numeric("Rate Heating (%)", digits=(16, 2),
        required=True, help="§ 559e para. 1 BGB.")
    simplified_limit = Monetary("Limit Simplified Procedure",
        currency='currency', digits='currency', required=True,
        help="Costs per apartment (§ 559c para. 1 BGB).")
    simplified_maintenance_percent = fields.Numeric(
        "Maintenance Flat Rate Simplified (%)", digits=(16, 2),
        required=True)
    heating_maintenance_percent = fields.Numeric(
        "Maintenance Flat Rate Heating (%)", digits=(16, 2), required=True)
    cap_years = fields.Integer("Cap Period (Years)", required=True)
    cap_high = fields.Numeric("Cap per m²", digits=(16, 2), required=True,
        help="§ 559 para. 3a BGB.")
    cap_low = fields.Numeric("Cap per m² (low rent)", digits=(16, 2),
        required=True)
    cap_threshold = fields.Numeric("Low Rent below per m²", digits=(16, 2),
        required=True)
    cap_m_type = fields.Many2One('real_estate.measurement.type',
        "Cap Measurement", ondelete='RESTRICT',
        help="Measurement giving the area of a rental unit for the cap per "
             "m² (§ 559 para. 3a BGB, normally the living space) and the "
             "increase per m² in the announcement - without it there is "
             "no cap.")
    cap_heating = fields.Numeric("Cap Heating per m²", digits=(16, 2),
        required=True, help="§ 559e BGB.")
    announcement_months = fields.Integer("Announcement Months",
        required=True, help="§ 555c para. 1 BGB.")
    extension_months = fields.Integer("Extension Months", required=True,
        help="§ 559b para. 2 BGB.")
    extension_tolerance_percent = fields.Numeric(
        "Extension Tolerance (%)", digits=(16, 2), required=True)
    simplified_lock_years = fields.Integer("Lock Simplified (Years)",
        required=True, help="§ 559c BGB.")
    currency = fields.Function(fields.Many2One('currency.currency',
            "Currency"), 'get_currency')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._order = [('valid_from', 'DESC'), ('id', 'DESC')]

    def get_currency(self, name):
        company = Transaction().context.get('company')
        if company:
            return Pool().get('company.company')(company).currency.id
        return None

    @classmethod
    def get(cls, date):
        "Rule valid on the date (latest valid_from <= date, else oldest)"
        date = date or Pool().get('ir.date').today()
        rules = cls.search([('valid_from', '<=', date)],
            order=[('valid_from', 'DESC')], limit=1)
        if not rules:
            rules = cls.search([], order=[('valid_from', 'ASC')], limit=1)
        return rules[0] if rules else None

    def as_dict(self):
        return {name: getattr(self, name) for name in [
                'rate_standard', 'rate_heating', 'simplified_limit',
                'simplified_maintenance_percent',
                'heating_maintenance_percent', 'cap_years', 'cap_high',
                'cap_low', 'cap_threshold', 'cap_heating',
                'announcement_months', 'extension_months',
                'extension_tolerance_percent', 'simplified_lock_years']}


#**********************************************************************
class ModernisationWarning(TrytonUserWarning):
    pass


class Modernisation(Workflow, ModelSQL, ModelView):
    "Modernisation"
    __name__ = 'real_estate.modernisation'
    _rec_name = 'number'

    _editable = {'readonly': ~Eval('state').in_(EDITABLE)}

    number = fields.Char("Number", readonly=True)
    name = fields.Char("Name", required=True)
    company = fields.Many2One('company.company', "Company", required=True,
        states=_editable)
    property = fields.Many2One('real_estate.base_object', "Property",
        required=True, states=_editable,
        domain=[
            ('type', '=', 'property'),
            ('company', '=', Eval('company', -1)),
            ])
    buildings = fields.Many2Many('real_estate.modernisation-building',
        'modernisation', 'building', "Buildings", states=_editable,
        domain=[
            ('type', '=', 'building'),
            ('parent', 'child_of', [Eval('property', -1)]),
            ],
        help="Buildings concerned - empty = all buildings of the "
             "property.")
    measure_types = fields.MultiSelection(MEASURE_TYPES, "Measure Types",
        sort=False, states=_editable,
        help="Measures according to § 555b BGB - Nos. 2 and 7 do not allow "
             "a rent increase.")
    variant = fields.Selection(VARIANTS, "Variant", required=True,
        sort=False, states=_editable)
    description = fields.Text("Description", states=_editable,
        help="Kind and scope of the measure in essential features (for "
             "announcement and increase declaration).")
    energy_saving_note = fields.Text("Energy Saving", states=_editable,
        help="Justification of the saving, flat values allowed (§ 555c "
             "para. 3 BGB).")
    planned_start = fields.Date("Planned Start", states=_editable)
    planned_duration = fields.Char("Planned Duration", states=_editable)
    actual_start = fields.Date("Actual Start",
        states={'readonly': ~Eval('state').in_(['draft', 'announced',
                    'in_progress'])})
    actual_end = fields.Date("Completed on",
        states={'readonly': ~Eval('state').in_(['in_progress'])})
    expected_costs = Monetary("Expected Costs", currency='currency',
        digits='currency', states=_editable,
        help="Expected total costs (net) - basis of the announcement.")
    expected_operating_costs = fields.Text("Expected Operating Costs",
        states=_editable,
        help="Expected future operating costs (§ 555c para. 1 BGB).")
    trivial = fields.Boolean("Trivial Measure", states=_editable,
        help="Only an insignificant impact and rent increase - no "
             "announcement needed (§ 555c para. 4 BGB).")
    trivial_reason = fields.Text("Reason (Trivial)",
        states={
            'invisible': ~Eval('trivial'),
            'required': Bool(Eval('trivial')),
            'readonly': ~Eval('state').in_(EDITABLE),
            })
    vacancy = fields.Boolean("Vacancy", states=_editable,
        help="Measure for vacant apartments without a tenant: no "
             "announcement, no deadlines, no adjustment run - the amount "
             "per apartment is the basis for the next letting.")
    comprehensive = fields.Boolean("Comprehensive Modernisation",
        states=_editable,
        help="The first letting afterwards is exempt from the rent brake "
             "(§ 556f sentence 2 BGB).")
    comprehensive_note = fields.Text("Reason (Comprehensive)",
        states={
            'invisible': ~Eval('comprehensive'),
            'required': Bool(Eval('comprehensive')),
            'readonly': ~Eval('state').in_(EDITABLE),
            })
    not_responsible = fields.Boolean("Not Attributable to Landlord",
        states=_editable,
        help="Measure due to circumstances not attributable to the "
             "landlord (§ 555b no. 6 BGB) - relevant for index rents.")
    allocation_key = fields.Selection([
            ('equal', "Equal Shares"),
            ('measurement', "Measurement"),
            ('manual', "Manual"),
            ], "Allocation Key", required=True, sort=False,
        states=_editable,
        help="Measurement or manual: a quantity per rental unit (e.g. "
             "living space or number of windows), the share is quantity / "
             "total - explain a manual allocation in the note.")
    allocation_m_type = fields.Many2One('real_estate.measurement.type',
        "Allocation Measurement", ondelete='RESTRICT',
        states={
            'invisible': Eval('allocation_key') != 'measurement',
            'required': Eval('allocation_key') == 'measurement',
            'readonly': ~Eval('state').in_(EDITABLE),
            },
        help="The quantities of the rental units are taken from this "
             "measurement by 'Determine Rental Units' (changeable "
             "afterwards).")
    allocation_note = fields.Text("Allocation Note",
        states={
            'required': Eval('allocation_key') == 'manual',
            'readonly': ~Eval('state').in_(EDITABLE),
            },
        help="Explanation of the allocation - required for manual "
             "quantities.")
    heat_pump_jaz_proven = fields.Boolean("Heat Pump SPF Proven",
        states={
            'invisible': Eval('variant') != 'heating_559e',
            'readonly': ~Eval('state').in_(EDITABLE + ['in_progress']),
            },
        help="Heat pump in a building before 1996: seasonal performance "
             "factor > 2.5 proven (§ 71o GEG).")
    announcement_date = fields.Date("Announcement Date",
        states={'readonly': ~Eval('state').in_(['draft'])})
    cost_lines = fields.One2Many('real_estate.modernisation.cost',
        'modernisation', "Costs",
        states={'readonly': Eval('state').in_(['completed', 'settled',
                    'cancelled'])})
    funds = fields.One2Many('real_estate.modernisation.fund',
        'modernisation', "Third-Party Funds",
        states={'readonly': Eval('state').in_(['completed', 'settled',
                    'cancelled'])})
    units = fields.One2Many('real_estate.modernisation.unit',
        'modernisation', "Rental Units",
        states={'readonly': Eval('state').in_(['settled', 'cancelled'])})
    planned_values = fields.One2Many('real_estate.modernisation.planned_value',
        'modernisation', "Planned Features",
        states={'readonly': ~Eval('state').in_(EDITABLE)},
        help="Classes, features and measurements of the rent survey after "
             "the modernisation - used by 'Calculate' and stored at the "
             "objects by 'Apply Planned Features' after the completion.")
    calculations = fields.One2Many('real_estate.modernisation.calculation',
        'modernisation', "Calculation", readonly=True)
    planning_objects = fields.Function(fields.Many2Many(
            'real_estate.base_object', None, None, "Planning Objects",
            help="Buildings of the measure (all of the property if none "
                 "chosen) and their rental units - selectable for the "
                 "planned features."),
        'on_change_with_planning_objects')
    rent_survey_version = fields.Function(fields.Many2One(
            'real_estate.rent_survey.version', "Rent Survey Version",
            help="Version of the rent survey of the property valid today."),
        'on_change_with_rent_survey_version')
    planned_values_applied = fields.Date("Planned Features Applied",
        readonly=True)
    currency = fields.Function(fields.Many2One('currency.currency',
            "Currency"), 'on_change_with_currency')
    total_costs = fields.Function(Monetary("Total Costs (net)",
            currency='currency', digits='currency'), 'get_totals')
    total_tax = fields.Function(Monetary("Tax", currency='currency',
            digits='currency'), 'get_totals')
    grant_total = fields.Function(Monetary("Grants", currency='currency',
            digits='currency'), 'get_totals')
    allocable_costs = fields.Function(Monetary("Allocable Costs",
            currency='currency', digits='currency',
            help="Sum of the allocable costs of the rental units (each on "
                 "its own basis net/gross)."), 'get_totals')
    check_message = fields.Function(fields.Text("Check Messages",
            help="Input tax check M08 against the option rate of the "
                 "property - computed from the completion on with the "
                 "current costs."),
        'get_check_message')
    record_link = fields.Function(fields.Many2One(
            'real_estate.modernisation', "Modernisation",
            help="Opens the measure in its own tab."),
        'get_record_link')
    adjustment_run = fields.Function(fields.Many2One(
            'real_estate.contract.term.adjustment.run', "Adjustment Run",
            help="Latest adjustment run (not cancelled) of the measure."),
        'get_adjustment_run')
    process = fields.Function(fields.Many2One('real_estate.process',
            "Process"), 'get_process')
    process_tasks = fields.Function(fields.One2Many('real_estate.task',
            None, "Workflow", readonly=True),
        'get_process_tasks', setter='set_process_tasks')
    state = fields.Selection(STATES, "State", readonly=True, required=True,
        sort=False)

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._order = [('create_date', 'DESC'), ('id', 'DESC')]
        cls._transitions |= {
            ('planning', 'draft'),
            ('draft', 'announced'),
            ('draft', 'in_progress'),
            ('announced', 'in_progress'),
            ('in_progress', 'completed'),
            ('completed', 'settled'),
            ('planning', 'cancelled'),
            ('draft', 'cancelled'),
            ('announced', 'cancelled'),
            ('in_progress', 'cancelled'),
            ('completed', 'cancelled'),
            }
        cls._buttons.update({
            'compute_units': {
                'invisible': ~Eval('state').in_(EDITABLE),
                'depends': ['state'],
                },
            'calculate': {
                'invisible': ~Eval('state').in_(EDITABLE),
                'depends': ['state'],
                },
            'apply_planned_values': {
                'invisible': (~Eval('state').in_(['completed', 'settled'])
                    | Bool(Eval('planned_values_applied'))),
                'depends': ['state', 'planned_values_applied'],
                },
            'set_receipts': {
                'invisible': ~Eval('state').in_(['announced', 'in_progress']),
                'depends': ['state'],
                },
            'create_run': {
                'invisible': ((Eval('state') != 'completed')
                    | Eval('vacancy') | Bool(Eval('adjustment_run'))),
                'depends': ['state', 'vacancy', 'adjustment_run'],
                },
            'sample_letter': {
                'invisible': (~Eval('state').in_(EDITABLE)
                    | Eval('vacancy') | Eval('trivial')),
                'depends': ['state', 'vacancy', 'trivial'],
                },
            'take_over': {
                'invisible': Eval('state') != 'planning',
                'depends': ['state'],
                },
            'announce': {
                'invisible': ((Eval('state') != 'draft') | Eval('vacancy')
                    | Eval('trivial')),
                'depends': ['state', 'vacancy', 'trivial'],
                },
            'start': {
                'invisible': ~(((Eval('state') == 'draft')
                        & (Eval('vacancy') | Eval('trivial')))
                    | (Eval('state') == 'announced')),
                'depends': ['state', 'vacancy', 'trivial'],
                },
            'complete': {
                'invisible': Eval('state') != 'in_progress',
                'depends': ['state'],
                },
            'cancel': {
                'invisible': Eval('state').in_(['settled', 'cancelled']),
                'depends': ['state'],
                },
            })

    @staticmethod
    def default_state():
        return 'planning'

    @staticmethod
    def default_company():
        return Transaction().context.get('company')

    @staticmethod
    def default_variant():
        return 'standard_559'

    @staticmethod
    def default_allocation_key():
        return 'measurement'

    @staticmethod
    def default_allocation_m_type():
        "Proposal: the cap measurement of the current rule"
        rule = Pool().get('real_estate.modernisation.rule').get(None)
        return rule.cap_m_type.id if rule and rule.cap_m_type else None

    @fields.depends('company')
    def on_change_with_currency(self, name=None):
        return self.company.currency if self.company else None

    @fields.depends('property', 'buildings')
    def on_change_with_planning_objects(self, name=None):
        BaseObject = Pool().get('real_estate.base_object')
        if not self.property or self.property.id is None \
                or self.property.id < 0:
            return []
        buildings = [b for b in (self.buildings or [])
            if b.id is not None and b.id >= 0]
        if not buildings:
            buildings = BaseObject.search([
                    ('parent', 'child_of', [self.property.id]),
                    ('type', '=', 'building'),
                    ])
        if not buildings:
            return []
        objects = BaseObject.search([
                ('parent', 'child_of', [b.id for b in buildings]),
                ('type', 'in', ['building', 'object']),
                ], order=[('type', 'ASC'), ('name', 'ASC')])
        return [o.id for o in objects]

    @fields.depends('property')
    def on_change_with_rent_survey_version(self, name=None):
        if self.property and self.property.rent_survey:
            return self.property.rent_survey.version_on(
                Pool().get('ir.date').today())
        return None

    @classmethod
    def view_attributes(cls):
        return super().view_attributes() + [
            ('//page[@id="page_workflow"]', 'states', {
                    'invisible': ~Eval('process'),
                    }, ['process']),
            ]

    def get_record_link(self, name):
        return self.id

    def get_check_message(self, name):
        "M08 from the completion on, else an information"
        if self.state not in ('completed', 'settled'):
            return gettext('real_estate.msg_modernisation_check_pending')
        return (self._input_tax_check()
            or gettext('real_estate.msg_modernisation_check_none'))

    @classmethod
    def get_adjustment_run(cls, records, name):
        Relation = Pool().get(
            'real_estate.contract.term.adjustment.run-modernisation')
        result = {r.id: None for r in records}
        for relation in Relation.search([
                    ('modernisation', 'in', [r.id for r in records]),
                    ('run.state', '!=', 'cancelled'),
                    ], order=[('run.id', 'ASC')]):
            result[relation.modernisation.id] = relation.run.id
        return result

    @classmethod
    def get_process(cls, records, name):
        Process = Pool().get('real_estate.process')
        result = {r.id: None for r in records}
        for process in Process.search([
                    ('resource', 'in', [str(r) for r in records]),
                    ], order=[('start_date', 'ASC'), ('id', 'ASC')]):
            result[process.resource.id] = process.id
        return result

    def get_process_tasks(self, name):
        return [t.id for t in self.process.tasks] if self.process else []

    @classmethod
    def set_process_tasks(cls, records, name, value):
        pass

    @classmethod
    def create(cls, vlist):
        pool = Pool()
        ModelData = pool.get('ir.model.data')
        Sequence = pool.get('ir.sequence')
        vlist = [v.copy() for v in vlist]
        with without_check_access():
            sequence = Sequence(ModelData.get_id('real_estate',
                    'sequence_modernisation'))
            for values in vlist:
                if not values.get('number'):
                    values['number'] = sequence.get()
        records = super().create(vlist)
        cls._start_processes(records)
        return records

    @classmethod
    def _start_processes(cls, records):
        "Process 'modernisation' of the measure (spec 9)"
        pool = Pool()
        Template = pool.get('real_estate.process.template')
        Process = pool.get('real_estate.process')
        Date = pool.get('ir.date')
        templates = Template.search([
                ('code', '=', 'modernisation'),
                ('model', '=', cls.__name__),
                ], limit=1)
        if not templates:
            return
        for record in records:
            Process.start(templates[0], record, Date.today())

    @classmethod
    def check_processes(cls, records):
        "Evaluate the steps of the running processes of the measures"
        Process = Pool().get('real_estate.process')
        processes = [r.process for r in cls.browse([r.id for r in records])
            if r.process and r.process.state == 'running']
        if processes:
            Process.check(processes)

    @classmethod
    def _state_tasks(cls, records):
        """Deadline tasks following the state (spec 9): earliest start
        closed by the start, increase declaration due one month after the
        completion (not for a vacancy), closed by the settlement; a
        cancelled measure cancels its tasks and process"""
        pool = Pool()
        Task = pool.get('real_estate.task')
        Process = pool.get('real_estate.process')
        for record in records:
            if record.state in ('in_progress', 'completed', 'settled'):
                Task.close_for(record, 'modernisation_start')
            if (record.state == 'completed' and not record.vacancy
                    and record.actual_end):
                Task.create_for(record, 'modernisation_declaration',
                    record.actual_end + relativedelta(months=1))
            if record.state == 'settled':
                Task.close_for(record, 'modernisation_declaration')
            if record.state == 'cancelled':
                for code in ['modernisation_start', 'modernisation_objection',
                        'modernisation_declaration']:
                    Task.cancel_for(record, code)
                if record.process and record.process.state == 'running':
                    Process.cancel([record.process])

    @classmethod
    def write(cls, *args):
        # a changed allocation key or measurement takes over the quantities
        # of the rental units from the measurement at once
        actions = iter(args)
        refresh = []
        args = list(args)
        for records, values in zip(actions, actions):
            if {'allocation_key', 'allocation_m_type'} & set(values):
                refresh.extend(records)
        actions = iter(args)
        changed = []
        for records, values in zip(actions, actions):
            if 'state' in values:
                changed.extend(records)
        super().write(*args)
        if refresh:
            cls._refresh_quantities(cls.browse([r.id for r in refresh]))
        if changed:
            changed = cls.browse([r.id for r in changed])
            cls._state_tasks(changed)
            cls.check_processes(changed)

    @classmethod
    def _refresh_quantities(cls, records):
        "Allocation quantities of the units from the allocation measurement"
        Unit = Pool().get('real_estate.modernisation.unit')
        to_write = []
        for record in records:
            if (record.allocation_key != 'measurement'
                    or not record.allocation_m_type):
                continue
            date = record._reference_date()
            for unit in record.units:
                quantity = cls._quantity(unit.object,
                    record.allocation_m_type, date)
                if quantity != unit.allocation_quantity:
                    to_write.extend([[unit],
                            {'allocation_quantity': quantity}])
        if to_write:
            Unit.write(*to_write)

    @classmethod
    def copy(cls, records, default=None):
        default = default.copy() if default else {}
        default.setdefault('number', None)
        default.setdefault('state', 'planning')
        default.setdefault('announcement_date', None)
        default.setdefault('actual_start', None)
        default.setdefault('actual_end', None)
        default.setdefault('calculations', None)
        default.setdefault('planned_values_applied', None)
        return super().copy(records, default=default)

    @classmethod
    def delete(cls, records):
        for record in records:
            if record.state not in ('planning', 'draft', 'cancelled'):
                raise ValidationError(gettext(
                        'real_estate.msg_modernisation_delete',
                        modernisation=record.rec_name))
        super().delete(records)

    def get_rec_name(self, name):
        return ' '.join(filter(None, [self.number, self.name]))

    @classmethod
    def search_rec_name(cls, name, clause):
        return ['OR',
            ('number',) + tuple(clause[1:]),
            ('name',) + tuple(clause[1:]),
            ]

    # ------------------------------------------------------------------
    # Calculation

    @builtins.property
    def rule(self):
        Rule = Pool().get('real_estate.modernisation.rule')
        return Rule.get(self.announcement_date or self.planned_start)

    def allocation_cost_lines(self):
        """Cost lines of the allocation: the actual costs once there is an
        actual line, else the planned ones (no double counting)"""
        actual = [c for c in self.cost_lines if c.state == 'actual']
        return actual or list(self.cost_lines)

    def allocation(self, overrides=None):
        """compute_allocation() for the units of the measure. 'overrides'
        gives per unit id values of the adjustment run (rent before the
        increase, previous increases within the cap period)."""
        rule = self.rule
        if not rule:
            return {}
        overrides = overrides or {}
        costs = [{
                'net': c.amount or 0,
                'tax': c.tax_amount or 0,
                'maintenance_mode': c.maintenance_mode,
                'maintenance_value': c.maintenance_value,
                'unit': c.unit.id if c.unit else None,
                } for c in self.allocation_cost_lines()]
        funds = [{
                'kind': f.kind,
                'amount': f.amount or 0,
                'annual_benefit': f.annual_benefit or 0,
                'unit': f.unit.id if f.unit else None,
                } for f in self.funds]
        areas = self.cap_areas()
        units = []
        for u in self.units:
            values = {
                'key': u.id,
                'area': areas.get(u.id),
                'in_allocation': u.in_allocation,
                'quantity': u.allocation_quantity,
                'vat_deductible': u.vat_deductible,
                'rent': u.rent,
                'previous': 0,
                'previous_heating': 0,
                }
            values.update(overrides.get(u.id, {}))
            units.append(values)
        return compute_allocation(costs, funds, units, self.variant,
            self.allocation_key, rule.as_dict())

    @classmethod
    def new_letting_amount(cls, apartment, date):
        """Modernisation amount for a new letting (§ 556e para. 2 BGB,
        D-M5): increase per month of the apartment from measures completed
        within the 3 years before 'date'. Returns (amount, measures)."""
        Unit = Pool().get('real_estate.modernisation.unit')
        amount = Decimal(0)
        measures = []
        if not apartment or not date:
            return amount, measures
        for unit in Unit.search([
                    ('object', '=', apartment.id),
                    ('modernisation.state', 'in', ['completed', 'settled']),
                    ('modernisation.actual_end', '<=', date),
                    ('modernisation.actual_end', '>',
                        date - relativedelta(years=3)),
                    ]):
            measure = unit.modernisation
            values = measure.allocation().get(unit.id)
            if values and values['increase']:
                amount += values['increase']
                measures.append(measure)
        return amount, measures

    @classmethod
    def comprehensive_first_letting(cls, apartment, date, contract=None):
        """Comprehensive modernisation of the apartment completed before
        'date' with no letting since then except 'contract' - the first
        letting afterwards is exempt from the rent brake (§ 556f sentence 2
        BGB, D-M10). Returns the measure or None."""
        pool = Pool()
        Unit = pool.get('real_estate.modernisation.unit')
        ItemObject = pool.get('real_estate.contract.item.object')
        if not apartment or not date:
            return None
        units = Unit.search([
                ('object', '=', apartment.id),
                ('modernisation.comprehensive', '=', True),
                ('modernisation.state', 'in', ['completed', 'settled']),
                ('modernisation.actual_end', '<=', date),
                ], order=[('modernisation.actual_end', 'DESC')], limit=1)
        if not units:
            return None
        measure = units[0].modernisation
        domain = [
            ('object', '=', apartment.id),
            ('item.contract.start_date', '>', measure.actual_end),
            ('item.contract.start_date', '<', date),
            ('item.contract.state', 'not in', ['draft', 'cancelled']),
            ]
        if contract:
            domain.append(('item.contract', '!=', contract.id))
        if ItemObject.search(domain, limit=1):
            return None
        return measure

    def cap_areas(self):
        """Area per unit for the cap per m² (§ 559 para. 3a BGB) from the
        cap measurement of the rule, None without a value"""
        rule = self.rule
        if not rule or not rule.cap_m_type:
            return {}
        date = self._reference_date()
        return {u.id: self._quantity(u.object, rule.cap_m_type, date)
            for u in self.units}

    @classmethod
    def get_totals(cls, records, names):
        result = {n: {r.id: None for r in records} for n in names}
        for record in records:
            lines = record.allocation_cost_lines()
            net = sum((c.amount or 0) for c in lines)
            tax = sum((c.tax_amount or 0) for c in lines)
            grants = sum((f.amount or 0) for f in record.funds
                if f.kind != 'loan_interest')
            allocable = sum(v['allocable']
                for v in record.allocation().values())
            values = {
                'total_costs': _cent(net),
                'total_tax': _cent(tax),
                'grant_total': _cent(grants),
                'allocable_costs': _cent(allocable),
                }
            for name in names:
                result[name][record.id] = values[name]
        return result

    # ------------------------------------------------------------------
    # Rental units

    def _reference_date(self):
        Date = Pool().get('ir.date')
        return (self.announcement_date or self.planned_start
            or Date.today())

    def _buildings(self):
        BaseObject = Pool().get('real_estate.base_object')
        if self.buildings:
            return list(self.buildings)
        return BaseObject.search([
                ('parent', 'child_of', [self.property.id]),
                ('type', '=', 'building'),
                ])

    @staticmethod
    def _contract_term(obj, date):
        """Running contract of the unit on the date and its rent term
        allowing the procedure 'modernisation'"""
        Occupancy = Pool().get('real_estate.base_object.occupancy')
        for occupancy in Occupancy.search([
                    ('base_object', '=', obj.id),
                    ('start_date', '<=', date),
                    ['OR', ('end_date', '=', None),
                        ('end_date', '>=', date)],
                    ('contract', '!=', None),
                    ], limit=1):
            contract = occupancy.contract
            for term in contract.terms:
                if ('modernisation' in (
                            term.term_type.adjustment_procedures or [])
                        and term.valid_from <= date
                        and (not term.valid_to or term.valid_to >= date)
                        and term.reference_item
                        and obj in term.reference_item.objects):
                    return contract, term
            return contract, None
        return None, None

    @staticmethod
    def _quantity(obj, m_type, date):
        "Quantity of the allocation measurement on the date"
        Measurement = Pool().get('real_estate.measurement')
        value = Measurement.get_total_value(obj.id, m_type, date)
        return Decimal(str(value)) if value is not None else None

    @staticmethod
    def _vat_option(contract, date):
        "Proposal: a current term of the contract carries VAT (§ 9 UStG)"
        if not contract:
            return False
        return any(t.taxes for t in contract.terms
            if t.valid_from <= date and (not t.valid_to or t.valid_to >= date))

    @classmethod
    @ModelView.button_action('real_estate.wizard_modernisation_receipt')
    def set_receipts(cls, records):
        "Receipt date of the announcement for all rental units at once"
        pass

    @classmethod
    @ModelView.button
    def create_run(cls, records):
        """Adjustment run 'modernisation' for the completed measures (one
        run per company): parameters filled in, key and declaration date
        today, at the earliest the completion - opened in the form of the
        run for the selection"""
        pool = Pool()
        Run = pool.get('real_estate.contract.term.adjustment.run')
        Action = pool.get('ir.action')
        ModelData = pool.get('ir.model.data')
        Date = pool.get('ir.date')
        today = Date.today()
        measures = [r for r in records if r.state == 'completed'
            and not r.vacancy and not r.adjustment_run]
        if not measures:
            return
        by_company = {}
        for measure in measures:
            by_company.setdefault(measure.company, []).append(measure)
        values = []
        for company, group in by_company.items():
            date = max([today] + [m.actual_end for m in group
                    if m.actual_end])
            values.append({
                    'procedure': 'modernisation',
                    'company': company.id,
                    'name': ', '.join(m.rec_name for m in group),
                    'key_date': date,
                    'declaration_date': date,
                    'modernisations': [('add', [m.id for m in group])],
                    'properties': [('add', list({m.property.id
                                    for m in group}))],
                    })
        runs = Run.create(values)
        action = Action(ModelData.get_id('real_estate',
                'act_contract_term_adjustment_run')).get_action_value()
        action['pyson_domain'] = PYSONEncoder().encode(
            [('id', 'in', [r.id for r in runs])])
        action['domains'] = []
        action['res_id'] = [r.id for r in runs]
        action['views'] = list(reversed(action['views']))
        return action

    # ------------------------------------------------------------------
    # Calculation (spec 4.7, 6.8)

    def _planned(self):
        "Planned values for the what-if calculation of the rent survey"
        values, measurements = {}, {}
        for planned in self.planned_values:
            if not planned.object:
                continue
            if planned.kind == 'measurement':
                if planned.measurement_type and planned.value is not None:
                    measurements[(planned.object.id,
                            planned.measurement_type.id)] = planned.value
                continue
            values.setdefault(planned.object.id, []).append({
                    'kind': planned.kind,
                    'action': planned.action or 'add',
                    'dimension_code': planned.dimension_code,
                    'class_code': planned.class_code,
                    'feature_code': planned.feature_code,
                    'evidence': gettext(
                        'real_estate.msg_modernisation_planned_evidence',
                        modernisation=self.rec_name),
                    })
        return {'values': values, 'measurements': measurements}

    def _previous(self, unit, date):
        """Previous increases of the apartment within the cap period before
        'date' (executed modernisation adjustments of all contracts)"""
        pool = Pool()
        Adjustment = pool.get('real_estate.contract.term.adjustment')
        from .contract_modernisation import previous_increases
        rule = self.rule
        history = [(a.planned_valid_from,
                (a.planned_amount or 0) - (a.amount_old or 0),
                a.modernisation.variant == 'heating_559e')
            for a in Adjustment.search([
                    ('modernisation_unit.object', '=', unit.object.id),
                    ('state', '=', 'done'),
                    ])]
        return previous_increases(history, date,
            rule.cap_years if rule else 6)

    @staticmethod
    def _comparative(company, obj, date, planned=None):
        """Comparative rent per m² and living space on 'date' without
        storing a calculation - with the planned values if given. Returns
        (rent per m², area, message)."""
        pool = Pool()
        Calculation = pool.get('real_estate.rent_survey.calculation')
        from .rent_survey import planned_values
        calculation = Calculation(company=company, base_object=obj,
            key_date=date, accepted_rent_per_sqm=None)
        if planned:
            with planned_values(planned):
                values = calculation._calculate()
        else:
            values = calculation._calculate()
        if values.get('check_state') == 'error':
            return None, None, values.get('check_message')
        return values.get('rent_per_sqm'), values.get('area'), None

    @classmethod
    @ModelView.button
    def calculate(cls, records):
        """Calculation per rental unit (spec 6.8): increase after § 559,
        comparative rent before and after the modernisation (what if, with
        the planned features), scope after § 558, limit of a new letting
        and annual additional rent - the lines are created again"""
        pool = Pool()
        Line = pool.get('real_estate.modernisation.calculation')
        Date = pool.get('ir.date')
        from .rent_survey import _apartment, _survey_version
        from .contract_comparative_rent import (
            _history, _term_chain, comparative_cap, earliest_first,
            effective_date, WAITING_MONTHS, NEW_LETTING_PERCENT,
            NEW_LETTING_TIGHT_PERCENT)
        today = Date.today()
        for record in records:
            if record.state not in EDITABLE:
                continue
            Line.delete(list(record.calculations))
            if not record.units:
                cls.compute_units([record])
                record = cls(record.id)
            planned = record._planned()
            overrides = {}
            for unit in record.units:
                previous, previous_heating = record._previous(unit, today)
                overrides[unit.id] = {'previous': previous,
                    'previous_heating': previous_heating}
            allocation = record.allocation(overrides)
            prop = record.property
            tight = prop.is_tight_market(today)
            valid_from = effective_date(today)
            lines = []
            for unit in record.units:
                values = allocation.get(unit.id) or {}
                no_increase = (unit.excluded
                    and unit.exclusion_reason != 'vacancy')
                increase = (None if no_increase
                    else values.get('increase'))
                line = {
                    'modernisation': record.id,
                    'unit': unit.id,
                    'object': unit.object.id,
                    'costs': values.get('costs'),
                    'allocable': values.get('allocable'),
                    'current_rent': unit.rent,
                    'increase': increase,
                    'rent_after': ((unit.rent or 0) + increase
                        if unit.rent is not None and increase is not None
                        else None),
                    }
                messages = []
                obj = unit.object
                if _apartment(obj) and _survey_version(obj, today):
                    before, area, message = cls._comparative(
                        record.company, obj, today)
                    after, area_after, message_after = cls._comparative(
                        record.company, obj, today, planned)
                    messages.extend(m for m in [message, message_after] if m)
                    area = area_after or area
                    if area:
                        line['area'] = area
                    if before is not None and area:
                        line['comparative_before'] = _cent(before * area)
                        line['rent_per_sqm_before'] = before
                    if after is not None and area:
                        comparative = _cent(after * area)
                        line['comparative_after'] = comparative
                        line['rent_per_sqm_after'] = after
                        # § 558 after the modernisation: cap and waiting
                        # period of the rent term chain
                        if unit.term and unit.rent is not None:
                            chain = _term_chain(unit.term)
                            last_change, base, excluded = _history(chain,
                                valid_from)
                            _, new, _ = comparative_cap(comparative, base,
                                excluded, prop.cap_percent(valid_from))
                            line['new_rent_558'] = max(new, unit.rent)
                            line['earliest_558'] = max(valid_from,
                                earliest_first(last_change + relativedelta(
                                        months=WAITING_MONTHS)))
                        # new letting: rent brake (+ § 556e para. 2) or
                        # rent overcharge, no limit after a comprehensive
                        # modernisation (§ 556f)
                        if tight and record.comprehensive:
                            messages.append(gettext(
                                    'real_estate.msg_modernisation_calc_556f'))
                        elif tight:
                            factor = 1 + NEW_LETTING_TIGHT_PERCENT / 100
                            limits = [_cent(comparative * factor)]
                            if (line.get('comparative_before') is not None
                                    and values.get('increase')):
                                limits.append(_cent(
                                        line['comparative_before'] * factor
                                        + values['increase']))
                            line['letting_limit'] = max(limits)
                        else:
                            line['letting_limit'] = _cent(comparative
                                * (1 + NEW_LETTING_PERCENT / 100))
                elif not no_increase:
                    messages.append(gettext(
                            'real_estate.msg_modernisation_calc_no_survey'))
                if (unit.in_allocation
                        and record.allocation_key in ('measurement', 'manual')
                        and unit.allocation_quantity is None):
                    messages.insert(0, gettext(
                            'real_estate.msg_modernisation_calc_quantity'))
                if increase is not None:
                    line['annual_559'] = _cent(increase * 12)
                if (line.get('new_rent_558') is not None
                        and unit.rent is not None):
                    line['annual_558'] = _cent(
                        (line['new_rent_558'] - unit.rent) * 12)
                costs = values.get('costs')
                for key, target in [('annual_559', 'yield_559'),
                        ('annual_558', 'yield_558')]:
                    if line.get(key) is not None and costs:
                        line[target] = (line[key] / costs * 100).quantize(
                            CENT, rounding=ROUND_HALF_UP)
                line['message'] = '\n'.join(messages) or None
                lines.append(line)
            if lines:
                Line.create(lines)

    @classmethod
    @ModelView.button
    def apply_planned_values(cls, records):
        """Store the planned features at the objects valid from the
        completion (spec 4.6): classes and features as rent survey values
        (a removed or replaced assignment ends the day before, resp. is
        deleted - as 'Assign Rent Survey Features'), measurements as new
        measurement rows"""
        pool = Pool()
        Value = pool.get('real_estate.base_object.rent_survey_value')
        Measurement = pool.get('real_estate.measurement')
        Date = pool.get('ir.date')
        from .rent_survey import _ends, valid_on
        for record in records:
            if record.state not in ('completed', 'settled'):
                continue
            date = record.actual_end or Date.today()
            for planned in record.planned_values:
                obj = planned.object
                if planned.kind == 'measurement':
                    if not planned.measurement_type or planned.value is None:
                        continue
                    existing = Measurement.search([
                            ('base_object', '=', obj.id),
                            ('m_type', '=', planned.measurement_type.id),
                            ('valid_from', '=', date),
                            ])
                    if existing:
                        Measurement.write(existing,
                            {'value': float(planned.value)})
                    else:
                        Measurement.create([{
                                    'base_object': obj.id,
                                    'm_type': planned.measurement_type.id,
                                    'valid_from': date,
                                    'value': float(planned.value),
                                    }])
                    continue
                current = [v for v in Value.search([
                            ('base_object', '=', obj.id),
                            ('kind', '=', planned.kind),
                            ]) if valid_on(v, date)]
                if planned.kind == 'class':
                    matching = [v for v in current
                        if v.dimension_code == planned.dimension_code
                        and (planned.action == 'add'
                            or v.class_code == planned.class_code)]
                else:
                    matching = [v for v in current
                        if v.feature_code == planned.feature_code]
                if planned.kind == 'feature' and planned.action == 'add' \
                        and matching:
                    continue
                to_end = [v for v in matching if _ends(v, date)]
                to_delete = [v for v in matching if v not in to_end]
                if to_end:
                    Value.write(to_end, {
                            'valid_to': date - datetime.timedelta(days=1)})
                if to_delete:
                    Value.delete(to_delete)
                if planned.action == 'add':
                    Value.create([{
                                'base_object': obj.id,
                                'kind': planned.kind,
                                'dimension_code': planned.dimension_code,
                                'class_code': planned.class_code,
                                'feature_code': planned.feature_code,
                                'valid_from': date,
                                'evidence': gettext(
                                    'real_estate.msg_modernisation_planned_evidence',
                                    modernisation=record.rec_name),
                                }])
            cls.write([record], {'planned_values_applied': Date.today()})
        cls.check_processes(records)

    @classmethod
    @ModelView.button_action(
        'real_estate.report_modernisation_sample_letter')
    def sample_letter(cls, records):
        "Sample announcement before the announcement (marked as draft)"
        pass

    @classmethod
    @ModelView.button
    def compute_units(cls, records):
        """Rental units of the buildings (apartments, commercial units,
        vacancy) with contract, rent term and allocation quantity -
        existing lines are updated, manual settings kept"""
        pool = Pool()
        BaseObject = pool.get('real_estate.base_object')
        Unit = pool.get('real_estate.modernisation.unit')
        for record in records:
            date = record._reference_date()
            existing = {u.object.id: u for u in record.units}
            to_create = []
            for building in record._buildings():
                for obj in BaseObject.search([
                            ('parent', 'child_of', [building.id]),
                            ('type', '=', 'object'),
                            ]):
                    contract, term = cls._contract_term(obj, date)
                    commercial = obj.type_of_use == 'commercial'
                    values = {
                        'contract': contract.id if contract else None,
                        'term': term.id if term else None,
                        }
                    if (record.allocation_key == 'measurement'
                            and record.allocation_m_type):
                        values['allocation_quantity'] = cls._quantity(obj,
                            record.allocation_m_type, date)
                    unit = existing.get(obj.id)
                    if unit:
                        Unit.write([unit], values)
                        continue
                    values.update({
                            'modernisation': record.id,
                            'object': obj.id,
                            'in_allocation': True,
                            'vat_deductible': cls._vat_option(contract,
                                date),
                            'excluded': commercial or not term,
                            'exclusion_reason': (
                                'vacancy' if not contract
                                else 'commercial' if commercial
                                else 'no_term' if not term else None),
                            })
                    to_create.append(values)
            if to_create:
                Unit.create(to_create)
        cls.check_processes(records)

    # ------------------------------------------------------------------
    # Workflow

    def _check(self, codes):
        "Checks M01-M05 and M10 (spec 7)"
        Lang = Pool().get('ir.lang')
        lang = Lang.get()
        errors, warnings = [], []
        types = set(self.measure_types or [])
        if 'M01' in codes and not (types - NOT_ALLOCABLE):
            errors.append(gettext('real_estate.msg_modernisation_m01'))
        if 'M02' in codes:
            missing = [label for label, value in [
                    (gettext('real_estate.msg_modernisation_field_description'),
                        self.description),
                    (gettext('real_estate.msg_modernisation_field_start'),
                        self.planned_start),
                    (gettext('real_estate.msg_modernisation_field_duration'),
                        self.planned_duration),
                    (gettext('real_estate.msg_modernisation_field_costs'),
                        self.expected_costs),
                    (gettext(
                        'real_estate.msg_modernisation_field_operating'),
                        self.expected_operating_costs),
                    ] if not value]
            if missing:
                errors.append(gettext('real_estate.msg_modernisation_m02',
                        fields=', '.join(missing)))
        if 'M10' in codes and self.allocation_key in (
                'measurement', 'manual'):
            missing = [u.object.rec_name for u in self.units
                if u.in_allocation and u.allocation_quantity is None]
            if missing:
                errors.append(gettext('real_estate.msg_modernisation_m10',
                        units=', '.join(missing)))
        rule = self.rule
        if 'M02' in codes and rule and not rule.cap_m_type:
            errors.append(gettext(
                    'real_estate.msg_modernisation_rule_cap_m_type',
                    rule=Pool().get('ir.lang').get().strftime(
                        rule.valid_from)))
        if 'M03' in codes and self.planned_start and rule:
            earliest = (self.announcement_date or Pool().get(
                    'ir.date').today()) + relativedelta(
                months=rule.announcement_months)
            if self.planned_start < earliest:
                errors.append(gettext('real_estate.msg_modernisation_m03',
                        start=lang.strftime(self.planned_start),
                        earliest=lang.strftime(earliest)))
        if 'M04' in codes and self.variant == 'heating_559e' \
                and '1a' not in types:
            errors.append(gettext('real_estate.msg_modernisation_m04'))
        if 'M05' in codes and self.variant == 'simplified_559c' and rule:
            for unit_id, values in self.allocation().items():
                if values['costs'] > rule.simplified_limit:
                    unit = Pool().get('real_estate.modernisation.unit')(
                        unit_id)
                    warnings.append(gettext(
                            'real_estate.msg_modernisation_m05',
                            unit=unit.object.rec_name,
                            costs=lang.format_number(values['costs'], 2),
                            limit=lang.format_number(
                                rule.simplified_limit, 2)))
        return errors, warnings

    def _raise(self, errors, warnings, key):
        Warning = Pool().get('res.user.warning')
        if errors:
            raise ValidationError('\n'.join(errors))
        if warnings:
            name = Warning.format(f'modernisation_{key}', [self])
            if Warning.check(name):
                raise ModernisationWarning(name, '\n'.join(warnings))

    @classmethod
    @ModelView.button
    @Workflow.transition('draft')
    def take_over(cls, records):
        """Planning taken over: the planned costs are the expected costs"""
        for record in records:
            if record.expected_costs is None:
                cls.write([record], {'expected_costs': _cent(sum(
                                (c.amount or 0) for c in record.cost_lines))})

    @classmethod
    @ModelView.button
    @Workflow.transition('announced')
    def announce(cls, records):
        """Announcement (§ 555c BGB): checks M01-M05, expected increase per
        unit frozen, letter per unit with a tenant archived at the unit
        and the contract"""
        pool = Pool()
        Unit = pool.get('real_estate.modernisation.unit')
        Date = pool.get('ir.date')
        for record in records:
            if not record.units:
                cls.compute_units([record])
                record = cls(record.id)
            if not record.announcement_date:
                cls.write([record], {'announcement_date': Date.today()})
                record = cls(record.id)
            record._raise(*record._check(
                    ['M01', 'M02', 'M03', 'M04', 'M05', 'M10']), 'announce')
            allocation = record.allocation()
            for unit in record.units:
                Unit.write([unit], {'announced_increase': None
                        if unit.excluded
                        else allocation.get(unit.id, {}).get('increase')})
            Unit.archive_letters([u for u in Unit.browse(
                        [u.id for u in record.units])
                    if u.contract and not u.excluded])

    @classmethod
    @ModelView.button
    @Workflow.transition('in_progress')
    def start(cls, records):
        """Start of the work (M06: warning if before receipt + 3 months);
        without an announcement only for a vacancy or a trivial measure"""
        pool = Pool()
        Date = pool.get('ir.date')
        Lang = pool.get('ir.lang')
        lang = Lang.get()
        for record in records:
            if record.state == 'draft' and not (record.vacancy
                    or record.trivial):
                raise ValidationError(gettext(
                        'real_estate.msg_modernisation_announce_first',
                        modernisation=record.rec_name))
            start = record.actual_start or Date.today()
            rule = record.rule
            late = [u for u in record.units
                if not u.excluded and u.announcement_receipt_date and rule
                and start < u.announcement_receipt_date + relativedelta(
                    months=rule.announcement_months)]
            if late:
                record._raise([], [gettext(
                            'real_estate.msg_modernisation_m06',
                            start=lang.strftime(start),
                            units=', '.join(u.object.rec_name
                                for u in late))], 'start')
            cls.write([record], {'actual_start': start})

    @classmethod
    @ModelView.button
    def complete(cls, records):
        """Completion: costs complete (M07), check of the input tax (M08);
        a vacancy measure is settled at once (no adjustment run)"""
        cls._complete(records)
        vacancy = [r for r in cls.browse([r.id for r in records])
            if r.vacancy]
        if vacancy:
            cls.settle(vacancy)

    @classmethod
    @Workflow.transition('completed')
    def _complete(cls, records):
        pool = Pool()
        Date = pool.get('ir.date')
        for record in records:
            record._raise(*record._check(['M10']), 'complete')
            actual = [c for c in record.cost_lines]
            if not actual or sum((c.amount or 0) for c in actual) <= 0:
                raise ValidationError(gettext(
                        'real_estate.msg_modernisation_m07_costs',
                        modernisation=record.rec_name))
            if record.variant == 'standard_559':
                missing = [c.description for c in actual
                    if not c.maintenance_mode]
                if missing:
                    raise ValidationError(gettext(
                            'real_estate.msg_modernisation_m07_maintenance',
                            costs=', '.join(missing)))
            cls.write([record], {
                    'actual_end': record.actual_end or Date.today(),
                    })

    @classmethod
    @Workflow.transition('settled')
    def settle(cls, records):
        pass

    @classmethod
    @ModelView.button
    @Workflow.transition('cancelled')
    def cancel(cls, records):
        pass

    def _input_tax_check(self):
        """M08: input tax of the units with deduction compared with the
        option rate of the property - only a hint"""
        pool = Pool()
        OptionRate = pool.get('real_estate.option_rate')
        Lang = pool.get('ir.lang')
        lang = Lang.get()
        tax = sum((c.tax_amount or 0)
            for c in self.allocation_cost_lines())
        if not tax:
            return None
        allocation = self.allocation()
        deductible = sum(Decimal(tax) * v['share'] for unit_id, v
            in allocation.items()
            if pool.get('real_estate.modernisation.unit')(
                unit_id).vat_deductible)
        rates = OptionRate.search([
                ('base_object', '=', self.property.id),
                ('valid_from', '<=', self.actual_end or self._reference_date()),
                ], order=[('valid_from', 'DESC')], limit=1)
        if not rates:
            return None
        expected = Decimal(tax) * Decimal(rates[0].option_rate) / 100
        if abs(_cent(deductible) - _cent(expected)) > max(
                Decimal(1), _cent(expected) * Decimal('0.05')):
            return gettext('real_estate.msg_modernisation_m08',
                deductible=lang.format_number(_cent(deductible), 2),
                expected=lang.format_number(_cent(expected), 2),
                rate=lang.format_number(rates[0].option_rate, 2))
        return None


class ModernisationPlannedValue(ModelSQL, ModelView):
    "Modernisation Planned Feature"
    __name__ = 'real_estate.modernisation.planned_value'

    modernisation = fields.Many2One('real_estate.modernisation',
        "Modernisation", required=True, ondelete='CASCADE')
    property = fields.Function(fields.Many2One('real_estate.base_object',
            "Property"), 'on_change_with_property')
    rent_survey_version = fields.Function(fields.Many2One(
            'real_estate.rent_survey.version', "Rent Survey Version"),
        'on_change_with_rent_survey_version')
    object = fields.Many2One('real_estate.base_object', "Object",
        required=True, ondelete='CASCADE',
        domain=[
            ('id', 'in', Eval('_parent_modernisation', {}).get(
                    'planning_objects', [])),
            ],
        help="Building or rental unit of the measure the value is planned "
             "for (level of the rent survey).")
    object_type = fields.Function(fields.Char("Object Type"),
        'on_change_with_object_type')
    kind = fields.Selection([
            ('feature', "Feature"),
            ('class', "Class"),
            ('measurement', "Measurement"),
            ], "Kind", required=True, sort=False)
    action = fields.Selection([
            ('add', "Add"),
            ('remove', "Remove"),
            ], "Action", sort=False,
        states={
            'invisible': Eval('kind') == 'measurement',
            'required': Eval('kind') != 'measurement',
            },
        help="Add: the class or feature applies after the modernisation "
             "(a class replaces the class of its classification feature). "
             "Remove: it does not apply any more.")
    survey_class = fields.Function(fields.Many2One(
            'real_estate.rent_survey.dimension.class', "Class",
            domain=[
                ('dimension.version', '=', Eval('_parent_modernisation',
                        {}).get('rent_survey_version', -1)),
                # level of the classification feature or a higher one
                ('dimension.level', 'in', If(
                        Eval('object_type') == 'building',
                        ['property', 'building'],
                        ['property', 'building', 'object'])),
                ],
            states={
                'invisible': Eval('kind') != 'class',
                'required': Eval('kind') == 'class',
                }),
        'get_survey_class', setter='set_codes')
    survey_feature = fields.Function(fields.Many2One(
            'real_estate.rent_survey.feature', "Feature",
            domain=[
                ('group.version', '=', Eval('_parent_modernisation',
                        {}).get('rent_survey_version', -1)),
                ('level', '=', Eval('object_type')),
                ],
            states={
                'invisible': Eval('kind') != 'feature',
                'required': Eval('kind') == 'feature',
                }),
        'get_survey_feature', setter='set_codes')
    dimension_code = fields.Char("Classification Feature Code",
        readonly=True)
    class_code = fields.Char("Class Code", readonly=True)
    feature_code = fields.Char("Feature Code", readonly=True)
    measurement_type = fields.Many2One('real_estate.measurement.type',
        "Measurement Type", ondelete='RESTRICT',
        domain=[('is_group', '=', False)],
        states={
            'invisible': Eval('kind') != 'measurement',
            'required': Eval('kind') == 'measurement',
            },
        help="E.g. the energy consumption value after the modernisation.")
    value = fields.Numeric("Value", digits=(16, 2),
        states={
            'invisible': Eval('kind') != 'measurement',
            'required': Eval('kind') == 'measurement',
            })
    name = fields.Function(fields.Char("Planned Value"), 'get_name',
        searcher='search_name')

    @staticmethod
    def default_kind():
        return 'feature'

    @classmethod
    def search_name(cls, name, clause):
        return ['OR',
            ('class_code',) + tuple(clause[1:]),
            ('feature_code',) + tuple(clause[1:]),
            ('measurement_type.name',) + tuple(clause[1:]),
            ]

    @classmethod
    def validate(cls, records):
        """The feature belongs to the level of the object, the class to a
        classification feature of the level or a higher one"""
        super().validate(records)
        allowed = {
            'building': {'property', 'building'},
            'object': {'property', 'building', 'object'},
            }
        for record in records:
            level = record.object.type if record.object else None
            if record.kind == 'feature' and record.survey_feature \
                    and record.survey_feature.level != level:
                raise ValidationError(gettext(
                        'real_estate.msg_modernisation_planned_level',
                        value=record.survey_feature.rec_name,
                        object=record.object.rec_name))
            if record.kind == 'class' and record.survey_class \
                    and record.survey_class.dimension.level not in \
                    allowed.get(level, set()):
                raise ValidationError(gettext(
                        'real_estate.msg_modernisation_planned_level',
                        value=record.survey_class.rec_name,
                        object=record.object.rec_name))

    @staticmethod
    def default_action():
        return 'add'

    @fields.depends('modernisation', '_parent_modernisation.property')
    def on_change_with_property(self, name=None):
        return (self.modernisation.property
            if self.modernisation and self.modernisation.property else None)

    @fields.depends('modernisation', '_parent_modernisation.property')
    def on_change_with_rent_survey_version(self, name=None):
        prop = (self.modernisation.property
            if self.modernisation else None)
        if prop and prop.rent_survey:
            return prop.rent_survey.version_on(
                Pool().get('ir.date').today())
        return None

    @fields.depends('object')
    def on_change_with_object_type(self, name=None):
        return self.object.type if self.object else None

    def get_survey_class(self, name):
        version = self.rent_survey_version
        if not version or self.kind != 'class':
            return None
        for dimension in version.dimensions:
            if dimension.code == self.dimension_code:
                for class_ in dimension.classes:
                    if class_.code == self.class_code:
                        return class_.id
        return None

    def get_survey_feature(self, name):
        version = self.rent_survey_version
        if not version or self.kind != 'feature':
            return None
        for group in version.groups:
            for feature in group.features:
                if feature.code == self.feature_code:
                    return feature.id
        return None

    @classmethod
    def set_codes(cls, records, name, value):
        pool = Pool()
        Class = pool.get('real_estate.rent_survey.dimension.class')
        Feature = pool.get('real_estate.rent_survey.feature')
        if name == 'survey_class':
            class_ = Class(value) if value else None
            cls.write(records, {
                    'dimension_code': class_.dimension.code if class_
                    else None,
                    'class_code': class_.code if class_ else None,
                    })
        else:
            feature = Feature(value) if value else None
            cls.write(records, {
                    'feature_code': feature.code if feature else None,
                    })

    def get_name(self, name):
        if self.kind == 'measurement':
            return (f'{self.measurement_type.rec_name}: {self.value}'
                if self.measurement_type else '')
        if self.kind == 'class':
            return (self.survey_class.rec_name if self.survey_class
                else f'{self.dimension_code}: {self.class_code}')
        return (self.survey_feature.rec_name if self.survey_feature
            else self.feature_code or '')


class ModernisationCalculation(ModelSQL, ModelView):
    "Modernisation Calculation"
    __name__ = 'real_estate.modernisation.calculation'

    modernisation = fields.Many2One('real_estate.modernisation',
        "Modernisation", required=True, ondelete='CASCADE', readonly=True)
    unit = fields.Many2One('real_estate.modernisation.unit', "Rental Unit",
        ondelete='CASCADE', readonly=True)
    object = fields.Many2One('real_estate.base_object', "Object",
        readonly=True)
    currency = fields.Function(fields.Many2One('currency.currency',
            "Currency"), 'get_currency')
    area = fields.Numeric("Living Space", digits=(16, 2), readonly=True)
    costs = Monetary("Costs of the Unit", currency='currency',
        digits='currency', readonly=True)
    allocable = Monetary("Allocable Costs", currency='currency',
        digits='currency', readonly=True)
    current_rent = Monetary("Current Rent", currency='currency',
        digits='currency', readonly=True)
    increase = Monetary("Increase § 559", currency='currency',
        digits='currency', readonly=True,
        help="Monthly increase after the cap (previous increases of the "
             "last 6 years counted).")
    rent_after = Monetary("Rent after § 559", currency='currency',
        digits='currency', readonly=True)
    rent_per_sqm_before = fields.Numeric("Comparative Rent per m² before",
        digits=(16, 2), readonly=True)
    rent_per_sqm_after = fields.Numeric("Comparative Rent per m² after",
        digits=(16, 2), readonly=True)
    comparative_before = Monetary("Comparative Rent before",
        currency='currency', digits='currency', readonly=True)
    comparative_after = Monetary("Comparative Rent after",
        currency='currency', digits='currency', readonly=True,
        help="Calculation of the rent survey with the planned features "
             "(what if) - nothing is stored.")
    new_rent_558 = Monetary("Rent after § 558", currency='currency',
        digits='currency', readonly=True,
        help="Comparative rent after the modernisation, limited by the cap "
             "of § 558 BGB (rent 3 years before + 20 % / 15 %).")
    earliest_558 = fields.Date("§ 558 from", readonly=True,
        help="Earliest effective date after § 558 BGB: waiting period of "
             "15 months since the last change, at the earliest a request "
             "today.")
    letting_limit = Monetary("New Letting Limit", currency='currency',
        digits='currency', readonly=True,
        help="Tight housing market: 110 % of the comparative rent after, "
             "at least 110 % of the comparative rent before + the increase "
             "after § 559 (§ 556e para. 2 BGB); else 120 % (§ 5 WiStG). "
             "Empty after a comprehensive modernisation (§ 556f BGB).")
    annual_559 = Monetary("Additional Rent p. a. § 559",
        currency='currency', digits='currency', readonly=True)
    annual_558 = Monetary("Additional Rent p. a. § 558",
        currency='currency', digits='currency', readonly=True)
    yield_559 = fields.Numeric("Yield § 559 (%)", digits=(16, 2),
        readonly=True, help="Additional rent p. a. / costs of the unit.")
    yield_558 = fields.Numeric("Yield § 558 (%)", digits=(16, 2),
        readonly=True, help="Additional rent p. a. / costs of the unit.")
    message = fields.Text("Messages", readonly=True)

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._order = [('id', 'ASC')]

    def get_currency(self, name):
        company = self.modernisation.company if self.modernisation else None
        return company.currency.id if company else None


class ModernisationBuilding(ModelSQL):
    "Modernisation - Building"
    __name__ = 'real_estate.modernisation-building'

    modernisation = fields.Many2One('real_estate.modernisation',
        "Modernisation", required=True, ondelete='CASCADE')
    building = fields.Many2One('real_estate.base_object', "Building",
        required=True, ondelete='CASCADE')


#**********************************************************************
class ModernisationCost(sequence_ordered(), ModelSQL, ModelView):
    "Modernisation Cost"
    __name__ = 'real_estate.modernisation.cost'

    modernisation = fields.Many2One('real_estate.modernisation',
        "Modernisation", required=True, ondelete='CASCADE')
    description = fields.Char("Trade / Service", required=True,
        help="Costs per trade or service area (e.g. facade, windows, "
             "heating, lift) - not per invoice.")
    state = fields.Selection([
            ('planned', "Planned"),
            ('actual', "Actual"),
            ], "Kind", required=True, sort=False)
    invoice_line = fields.Many2One('account.invoice.line', "Invoice Line",
        ondelete='SET NULL',
        domain=[
            ('invoice.type', '=', 'in'),
            ('invoice.company', '=', Eval('company', -1)),
            ],
        help="Supplier invoice line as proof - net amount and tax are "
             "taken over.")
    company = fields.Function(fields.Many2One('company.company',
            "Company"), 'on_change_with_company')
    currency = fields.Function(fields.Many2One('currency.currency',
            "Currency"), 'on_change_with_currency')
    amount = Monetary("Net Amount", currency='currency', digits='currency',
        required=True)
    tax = fields.Many2One('account.tax', "Tax", ondelete='RESTRICT',
        domain=[('parent', '=', None)])
    tax_amount = Monetary("Tax Amount", currency='currency',
        digits='currency')
    gross_amount = fields.Function(Monetary("Gross Amount",
            currency='currency', digits='currency'), 'get_gross_amount')
    maintenance_mode = fields.Selection([
            (None, ''),
            ('none', "None"),
            ('percent', "Percent"),
            ('amount', "Amount (net)"),
            ], "Maintenance Share", sort=False,
        states={'invisible': Eval('_parent_modernisation', {}).get(
                'variant', 'standard_559') != 'standard_559'},
        help="Share of maintenance costs that cannot be allocated (§ 559 "
             "para. 2 BGB) - flat rate with the simplified and the "
             "heating variant.")
    maintenance_value = fields.Numeric("Maintenance Value", digits=(16, 2),
        states={'invisible': ~Eval('maintenance_mode').in_(
                    ['percent', 'amount'])})
    unit = fields.Many2One('real_estate.modernisation.unit', "Rental Unit",
        ondelete='SET NULL',
        domain=[('modernisation', '=', Eval('modernisation', -1))],
        help="Costs of one rental unit only (e.g. a balcony) - empty = "
             "allocation by the key.")
    measure_type = fields.Selection([(None, '')] + MEASURE_TYPES,
        "Measure Type", sort=False)

    @staticmethod
    def default_state():
        return 'planned'

    @fields.depends('modernisation', '_parent_modernisation.company')
    def on_change_with_company(self, name=None):
        return (self.modernisation.company
            if self.modernisation and self.modernisation.company else None)

    @fields.depends('modernisation', '_parent_modernisation.company')
    def on_change_with_currency(self, name=None):
        company = (self.modernisation.company
            if self.modernisation else None)
        return company.currency if company else None

    def get_gross_amount(self, name):
        return (self.amount or 0) + (self.tax_amount or 0)

    @fields.depends('invoice_line', 'amount', 'tax', 'tax_amount',
        'description', 'state')
    def on_change_invoice_line(self):
        if not self.invoice_line:
            return
        Tax = Pool().get('account.tax')
        line = self.invoice_line
        self.amount = line.amount
        taxes = list(line.taxes or [])
        self.tax_amount = _cent(sum(t['amount'] for t in Tax.compute(
                    taxes, line.unit_price or Decimal(0), line.quantity or 0,
                    line.tax_date))) if taxes else Decimal(0)
        self.state = 'actual'
        self.tax = taxes[0] if len(taxes) == 1 else None
        if not self.description:
            self.description = line.description

    @fields.depends('tax', 'amount', 'invoice_line')
    def on_change_tax(self):
        if self.invoice_line or not self.tax or self.amount is None:
            return
        pool = Pool()
        Tax = pool.get('account.tax')
        Date = pool.get('ir.date')
        self.tax_amount = _cent(sum(t['amount'] for t in Tax.compute(
                    [self.tax], self.amount, 1, Date.today())))

    @fields.depends(methods=['on_change_tax'])
    def on_change_amount(self):
        self.on_change_tax()


#**********************************************************************
class ModernisationFund(ModelSQL, ModelView):
    "Modernisation Third-Party Fund"
    __name__ = 'real_estate.modernisation.fund'

    modernisation = fields.Many2One('real_estate.modernisation',
        "Modernisation", required=True, ondelete='CASCADE')
    kind = fields.Selection([
            ('grant', "Grant"),
            ('loan_interest', "Interest Advantage of a Loan"),
            ('third_party', "Third-Party Payment"),
            ], "Kind", required=True, sort=False,
        help="Grant and third-party payment reduce the costs, the annual "
             "interest advantage reduces the annual increase (§ 559a "
             "BGB).")
    source = fields.Char("Source", help="E.g. BEG EM (BAFA), KfW 261.")
    currency = fields.Function(fields.Many2One('currency.currency',
            "Currency"), 'on_change_with_currency')
    amount = Monetary("Amount", currency='currency', digits='currency',
        states={'invisible': Eval('kind') == 'loan_interest'})
    annual_benefit = Monetary("Annual Interest Advantage",
        currency='currency', digits='currency',
        states={'invisible': Eval('kind') != 'loan_interest'})
    unit = fields.Many2One('real_estate.modernisation.unit', "Rental Unit",
        ondelete='SET NULL',
        domain=[('modernisation', '=', Eval('modernisation', -1))])

    @staticmethod
    def default_kind():
        return 'grant'

    @fields.depends('modernisation', '_parent_modernisation.company')
    def on_change_with_currency(self, name=None):
        company = (self.modernisation.company
            if self.modernisation else None)
        return company.currency if company else None


#**********************************************************************
class ModernisationUnit(ModelSQL, ModelView):
    "Modernisation Rental Unit"
    __name__ = 'real_estate.modernisation.unit'

    modernisation = fields.Many2One('real_estate.modernisation',
        "Modernisation", required=True, ondelete='CASCADE')
    object = fields.Many2One('real_estate.base_object', "Rental Unit",
        required=True, ondelete='RESTRICT',
        domain=[('type', '=', 'object')])
    contract = fields.Many2One('real_estate.contract', "Contract",
        ondelete='SET NULL')
    term = fields.Many2One('real_estate.contract.term', "Rent Term",
        ondelete='SET NULL',
        domain=[('contract', '=', Eval('contract', -1))])
    currency = fields.Function(fields.Many2One('currency.currency',
            "Currency"), 'on_change_with_currency')
    in_allocation = fields.Boolean("In Allocation",
        help="The unit takes part in the allocation of the costs - a "
             "vacancy always takes part (the landlord bears its share).")
    allocation_exclusion_reason = fields.Text("Reason (not in Allocation)",
        states={
            'invisible': Bool(Eval('in_allocation')),
            'required': ~Eval('in_allocation'),
            },
        help="Excluding a unit increases the share of the others.")
    vat_deductible = fields.Boolean("Input Tax Deductible",
        help="Letting with option to VAT (§ 9 UStG): costs on a net basis, "
             "else gross.")
    allocation_quantity = fields.Numeric("Allocation Quantity",
        digits=(16, 4),
        states={'invisible': ~Eval('_parent_modernisation', {}).get(
                'allocation_key', 'measurement').in_(
                    ['measurement', 'manual'])},
        help="Quantity of the unit for the allocation by measurement or "
             "manual (e.g. number of windows).")
    rent = fields.Function(Monetary("Current Rent", currency='currency',
            digits='currency'), 'get_rent')
    share = fields.Function(fields.Numeric("Share (%)", digits=(16, 4)),
        'get_allocation')
    allocated_costs = fields.Function(Monetary("Allocable Costs",
            currency='currency', digits='currency'), 'get_allocation')
    expected_increase = fields.Function(Monetary("Expected Increase",
            currency='currency', digits='currency',
            help="Monthly increase after the cap - preview from the "
                 "current costs."), 'get_allocation')
    limited = fields.Function(fields.Boolean("Capped"), 'get_allocation')
    announced_increase = Monetary("Announced Increase", currency='currency',
        digits='currency', readonly=True)
    announcement_receipt_date = fields.Date("Receipt of Announcement")
    announcement_defective = fields.Boolean("Announcement Defective",
        help="The announcement is missing or defective (§ 555c para. 1, "
             "3-5 BGB), e.g. incomplete text - the effective date is "
             "postponed by 6 months.")
    announcement_defect_note = fields.Text("Defect",
        states={'invisible': ~Eval('announcement_defective')})
    hardship_notice_missing = fields.Boolean("Hardship Notice Missing",
        help="The notice on form and period of the hardship objection "
             "was missing (§ 555c para. 2 BGB): the period does not "
             "start, the effective date is not postponed.")
    hardship_deadline = fields.Function(fields.Date("Hardship Objection "
            "until"), 'get_deadlines')
    special_termination_deadline = fields.Function(fields.Date(
            "Special Termination until"), 'get_deadlines')
    hardship_received = fields.Boolean("Hardship Objection")
    hardship_date = fields.Date("Hardship Objection on",
        states={'invisible': ~Eval('hardship_received')})
    hardship_note = fields.Text("Hardship Note",
        states={'invisible': ~Eval('hardship_received')})
    hardship_decision = fields.Selection([
            (None, ''),
            ('none', "Open"),
            ('accepted', "Accepted"),
            ('rejected', "Rejected"),
            ], "Decision", sort=False,
        states={'invisible': ~Eval('hardship_received')})
    terminated = fields.Boolean("Terminated (§ 555e)",
        help="The tenant terminated after the announcement - terminate "
             "the contract with the termination wizard.")
    excluded = fields.Boolean("No Increase",
        help="No rent increase for this unit (it still takes part in the "
             "allocation).")
    exclusion_reason = fields.Selection([
            (None, ''),
            ('vacancy', "Vacancy"),
            ('commercial', "Commercial (Contract only)"),
            ('no_term', "No Rent Term with the Procedure"),
            ('graduated_rent', "Graduated Rent"),
            ('index_rent', "Index Rent"),
            ('hardship', "Hardship Accepted"),
            ('terminated', "Termination"),
            ('waiver', "Waiver"),
            ('other', "Other"),
            ], "Reason", sort=False,
        states={
            'invisible': ~Eval('excluded'),
            'required': Bool(Eval('excluded')),
            })
    exclusion_note = fields.Text("Note",
        states={'invisible': ~Eval('excluded')})
    letter = fields.Many2One('ir.attachment', "Announcement (Document)",
        readonly=True, ondelete='SET NULL')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._order = [('id', 'ASC')]

    @staticmethod
    def default_in_allocation():
        return True

    @fields.depends('object', 'allocation_quantity', 'modernisation',
        '_parent_modernisation.allocation_key',
        '_parent_modernisation.allocation_m_type',
        '_parent_modernisation.announcement_date',
        '_parent_modernisation.planned_start')
    def on_change_object(self):
        "Allocation by measurement: quantity of the object proposed"
        measure = self.modernisation
        if (self.object and measure
                and measure.allocation_key == 'measurement'
                and measure.allocation_m_type):
            self.allocation_quantity = self._measurement_quantity(
                measure, self.object)

    @staticmethod
    def _measurement_quantity(measure, obj):
        pool = Pool()
        Modernisation = pool.get('real_estate.modernisation')
        Date = pool.get('ir.date')
        date = (measure.announcement_date or measure.planned_start
            or Date.today())
        return Modernisation._quantity(obj, measure.allocation_m_type, date)

    @classmethod
    def create(cls, vlist):
        """A unit entered without quantity gets the quantity of the
        allocation measurement (allocation by measurement)"""
        pool = Pool()
        Modernisation = pool.get('real_estate.modernisation')
        BaseObject = pool.get('real_estate.base_object')
        vlist = [v.copy() for v in vlist]
        for values in vlist:
            if (values.get('allocation_quantity') is None
                    and values.get('modernisation') and values.get('object')):
                measure = Modernisation(values['modernisation'])
                if (measure.allocation_key == 'measurement'
                        and measure.allocation_m_type):
                    values['allocation_quantity'] = (
                        cls._measurement_quantity(measure,
                            BaseObject(values['object'])))
        return super().create(vlist)

    @fields.depends('modernisation', '_parent_modernisation.company')
    def on_change_with_currency(self, name=None):
        company = (self.modernisation.company
            if self.modernisation else None)
        return company.currency if company else None

    def get_rec_name(self, name):
        return self.object.rec_name if self.object else str(self.id)

    @classmethod
    def write(cls, *args):
        """Receipt of the announcement: deadline tasks (objection period
        per unit, earliest start per measure); every change of the units
        evaluates the process of the measure"""
        Modernisation = Pool().get('real_estate.modernisation')
        actions = iter(args)
        receipts, measures = [], set()
        for records, values in zip(actions, actions):
            if 'announcement_receipt_date' in values or (
                    'hardship_notice_missing' in values):
                receipts.extend(records)
            measures |= {r.modernisation.id for r in records}
        super().write(*args)
        if receipts:
            cls._receipt_tasks(cls.browse([r.id for r in receipts]))
        if measures:
            Modernisation.check_processes(
                Modernisation.browse(list(measures)))

    @classmethod
    def _receipt_tasks(cls, units):
        pool = Pool()
        Task = pool.get('real_estate.task')
        for unit in units:
            measure = unit.modernisation
            key = f'unit:{unit.id}'
            deadline = unit.special_termination_deadline
            if deadline and not unit.excluded:
                task = Task.create_for(measure, 'modernisation_objection',
                    deadline, name=gettext(
                        'real_estate.msg_modernisation_task_objection',
                        unit=unit.object.rec_name,
                        modernisation=measure.rec_name),
                    origin_key=key)
                if task and task.due_date != deadline:
                    Task.write([task], {'due_date': deadline})
            # earliest start of the work: latest receipt + 3 months
            rule = measure.rule
            receipts = [u.announcement_receipt_date for u in measure.units
                if u.announcement_receipt_date and not u.excluded]
            if receipts and rule and measure.state in ('draft', 'announced'):
                due = max(receipts) + relativedelta(
                    months=rule.announcement_months)
                task = Task.create_for(measure, 'modernisation_start', due)
                if task and task.due_date != due:
                    Task.write([task], {'due_date': due})

    @classmethod
    def validate_fields(cls, units, field_names):
        super().validate_fields(units, field_names)
        if field_names & {'in_allocation', 'allocation_exclusion_reason'}:
            for unit in units:
                # M09: a vacancy always takes part, an exclusion needs a
                # reason
                if not unit.in_allocation:
                    if not unit.contract:
                        raise ValidationError(gettext(
                                'real_estate.msg_modernisation_m09_vacancy',
                                unit=unit.rec_name))
                    if not (unit.allocation_exclusion_reason or '').strip():
                        raise ValidationError(gettext(
                                'real_estate.msg_modernisation_m09',
                                unit=unit.rec_name))

    def get_rent(self, name):
        term = self.term
        if not term:
            return None
        return _cent(Decimal(str(term.quantity or 0))
            * (term.unit_price or Decimal(0)))

    @classmethod
    def get_allocation(cls, units, names):
        result = {n: {u.id: None for u in units} for n in names}
        cache = {}
        for unit in units:
            measure = unit.modernisation
            if measure.id not in cache:
                cache[measure.id] = measure.allocation()
            values = cache[measure.id].get(unit.id)
            if not values:
                continue
            mapping = {
                'share': (values['share'] * 100).quantize(
                    Decimal('0.0001')),
                'allocated_costs': values['allocable'],
                # a vacancy shows its amount (basis of the next letting)
                'expected_increase': (None if unit.excluded
                    and unit.exclusion_reason != 'vacancy'
                    else values['increase']),
                'limited': values['limited'] and not (unit.excluded
                    and unit.exclusion_reason != 'vacancy'),
                }
            for name in names:
                result[name][unit.id] = mapping[name]
        return result

    def get_deadlines(self, name):
        receipt = self.announcement_receipt_date
        if not receipt:
            return None
        if name == 'hardship_deadline' and self.hardship_notice_missing:
            return None
        # both: end of the month following the receipt (§§ 555d, 555e)
        return _end_of_next_month(receipt)

    @classmethod
    def archive_letters(cls, units):
        """Announcement letter per unit, archived at the unit and (copy
        sharing the stored file) at the contract"""
        pool = Pool()
        Attachment = pool.get('ir.attachment')
        Letter = pool.get('real_estate.modernisation.announcement_letter',
            type='report')
        for unit in units:
            ext, content, _, name = Letter.execute([unit.id], {
                    'model': cls.__name__,
                    'original': True,
                    })
            title = name.split('-')[0].strip()
            attachment, = Attachment.create([{
                        'name': (f'{title} {unit.modernisation.number} '
                            f'{unit.object.name}.{ext}'),
                        'resource': str(unit),
                        'data': content,
                        }])
            cls.write([unit], {'letter': attachment.id})
            if unit.contract:
                Attachment.copy([attachment],
                    default={'resource': str(unit.contract)})


#**********************************************************************
class ModernisationSampleLetter(Report):
    """Sample announcement of a measure before the announcement: the
    letter of the first rental unit with a contract and an increase,
    marked as draft - nothing is archived"""
    __name__ = 'real_estate.modernisation.sample_letter'

    @classmethod
    def execute(cls, ids, data):
        pool = Pool()
        Modernisation = pool.get('real_estate.modernisation')
        Letter = pool.get('real_estate.modernisation.announcement_letter',
            type='report')
        units = []
        for measure in Modernisation.browse(ids):
            candidates = [u for u in measure.units
                if u.contract and not u.excluded]
            if candidates:
                units.append(candidates[0])
        if not units:
            raise ValidationError(gettext(
                    'real_estate.msg_modernisation_no_sample',
                    modernisation=', '.join(m.rec_name
                        for m in Modernisation.browse(ids))))
        ext, content, direct_print, _ = Letter.execute(
            [u.id for u in units], {
                'model': 'real_estate.modernisation.unit',
                })
        ActionReport = pool.get('ir.action.report')
        actions = ActionReport.search([
                ('report_name', '=', cls.__name__),
                ], limit=1)
        title = actions[0].name if actions else cls.__name__
        name = '-'.join([title] + [m.number
                for m in Modernisation.browse(ids)])
        return ext, content, direct_print, name


#**********************************************************************
class ModernisationReceiptStart(ModelView):
    "Modernisation - Capture Receipts"
    __name__ = 'real_estate.modernisation.receipt.start'

    receipt_date = fields.Date("Receipt Date", required=True,
        help="Receipt of the announcement by the tenants (e.g. the day the "
             "caretaker put the letters into the letter boxes).")
    overwrite = fields.Boolean("Overwrite Existing",
        help="Also rental units with a receipt date already captured - else "
             "only those without.")
    count = fields.Integer("Rental Units", readonly=True)


class ModernisationReceipt(Wizard):
    """Capture the receipt of the announcement for all rental units with a
    contract and an increase at once - deviations are corrected afterwards
    per rental unit"""
    __name__ = 'real_estate.modernisation.receipt'

    start = StateView('real_estate.modernisation.receipt.start',
        'real_estate.modernisation_receipt_start_view_form', [
            Button("Cancel", 'end', 'tryton-cancel'),
            Button("Capture", 'capture', 'tryton-ok', default=True),
            ])
    capture = StateTransition()

    def _units(self, overwrite):
        return [u for u in self.record.units
            if u.contract and not u.excluded
            and (overwrite or not u.announcement_receipt_date)]

    def default_start(self, fields):
        return {
            'receipt_date': Pool().get('ir.date').today(),
            'overwrite': False,
            'count': len(self._units(False)),
            }

    def transition_capture(self):
        Unit = Pool().get('real_estate.modernisation.unit')
        units = self._units(self.start.overwrite)
        if not units:
            raise ValidationError(gettext(
                    'real_estate.msg_modernisation_no_receipts',
                    modernisation=self.record.rec_name))
        Unit.write(units,
            {'announcement_receipt_date': self.start.receipt_date})
        return 'end'


#**********************************************************************
class ModernisationPlanVacancy(Wizard):
    """Plan a modernisation of a vacant rental unit (optional step of the
    vacancy process, spec 9): a measure 'vacancy' in the state planning
    for the unit - an open one of the unit is opened instead"""
    __name__ = 'real_estate.modernisation.plan_vacancy'

    start = StateAction('real_estate.act_modernisation')

    def do_start(self, action):
        pool = Pool()
        Modernisation = pool.get('real_estate.modernisation')
        Unit = pool.get('real_estate.modernisation.unit')
        obj = self.record
        if not obj or obj.type != 'object':
            raise ValidationError(gettext(
                    'real_estate.msg_modernisation_plan_object'))
        units = Unit.search([
                ('object', '=', obj.id),
                ('modernisation.vacancy', '=', True),
                ('modernisation.state', 'not in', ['settled', 'cancelled']),
                ], limit=1)
        if units:
            measure = units[0].modernisation
        else:
            building = obj.parent
            while building and building.type not in ('building', 'property'):
                building = building.parent
            prop = building
            while prop and prop.type != 'property':
                prop = prop.parent
            if not prop:
                raise ValidationError(gettext(
                        'real_estate.msg_modernisation_plan_object'))
            measure, = Modernisation.create([{
                        'name': gettext(
                            'real_estate.msg_modernisation_plan_name',
                            object=obj.name),
                        'company': obj.company.id,
                        'property': prop.id,
                        'buildings': ([('add', [building.id])]
                            if building and building.type == 'building'
                            else []),
                        'vacancy': True,
                        }])
            date = measure._reference_date()
            values = {
                'modernisation': measure.id,
                'object': obj.id,
                'in_allocation': True,
                'excluded': True,
                'exclusion_reason': 'vacancy',
                }
            if (measure.allocation_key == 'measurement'
                    and measure.allocation_m_type):
                values['allocation_quantity'] = Modernisation._quantity(obj,
                    measure.allocation_m_type, date)
            Unit.create([values])
        action['pyson_domain'] = PYSONEncoder().encode(
            [('id', '=', measure.id)])
        action['domains'] = []
        return action, {'res_id': [measure.id]}


#**********************************************************************
class Process(metaclass=PoolMeta):
    "Named step methods of the process 'modernisation' (spec 9)"
    __name__ = 'real_estate.process'

    def _modernisation(self):
        resource = self.resource
        if resource and resource.__name__ == 'real_estate.modernisation':
            return resource
        return None

    def _modernisation_state_in(self, states):
        measure = self._modernisation()
        return bool(measure and measure.state in states)

    def _step_done_modernisation_planned(self):
        return self._modernisation_state_in(['draft', 'announced',
                'in_progress', 'completed', 'settled'])

    def _step_done_modernisation_units(self):
        measure = self._modernisation()
        return bool(measure and measure.units)

    def _step_done_modernisation_announced(self):
        return self._modernisation_state_in(['announced', 'in_progress',
                'completed', 'settled'])

    def _step_done_modernisation_receipts(self):
        "Every unit with an increase has the receipt of the announcement"
        measure = self._modernisation()
        if not measure or measure.state in ('planning', 'draft'):
            return False
        return all(u.announcement_receipt_date for u in measure.units
            if u.contract and not u.excluded)

    def _step_done_modernisation_objections(self):
        """The objection periods of all units have ended and no hardship
        objection is undecided"""
        Date = Pool().get('ir.date')
        measure = self._modernisation()
        if not self._step_done_modernisation_receipts():
            return False
        today = Date.today()
        for unit in measure.units:
            if not unit.contract or unit.excluded:
                continue
            deadline = unit.special_termination_deadline
            if deadline and today <= deadline:
                return False
            if unit.hardship_received and unit.hardship_decision in (
                    None, 'none'):
                return False
        return True

    def _step_done_modernisation_started(self):
        return self._modernisation_state_in(['in_progress', 'completed',
                'settled'])

    def _step_done_modernisation_completed(self):
        return self._modernisation_state_in(['completed', 'settled'])

    def _step_done_modernisation_settled(self):
        return self._modernisation_state_in(['settled'])

    def _step_create_modernisation_announcement(self):
        "Announcement steps: not for a vacancy or a trivial measure"
        measure = self._modernisation()
        return bool(measure and not measure.vacancy and not measure.trivial
            and measure.state != 'planning')

    def _step_create_modernisation_run(self):
        "Adjustment run: not for a vacancy measure"
        measure = self._modernisation()
        return bool(measure and not measure.vacancy
            and measure.state in ('completed', 'settled'))

    def _step_create_modernisation_rent_survey(self):
        """Update the features of the rent survey: only for a property
        with a rent survey, once the measure is completed"""
        measure = self._modernisation()
        return bool(measure and measure.property
            and measure.property.rent_survey
            and measure.state in ('completed', 'settled'))


#**********************************************************************
class InvoiceLine(metaclass=PoolMeta):
    __name__ = 'account.invoice.line'

    modernisation = fields.Function(fields.Many2One(
            'real_estate.modernisation', "Modernisation"),
        'get_modernisation', searcher='search_modernisation')

    @classmethod
    def get_modernisation(cls, lines, name):
        Cost = Pool().get('real_estate.modernisation.cost')
        result = {l.id: None for l in lines}
        for cost in Cost.search([
                    ('invoice_line', 'in', [l.id for l in lines])]):
            result[cost.invoice_line.id] = cost.modernisation.id
        return result

    @classmethod
    def search_modernisation(cls, name, clause):
        Cost = Pool().get('real_estate.modernisation.cost')
        _, operator, value = clause[:3]
        costs = Cost.search([('modernisation',) + tuple(clause[1:])])
        return [('id', 'in', [c.invoice_line.id for c in costs
                    if c.invoice_line])]


#**********************************************************************
class ModernisationAnnouncementLetter(Report):
    """Announcement of a modernisation (§ 555c BGB) - one letter per
    rental unit to all main tenants of its contract"""
    __name__ = 'real_estate.modernisation.announcement_letter'

    @classmethod
    def get_context(cls, records, header, data):
        pool = Pool()
        Party = pool.get('party.party')
        ContractReport = pool.get('real_estate.contract.report',
            type='report')
        context = super().get_context(records, header, data)
        context['format_value'] = ContractReport.format_value
        original = bool(data and data.get('original'))
        marks, tenants, measure_labels, areas = {}, {}, {}, {}
        labels = dict(pool.get('real_estate.modernisation').fields_get(
                ['measure_types'])['measure_types']['selection'])
        for record in records:
            measure = record.modernisation
            marks[record.id] = ('' if original or measure.state not in (
                    'planning', 'draft') else 'ENTWURF')
            contract = record.contract
            party_ids = (contract.main_tenant_party_ids or []
                if contract else [])
            parties = Party.browse(party_ids) if party_ids else (
                [contract.contractual_partner]
                if contract and contract.contractual_partner else [])
            tenants[record.id] = [
                (party, party.address_get(type='invoice'))
                for party in parties]
            measure_labels[record.id] = [labels.get(t, t)
                for t in (measure.measure_types or [])]
            areas[record.id] = measure.cap_areas().get(record.id)
        context['marks'] = marks
        context['tenants'] = tenants
        context['measure_labels'] = measure_labels
        context['areas'] = areas
        context['end_of_next_month'] = _end_of_next_month
        return context
