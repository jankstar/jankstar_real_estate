'Index Rent (§ 557b BGB) - adjustments and adjustment run'
import datetime
from decimal import ROUND_HALF_UP, Decimal

from dateutil.relativedelta import relativedelta

from trytond.exceptions import UserWarning
from trytond.i18n import gettext
from trytond.model import ModelSQL, ModelView, Workflow, fields
from trytond.model.exceptions import ValidationError
from trytond.modules.currency.fields import Monetary
from trytond.modules.product import price_digits
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Eval, If
from trytond.transaction import Transaction

from .contract_type import ADJUSTMENT_PROCEDURES, RUN_AGREEMENT_PROCEDURES

# Severity of the check protocol, ordered
CHECK_LEVELS = ['ok', 'warning', 'error']


class IndexAdjustmentWarning(UserWarning):
    pass


# Declaration (letter) of the procedures of the adjustment run
LETTERS = {
    'index_rent': 'real_estate.contract.index_adjustment.letter',
    'comparative_rent': 'real_estate.contract.comparative_rent.letter',
    }


def _first_of_month(date):
    return date.replace(day=1)


#**********************************************************************
class ContractRentAdjustment(metaclass=PoolMeta):
    __name__ = 'real_estate.contract.rent_adjustment'

    def _receipt_days(self):
        company = self.contract.company if self.contract else None
        re_accounting = company.re_accounting if company else None
        if re_accounting and re_accounting.receipt_days is not None:
            return re_accounting.receipt_days
        return 3

    def _declaration_deadline(self):
        """Latest declaration (send) date for an adjustment effective on
        the next possible date (statutory rule): the declaration has to be
        received in the month before last, minus the receipt days of the
        real estate accounting - the follow-up date for the adjustment
        run. None for a commercial contract month rule."""
        if (self.procedure != 'index_rent' or self.state != 'active'
                or self.effective_rule != 'statutory'
                or not self.next_possible_date):
            return None
        target = self.next_possible_date
        if target.day != 1:
            target = _first_of_month(target) + relativedelta(months=1)
        receipt_deadline = (target - relativedelta(months=1)
            - datetime.timedelta(days=1))
        return receipt_deadline - datetime.timedelta(
            days=self._receipt_days())

    def planned_valid_from(self, index_month, declaration_date=None,
            receipt_date=None):
        """Effective date of an adjustment (spec 6.4). Statutory: first day
        of the month after next following the receipt - before the receipt
        is confirmed a preview from the declaration date + receipt days.
        Contract month (commercial): index month + offset months."""
        if self.effective_rule == 'contract_month':
            if not index_month:
                return None
            return _first_of_month(index_month) + relativedelta(
                months=self.effective_offset_months or 0)
        received = receipt_date
        if not received and declaration_date:
            received = declaration_date + datetime.timedelta(
                days=self._receipt_days())
        if not received:
            return None
        return _first_of_month(received) + relativedelta(months=2)

    def compute_index_adjustment(self, index_month, declaration_date=None,
            receipt_date=None):
        """Calculate an index adjustment (spec 6.2, 6.3) and its checks
        (spec 7). Returns (values, findings, flags): the field values of
        the adjustment, a list of (code, level, message) and the flags
        'threshold_reached' and 'decrease'."""
        pool = Pool()
        CapRule = pool.get('real_estate.index_cap_rule')
        index = self.price_index
        term = self.current_term
        contract = self.contract
        residential = self._residential
        findings = []

        def add(code, level, message_id, **kwargs):
            findings.append((code, level, gettext(
                        'real_estate.' + message_id, **kwargs)))

        month_old = self.current_index_month
        month_new = _first_of_month(index_month) if index_month else None
        values = {
            'rent_adjustment': self.id,
            'term_old': term.id,
            'index_month_old': month_old,
            'index_month_new': month_new,
            'index_base_year': index.base_year,
            'planned_quantity': term.quantity,
            'planned_valid_from': self.planned_valid_from(
                month_new, declaration_date, receipt_date),
            }
        flags = {'threshold_reached': False, 'decrease': False}

        # I05: reference and new value final in the current base year
        old = index.get_value(month_old) if month_old else None
        new = index.get_value(month_new) if month_new else None
        values['index_value_old'] = old.value if old else None
        values['index_value_new'] = new.value if new else None
        if not old or not new or month_new <= month_old:
            add('I05', 'error', 'msg_index_adjustment_values',
                index=index.rec_name, base_year=index.base_year,
                month_old=month_old.strftime('%m.%Y') if month_old else '-',
                month_new=month_new.strftime('%m.%Y') if month_new else '-')
            return values, findings, flags

        ratio = new.value / old.value
        change = (ratio - 1) * 100
        values['index_change_percent'] = change.quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP)

        # Contractual threshold on the uncapped change
        if self.threshold_type == 'percent':
            reached = abs(change) >= self.threshold_value
        elif self.threshold_type == 'points':
            reached = abs(new.value - old.value) >= self.threshold_value
        else:
            reached = ratio != 1
        flags['threshold_reached'] = reached
        if not reached:
            add('S01', 'error', 'msg_index_adjustment_threshold',
                change=values['index_change_percent'])

        # Cap ("Mietrecht II", preliminary) on the planned receipt date
        applied = change
        values['cap_rule'] = None
        if self.apply_cap == 'auto' and change > 0:
            received = receipt_date or (declaration_date
                + datetime.timedelta(days=self._receipt_days())
                if declaration_date else None)
            rule = CapRule.find(received, contract.property)
            if rule:
                def value_of(month):
                    value = index.get_value(month)
                    if not value:
                        raise KeyError(month)
                    return value.value
                try:
                    applied = rule.apply(value_of, month_old, month_new)
                    values['cap_rule'] = rule.id
                except KeyError as e:
                    add('I05', 'error', 'msg_index_adjustment_cap_value',
                        month=e.args[0].strftime('%m.%Y'))
        values['applied_change_percent'] = applied.quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP)

        # Amounts: the new amount per period is decisive (cent, half up)
        cent = Decimal(10) ** -(contract.currency.digits
            if contract.currency else 2)
        quantity = Decimal(str(term.quantity or 0))
        amount_old = (quantity * (term.unit_price or Decimal(0))).quantize(
            cent, rounding=ROUND_HALF_UP)
        factor = ratio if values['cap_rule'] is None else 1 + applied / 100
        amount_new = (amount_old * factor).quantize(
            cent, rounding=ROUND_HALF_UP)
        values['planned_amount'] = amount_new
        unit_price = None
        if quantity:
            unit_price = (amount_new / quantity).quantize(
                Decimal(10) ** -price_digits[1], rounding=ROUND_HALF_UP)
        values['planned_unit_price'] = unit_price
        decrease = amount_new < amount_old
        flags['decrease'] = decrease
        values['direction'] = 'decrease' if decrease else 'increase'

        # I08: rounding difference with a quantity other than 1
        if (quantity and quantity != 1 and unit_price is not None
                and (quantity * unit_price).quantize(
                    cent, rounding=ROUND_HALF_UP) != amount_new):
            add('I08', 'warning', 'msg_index_adjustment_rounding',
                amount=amount_new)
        # I13: decrease
        if decrease:
            add('I13', 'warning', 'msg_index_adjustment_decrease')

        valid_from = values['planned_valid_from']
        # I04: rent unchanged for at least 12 months (§ 557b para. 2 BGB)
        if (valid_from and self.next_possible_date
                and valid_from < self.next_possible_date):
            add('I04', 'error' if residential else 'warning',
                'msg_index_adjustment_lock_period',
                valid_from=valid_from.strftime('%d.%m.%Y'),
                next_date=self.next_possible_date.strftime('%d.%m.%Y'))
        # I06: running contract, effective date not after its end
        if contract.state != 'running':
            add('I06', 'error', 'msg_index_adjustment_contract_state',
                contract=contract.rec_name)
        end = contract.get_effective_end_date()
        if valid_from and end and valid_from > end:
            add('I06', 'error', 'msg_index_adjustment_contract_end',
                valid_from=valid_from.strftime('%d.%m.%Y'),
                end=end.strftime('%d.%m.%Y'))
        # I09: current term not booked beyond the effective date
        booked_to = term.get_booked_to()
        if valid_from and booked_to and booked_to >= valid_from:
            add('I09', 'error', 'msg_index_adjustment_booked',
                term=term.rec_name.strip(),
                booked_to=booked_to.strftime('%d.%m.%Y'),
                valid_from=valid_from.strftime('%d.%m.%Y'))
        # I14: current term not locked by a graduated rent
        if term.graduated_locked:
            add('I14', 'error', 'msg_index_adjustment_locked',
                term=term.rec_name.strip())
        return values, findings, flags

    @classmethod
    def index_select(cls, agreements, index_month, declaration_date,
            include_decreases=False, values=None, skip=()):
        """Draft index adjustments for the agreements (spec 8, Anpassungslauf
        9): no open adjustment (I07), lock period (I04), new value (I05),
        threshold, decreases. 'values' are added to every new adjustment
        (run), agreements in 'skip' are not considered (excluded in the
        run). Returns (adjustments, counts, protocol lines)."""
        Adjustment = Pool().get('real_estate.contract.term.adjustment')
        counts = dict.fromkeys(['agreements', 'created', 'open',
                'lock_period', 'threshold', 'decrease', 'no_value', 'error',
                'excluded'], 0)
        lines, created = [], []

        def protocol(agreement, message_id, findings=(), **kwargs):
            lines.append(gettext('real_estate.' + message_id,
                    rent_adjustment=agreement.rec_name, **kwargs))
            lines.extend(f'    {code}: {text}' for code, _, text in findings)

        for agreement in agreements:
            counts['agreements'] += 1
            if agreement.id in skip:
                counts['excluded'] += 1
                protocol(agreement, 'msg_adjustment_run_line_excluded')
                continue
            open_ = [a for a in agreement.adjustments
                if a.state in ('draft', 'approved', 'declared')]
            if open_:
                counts['open'] += 1
                protocol(agreement, 'msg_index_run_line_open',
                    adjustment=open_[0].rec_name)
                continue
            new_values, findings, flags = agreement.compute_index_adjustment(
                index_month, declaration_date)
            codes = {code for code, _, _ in findings}
            change = new_values.get('applied_change_percent')
            valid_from = new_values['planned_valid_from']
            valid_from_text = (valid_from.strftime('%d.%m.%Y')
                if valid_from else '-')
            if 'I05' in codes:
                counts['no_value'] += 1
                protocol(agreement, 'msg_index_run_line_no_value', findings)
                continue
            if (agreement._residential and valid_from
                    and agreement.next_possible_date
                    and valid_from < agreement.next_possible_date):
                counts['lock_period'] += 1
                protocol(agreement, 'msg_index_run_line_lock_period',
                    findings, valid_from=valid_from_text)
                continue
            if not flags['threshold_reached']:
                counts['threshold'] += 1
                protocol(agreement, 'msg_index_run_line_threshold',
                    findings, change=change)
                continue
            if flags['decrease'] and not include_decreases:
                counts['decrease'] += 1
                protocol(agreement, 'msg_index_run_line_decrease',
                    findings, change=change)
                continue
            new_values = Adjustment._finish_compute(new_values, findings)
            new_values.update(dict(values or {},
                    declaration_date=declaration_date))
            adjustment, = Adjustment.create([new_values])
            created.append(adjustment)
            counts['created'] += 1
            message_id = 'msg_index_run_line_created'
            if adjustment.check_state == 'error':
                counts['error'] += 1
                message_id = 'msg_index_run_line_created_error'
            protocol(agreement, message_id, findings, change=change,
                amount=new_values.get('planned_amount'),
                valid_from=valid_from_text)
        if not counts['agreements']:
            lines.append(gettext('real_estate.msg_index_run_line_none'))
        return created, counts, lines

    @classmethod
    def index_agreements(cls, company, price_index, properties=None,
            contracts=None):
        "Active index agreements of the series (filters of the run)"
        domain = [
            ('procedure', '=', 'index_rent'),
            ('state', '=', 'active'),
            ('price_index', '=', price_index.id),
            ('contract.company', '=', company.id),
            ]
        if properties:
            domain.append(('contract.property', 'in',
                    [p.id for p in properties]))
        if contracts:
            domain.append(('contract', 'in', [c.id for c in contracts]))
        return cls.search(domain)


