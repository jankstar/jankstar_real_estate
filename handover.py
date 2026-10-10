'Handover report (Übergabeprotokoll) - spezifikation-uebergabeprotokoll.md'
from decimal import Decimal

from trytond.exceptions import UserWarning
from trytond.i18n import gettext
from trytond.model import (
    DeactivableMixin, ModelSQL, ModelView, Workflow, fields,
    sequence_ordered)
from trytond.model.exceptions import AccessError, ValidationError
from trytond.modules.company.model import employee_field
from trytond.modules.currency.fields import Monetary
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Bool, Eval, If
from trytond.transaction import Transaction

KINDS = [
    ('move_in', "Move-in"),
    ('pre_inspection', "Pre-inspection"),
    ('move_out', "Move-out"),
    ]
CONDITIONS = [
    ('ok', "OK"),
    ('wear', "Normal Wear"),
    ('damage', "Damage"),
    ('missing', "Missing"),
    ]
KEY_TYPES = [
    ('house', "Front Door"),
    ('apartment', "Apartment Door"),
    ('mailbox', "Mailbox"),
    ('cellar', "Cellar"),
    ('garage', "Garage"),
    ('other', "Other"),
    ]


class HandoverMeterWarning(UserWarning):
    pass


def _types_of_use():
    BaseObject = Pool().get('real_estate.base_object')
    return [(k, v) for k, v in BaseObject.fields_get(
            ['type_of_use'])['type_of_use']['selection'] if k]


#**********************************************************************
class HandoverChecklist(DeactivableMixin, ModelSQL, ModelView):
    "Handover Checklist"
    __name__ = 'real_estate.handover.checklist'

    name = fields.Char("Name", required=True, translate=True)
    types_of_use = fields.MultiSelection('get_types_of_use', "Types of Use",
        help="Proposed for handover reports of contracts with these types "
             "of use.")
    lines = fields.One2Many('real_estate.handover.checklist.line',
        'checklist', "Check Items")

    @classmethod
    def get_types_of_use(cls):
        return _types_of_use()


class HandoverChecklistLine(sequence_ordered(), ModelSQL, ModelView):
    "Handover Checklist Line"
    __name__ = 'real_estate.handover.checklist.line'

    checklist = fields.Many2One('real_estate.handover.checklist',
        "Checklist", required=True, ondelete='CASCADE')
    room = fields.Char("Room", required=True, translate=True)
    item = fields.Char("Item", required=True, translate=True)


