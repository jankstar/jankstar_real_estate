
from trytond.model import (
    DeactivableMixin, Index, ModelSQL, ModelView, fields, Unique, Check, sequence_ordered,
    sum_tree, tree)
from trytond.model.exceptions import ValidationError
from trytond.i18n import gettext
from trytond.cache import Cache
from trytond.report import Report
from trytond.pool import Pool
from trytond.transaction import Transaction
from trytond.pyson import Bool, Eval, If, PYSONEncoder, TimeDelta
from trytond.pool import PoolMeta
from trytond.i18n import lazy_gettext
from sql import Column

from .base_object import BaseObject

import logging

logger = logging.getLogger(__name__)


class MeasurementType(DeactivableMixin, sequence_ordered(), ModelSQL, ModelView):
    __name__ = 'real_estate.measurement.type'

    _get_default_type_cache = Cache('real_estate_measurement_type.get_default_type')
    _get_window_domains_cache = Cache('real_estate_measurement_type.get_window_domains')

    types = fields.MultiSelection(
        'get_types', "Types",
        help="The type of object which can use this measurement.")
    name = fields.Char("Name", required=True, translate=True)
    unit = fields.Many2One('product.uom', "Unit", required=True)
    default = fields.Boolean(
        "Default",
        help="Check to use as default status for the type.")
    
    no_print = fields.Boolean("No Print")


    @classmethod
    def get_types(cls):
        pool = Pool()
        BaseObject = pool.get('real_estate.base_object')
        return BaseObject.fields_get(['type'])['type']['selection']

    @classmethod
    def get_default_type(cls, type_=None):
        if type_ is None:
            return None
        myType = cls._get_default_type_cache.get(type_, -1)
        if myType != -1:
            return myType
        records = cls.search([
                ('types', 'in', type_),
                ('default', '=', True)
                ], limit=1)
        if records:
            myType = records[0].id
        else:
            myType = None
        cls._get_default_status_cache.set(type, myType)
        return myType

    @classmethod
    def on_modification(cls, mode, records, field_names=None):
        super().on_modification(mode, records, field_names=field_names)
        cls._get_default_type_cache.clear()
        cls._get_window_domains_cache.clear()

    @classmethod
    def get_window_domains(cls, action):
        pool = Pool()
        Data = pool.get('ir.model.data')
        if action.id == Data.get_id('base_object', 'act_property_tree'):
            return cls._get_window_domains([x[0] for x in cls.get_types()])
        elif action.id == Data.get_id('base_object', 'act_property_form'):
            return cls._get_window_domains(['property'])
        elif action.id == Data.get_id('base_object', 'act_building_form'):
            return cls._get_window_domains(['building'])
        else:
            return []

    @classmethod
    def _get_window_domains(cls, types):
        key = tuple(sorted(types))
        domains = cls._get_window_domains_cache.get(key)
        if domains is not None:
            return domains
        encoder = PYSONEncoder()
        domains = []
        for myTypes in cls.search([('types', 'in', types)]):
            domain = encoder.encode([('type', '=', myTypes.id)])
            domains.append((myTypes.name, domain, myTypes.count))
        if domains:
            domains.append(
                (gettext('base_object.msg_domain_all'), '[]', False))
        cls._get_window_domains_cache.set(key, domains)
        return domains


class Measurement(DeactivableMixin, ModelSQL, ModelView, metaclass=PoolMeta):
    "Measurement"
    __name__ = 'real_estate.measurement'
    _rec_name = 'name'


    base_object = fields.Many2One('real_estate.base_object', 
        "Base Object", required=True, path='path', ondelete='CASCADE',)
    valid_from = fields.Date('From', required=True)
    m_type = fields.Many2One(
        'real_estate.measurement.type', "Measurement Type", required=True,
        domain=[If(Bool(Eval('type')), ('types', 'in', Eval('type')), ())])
    value = fields.Float('Value', required=True)
    symbol = fields.Function(fields.Char("Symbol"), 
                                'on_change_with_symbol') 
    name = fields.Function(fields.Char("Name"), 
                                'on_change_with_name', 
                                searcher='compute_name_search')   

    type = fields.Function(fields.Char("Object Type"), 
                                'on_change_with_type') 
    
    no_print = fields.Boolean("No Print")

    @fields.depends('m_type')
    def on_change_with_name(self, name=None):
        if self.m_type:
            return f"{self.m_type.name} - {self.m_type.unit.symbol}"
        return f" - "
    
    @fields.depends('m_type')
    def on_change_with_symbol(self, name=None):
        if self.m_type:
            return self.m_type.unit.symbol
        return f" - "

    @fields.depends('m_type')
    def on_change_with_no_print(self, name=None):
        if self.m_type:
            return self.m_type.no_print
        return self.no_print
    
    @fields.depends('base_object')
    def on_change_with_type(self, name=None):
        if self.base_object:
            return self.base_object.type
        return None

    @fields.depends('base_object', 'type', 'valid_from')
    def on_change_base_object(self, name=None):
        if self.base_object != None:
            self.type = self.base_object.type
            self.valid_from = self.base_object.start_date

    # @fields.depends('base_object', 'valid_from')
    # def on_change_with_start_date(self, name=None):
    #     if self.base_object != None and self.valid_from == None and hasattr(self.base_object, 'start_date'):
    #         return self.base_object.start_date
    #     return self.valid_from

    @classmethod
    def __setup__(cls):
        super().__setup__()
        t = cls.__table__()
        cls._sql_constraints = [
            ('m_type_unique', Unique(t, t.m_type, t.base_object, t.valid_from), "valid_from, type and base object must be unique!"),
        ]

    @classmethod
    def validate_fields(cls, instances, fields):
        super().validate_fields(instances,fields)
        for self in instances:
            if 'valid_from' in fields and self.base_object != None:
                if self.valid_from != None:
                    if self.base_object.start_date != None and self.valid_from < self.base_object.start_date :
                        raise ValidationError(self.name + ": "+
                                            "Valid from (" + BaseObject.date2string(self.valid_from) + ") must be greater or equal than base object start date (" + 
                                            BaseObject.date2string(self.base_object.start_date) + ")!")
                    if self.base_object.end_date != None and self.valid_from > self.base_object.end_date :
                            raise ValidationError(self.name + ": "+
                                                "Valid from (" + BaseObject.date2string(self.valid_from) + ") must be less or equal than base object end date (" + 
                                                BaseObject.date2string(self.base_object.end_date) + ")!")
    @classmethod
    def compute_name_search(cls, name, clause):
        if clause[1].startswith('!') or clause[1].startswith('not '):
            bool_op = 'AND'
        else:
            bool_op = 'OR'

        if hasattr(cls, 'm_type'):
            return [bool_op,
                ('m_type.name',) + tuple(clause[1:]),
                ('m_type.unit',) + tuple(clause[1:]),
                ('valde_from',) + tuple(clause[1:]),
                ]
        return []    