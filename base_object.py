
'Base Object'
from trytond.model import (sequence_ordered, 
    DeactivableMixin, Index, ModelSQL, ModelView, Workflow, fields, Unique, Check,
    sum_tree, tree)
from trytond.model.exceptions import ValidationError
from trytond.exceptions import UserError
from trytond.i18n import gettext
from trytond.cache import Cache
from trytond.report import Report
from trytond.pool import Pool
from trytond.transaction import Transaction
from trytond.pyson import Bool, Eval, If, PYSONEncoder, TimeDelta, Equal
from trytond.pool import PoolMeta
from trytond.wizard import Button, StateTransition, StateView, Wizard
from trytond.i18n import lazy_gettext
from trytond.modules.company import CompanyReport

from sql import Column
from decimal import Decimal
import datetime

from dateutil.relativedelta import relativedelta
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


class Quantitative(fields.Numeric):
    """
    Define a numeric field with unit (``decimal``).
    """
    def __init__(self, string='', unit=None, digits=None, help='',
            required=False, readonly=False, domain=None, states=None,
            on_change=None, on_change_with=None, depends=None, context=None,
            loading='eager'):
        '''
        :param unit: the name of the Many2One field which stores
            the unit
        '''
        if unit:
            if depends is None:
                depends = set()
            else:
                depends = set(depends)
            depends.add(unit)
        super().__init__(string=string, digits=digits, help=help,
            required=required, readonly=readonly, domain=domain, states=states,
            on_change=on_change, on_change_with=on_change_with,
            depends=depends, context=context, loading=loading)
        self.unit = unit

    def definition(self, model, language):
        definition = super().definition(model, language)
        definition['symbol'] = self.unit
        definition['quantitative'] = True
        return definition

