'Contract Item'
from trytond.model import (sequence_ordered,
    ModelSQL, ModelView, Unique, fields)
from trytond.model.exceptions import ValidationError
from trytond.exceptions import UserWarning
from trytond.i18n import gettext
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Bool, Eval, If
from trytond.transaction import Transaction

import logging

logger = logging.getLogger(__name__)


class ContractItemOccupancyWarning(UserWarning):
    pass


#**********************************************************************
class ContractItemObject(sequence_ordered(), ModelSQL, ModelView):
    "Contract Item Object"
    __name__ = 'real_estate.contract.item.object'

    item = fields.Many2One('real_estate.contract.item', 'Item',
        required=True, ondelete='CASCADE')
    property = fields.Function(
        fields.Many2One('real_estate.base_object', 'Property'),
        'on_change_with_property')
    occupancy = fields.Function(
        fields.Boolean('Occupancy'),
        'on_change_with_occupancy')
    object = fields.Many2One('real_estate.base_object', 'Object',
        required=True, ondelete='CASCADE',
        domain=[
            If(Bool(Eval('occupancy')), ('type', '=', 'object'), ()),
            If(Bool(Eval('property')), ('property', '=', Eval('property')), ()),
        ],
        context={
            # Lets the object search dialog's 'Occupancy' column show the
            # rented/vacant/under-negotiation state as of this item's own
            # valid_from, not just today - see
            # BaseObject.get_occupancy_state.
            'occupancy_date': Eval('_parent_item', {}).get('valid_from'),
        },
        depends=['item', '_parent_item.valid_from'])

    @classmethod
    def __setup__(cls):
        super().__setup__()
        t = cls.__table__()
        cls._sql_constraints = [
            ('item_object_unique', Unique(t, t.item, t.object),
                'real_estate.msg_contract_item_object_unique'),
            ]

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

    @fields.depends('item', '_parent_item.contract')
    def on_change_with_occupancy(self, name=None):
        if self.item and self.item.contract and self.item.contract.c_type:
            return self.item.contract.c_type.occupancy
        return False

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
    # Many2Many (not One2Many) on purpose, even though the relation model
    # ('real_estate.contract.item.object', unchanged) is the same either
    # way: a Many2Many widget shows the TARGET model's own list/form views
    # (real_estate.base_object - including its 'Belegung' column and full
    # form on double-click), whereas a One2Many widget would show the
    # relation model's own (much sparser) views instead.
    objects = fields.Many2Many(
        'real_estate.contract.item.object', 'item', 'object', 'Objects',
        order=[('sequence', 'ASC')],
        domain=[
            If(Bool(Eval('occupancy')), ('type', '=', 'object'), ()),
            If(Bool(Eval('property')), ('property', '=', Eval('property')), ()),
        ],
        context={
            # Shows the object search/list's 'Occupancy' column as of this
            # item's own valid_from, not just today - see
            # BaseObject.get_occupancy_state. Own field here (no
            # '_parent_' needed), since 'valid_from' lives directly on
            # this same model.
            'occupancy_date': Eval('valid_from'),
        },
        depends=['valid_from'])
    terms = fields.One2Many('real_estate.contract.term', 'reference_item', 'Terms',
        states={
            # Adding a term here implicitly sets 'reference_item' to this
            # (not-yet-saved) item, which then can't resolve related data
            # (measurements, objects, ...) needed for term calculations -
            # so require the item to be saved first (Ctrl+S); the list
            # itself stays visible, just not editable, until then.
            'readonly': Eval('id', 0) <= 0,
        },
        help="Terms referencing this item. Save the item first (Ctrl+S) "
             "before adding terms here.")
    current_terms = fields.Function(fields.One2Many(
            'real_estate.contract.term', None, "Current Terms",
            readonly=True,
            help="Terms of this item valid on the contract's key date (see "
                 "'Current Terms' on the contract). Terms are added and "
                 "removed on the contract."),
        'get_current_terms')
    valid_from = fields.Date('Valid from', required=True)
    valid_to = fields.Date('Valid to')

    name = fields.Function(fields.Char("Name"),
                                'on_change_with_name',
                                searcher='compute_name_search')

    property = fields.Function(fields.Many2One('real_estate.base_object', 'Property'),
        'on_change_with_property')

    occupancy = fields.Function(
        fields.Boolean('Occupancy'),
        'on_change_with_occupancy')

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
        for obj in (self.objects or []):
            children.extend(obj.children)
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
        first = self.objects[0] if self.objects else None
        if first:
            return first.name + ' ( ' + (first.object_number or '') + ' )'
        return ' - '

    @fields.depends('label', 'objects')
    def on_change_objects(self):
        if not self.label and self.objects:
            first = self.objects[0]
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

    @fields.depends('contract')
    def on_change_with_occupancy(self, name=None):
        if self.contract and self.contract.c_type:
            return self.contract.c_type.occupancy
        return False

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
            obj.id
            for item in items
            for obj in (item.objects or [])
        }
        if not all_obj_ids:
            return result
        measurements = Measurement.search([('base_object', 'in', list(all_obj_ids))])
        obj_to_meas = {}
        for m in measurements:
            obj_to_meas.setdefault(m.base_object.id, []).append(m.id)
        for item in items:
            meas_ids = []
            for obj in (item.objects or []):
                meas_ids.extend(obj_to_meas.get(obj.id, []))
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
            ('objects.name',) + tuple(clause[1:]),
            ('objects.object_number',) + tuple(clause[1:]),
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
        """Only meaningful while occupancy tracking applies (occupancy
        contract type, not cancelled) - and only checkable dynamically at
        save time, since it depends on this item's own valid_from/valid_to
        range overlapping OTHER contracts' occupancy periods, not on any
        single field's static value (hence no plain 'domain' on a field
        can express it - see ContractItemObject.object's domain, which
        only restricts object type/property, nothing occupancy-related).

        An overlap with an already 'rented' period is a hard error (two
        firm tenancies can't coexist). An overlap with an 'under
        negotiation' period is only a soft, confirmable warning - that
        other prospect may still fall through, so the user should be able
        to proceed deliberately instead of being blocked outright."""
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
        Warning = pool.get('res.user.warning')

        date_from = item.valid_from.isoformat() if item.valid_from else '?'
        date_to = item.valid_to.isoformat() if item.valid_to else 'open'

        for obj in item.objects:
            base_domain = [
                ('base_object', '=', obj.id),
                ('contract', '!=', item.contract.id),
                ['OR', ('end_date', '=', None), ('end_date', '>=', item.valid_from)],
            ]
            if item.valid_to:
                base_domain.append(('start_date', '<=', item.valid_to))

            if BaseObjectOccupancy.search(
                    base_domain + [('state', '=', 'rented')]):
                raise ValidationError(
                    gettext('real_estate.msg_occupancy_overlap').format(
                        obj.rec_name, date_from, date_to))

            if BaseObjectOccupancy.search(
                    base_domain + [('state', '=', 'under_negotiation')]):
                # 'obj' only, not 'item', in the key: for a brand-new item
                # (created together with a new contract in one go), 'item'
                # has no stable id yet across a warned-then-retried
                # create() - PostgreSQL sequences aren't rolled back, so a
                # retry after confirming would get a different id and the
                # confirmed key would never match, looping forever (see
                # Contract._check_party_roles for the same issue/fix).
                # 'obj' is always a pre-existing, already-saved object.
                key = Warning.format(
                    'occupancy_overlap_under_negotiation', [obj])
                if Warning.check(key):
                    raise ContractItemOccupancyWarning(key, gettext(
                        'real_estate.msg_occupancy_overlap_warning').format(
                            obj.rec_name, date_from, date_to))

    def get_current_terms(self, name=None):
        if not self.contract:
            return []
        key_date = self.contract.on_change_with_current_terms_date()
        terms = [t for t in (self.terms or [])
            if t.valid_from and t.valid_from <= key_date
            and (not t.valid_to or t.valid_to >= key_date)]
        terms.sort(key=lambda t: (t.sequence is None, t.sequence or 0))
        return [t.id for t in terms]

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
        pool = Pool()
        Term = pool.get('real_estate.contract.term')
        # An item may only be deleted once no term references it any more
        # (clear message instead of the database's foreign key error)
        for record in records:
            terms = Term.search([('reference_item', '=', record.id)])
            if terms:
                raise ValidationError(gettext(
                    'real_estate.msg_item_delete_has_terms',
                    item=record.rec_name,
                    terms=', '.join(t.rec_name.strip() for t in terms)))
        base_object_ids = {o.id for r in records for o in r.objects}
        super().delete(records)
        if base_object_ids:
            cls._refresh_occupancy_by_ids(base_object_ids)

    @classmethod
    def _refresh_occupancy(cls, items):
        base_object_ids = {o.id for r in items for o in r.objects}
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
