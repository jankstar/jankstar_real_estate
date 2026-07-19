'Contract Item'
from trytond.model import (sequence_ordered,
    ModelSQL, ModelView, fields)
from trytond.model.exceptions import ValidationError
from trytond.i18n import gettext
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Bool, Eval, If
from trytond.transaction import Transaction

import logging

logger = logging.getLogger(__name__)


#**********************************************************************
class ContractItemObject(sequence_ordered(), ModelSQL, ModelView):
    "Contract Item Object"
    __name__ = 'real_estate.contract.item.object'

    item = fields.Many2One('real_estate.contract.item', 'Item',
        required=True, ondelete='CASCADE')
    property = fields.Function(
        fields.Many2One('real_estate.base_object', 'Property'),
        'on_change_with_property')
    object = fields.Many2One('real_estate.base_object', 'Object',
        required=True, ondelete='CASCADE',
        domain=[
            ('type', '=', 'object'),
            If(Bool(Eval('property')), ('property', '=', Eval('property')), ()),
        ])

    @classmethod
    def create(cls, vlist):
        vlist = [v.copy() for v in vlist]
        for vals in vlist:
            if not vals.get('sequence'):
                item_id = vals.get('item')
                if item_id:
                    existing = cls.search(
                        [('item', '=', item_id)],
                        order=[('sequence', 'DESC')], limit=1)
                    max_seq = existing[0].sequence if existing else 0
                else:
                    max_seq = 0
                vals['sequence'] = ((max_seq // 10) + 1) * 10
        records = super().create(vlist)
        cls._refresh_occupancy_for_items(records)
        return records

    @classmethod
    def write(cls, *args):
        old_obj_ids = set()
        actions = iter(args)
        for records, _ in zip(actions, actions):
            for r in records:
                if r.object:
                    old_obj_ids.add(r.object.id)
        super().write(*args)
        actions = iter(args)
        all_records = []
        for records, _ in zip(actions, actions):
            all_records.extend(records)
        cls._refresh_occupancy_for_items(cls.browse([r.id for r in all_records]),
            extra_obj_ids=old_obj_ids)

    @classmethod
    def delete(cls, records):
        obj_ids = {r.object.id for r in records if r.object}
        item_ids = {r.item.id for r in records if r.item}
        super().delete(records)
        if obj_ids:
            ContractItem = Pool().get('real_estate.contract.item')
            ContractItem._refresh_occupancy_by_ids(obj_ids)
            # re-validate remaining items that lost an object
            if item_ids:
                for item in ContractItem.browse(list(item_ids)):
                    ContractItem._check_occupancy_overlap(item)

    @fields.depends('item', '_parent_item.contract')
    def on_change_with_property(self, name=None):
        if self.item and self.item.contract:
            return self.item.contract.property
        return None

    @classmethod
    def _refresh_occupancy_for_items(cls, records, extra_obj_ids=None):
        pool = Pool()
        ContractItem = pool.get('real_estate.contract.item')
        obj_ids = {r.object.id for r in records if r.object}
        if extra_obj_ids:
            obj_ids.update(extra_obj_ids)
        parent_item_ids = {r.item.id for r in records if r.item}
        for item in ContractItem.browse(list(parent_item_ids)):
            ContractItem._check_occupancy_overlap(item)
        if obj_ids:
            ContractItem._refresh_occupancy_by_ids(obj_ids)


#**********************************************************************
class ContractItem(sequence_ordered(), ModelSQL, ModelView, metaclass=PoolMeta):
    "Contract Item"
    __name__ = 'real_estate.contract.item'
    __rec_name__ = 'name'

    contract = fields.Many2One('real_estate.contract', 'Contract', required=True,
         path='path', ondelete='CASCADE')
    label = fields.Char("Label")
    objects = fields.One2Many('real_estate.contract.item.object', 'item', 'Objects')
    valid_from = fields.Date('Valid from', required=True)
    valid_to = fields.Date('Valid to')

    name = fields.Function(fields.Char("Name"),
                                'on_change_with_name',
                                searcher='compute_name_search')

    property = fields.Function(fields.Many2One('real_estate.base_object', 'Property'),
        'on_change_with_property')

    company = fields.Function(fields.Many2One('company.company', 'Company'),
        'on_change_with_company')

    type_of_use = fields.Function(fields.Selection('get_type_of_use_selection',
        "Type of Use"), 'on_change_with_type_of_use')

    currency = fields.Function(fields.Many2One('currency.currency',
        'Currency'), 'on_change_with_currency')

    children = fields.Function(
        fields.One2Many('real_estate.base_object', None, 'Children'),
        'on_change_with_children', setter='set_children')

    measurements = fields.Function(
        fields.One2Many('real_estate.measurement', None, 'Measurements'),
        'get_measurements', setter='set_measurements')

    @fields.depends('objects')
    def on_change_with_children(self, name=None):
        children = []
        for item_obj in (self.objects or []):
            if item_obj.object:
                children.extend(item_obj.object.children)
        return children

    @fields.depends(
        'contract', 'sequence',
        '_parent_contract.next_item_sequence', '_parent_contract.c_type')
    def on_change_with_sequence(self, name=None):
        if (self.sequence is not None and self.sequence != 0):
            return self.sequence

        if self.contract is not None and self.contract.next_item_sequence:
            return self.contract.next_item_sequence

        return self.contract.c_type.step_item if self.contract and self.contract.c_type else 1

    @fields.depends('label', 'objects')
    def on_change_with_name(self, name=None):
        if self.label:
            return self.label
        first = self.objects[0].object if self.objects else None
        if first:
            return first.name + ' ( ' + (first.object_number or '') + ' )'
        return ' - '

    @fields.depends('label', 'objects')
    def on_change_objects(self):
        if not self.label and self.objects:
            first = self.objects[0].object
            if first:
                self.label = first.name

    @fields.depends('contract', 'valid_from', '_parent_contract.start_date')
    def on_change_contract(self, name=None):
        if self.contract is not None and self.valid_from is None:
            self.valid_from = self.contract.start_date

    @fields.depends('contract', '_parent_contract.property')
    def on_change_with_property(self, name=None):
        if self.contract:
            return self.contract.property
        return None

    @fields.depends('contract', '_parent_contract.currency')
    def on_change_with_currency(self, name=None):
        return self.contract.currency if self.contract else None

    @fields.depends('contract', '_parent_contract.company')
    def on_change_with_company(self, name=None):
        if self.contract:
            return self.contract.company
        return None

    @classmethod
    def get_measurements(cls, items, name):
        pool = Pool()
        Measurement = pool.get('real_estate.measurement')
        result = {item.id: [] for item in items}
        all_obj_ids = {
            io.object.id
            for item in items
            for io in (item.objects or [])
            if io.object
        }
        if not all_obj_ids:
            return result
        measurements = Measurement.search([('base_object', 'in', list(all_obj_ids))])
        obj_to_meas = {}
        for m in measurements:
            obj_to_meas.setdefault(m.base_object.id, []).append(m.id)
        for item in items:
            meas_ids = []
            for io in (item.objects or []):
                if io.object:
                    meas_ids.extend(obj_to_meas.get(io.object.id, []))
            result[item.id] = meas_ids
        return result

    @classmethod
    def get_type_of_use_selection(cls):
        pool = Pool()
        BaseObject = pool.get('real_estate.base_object')
        return BaseObject.fields_get(['type_of_use'])['type_of_use']['selection']

    @fields.depends('contract', '_parent_contract.type_of_use')
    def on_change_with_type_of_use(self, name=None):
        if self.contract:
            return self.contract.type_of_use
        return None

    @classmethod
    def compute_name_search(cls, name, clause):
        if clause[1].startswith('!') or clause[1].startswith('not '):
            bool_op = 'AND'
        else:
            bool_op = 'OR'

        return [bool_op,
            ('label',) + tuple(clause[1:]),
            ('objects.object.name',) + tuple(clause[1:]),
            ('objects.object.object_number',) + tuple(clause[1:]),
        ]

    @classmethod
    def validate_fields(cls, instances, fields):
        super().validate_fields(instances, fields)
        for item in instances:
            if {'valid_from', 'valid_to', 'objects'} & set(fields):
                cls._check_occupancy_overlap(item)
            if 'valid_from' not in fields:
                continue
            if item.valid_from is None or item.contract is None:
                continue
            if item.contract.start_date and item.valid_from < item.contract.start_date:
                raise ValidationError(
                    gettext('real_estate.msg_item_valid_from_before_contract_start').format(
                        item.rec_name,
                        item.valid_from.isoformat(),
                        item.contract.start_date.isoformat()))
            if item.contract.get_effective_end_date() and item.valid_from > item.contract.get_effective_end_date():
                raise ValidationError(
                    gettext('real_estate.msg_item_valid_from_after_contract_end').format(
                        item.rec_name,
                        item.valid_from.isoformat(),
                        item.contract.get_effective_end_date().isoformat()))

    @classmethod
    def set_children(cls, record, name, value):
        pass

    @classmethod
    def set_measurements(cls, records, name, value):
        pass

    @classmethod
    def _check_occupancy_overlap(cls, item):
        if not item.contract or not item.contract.c_type:
            return
        if not item.contract.c_type.occupancy:
            return
        if not item.objects:
            return
        contract_state = item.contract.state or 'draft'
        if contract_state == 'cancelled':
            return

        pool = Pool()
        BaseObjectOccupancy = pool.get('real_estate.base_object.occupancy')

        for item_obj in item.objects:
            if not item_obj.object:
                continue
            domain = [
                ('base_object', '=', item_obj.object.id),
                ('state', 'in', ('rented', 'under_negotiation')),
                ('contract', '!=', item.contract.id),
                ['OR', ('end_date', '=', None), ('end_date', '>=', item.valid_from)],
            ]
            if item.valid_to:
                domain.append(('start_date', '<=', item.valid_to))

            if not BaseObjectOccupancy.search(domain):
                continue

            obj_name = item_obj.object.rec_name
            date_from = item.valid_from.isoformat() if item.valid_from else '?'
            date_to = item.valid_to.isoformat() if item.valid_to else 'open'

            raise ValidationError(
                gettext('real_estate.msg_occupancy_overlap').format(
                    obj_name, date_from, date_to))

    @classmethod
    def create(cls, vlist):
        records = super().create(vlist)
        cls._refresh_occupancy(records)
        return records

    @classmethod
    def write(cls, *args):
        actions = iter(args)
        old_ids = set()
        re_calc_contract_ids = set()
        for records, values in zip(actions, actions):
            old_ids.update(r.id for r in records)
            if not Transaction().context.get('_skip_re_calc') and \
                    {'valid_from', 'valid_to'} & set(values):
                for r in records:
                    if r.contract:
                        re_calc_contract_ids.add(r.contract.id)
        super().write(*args)
        updated = cls.browse(list(old_ids))
        cls._refresh_occupancy(updated)
        if re_calc_contract_ids:
            Contract = Pool().get('real_estate.contract')
            Contract._re_calc_terms(Contract.browse(list(re_calc_contract_ids)))

    @classmethod
    def delete(cls, records):
        base_object_ids = {
            o.object.id for r in records for o in r.objects if o.object}
        super().delete(records)
        if base_object_ids:
            cls._refresh_occupancy_by_ids(base_object_ids)

    @classmethod
    def _refresh_occupancy(cls, items):
        base_object_ids = {
            o.object.id for r in items for o in r.objects if o.object}
        cls._refresh_occupancy_by_ids(base_object_ids)

    @classmethod
    def _refresh_occupancy_by_ids(cls, base_object_ids):
        if not base_object_ids:
            return
        pool = Pool()
        BaseObjectOccupancy = pool.get('real_estate.base_object.occupancy')
        BaseObject = pool.get('real_estate.base_object')
        BaseObjectOccupancy.refresh(BaseObject.browse(list(base_object_ids)))
        cls._trigger_billing_unit_selection(base_object_ids)

    @classmethod
    def _trigger_billing_unit_selection(cls, base_object_ids):
        pool = Pool()
        BaseObject = pool.get('real_estate.base_object')
        BillingUnit = pool.get('real_estate.billing_unit')
        objects = BaseObject.browse(list(base_object_ids))
        property_ids = {o.property.id for o in objects if o.property}
        if not property_ids:
            return
        billing_units = BillingUnit.search([
            ('property', 'in', list(property_ids)),
            ('state', 'in', ['approved', 'selection', 'value_share']),
        ])
        if not billing_units:
            return
        BillingUnit.selection(billing_units)
        refreshed = BillingUnit.browse([bu.id for bu in billing_units])
        compute_units = [bu for bu in refreshed if bu.state in ('selection', 'value_share')]
        if compute_units:
            BillingUnit.compute_value_shares_button(compute_units)