#**************************************************************************
class BaseObject(Workflow, DeactivableMixin, re_sequence_ordered(), tree(separator='\\'), ModelSQL, ModelView):
    "Base Object - base class for real estate objects"
    __name__ = 'real_estate.base_object'
    __rec_name__ = 'compute_name'
    __history__ = True

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
        'real_estate.base_object', 'Parent', path='path', 
        ondelete='CASCADE',
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

    ## special data propperty
    _states_only_propperty= {
            'invisible': Eval('type') != 'property',
            }
    
    billing_as = fields.Selection([
            ('residential', 'Residential (gross)'),
            ('commercial', 'Commercial (net)'),
            ],
        'Billing as',
        sort=False,
        states={
            'invisible': Eval('type') != 'property',
            'readonly': Eval('state') != 'draft',
            })

    collective_billing = fields.Boolean('Collective Billing',
        states={
            'invisible': Eval('type') != 'property',
            'readonly': Eval('state') != 'draft',
            })

    billing_units = fields.One2Many('real_estate.billing_unit', 'property', 'Billing Units',
        states=_states_only_propperty)

    occupancy = fields.One2Many('real_estate.base_object.occupancy', 'base_object',
        'Occupancy',
        states={'invisible': Eval('type') != 'object'},
        readonly=True)

    ## special data building
    _states_only_building= {
            'invisible': Eval('type') != 'building',
            }
    
    year_of_construction = fields.Char("Year of Construction", size=4,
        states=_states_only_building)
    
    number_of_floors = fields.Integer("Number of Floors",
        states=_states_only_building)
    
    ## special data rental object
    _states_only_object= {
            'invisible': Eval('type') != 'object',
            }
    floor = fields.Integer("Floor",
        states=_states_only_object)
    basement_nr = fields.Char("Basement Number", size=10,
        states={
            'invisible': (Eval('type') != 'object')
                | Eval('use_class', '').in_(['parking', 'garage']),
        })
    parking_nr = fields.Char("Parking Number", size=10,
        states={
            'invisible': (Eval('type') != 'object')
                | ~Eval('use_class', '').in_(['parking', 'garage']),
        })

    ## special equipment data
    _states_only_equipment = {
            'invisible': Eval('type') != 'equipment',
            }
    
    e_type = fields.Selection([
            ('technical_building_equipment,', 'Technical Building Equipment'),
            ('structure', 'Structures, e.g., masonry, windows, doors'),
            ('installation', 'Installation, e.g., furniture'),
            ('meters', 'Meters'),
            (None, 'None'),
            ], "Equipment Type", sort=False,
        states={
            'invisible': Eval('type') != 'equipment',
            'required': Eval('type') == 'equipment',
            })

    no_print = fields.Boolean("Do not print this equipment in reports",
        states=_states_only_equipment)
    
    product = fields.Many2One('product.product', 'Product', 
        states=_states_only_equipment,
        context={
            'company': Eval('company', None),
            },
        depends={'company'},
        #domain=[
        #    ('type', '=', 'assets'),
        #    ('depreciable', '=', True),
        #    ]
        )
    
    ## special equipment meter data
    _states_only_equipment_meter = {
            'invisible': ((Eval('type') != 'equipment') | (Eval('e_type') != 'meters')),
            }

    meter_unit = fields.Many2One('product.uom', "Unit",
        states={
            'invisible': ((Eval('type') != 'equipment') | (Eval('e_type') != 'meters')),
            'required':  ((Eval('type') == 'equipment') & (Eval('e_type') == 'meters')),
            },
        )
    
    meter_is_counter = fields.Boolean("Is Counter",
        states=_states_only_equipment_meter,
        help="Check if the meter is a counter (i.e., values are increasing over time).\n" 
        "If not checked, the meter values are considered as absolute values (e.g., fuel level in a tank)."
        )
    
    meter_factor = fields.Float("Factor", digits=(8, 2),
        help="Factor to apply to the meter values (e.g., \n"
        "a bridge on an electricity meter, so that the factor must be multiplied for display purposes).",
        states={
            'invisible': ((Eval('type') != 'equipment') | (Eval('e_type') != 'meters')),
            'required':  ((Eval('type') == 'equipment') & (Eval('e_type') == 'meters')),
            })


    meter_id = fields.Function(fields.Char("Meter ID"), 
        'on_change_with_meter_id')
    meter_last_value = fields.Function(Quantitative ("Last Value", unit='meter_unit',digits='meter_unit',), 
        'on_change_with_last_meter_value')
    meter_last_reading_date = fields.Function(fields.Date("Last Reading Date"), 
        'on_change_with_last_meter_reading_date')
    meter_last_reading_user = fields.Function(fields.Many2One('res.user', "Last Reading User"), 
        'on_change_with_last_meter_reading_user')
    meter_last_consumption = fields.Function(Quantitative("Last Consumption", unit='meter_unit',digits='meter_unit',), 
        'on_change_with_last_meter_consumption')
    
    meter_readings = fields.One2Many('real_estate.meter_reading', 'base_object', 'Meter Readings',
        domain=[('base_object', '=', Eval('id', -1))],
        states=_states_only_equipment_meter,
        )

    @classmethod
    def view_attributes(cls):
        return super().view_attributes() + [
            ('/form/notebook/page[@id="page_building"]', 'states', cls._states_only_building),
            ('/form/notebook/page[@id="page_object"]', 'states', cls._states_only_object),
            ('/form/notebook/page[@id="page_occupancy"]', 'states', cls._states_only_object),
            ('/form/notebook/page[@id="page_equipment"]', 'states', cls._states_only_equipment),
            ('/form/notebook/page[@id="page_meter"]', 'states', cls._states_only_equipment_meter),
            ('/form/notebook/page[@id="page_billing_unit"]', 'states', cls._states_only_propperty),
            ]


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
                    },
                'refresh_occupancy': {
                    'invisible': Eval('type') != 'object',
                    'depends': ['type'],
                    },
                'compute_value_shares': {
                    'invisible': ~(
                        (Eval('type') == 'property') &
                        (Eval('state') == 'approved')),
                    'depends': ['type', 'state'],
                    },
                'compute_settlement_result_property': {
                    'invisible': ~(
                        (Eval('type') == 'property') &
                        (Eval('state') == 'approved')),
                    'depends': ['type', 'state'],
                    },
                'billing_property': {
                    'invisible': ~(
                        (Eval('type') == 'property') &
                        (Eval('state') == 'approved')),
                    'depends': ['type', 'state'],
                    },
                'cancel_property': {
                    'invisible': ~(
                        (Eval('type') == 'property') &
                        (Eval('state') == 'approved')),
                    'depends': ['type', 'state'],
                    },
                'estimate_consumption': {
                    'invisible': ~(
                        (Eval('type') == 'equipment') &
                        (Eval('e_type') == 'meters') &
                        (Eval('state') == 'approved')),
                    'depends': ['type', 'e_type', 'state'],
                    },
                })

    @classmethod
    @ModelView.button
    def refresh_occupancy(cls, base_objects):
        BaseObjectOccupancy = Pool().get('real_estate.base_object.occupancy')
        objects = [o for o in base_objects if o.type == 'object']
        if objects:
            BaseObjectOccupancy.refresh(objects)

    @classmethod
    @ModelView.button
    def compute_value_shares(cls, base_objects):
        BillingUnit = Pool().get('real_estate.billing_unit')
        for obj in base_objects:
            if obj.type != 'property' or obj.state != 'approved':
                continue
            units = [bu for bu in obj.billing_units if bu.state == 'value_share']
            if units:
                BillingUnit.compute_value_shares_button(units)

    @classmethod
    @ModelView.button
    def compute_settlement_result_property(cls, base_objects):
        BillingUnit = Pool().get('real_estate.billing_unit')
        for obj in base_objects:
            if obj.type != 'property' or obj.state != 'approved':
                continue
            units = [bu for bu in obj.billing_units if bu.state == 'value_share']
            if units:
                BillingUnit.compute_settlement_result(units)

    @classmethod
    @ModelView.button
    def billing_property(cls, base_objects):
        BillingUnit = Pool().get('real_estate.billing_unit')
        for obj in base_objects:
            if obj.type != 'property' or obj.state != 'approved':
                continue
            units = [bu for bu in obj.billing_units if bu.state == 'value_share']
            if units:
                BillingUnit.billing(units)

    @classmethod
    @ModelView.button
    def cancel_property(cls, base_objects):
        BillingUnit = Pool().get('real_estate.billing_unit')
        for obj in base_objects:
            if obj.type != 'property' or obj.state != 'approved':
                continue
            units = [bu for bu in obj.billing_units if bu.state == 'billed']
            if units:
                BillingUnit.cancel(units)

    @classmethod
    @ModelView.button_action('real_estate.wizard_estimate_consumption')
    def estimate_consumption(cls, base_objects):
        pass

    @classmethod
    def default_company(cls):
        return Transaction().context.get('company')

    @staticmethod
    def default_state():
        return 'draft'

    @staticmethod
    def default_billing_as():
        return 'residential'

    @staticmethod
    def default_collective_billing():
        return True
    
    @classmethod
    def default_meter_factor(cls):
        return 1

    @classmethod
    def default_meter_is_counter(cls):
        return True

    
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
                    raise ValidationError(
                        gettext("real_estate.msg_end_date_must_be_less_or_equal_than_parent_end_date",).format(
                            self.name,
                            self.date2string(self.end_date),
                            self.date2string(self.parent.end_date),)
                        )
                
            if 'year_of_construction' in fields:
                if self.type == 'building' and self.year_of_construction != None and \
                    ( not self.year_of_construction.isdigit() or len(self.year_of_construction) != 4 ):
                    raise ValidationError(
                        gettext("real_estate.msg_year_of_construction_must_be_4_digits",).format(
                            self.name,
                            self.year_of_construction,)
                        )
            



    @classmethod
    def write(cls, *args):
        super().write(*args)
        all_ids = set()
        actions = iter(args)
        for records, _ in zip(actions, actions):
            for rec in records:
                all_ids.add(rec.id)
        rental_objects = [o for o in cls.browse(list(all_ids)) if o.type == 'object']
        if rental_objects:
            BaseObjectOccupancy = Pool().get('real_estate.base_object.occupancy')
            BaseObjectOccupancy.refresh(rental_objects)
            property_ids = {o.property.id for o in rental_objects if o.property}
            if property_ids:
                cls.compute_value_shares(cls.browse(list(property_ids)))

    def get_number_of_objects(self, name=None):
        return len(self.children)   
    
    def on_change_with_meter_id(self, name=None):
        # get last meter id
        MeterReading = Pool().get('real_estate.meter_reading')
        last_reading = MeterReading.search([
            ('base_object', '=', self.id),
            ], order=[('reading_date', 'DESC'),('m_type', 'ASC')], limit=1)
        if last_reading:
            return last_reading[0].meter_id  
            
    def on_change_with_last_meter_value(self, name=None):
        # get last meter id
        MeterReading = Pool().get('real_estate.meter_reading')
        last_reading = MeterReading.search([
            ('base_object', '=', self.id),
            ], order=[('reading_date', 'DESC'),('m_type', 'ASC')], limit=1)
        if last_reading:
            return last_reading[0].value  
    
    def on_change_with_last_meter_reading_date(self, name=None):
        # get last meter id
        MeterReading = Pool().get('real_estate.meter_reading')
        last_reading = MeterReading.search([
            ('base_object', '=', self.id),
            ], order=[('reading_date', 'DESC'),('m_type', 'ASC')], limit=1)
        if last_reading:
            return last_reading[0].reading_date  
    
    def on_change_with_last_meter_reading_user(self, name=None):
        # get last meter id
        MeterReading = Pool().get('real_estate.meter_reading')
        last_reading = MeterReading.search([
            ('base_object', '=', self.id),
            ], order=[('reading_date', 'DESC'),('m_type', 'ASC')], limit=1)
        if last_reading:
            return last_reading[0].reading_user
    
    def on_change_with_last_meter_consumption(self, name=None):
        # get last meter id
        MeterReading = Pool().get('real_estate.meter_reading')
        last_reading = MeterReading.search([
            ('base_object', '=', self.id),
            ], order=[('reading_date', 'DESC'),('m_type', 'ASC')], limit=1)
        if last_reading:
            return last_reading[0].consumption  


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