#**********************************************************************
class Handover(Workflow, ModelSQL, ModelView):
    "Handover Report"
    __name__ = 'real_estate.contract.handover'

    _states = {'readonly': Eval('state') != 'draft'}

    company = fields.Many2One('company.company', "Company", required=True,
        states=_states)
    contract = fields.Many2One('real_estate.contract', "Contract",
        required=True, ondelete='CASCADE', states=_states,
        domain=[('company', '=', Eval('company', -1))])
    property = fields.Many2One('real_estate.base_object', "Property",
        readonly=True)
    kind = fields.Selection(KINDS, "Kind", required=True, sort=False,
        states=_states)
    date = fields.Date("Date", required=True, states=_states)
    time = fields.Char("Time", states=_states)
    objects = fields.Many2Many('real_estate.contract.handover-base_object',
        'handover', 'object', "Objects", states=_states,
        help="Objects handed over - proposed: the objects of the contract "
             "items.")
    tenants = fields.Many2Many('real_estate.contract.handover-party',
        'handover', 'party', "Tenants Present", states=_states)
    tenant_present = fields.Boolean("Tenant Present", states=_states,
        help="Uncheck if the handover took place in the absence of the "
             "tenant.")
    landlord_employee = fields.Many2One('company.employee',
        "Landlord Representative", states=_states)
    other_participants = fields.Text("Other Participants", states=_states)
    checklist = fields.Many2One('real_estate.handover.checklist',
        "Checklist", states=_states, ondelete='SET NULL',
        help="Template of the check items - proposed by the type of use "
             "of the contract.")
    lines = fields.One2Many('real_estate.contract.handover.line',
        'handover', "Check Items", states=_states)
    keys = fields.One2Many('real_estate.contract.handover.key',
        'handover', "Keys", states=_states)
    meters = fields.One2Many('real_estate.contract.handover.meter',
        'handover', "Meter Readings", states=_states)
    general_condition = fields.Selection([
            (None, ''),
            ('good', "Good"),
            ('normal_wear', "Normal Wear"),
            ('defects', "Defects"),
            ], "General Condition", sort=False, states=_states)
    cleaned = fields.Boolean("Swept Clean", states={
            'readonly': Eval('state') != 'draft',
            'invisible': Eval('kind') == 'move_in',
            })
    notes = fields.Text("Agreements", states=_states)
    currency = fields.Function(fields.Many2One('currency.currency',
            "Currency"), 'on_change_with_currency')
    cost_total = fields.Function(Monetary("Estimated Costs",
            currency='currency', digits='currency',
            help="Sum of the estimated costs of the damages."),
        'get_cost_total')
    signed_document = fields.Many2One('ir.attachment', "Signed Report",
        ondelete='SET NULL',
        help="Scan of the signed report - first add it as attachment.")
    state = fields.Selection([
            ('draft', "Draft"),
            ('done', "Done"),
            ('cancelled', "Cancelled"),
            ], "State", readonly=True, required=True, sort=False)
    done_by = employee_field("Done by", states=['done', 'cancelled'])
    done_date = fields.Date("Done on", readonly=True)

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._order = [('date', 'DESC'), ('id', 'DESC')]
        cls._transitions |= {
            ('draft', 'done'),
            ('draft', 'cancelled'),
            ('done', 'draft'),
            ('cancelled', 'draft'),
            }
        cls._buttons.update({
            'done': {
                'invisible': Eval('state') != 'draft',
                'depends': ['state'],
                },
            'cancel': {
                'invisible': Eval('state') != 'draft',
                'depends': ['state'],
                },
            'draft': {
                'invisible': Eval('state') == 'draft',
                'depends': ['state'],
                },
            'fill_lines': {
                'invisible': Eval('state') != 'draft',
                'depends': ['state'],
                },
            })

    @staticmethod
    def default_company():
        return Transaction().context.get('company')

    @staticmethod
    def default_state():
        return 'draft'

    @staticmethod
    def default_tenant_present():
        return True

    @staticmethod
    def default_landlord_employee():
        return Transaction().context.get('employee')

    def get_rec_name(self, name):
        kinds = dict(self.fields_get(['kind'])['kind']['selection'])
        return ' '.join(filter(None, [kinds.get(self.kind, ''),
                    self.contract.rec_name if self.contract else '',
                    self.date.strftime('%d.%m.%Y') if self.date else '']))

    @fields.depends('contract', '_parent_contract.currency')
    def on_change_with_currency(self, name=None):
        return self.contract.currency if self.contract else None

    def get_cost_total(self, name):
        return sum((l.cost_estimate or Decimal(0) for l in self.lines),
            Decimal(0))

    # ------------------------------------------------------------------
    # Proposals (spec 2-5)

    @fields.depends('contract', '_parent_contract.id', 'kind', 'date',
        'objects', 'tenants', 'checklist', 'lines', 'keys', 'meters')
    def on_change_contract(self):
        self._propose()

    @fields.depends('contract', '_parent_contract.id', 'kind', 'date',
        'objects', 'tenants', 'checklist', 'lines', 'keys', 'meters')
    def on_change_kind(self):
        self._propose()

    @fields.depends('checklist', 'lines', 'kind', 'contract',
        '_parent_contract.id')
    def on_change_checklist(self):
        if not self.lines:
            self.lines = self._checklist_lines()

    def _propose(self):
        contract = self.contract
        if not contract:
            return
        if not self.date and self.kind:
            self.date = (contract.start_date if self.kind == 'move_in'
                else contract.get_effective_end_date())
        if not self.objects:
            self.objects = [o for item in contract.items
                for o in item.objects]
        if not self.tenants:
            Party = Pool().get('party.party')
            self.tenants = Party.browse(contract.main_tenant_party_ids or [])
        if not self.checklist:
            self.checklist = self._default_checklist()
        if not self.lines:
            self.lines = self._checklist_lines()
        if not self.keys:
            self.keys = self._previous_keys()
        if not self.meters:
            self.meters = self._meter_lines()

    def _default_checklist(self):
        Checklist = Pool().get('real_estate.handover.checklist')
        type_of_use = self.contract.type_of_use if self.contract else None
        if type_of_use:
            checklists = Checklist.search([
                    ('types_of_use', 'in', type_of_use)], limit=1)
            if checklists:
                return checklists[0]
        return None

    def _checklist_lines(self):
        Line = Pool().get('real_estate.contract.handover.line')
        lines = []
        # Move-out: open defects of the last done pre-inspection first
        if self.kind == 'move_out' and self.contract:
            pre = self.search([
                    ('contract', '=', self.contract.id),
                    ('kind', '=', 'pre_inspection'),
                    ('state', '=', 'done'),
                    ], order=[('date', 'DESC'), ('id', 'DESC')], limit=1)
            if pre:
                for line in pre[0].lines:
                    if line.condition != 'ok':
                        lines.append(Line(room=line.room, item=line.item,
                                condition=line.condition,
                                description=line.description,
                                remedy_by=line.remedy_by,
                                remedy_until=line.remedy_until,
                                from_pre_inspection=True))
        if self.checklist:
            lines.extend(Line(room=l.room, item=l.item, condition='ok',
                    remedy_by='none')
                for l in self.checklist.lines)
        return lines

    def _previous_keys(self):
        Key = Pool().get('real_estate.contract.handover.key')
        if self.kind != 'move_out' or not self.contract:
            return []
        move_in = self.search([
                ('contract', '=', self.contract.id),
                ('kind', '=', 'move_in'),
                ('state', '=', 'done'),
                ], limit=1)
        if not move_in:
            return []
        return [Key(key_type=k.key_type, description=k.description,
                quantity=None) for k in move_in[0].keys]

    def _meter_lines(self):
        pool = Pool()
        BaseObject = pool.get('real_estate.base_object')
        Meter = pool.get('real_estate.contract.handover.meter')
        objects = [o.id for o in (self.objects or [])]
        if not objects:
            return []
        meters = BaseObject.search([
                ('parent', 'child_of', objects),
                ('type', '=', 'equipment'),
                ('e_type', '=', 'meters'),
                ])
        return [Meter(meter=m, meter_id=m.meter_id) for m in meters]

    @classmethod
    @ModelView.button
    def fill_lines(cls, handovers):
        "Add the check items, keys and meters not yet proposed"
        for handover in handovers:
            handover._propose()
            handover.save()

    @classmethod
    def create(cls, vlist):
        Contract = Pool().get('real_estate.contract')
        vlist = [v.copy() for v in vlist]
        for values in vlist:
            if values.get('contract'):
                contract = Contract(values['contract'])
                values['property'] = (contract.property.id
                    if contract.property else None)
        handovers = super().create(vlist)
        # Created without proposals (e.g. on the contract's tab): propose
        to_propose = [h for h in handovers
            if not h.lines and not h.keys and not h.meters]
        for handover in to_propose:
            handover._propose()
            handover.save()
        return handovers

    @classmethod
    def write(cls, *args):
        Contract = Pool().get('real_estate.contract')
        actions = iter(args)
        args = []
        for records, values in zip(actions, actions):
            if values.get('contract'):
                values = values.copy()
                contract = Contract(values['contract'])
                values['property'] = (contract.property.id
                    if contract.property else None)
            args.extend((records, values))
        super().write(*args)
        # the signed report is also shown on the contract
        actions = iter(args)
        signed = []
        for records, values in zip(actions, actions):
            if values.get('signed_document'):
                signed.extend(records)
        cls._attach_to_contract(cls.browse(signed))

    @classmethod
    def _attach_to_contract(cls, handovers):
        """Copy the signed report to the contract (the copy shares the
        stored file) - once per document"""
        Attachment = Pool().get('ir.attachment')
        for handover in handovers:
            document = handover.signed_document
            if not document or not handover.contract:
                continue
            resource = str(handover.contract)
            if Attachment.search([
                        ('resource', '=', resource),
                        ('file_id', '=', document.file_id),
                        ('name', '=', document.name),
                        ], limit=1):
                continue
            Attachment.copy([document], default={'resource': resource})

    @classmethod
    def delete(cls, handovers):
        for handover in handovers:
            if handover.state == 'done':
                raise AccessError(gettext(
                        'real_estate.msg_handover_delete_done',
                        handover=handover.rec_name))
        super().delete(handovers)

    # ------------------------------------------------------------------
    # Workflow (spec 6)

    @classmethod
    @ModelView.button
    @Workflow.transition('done')
    def done(cls, handovers):
        pool = Pool()
        User = pool.get('res.user')
        Date = pool.get('ir.date')
        Warning = pool.get('res.user.warning')
        employee = User(Transaction().user).employee
        for handover in handovers:
            handover._check_done()
            missing = [m for m in handover.meters if m.value is None]
            if missing:
                key = Warning.format('handover_meter_missing', [handover])
                if Warning.check(key):
                    raise HandoverMeterWarning(key, gettext(
                            'real_estate.msg_handover_meter_missing',
                            handover=handover.rec_name,
                            meters=', '.join(m.meter.rec_name
                                for m in missing)))
        # State written here already (the workflow decorator writes it
        # only after this method): the process steps check for done
        # handover reports
        cls.write(handovers, {
                'state': 'done',
                'done_by': employee.id if employee else None,
                'done_date': Date.today(),
                })
        for handover in handovers:
            handover._create_readings()
            handover.contract.add_log('handover', gettext(
                    'real_estate.msg_handover_log',
                    handover=handover.rec_name,
                    keys=sum(k.quantity or 0 for k in handover.keys),
                    defects=len([l for l in handover.lines
                            if l.condition != 'ok'])))
        cls._update_processes(handovers)

    def _check_done(self):
        name = self.rec_name
        if not self.objects:
            raise ValidationError(gettext(
                    'real_estate.msg_handover_no_objects', handover=name))
        if self.kind in ('move_in', 'move_out') and not self.keys:
            raise ValidationError(gettext(
                    'real_estate.msg_handover_no_keys', handover=name))
        if self.kind in ('move_in', 'move_out'):
            others = self.search([
                    ('id', '!=', self.id),
                    ('contract', '=', self.contract.id),
                    ('kind', '=', self.kind),
                    ('state', '=', 'done'),
                    ], limit=1)
            if others:
                raise ValidationError(gettext(
                        'real_estate.msg_handover_unique',
                        handover=name, other=others[0].rec_name))

    def _create_readings(self):
        """Meter readings at the handover date (spec 5) - existing
        readings of the day are linked instead."""
        pool = Pool()
        Reading = pool.get('real_estate.meter_reading')
        Meter = pool.get('real_estate.contract.handover.meter')
        for line in self.meters:
            if line.value is None or line.reading:
                continue
            existing = Reading.search([
                    ('base_object', '=', line.meter.id),
                    ('reading_date', '=', self.date),
                    ], limit=1)
            if existing:
                reading = existing[0]
            else:
                reading, = Reading.create([{
                            'company': self.company.id,
                            'base_object': line.meter.id,
                            'meter_id': line.meter_id or line.meter.meter_id,
                            'reading_date': self.date,
                            'm_type': 'reading',
                            'value': line.value,
                            'comment': self.rec_name,
                            }])
            Meter.write([line], {'reading': reading.id})

    @classmethod
    def _update_processes(cls, handovers):
        "Complete the matching process steps at once (spec 8)"
        Process = Pool().get('real_estate.process')
        processes = Process.search([
                ('contract', 'in', [h.contract.id for h in handovers]),
                ('state', '=', 'running'),
                ])
        if processes:
            Process.check(processes)

    @classmethod
    @ModelView.button
    @Workflow.transition('cancelled')
    def cancel(cls, handovers):
        pass

    @classmethod
    @ModelView.button
    @Workflow.transition('draft')
    def draft(cls, handovers):
        pool = Pool()
        ModelData = pool.get('ir.model.data')
        User = pool.get('res.user')
        admin = ModelData.get_id('real_estate', 'group_real_estate_admin')
        if (Transaction().user and any(h.state == 'done' for h in handovers)
                and admin not in User.get_groups()):
            raise AccessError(gettext('real_estate.msg_handover_reopen'))
        cls.write(handovers, {'done_by': None, 'done_date': None})