#**********************************************************************
class ContractTermAdjustment(metaclass=PoolMeta):
    __name__ = 'real_estate.contract.term.adjustment'

    _index = Eval('procedure') == 'index_rent'
    _states_index = {'invisible': ~_index, 'readonly': True}
    # fields of every procedure of the adjustment run with an agreement
    _run = Eval('procedure').in_(RUN_AGREEMENT_PROCEDURES)
    _states_run = {'invisible': ~_run, 'readonly': True}

    rent_adjustment = fields.Many2One(
        'real_estate.contract.rent_adjustment', "Rent Adjustment",
        ondelete='CASCADE', readonly=True,
        help="Agreement of the adjustment - required for index and "
             "comparative rents.")
    procedure = fields.Function(fields.Selection(
            [(None, '')] + ADJUSTMENT_PROCEDURES, "Procedure"),
        'on_change_with_procedure', searcher='search_procedure')
    effective_rule = fields.Function(fields.Char("Effective Date Rule"),
        'on_change_with_effective_rule')
    index_month_old = fields.Date("Index Month (Reference)",
        states=_states_index)
    index_value_old = fields.Numeric("Index Value (Reference)",
        digits=(16, 1), states=_states_index)
    index_month_new = fields.Date("Index Month (New)", states=_states_index)
    index_value_new = fields.Numeric("Index Value (New)", digits=(16, 1),
        states=_states_index)
    index_base_year = fields.Integer("Base Year", states=_states_index)
    index_change_percent = fields.Numeric("Index Change (%)",
        digits=(16, 2), states=_states_index)
    applied_change_percent = fields.Numeric("Applied Change (%)",
        digits=(16, 2), states=_states_index,
        help="Change counted after the cap rule (else the index change).")
    cap_rule = fields.Many2One('real_estate.index_cap_rule', "Cap Rule",
        ondelete='RESTRICT', states=_states_index)
    direction = fields.Selection([
            (None, ''),
            ('increase', "Increase"),
            ('decrease', "Decrease"),
            ], "Direction", states=_states_run)
    planned_quantity = fields.Numeric("Quantity", digits=(16, 4),
        states=_states_run)
    planned_amount = Monetary("New Amount", currency='currency',
        digits='currency', states=_states_run,
        help="New rent per period - the decisive amount.")
    planned_unit_price = Monetary("New Unit Price", currency='currency',
        digits=price_digits, states=_states_run)
    difference_amount = fields.Function(Monetary("Difference",
            currency='currency', digits='currency',
            states={'invisible': ~_run}),
        'get_difference_amount')
    declaration_date = fields.Date("Declaration Date",
        states={
            'invisible': ~_run,
            'readonly': ~Eval('state').in_(['draft', 'approved']),
            },
        help="Date of the declaration to the tenant - before the receipt "
             "is confirmed it is the basis of the effective date preview.")
    dispatch_method = fields.Selection([
            (None, ''),
            ('letter', "Letter"),
            ('registered_letter', "Registered Letter"),
            ('hand_delivery', "Hand Delivery"),
            ('email', "E-Mail"),
            ('other', "Other"),
            ], "Dispatch Method",
        states={
            'invisible': ~_run,
            'readonly': ~Eval('state').in_(['draft', 'approved', 'declared']),
            },
        help="How the declaration was sent (proof of receipt) - a "
             "registered letter or a messenger is recommended.")
    receipt_date = fields.Date("Receipt Date",
        states={
            'invisible': ~_run,
            'readonly': Eval('state') != 'declared',
            },
        help="Receipt of the declaration by the tenant (with several "
             "tenants: receipt by the last one) - always to be confirmed "
             "manually.")
    planned_valid_from = fields.Date("Effective from", states=_states_run,
        help="Effective date of the new rent - calculated from the receipt "
             "date, before that a preview from the declaration date.")
    check_state = fields.Selection([
            (None, ''),
            ('ok', "OK"),
            ('warning', "Warning"),
            ('error', "Error"),
            ], "Check", readonly=True)
    check_message = fields.Text("Check Protocol", readonly=True)
    letter = fields.Many2One('ir.attachment', "Declaration (Document)",
        readonly=True, ondelete='SET NULL',
        states={'invisible': ~_run},
        help="Archived original of the declaration, created by 'Declare'.")
    executed_by = fields.Many2One('company.employee', "Executed by",
        readonly=True, states={'invisible': ~_run})
    executed_date = fields.Date("Executed on", readonly=True,
        states={'invisible': ~_run})

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._order = [
            ('planned_valid_from', 'DESC NULLS FIRST'),
            ('id', 'DESC'),
            ]
        cls._transitions |= {
            ('draft', 'approved'),
            ('draft', 'cancelled'),
            ('approved', 'cancelled'),
            ('declared', 'cancelled'),
            ('cancelled', 'draft'),
            ('approved', 'declared'),
            ('declared', 'done'),
            }
        run = Eval('procedure').in_(RUN_AGREEMENT_PROCEDURES)
        # Fields of the operating cost / free adjustment procedures are
        # hidden for an adjustment of the run with an agreement, the new
        # term until it exists, the agreement fields without an agreement
        for name in ('adjustment_mode', 'settlement_result'):
            field = getattr(cls, name)
            field.states = dict(field.states or {})
            field.states['invisible'] = (
                run | field.states.get('invisible', False))
        for name in ('term_new', 'valid_from_new', 'valid_to_new',
                'amount_new', 'tax_amount_new', 'total_amount_new'):
            field = getattr(cls, name)
            field.states = dict(field.states or {})
            field.states['invisible'] = ~Eval('term_new')
        for name in ('rent_adjustment', 'procedure'):
            field = getattr(cls, name)
            field.states = dict(field.states or {})
            field.states['invisible'] = ~Eval('rent_adjustment')
        cls._buttons.update({
            'recompute': {
                'invisible': ~run | (Eval('state') != 'draft'),
                'depends': ['procedure', 'state'],
                },
            'approve': {
                'invisible': Eval('state') != 'draft',
                'depends': ['state'],
                },
            'cancel': {
                'invisible': ~Eval('state').in_(
                    ['draft', 'approved', 'declared']),
                'depends': ['state'],
                },
            'draft': {
                'invisible': Eval('state') != 'cancelled',
                'depends': ['state'],
                },
            })

    @classmethod
    def view_attributes(cls):
        return super().view_attributes() + [
            ('//page[@id="page_index"]', 'states',
                {'invisible': ~cls._index}, ['procedure']),
            ('//page[@id="page_declaration"]', 'states',
                {'invisible': ~cls._run}, ['procedure']),
            ('//separator[@name="term_new"]', 'states',
                {'invisible': ~Eval('term_new')}, ['term_new']),
            ('/tree', 'visual', If(Eval('check_state') == 'error', 'danger',
                    If(Eval('check_state') == 'warning', 'warning', '')),
                ['check_state']),
            ]

    @fields.depends('rent_adjustment')
    def on_change_with_effective_rule(self, name=None):
        return (self.rent_adjustment.effective_rule
            if self.rent_adjustment else None)

    @fields.depends('rent_adjustment')
    def on_change_with_procedure(self, name=None):
        return self.rent_adjustment.procedure if self.rent_adjustment else None

    @classmethod
    def search_procedure(cls, name, clause):
        return [('rent_adjustment.procedure',) + tuple(clause[1:])]

    def get_difference_amount(self, name):
        if self.planned_amount is None or self.amount_old is None:
            return None
        return self.planned_amount - self.amount_old

    @classmethod
    def _check_values(cls, findings):
        "check_state/check_message of a list of (code, level, message)"
        if not findings:
            return {'check_state': 'ok', 'check_message': None}
        level = max((lv for _, lv, _ in findings), key=CHECK_LEVELS.index)
        labels = dict(cls.fields_get(['check_state'])['check_state']
            ['selection'])
        return {
            'check_state': level,
            'check_message': '\n'.join(
                f'{code} ({labels.get(lv, lv)}): {text}'
                for code, lv, text in findings),
            }

    def _index_compute(self):
        """Recalculate the index adjustment for its stored new index month
        (current reference of the agreement, current series)."""
        agreement = self.rent_adjustment
        values, findings, _ = agreement.compute_index_adjustment(
            self.index_month_new, self.declaration_date, self.receipt_date)
        values.pop('rent_adjustment')
        return self._finish_compute(values, findings, self.manual_amount)

    @classmethod
    def write(cls, *args):
        super().write(*args)
        # The effective date follows declaration/receipt date until done
        actions = iter(args)
        to_update = []
        for records, values in zip(actions, actions):
            if {'declaration_date', 'receipt_date'} & set(values):
                to_update.extend(r for r in records
                    if r.procedure in RUN_AGREEMENT_PROCEDURES
                    and r.state in ('draft', 'approved', 'declared'))
        for record in to_update:
            valid_from = record._effective_date()
            if valid_from != record.planned_valid_from:
                super().write([record], {'planned_valid_from': valid_from})

    @classmethod
    def delete(cls, records):
        for record in records:
            if (record.rent_adjustment
                    and record.state not in ('draft', 'cancelled')):
                raise ValidationError(gettext(
                        'real_estate.msg_index_adjustment_delete',
                        adjustment=record.rec_name))
        super().delete(records)

    def get_rec_name(self, name):
        parts = [self.contract.rec_name if self.contract else '']
        if self.index_month_new:
            parts.append(self.index_month_new.strftime('%m.%Y'))
        if self.planned_valid_from:
            parts.append(self.planned_valid_from.strftime('%d.%m.%Y'))
        return ' / '.join(p for p in parts if p) or str(self.id)

    @classmethod
    @ModelView.button
    def recompute(cls, records):
        for record in records:
            if record.rent_adjustment and record.state == 'draft':
                cls.write([record], record._compute())

    @classmethod
    @ModelView.button
    @Workflow.transition('approved')
    def approve(cls, records):
        Warning = Pool().get('res.user.warning')
        for record in records:
            if record.procedure not in RUN_AGREEMENT_PROCEDURES:
                continue
            if record.check_state == 'error':
                raise ValidationError(gettext(
                        'real_estate.msg_index_adjustment_approve_error',
                        adjustment=record.rec_name,
                        protocol=record.check_message or ''))
            if record.check_state == 'warning':
                key = Warning.format('index_adjustment_approve', [record])
                if Warning.check(key):
                    raise IndexAdjustmentWarning(key, gettext(
                            'real_estate.msg_index_adjustment_approve_warning',
                            adjustment=record.rec_name,
                            protocol=record.check_message or ''))

    @classmethod
    @ModelView.button
    @Workflow.transition('cancelled')
    def cancel(cls, records):
        Warning = Pool().get('res.user.warning')
        declared = [r for r in records if r.state == 'declared']
        if declared:
            key = Warning.format('index_adjustment_cancel_declared', declared)
            if Warning.check(key):
                raise IndexAdjustmentWarning(key, gettext(
                        'real_estate.msg_index_adjustment_cancel_declared',
                        adjustments=', '.join(r.rec_name for r in declared)))

    @classmethod
    @ModelView.button
    @Workflow.transition('draft')
    def draft(cls, records):
        for record in records:
            if not record.rent_adjustment:
                continue
            # I07 / V02: at most one open adjustment per agreement
            others = [a for a in record.rent_adjustment.adjustments
                if a.id != record.id
                and a.state in ('draft', 'approved', 'declared')]
            if others:
                raise ValidationError(gettext(
                        'real_estate.msg_index_adjustment_open',
                        rent_adjustment=record.rent_adjustment.rec_name,
                        adjustment=others[0].rec_name))
            cls.write([record], record._compute())

    @classmethod
    @Workflow.transition('declared')
    def declare(cls, records):
        """Create the declaration to the tenants (spec 6.1) and archive the
        original as attachment - the values of the adjustment are frozen
        from now on."""
        pool = Pool()
        Attachment = pool.get('ir.attachment')
        Date = pool.get('ir.date')
        today = Date.today()
        for record in records:
            if record.procedure not in LETTERS:
                continue
            Letter = pool.get(LETTERS[record.procedure], type='report')
            if not record.declaration_date:
                cls.write([record], {'declaration_date': today})
            ext, content, _, name = Letter.execute([record.id], {
                    'model': cls.__name__,
                    'original': True,
                    })
            attachment, = Attachment.create([{
                        'name': f'{name}.{ext}',
                        'resource': str(record),
                        'data': content,
                        }])
            cls.write([record], {'letter': attachment.id})

    @classmethod
    @Workflow.transition('done')
    def execute(cls, records):
        """Execute the declared index adjustment (spec 6.5): checks with
        the actual receipt, split of the term from the effective date,
        recalculation of the cash flow and contract log."""
        pool = Pool()
        Term = pool.get('real_estate.contract.term')
        Contract = pool.get('real_estate.contract')
        User = pool.get('res.user')
        Date = pool.get('ir.date')
        Task = pool.get('real_estate.task')
        cls.lock(records)
        employee = User(Transaction().user).employee
        for record in records:
            if record.procedure == 'comparative_rent':
                record._execute_comparative(employee)
                continue
            if record.procedure != 'index_rent':
                continue
            agreement = record.rent_adjustment
            name = record.rec_name
            if (agreement.effective_rule == 'statutory'
                    and not record.receipt_date):
                raise ValidationError(gettext(
                        'real_estate.msg_index_adjustment_receipt_missing',
                        adjustment=name))
            if agreement.current_term != record.term_old:
                raise ValidationError(gettext(
                        'real_estate.msg_index_adjustment_term_changed',
                        adjustment=name,
                        term=record.term_old.rec_name.strip()))
            # Checks again with the actual receipt (I04, I06, I09, I14)
            values, findings, _ = agreement.compute_index_adjustment(
                record.index_month_new, record.declaration_date,
                record.receipt_date)
            errors = [f'{code}: {text}' for code, level, text in findings
                if level == 'error' and code in ('I04', 'I06', 'I09', 'I14')]
            if errors:
                raise ValidationError(gettext(
                        'real_estate.msg_index_adjustment_execute_errors',
                        adjustment=name, protocol='\n'.join(errors)))
            # I11: the declared rent must not exceed the rent allowed with
            # the cap rule on the actual receipt date
            if (record.direction == 'increase'
                    and values.get('planned_amount') is not None
                    and values['planned_amount'] < record.planned_amount):
                raise ValidationError(gettext(
                        'real_estate.msg_index_adjustment_cap_changed',
                        adjustment=name, declared=record.planned_amount,
                        allowed=values['planned_amount']))
            valid_from = values['planned_valid_from']
            new_term = Term._split(record.term_old, valid_from,
                record.planned_unit_price, record.planned_quantity)
            contract = record.term_old.contract
            Contract._re_calc_terms([contract])
            cls.write([record], {
                    'term_new': new_term.id,
                    'planned_valid_from': valid_from,
                    'executed_by': employee.id if employee else None,
                    'executed_date': Date.today(),
                    })
            record = cls(record.id)
            contract.add_log('index_rent', gettext(
                    'real_estate.msg_index_adjustment_log',
                    index=agreement.price_index.rec_name,
                    month_old=record.index_month_old.strftime('%m.%Y'),
                    value_old=record.index_value_old,
                    month_new=record.index_month_new.strftime('%m.%Y'),
                    value_new=record.index_value_new,
                    change=record.index_change_percent,
                    applied=record.applied_change_percent,
                    cap=record.cap_rule.rec_name if record.cap_rule else '-',
                    amount_old=record.amount_old,
                    amount_new=record.planned_amount,
                    valid_from=valid_from.strftime('%d.%m.%Y'),
                    receipt=(record.receipt_date.strftime('%d.%m.%Y')
                        if record.receipt_date else '-'),
                    dispatch=record.dispatch_method or '-'))
            # The preparation task of the agreement is done
            Task.close_for(agreement, 'index_prepare')
