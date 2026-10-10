'Adjustment run: one process for all subsequent rent adjustment procedures - spezifikation-anpassungslauf.md'
import datetime
from decimal import ROUND_HALF_UP, Decimal

from dateutil.relativedelta import relativedelta

from trytond.i18n import gettext
from trytond.model import ModelSQL, ModelView, Workflow, fields
from trytond.model.exceptions import ValidationError
from trytond.modules.currency.fields import Monetary
from trytond.modules.product import price_digits
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Bool, Eval, PYSONEncoder
from trytond.transaction import Transaction, without_check_access

from .contract_type import ADJUSTMENT_PROCEDURES, RUN_AGREEMENT_PROCEDURES

STATES = [
    ('draft', "Draft"),
    ('selected', "Selected"),
    ('calculated', "Calculated"),
    ('approved', "Approved"),
    ('declared', "Declared"),
    ('ready', "Ready"),
    ('done', "Done"),
    ('cancelled', "Cancelled"),
    ]
OPEN = ('draft', 'approved', 'declared')
# final states of an adjustment in the run
CLOSED = ('done', 'cancelled', 'refused')
# decided consent of the tenant (comparative rent)
CONSENT_DECIDED = ('consented', 'partially_consented', 'refused')


#**********************************************************************
# Procedures (spec 5): the run calls only this interface

class AdjustmentProcedure:
    "Interface of a procedure of the adjustment run"
    code = None
    # an announcement (letter) to the tenant is required
    needs_declaration = True
    # 'none' / 'receipt' (receipt decisive) / 'consent' (consent needed)
    consent = 'receipt'

    @classmethod
    def select(cls, run, terms=None):
        """Create draft adjustments of the run - all candidates of the
        filters or only those of 'terms' (added manually). Returns
        (counts, lines)"""
        raise NotImplementedError

    @classmethod
    def compute(cls, adjustments):
        "Recompute values and checks of draft adjustments"
        Adjustment = Pool().get('real_estate.contract.term.adjustment')
        for adjustment in adjustments:
            Adjustment.write([adjustment], adjustment._compute())

    @classmethod
    def receipt_needed(cls, adjustment):
        "The receipt must be captured before the execution"
        return cls.consent != 'none'

    @classmethod
    def ready(cls, adjustment):
        """The announced adjustment can be executed (or closed): receipt
        captured if needed, consent decided if needed"""
        if cls.receipt_needed(adjustment) and not adjustment.receipt_date:
            return False
        if cls.consent == 'consent':
            return adjustment.consent_state in CONSENT_DECIDED
        return True


class IndexRentProcedure(AdjustmentProcedure):
    "Index rent (§ 557b BGB) - spezifikation-indexmiete.md"
    code = 'index_rent'

    @classmethod
    def select(cls, run, terms=None):
        RentAdjustment = Pool().get('real_estate.contract.rent_adjustment')
        if not run.price_index or not run.index_month:
            raise ValidationError(gettext(
                    'real_estate.msg_adjustment_run_parameters',
                    run=run.rec_name))
        # agreements with an adjustment cancelled in this run are excluded
        skip = {a.rent_adjustment.id for a in run.adjustments
            if a.state == 'cancelled' and a.rent_adjustment}
        agreements = RentAdjustment.index_agreements(run.company,
            run.price_index, list(run.properties), list(run.contracts))
        if terms is not None:
            agreements = [a for a in agreements if a.current_term in terms]
        _, counts, lines = RentAdjustment.index_select(agreements,
            run.index_month, run.declaration_date or run.key_date,
            run.include_decreases,
            values={'run': run.id}, skip=skip if terms is None else ())
        return counts, lines

    @classmethod
    def receipt_needed(cls, adjustment):
        # the receipt is mandatory only with the statutory effective date
        return adjustment.effective_rule == 'statutory'


PROCEDURES = {p.code: p for p in [IndexRentProcedure]}


def procedure_of(code):
    return PROCEDURES.get(code)