#**************************************************************************
class BaseObjectOccupancy(ModelSQL, ModelView):
    "Base Object Occupancy"
    __name__ = 'real_estate.base_object.occupancy'

    base_object = fields.Many2One('real_estate.base_object', 'Object',
        required=True, ondelete='CASCADE', readonly=True)
    property = fields.Many2One('real_estate.base_object', 'Property',
        readonly=True, ondelete='SET NULL')
    start_date = fields.Date('Start Date', readonly=True)
    end_date = fields.Date('End Date', readonly=True)
    state = fields.Selection([
        ('rented', 'Rented'),
        ('vacant', 'Vacant'),
        ('under_negotiation', 'Under Negotiation'),
    ], 'State', readonly=True)
    contract = fields.Many2One('real_estate.contract', 'Contract',
        readonly=True, ondelete='SET NULL')

    company = fields.Function(
        fields.Many2One('company.company', 'Company'),
        'on_change_with_company', searcher='search_company')

    @fields.depends('base_object')
    def on_change_with_company(self, name=None):
        if self.base_object:
            return self.base_object.company
        return None

    @classmethod
    def search_company(cls, name, clause):
        return [('base_object.company',) + tuple(clause[1:])]

    @classmethod
    def refresh(cls, base_objects):
        for base_object in base_objects:
            cls.delete(cls.search([('base_object', '=', base_object.id)]))
            if base_object.type == 'object' and base_object.start_date:
                cls._compute(base_object)

    @classmethod
    def _get_property(cls, base_object):
        obj = base_object
        while obj and obj.type != 'property':
            obj = obj.parent
        return obj if obj and obj.type == 'property' else None

    @classmethod
    def _compute(cls, base_object):
        ContractItem = Pool().get('real_estate.contract.item')
        property_ = cls._get_property(base_object)

        items = ContractItem.search([
            ('object', '=', base_object.id),
            ('contract.c_type.occupancy', '=', True),
            ('contract.state', 'in', ('running', 'terminated', 'draft')),
        ], order=[('valid_from', 'ASC')])

        ref_start = base_object.start_date
        ref_end = base_object.end_date
        prop_id = property_.id if property_ else None

        records = []
        cursor = ref_start

        for item in items:
            item_start = max(item.valid_from, ref_start) if item.valid_from else ref_start
            item_end = item.valid_to
            # effective end date (termination) only applies to active contracts
            if item.contract and item.contract.state in ('running', 'terminated'):
                contract_end = item.contract.get_effective_end_date()
                if contract_end:
                    item_end = min(item_end, contract_end) if item_end else contract_end
            if ref_end:
                item_end = min(item_end, ref_end) if item_end else ref_end

            if cursor < item_start:
                records.append({
                    'base_object': base_object.id,
                    'property': prop_id,
                    'start_date': cursor,
                    'end_date': item_start - relativedelta(days=1),
                    'state': 'vacant',
                    'contract': None,
                })

            state = ('rented'
                if item.contract.state in ('running', 'terminated')
                else 'under_negotiation')

            records.append({
                'base_object': base_object.id,
                'property': prop_id,
                'start_date': item_start,
                'end_date': item_end,
                'state': state,
                'contract': item.contract.id,
            })

            if item_end:
                cursor = item_end + relativedelta(days=1)
            else:
                cursor = None
                break

        if cursor is not None:
            # trailing_end is None when object has no end date (open-ended)
            trailing_end = ref_end
            if not items:
                # no occupancy contracts at all — whole period is vacant
                records.append({
                    'base_object': base_object.id,
                    'property': prop_id,
                    'start_date': ref_start,
                    'end_date': trailing_end,
                    'state': 'vacant',
                    'contract': None,
                })
            elif trailing_end is None or cursor <= trailing_end:
                # trailing vacant after last contract;
                # open-ended (end_date=None) when object itself has no end date
                records.append({
                    'base_object': base_object.id,
                    'property': prop_id,
                    'start_date': cursor,
                    'end_date': trailing_end,
                    'state': 'vacant',
                    'contract': None,
                })

        if records:
            cls.create(records)


