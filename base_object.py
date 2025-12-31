
'Base Object'
from trytond.model import (sequence_ordered, 
    DeactivableMixin, Index, ModelSQL, ModelView, Workflow, fields, Unique, Check,
    sum_tree, tree)
from trytond.model.exceptions import ValidationError
from trytond.i18n import gettext
from trytond.cache import Cache
from trytond.report import Report
from trytond.pool import Pool
from trytond.transaction import Transaction
from trytond.pyson import Bool, Eval, If, PYSONEncoder, TimeDelta, Equal
from trytond.pool import PoolMeta
from trytond.i18n import lazy_gettext
from trytond.modules.company import CompanyReport

from sql import Column

import logging

logger = logging.getLogger(__name__)

def re_sequence_ordered(
        field_name='sequence',
        field_label=lazy_gettext('ir.msg_sequence'),
        order='ASC NULLS FIRST'):
    "Returns a mixin to order the model by order fields"
    assert order.startswith('ASC')

    class SequenceOrderedMixin(object):
        "Mixin to order model by a sequence field"
        __slots__ = ()

        @classmethod
        def __setup__(cls):
            super().__setup__()
            table = cls.__table__()
            cls._order = [(field_name, order)] + cls._order
            cls._sql_indexes.add(
                Index(table,
                    (Column(table, field_name), Index.Range(order=order)),
                    (table.id, Index.Range(order=order))))

    setattr(SequenceOrderedMixin, field_name, fields.Integer(field_label, required=True))
    return SequenceOrderedMixin