#**********************************************************************
class ContractTermAdjustmentRun(Workflow, ModelSQL, ModelView):
    "Contract Term Adjustment Run"
    __name__ = 'real_estate.contract.term.adjustment.run'

    _draft = {'readonly': Eval('state') != 'draft'}
    _index = Eval('procedure') == 'index_rent'
    _comparative = Eval('procedure') == 'comparative_rent'

    run_id = fields.Char("Run ID", readonly=True)
    name = fields.Char("Name")
    procedure = fields.Selection('get_procedures', "Procedure",
        required=True, sort=False, states=_draft)
    company = fields.Many2One('company.company', "Company", required=True,
        states=_draft)
    properties = fields.Many2Many(
        'real_estate.contract.term.adjustment.run-base_object', 'run',
        'property', "Properties", states=_draft,
        domain=[
            ('type', '=', 'property'),
            ('company', '=', Eval('company', -1)),
            ],
        help="Empty = all properties of the company.")
    contracts = fields.Many2Many(
        'real_estate.contract.term.adjustment.run-contract', 'run',
        'contract', "Contracts", states=_draft,
        domain=[('company', '=', Eval('company', -1))],
        help="Empty = all contracts of the properties.")
    key_date = fields.Date("Key Date", required=True, states=_draft,
        help="Key date of the procedure (index rent: date of the "
             "declaration for the preview).")
    declaration_date = fields.Date("Declaration Date",
        states={'readonly': ~Eval('state').in_(
                ['draft', 'selected', 'calculated', 'approved'])},
        help="Planned date of the announcement to the tenants.")
    price_index = fields.Many2One('real_estate.price_index', "Price Index",
        ondelete='RESTRICT',
        states={
            'invisible': ~_index,
            'required': _index & (Eval('state') == 'draft'),
            'readonly': Eval('state') != 'draft',
            })
    index_month = fields.Date("Index Month",
        states={
            'invisible': ~_index,
            'required': _index & (Eval('state') == 'draft'),
            'readonly': Eval('state') != 'draft',
            })
    include_decreases = fields.Boolean("Include Decreases",
        states={
            'invisible': ~_index,
            'readonly': Eval('state') != 'draft',
            })
    min_increase_amount = Monetary("Minimum Increase", currency='currency',
        digits='currency',
        states={
            'invisible': ~_comparative,
            'readonly': ~Eval('state').in_(['draft', 'selected', 'calculated']),
            },
        help="Smaller increases per month are not proposed.")
    min_increase_percent = fields.Numeric("Minimum Increase (%)",
        digits=(16, 2),
        states={
            'invisible': ~_comparative,
            'readonly': ~Eval('state').in_(['draft', 'selected', 'calculated']),
            },
        help="Smaller increases (percent of the current rent) are not "
             "proposed.")
    create_calculations = fields.Boolean("Create Calculations",
        states={
            'invisible': ~_comparative,
            'readonly': Eval('state') != 'draft',
            },
        help="Create (or calculate again) the comparative rent calculation "
             "of every selected apartment on the key date - it has to be "
             "accepted before the run is calculated.")
    currency = fields.Function(fields.Many2One('currency.currency',
            "Currency"), 'on_change_with_currency')
    adjustments = fields.One2Many('real_estate.contract.term.adjustment',
        'run', "Adjustments",
        states={'readonly': ~Eval('state').in_(
                ['selected', 'calculated'])})
    receipts = fields.One2Many('real_estate.contract.term.adjustment',
        'run', "Receipts", filter=[('state', '=', 'declared')],
        states={'readonly': ~Eval('state').in_(['declared', 'ready'])})
    summary = fields.Text("Summary", readonly=True)
    protocol = fields.Text("Protocol", readonly=True)
    progress = fields.Function(fields.Char("Progress"), 'get_progress')
    run_date = fields.Function(fields.Date("Run Date"), 'get_run_date')
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
            ('draft', 'selected'),
            ('selected', 'selected'),
            ('calculated', 'selected'),
            ('selected', 'calculated'),
            ('calculated', 'calculated'),
            ('calculated', 'approved'),
            ('approved', 'declared'),
            ('approved', 'ready'),
            ('declared', 'ready'),
            ('ready', 'declared'),
            ('ready', 'done'),
            ('selected', 'draft'),
            ('calculated', 'draft'),
            ('draft', 'cancelled'),
            ('selected', 'cancelled'),
            ('calculated', 'cancelled'),
            ('approved', 'cancelled'),
            ('declared', 'cancelled'),
            ('ready', 'cancelled'),
            }
        cls._buttons.update({
            'select': {
                'invisible': ~Eval('state').in_(
                    ['draft', 'selected', 'calculated']),
                'depends': ['state'],
                },
            'calculate': {
                'invisible': ~Eval('state').in_(['selected', 'calculated']),
                'depends': ['state'],
                },
            'approve': {
                'invisible': Eval('state') != 'calculated',
                'depends': ['state'],
                },
            'declare': {
                'invisible': Eval('state') != 'approved',
                'depends': ['state'],
                },
            'execute': {
                'invisible': ~Eval('state').in_(['declared', 'ready']),
                'depends': ['state'],
                },
            'reset': {
                'invisible': ~Eval('state').in_(['selected', 'calculated']),
                'depends': ['state'],
                },
            'add_terms': {
                'invisible': ~Eval('state').in_(['selected', 'calculated']),
                'depends': ['state'],
                },
            'open_calculations': {
                'invisible': ((Eval('procedure') != 'comparative_rent')
                    | (Eval('state') == 'draft')),
                'depends': ['procedure', 'state'],
                },
            'cancel': {
                'invisible': Eval('state').in_(['done', 'cancelled']),
                'depends': ['state'],
                },
            })

    @classmethod
    def view_attributes(cls):
        return super().view_attributes() + [
            ('//page[@id="page_workflow"]', 'states', {
                    'invisible': ~Eval('process'),
                    }, ['process']),
            ]

    @staticmethod
    def default_state():
        return 'draft'

    @staticmethod
    def default_company():
        return Transaction().context.get('company')

    @staticmethod
    def default_key_date():
        return Pool().get('ir.date').today()

    @staticmethod
    def default_create_calculations():
        return True

    @fields.depends('company')
    def on_change_with_currency(self, name=None):
        return self.company.currency if self.company else None

    @classmethod
    def default_procedure(cls):
        return 'index_rent'

    @classmethod
    def default_price_index(cls):
        PriceIndex = Pool().get('real_estate.price_index')
        indices = PriceIndex.search([('code', '=', 'VPI-DE')], limit=1)
        return indices[0].id if indices else None

    @fields.depends('price_index', 'index_month')
    def on_change_price_index(self):
        if self.price_index and not self.index_month:
            self.index_month = self.price_index.last_value_month

    @classmethod
    def get_procedures(cls):
        labels = dict(ADJUSTMENT_PROCEDURES)
        return [(k, labels[k]) for k in PROCEDURES]

    @property
    def procedure_class(self):
        return procedure_of(self.procedure)

    def get_rec_name(self, name):
        return ' '.join(filter(None, [self.run_id, self.name]))

    @classmethod
    def search_rec_name(cls, name, clause):
        return ['OR',
            ('run_id',) + tuple(clause[1:]),
            ('name',) + tuple(clause[1:]),
            ]

    def get_run_date(self, name):
        return self.create_date.date() if self.create_date else None

    def get_progress(self, name):
        states = [a.state for a in self.adjustments]
        labels = dict(Pool().get('real_estate.contract.term.adjustment')
            .fields_get(['state'])['state']['selection'])
        return ', '.join(f'{labels.get(s, s)} {states.count(s)}'
            for s in ['draft', 'approved', 'declared', 'done', 'refused',
                'cancelled']
            if s in states)

    @classmethod
    def get_process(cls, runs, name):
        Process = Pool().get('real_estate.process')
        result = {r.id: None for r in runs}
        for process in Process.search([
                    ('resource', 'in', [str(r) for r in runs]),
                    ], order=[('start_date', 'ASC'), ('id', 'ASC')]):
            result[process.resource.id] = process.id
        return result

    def get_process_tasks(self, name):
        return [t.id for t in self.process.tasks] if self.process else []

    @classmethod
    def set_process_tasks(cls, runs, name, value):
        pass

    @classmethod
    def create(cls, vlist):
        pool = Pool()
        ModelData = pool.get('ir.model.data')
        Sequence = pool.get('ir.sequence')
        vlist = [v.copy() for v in vlist]
        with without_check_access():
            sequence = Sequence(ModelData.get_id('real_estate',
                    'sequence_adjustment_run'))
            for values in vlist:
                if not values.get('run_id'):
                    values['run_id'] = sequence.get()
        return super().create(vlist)

    @classmethod
    def delete(cls, runs):
        for run in runs:
            if run.state not in ('draft', 'cancelled'):
                raise ValidationError(gettext(
                        'real_estate.msg_adjustment_run_delete',
                        run=run.rec_name))
        super().delete(runs)

    def _log(self, message_id, lines=(), **kwargs):
        "Append a dated block to the protocol of the run"
        stamp = datetime.datetime.now().strftime('%d.%m.%Y %H:%M')
        block = [f'{stamp} {gettext("real_estate." + message_id, **kwargs)}']
        block.extend(lines)
        return '\n'.join(filter(None, [self.protocol] + block))

    @classmethod
    def _check_processes(cls, runs):
        Process = Pool().get('real_estate.process')
        processes = [r.process for r in runs
            if r.process and r.process.state == 'running']
        if processes:
            Process.check(processes)

    @classmethod
    def _start_processes(cls, runs):
        "Start the process of the procedure's template (spec 7)"
        pool = Pool()
        Template = pool.get('real_estate.process.template')
        Process = pool.get('real_estate.process')
        Date = pool.get('ir.date')
        for run in runs:
            if run.process:
                continue
            templates = Template.search([
                    ('code', '=', f'adjustment_run_{run.procedure}'),
                    ('model', '=', cls.__name__),
                    ], limit=1)
            if templates:
                Process.start(templates[0], run, Date.today())

    # ------------------------------------------------------------------
    # Workflow (spec 4.2)

    @classmethod
    @ModelView.button
    def select(cls, runs):
        """Select the candidates of the procedure: draft adjustments of the
        run - existing ones stay (manual changes, exclusions)"""
        for run in runs:
            if run.state not in ('draft', 'selected', 'calculated'):
                continue
            counts, lines = run.procedure_class.select(run)
            summary = gettext('real_estate.msg_adjustment_run_selected',
                **{k: counts.get(k, 0) for k in [
                        'agreements', 'created', 'excluded']})
            cls.write([run], {
                    'state': 'selected',
                    'summary': summary,
                    'protocol': run._log('msg_adjustment_run_selected',
                        lines, **{k: counts.get(k, 0) for k in [
                                'agreements', 'created', 'excluded']}),
                    })
        runs = cls.browse([r.id for r in runs])
        cls._start_processes(runs)
        cls._check_processes(runs)

    @classmethod
    @ModelView.button
    def calculate(cls, runs):
        "Recompute the values and checks of the draft adjustments"
        runs = [r for r in runs if r.state in ('selected', 'calculated')]
        for run in runs:
            drafts = [a for a in run.adjustments if a.state == 'draft']
            run.procedure_class.compute(drafts)
            drafts = [a.__class__(a.id) for a in drafts]
            count = {s: len([a for a in drafts if a.check_state == s])
                for s in ('ok', 'warning', 'error')}
            cls.write([run], {
                    'state': 'calculated',
                    'protocol': run._log(
                        'msg_adjustment_run_calculated', **count),
                    })
        cls._check_processes(cls.browse([r.id for r in runs]))

    @classmethod
    @ModelView.button
    def approve(cls, runs):
        """Approve the drafts without errors (a warning needs a reason);
        the others are cancelled with a protocol line"""
        Adjustment = Pool().get('real_estate.contract.term.adjustment')
        runs = [r for r in runs if r.state == 'calculated']
        for run in runs:
            drafts = [a for a in run.adjustments if a.state == 'draft']
            ok, rejected, lines = [], [], []
            for adjustment in drafts:
                if adjustment.check_state == 'error':
                    rejected.append(adjustment)
                    lines.append(gettext(
                            'real_estate.msg_adjustment_run_line_error',
                            adjustment=adjustment.rec_name))
                elif (adjustment.check_state == 'warning'
                        and not (adjustment.approval_reason or '').strip()):
                    rejected.append(adjustment)
                    lines.append(gettext(
                            'real_estate.msg_adjustment_run_line_reason',
                            adjustment=adjustment.rec_name))
                else:
                    ok.append(adjustment)
            if not ok:
                raise ValidationError(gettext(
                        'real_estate.msg_adjustment_run_nothing_approved',
                        run=run.rec_name, protocol='\n'.join(lines)))
            with Transaction().set_context(_skip_warnings=True):
                Adjustment.approve(ok)
                if rejected:
                    Adjustment.cancel(rejected)
            cls.write([run], {
                    'state': 'approved',
                    'protocol': run._log('msg_adjustment_run_approved', lines,
                        approved=len(ok), rejected=len(rejected)),
                    })
        cls._check_processes(cls.browse([r.id for r in runs]))

    @classmethod
    @ModelView.button
    def declare(cls, runs):
        """Announcement: letters of the approved adjustments (procedure
        with declaration), else directly ready for the execution"""
        Adjustment = Pool().get('real_estate.contract.term.adjustment')
        for run in runs:
            if run.state != 'approved':
                continue
            approved = [a for a in run.adjustments if a.state == 'approved']
            if not run.procedure_class.needs_declaration:
                cls._set_state([run], 'ready')
                continue
            date = run.declaration_date or Pool().get('ir.date').today()
            Adjustment.write([a for a in approved
                    if not a.declaration_date], {'declaration_date': date})
            Adjustment.declare(Adjustment.browse([a.id for a in approved]))
            cls._set_state([run], 'declared')
            cls.write([run], {'protocol': run._log(
                        'msg_adjustment_run_declared',
                        count=len(approved))})
        cls.update_state(cls.browse([r.id for r in runs]))
        cls._check_processes(cls.browse([r.id for r in runs]))

    @classmethod
    @ModelView.button
    def execute(cls, runs):
        "Execute the adjustments whose receipt is captured (if needed)"
        Adjustment = Pool().get('real_estate.contract.term.adjustment')
        for run in runs:
            if run.state not in ('declared', 'ready'):
                continue
            procedure = run.procedure_class
            todo = [a for a in run.adjustments if a.state == 'declared'
                and procedure.ready(a)]
            if not todo:
                raise ValidationError(gettext(
                        'real_estate.msg_adjustment_run_nothing_to_execute',
                        run=run.rec_name))
            refused = [a for a in todo if a.consent_state == 'refused']
            if refused:
                Adjustment.refuse(refused)
            todo = [a for a in todo if a not in refused]
            if todo:
                Adjustment.execute(todo)
            todo += refused
            cls.write([run], {'protocol': run._log(
                        'msg_adjustment_run_executed', count=len(todo))})
        cls.update_state(cls.browse([r.id for r in runs]))
        cls._check_processes(cls.browse([r.id for r in runs]))

    @classmethod
    @ModelView.button
    def reset(cls, runs):
        "Back to draft: the adjustments of the run are deleted"
        Adjustment = Pool().get('real_estate.contract.term.adjustment')
        for run in runs:
            if run.state not in ('selected', 'calculated'):
                continue
            Adjustment.delete([a for a in run.adjustments
                    if a.state in ('draft', 'cancelled')])
            cls.write([run], {
                    'state': 'draft',
                    'protocol': run._log('msg_adjustment_run_reset'),
                    })

    @classmethod
    @ModelView.button
    def cancel(cls, runs):
        "Cancel the open adjustments of the run"
        pool = Pool()
        Adjustment = pool.get('real_estate.contract.term.adjustment')
        Process = pool.get('real_estate.process')
        runs = [r for r in runs if r.state not in ('done', 'cancelled')]
        # State first: the run must not follow its adjustments to 'done'
        cls._set_state(runs, 'cancelled')
        for run in runs:
            open_ = [a for a in run.adjustments if a.state in OPEN]
            if open_:
                Adjustment.cancel(open_)
            if run.process and run.process.state == 'running':
                Process.cancel([run.process])

    @classmethod
    @ModelView.button_action('real_estate.wizard_adjustment_run_add')
    def add_terms(cls, runs):
        pass

    @classmethod
    @ModelView.button
    def open_calculations(cls, runs):
        """The comparative rent calculations of the run's adjustments - to
        accept them together before 'Calculate'"""
        pool = Pool()
        Action = pool.get('ir.action')
        ModelData = pool.get('ir.model.data')
        Calculation = pool.get('real_estate.rent_survey.calculation')
        objects = {a.calculation_object.id for r in runs
            for a in r.adjustments if a.calculation_object}
        calculations = Calculation.search([
                ('base_object', 'in', list(objects)),
                ('key_date', 'in', list({r.key_date for r in runs})),
                ])
        action = Action(ModelData.get_id('real_estate',
                'act_rent_survey_calculation')).get_action_value()
        action['pyson_domain'] = PYSONEncoder().encode(
            [('id', 'in', [c.id for c in calculations])])
        # open the records themselves, not the first tab of the action
        action['domains'] = []
        action['name'] += f' ({", ".join(r.rec_name for r in runs)})'
        return action

    @classmethod
    def _set_state(cls, runs, state):
        if runs:
            cls.write(runs, {'state': state})

    @classmethod
    def update_state(cls, runs):
        """Follow-up states: 'ready' once every announced adjustment has
        its receipt (if needed), 'done' once no adjustment is open"""
        for run in runs:
            if run.state not in ('declared', 'ready'):
                continue
            procedure = run.procedure_class
            if all(a.state in CLOSED for a in run.adjustments):
                cls._set_state([run], 'done')
                continue
            ready = all(procedure.ready(a)
                for a in run.adjustments if a.state == 'declared')
            if run.state == 'declared' and ready:
                cls._set_state([run], 'ready')
            elif run.state == 'ready' and not ready:
                cls._set_state([run], 'declared')