class HandoverObject(ModelSQL):
    "Handover Report - Object"
    __name__ = 'real_estate.contract.handover-base_object'

    handover = fields.Many2One('real_estate.contract.handover', "Handover",
        required=True, ondelete='CASCADE')
    object = fields.Many2One('real_estate.base_object', "Object",
        required=True, ondelete='CASCADE')


class HandoverParty(ModelSQL):
    "Handover Report - Party"
    __name__ = 'real_estate.contract.handover-party'

    handover = fields.Many2One('real_estate.contract.handover', "Handover",
        required=True, ondelete='CASCADE')
    party = fields.Many2One('party.party', "Party", required=True,
        ondelete='CASCADE')


#**********************************************************************
class HandoverLine(sequence_ordered(), ModelSQL, ModelView):
    "Handover Report - Check Item"
    __name__ = 'real_estate.contract.handover.line'

    handover = fields.Many2One('real_estate.contract.handover', "Handover",
        required=True, ondelete='CASCADE')
    room = fields.Char("Room", required=True)
    item = fields.Char("Item", required=True)
    condition = fields.Selection(CONDITIONS, "Condition", required=True,
        sort=False)
    description = fields.Text("Description")
    remedy_by = fields.Selection([
            ('none', ""),
            ('tenant', "Tenant"),
            ('landlord', "Landlord"),
            ], "Remedy by", sort=False,
        states={'invisible': Eval('condition') == 'ok'})
    remedy_until = fields.Date("Remedy until",
        states={'invisible': Eval('remedy_by', 'none') == 'none'})
    currency = fields.Function(fields.Many2One('currency.currency',
            "Currency"), 'on_change_with_currency')
    cost_estimate = Monetary("Estimated Costs", currency='currency',
        digits='currency',
        states={'invisible': ~Eval('condition').in_(['damage', 'missing'])},
        help="Basis for a retention from the deposit.")
    from_pre_inspection = fields.Boolean("From Pre-inspection",
        readonly=True)

    @classmethod
    def view_attributes(cls):
        return super().view_attributes() + [
            ('/tree', 'visual', If(Eval('condition').in_(
                        ['damage', 'missing']), 'danger',
                    If(Eval('condition') == 'wear', 'warning', '')),
                ['condition']),
            ]

    @staticmethod
    def default_condition():
        return 'ok'

    @staticmethod
    def default_remedy_by():
        return 'none'

    @fields.depends('handover', '_parent_handover.contract')
    def on_change_with_currency(self, name=None):
        if self.handover and self.handover.contract:
            return self.handover.contract.currency
        return None


