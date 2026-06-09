'Settlement Unit'
from trytond.model import (
    DeactivableMixin, ModelSQL, ModelView, fields)
from trytond.model.exceptions import ValidationError
from trytond.i18n import gettext
from trytond.pool import Pool
from trytond.transaction import Transaction
from trytond.pyson import Bool, Eval
from trytond.modules.currency.fields import Monetary

import re
import datetime
from decimal import Decimal, ROUND_HALF_UP

from . import base_object


#**********************************************************************
class SettlementUnit(DeactivableMixin, base_object.re_sequence_ordered(), ModelSQL, ModelView):
    """Settlement Unit, e.g. cost allocation for a specific cost type and period within a billing unit."""
    __name__ = 'real_estate.settlement_unit'
    __rec_name__ = 'name'

    property = fields.Function(fields.Many2One('real_estate.base_object', 'Property'),
        'on_change_with_property')

    company = fields.Function(fields.Many2One('company.company', 'Company'),
        'on_change_with_company')

    billing_unit = fields.Many2One('real_estate.billing_unit', 'Billing Unit',
        required=True, ondelete='CASCADE',
        )

    start_date = fields.Function(fields.Date('Start Date'), 'on_change_with_start_date')

    end_date = fields.Function(fields.Date('End Date'), 'on_change_with_end_date')

    state = fields.Function(fields.Selection('get_states', "State"), 'on_change_with_state')

    sub_state = fields.Function(fields.Selection('get_sub_states', "Sub State"), 'get_sub_state')

    type = fields.Many2One(
        'real_estate.cost_type', "Cost Type", required=True, on_change='on_change_type')

    comment = fields.Text("Comment")

    name = fields.Function(fields.Char("Name"), 'on_change_with_name',
        searcher='name_search')

    planned_costs = Monetary('Planned Costs', currency='currency', digits='currency',
        states={'readonly': Eval('state') == 'billed'},
        )

    actual_costs = Monetary('Actual Costs', currency='currency', digits='currency',
        states={'readonly': Eval('state') == 'billed'},
        )

    currency = fields.Function(fields.Many2One('currency.currency', 'Currency'), 'on_change_with_currency')

    allocation_rule = fields.Selection([
            ('no_allocation', 'No allocation'),
            ('allocation_by_measurement', 'Allocation by measurement'),
            ('allocation_by_consumption', 'Allocation by consumption'),
            ('allocation_per_rental_unit', 'Allocation per rental unit'),
            ('allocation_from_external_billing', 'Allocation from external billing')
            ], "Allocation Rule", sort=False,
            )

    vacancy = fields.Selection([
        ('no_allocation', 'No allocation (all cost allocated by tenant)'),
        ('by_owner', 'Allocation by owner'),
        ], "Allocation During Vacancy", sort=False,
        states={'invisible': Eval('allocation_rule') == 'no_allocation'},
        )

    m_type = fields.Many2One(
        'real_estate.measurement.type', "Measurement Type",
        domain=[('types', '=', ['object'])],
        states={
            'invisible': Eval('allocation_rule') != 'allocation_by_measurement',
            'required': Eval('allocation_rule') == 'allocation_by_measurement',
            })

    meter_unit = fields.Many2One('product.uom', "Unit",
        states={
            'invisible': Eval('allocation_rule') != 'allocation_by_consumption',
            'required': Eval('allocation_rule') == 'allocation_by_consumption',
            })

    reg_ex_object = fields.Char("Reg. Ex. Object",
        help="Regular expression to find the object. For Example '[1-9/ ]*Apartement[1-9()# ]*' to find the object with name contains '100/100 Apartement #45'.",
        states={
            'invisible': Eval('allocation_rule') == 'no_allocation',
            })

    reg_ex_meter = fields.Char("Reg. Ex. Meter",
        help="Regular expression to find the meter. For Example '[1-9/ ]*Electricity[1-9a-Z()# ]*' to find the meter with name contains '556 Electricity Meter'.",
        states={
            'invisible': Eval('allocation_rule') != 'allocation_by_consumption',
            })

    objects = fields.Function(fields.One2Many('real_estate.base_object', None, 'Objects',
                                              readonly=True,
        states={
            'invisible': ((Eval('allocation_rule') == 'no_allocation') | (Eval('state') == 'billed')),
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
        'on_change_with_invoice_lines')

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
        ]

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
    def get_states():
        pool = Pool()
        BillingUnit = pool.get('real_estate.billing_unit')
        return BillingUnit.fields_get(['state'])['state']['selection']

    @staticmethod
    def get_sub_states():
        pool = Pool()
        CostShare = pool.get('real_estate.cost_share')
        return CostShare.fields_get(['state'])['state']['selection']

    @fields.depends('type', 'sequence')
    def on_change_type(self):
        if self.type and not self.sequence:
            self.sequence = self.type.sequence

    @fields.depends('billing_unit')
    def on_change_with_state(self, name=None):
        return self.billing_unit.state if self.billing_unit else None

    def get_sub_state(self, name):
        if self.allocation_rule == 'no_allocation':
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
        elif self.vacancy == 'no_allocation':
            return 'no_allocation'
        return 'preparation'

    @fields.depends('cost_shares')
    def on_change_with_sub_state(self, name=None):
        return self.get_sub_state(name)

    @fields.depends('billing_unit')
    def on_change_with_property(self, name=None):
        return self.billing_unit.property if self.billing_unit else None

    @fields.depends('billing_unit')
    def on_change_with_company(self, name=None):
        return self.billing_unit.property.company if self.billing_unit else None

    @fields.depends('billing_unit', 'reg_ex_object', 'allocation_rule')
    def on_change_with_objects(self, name=None):
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

    @fields.depends('billing_unit', 'reg_ex_meter', 'allocation_rule', 'objects', 'meter_unit')
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

    @fields.depends('billing_unit', 'm_type', 'allocation_rule', 'objects')
    def on_change_with_measurements(self, name=None):
        measurements = []
        if self.billing_unit and self.objects and self.allocation_rule == 'allocation_by_measurement':
            measurements = Pool().get('real_estate.measurement').search([
                ('base_object', 'in', [obj.id for obj in self.objects]),
                ('m_type', '=', self.m_type),
            ], order=[('base_object', 'ASC'), ('valid_from', 'DESC')])
        return measurements

    def on_change_with_invoice_lines(self, name=None):
        invoice_lines = Pool().get('account.invoice.line').search([
            ('settlement_unit', '=', self.id),
            ('invoice.state', '!=', 'cancelled'),
        ])
        return invoice_lines

    @classmethod
    def set_objects(cls, objects, name, value):
        pass

    @classmethod
    def set_meters(cls, meters, name, value):
        pass

    @classmethod
    def set_measurements(cls, measurements, name, value):
        pass

    @fields.depends('type')
    def on_change_with_sequence(self, name=None):
        return self.type.sequence if (self.type and not self.sequence) else self.sequence

    @fields.depends('billing_unit')
    def on_change_with_start_date(self, name=None):
        return self.billing_unit.start_date if self.billing_unit else None

    @fields.depends('billing_unit')
    def on_change_with_end_date(self, name=None):
        return self.billing_unit.end_date if self.billing_unit else None

    @fields.depends('type', 'sequence')
    def on_change_with_name(self, name=None):
        return f"{self.sequence} - {self.type.name}" if self.type else f"{self.sequence} - ? "

    @fields.depends('company')
    def on_change_with_currency(self, name=None):
        return self.company.currency if self.company else None

    @fields.depends('start_date', 'end_date')
    def on_change_with_time_total(self, name=None):
        if self.start_date and self.end_date:
            return (self.end_date - self.start_date).days + 1
        return None

    def selection(self):
        """Select objects and contracts for billing using the occupancy table."""
        if self.state != 'approved' and self.state != 'selection' and self.state != 'value_share':
            raise ValidationError(gettext("Only settlement units with state 'Approved' or 'Selection' or 'Value Share' can be selected."))

        CostShare = Pool().get('real_estate.cost_share')
        if self.cost_shares:
            CostShare.delete(list(self.cost_shares))

        if self.allocation_rule == 'no_allocation':
            self.billing_unit.add_log('selection',
                f'Settlement unit {self.id}: no_allocation — selection skipped.')
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
        Tax = pool.get('account.tax')
        lines = InvoiceLine.search([
            ('settlement_unit', '=', self.id),
            ('invoice.state', '!=', 'cancelled'),
        ])
        actual = Decimal(0)
        for line in lines:
            amount = line.amount or Decimal(0)
            tax_amount = Decimal(0)
            if line.taxes:
                tax_date = (line.invoice.invoice_date
                    if line.invoice and line.invoice.invoice_date
                    else datetime.date.today())
                computed = Tax.compute(
                    list(line.taxes),
                    line.unit_price or Decimal(0),
                    line.quantity or Decimal(0),
                    tax_date,
                )
                tax_amount = sum(
                    Decimal(str(t['amount'])) for t in computed
                )

            if self.property and self.property.billing_as == 'commercial':
                actual += amount
            else:
                actual += amount + tax_amount
        self.actual_costs = actual.quantize(Decimal('0.01'))
        self.save()

    def compute_value_shares(self):
        """Compute value_share on each CostShare based on allocation_rule,
        then write value_total as the sum on this SettlementUnit."""
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

        if self.allocation_rule == 'no_allocation':
            return

        if self.allocation_rule == 'allocation_from_external_billing':
            self._compute_value_shares_external()
            return

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
                measurements = Measurement.search([
                    ('base_object', '=', cost_share.base_object.id),
                    ('m_type', '=', self.m_type.id),
                    ('valid_from', '<=', cost_share.end_date),
                ], order=[('valid_from', 'DESC')], limit=1)
                if measurements:
                    mval = float(measurements[0].value or 0)
                    value = (mval * cost_share.time_share / self.time_total
                             if self.time_total else mval)
                else:
                    error_msg = (
                        f'No measurement for {cost_share.base_object.rec_name}'
                        f' type {self.m_type.name} on {cost_share.end_date}')

            elif self.allocation_rule == 'allocation_by_consumption':
                pre_days = (self.type.reading_pre_days
                            if self.type and self.type.reading_pre_days is not None
                            else 7)
                post_days = (self.type.reading_post_days
                             if self.type and self.type.reading_post_days is not None
                             else 7)

                def _closest_reading(meter_id, target_date):
                    """Return the reading closest to target_date within the window."""
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
                n = int(abs(diff) / _cent)
                if diff > 0:
                    rows.sort(key=lambda r: r[1])
                    for i in range(n):
                        rows[i % len(rows)][1] += _cent
                else:
                    rows.sort(key=lambda r: r[1], reverse=True)
                    for i in range(n):
                        rows[i % len(rows)][1] -= _cent
            return rows

        planned_rows = _distribute(self.planned_costs or Decimal(0))
        actual_rows = _distribute(self.actual_costs or Decimal(0))

        actual_by_id = {r[0].id: r[1] for r in actual_rows}
        for cost_share, planned_amount in planned_rows:
            cost_share.planned_costs = planned_amount
            cost_share.actual_costs = actual_by_id.get(cost_share.id, Decimal(0))
            cost_share.save()

    def _compute_value_shares_external(self):
        """For allocation_from_external_billing: use manually entered actual_costs
        and planned_costs on each CostShare directly. No proportional distribution."""
        CostShare = Pool().get('real_estate.cost_share')
        cost_shares = CostShare.search([('settlement_unit', '=', self.id)])
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

    def billing(self, selection_on=False):
        if self.state == 'billed':
            raise ValidationError(gettext("This settlement unit is already billed."))
        if self.state != 'draft':
            raise ValidationError(gettext("Only settlement unit with state 'Approved' can be billed."))

        if selection_on:
            if self.allocation_rule != 'no_allocation':
                self.selection()

    @classmethod
    def name_search(cls, name, clause):
        if clause[1].startswith('!') or clause[1].startswith('not '):
            bool_op = 'AND'
        else:
            bool_op = 'OR'

        return [bool_op,
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