class ContractTermAdjustmentRunProperty(ModelSQL):
    "Adjustment Run - Property"
    __name__ = 'real_estate.contract.term.adjustment.run-base_object'

    run = fields.Many2One('real_estate.contract.term.adjustment.run', "Run",
        required=True, ondelete='CASCADE')
    property = fields.Many2One('real_estate.base_object', "Property",
        required=True, ondelete='CASCADE')


class ContractTermAdjustmentRunContract(ModelSQL):
    "Adjustment Run - Contract"
    __name__ = 'real_estate.contract.term.adjustment.run-contract'

    run = fields.Many2One('real_estate.contract.term.adjustment.run', "Run",
        required=True, ondelete='CASCADE')
    contract = fields.Many2One('real_estate.contract', "Contract",
        required=True, ondelete='CASCADE')


#**********************************************************************
class ContractTermAdjustment(metaclass=PoolMeta):
    __name__ = 'real_estate.contract.term.adjustment'

    _run = Eval('procedure').in_(RUN_AGREEMENT_PROCEDURES)
    _consent = Eval('procedure') == 'comparative_rent'
    _draft = {
        'invisible': ~_run,
        'readonly': Eval('state') != 'draft',
        }

    run = fields.Many2One('real_estate.contract.term.adjustment.run', "Run",
        readonly=True, ondelete='SET NULL')
    approval_reason = fields.Text("Approval Reason",
        states={'readonly': Eval('state') != 'draft'},
        help="Required for the approval in the run with a warning.")
    computed_amount = Monetary("Computed Amount", currency='currency',
        digits='currency', readonly=True, states={'invisible': ~_run},
        help="New rent per period as computed by the procedure.")
    manual_amount = Monetary("Manual Amount", currency='currency',
        digits='currency', states=_draft,
        help="New rent entered manually instead of the computed amount - "
             "between the current and the computed amount, with a "
             "reason.")
    override_reason = fields.Text("Reason for Manual Amount",
        states={
            'invisible': ~_run,
            'readonly': Eval('state') != 'draft',
            'required': Bool(Eval('manual_amount')),
            })
    consent_state = fields.Selection([
            (None, ''),
            ('pending', "Pending"),
            ('consented', "Consented"),
            ('partially_consented', "Partially Consented"),
            ('refused', "Refused"),
            ], "Consent", sort=False,
        states={
            'invisible': ~_consent,
            'readonly': (Eval('state') != 'declared')
                | ~Eval('receipt_date'),
            },
        help="Decision of the tenant on the request for consent (§ 558b "
             "BGB) - to be captured after the receipt.")
    consent_date = fields.Date("Consent Date",
        states={
            'invisible': ~_consent,
            'readonly': Eval('state') != 'declared',
            'required': Eval('consent_state').in_(
                ['consented', 'partially_consented', 'refused']),
            })
    consented_amount = Monetary("Consented Amount", currency='currency',
        digits='currency',
        states={
            'invisible': Eval('consent_state') != 'partially_consented',
            'readonly': Eval('state') != 'declared',
            'required': Eval('consent_state') == 'partially_consented',
            },
        help="New rent the tenant consented to (partial consent).")
    consent_deadline = fields.Function(fields.Date("Consent until",
            states={'invisible': ~_consent},
            help="End of the period for consideration: end of the second "
                 "calendar month after the receipt (§ 558b para. 2 BGB)."),
        'get_deadlines')
    lawsuit_deadline = fields.Function(fields.Date("Lawsuit until",
            states={'invisible': ~_consent},
            help="End of the period for an action for consent: three months "
                 "after the period for consideration (§ 558b para. 2 BGB)."),
        'get_deadlines')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls.state.selection.append(('refused', "Refused"))
        cls._transitions |= {('declared', 'refused')}

    def get_deadlines(self, name):
        if self.procedure != 'comparative_rent' or not self.receipt_date:
            return None
        consent = (self.receipt_date.replace(day=1)
            + relativedelta(months=3) - datetime.timedelta(days=1))
        if name == 'consent_deadline':
            return consent
        return consent + relativedelta(months=3)

    @classmethod
    def validate_fields(cls, records, field_names):
        super().validate_fields(records, field_names)
        if field_names & {'manual_amount', 'override_reason'}:
            for record in records:
                if (record.manual_amount is not None
                        and not (record.override_reason or '').strip()):
                    raise ValidationError(gettext(
                            'real_estate.msg_adjustment_manual_reason',
                            adjustment=record.rec_name))
        if field_names & {'consent_state', 'consented_amount'}:
            for record in records:
                if record.consent_state != 'partially_consented':
                    continue
                amount = record.consented_amount
                if (amount is None or amount <= (record.amount_old or 0)
                        or amount >= (record.planned_amount or 0)):
                    raise ValidationError(gettext(
                            'real_estate.msg_adjustment_consented_amount',
                            adjustment=record.rec_name,
                            old=record.amount_old,
                            new=record.planned_amount))

    def _compute(self):
        "Values and checks of the procedure (draft adjustment)"
        if self.procedure == 'index_rent':
            return self._index_compute()
        if self.procedure == 'comparative_rent':
            return self._comparative_compute()
        return {}

    def _effective_date(self):
        "Effective date from the declaration resp. receipt date"
        agreement = self.rent_adjustment
        if self.procedure == 'index_rent':
            return agreement.planned_valid_from(self.index_month_new,
                self.declaration_date, self.receipt_date)
        if self.procedure == 'comparative_rent':
            return agreement.comparative_valid_from(self.declaration_date,
                self.receipt_date)
        return self.planned_valid_from

    @classmethod
    def _finish_compute(cls, values, findings, manual_amount=None,
            amount_old=None):
        """Common end of a computation: the computed amount is kept, a
        manual amount (between the current and the computed amount)
        replaces the new amount; check state from the findings"""
        lang = Pool().get('ir.lang').get()
        findings = list(findings)
        computed = values.get('planned_amount')
        values['computed_amount'] = computed
        if manual_amount is not None and computed is not None:
            low, high = sorted([amount_old or computed, computed])

            def num(value):
                return lang.format_number(value, 2)
            if not low <= manual_amount <= high:
                findings.append(('A02', 'error', gettext(
                            'real_estate.msg_adjustment_manual_range',
                            amount=num(manual_amount), low=num(low),
                            high=num(high))))
            else:
                findings.append(('A01', 'ok', gettext(
                            'real_estate.msg_adjustment_manual',
                            amount=num(manual_amount),
                            computed=num(computed))))
            values['planned_amount'] = manual_amount
            quantity = values.get('planned_quantity')
            if quantity:
                values['planned_unit_price'] = (
                    manual_amount / Decimal(str(quantity))).quantize(
                    Decimal(10) ** -price_digits[1], rounding=ROUND_HALF_UP)
        values.update(cls._check_values(findings))
        return values

    @classmethod
    def write(cls, *args):
        Task = Pool().get('real_estate.task')
        actions = iter(args)
        args = list(args)
        receipts, decided, recompute = [], [], []
        for records, values in zip(actions, actions):
            if (values.get('receipt_date')
                    and 'consent_state' not in values):
                receipts.extend(r for r in records
                    if r.procedure == 'comparative_rent'
                    and not r.consent_state)
            if values.get('consent_state') in CONSENT_DECIDED:
                decided.extend(records)
            if {'manual_amount', 'override_reason'} & set(values):
                recompute.extend(r for r in records if r.state == 'draft')
        super().write(*args)
        if receipts:
            super().write(receipts, {'consent_state': 'pending'})
            for record in cls.browse(receipts):
                Task.create_for(record, 'comparative_consent',
                    record.consent_deadline)
        for record in cls.browse(decided):
            Task.close_for(record, 'comparative_consent')
            if record.consent_state == 'refused':
                record._lawsuit_task()
        for record in cls.browse(recompute):
            super().write([record], record._compute())
        actions = iter(args)
        runs = set()
        for records, values in zip(actions, actions):
            if {'receipt_date', 'state', 'consent_state'} & set(values):
                runs |= {r.run.id for r in records if r.run}
        if runs:
            Run = Pool().get('real_estate.contract.term.adjustment.run')
            Run.update_state(Run.browse(list(runs)))

    def _lawsuit_task(self):
        "Task: check the action for consent before the lawsuit deadline"
        Task = Pool().get('real_estate.task')
        if self.lawsuit_deadline:
            Task.create_for(self, 'comparative_lawsuit',
                self.lawsuit_deadline - datetime.timedelta(days=14))

    @classmethod
    @Workflow.transition('refused')
    def refuse(cls, records):
        """The tenant refused the consent: the adjustment ends without a
        new term, the agreement stays active (next run after the lock of
        one year)"""
        Task = Pool().get('real_estate.task')
        for record in records:
            Task.close_for(record, 'comparative_consent')
            record._lawsuit_task()
            if record.contract:
                record.contract.add_log('comparative_rent', gettext(
                        'real_estate.msg_comparative_log_refused',
                        adjustment=record.rec_name,
                        amount=record.planned_amount))


#**********************************************************************
class Process(metaclass=PoolMeta):
    __name__ = 'real_estate.process'

    def _run_state_in(self, states):
        resource = self.resource
        return bool(resource
            and resource.__name__ == 'real_estate.contract.term.adjustment.run'
            and resource.state in states)

    def _step_done_run_selected(self):
        return self._run_state_in(['selected', 'calculated', 'approved',
                'declared', 'ready', 'done'])

    def _step_done_run_calculated(self):
        return self._run_state_in(['calculated', 'approved', 'declared',
                'ready', 'done'])

    def _step_done_run_approved(self):
        return self._run_state_in(['approved', 'declared', 'ready', 'done'])

    def _step_done_run_declared(self):
        return self._run_state_in(['declared', 'ready', 'done'])

    def _step_done_run_ready(self):
        return self._run_state_in(['ready', 'done'])

    def _step_done_run_done(self):
        return self._run_state_in(['done'])
