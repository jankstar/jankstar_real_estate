'Meter reading sheet (Zählerableseliste): collective entry of meter readings'
from decimal import Decimal

from dateutil.relativedelta import relativedelta

from trytond.exceptions import UserWarning
from trytond.i18n import gettext
from trytond.model import ModelSQL, ModelView, Workflow, fields
from trytond.model.exceptions import AccessError, ValidationError
from trytond.modules.company.model import employee_field
from trytond.pool import Pool
from trytond.pyson import Eval, PYSONEncoder
from trytond.report import Report
from trytond.transaction import Transaction

STATES = [
    ('draft', "Draft"),
    ('done', "Done"),
    ('cancelled', "Cancelled"),
    ]


class MeterReadingSheetWarning(UserWarning):
    pass


#**********************************************************************
class MeterReadingSheet(Workflow, ModelSQL, ModelView):
    "Meter Reading Sheet"
    __name__ = 'real_estate.meter_reading.sheet'

    _states = {'readonly': Eval('state') != 'draft'}

    company = fields.Many2One('company.company', "Company", required=True,
        states=_states)
    base_object = fields.Many2One('real_estate.base_object', "Object",
        required=True, ondelete='RESTRICT', states=_states,
        domain=[
            ('type', 'in', ['property', 'building', 'object']),
            ('company', '=', Eval('company', -1)),
            ],
        help="Property, building or rental unit - the meters below it are "
             "listed.")
    property = fields.Many2One('real_estate.base_object', "Property",
        readonly=True)
    reading_date = fields.Date("Reading Date", required=True,
        states=_states)
    equipment_kind = fields.Many2One('real_estate.equipment.kind',
        "Equipment Kind", ondelete='SET NULL', states=_states,
        help="Only meters of this equipment kind.")
    name_filter = fields.Char("Name Filter", states=_states,
        help="Only meters whose name contains this text, e.g. "
             "'Warmwasser'.")
    reader = fields.Many2One('res.user', "Reader", states=_states,
        help="Reading user of the meter readings created.")
    notes = fields.Text("Notes")
    lines = fields.One2Many('real_estate.meter_reading.sheet.line', 'sheet',
        "Meters", states=_states)
    progress = fields.Function(fields.Char("Progress"), 'get_progress')
    state = fields.Selection(STATES, "State", readonly=True, required=True,
        sort=False)
    done_by = employee_field("Done by", states=['done', 'cancelled'])
    done_date = fields.Date("Done on", readonly=True)

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._order = [('reading_date', 'DESC'), ('id', 'DESC')]
        cls._transitions |= {
            ('draft', 'done'),
            ('draft', 'cancelled'),
            ('done', 'draft'),
            ('cancelled', 'draft'),
            }
        cls._buttons.update({
            'load_meters': {
                'invisible': Eval('state') != 'draft',
                'depends': ['state'],
                },
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
            'follow_up': {
                'invisible': Eval('state') != 'done',
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
    def default_reader():
        return Transaction().user

    @staticmethod
    def default_reading_date():
        return Pool().get('ir.date').today()

    def get_rec_name(self, name):
        return ' '.join(filter(None, [
                    self.base_object.rec_name if self.base_object else '',
                    self.reading_date.strftime('%d.%m.%Y')
                    if self.reading_date else '']))

    @classmethod
    def search_rec_name(cls, name, clause):
        return [('base_object.rec_name',) + tuple(clause[1:])]

    def get_progress(self, name):
        read = len([l for l in self.lines if l.value is not None])
        return f'{read} / {len(self.lines)}'

    @staticmethod
    def _property_of(obj):
        node = obj
        while node and node.type != 'property':
            node = node.parent
        return node

    @classmethod
    def _set_property(cls, values):
        BaseObject = Pool().get('real_estate.base_object')
        if values.get('base_object'):
            prop = cls._property_of(BaseObject(values['base_object']))
            values['property'] = prop.id if prop else None

    # ------------------------------------------------------------------
    # Lines

    def _meters(self):
        "Meters below the object, filtered by equipment kind and name"
        BaseObject = Pool().get('real_estate.base_object')
        domain = [
            ('parent', 'child_of', [self.base_object.id]),
            ('type', '=', 'equipment'),
            ('e_type', '=', 'meters'),
            ('state', '!=', 'deactivated'),
            ]
        if self.equipment_kind:
            domain.append(('equipment_kind', '=', self.equipment_kind.id))
        if self.name_filter:
            domain.append(('name', 'ilike', f'%{self.name_filter}%'))
        return BaseObject.search(domain)

    @staticmethod
    def _unit_of(meter):
        node = meter.parent
        while node and node.type != 'object':
            node = node.parent
        return node

    def _tenant_of(self, unit):
        "Main tenant of the contract of the unit on the reading date"
        Occupancy = Pool().get('real_estate.base_object.occupancy')
        if not unit or not self.reading_date:
            return None
        for occ in Occupancy.search([
                    ('base_object', '=', unit.id),
                    ('start_date', '<=', self.reading_date),
                    ['OR', ('end_date', '=', None),
                        ('end_date', '>=', self.reading_date)],
                    ('contract', '!=', None),
                    ], limit=1):
            return occ.contract.contractual_partner
        return None

    def _previous_reading(self, meter):
        "Last reading of the meter before the reading date"
        Reading = Pool().get('real_estate.meter_reading')
        readings = Reading.search([
                ('base_object', '=', meter.id),
                ('reading_date', '<', self.reading_date),
                ], order=[('reading_date', 'DESC'), ('m_type', 'DESC')],
            limit=1)
        return readings[0] if readings else None

    def _line_info(self, meter):
        "Unit, tenant and previous reading of a meter line"
        unit = self._unit_of(meter)
        tenant = self._tenant_of(unit)
        previous = self._previous_reading(meter)
        return {
            'unit': unit.id if unit else None,
            'tenant': tenant.id if tenant else None,
            'previous_value': previous.value if previous else None,
            'previous_date': previous.reading_date if previous else None,
            'meter_id': (previous.meter_id if previous
                else meter.meter_id),
            }

    @classmethod
    @ModelView.button
    def load_meters(cls, sheets):
        """Add the meters not yet listed and refresh unit, tenant and
        previous reading of the lines - values entered are kept"""
        Line = Pool().get('real_estate.meter_reading.sheet.line')
        to_create, to_write = [], []
        for sheet in sheets:
            if sheet.state != 'draft':
                continue
            listed = {l.meter.id: l for l in sheet.lines}
            new = []
            for meter in sheet._meters():
                info = sheet._line_info(meter)
                line = listed.get(meter.id)
                if line:
                    if line.meter_id:
                        info.pop('meter_id')
                    to_write.extend(([line], info))
                else:
                    unit = cls._unit_of(meter)
                    new.append(((unit.rec_name if unit else '',
                                meter.rec_name),
                            dict(info, sheet=sheet.id, meter=meter.id)))
            to_create.extend(v for _, v in sorted(new, key=lambda n: n[0]))
        if to_write:
            Line.write(*to_write)
        if to_create:
            Line.create(to_create)

    @classmethod
    def create(cls, vlist):
        vlist = [v.copy() for v in vlist]
        for values in vlist:
            cls._set_property(values)
        sheets = super().create(vlist)
        # Created without lines (form, copy, follow-up): load the meters
        cls.load_meters([s for s in sheets if not s.lines])
        return sheets

    @classmethod
    def write(cls, *args):
        actions = iter(args)
        args = []
        for records, values in zip(actions, actions):
            if 'base_object' in values:
                values = values.copy()
                cls._set_property(values)
            args.extend((records, values))
        super().write(*args)

    @classmethod
    def copy(cls, sheets, default=None):
        default = default.copy() if default else {}
        default.setdefault('lines', None)
        default.setdefault('done_by', None)
        default.setdefault('done_date', None)
        return super().copy(sheets, default=default)

    @classmethod
    def delete(cls, sheets):
        for sheet in sheets:
            if sheet.state == 'done':
                raise AccessError(gettext(
                        'real_estate.msg_meter_reading_sheet_delete_done',
                        sheet=sheet.rec_name))
        super().delete(sheets)

    # ------------------------------------------------------------------
    # Workflow

    @classmethod
    @ModelView.button
    @Workflow.transition('done')
    def done(cls, sheets):
        """Create the meter readings of the lines with a value - an
        existing reading of the meter on the reading date is linked"""
        pool = Pool()
        User = pool.get('res.user')
        Date = pool.get('ir.date')
        Warning = pool.get('res.user.warning')
        for sheet in sheets:
            if not sheet.lines:
                raise ValidationError(gettext(
                        'real_estate.msg_meter_reading_sheet_no_lines',
                        sheet=sheet.rec_name))
            missing = [l for l in sheet.lines if l.value is None]
            if missing:
                key = Warning.format('meter_reading_sheet_missing', [sheet])
                if Warning.check(key):
                    raise MeterReadingSheetWarning(key, gettext(
                            'real_estate.msg_meter_reading_sheet_missing',
                            sheet=sheet.rec_name, count=len(missing),
                            meters=', '.join(l.meter.rec_name
                                for l in missing[:10])))
        for sheet in sheets:
            sheet._create_readings()
        employee = User(Transaction().user).employee
        cls.write(sheets, {
                'done_by': employee.id if employee else None,
                'done_date': Date.today(),
                })

    def _create_readings(self):
        pool = Pool()
        Reading = pool.get('real_estate.meter_reading')
        Line = pool.get('real_estate.meter_reading.sheet.line')
        user = self.reader or Transaction().user
        for line in self.lines:
            if line.value is None or line.reading:
                continue
            existing = Reading.search([
                    ('base_object', '=', line.meter.id),
                    ('reading_date', '=', self.reading_date),
                    ], limit=1)
            if existing:
                Line.write([line], {
                        'reading': existing[0].id,
                        'reading_created': False,
                        })
                continue
            reading, = Reading.create([{
                        'company': self.company.id,
                        'base_object': line.meter.id,
                        'meter_id': line.meter_id or line.meter.meter_id,
                        'reading_date': self.reading_date,
                        'm_type': 'reading',
                        'value': line.value,
                        'reading_user': getattr(user, 'id', user),
                        'comment': self.rec_name,
                        }])
            Line.write([line], {
                    'reading': reading.id,
                    'reading_created': True,
                    })

    @classmethod
    @ModelView.button
    @Workflow.transition('cancelled')
    def cancel(cls, sheets):
        pass

    @classmethod
    @ModelView.button
    @Workflow.transition('draft')
    def draft(cls, sheets):
        """Back to draft: the meter readings created by the sheet are
        deleted (they are created again when done), linked ones kept"""
        pool = Pool()
        Reading = pool.get('real_estate.meter_reading')
        Line = pool.get('real_estate.meter_reading.sheet.line')
        lines = [l for s in sheets for l in s.lines if l.reading]
        created = [l.reading for l in lines if l.reading_created]
        if lines:
            Line.write(lines, {'reading': None, 'reading_created': False})
        if created:
            Reading.delete(created)
        cls.write(sheets, {'done_by': None, 'done_date': None})

    @classmethod
    @ModelView.button
    def follow_up(cls, sheets):
        """Create the sheets of the next reading (same object and filter,
        reading date + 1 year) and open them"""
        pool = Pool()
        Action = pool.get('ir.action')
        ModelData = pool.get('ir.model.data')
        new = []
        for sheet in sheets:
            new.extend(cls.copy([sheet], default={
                        'reading_date': (sheet.reading_date
                            + relativedelta(years=1)),
                        'notes': None,
                        }))
        action = Action(ModelData.get_id(
                'real_estate', 'act_meter_reading_sheet')).get_action_value()
        action['pyson_domain'] = PYSONEncoder().encode(
            [('id', 'in', [s.id for s in new])])
        action['views'] = list(reversed(action['views']))
        # open the records themselves, not the first tab of the action
        action['domains'] = []
        # the client opens a form-first action without res_id as a new record
        action['res_id'] = [s.id for s in new]
        return action


#**********************************************************************
class MeterReadingSheetLine(ModelSQL, ModelView):
    "Meter Reading Sheet Line"
    __name__ = 'real_estate.meter_reading.sheet.line'

    sheet = fields.Many2One('real_estate.meter_reading.sheet', "Sheet",
        required=True, ondelete='CASCADE')
    meter = fields.Many2One('real_estate.base_object', "Meter",
        required=True, ondelete='RESTRICT',
        domain=[('type', '=', 'equipment'), ('e_type', '=', 'meters')])
    unit = fields.Many2One('real_estate.base_object', "Rental Unit",
        readonly=True)
    tenant = fields.Many2One('party.party', "Tenant", readonly=True)
    meter_id = fields.Char("Meter ID")
    previous_value = fields.Numeric("Previous Value", digits=(16, 3),
        readonly=True)
    previous_date = fields.Date("Previous Date", readonly=True)
    value = fields.Numeric("Value", digits=(16, 3))
    uom = fields.Function(fields.Many2One('product.uom', "Unit of Measure"),
        'on_change_with_uom')
    consumption = fields.Function(fields.Numeric("Consumption",
            digits=(16, 3)), 'on_change_with_consumption')
    remarks = fields.Char("Remarks")
    reading = fields.Many2One('real_estate.meter_reading', "Meter Reading",
        readonly=True, ondelete='SET NULL')
    reading_created = fields.Boolean("Reading Created", readonly=True,
        help="The meter reading was created by the sheet (deleted again "
             "when the sheet is reset to draft).")

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._order = [('sheet', 'ASC'), ('id', 'ASC')]

    @fields.depends('meter', '_parent_meter.meter_unit')
    def on_change_with_uom(self, name=None):
        return self.meter.meter_unit if self.meter else None

    @fields.depends('meter', 'value', 'previous_value',
        '_parent_meter.meter_is_counter')
    def on_change_with_consumption(self, name=None):
        if (self.meter and self.meter.meter_is_counter
                and self.value is not None
                and self.previous_value is not None):
            return self.value - self.previous_value
        return None

    @fields.depends('meter', 'sheet', '_parent_sheet.reading_date',
        '_parent_sheet.id')
    def on_change_meter(self):
        if self.meter and self.sheet and self.sheet.reading_date:
            for name, value in self.sheet._line_info(self.meter).items():
                setattr(self, name, value)

    @fields.depends('meter', 'value', '_parent_meter.meter_no_decimals')
    def on_change_value(self):
        if (self.meter and self.meter.meter_no_decimals
                and self.value is not None):
            self.value = self.value.quantize(Decimal(1))


#**********************************************************************
class MeterReadingSheetReport(Report):
    "Meter reading sheet to take along (Ableseliste)"
    __name__ = 'real_estate.meter_reading.sheet.report'

    @classmethod
    def get_context(cls, records, header, data):
        ContractReport = Pool().get('real_estate.contract.report',
            type='report')
        context = super().get_context(records, header, data)
        context['format_value'] = ContractReport.format_value
        return context