class HandoverKey(ModelSQL, ModelView):
    "Handover Report - Key"
    __name__ = 'real_estate.contract.handover.key'

    handover = fields.Many2One('real_estate.contract.handover', "Handover",
        required=True, ondelete='CASCADE')
    key_type = fields.Selection(KEY_TYPES, "Key", required=True, sort=False)
    description = fields.Char("Description",
        help="E.g. locking system, key number.")
    quantity = fields.Integer("Quantity",
        help="Handed over (move-in) resp. returned (move-out).")
    quantity_expected = fields.Function(fields.Integer("Expected",
            help="Move-out: quantity according to the move-in report."),
        'get_quantity_expected')

    @classmethod
    def view_attributes(cls):
        return super().view_attributes() + [
            ('/tree', 'visual', If(Bool(Eval('quantity_expected'))
                    & (Eval('quantity', 0) != Eval('quantity_expected', 0)),
                    'danger', ''),
                ['quantity', 'quantity_expected']),
            ]

    def get_quantity_expected(self, name):
        Handover = Pool().get('real_estate.contract.handover')
        handover = self.handover
        if handover.kind != 'move_out':
            return None
        move_in = Handover.search([
                ('contract', '=', handover.contract.id),
                ('kind', '=', 'move_in'),
                ('state', '=', 'done'),
                ], limit=1)
        if not move_in:
            return None
        return sum(k.quantity or 0 for k in move_in[0].keys
            if k.key_type == self.key_type
            and (k.description or '') == (self.description or ''))