#**************************************************************************
class BaseObjectEquipmentContext(ModelView):
    'Base Object Equipment Context'
    __name__ = 'real_estate.base_object.equipment.context'

    company = fields.Many2One('company.company', 'Company', required=True)
    property = fields.Many2One('real_estate.base_object', 'Property',
        domain=[
            ('type', '=', 'property'),
            ('company', '=', Eval('company', -1)),
        ])
    parent = fields.Many2One('real_estate.base_object', 'Parent Object',
        domain=[
            ('company', '=', Eval('company', -1)),
        ])
    e_type = fields.Selection('get_e_type', 'Equipment Type', sort=False)

    @classmethod
    def get_e_type(cls):
        pool = Pool()
        BaseObject = pool.get('real_estate.base_object')
        return [(None, '')] + [
            (k, v) for k, v in BaseObject._fields['e_type'].selection
            if k is not None]

    @classmethod
    def default_company(cls):
        return Transaction().context.get('company')

#**************************************************************************
class BaseObjectCompanyContext(ModelView):
    'Base Object Company Context'
    __name__ = 'real_estate.base_object.company.context'

    company = fields.Many2One('company.company', 'Company', required=True)

    @classmethod
    def default_company(cls):
        return Transaction().context.get('company')

#**************************************************************************
class BaseObjectContext(ModelView):
    'Base Object Context'
    __name__ = 'real_estate.base_object.context'

    company = fields.Many2One('company.company', 'Company', required=True)
    property = fields.Many2One('real_estate.base_object', 'Property',
        domain=[
            ('type', '=', 'property'),
            ('company', '=', Eval('company', -1)),
        ])

    @classmethod
    def default_company(cls):
        return Transaction().context.get('company')


