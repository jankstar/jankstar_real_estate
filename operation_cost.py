
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
from trytond.modules.product import price_digits
from trytond.modules.currency.fields import Monetary
from trytond.exceptions import UserWarning

from dateutil.relativedelta import relativedelta

from sql import Column
import re
from decimal import Decimal
from . import base_object

import logging
import pdb

logger = logging.getLogger(__name__)
class InvalidCalculationMethod(ValidationError):
    pass

#**********************************************************************
class CostGroup(Workflow,DeactivableMixin, sequence_ordered(), ModelSQL, ModelView):
    __name__ = 'real_estate.cost_group'
    __rec_name__ = 'name'

    company = fields.Function(fields.Many2One('company.company','Company'),
        'on_change_with_company')
    
    property = fields.Many2One('real_estate.base_object', 
        "Property", required=True, path='path', ondelete='CASCADE',)

    start_date = fields.Date('Start Date', 
        states={
            'readonly': ((Eval('state') != 'draft')),
            },
        required=True,
        domain=[If(Bool(Eval('end_date')), ('start_date', '<=', Eval('end_date', None)),())],
        )
      
    end_date = fields.Function(fields.Date('End Date'),'on_change_with_end_date')

    calculation_method = fields.Selection([
        ('rental_apartment', 'Rental Apartment'),
        ('WEG_billing', 'WEG Billing'),
        ], "Calculation Method", sort=False,
        states={ 'readonly': Eval('state') != 'draft', },
        )

    planned_costs = fields.Function(Monetary('Planned Costs', currency='currency', digits= 'currency',#(16, 2),
        ),'on_change_with_planned_costs',
        )

    currency = fields.Function(fields.Many2One('currency.currency', 'Currency',), 'on_change_with_currency') 

    description = fields.Char('Description', required=True)

    name = fields.Function(fields.Char("Name"), 'on_change_with_name', 
                searcher='name_search')  
    
    state = fields.Selection([
            ('draft', 'Draft'),
            ('approved', 'Approved'),
            ('selection', 'Selection'),
            ('estimated_value_share', 'Estimated Value Share'),
            ('value_share', 'Value Share'),
            ('billed', 'Billed'),
            ], "State", sort=False,
            #states={ 'readonly': True, },
            )

    sub_state = fields.Function(fields.Selection('get_sub_states', "Sub State"), 'on_change_with_sub_state')      

    term_types_of_use = fields.MultiSelection(
            'get_term_types_of_use', "Term Types",
            help="The term type which can use this cost group.") 


    cost_objects = fields.One2Many('real_estate.cost_object', 'cost_group', 'Cost Objects',
            #states=_states_only_propperty
            states={ 'readonly': Eval('state') != 'draft', },
            )    


    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._transitions |= set((
            ('draft', 'approved'),
            ('approved', 'selection'),
            ('selection', 'estimated_value_share'),
            ('estimated_value_share', 'value_share'),
            ))

        cls._buttons.update({
                'approved': {
                    'invisible': (
                        ~Eval('state').in_(['draft'])
                        ),
                    #'icon': If(Eval('state') == 'cancelled', 'tryton-undo',
                    #    'tryton-back'),
                    'depends': ['state'],
                    },
                'selection': {
                    'invisible': (
                        (~Eval('state').in_(['approved', 'selection']))
                        ),
                    'depends': ['state', 'sub_state'],
                    },
                })

    @classmethod
    @ModelView.button
    @Workflow.transition('approved')
    #@set_employee('running_by')
    #@reset_employee('cancelled_by', 'terminated_by')
    def approved(cls, cost_groups):
        for cost_group in cost_groups:
            cost_group.add_log('state_change', f'cost group state changed to approved')
            cost_group.state = 'approved'
            cost_group.save()


    @classmethod
    @ModelView.button
    @Workflow.transition('selection')
    def selection(cls, cost_groups):
        for cost_group in cost_groups:
            cost_group.add_log('state_change', f'cost group state changed to selection')
            all_state = True
            for cost_object in cost_group.cost_objects:
                cost_object.selection()   
                if cost_object.sub_state != 'selection':
                    all_state = False
            if all_state:
                cost_group.state = 'selection'
            cost_group.save()


    @staticmethod
    def default_state():
        return 'draft'
    
    @staticmethod
    def default_calculation_method():
        return 'rental_apartment'

    @staticmethod
    def get_sub_states():
        pool = Pool()
        SettlementUnit = pool.get('real_estate.settlement_unit')
        return SettlementUnit.fields_get(['state'])['state']['selection']
    
    @fields.depends('cost_objects')
    def on_change_with_sub_state(self, name=None):
        #return the lowest state of all settlement units
        if self.cost_objects:
            states = set(cost_object.sub_state for cost_object in self.cost_objects)
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
        return None

    @fields.depends('property')
    def on_change_with_company(self, name=None):
        return self.property.company if self.property else None
    
    def pre_validate(self):
        super().pre_validate()
        self.check_calculation_method()

    @fields.depends('calculation_method', 'start_date')
    def check_calculation_method(self, name=None):
        if self.calculation_method == 'WEG_billing' and ( self.start_date.month != 1 or self.start_date.day != 1 ):
            raise InvalidCalculationMethod(gettext("real_estate.msg_invalid_calculation_method",).format(
                self.start_date))


    @fields.depends('start_date')
    def on_change_with_end_date(self, name=None):
        if self.start_date :
            return self.start_date - relativedelta(days=1) + relativedelta(years=1)
        return None

    @fields.depends(methods=['_check_calculation_method_notify'])
    def on_change_notify(self):
        notifications = super().on_change_notify()
        notifications.extend(self._check_calculation_method_notify())
        return notifications

    @fields.depends('calculation_method', 'start_date')
    def _check_calculation_method_notify(self):
        if self.calculation_method == 'WEG_billing' and ( self.start_date.month != 1 or self.start_date.day != 1 ):
            logger.warning(f"Invalid calculation method for cost group {self.id}: start date {self.start_date} is not the first day of the year.")
            yield ('warning', 
                   gettext("real_estate.msg_invalid_calculation_method",).format(
                       self.start_date))

    @classmethod
    def get_term_types_of_use(cls):
        pool = Pool()
        TermType = pool.get('real_estate.contract.term.type')
        term_types = TermType.search([])
        if term_types:
            result = [(str(ele.id), ele.name) for ele in term_types]
            return result
        return [] 

    @classmethod
    def search_name(cls, name, offset=0, limit=None, order=None):
        pool = Pool()
        BaseObject = pool.get('real_estate.base_object')
        return BaseObject.search_name(name, offset, limit, order)

    @staticmethod
    def default_start_date():
        #first day of the current month
        return Pool().get('ir.date').today().replace(day=1)    

    @fields.depends('start_date', 'end_date', 'description')
    def on_change_with_name(self, name=None):
        if self.start_date and self.end_date:     
            return f"{self.description} - {self.start_date} / {self.end_date}"
        return f" ? "

    @fields.depends('company')
    def on_change_with_currency(self, name=None):
        return self.company.currency if self.company else None

    @fields.depends('cost_objects')
    def on_change_with_planned_costs(self, name=None):
        if self.cost_objects:
            return sum(cost_object.planned_costs for cost_object in self.cost_objects if cost_object.planned_costs)

        # # here you can implement the logic to calculate the planned costs based on the start and end date
        # # for example, you can sum up the costs of all cost objects that fall within the date range
        # if self.start_date and self.end_date:
        #     pool = Pool()
        #     CostObject = pool.get('real_estate.cost_object')
        #     cost_objects = CostObject.search([
        #         ('cost_group', '=', self.id),
        #         ('start_date', '>=', self.start_date),
        #         ('end_date', '<=', self.end_date),
        #     ])
        #     total_costs = sum(cost_object.planned_costs for cost_object in cost_objects)
        #     return total_costs
        # return None

    @fields.depends('property')
    def on_change_with_company(self, name=None):
        return self.property.company if self.property else None

    @classmethod
    def name_search(cls, name, clause):
        if clause[1].startswith('!') or clause[1].startswith('not '):
            bool_op = 'AND'
        else:
            bool_op = 'OR'

        return [bool_op,
            ('property.name',) + tuple(clause[1:]),
        ]  


    def add_log(self, event, description=None):
        pool = Pool()
        CostLog = pool.get('real_estate.cost_group.log')
        CostLog.create([{
            'cost_group': self.id,
            'event': event,
            'description': description or '',
        }])
        print(f'cost group {self.id}, event {event}, description {description}')