class BaseObject(Workflow,DeactivableMixin, re_sequence_ordered(), tree(separator='\\'), ModelSQL, ModelView):
    "Base Object - base class for real estate objects"
    __name__ = 'real_estate.base_object'
    __rec_name__ = 'compute_name'

    name = fields.Char("Description", required=True)
    type = fields.Selection([
            ('property', 'Property'),
            ('land', 'Land'),
            ('building', 'Building'),
            ('object', 'Rental Object'),
            ('equipment', 'Equipment'),
            ],
        "Type", 
        translate=True,
        required=True,
                #  domain=[
                #     If(Bool(Equal( Eval('parent.type', ''), '')), ('type', '=', 'property' ),(),),
                #     If(Bool(Equal( Eval('parent.type'), 'property')), ('type', 'in', ('building', 'land', 'object', 'equipment') ),(),),
                #     If(Bool(Equal( Eval('parent.type'), 'building')), ('type', 'in', ('object', 'equipment') ), (),),
                #     If(Bool(Equal( Eval('parent.type'), 'land')), ('type', 'in', ('object', 'equipment' ) ), (), ),
                #     If(Bool(Equal( Eval('parent.type'), 'object')), ('type', '=', 'equipment' ), (), ),
                #     If(Bool(Equal( Eval('parent.type'), 'equipment')), ('type', '=', 'equipment' ), (), ),
                # # ('type', 'in', ('property', 'building', 'land', 'object', 'equipment')),
                #  ],
            sort=False)
    
    type_of_use = fields.Selection([
            ('residential', 'Residential'),
            ('commercial', 'Commercial'),
            ('property', 'Residential property'),
            ('internal', 'Internal Use'),
            (None, 'None'),
            ],
        "Type of Use", 
        translate=True,
        states={
            'invisible': Eval('type') != 'object',
            'required': Eval('type') == 'object',
            },
            sort=False)

    use_class = fields.Selection([
            ('apartment', 'Apartment'),
            ('office', 'Office'),
            ('retail', 'Retail'),
            ('warehouse', 'Warehouse'),
            ('parking', 'Parking'),
            ('garage', 'Garage'),
            (None, 'None'),
            ],
        "Use", 
        translate=True,
        states={
            'invisible': Eval('type') != 'object',
            'required': Eval('type') == 'object',
            },
            sort=False)


    company = fields.Many2One('company.company', "Company", required=True, ondelete='CASCADE')
    start_date = fields.Date("Start Date", required=True)
    end_date = fields.Date("End Date")
    address = fields.Many2One('real_estate.address', 'Address', required=False)
    comment = fields.Text("Comment")
    compute_name = fields.Function(fields.Char("Name"), 
                                   'on_change_with_compute_name', 
                                   searcher='compute_name_search')    
    property = fields.Many2One('real_estate.base_object','Property',
        states={'invisible': ( Eval('type') == 'property' or Eval('type', -1) == -1 ),
                'readonly': True, },
    )
    
    object_number = fields.Char("No",
        states={ 'readonly': True, })

    parent = fields.Many2One(
        'real_estate.base_object', 'Parent', path='path', ondelete='RESTRICT',
        domain=[
            ('company', '=', Eval('company', -1)),
            If(Bool(Equal( Eval('type'), 'building')), ('type', 'in', ('property', 'building') ), ()),
            If(Bool(Equal( Eval('type'), 'land')), ('type', '=', 'property' ), ()),
            If(Bool(Equal( Eval('type'), 'object')), ('type', 'in', ('property', 'building', 'land') ), ()),
            If(Bool(Equal( Eval('type'), 'equipment')), ('type', 'in', ('building', 'land', 'object', 'equipment') ), ()),],
        states={
            'invisible': ( Eval('type') == 'property' or Eval('type', -1) == -1 ),
            'required': Eval('type') != 'property',
            })
    path = fields.Char("Path")
    children = fields.One2Many('real_estate.base_object', 'parent', 'Children',
        domain=[
            ('company', '=', Eval('company', -1)),
            ])

    state = fields.Selection([
            ('draft', 'Draft'),
            ('approved', 'Approved'),
            ('locked', 'Locked'),
            ('deactivated', 'Deactivated'),
            ], "State",  required=True, sort=False)


    number_of_objects = fields.Function(fields.Integer("Number of Sub-Objects"), 'get_number_of_objects')

    
    measurements = fields.One2Many('real_estate.measurement', 'base_object', 'Measurements',)

    parties = fields.One2Many('real_estate.object_party', 'base_object', 'Parties',)

    ## special data building
    _states_only_building= {
            'invisible': Eval('type') != 'building',
            }
    
    year_of_construction = fields.Char("Year of Construction", size=4,
        states={
            'invisible': Eval('type') != 'building',
            })
    
    number_of_floors = fields.Integer("Number of Floors",
        states={
            'invisible': Eval('type') != 'building',
            })
    
    ## special data rental object
    _states_only_object= {
            'invisible': Eval('type') != 'object',
            }
    floor = fields.Integer("Floor",
        states={
            'invisible': Eval('type') != 'object',
            })
    basement_nr = fields.Char("Basement Number", size=10,
        states={
            'invisible': Eval('type') != 'object',
            })

    @classmethod
    def view_attributes(cls):
        return super().view_attributes() + [('/form/notebook/page[@id="page_building"]', 'states', cls._states_only_building),
               ('/form/notebook/page[@id="page_object"]', 'states', cls._states_only_object)]


    @classmethod
    def __setup__(cls):
        super().__setup__()
        table = cls.__table__()
        cls._sql_constraints = [
            ('sequence_unique', Unique(table, table.sequence, table.type, table.parent), "sequence by type and parent must be unique!"),
            ('sequence_check', Check(table, table.sequence > 0), "sequence must not be null!"),
        ]
        cls._sql_indexes.add(
            Index(
                table,
                (table.state, Index.Equality(cardinality='low')),
                where=table.state.in_(['draft', 'approved', 'locked', 'deactivated']),))
        cls._transitions |= set((
                ('draft', 'approved'),
                ('approved', 'locked'),
                ('approved', 'draft'),                
                ('locked', 'approved'),
                ('locked', 'deactivated'),
                ))  
        cls._buttons.update({
                'draft': {
                    'invisible': Eval('state') in ('draft', 'deactivated', 'locked'),
                    'depends': ['state'],
                    },
                'approved': {
                    'invisible': Eval('state') in ('approved', 'deactivated'),
                    'depends': ['state'],
                    },
                'locked': {
                    'invisible': Eval('state') in ('locked', 'deactivated', 'draft'),
                    'depends': ['state'],
                    },
                'deactivated': {
                    'invisible': Eval('state') != 'locked',
                    'depends': ['state'],
                    },                })              
       
    @classmethod
    def default_company(cls):
        return Transaction().context.get('company')

    @staticmethod
    def default_state():
        return 'draft'

    @classmethod
    def date2string(cls, date):
        User = Pool().get('res.user')
        user = User(Transaction().user)
        return Report.format_date(date, user.language )

   
    @classmethod
    def validate_fields(cls, instances, fields):
        super().validate_fields(instances,fields)
        for self in instances:
            if 'sequence' in fields:
                if self.sequence == None:
                    raise ValidationError(self.name + ": " + "Sequence must not be null!")
            if 'type' in fields: 
                if self.type == None  \
                    or self.parent == None and not self.type in ['property'] \
                    or self.parent != None and self.parent.type == 'property' and not self.type in ['building', 'land', 'object', 'equipment'] \
                    or self.parent != None and self.parent.type == 'land' and not self.type in ['object', 'equipment'] \
                    or self.parent != None and self.parent.type == 'building' and not self.type in ['building', 'object', 'equipment'] \
                    or self.parent != None and self.parent.type == 'object' and not self.type in [ 'equipment'] \
                    or self.parent != None and self.parent.type == 'equipment' and not self.type in [ 'equipment']     :
                    raise ValidationError(self.name + ": " + self.type + " is not a valid type!")
            if 'start_date' in fields or 'end_date' in fields:
                if self.start_date != None and self.end_date != None and self.start_date > self.end_date:
                    raise ValidationError(self.name + ": "+
                    "Start date (" + self.date2string(self.start_date) + 
                                          ") must be less than end date (" + self.date2string(self.end_date) + ")!")

            if 'start_date' in fields and self.parent != None:
                if self.start_date != None and self.parent.start_date != None and self.start_date < self.parent.start_date :
                    raise ValidationError(self.name + ": "+
                                            "Start date (" + self.date2string(self.start_date) + ") must be greater or equal than parent start date (" + 
                                            self.date2string(self.parent.start_date) + ")!") 

            if 'end_date' in fields and self.parent:
                if self.end_date != None and self.parent.end_date != None and self.end_date > self.parent.end_date :
                    raise ValidationError(self.name + ": "+
                                            "End date (" + self.date2string(self.end_date) + ") must be less or equal than parent end date (" + 
                                            self.date2string(self.parent.end_date) + ")!")
                
            if 'year_of_construction' in fields:
                if self.type == 'building' and self.year_of_construction != None and ( not self.year_of_construction.isdigit() or len(self.year_of_construction) != 4 ):
                    raise ValidationError(self.name + ": "+
                                            "Year of construction (" + self.year_of_construction + ") must be a number with 4 digits!")
            



    def get_number_of_objects(self, name=None):
        return len(self.children)   
    
    @fields.depends('object_number', 'name', 'id', 'type')
    def on_change_with_compute_name(self, name=None):
        return f"{self.object_number} - {self.name} ({self.id})"

    @fields.depends('sequence', 'parent')
    def on_change_with_object_number(self, name=None):
        if self.parent != None and self.parent.object_number != None:
            return f"{self.parent.object_number}/{self.sequence}"
        return f"{self.sequence}"

    @fields.depends('parent', 'start_date')
    def on_change_with_start_date(self, name=None):
        if self.parent != None and self.start_date == None and hasattr(self.parent, 'start_date'):
            return self.parent.start_date
        return self.start_date
    

    @fields.depends('parent', 'start_date', 'type', 'address', 'state')
    def on_change_parent(self, name=None):
        if self.parent != None :
            if self.start_date == None:
                self.start_date = self.parent.start_date
            if self.type == None:
                if self.parent.type == 'property':
                    self.type = 'building'
                if self.parent.type == 'land':
                    self.type = 'object'
                if self.parent.type == 'building':
                    self.type =  'object'
                if self.parent.type == 'object':
                    self.type =  'equipment'
                if self.parent.type == 'equipment':
                    self.type =  'equipment'     
            if self.address == None:
                self.address = self.parent.address  
            if self.state == None:
                self.state = self.parent.state 

    @fields.depends('parent', 'type')
    def on_change_with_type(self, name=None):
        if self.type == None:
            if self.parent != None and hasattr(self.parent, 'type'):
                if self.parent.type == 'property':
                    return 'building'
                if self.parent.type == 'land':
                    return 'object'
                if self.parent.type == 'building':
                    return 'object'
                if self.parent.type == 'object':
                    return 'equipment'
                if self.parent.type == 'equipment':
                    return 'equipment'
        return self.type
                

    @fields.depends('parent', 'address')
    def on_change_with_address(self, name=None):
        if self.parent != None and self.address == None and  hasattr(self.parent, 'address'):
            return self.parent.address
        return self.address

    @fields.depends('parent', 'type')
    def on_change_with_property(self, name=None):
        if self.type == 'property':
            return None
        if self.parent != None:
            obj = self.parent
            while obj.parent != None:
                obj = obj.parent
            return obj
        return None

    @classmethod
    def compute_name_search(cls, name, clause):
        if clause[1].startswith('!') or clause[1].startswith('not '):
            bool_op = 'AND'
        else:
            bool_op = 'OR'

        if hasattr(cls, 'address'):
            return [bool_op,
                ('object_number',) + tuple(clause[1:]),                    
                ('name',) + tuple(clause[1:]),
                ('address.city',) + tuple(clause[1:]),
                ('address.street',) + tuple(clause[1:]),
                ]
        return [bool_op,
            ('object_number',) + tuple(clause[1:]),                    
            ('name',) + tuple(clause[1:]),
            ]
   
class BaseObjectReport(Report):
    __name__ = 'real_estate.base_object.report'    