class BaseObjectOccupancyContext(ModelView):
    'Base Object Occupancy Context'
    __name__ = 'real_estate.base_object.occupancy.context'

    company = fields.Many2One('company.company', 'Company', required=True)
    property = fields.Many2One('real_estate.base_object', 'Property',
        domain=[
            ('type', '=', 'property'),
            ('company', '=', Eval('company', -1)),
        ])
    base_object = fields.Many2One('real_estate.base_object', 'Object',
        domain=[
            ('type', '=', 'object'),
            If(Eval('property', None),
                [('property', '=', Eval('property', None))],
                []),
        ])
    contract = fields.Many2One('real_estate.contract', 'Contract',
        domain=[
            ('company', '=', Eval('company', -1)),
            If(Eval('property', None),
                [('property', '=', Eval('property', None))],
                []),
        ])
    from_date = fields.Date('From Date',
        states={'invisible': Eval('current_only', False)})
    to_date = fields.Date('To Date',
        states={'invisible': Eval('current_only', False)})
    current_only = fields.Boolean('Current Only',
        help="Show only occupancies active today, regardless of date range.")
    state = fields.Selection('get_state', 'State', sort=False)

    @classmethod
    def get_state(cls):
        pool = Pool()
        Occupancy = pool.get('real_estate.base_object.occupancy')
        return [(None, '')] + list(Occupancy._fields['state'].selection)

    @classmethod
    def default_company(cls):
        return Transaction().context.get('company')

    @classmethod
    def default_from_date(cls):
        today = Pool().get('ir.date').today()
        return today.replace(month=1, day=1)

    @classmethod
    def default_to_date(cls):
        today = Pool().get('ir.date').today()
        return today.replace(month=12, day=31)

    @classmethod
    def default_current_only(cls):
        return False