#**********************************************************************
class CostObjectType(DeactivableMixin, sequence_ordered(), ModelSQL, ModelView):
    __name__ = 'real_estate.cost_object.type'

    name = fields.Char("Name", required=True, translate=True)
    comment = fields.Text("Comment")    
    no_print = fields.Boolean("No Print")


#**********************************************************************
class CostGroupLog(ModelSQL, ModelView):
    "Cost Group log obj"
    __name__ = 'real_estate.cost_group.log'

    cost_group = fields.Many2One('real_estate.cost_group', 'Cost Group', required=True, ondelete='CASCADE')
    event = fields.Char('Event', required=True)
    description = fields.Text('Description')
    create_date = fields.DateTime('Create Date', readonly=True)
    create_uid = fields.Many2One('res.user', 'User', readonly=True)


#**********************************************************************
class CostObject(DeactivableMixin, base_object.re_sequence_ordered(), ModelSQL, ModelView):
    __name__ = 'real_estate.cost_object'

    property = fields.Function(fields.Many2One('real_estate.base_object','Property'),
        'on_change_with_property')

    company = fields.Function(fields.Many2One('company.company','Company'),
        'on_change_with_company')
    
    cost_group = fields.Many2One('real_estate.cost_group', 'Cost Group', 
        required=True, ondelete='CASCADE',
        # domain=[
        #      ('company', '=', Eval('company', -1)),
        #      ('property', '=', Eval('property', -1)),],
             ) 

    start_date = fields.Function(fields.Date('Start Date',), 'on_change_with_start_date',)
    
    end_date = fields.Function(fields.Date('End Date'),'on_change_with_end_date')   

    state = fields.Function(fields.Selection('get_states', "State"), 'on_change_with_state')  

    sub_state = fields.Function(fields.Selection('get_sub_states', "Sub State"), 'on_change_with_sub_state')  

    type = fields.Many2One(
        'real_estate.cost_object.type', "Cost Type", required=True, on_change='on_change_type',)
    
    comment = fields.Text("Comment")    
    
    name = fields.Function(fields.Char("Name"), 'on_change_with_name', 
                searcher='name_search')  

    planned_costs = Monetary('Planned Costs', currency='currency', digits= 'currency',#(16, 2),
        states={
            'readonly': Eval('state') == 'billed',
            },
        )

    currency = fields.Function(fields.Many2One('currency.currency', 'Currency',), 'on_change_with_currency') 


    allocation_rule =  fields.Selection([
            ('no_allocation', 'No allocation'),
            ('allocation_by_measurement', 'Allocation by measurement'),
            ('allocation_by_consumption', 'Allocation by consumption'),
            ('allocation_per_rental_unit', 'Allocation per rental unit'),
            ], "Allocation Rule", sort=False,
            #states={ 'readonly': True, },
            ) 

    vacancy = fields.Selection([
        ('no_allocation', 'No allocation (all cost allocated by tenant)'),
        ('by_owner', 'Allocation by owner'),
        ], "Allocation During Vacancy", sort=False,
        states={ 'invisible': Eval('allocation_rule') == 'no_allocation', },
        )
    
    m_type = fields.Many2One(
        'real_estate.measurement.type', "Measurement Type",
        domain=[('types', '=', ['object'])], #exact only 'object'
        states={
            'invisible': Eval('allocation_rule') != 'allocation_by_measurement',
            'required': Eval('allocation_rule') == 'allocation_by_measurement',
            },)


    meter_unit = fields.Many2One('product.uom', "Unit",
        states={
            'invisible': Eval('allocation_rule') != 'allocation_by_consumption',
            'required': Eval('allocation_rule') == 'allocation_by_consumption',
            },)

    reg_ex_object = fields.Char("Reg. Ex. Object",
        help="Regular expression to find the object. For Example '[1-9/ ]*Apartement[1-9()# ]*' to find the object with name contains '100/100 Apartement #45'.",
        states={
            'invisible': Eval('allocation_rule') == 'no_allocation',
            #'required': Eval('allocation_rule') != 'no_allocation',
            },)
    
    reg_ex_meter = fields.Char("Reg. Ex. Meter",
        help="Regular expression to find the meter. For Example '[1-9/ ]*Electricity[1-9a-Z()# ]*' to find the meter with name contains '556 Electricity Meter'.",
        states={
            'invisible': Eval('allocation_rule') != 'allocation_by_consumption',
            #'required': Eval('allocation_rule') == 'allocation_by_consumption',
            },)  


    objects = fields.Function(fields.One2Many('real_estate.base_object', None, 'Objects',
                                              readonly=True,
        #domain=[('company', '=', Eval('company', -1)),
        #        ('property', '=', Eval('property', -1)),
        #        ('type', '=', 'object')],
        states={
            'invisible': ((Eval('allocation_rule') == 'no_allocation') | (Eval('state') == 'billed')),
            }
        ),'on_change_with_objects', 
        setter='set_objects',
        )
    

    meters = fields.Function(fields.One2Many('real_estate.base_object', None, 'Meters',
                                              readonly=True,
        #domain=[('company', '=', Eval('company', -1)),
        #        ('property', '=', Eval('property', -1)),
        #        ('type', '=', 'meter')],
        states={
            'invisible': ((Eval('allocation_rule') != 'allocation_by_consumption') | (Eval('state') == 'billed')),
            }
        ),'on_change_with_meters', 
        setter='set_meters',
        )

    measurements = fields.Function(fields.One2Many('real_estate.measurement', None, 'Measurements',
                                              readonly=True,
        #domain=[('company', '=', Eval('company', -1)),
        #        ('property', '=', Eval('property', -1)),
        #        ('m_type', '=', Eval('m_type', -1))],
        states={
            'invisible': ((Eval('allocation_rule') != 'allocation_by_measurement') | (Eval('state') == 'billed')),
            }
        ),'on_change_with_measurements', 
        setter='set_measurements',
        )


    settlement_units = fields.One2Many('real_estate.settlement_unit', 'cost_object', 'Settlement Units',
        states={ 
            'readonly': True, 
            'invisible': ((Bool(Eval('settlement_units',0)) == False ) | (Eval('state') == 'draft')),
            },
        )
    
    value_total = fields.Float('Value to Total', digits=(16, 4),
      states={  'readonly': True,  }
        )

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
        CostGroup = pool.get('real_estate.cost_group')
        return CostGroup.fields_get(['state'])['state']['selection']     
    
    @staticmethod
    def get_sub_states():
        pool = Pool()
        SettlementUnit = pool.get('real_estate.settlement_unit')
        return SettlementUnit.fields_get(['state'])['state']['selection']

    @fields.depends('type', 'sequence')
    def on_change_type(self):
        if self.type and not self.sequence:
            self.sequence = self.type.sequence

    @fields.depends('cost_group')
    def on_change_with_state(self, name=None):
        return self.cost_group.state if self.cost_group else None     
    
    @fields.depends('settlement_units')
    def on_change_with_sub_state(self, name=None):
        #return the lowest state of all settlement units
        if self.settlement_units:
            states = set(settlement_unit.state for settlement_unit in self.settlement_units)
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
        return 'error' #if no settlement unit linked, return error to avoid the cost object can be selected in cost group selection state

    @fields.depends('cost_group')
    def on_change_with_property(self, name=None):
        return self.cost_group.property if self.cost_group else None
    
    @fields.depends('cost_group')
    def on_change_with_company(self, name=None):
        return self.cost_group.property.company if self.cost_group else None

    @fields.depends('cost_group', 'reg_ex_object', 'allocation_rule')
    def on_change_with_objects(self, name=None):
        objects = []
        if self.cost_group and self.allocation_rule != 'no_allocation':
            objects = Pool().get('real_estate.base_object').search([
                ('company', '=', self.cost_group.company),
                ('property', '=', self.cost_group.property),
                ('type', '=', 'object'),
                ('state', '=', 'approved'), #only search approved objects
            ])
            if self.reg_ex_object:
                pattern = re.compile(self.reg_ex_object)
                objects = [item for item in objects if pattern.search(item.name)]
        return objects
    
    @fields.depends('cost_group', 'reg_ex_meter', 'allocation_rule', 'objects', 'meter_unit')
    def on_change_with_meters(self, name=None):
        meters = []
        if self.cost_group and self.objects and self.allocation_rule == 'allocation_by_consumption':
            meters = Pool().get('real_estate.base_object').search([
                ('company', '=', self.cost_group.company),
                ('property', '=', self.cost_group.property),
                ('parent', 'in', [obj.id for obj in self.objects]), #only search meters which are linked to the objects
                ('type', '=', 'equipment'),
                ('e_type', '=', 'meters'), #only search meters which have measurement type
                ('meter_unit', '=', self.meter_unit), #only search meters which have the same unit
                ('state', '=', 'approved'), #only search approved objects
            ])
            if self.reg_ex_meter:
                pattern = re.compile(self.reg_ex_meter)
                meters = [item for item in meters if pattern.search(item.name)]
        return meters

    @fields.depends('cost_group', 'm_type', 'allocation_rule', 'objects')
    def on_change_with_measurements(self, name=None):
        measurements = []
        if self.cost_group and self.objects and self.allocation_rule == 'allocation_by_measurement':
            measurements = Pool().get('real_estate.measurement').search([
                ('base_object', 'in', [obj.id for obj in self.objects]), #only search measurements which are linked to the objects
                ('m_type', '=', self.m_type), #only search measurements which have the same measurement type
            ], order=[('base_object', 'ASC'),('valid_from', 'DESC')]) #order by field_name to make sure the sequence of measurements is correct
        return measurements

    @classmethod
    def set_objects(cls, objects, name, value):
        # `objects` = Liste der Instanzen,
        # `name` = Feldname ('objects'),
        # `value` = neuer Wert, z.B. Liste von IDs bei Many2Many
        pass   # hier Logik schreiben    

    @classmethod
    def set_meters(cls, meters, name, value):
        pass   # hier Logik schreiben

    @classmethod
    def set_measurements(cls, measurements, name, value):
        pass   # hier Logik schreiben

    @fields.depends('type')
    def on_change_with_sequence(self, name=None):
        return self.type.sequence if ( self.type and not self.sequence ) else self.sequence

    @fields.depends('cost_group')
    def on_change_with_start_date(self, name=None):
        return self.cost_group.start_date if self.cost_group else None
    
    @fields.depends('cost_group')
    def on_change_with_end_date(self, name=None):
        return self.cost_group.end_date if self.cost_group else None

    @fields.depends('type', 'sequence')
    def on_change_with_name(self, name=None):
        return f"{self.sequence} - {self.type.name}" if self.type else f"{self.sequence} - ? "
    
    @fields.depends('company')
    def on_change_with_currency(self, name=None):
        return self.company.currency if self.company else None    

    def selection(self):
        if self.state != 'approved':
            raise ValidationError(gettext("Only cost object with state 'Approved' can be selected."))

        #all settlement units linked to this cost object delete
        for settlement_unit in self.settlement_units:
            settlement_unit.delete()

        object_count = 0
        #all object linked to this cost object must be in state 'approved'
        for object in self.objects:
            #only start date and end date of the object, it should be in the range of cost object start date and end date
            if object.state == 'approved' and \
                object.start_date <= self.end_date and ( object.end_date == None or object.end_date >= self.start_date):
                object_cont += 1

                if self.cost_group.calculation_method == 'WEG_billing' :
                    #only the last one contract 
                    contract_items = Pool().get('real_estate.contract.item').search([
                        ('object', '=', object), #only search contract which have contract item linked to the object
                        ('valid_from', '<=', self.end_date),
                        (('valid_to', '>=', self.start_date) or ('valid_to', '=', None)),
                        ('contract.state', 'in', ('running','terminaated')), #only search contract in state 'running' or 'terminated'
                        ],
                        order=[('valid_from', 'DESC')], #select the last contract
                        limit=1) #only one contract
                else:
                    #all contracts in the validation date range
                    contract_items = Pool().get('real_estate.contract.item').search([
                        ('object', '=', object), #only search contract which have contract item linked to the object
                        ('valid_from', '<=', self.end_date),
                        (('valid_to', '>=', self.start_date) or ('valid_to', '=', None)),
                        ('contract.state', 'in', ('running','terminaated')), #only search contract in state 'running' or 'terminated'
                        ],
                        order=[('valid_from', 'ASC')]) #order by start date to make sure the sequence of settlement unit is correct

                for contract_item in contract_items:
                    settlement_unit = Pool().get('real_estate.settlement_unit')()
                    settlement_unit.cost_object = self.id
                    settlement_unit.contract = contract_item.contract.id
                    settlement_unit.base_object = contract_item.object.id
                    settlement_unit.start_date = max(contract_item.start_date, self.start_date) if contract_item.start_date else self.start_date
                    settlement_unit.end_date = min(contract_item.end_date, self.end_date) if contract_item.end_date else self.end_date
                    settlement_unit.state = 'selection'
                    if self.cost_group.calculation_method == 'WEG_billing':
                        settlement_unit.start_date = self.cost_group.start_date
                        settlement_unit.end_date = self.cost_group.end_date
                    settlement_unit.save()
                if not contract_items:
                    self.cost_group.add_log('selection_error', f'Cost object {self.id} can not be selected because no contract item found for object {object.id} in the date range.')
            
        if object_count == 0:           
            self.cost_group.add_log('selection', f'Cost object {self.id} is selected with {object_count} objects and {len(self.settlement_units)} settlement units.')  

        if len(self.settlement_units) > 0:
            self.state = 'selection'
        else:
            self.state = 'error'    

        self.save()
        
    def builling(self, selection_on=False):
        if self.state == 'billed':
            raise ValidationError(gettext("This cost object is already billed."))
        if self.state != 'draft':
            raise ValidationError(gettext("Only cost object with state 'Approved' can be billed."))

        if selection_on:
            #if cost object without allocation rule 'no_allocation' can be billed without selection
            if self.allocation_rule != 'no_allocation':
                self.selection()
            

        #self.state = 'billed'
        #self.save()



    @classmethod
    def name_search(cls, name, clause):
        if clause[1].startswith('!') or clause[1].startswith('not '):
            bool_op = 'AND'
        else:
            bool_op = 'OR'

        return [bool_op,
            ('property.name',) + tuple(clause[1:]),
            ('commend',) + tuple(clause[1:]),
        ]      

