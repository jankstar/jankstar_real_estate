'Contract Item'
from trytond.model import (sequence_ordered,
    ModelSQL, ModelView, fields)
from trytond.model.exceptions import ValidationError
from trytond.i18n import gettext
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Eval

import logging

logger = logging.getLogger(__name__)


#**********************************************************************
class ContractItem(sequence_ordered(), ModelSQL, ModelView, metaclass=PoolMeta):
    "Contract Item"
    __name__ = 'real_estate.contract.item'
    __rec_name__ = 'name'

    contract = fields.Many2One('real_estate.contract', 'Contract', required=True,
         path='path', ondelete='CASCADE')
    object = fields.Many2One('real_estate.base_object', 'Object', required=True,
            ondelete='CASCADE',
            domain=[('type', 'in', ('object',)),
                    ('type_of_use', '=', Eval('type_of_use', -1)),
                    ('property', '=', Eval('property', -1)),
                    ('company', '=', Eval('company', -1)),
                    ],)
    valid_from = fields.Date('Valid from', required=True)
    valid_to = fields.Date('Valid to')

    name = fields.Function(fields.Char("Name"),
                                'on_change_with_name',
                                searcher='compute_name_search')

    property = fields.Function(fields.Many2One('real_estate.base_object', 'Property'),
        'on_change_with_property')

    company = fields.Function(fields.Many2One('company.company', 'Company'),
        'on_change_with_company')

    type_of_use = fields.Function(fields.Char("Type of Use"),
        'on_change_with_type_of_use')

    currency = fields.Function(fields.Many2One('currency.currency',
        'Currency'), 'on_change_with_currency')

    children = fields.Function(
        fields.One2Many('real_estate.base_object', None,
                        'Children',)
        , 'on_change_with_children', setter='set_children')

    @fields.depends('object')
    def on_change_with_children(self, name=None):
        if self.object:
            return self.object.children
        return []

    @fields.depends('contract', 'sequence')
    def on_change_with_sequence(self, name=None):
        if (self.sequence is not None and self.sequence != 0):
            return self.sequence

        if self.contract is not None and self.contract.next_item_sequence:
            return self.contract.next_item_sequence

        return self.contract.c_type.step_item if self.contract and self.contract.c_type else 1

    @fields.depends('object')
    def on_change_with_name(self, name=None):
        if self.object:
            return self.object.name + ' ( ' + self.object.object_number + ' )'
        return f" - "

    @fields.depends('contract', 'valid_from')
    def on_change_contract(self, name=None):
        if self.contract is not None and self.valid_from is None:
            self.valid_from = self.contract.start_date

    @fields.depends('contract')
    def on_change_with_property(self, name=None):
        if self.contract:
            return self.contract.property
        return None

    @fields.depends('contract')
    def on_change_with_currency(self, name=None):
        return self.contract.currency if self.contract else None

    @fields.depends('contract')
    def on_change_with_company(self, name=None):
        if self.contract:
            return self.contract.company
        return None

    @fields.depends('contract')
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
            ('object.name',) + tuple(clause[1:]),
            ('object.object_number',) + tuple(clause[1:]),
        ]

    @classmethod
    def validate_fields(cls, instances, fields):
        super().validate_fields(instances, fields)
        for item in instances:
            if {'valid_from', 'valid_to', 'object'} & set(fields):
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
    def _check_occupancy_overlap(cls, item):
        if not item.contract or not item.contract.c_type:
            return
        if not item.contract.c_type.occupancy:
            return
        if not item.object:
            return
        contract_state = item.contract.state or 'draft'
        if contract_state == 'cancelled':
            return

        # Use the already-computed occupancy table: it correctly accounts for
        # termination dates, draft-state (under_negotiation), and only
        # includes occupancy-type contracts.
        pool = Pool()
        BaseObjectOccupancy = pool.get('real_estate.base_object.occupancy')

        domain = [
            ('base_object', '=', item.object.id),
            ('state', 'in', ('rented', 'under_negotiation')),
            ('contract', '!=', item.contract.id),
            ['OR', ('end_date', '=', None), ('end_date', '>=', item.valid_from)],
        ]
        if item.valid_to:
            domain.append(('start_date', '<=', item.valid_to))

        if not BaseObjectOccupancy.search(domain):
            return

        obj_name = item.object.rec_name
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
        base_object_ids = {r.object.id for r in records if r.object}
        super().delete(records)
        if base_object_ids:
            cls._refresh_occupancy_by_ids(base_object_ids)

    @classmethod
    def _refresh_occupancy(cls, items):
        base_object_ids = {r.object.id for r in items if r.object}
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