#**************************************************************************
class MeterReadingContext(ModelView):
    'Meter Reading Context'
    __name__ = 'real_estate.meter_reading.context'

    company = fields.Many2One('company.company', 'Company', required=True)
    property = fields.Many2One('real_estate.base_object', 'Property',
        domain=[
            ('type', '=', 'property'),
            ('company', '=', Eval('company', -1)),
        ])
    parent = fields.Many2One('real_estate.base_object', 'Parent Object',
        domain=[
            ('company', '=', Eval('company', -1)),
        ])
    equipment = fields.Many2One('real_estate.base_object', 'Equipment',
        domain=[
            ('type', '=', 'equipment'),
            ('e_type', '=', 'meters'),
            If(Eval('parent', None),
                [('parent', '=', Eval('parent', None))],
                []),
            ('company', '=', Eval('company', -1)),
        ])
    from_date = fields.Date('From Date')
    to_date = fields.Date('To Date')

    @classmethod
    def default_company(cls):
        return Transaction().context.get('company')

    @classmethod
    def default_from_date(cls):
        today = Pool().get('ir.date').today()
        return today.replace(month=1, day=1)

    @classmethod
    def default_to_date(cls):
        return Pool().get('ir.date').today()


#**************************************************************************
class MeterReading(ModelSQL, ModelView):
    "Meter Reading"
    __name__ = 'real_estate.meter_reading'


    name  = fields.Function(fields.Char("Name"), 'on_change_with_name')

    m_type = fields.Selection([
            ('initial', 'initial, installation'),
            ('reading', 'reading'),
            ('estimate', 'estimate'),
            ('final', 'final reading, removal'),
            ], "Reading Type", required=True, sort=False)

    company = fields.Many2One('company.company', 'Company', required=True)
    base_object = fields.Many2One('real_estate.base_object', 'Base Object', required=True, ondelete='CASCADE',
        domain=[('type', '=', 'equipment'), ('e_type', '=', 'meters'),
                ('company', '=', Eval('company', -1))],
        )
    meter_id = fields.Char("Meter ID", required=True)
    reading_date = fields.Date("Reading Date", required=True)
    reading_user = fields.Many2One('res.user', "Reading User")
    comment = fields.Text("Comment")
    value = Quantitative("Value", required=True, unit='unit', digits='unit')
    unit = fields.Function(fields.Many2One('product.uom', "Unit", 
            readonly=True,),'on_change_with_unit')
    consumption = fields.Function(Quantitative("Consumption", unit='unit',digits='unit',), 
        'on_change_with_consumption')

    @classmethod
    def default_company(cls):
        return Transaction().context.get('company')

    @fields.depends('base_object')
    def on_change_base_object(self):
        if self.base_object and self.base_object.company:
            self.company = self.base_object.company

    @classmethod
    def default_reading_user(cls):
        return  Transaction().user
    
    @classmethod
    def default_reading_date(cls):
        return Pool().get('ir.date').today()
    
    @classmethod
    def default_m_type(cls):
        return 'reading'

    @fields.depends('base_object')
    def on_change_with_unit(self, name=None):
        if self.base_object and self.base_object.meter_unit:
            return self.base_object.meter_unit.id
        return None
    
    @fields.depends('base_object', 'reading_date', 'value', 'unit')
    def on_change_with_name(self, name=None):
        return f"{self.base_object.compute_name if self.base_object else '?'}" +\
              f" - {self.reading_date}: {self.value} {self.unit.symbol if self.unit else ''}"

    @fields.depends('base_object', 'reading_date','meter_id')
    def on_change_with_meter_id(self, name=None):
        if self.meter_id:
             return self.meter_id
        if self.base_object:
            # get last meter id
            MeterReading = Pool().get('real_estate.meter_reading')
            last_reading = MeterReading.search([
                ('base_object', '=', self.base_object.id),
                ('reading_date', '<', self.reading_date),
                ], order=[('reading_date', 'DESC'), ('m_type', 'DESC')], limit=1)
            if last_reading:
                return last_reading[0].meter_id         
        return None
    
    @fields.depends('base_object', 'reading_date', 'value', 'meter_id')
    def on_change_with_consumption(self, name=None):
        if self.base_object and self.base_object.meter_is_counter:
            # get last reading
            MeterReading = Pool().get('real_estate.meter_reading')
            last_reading = MeterReading.search([
                ('base_object', '=', self.base_object.id),
                ('meter_id', '=', self.meter_id),
                ('reading_date', '<', self.reading_date),
                ], order=[('reading_date', 'DESC'), ('m_type', 'DESC')], limit=1)
            if last_reading and last_reading[0].value != None and self.value != None:
                last_value = last_reading[0].value
                return self.value - last_value

        return 0

    @classmethod
    def simulate_estimate(cls, base_object, per_date, meter_id=None):
        """Return (estimated_value, consumption, r1, r2).
        Requires >= 2 non-estimate readings within 1 year before per_date.
        """
        one_year_ago = per_date - datetime.timedelta(days=365)
        domain = [
            ('base_object', '=', base_object.id),
            ('reading_date', '>=', one_year_ago),
            ('reading_date', '<', per_date),
            ('m_type', 'in', ['initial', 'reading', 'final']),
        ]
        if meter_id:
            domain.append(('meter_id', '=', meter_id))
        readings = cls.search(domain, order=[('reading_date', 'ASC')])
        if len(readings) < 2:
            raise UserError(
                f'Not enough readings for {base_object.rec_name}: '
                f'need at least 2 within one year before {per_date}.')
        r1, r2 = readings[-2], readings[-1]
        days_between = (r2.reading_date - r1.reading_date).days
        if days_between == 0:
            raise UserError(
                f'Readings {r1.reading_date} and {r2.reading_date} '
                f'have the same date — cannot extrapolate.')
        days_to_estimate = (per_date - r2.reading_date).days
        rate = (float(r2.value) - float(r1.value)) / days_between
        estimated_value = Decimal(str(
            round(float(r2.value) + rate * days_to_estimate, 4)))
        consumption = estimated_value - r2.value
        return estimated_value, consumption, r1, r2

    @classmethod
    def create_estimate(cls, base_object, per_date, reason, meter_id=None):
        """Create and save an estimate reading. Returns the new MeterReading."""
        estimated_value, consumption, r1, r2 = cls.simulate_estimate(
            base_object, per_date, meter_id)
        effective_meter_id = meter_id or r2.meter_id
        reading = cls()
        reading.company = base_object.company
        reading.base_object = base_object
        reading.meter_id = effective_meter_id
        reading.reading_date = per_date
        reading.m_type = 'estimate'
        reading.value = estimated_value
        reading.comment = reason
        reading.save()
        return reading