#**********************************************************************
class SettlementUnit(DeactivableMixin, ModelSQL, ModelView):
    __name__ = 'real_estate.settlement_unit'

    cost_object = fields.Many2One('real_estate.cost_object', 'Cost Object', required=True, ondelete='CASCADE',)

    state = fields.Selection([
            ('selection', 'Selection'),
            ('estimated_value_share', 'Estimated Value Share'),
            ('value_share', 'Value Share'),
            ('error', 'Error'),
            ], "Settlement Unit", sort=False,
            states={ 'readonly': True, },
            )
    
    start_date = fields.Date('Start Date', 
         states={
        'readonly': True,},
        )
    
    end_date = fields.Date('End Date', 
         states={
        'readonly': True,},
        )
    
    contract = fields.Many2One('real_estate.contract', 'Contract', ondelete='CASCADE',
        states={
        'readonly': True,},
        )
    
    base_object = fields.Many2One('real_estate.base_object', 'Object', ondelete='CASCADE',
        states={
        'readonly': True,},
        )
    
    value_share = fields.Float('Value Share',digits=(16, 4),
        states={
        'readonly': Eval('state') != 'value_share',},
        )

    planned_costs = Monetary('Planned Costs', currency='currency', digits= 'currency',#(16, 2),
        states={
            'readonly': Eval('state') == 'billed',
            },
        )
    
    actual_costs = Monetary('Actual Costs', currency='currency', digits= 'currency',#(16, 2),
        states={
            'readonly': Eval('state') != 'value_share',
            },
        )

    currency = fields.Function(fields.Many2One('currency.currency', 'Currency',), 'on_change_with_currency') 

    error_message = fields.Char('Error Message', readonly=True)


    @classmethod
    def default_state(cls):
        return 'selection'
    
    @fields.depends('cost_object')
    def on_change_with_currency(self, name=None):
        return self.cost_object.currency if self.cost_object else None