class HandoverMeter(ModelSQL, ModelView):
    "Handover Report - Meter Reading"
    __name__ = 'real_estate.contract.handover.meter'

    handover = fields.Many2One('real_estate.contract.handover', "Handover",
        required=True, ondelete='CASCADE')
    meter = fields.Many2One('real_estate.base_object', "Meter",
        required=True, ondelete='RESTRICT',
        domain=[('type', '=', 'equipment'), ('e_type', '=', 'meters')])
    meter_id = fields.Char("Meter ID")
    value = fields.Numeric("Value", digits=(16, 3))
    reading = fields.Many2One('real_estate.meter_reading', "Meter Reading",
        readonly=True, ondelete='SET NULL')

    @fields.depends('meter')
    def on_change_meter(self):
        if self.meter:
            self.meter_id = self.meter.meter_id


#**********************************************************************
class Contract(metaclass=PoolMeta):
    __name__ = 'real_estate.contract'

    handovers = fields.One2Many('real_estate.contract.handover', 'contract',
        "Handover Reports")


class Process(metaclass=PoolMeta):
    __name__ = 'real_estate.process'

    def _handover_done(self, kind):
        Handover = Pool().get('real_estate.contract.handover')
        contract = self._contract()
        return bool(contract and Handover.search([
                    ('contract', '=', contract.id),
                    ('kind', '=', kind),
                    ('state', '=', 'done'),
                    ], limit=1))

    def _step_done_handover_move_in_done(self):
        return self._handover_done('move_in')

    def _step_done_handover_pre_inspection_done(self):
        return self._handover_done('pre_inspection')

    def _step_done_handover_move_out_done(self):
        return self._handover_done('move_out')