#**************************************************************************
class EstimateConsumptionStart(ModelView):
    'Estimate Consumption Start'
    __name__ = 'real_estate.estimate_consumption.start'

    meter = fields.Many2One('real_estate.base_object', 'Meter', readonly=True)
    meter_unit = fields.Many2One('product.uom', 'Unit', readonly=True)
    meter_factor = fields.Float('Factor', digits=(8, 2), readonly=True)
    meter_id = fields.Char('Meter ID', required=True)
    per_date = fields.Date('Per Date', required=True)
    reason = fields.Char('Reason', required=True)


#**************************************************************************
class EstimateConsumptionResult(ModelView):
    'Estimate Consumption Result'
    __name__ = 'real_estate.estimate_consumption.result'

    meter = fields.Many2One('real_estate.base_object', 'Meter', readonly=True)
    meter_id = fields.Char('Meter ID', readonly=True)
    per_date = fields.Date('Per Date', readonly=True)
    reason = fields.Char('Reason', readonly=True)
    reading1_date = fields.Date('Reading 1 Date', readonly=True)
    reading1_value = fields.Numeric('Reading 1 Value', readonly=True, digits=(16, 4))
    reading2_date = fields.Date('Reading 2 Date', readonly=True)
    reading2_value = fields.Numeric('Reading 2 Value', readonly=True, digits=(16, 4))
    consumption = fields.Numeric('Consumption', readonly=True, digits=(16, 4))
    estimated_value = fields.Numeric('Estimated Value', required=True, digits=(16, 4))


