'Rent Adjustment (Mietanpassung)'
import builtins
import datetime
import hashlib
import operator
from decimal import Decimal, ROUND_HALF_UP

from dateutil.relativedelta import relativedelta

from trytond.exceptions import UserWarning
from trytond.i18n import gettext
from trytond.model import ModelSQL, ModelView, Workflow, fields
from trytond.model.exceptions import ValidationError
from trytond.modules.currency.fields import Monetary
from trytond.modules.product import price_digits
from trytond.transaction import Transaction
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Eval, If

from .contract_term import ContractGraduatedRentChangeWarning
from .contract_type import ADJUSTMENT_PROCEDURES, RUN_AGREEMENT_PROCEDURES

# Procedures agreed in the contract (with agreement date / written form)
AGREED_PROCEDURES = {'graduated_rent', 'index_rent'}


class RentAdjustmentGenerateWarning(UserWarning):
    pass


class RentAdjustmentIndexWarning(UserWarning):
    pass


#**********************************************************************
class ContractRentAdjustment(Workflow, ModelSQL, ModelView):
    'Rent Adjustment'
    # One rent adjustment of one contract term - header of every procedure
    # (graduated rent, index rent, comparative rent, ...). A graduated rent
    # generates all its steps in advance (spezifikation-mietanpassung.md)
    __name__ = 'real_estate.contract.rent_adjustment'

    _states_draft = {'readonly': Eval('state') != 'draft'}
    _graduated = Eval('procedure') == 'graduated_rent'
    _states_graduated = {
        'invisible': ~_graduated,
        'required': _graduated,
        }
    _index = Eval('procedure') == 'index_rent'
    _states_index = {
        'invisible': ~_index,
        'required': _index,
        'readonly': Eval('state') != 'draft',
        }
    _states_index_optional = {
        'invisible': ~_index,
        'readonly': Eval('state') != 'draft',
        }

    contract = fields.Many2One('real_estate.contract', "Contract",
        required=True, ondelete='CASCADE', states=_states_draft)
    company = fields.Function(fields.Many2One('company.company', "Company"),
        'on_change_with_company', searcher='search_contract_field')
    property = fields.Function(fields.Many2One('real_estate.base_object',
            "Property"),
        'on_change_with_property', searcher='search_contract_field')
    procedure = fields.Selection(ADJUSTMENT_PROCEDURES, "Procedure",
        required=True, sort=False, states=_states_draft)
    term = fields.Many2One('real_estate.contract.term', "Term",
        required=True, ondelete='RESTRICT',
        domain=[
            ('contract', '=', Eval('contract', -1)),
            ('contract.c_type.adjustment_procedures', 'in',
                [Eval('procedure', '')]),
            ('term_type.adjustment_procedures', 'in',
                [Eval('procedure', '')]),
            If(Eval('state') == 'draft',
                ('graduated_locked', '=', False), ()),
            ],
        states=_states_draft,
        help="Term to adjust (for a graduated rent: the base term, step "
             "0). Only terms of this contract are offered whose contract "
             "type and term type both allow the procedure.")
    valid_from = fields.Date("Valid from", required=True,
        states={
            'readonly': (Eval('state') != 'draft') | _graduated,
            },
        help="Date from which the adjustment applies - for a graduated "
             "rent the start of the base term.")
    term_type = fields.Function(fields.Many2One(
            'real_estate.contract.term.type', "Term Type"),
        'on_change_with_term_type')
    reference_item = fields.Function(fields.Many2One(
            'real_estate.contract.item', "Reference Item"),
        'on_change_with_reference_item')
    rhythm_months = fields.Integer("Rhythm (Months)",
        domain=[If(_graduated, ('rhythm_months', '>=', 12), ())],
        states=_states_graduated,
        help="Months between two steps - at least 12 (§ 557a para. 2 "
             "BGB: the rent has to remain unchanged for at least one "
             "year).")
    step_count = fields.Integer("Number of Steps",
        domain=[If(_graduated, ('step_count', '>=', 1), ())],
        states=_states_graduated)
    increase_mode = fields.Selection([
            ('absolute', "Absolute Amount"),
            ('per_area', "Amount per Area"),
            ('percent', "Percentage"),
            ], "Increase Mode", sort=False, states=_states_graduated,
        help="Only a calculation aid: every step stores exactly one amount "
             "(net, per rhythm period, rounded to the cent).")
    increase_value = fields.Numeric("Increase Value", digits=(16, 4),
        states=_states_graduated,
        help="Absolute Amount: amount per period. Amount per Area: amount "
             "per m² and period. Percentage: percent.")
    percent_basis = fields.Selection([
            ('base', "Base Amount"),
            ('previous', "Previous Step"),
            ], "Percentage Basis", sort=False,
        states={
            'invisible': ~_graduated | (Eval('increase_mode') != 'percent'),
            'required': _graduated & (Eval('increase_mode') == 'percent'),
            },
        help="Base Amount: same increase for all steps. Previous Step: "
             "each step is calculated from the previous one (compound).")
    generated_area = fields.Numeric("Generated Area", digits=(16, 4),
        readonly=True,
        help="Area fixed when generating (part of the agreement).")
    area = fields.Function(fields.Numeric("Area (m²)", digits=(16, 4),
            states={'invisible': ~_graduated
                | (Eval('increase_mode') != 'per_area')},
            help="Area of the base term's informative measurement as of "
                 "its start - fixed when generating."),
        'on_change_with_area')

    currency = fields.Function(fields.Many2One(
            'currency.currency', "Currency"),
        'on_change_with_currency')
    base_amount = fields.Function(Monetary("Base Amount",
            currency='currency', digits='currency',
            help="Net amount of the base term (quantity × unit price)."),
        'on_change_with_base_amount')
    increase_amount = fields.Function(Monetary("Increase of 1st Step",
            currency='currency', digits='currency'),
        'on_change_with_increase_amount')
    increase_percent = fields.Function(fields.Numeric(
            "Increase of 1st Step (%)", digits=(16, 2),
            help="Information only."),
        'on_change_with_increase_percent')
    final_amount = fields.Function(Monetary("Final Amount",
            currency='currency', digits='currency'),
        'on_change_with_final_amount')
    total_increase_percent = fields.Function(fields.Numeric(
            "Total Increase (%)", digits=(16, 2),
            help="Information only."),
        'on_change_with_total_increase_percent')
    last_step_date = fields.Function(fields.Date("Start of Last Step"),
        'on_change_with_last_step_date')
    preview = fields.Function(fields.Text("Preview"),
        'on_change_with_preview')

    base_valid_to_orig = fields.Date("Original End of Base Term",
        readonly=True,
        help="'Valid to' of the base term before generating - restored "
             "on reset, taken over by the last step.")
    agreement_date = fields.Date("Agreement Date",
        states={
            'required': Eval('procedure').in_(list(AGREED_PROCEDURES)),
            },
        help="Date of the agreement (graduated or index rent) resp. of the "
             "adjustment declaration.")
    written_form = fields.Boolean("Written Form",
        states={
            'invisible': ~Eval('procedure').in_(list(AGREED_PROCEDURES)),
            },
        help="The agreement was made in writing (§ 557a para. 1 BGB for a "
             "graduated rent, mandatory for residential contracts).")
    termination_waiver_until = fields.Date("Termination Waiver until",
        states={'invisible': ~_graduated},
        help="Tenant's waiver of termination until - at most 4 years after "
             "the agreement (§ 557a para. 3 BGB).")

    # Index rent (§ 557b BGB, spezifikation-indexmiete.md 4.1)
    type_of_use = fields.Function(fields.Char("Type of Use"),
        'on_change_with_type_of_use')
    price_index = fields.Many2One('real_estate.price_index', "Price Index",
        ondelete='RESTRICT',
        domain=[If(Eval('type_of_use') == 'residential',
                ('residential_allowed', '=', True), ())],
        states=_states_index,
        help="Index series of the agreement - for residential contracts "
             "only the consumer price index for Germany (§ 557b para. 1 "
             "BGB).")
    index_base_month = fields.Date("Base Month", states=_states_index,
        help="Month of the base index according to the contract (first "
             "day of the month).")
    index_base_value_contract = fields.Numeric("Base Value (Contract)",
        digits=(16, 1), states=_states_index_optional,
        help="Base index as stated in the contract (possibly in an older "
             "base year) - documentation only.")
    index_base_year_contract = fields.Integer("Base Year (Contract)",
        states=_states_index_optional,
        help="Base year of the value stated in the contract.")
    index_base_value = fields.Function(fields.Numeric("Base Value",
            digits=(16, 1),
            states={'invisible': ~_index},
            help="Value of the base month in the current base year of "
                 "the series - basis of the first adjustment."),
        'get_index_info')
    threshold_type = fields.Selection([
            ('none', "None"),
            ('percent', "Percent"),
            ('points', "Index Points"),
            ], "Threshold", sort=False,
        states={
            'invisible': ~_index,
            'required': _index,
            'readonly': ~Eval('state').in_(['draft', 'active']),
            },
        help="Minimum change agreed in the contract before the rent is "
             "adjusted.")
    threshold_value = fields.Numeric("Threshold Value", digits=(16, 2),
        states={
            'invisible': ~_index | (Eval('threshold_type') == 'none'),
            'required': _index & (Eval('threshold_type') != 'none'),
            'readonly': ~Eval('state').in_(['draft', 'active']),
            })
    effective_rule = fields.Selection([
            ('statutory', "Statutory (§ 557b para. 3 BGB)"),
            ('contract_month', "Contract Month"),
            ], "Effective Date Rule", sort=False, states=_states_index,
        help="Statutory: from the start of the month after next following "
             "the receipt of the declaration (mandatory for residential "
             "contracts). Contract Month: commercial only - from the given "
             "number of months after the index month.")
    effective_offset_months = fields.Integer("Offset (Months)",
        domain=[If(Eval('effective_rule') == 'contract_month',
                ('effective_offset_months', '>=', 0), ())],
        states={
            'invisible': ~_index | (Eval('effective_rule') != 'contract_month'),
            'required': _index & (Eval('effective_rule') == 'contract_month'),
            'readonly': Eval('state') != 'draft',
            })
    apply_cap = fields.Selection([
            ('auto', "Automatic"),
            ('never', "Never"),
            ], "Apply Cap", sort=False, states=_states_index,
        help="Automatic: the index rent cap rule applies if an active rule "
             "and a tight housing market apply. Never: e.g. commercial.")
    current_term = fields.Function(fields.Many2One(
            'real_estate.contract.term', "Current Term",
            states={'invisible': ~Eval('procedure').in_(
                    RUN_AGREEMENT_PROCEDURES)},
            help="Currently valid term of the chain (same term type and "
                 "item from the agreed term on)."),
        'get_index_info')
    current_index_month = fields.Function(fields.Date("Current Index Month",
            states={'invisible': ~_index},
            help="Index month of the last executed adjustment, else the "
                 "base month - reference of the next adjustment."),
        'get_index_info')
    current_index_value = fields.Function(fields.Numeric(
            "Current Index Value", digits=(16, 1),
            states={'invisible': ~_index}),
        'get_index_info')
    last_change_date = fields.Function(fields.Date("Last Change",
            states={'invisible': ~_index},
            help="Effective date of the last executed index adjustment, "
                 "else the start of the agreement ('Valid from')."),
        'get_index_info')
    next_possible_date = fields.Function(fields.Date("Next Possible Date",
            states={'invisible': ~_index},
            help="Last change + 12 months (§ 557b para. 2 BGB)."),
        'get_index_info')
    declaration_deadline = fields.Function(fields.Date("Declaration until",
            states={'invisible': ~_index},
            help="Follow-up: latest date to send the declaration so that "
                 "the adjustment takes effect on the next possible date "
                 "(receipt in the month before last, minus the receipt "
                 "days of the real estate accounting) - start the "
                 "adjustment run before this date."),
        'get_declaration_deadline', searcher='search_declaration_deadline')

    adjustments = fields.One2Many('real_estate.contract.term.adjustment',
        'rent_adjustment', "Adjustments", readonly=True,
        states={'invisible': ~Eval('procedure').in_(
                RUN_AGREEMENT_PROCEDURES)})

    terms = fields.One2Many('real_estate.contract.term', 'rent_adjustment',
        "Steps", readonly=True, order=[('graduated_step', 'ASC')])
    booked = fields.Function(fields.Boolean("Booked"), 'get_booked_info')
    last_booked_date = fields.Function(fields.Date("Last Booked Date"),
        'get_booked_info')
    last_booked_step = fields.Function(fields.Integer("Last Booked Step"),
        'get_booked_info')

    predecessor = fields.Function(fields.Many2One(
            'real_estate.contract.rent_adjustment', "Previous Graduated Rent",
            help="Graduated rent whose last step is the base term of this "
                 "one (follow-up graduated rent)."),
        'get_chain')
    successor = fields.Function(fields.Many2One(
            'real_estate.contract.rent_adjustment', "Follow-up Graduated Rent",
            help="Graduated rent based on the last step of this one."),
        'get_chain')

    generated_parameters = fields.Text("Generated Parameters", readonly=True,
        help="Parameters of the last generation - logged as the old "
             "parameters when the graduated rent is changed after booking.")

    state = fields.Selection([
            ('draft', "Draft"),
            ('generated', "Generated"),
            ('active', "Active"),
            ('closed', "Closed"),
            ], "State", readonly=True, required=True, sort=False)
    comment = fields.Text("Comment")

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._order.insert(0, ('contract', 'ASC'))
        cls._order.insert(1, ('valid_from', 'ASC'))
        cls._transitions |= {
            ('draft', 'generated'),
            ('generated', 'draft'),
            ('draft', 'active'),
            ('active', 'draft'),
            ('active', 'closed'),
            }
        graduated = Eval('procedure') == 'graduated_rent'
        run = Eval('procedure').in_(RUN_AGREEMENT_PROCEDURES)
        cls._buttons.update({
            'activate': {
                'invisible': ~run | (Eval('state') != 'draft'),
                'depends': ['procedure', 'state'],
                },
            'draft': {
                'invisible': ~run | (Eval('state') != 'active'),
                'depends': ['procedure', 'state'],
                },
            'close': {
                'invisible': ~run | (Eval('state') != 'active'),
                'depends': ['procedure', 'state'],
                },
            'generate': {
                'invisible': ~graduated | (Eval('state') != 'draft'),
                'depends': ['procedure', 'state'],
                },
            'regenerate': {
                'invisible': ~graduated | (Eval('state') != 'generated'),
                'depends': ['procedure', 'state'],
                },
            'reset': {
                'invisible': (~graduated | (Eval('state') != 'generated')
                    | Eval('booked', False)),
                'depends': ['procedure', 'state', 'booked'],
                },
            'terminate': {
                'invisible': (~graduated | (Eval('state') != 'generated')
                    | ~Eval('booked', False)),
                'depends': ['procedure', 'state', 'booked'],
                },
            })

    @classmethod
    def view_attributes(cls):
        return super().view_attributes() + [
            ('//page[@id="page_parameters"]', 'states',
                {'invisible': ~cls._graduated}, ['procedure']),
            ('//page[@id="page_steps"]', 'states',
                {'invisible': ~cls._graduated}, ['procedure']),
            ('//page[@id="page_index"]', 'states',
                {'invisible': ~cls._index}, ['procedure']),
            ('//page[@id="page_adjustments"]', 'states',
                {'invisible': ~Eval('procedure').in_(
                        RUN_AGREEMENT_PROCEDURES)}, ['procedure']),
            ]

    @staticmethod
    def default_state():
        return 'draft'

    @staticmethod
    def default_rhythm_months():
        return 12

    @staticmethod
    def default_step_count():
        return 10

    @staticmethod
    def default_increase_mode():
        return 'absolute'

    @staticmethod
    def default_percent_basis():
        return 'base'

    @staticmethod
    def default_threshold_type():
        return 'none'

    @staticmethod
    def default_effective_rule():
        return 'statutory'

    @staticmethod
    def default_apply_cap():
        return 'auto'

    def get_rec_name(self, name):
        labels = dict(self.fields_get(['procedure'])['procedure']['selection'])
        parts = [labels.get(self.procedure, self.procedure or '')]
        if self.contract:
            parts.append(self.contract.rec_name)
        if self.term:
            parts.append(self.term.rec_name.strip())
        return ' / '.join(p for p in parts if p)

    @fields.depends('contract', 'agreement_date',
        '_parent_contract.date_of_signature')
    def on_change_contract(self):
        if self.contract and not self.agreement_date:
            self.agreement_date = self.contract.date_of_signature

    @fields.depends('term', 'procedure', 'valid_from')
    def on_change_term(self):
        # A graduated rent starts with its base term, an index rent by
        # default with the agreed term
        if self.term and (self.procedure == 'graduated_rent'
                or (self.procedure == 'index_rent' and not self.valid_from)):
            self.valid_from = self.term.valid_from

    @fields.depends('term', 'procedure', 'valid_from')
    def on_change_procedure(self):
        self.on_change_term()

    @fields.depends('contract', '_parent_contract.type_of_use')
    def on_change_with_type_of_use(self, name=None):
        return self.contract.type_of_use if self.contract else None

    @fields.depends('index_base_month')
    def on_change_index_base_month(self):
        # The base index is a month value: always the first of the month
        if self.index_base_month:
            self.index_base_month = self.index_base_month.replace(day=1)

    @fields.depends('term')
    def on_change_with_term_type(self, name=None):
        return self.term.term_type if self.term else None

    @fields.depends('term')
    def on_change_with_reference_item(self, name=None):
        return self.term.reference_item if self.term else None

    @fields.depends('contract', '_parent_contract.currency')
    def on_change_with_currency(self, name=None):
        return self.contract.currency if self.contract else None

    @fields.depends('contract', '_parent_contract.company')
    def on_change_with_company(self, name=None):
        return self.contract.company if self.contract else None

    @fields.depends('contract', '_parent_contract.property')
    def on_change_with_property(self, name=None):
        return self.contract.property if self.contract else None

    @classmethod
    def search_contract_field(cls, name, clause):
        return [('contract.' + clause[0],) + tuple(clause[1:])]

    @fields.depends('generated_area', 'term')
    def on_change_with_area(self, name=None):
        if self.generated_area is not None:
            return self.generated_area
        return self._compute_area()

    def _compute_area(self):
        """Area for 'per_area': the base term's informative measurement as
        of its start (hierarchy-aware via ContractTerm._sum_measurements).
        None if the term type has no informative measurement type."""
        Term = Pool().get('real_estate.contract.term')
        term = self.term
        if not (term and term.term_type and term.term_type.info_m_type
                and term.reference_item):
            return None
        return Term._sum_measurements(
            term.reference_item, term.term_type.info_m_type,
            term.valid_from)

    @fields.depends('term', 'currency')
    def on_change_with_base_amount(self, name=None):
        term = self.term
        if not term:
            return None
        if term.graduated_amount is not None:
            return term.graduated_amount
        return self._round(
            Decimal(str(term.quantity or 0)) * (term.unit_price or 0))

    def _round(self, amount):
        # Commercial rounding (half up) to the currency digits
        digits = self.currency.digits if self.currency else 2
        return Decimal(amount).quantize(
            Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)

    def compute_amounts(self, start_amount, k_max):
        """Step amounts [amount_0, amount_1, ..., amount_k_max] starting
        from start_amount - the one calculation for preview and
        generation. The increase is rounded per step, so every step
        amount is an exact cent amount."""
        amounts = [self._round(start_amount)]
        value = Decimal(self.increase_value or 0)
        area = Decimal(str(self.area or 0))
        base_amount = self.base_amount or Decimal(0)
        for k in range(1, k_max + 1):
            if self.increase_mode == 'absolute':
                increase = self._round(value)
            elif self.increase_mode == 'per_area':
                increase = self._round(value * area)
            elif self.percent_basis == 'previous':
                increase = self._round(amounts[k - 1] * value / 100)
            else:
                increase = self._round(base_amount * value / 100)
            amounts.append(amounts[k - 1] + increase)
        return amounts

    def compute_dates(self, k_max):
        """Start dates [start, step 1, ..., step k_max]."""
        if not self.valid_from:
            return []
        return [self.valid_from + relativedelta(
                months=k * (self.rhythm_months or 0))
            for k in range(0, k_max + 1)]

    def _preview_amounts(self):
        if not (self.procedure == 'graduated_rent'
                and self.term and self.step_count
                and self.step_count > 0 and self.increase_mode):
            return []
        return self.compute_amounts(self.base_amount or 0, self.step_count)

    @fields.depends('procedure', 'term', 'currency', 'increase_mode',
        'increase_value', 'percent_basis', 'generated_area',
        methods=['on_change_with_base_amount', 'on_change_with_area'])
    def on_change_with_increase_amount(self, name=None):
        self.base_amount = self.on_change_with_base_amount()
        self.area = self.on_change_with_area()
        if not (self.procedure == 'graduated_rent'
                and self.term and self.increase_mode):
            return None
        amounts = self.compute_amounts(self.base_amount or 0, 1)
        return amounts[1] - amounts[0]

    @fields.depends(methods=['on_change_with_increase_amount'])
    def on_change_with_increase_percent(self, name=None):
        increase = self.on_change_with_increase_amount()
        if increase is None or not self.base_amount:
            return None
        return (increase / self.base_amount * 100).quantize(Decimal('0.01'))

    @fields.depends('terms', 'state', 'step_count', 'rhythm_months',
        methods=['on_change_with_increase_amount'])
    def on_change_with_final_amount(self, name=None):
        # After generating: from the actual steps (they may have been
        # changed individually), before: preview from the parameters
        if self.state == 'generated' and self.terms:
            last = max(self.terms, key=lambda t: t.graduated_step or 0)
            return last.graduated_amount
        self.on_change_with_increase_amount()
        amounts = self._preview_amounts()
        return amounts[-1] if amounts else None

    @fields.depends(methods=['on_change_with_final_amount'])
    def on_change_with_total_increase_percent(self, name=None):
        final = self.on_change_with_final_amount()
        if final is None or not self.base_amount:
            return None
        return ((final - self.base_amount) / self.base_amount * 100
            ).quantize(Decimal('0.01'))

    @fields.depends('procedure', 'terms', 'state', 'step_count',
        'rhythm_months', 'valid_from')
    def on_change_with_last_step_date(self, name=None):
        if self.procedure != 'graduated_rent':
            return None
        if self.state == 'generated' and self.terms:
            last = max(self.terms, key=lambda t: t.graduated_step or 0)
            return last.valid_from
        dates = self.compute_dates(self.step_count or 0)
        return dates[-1] if dates else None

    @fields.depends('step_count', 'rhythm_months', 'valid_from', 'currency',
        methods=['on_change_with_increase_amount'])
    def on_change_with_preview(self, name=None):
        """Step table (step, start, amount, increase and - if the term type
        has an informative area - the new amount per m²) as text - uses the
        same calculation as the generation."""
        Lang = Pool().get('ir.lang')
        self.on_change_with_increase_amount()
        amounts = self._preview_amounts()
        dates = self.compute_dates(len(amounts) - 1) if amounts else []
        if not amounts or len(dates) != len(amounts):
            return ''
        lang = Lang.get()
        area = Decimal(str(self.area)) if self.area else None
        currency = self.currency.code if self.currency else ''

        def number(value):
            return lang.format_number(value, 2)

        lines = []
        for k, (date, amount) in enumerate(zip(dates, amounts)):
            values = {
                'increase': number(amount - amounts[k - 1]) if k else '',
                'per_area': (number((amount / area).quantize(
                            Decimal('0.01'), rounding=ROUND_HALF_UP))
                    if area else ''),
                'currency': currency,
                }
            if k and area:
                info = gettext(
                    'real_estate.msg_graduated_preview_increase_area',
                    **values)
            elif k:
                info = gettext(
                    'real_estate.msg_graduated_preview_increase', **values)
            elif area:
                info = gettext(
                    'real_estate.msg_graduated_preview_area', **values)
            else:
                info = ''
            lines.append(
                f'{k:>3}  {date:%d.%m.%Y}  {number(amount):>12}  {info}')
        return '\n'.join(lines)

    @classmethod
    def get_booked_info(cls, records, names):
        """Booking state of the steps: booked = any step with a last
        document date (see ContractTerm.last_document_date)."""
        result = {n: {r.id: None for r in records} for n in names}
        for record in records:
            steps = record._step_terms()
            booked = {k: t for k, t in steps.items() if t.last_document_date}
            if 'booked' in names:
                result['booked'][record.id] = bool(booked)
            if booked and 'last_booked_date' in names:
                result['last_booked_date'][record.id] = max(
                    t.last_document_date for t in booked.values())
            if booked and 'last_booked_step' in names:
                result['last_booked_step'][record.id] = max(booked)
        return result

    @classmethod
    def get_chain(cls, records, names):
        """Chain of graduated rents: predecessor = owner of the base term
        (if not this one), successor = graduated rent based on this one's
        last step (spec 6.4)."""
        result = {n: {r.id: None for r in records} for n in names}
        for record in records:
            if record.procedure != 'graduated_rent' or not record.term:
                continue
            owner = record.term.rent_adjustment
            if 'predecessor' in names and owner and owner != record:
                result['predecessor'][record.id] = owner.id
            steps = record._step_terms()
            if 'successor' in names and steps:
                followers = cls.search([
                        ('procedure', '=', 'graduated_rent'),
                        ('term', '=', steps[max(steps)].id),
                        ('id', '!=', record.id),
                        ], limit=1)
                if followers:
                    result['successor'][record.id] = followers[0].id
        return result

    def _step_terms(self):
        """{step number: term} of a generated graduated rent - step 0 is
        the base term (for a follow-up graduated rent the last step of the
        previous one, which keeps its own step number there)."""
        if self.state != 'generated' or not self.term:
            return {}
        steps = {t.graduated_step: t for t in self.terms
            if (t.graduated_step or 0) > 0}
        steps[0] = self.term
        return steps

    @classmethod
    def create(cls, vlist):
        vlist = [cls._sync_valid_from(dict(v)) for v in vlist]
        return super().create(vlist)

    @classmethod
    def write(cls, *args):
        actions = iter(args)
        args = []
        for records, values in zip(actions, actions):
            if {'term', 'procedure'} & set(values):
                for record in records:
                    args.extend(([record], cls._sync_valid_from(
                                dict(values), record)))
            else:
                args.extend((records, values))
        super().write(*args)

    @classmethod
    def _sync_valid_from(cls, values, record=None):
        """A graduated rent starts with its base term - 'Valid from' is
        always the base term's start (also for imports/scripts)."""
        Term = Pool().get('real_estate.contract.term')
        procedure = values.get('procedure',
            record.procedure if record else None)
        term_id = values.get('term',
            record.term.id if record and record.term else None)
        if procedure == 'graduated_rent' and term_id:
            values['valid_from'] = Term(term_id).valid_from
        return values

    @classmethod
    def validate_fields(cls, records, field_names):
        super().validate_fields(records, field_names)
        if field_names & {'procedure', 'term', 'contract'}:
            cls._check_procedure(records)
        if 'index_base_month' in field_names:
            for record in records:
                if (record.index_base_month
                        and record.index_base_month.day != 1):
                    raise ValidationError(gettext(
                        'real_estate.msg_index_rent_base_month_first_day',
                        rent_adjustment=record.rec_name))

    @classmethod
    def _check_procedure(cls, records):
        """The procedure must be allowed by the contract type and the term
        type, the term must belong to the contract, and a term can have
        at most one agreed procedure (graduated or index rent) - § 557a
        and § 557b BGB exclude each other."""
        UseClass = Pool().get('real_estate.use_class')
        labels = dict(cls.fields_get(['procedure'])['procedure']['selection'])
        for record in records:
            procedure = labels.get(record.procedure, record.procedure)
            term = record.term
            if term.contract != record.contract:
                raise ValidationError(gettext(
                    'real_estate.msg_rent_adjustment_term_contract',
                    term=term.rec_name.strip(),
                    contract=record.contract.rec_name))
            c_type = record.contract.c_type
            if record.procedure not in (
                    (c_type.adjustment_procedures or []) if c_type else []):
                raise ValidationError(gettext(
                    'real_estate.msg_rent_adjustment_contract_type',
                    procedure=procedure,
                    c_type=c_type.rec_name if c_type else ''))
            if record.procedure not in (
                    term.term_type.adjustment_procedures or []):
                raise ValidationError(gettext(
                    'real_estate.msg_rent_adjustment_term_type',
                    procedure=procedure,
                    term_type=term.term_type.rec_name.strip()))
            # the rental units of the term's item: their use class must
            # allow the procedure (comparative rent: apartments only)
            objects = (list(term.reference_item.objects)
                if term.reference_item else [])
            if not UseClass.allows(objects, record.procedure):
                raise ValidationError(gettext(
                    'real_estate.msg_rent_adjustment_use_class',
                    procedure=procedure, term=term.rec_name.strip(),
                    objects=', '.join(o.rec_name for o in objects) or '-'))
            # A locked graduated rent term cannot get another adjustment
            # (§ 557a para. 2 BGB) - checked for new/draft adjustments
            if record.state == 'draft' and term.graduated_locked:
                raise ValidationError(gettext(
                    'real_estate.msg_rent_adjustment_term_locked',
                    term=term.rec_name.strip()))
            if record.procedure in AGREED_PROCEDURES:
                others = cls.search([
                        ('term', '=', term.id),
                        ('procedure', 'in', list(AGREED_PROCEDURES)),
                        ('state', '!=', 'closed'),
                        ('id', '!=', record.id),
                        ], limit=1)
                if others:
                    raise ValidationError(gettext(
                        'real_estate.msg_rent_adjustment_agreed_exclusive',
                        term=term.rec_name.strip(),
                        other=others[0].rec_name))
            # I10: no comparative rent (§ 558 BGB) for a residential term
            # with an active index rent (§ 557b para. 2 sentence 3 BGB)
            if (record.procedure == 'comparative_rent'
                    and record.contract.type_of_use == 'residential'):
                for index_rent in cls.search([
                            ('contract', '=', record.contract.id),
                            ('procedure', '=', 'index_rent'),
                            ('state', '=', 'active'),
                            ]):
                    if term in index_rent._chain_terms():
                        raise ValidationError(gettext(
                            'real_estate.msg_index_rent_comparative',
                            term=term.rec_name.strip(),
                            index_rent=index_rent.rec_name))

    # ------------------------------------------------------------------
    # Graduated rent: generate / reset / regenerate (spec 5.3, 6.2, 6.3)

    @classmethod
    @ModelView.button
    @Workflow.transition('generated')
    def generate(cls, records):
        for record in records:
            if record.procedure != 'graduated_rent':
                continue
            record._check_generate()
            record._generate()

    @classmethod
    @ModelView.button
    @Workflow.transition('draft')
    def reset(cls, records):
        for record in records:
            if record.procedure != 'graduated_rent':
                continue
            record._check_reset()
            record._reset()
            record.term.contract.add_log('rent_adjustment',
                f'graduated rent reset: {record.rec_name}')
            Pool().get('real_estate.contract')._re_calc_terms(
                [record.term.contract])

    @classmethod
    @ModelView.button
    def regenerate(cls, records):
        for record in records:
            if record.procedure != 'graduated_rent':
                continue
            if record.booked:
                record._regenerate_booked()
                continue
            record._check_reset()
            record._reset()
            # _reset() restored the base term - regenerate from there
            record = cls(record.id)
            record._check_generate()
            record._generate()

    def _params_hash(self):
        """Hash of the parameters - part of warning keys, so a confirmed
        warning only covers exactly these parameters."""
        values = (self.term.id if self.term else None, self.rhythm_months,
            self.step_count, self.increase_mode, str(self.increase_value),
            self.percent_basis, self.written_form,
            str(self.termination_waiver_until), str(self.agreement_date))
        return hashlib.md5(repr(values).encode()).hexdigest()[:12]

    def _warn(self, code, message):
        Warning = Pool().get('res.user.warning')
        key = Warning.format(
            f'rent_adjustment_{code}_{self._params_hash()}', [self])
        if Warning.check(key):
            raise RentAdjustmentGenerateWarning(key, message)

    def _check_generate(self):
        """Checks G01-G15 before generating: errors raise, warnings are
        confirmable (spec 5.3)."""
        term = self.term
        contract = self.contract
        residential = contract.type_of_use == 'residential'
        name = self.rec_name
        # G01: procedure allowed by contract type and term type
        self.__class__._check_procedure([self])
        # G09: no graduated rent after termination / contract end
        if (contract.state not in ('draft', 'running')
                or contract.termination_date):
            raise ValidationError(gettext(
                'real_estate.msg_graduated_contract_state',
                rent_adjustment=name))
        # G15: the base term has to be an absolute amount
        if term.term_type.m_type:
            raise ValidationError(gettext(
                'real_estate.msg_graduated_measurement',
                rent_adjustment=name,
                term_type=term.term_type.rec_name.strip()))
        # G02, G03
        if (self.rhythm_months or 0) < 12:
            raise ValidationError(gettext(
                'real_estate.msg_graduated_rhythm', rent_adjustment=name))
        if (self.step_count or 0) < 1:
            raise ValidationError(gettext(
                'real_estate.msg_graduated_step_count',
                rent_adjustment=name))
        if not term.quantity:
            raise ValidationError(gettext(
                'real_estate.msg_graduated_zero_quantity',
                rent_adjustment=name))
        # G14: area for 'per_area'
        if self.increase_mode == 'per_area' and not self._compute_area():
            raise ValidationError(gettext(
                'real_estate.msg_graduated_no_area', rent_adjustment=name))
        # G04: every increase at least one cent
        amounts = self.compute_amounts(self.base_amount or 0,
            self.step_count)
        if (not self.increase_value or self.increase_value <= 0
                or any(b - a < Decimal('0.01')
                    for a, b in zip(amounts, amounts[1:]))):
            raise ValidationError(gettext(
                'real_estate.msg_graduated_increase', rent_adjustment=name))
        # G05: base term not booked
        if term.last_document_date:
            raise ValidationError(gettext(
                'real_estate.msg_graduated_term_booked',
                rent_adjustment=name, term=term.rec_name.strip(),
                date=term.last_document_date.isoformat()))
        # G08: base term not part of another graduated rent - except the
        # last step of a graduated rent (follow-up graduated rent)
        other = term.rent_adjustment
        if other and other != self and not (
                other.state == 'generated'
                and term.graduated_step == other.step_count):
            raise ValidationError(gettext(
                'real_estate.msg_graduated_term_locked',
                rent_adjustment=name, other=other.rec_name))
        # G06: no follow-up term of the same type/item
        Term = Pool().get('real_estate.contract.term')
        follow_ups = Term.search([
                ('contract', '=', contract.id),
                ('term_type', '=', term.term_type.id),
                ('reference_item', '=',
                    term.reference_item.id if term.reference_item else None),
                ('valid_from', '>', term.valid_from),
                ('id', '!=', term.id),
                ])
        if follow_ups:
            raise ValidationError(gettext(
                'real_estate.msg_graduated_follow_up',
                rent_adjustment=name,
                follow_up=follow_ups[0].rec_name.strip()))
        # G07: last step within the term's and the contract's end
        dates = self.compute_dates(self.step_count)
        limits = [d for d in (term.valid_to,
                contract.get_effective_end_date()) if d]
        if limits and dates[-1] > min(limits):
            max_steps = len([d for d in dates[1:] if d <= min(limits)])
            raise ValidationError(gettext(
                'real_estate.msg_graduated_too_many_steps',
                rent_adjustment=name, date=dates[-1].isoformat(),
                end=min(limits).isoformat(), max=max_steps))
        # G10: written form (residential: mandatory)
        if not self.written_form:
            if residential:
                raise ValidationError(gettext(
                    'real_estate.msg_graduated_written_form',
                    rent_adjustment=name))
            self._warn('written_form', gettext(
                    'real_estate.msg_graduated_written_form_warning',
                    rent_adjustment=name))
        # G11: termination waiver at most 4 years (residential)
        if (residential and self.termination_waiver_until
                and self.agreement_date
                and self.termination_waiver_until
                > self.agreement_date + relativedelta(years=4)):
            self._warn('waiver', gettext(
                    'real_estate.msg_graduated_waiver',
                    rent_adjustment=name,
                    date=self.termination_waiver_until.isoformat()))
        # G12: rounding of unit price when quantity != 1
        quantity = Decimal(str(term.quantity))
        if quantity != 1:
            exp = Decimal(1).scaleb(-price_digits[1])
            deviation = max(abs((quantity * (a / quantity).quantize(exp)
                        ).quantize(Decimal('0.01')) - a) for a in amounts)
            if deviation:
                self._warn('rounding', gettext(
                        'real_estate.msg_graduated_rounding',
                        rent_adjustment=name, quantity=str(quantity),
                        deviation=str(deviation)))
        # G13: step start matching the term's billing rhythm
        mismatch = [d for d in dates[1:] if not self._matches_rhythm(d)]
        if mismatch:
            self._warn('rhythm', gettext(
                    'real_estate.msg_graduated_rhythm_mismatch',
                    rent_adjustment=name, date=mismatch[0].isoformat()))

    def _matches_rhythm(self, date):
        """True if 'date' is a document date of the base term's rhythm
        (monthly/quarterly/annually); other rhythms are not checked."""
        term = self.term
        months = {'monthly': 1, 'quarterly': 3, 'annually': 12}.get(
            term.rhythm_type)
        if not months:
            return True
        months *= term.rhythm or 1
        first = term.valid_from
        if term.rhythm_start in (None, ''):
            first = first.replace(day=1)
        elif term.rhythm_start == '15th_month':
            first = first.replace(day=15)
        if term.rhythm_start == 'month_end':
            if (date + datetime.timedelta(days=1)).day != 1:
                return False
        elif date.day != first.day:
            return False
        diff = (date.year - first.year) * 12 + date.month - first.month
        return diff % months == 0

    def _generate(self):
        pool = Pool()
        Term = pool.get('real_estate.contract.term')
        Contract = pool.get('real_estate.contract')
        term = self.term
        contract = term.contract
        amount_0 = self._round(
            Decimal(str(term.quantity)) * (term.unit_price or 0))
        # the parameters refer to the base amount before generating
        self.base_amount = amount_0
        amounts = self.compute_amounts(amount_0, self.step_count)
        dates = self.compute_dates(self.step_count)
        quantity = Decimal(str(term.quantity))
        exp = Decimal(1).scaleb(-price_digits[1])
        self.__class__.write([self], {
                'base_valid_to_orig': term.valid_to,
                'generated_area': (self._compute_area()
                    if self.increase_mode == 'per_area' else None),
                })
        with Transaction().set_context(
                _skip_re_calc=True, _graduated_rent_generate=True):
            # A follow-up graduated rent starts with the last step of the
            # previous one: that term stays a member of the previous
            # graduated rent and is step 0 of this one only via 'term'
            if not term.rent_adjustment:
                Term.write([term], {
                        'rent_adjustment': self.id,
                        'graduated_step': 0,
                        'graduated_amount': amount_0,
                        })
            previous = term
            for step in range(1, self.step_count + 1):
                previous = Term._split(previous, dates[step],
                    (amounts[step] / quantity).quantize(exp),
                    values={
                        'rent_adjustment': self.id,
                        'graduated_step': step,
                        'graduated_amount': amounts[step],
                        })
        Contract._re_calc_terms([contract])
        self.__class__.write([self], {
                'generated_parameters': self._parameters_text()})
        overview = '\n'.join(
            f'{k}: {d.isoformat()} {a}'
            for k, (d, a) in enumerate(zip(dates, amounts)))
        contract.add_log('rent_adjustment',
            f'graduated rent generated: {self.rec_name} '
            f'(rhythm {self.rhythm_months} months, {self.step_count} steps, '
            f'{self.increase_mode} {self.increase_value})\n{overview}')

    def _check_reset(self):
        """Reset/regenerate only while nothing is booked, the last step is
        unchanged and no follow-up graduated rent is based on it."""
        name = self.rec_name
        if self.booked:
            raise ValidationError(gettext(
                'real_estate.msg_graduated_booked', rent_adjustment=name))
        self._check_follow_ups()

    def _check_follow_ups(self):
        """No follow-up graduated rent on the last step, last step not
        changed (split/ended by another procedure) - spec 6.4."""
        name = self.rec_name
        steps = self._step_terms()
        if not steps:
            return
        last = steps[max(steps)]
        followers = self.search([
                ('term', '=', last.id),
                ('id', '!=', self.id),
                ])
        if followers:
            raise ValidationError(gettext(
                'real_estate.msg_graduated_follow_up_rent_adjustment',
                rent_adjustment=name, other=followers[0].rec_name))
        if last.valid_to != self.base_valid_to_orig:
            raise ValidationError(gettext(
                'real_estate.msg_graduated_last_step_changed',
                rent_adjustment=name, term=last.rec_name.strip()))

    def _reset(self):
        """Delete steps 1...n and restore the base term (spec 6.2)."""
        Term = Pool().get('real_estate.contract.term')
        steps = [t for t in self.terms if (t.graduated_step or 0) > 0]
        with Transaction().set_context(
                _skip_re_calc=True, _graduated_rent_generate=True):
            if steps:
                Term.delete(steps)
            values = {'valid_to': self.base_valid_to_orig}
            # Membership only removed if it is this graduated rent's own
            # (not for the last step of a previous graduated rent)
            if self.term.rent_adjustment == self:
                values.update({
                        'rent_adjustment': None,
                        'graduated_step': None,
                        'graduated_amount': None,
                        })
            Term.write([self.term], values)
        self.__class__.write([self], {
                'base_valid_to_orig': None,
                'generated_area': None,
                'generated_parameters': None,
                })

    # ------------------------------------------------------------------
    # Changes after the first booking (spec 6.5)

    def _parameters_text(self):
        labels = dict(self.fields_get(
            ['increase_mode'])['increase_mode']['selection'])
        text = (f'rhythm {self.rhythm_months} months, '
            f'{self.step_count} steps, '
            f'{labels.get(self.increase_mode, self.increase_mode)} '
            f'{self.increase_value}')
        if self.increase_mode == 'percent':
            text += f' ({self.percent_basis})'
        return text

    def _overview(self):
        return '\n'.join(
            f'{k}: {t.valid_from.isoformat()} - '
            f'{t.valid_to.isoformat() if t.valid_to else "..."} '
            f'{t.graduated_amount if k else self.base_amount}'
            f'{" (booked)" if t.last_document_date else ""}'
            for k, t in sorted(self._step_terms().items()))

    def _booked_to(self):
        steps = self._step_terms()
        if self.last_booked_step is None:
            return None
        return steps[self.last_booked_step].get_booked_to()

    def _contract_change_values(self):
        """Values of the graduated rent warning (msg_graduated_rent_...)."""
        steps = self._step_terms()
        booked_to = self._booked_to()
        last = steps[max(steps)] if steps else self.term
        return {
            'contract': self.contract.rec_name,
            'agreement_date': (self.agreement_date.isoformat()
                if self.agreement_date else ''),
            'steps': max(steps) if steps else self.step_count,
            'first_date': self.valid_from.isoformat(),
            'last_date': last.valid_from.isoformat(),
            'booked_to': booked_to.isoformat() if booked_to else '',
            'first_open_date': ((booked_to + datetime.timedelta(days=1))
                .isoformat() if booked_to else ''),
            }

    def _contract_change_warning(self, action):
        """The graduated rent is part of the contract: a change after the
        first booking needs a contract amendment - confirmable warning,
        keyed on the action and the new parameters."""
        Warning = Pool().get('res.user.warning')
        key = Warning.format(
            f'graduated_rent_contract_change_{action}_{self._params_hash()}',
            [self])
        if Warning.check(key):
            raise ContractGraduatedRentChangeWarning(key, gettext(
                'real_estate.msg_graduated_rent_contract_change',
                **self._contract_change_values()))

    def _log_change(self, action, before):
        self.contract.add_log('rent_adjustment',
            f'graduated rent changed after booking ({action}): '
            f'{self.rec_name} - graduated rent warning confirmed by user '
            f'{Transaction().user}\n'
            f'old parameters: {self.generated_parameters or ""}\n'
            f'new parameters: {self._parameters_text()}\n'
            f'steps before:\n{before}\n'
            f'steps after:\n{self.__class__(self.id)._overview()}')

    def _regenerate_booked(self):
        """Regenerate only the steps after the last booked step f: booked
        steps keep amount and start (spec 6.5)."""
        pool = Pool()
        Term = pool.get('real_estate.contract.term')
        Contract = pool.get('real_estate.contract')
        name = self.rec_name
        self._check_follow_ups()
        steps = self._step_terms()
        f = self.last_booked_step
        f_term = steps[f]
        if (self.step_count or 0) < f:
            raise ValidationError(gettext(
                'real_estate.msg_graduated_step_count_booked',
                rent_adjustment=name, step=f))
        if (self.rhythm_months or 0) < 12:
            raise ValidationError(gettext(
                'real_estate.msg_graduated_rhythm', rent_adjustment=name))
        count = self.step_count - f
        amounts = self.compute_amounts(
            f_term.graduated_amount if f else self.base_amount, count)
        dates = [f_term.valid_from + relativedelta(
                months=k * self.rhythm_months) for k in range(count + 1)]
        if (not self.increase_value or self.increase_value <= 0
                or any(b - a < Decimal('0.01')
                    for a, b in zip(amounts, amounts[1:]))):
            raise ValidationError(gettext(
                'real_estate.msg_graduated_increase', rent_adjustment=name))
        booked_to = f_term.get_booked_to()
        if count and booked_to and dates[1] <= booked_to:
            raise ValidationError(gettext(
                'real_estate.msg_graduated_booked_period',
                rent_adjustment=name, date=dates[1].isoformat(),
                booked_to=booked_to.isoformat()))
        limits = [d for d in (self.base_valid_to_orig,
                self.contract.get_effective_end_date()) if d]
        if count and limits and dates[-1] > min(limits):
            max_steps = f + len([d for d in dates[1:] if d <= min(limits)])
            raise ValidationError(gettext(
                'real_estate.msg_graduated_too_many_steps',
                rent_adjustment=name, date=dates[-1].isoformat(),
                end=min(limits).isoformat(), max=max_steps))
        self._contract_change_warning('regenerate')
        before = self._overview()
        quantity = Decimal(str(f_term.quantity))
        exp = Decimal(1).scaleb(-price_digits[1])
        with Transaction().set_context(
                _skip_re_calc=True, _graduated_rent_generate=True):
            later = [t for k, t in steps.items() if k > f]
            if later:
                Term.delete(later)
            Term.write([f_term], {'valid_to': self.base_valid_to_orig})
            previous = f_term
            for k in range(1, count + 1):
                previous = Term._split(previous, dates[k],
                    (amounts[k] / quantity).quantize(exp),
                    values={
                        'rent_adjustment': self.id,
                        'graduated_step': f + k,
                        'graduated_amount': amounts[k],
                        })
        Contract._re_calc_terms([self.contract])
        self._log_change('regenerate', before)
        self.__class__.write([self], {
                'generated_parameters': self._parameters_text()})

    @classmethod
    @ModelView.button
    def terminate(cls, records):
        """End the graduated rent after the last booked step: the unbooked
        steps are deleted, the last booked step becomes the last step
        (open again, with the original end) - spec 6.2."""
        pool = Pool()
        Term = pool.get('real_estate.contract.term')
        Contract = pool.get('real_estate.contract')
        for record in records:
            if record.procedure != 'graduated_rent' or not record.booked:
                continue
            record._check_follow_ups()
            steps = record._step_terms()
            f = record.last_booked_step
            later = [t for k, t in steps.items() if k > f]
            if not later:
                raise ValidationError(gettext(
                    'real_estate.msg_graduated_nothing_to_terminate',
                    rent_adjustment=record.rec_name))
            record._contract_change_warning('terminate')
            before = record._overview()
            with Transaction().set_context(
                    _skip_re_calc=True, _graduated_rent_generate=True):
                Term.delete(later)
                Term.write([steps[f]], {
                        'valid_to': record.base_valid_to_orig})
            if f:
                cls.write([record], {'step_count': f})
            else:
                # only the base term is booked: no step remains
                cls(record.id)._reset()
                cls.write([record], {'state': 'draft'})
            Contract._re_calc_terms([record.contract])
            record = cls(record.id)
            record._log_change('terminate', before)
            cls.write([record], {
                    'generated_parameters': (record._parameters_text()
                        if record.state == 'generated' else None)})

    # ------------------------------------------------------------------
    # Index rent: agreement (spezifikation-indexmiete.md 4)

    def _chain_terms(self):
        """Terms of the chain of the agreed term: same contract, term type
        and item, starting with the agreed term - ordered by start (also
        covers splits by other procedures)."""
        Term = Pool().get('real_estate.contract.term')
        term = self.term
        if not term:
            return []
        return Term.search([
                ('contract', '=', term.contract.id),
                ('term_type', '=', term.term_type.id),
                ('reference_item', '=',
                    term.reference_item.id if term.reference_item else None),
                ('valid_from', '>=', term.valid_from),
                ], order=[('valid_from', 'ASC'), ('id', 'ASC')])

    @classmethod
    def get_index_info(cls, records, names):
        result = {name: {} for name in names}
        for record in records:
            index_rent = record.procedure == 'index_rent'
            chain = (record._chain_terms()
                if record.procedure in RUN_AGREEMENT_PROCEDURES else [])
            base_value = None
            if (index_rent and record.price_index
                    and record.index_base_month):
                value = record.price_index.get_value(record.index_base_month)
                base_value = value.value if value else None
            # Reference: the last executed adjustment (index month read
            # again from the current series), else the base index; last
            # change: its effective date, else the start of the agreement
            month, value = (record.index_base_month if index_rent
                else None), base_value
            last_change = record.valid_from if index_rent else None
            done = [a for a in (record.adjustments if index_rent else [])
                if a.state == 'done' and a.index_month_new]
            if done:
                last = max(done, key=lambda a: (a.planned_valid_from
                        or datetime.date.min, a.id))
                month = last.index_month_new
                current = (record.price_index.get_value(month)
                    if record.price_index else None)
                value = current.value if current else None
                last_change = last.planned_valid_from or last_change
            values = {
                'index_base_value': base_value,
                'current_term': chain[-1].id if chain else None,
                'current_index_month': month,
                'current_index_value': value,
                'last_change_date': last_change,
                'next_possible_date': (
                    last_change + relativedelta(months=12)
                    if last_change else None),
                }
            for name in names:
                result[name][record.id] = values[name]
        return result

    def get_declaration_deadline(self, name):
        return self._declaration_deadline()

    @classmethod
    def search_declaration_deadline(cls, name, clause):
        # Computed in Python over the active index rents (follow-up list)
        _, operator_, value = clause[:3]
        compare = {
            '=': operator.eq, '!=': operator.ne,
            '<': operator.lt, '<=': operator.le,
            '>': operator.gt, '>=': operator.ge,
            }[operator_]
        ids = []
        for record in cls.search([
                    ('procedure', '=', 'index_rent'),
                    ('state', '=', 'active'),
                    ]):
            deadline = record._declaration_deadline()
            if deadline is None:
                if value is None and operator_ == '=':
                    ids.append(record.id)
                continue
            if value is not None and compare(deadline, value):
                ids.append(record.id)
        return [('id', 'in', ids)]

    # builtins: the field "property" shadows the decorator in the class body
    @builtins.property
    def _residential(self):
        return bool(self.contract
            and self.contract.type_of_use == 'residential')

    def _index_warning(self, code, message):
        Warning = Pool().get('res.user.warning')
        key = Warning.format(f'index_rent_{code}', [self])
        if Warning.check(key):
            raise RentAdjustmentIndexWarning(key, message)

    def _check_activate(self):
        """Checks I01-I03, I10, I12 when activating an index rent
        agreement (errors for residential, hints for commercial)."""
        name = self.rec_name
        # I01: written form and agreement date (§ 557b para. 1 BGB)
        if not self.written_form or not self.agreement_date:
            message = gettext('real_estate.msg_index_rent_written_form',
                rent_adjustment=name)
            if self._residential:
                raise ValidationError(message)
            self._index_warning('written_form', message)
        # Residential: statutory effective date (§ 557b para. 3, 5 BGB)
        if self._residential and self.effective_rule != 'statutory':
            raise ValidationError(gettext(
                'real_estate.msg_index_rent_effective_rule',
                rent_adjustment=name))
        # I02: only the VPI for residential contracts
        if self._residential and not self.price_index.residential_allowed:
            raise ValidationError(gettext(
                'real_estate.msg_index_rent_residential_index',
                rent_adjustment=name, index=self.price_index.rec_name))
        # I03: value of the base month in the current series
        if not self.price_index.get_value(self.index_base_month):
            raise ValidationError(gettext(
                'real_estate.msg_index_rent_base_value_missing',
                rent_adjustment=name, index=self.price_index.rec_name,
                month=self.index_base_month.strftime('%m.%Y'),
                base_year=self.price_index.base_year))
        # I10: no comparative rent, modernisation only confirmed
        if self._residential:
            chain = [t.id for t in self._chain_terms()]
            others = self.search([
                    ('term', 'in', chain),
                    ('procedure', 'in', ['comparative_rent', 'modernisation']),
                    ('state', '!=', 'closed'),
                    ('id', '!=', self.id),
                    ])
            for other in others:
                if other.procedure == 'comparative_rent':
                    raise ValidationError(gettext(
                        'real_estate.msg_index_rent_comparative',
                        term=other.term.rec_name.strip(),
                        index_rent=name))
            if any(o.procedure == 'modernisation' for o in others):
                self._index_warning('modernisation', gettext(
                    'real_estate.msg_index_rent_modernisation',
                    rent_adjustment=name))
        # I12: commercial - Preisklauselgesetz (long-term contract)
        else:
            contract = self.contract
            long_term = bool(not contract.unlimited and contract.end_date
                and contract.start_date and contract.end_date
                >= contract.start_date + relativedelta(years=10)
                - datetime.timedelta(days=1))
            if not long_term:
                self._index_warning('price_clause', gettext(
                    'real_estate.msg_index_rent_price_clause',
                    rent_adjustment=name))

    @classmethod
    @ModelView.button
    @Workflow.transition('active')
    def activate(cls, records):
        for record in records:
            if record.procedure == 'index_rent':
                record._check_activate()

    @classmethod
    @ModelView.button
    @Workflow.transition('draft')
    def draft(cls, records):
        # Master data can only be corrected before the first approval
        for record in records:
            used = [a for a in record.adjustments
                if a.state in ('approved', 'declared', 'done')]
            if used:
                raise ValidationError(gettext(
                        'real_estate.msg_index_rent_draft_adjustments',
                        rent_adjustment=record.rec_name,
                        adjustment=used[0].rec_name))

    @classmethod
    @ModelView.button
    @Workflow.transition('closed')
    def close(cls, records):
        for record in records:
            open_ = [a for a in record.adjustments
                if a.state in ('draft', 'approved', 'declared')]
            if open_:
                raise ValidationError(gettext(
                        'real_estate.msg_index_rent_close_open',
                        rent_adjustment=record.rec_name,
                        adjustment=open_[0].rec_name))

    @classmethod
    def delete(cls, records):
        for record in records:
            if record.state != 'draft':
                raise ValidationError(gettext(
                    'real_estate.msg_rent_adjustment_delete_draft',
                    rent_adjustment=record.rec_name))
        super().delete(records)


#**********************************************************************
class Contract(metaclass=PoolMeta):
    __name__ = 'real_estate.contract'

    rent_adjustments = fields.One2Many('real_estate.contract.rent_adjustment',
        'contract', "Rent Adjustments",
        states={
            'readonly': ~Eval('state').in_(['draft', 'running']),
            })