#**************************************************************************
class EstimateConsumptionWizard(Wizard):
    'Estimate Consumption Wizard'
    __name__ = 'real_estate.estimate_consumption.wizard'

    start = StateView('real_estate.estimate_consumption.start',
        'real_estate.estimate_consumption_start_view_form', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('OK', 'result', 'tryton-ok', True),
        ])
    result = StateView('real_estate.estimate_consumption.result',
        'real_estate.estimate_consumption_result_view_form', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('Book', 'book', 'tryton-ok', True),
        ])
    book = StateTransition()

    def default_start(self, fields):
        pool = Pool()
        BaseObject = pool.get('real_estate.base_object')
        MeterReading = pool.get('real_estate.meter_reading')
        IrDate = pool.get('ir.date')
        active_id = Transaction().context.get('active_id')
        meter = BaseObject(active_id)
        last = MeterReading.search(
            [('base_object', '=', active_id)],
            order=[('reading_date', 'DESC')], limit=1)
        return {
            'meter': meter.id,
            'meter_unit': meter.meter_unit.id if meter.meter_unit else None,
            'meter_factor': meter.meter_factor,
            'meter_id': last[0].meter_id if last else None,
            'per_date': IrDate.today(),
        }

    def default_result(self, fields):
        pool = Pool()
        MeterReading = pool.get('real_estate.meter_reading')
        estimated_value, consumption, r1, r2 = MeterReading.simulate_estimate(
            self.start.meter, self.start.per_date, self.start.meter_id)
        return {
            'meter': self.start.meter.id,
            'meter_id': self.start.meter_id,
            'per_date': self.start.per_date,
            'reason': self.start.reason,
            'reading1_date': r1.reading_date,
            'reading1_value': r1.value,
            'reading2_date': r2.reading_date,
            'reading2_value': r2.value,
            'consumption': consumption,
            'estimated_value': estimated_value,
        }

    def transition_book(self):
        pool = Pool()
        MeterReading = pool.get('real_estate.meter_reading')
        reading = MeterReading()
        reading.company = self.result.meter.company
        reading.base_object = self.result.meter
        reading.meter_id = self.result.meter_id
        reading.reading_date = self.result.per_date
        reading.m_type = 'estimate'
        reading.value = Decimal(str(self.result.estimated_value))
        reading.comment = self.result.reason
        reading.save()
        return 'end'


    @classmethod
    def validate(cls, records):
        super().validate(records)  # Standard-Validierungen
        
        for record in records:
            # Validierung: reading_date muss groesser als letzte reading_date sein
            MeterReading = Pool().get('real_estate.meter_reading')
            last_reading = MeterReading.search([
                ('base_object', '=', record.base_object.id),
                ('reading_date', '<', record.reading_date),
                ], order=[('reading_date', 'DESC')], limit=1)
            if last_reading:
                if ( record.m_type == 'reading' or record.m_type == 'estimate') \
                    and record.meter_id != last_reading[0].meter_id:
                    raise ValidationError(
                        gettext("real_estate.msg_meter_id_must_be_same_as_last_reading",).format( 
                            #"Meter ID {} must be the same as last reading for point {}!").format(
                            record.meter_id,
                            record.base_object.compute_name,
                        )
                    )
                # meter reading value must be greater/equal than last reading value in case of counter, 
                if ( record.m_type == 'reading' or record.m_type == 'estimate') \
                    and record.value < last_reading[0].value and record.base_object.meter_is_counter:
                    raise ValidationError(
                        gettext("real_estate.msg_meter_reading_value_must_be_greater_than_last_reading",).format( 
                            #"Meter reading value {} must be greater than last reading value {} for point {}!").format(
                            record.value,
                            last_reading[0].value,
                            record.base_object.compute_name,
                        )
                    )
                if record.m_type == 'final' and ( record.meter_id != last_reading[0].meter_id \
                    or ( record.value < last_reading[0].value and record.base_object.meter_is_counter ) ):
                    raise ValidationError(
                        gettext("real_estate.msg_final_meter_reading_greater_and_have_same_id",).format( 
                            #"Final meter reading value {} must be greater than last reading value {} for point {} and have the same meter ID!").format(
                            record.value,
                            last_reading[0].value,
                            record.base_object.compute_name,
                        )
                    )
                if record.m_type == 'initial' and record.meter_id == last_reading[0].meter_id:
                    raise ValidationError(
                        gettext("real_estate.msg_initial_meter_id_must_not_be_same_as_last_reading",).format( 
                            #"Meter ID {} must not be the same as last reading for final reading for point {}!").format(
                            record.meter_id,
                            record.base_object.compute_name,
                        )
                    )
            else:
                if record.m_type != 'initial':
                    raise ValidationError(
                        gettext("real_estate.msg_first_meter_reading_must_be_initial",).format( 
                            #"First meter reading for point {} must be of type 'initial'!").format(
                            record.base_object.compute_name,
                        )
                    )

            # Validierung: no duplicate reading for same date and meter id
            # change meter-id: 1x final old mater_id and 1x initial new meter_id
            dubble_reading = MeterReading.search([
                ('base_object', '=', record.base_object.id),
                ('reading_date', '=', record.reading_date),
                ('meter_id', '=', record.meter_id),
                ], order=[('reading_date', 'DESC')], limit=1)
            if dubble_reading and dubble_reading[0].id != record.id:
                raise ValidationError(
                    gettext("real_estate.msg_duplicate_meter_reading_for_same_date_and_meter_id",).format( 
                        #"There is already a meter reading for point {} with reading date {}!").format(
                        record.base_object.compute_name,
                        record.reading_date,
                    )
                )

#**************************************************************************   
class BaseObjectReport(Report):
    __name__ = 'real_estate.base_object.report'    


