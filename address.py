# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
'Address'
import re
from string import Template

from sql import Literal
from sql.operators import Equal

from trytond.cache import Cache
from trytond.i18n import gettext
from trytond.model import (
    DeactivableMixin, Exclude, MatchMixin, ModelSQL, ModelView, fields,
    sequence_ordered)
from trytond.model.exceptions import AccessError
from trytond.pool import Pool
from trytond.pyson import Eval, If
from trytond.rpc import RPC
from trytond.transaction import Transaction

from trytond.model.exceptions import ValidationError
class InvalidFormat(ValidationError):
    pass


class Address(
        DeactivableMixin, sequence_ordered(),
        ModelSQL, ModelView):
    " Address - Real Estate Address "
    __name__ = 'real_estate.address'

    street = fields.Function(fields.Text(
            "Street",
            states={
                'readonly': (
                    Eval('street_name')
                    | Eval('building_number')
                    | Eval('unit_number')
                    | Eval('floor_number')
                    | Eval('room_number')
                    | Eval('post_box')
                    | Eval('post_office')
                    | Eval('private_bag')),
                }),
        'on_change_with_street', setter='set_street', searcher='search_street')
    street_unstructured = fields.Text(
        "Street",
        states={
            'invisible': (
                (Eval('street_name')
                    | Eval('building_number')
                    | Eval('unit_number')
                    | Eval('floor_number')
                    | Eval('room_number')
                    | Eval('post_box')
                    | Eval('post_office')
                    | Eval('private_bag'))
                & ~Eval('street_unstructured')),
            })

    street_name = fields.Char(
        "Street Name",
        states={
            'invisible': Eval('street_unstructured') & ~Eval('street_name'),
            })
    building_name = fields.Char(
        "Building Name",
        states={
            'invisible': Eval('street_unstructured') & ~Eval('building_name'),
            })
    building_number = fields.Char(
        "Building Number",
        states={
            'invisible': (
                Eval('street_unstructured') & ~Eval('building_number')),
            })
    unit_number = fields.Char(
        "Unit Number",
        states={
            'invisible': Eval('street_unstructured') & ~Eval('unit_number'),
            })
    floor_number = fields.Char(
        "Floor Number",
        states={
            'invisible': Eval('street_unstructured') & ~Eval('floor_number'),
            })
    room_number = fields.Char(
        "Room Number",
        states={
            'invisible': Eval('street_unstructured') & ~Eval('room_number'),
            })

    post_box = fields.Char(
        "Post Box",
        states={
            'invisible': Eval('street_unstructured') & ~Eval('post_box'),
            })
    private_bag = fields.Char(
        "Private Bag",
        states={
            'invisible': Eval('street_unstructured') & ~Eval('private_bag'),
            })
    post_office = fields.Char(
        "Post Office",
        states={
            'invisible': Eval('street_unstructured') & ~Eval('post_office'),
            })

    street_single_line = fields.Function(
        fields.Char("Street"),
        'on_change_with_street_single_line',
        searcher='search_street_single_line')
    postal_code = fields.Char("Postal Code")
    city = fields.Char("City")
    country = fields.Many2One('country.country', "Country")
    subdivision_types = fields.Function(
        fields.MultiSelection(
            'get_subdivision_types', "Subdivision Types"),
        'on_change_with_subdivision_types')
    subdivision = fields.Many2One("country.subdivision",
        'Subdivision',
        domain=[
            ('country', '=', Eval('country', -1)),
            If(Eval('subdivision_types', []),
                ('type', 'in', Eval('subdivision_types', [])),
                ()
                ),
            ])
    full_address = fields.Function(fields.Text('Full Address'),
            'get_full_address')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls.__rpc__.update(
            autocomplete_postal_code=RPC(instantiate=0, cache=dict(days=1)),
            autocomplete_city=RPC(instantiate=0, cache=dict(days=1)),
            )

    @classmethod
    def __register__(cls, module_name):
        table = cls.__table_handler__(module_name)

        # Migration from 7.4: rename street to street_unstructured
        # and name to building_name
        table.column_rename('street', 'street_unstructured')
        table.column_rename('name', 'building_name')

        super().__register__(module_name)

    @classmethod
    def default_county(cls):
        lCompany = Transaction().context.get('company')
        if lCompany:
            return lCompany.county  
        return Transaction().context.get('country')

    @fields.depends('street')
    def on_change_with_street_single_line(self, name=None):
        if self.street:
            return " ".join(self.street.splitlines())

    @classmethod
    def search_street_single_line(cls, name, domain):
        return [('street',) + tuple(domain[1:])]

    _autocomplete_limit = 100

    @fields.depends('country', 'subdivision')
    def _autocomplete_domain(self):
        domain = []
        if self.country:
            domain.append(('country', '=', self.country.id))
        if self.subdivision:
            domain.append(['OR',
                    ('subdivision', 'child_of',
                        [self.subdivision.id], 'parent'),
                    ('subdivision', '=', None),
                    ])
        return domain

    def _autocomplete_search(self, domain, name):
        pool = Pool()
        PostalCode = pool.get('country.postal_code')
        if domain:
            records = PostalCode.search(domain, limit=self._autocomplete_limit)
            if len(records) < self._autocomplete_limit:
                return sorted({getattr(z, name) for z in records})
        return []

    @fields.depends('city', methods=['_autocomplete_domain'])
    def autocomplete_postal_code(self):
        domain = [
            self._autocomplete_domain(),
            ('postal_code', 'not in', [None, '']),
            ]
        if self.city:
            domain.append(('city', 'ilike', '%%%s%%' % self.city))
        return self._autocomplete_search(domain, 'postal_code')

    @fields.depends('postal_code', methods=['_autocomplete_domain'])
    def autocomplete_city(self):
        domain = [
            self._autocomplete_domain(),
            ('city', 'not in', [None, '']),
            ]
        if self.postal_code:
            domain.append(('postal_code', 'ilike', '%s%%' % self.postal_code))
        return self._autocomplete_search(domain, 'city')

    def get_full_address(self, name):
        pool = Pool()
        AddressFormat = pool.get('party.address.format')
        full_address = Template(AddressFormat.get_format(self)).substitute(
            **self._get_address_substitutions())
        return self._strip(full_address)

    def _get_address_substitutions(self):
        pool = Pool()
        Country = pool.get('country.country')

        context = Transaction().context
        subdivision_code = ''
        if getattr(self, 'subdivision', None):
            subdivision_code = self.subdivision.code or ''
            if '-' in subdivision_code:
                subdivision_code = subdivision_code.split('-', 1)[1]
        country_name = ''
        if getattr(self, 'country', None):
            with Transaction().set_context(language='en'):
                country_name = Country(self.country.id).name
        substitutions = {
            'street': getattr(self, 'street', None) or '',
            'postal_code': getattr(self, 'postal_code', None) or '',
            'city': getattr(self, 'city', None) or '',
            'subdivision': (self.subdivision.name
                if getattr(self, 'subdivision', None) else ''),
            'subdivision_code': subdivision_code,
            'country': country_name,
            'country_code': (self.country.code or ''
                if getattr(self, 'country', None) else ''),
            }
        # Keep zip for backward compatibility
        substitutions['zip'] = substitutions['postal_code']
        if context.get('address_from_country') == getattr(self, 'country', ''):
            substitutions['country'] = ''

        for key, value in list(substitutions.items()):
            substitutions[key.upper()] = value.upper()
        substitutions.update(self._get_street_substitutions())
        return substitutions

    @fields.depends('street', 'street_unstructured')
    def on_change_street(self):
        self.street_unstructured = self.street

    @fields.depends(
        'street_unstructured', 'country',
        methods=['_get_street_substitutions'])
    def on_change_with_street(self, name=None):
        pool = Pool()
        AddressFormat = pool.get('party.address.format')

        format_ = AddressFormat.get_street_format(self)
        street = Template(format_).substitute(
            **self._get_street_substitutions())
        if not (street := self._strip(street, doublespace=True)):
            street = self.street_unstructured
        return street

    @classmethod
    def set_street(cls, addresses, name, value):
        addresses = [a for a in addresses if a.street != value]
        cls.write(addresses, {
                'street_unstructured': value,
                'street_name': None,
                'building_name': None,
                'building_number': None,
                'unit_number': None,
                'floor_number': None,
                'room_number': None,
                })

    @classmethod
    def search_street(cls, name, clause):
        if clause[1].startswith('!') or clause[1].startswith('not '):
            bool_op = 'AND'
        else:
            bool_op = 'OR'
        return [bool_op,
            ('street_unstructured', *clause[1:]),
            ('street_name', *clause[1:]),
            ('building_name', *clause[1:]),
            ('building_number', *clause[1:]),
            ('unit_number', *clause[1:]),
            ('floor_number', *clause[1:]),
            ('room_number', *clause[1:]),
            ]

    @property
    def numbers(self):
        pool = Pool()
        AddressFormat = pool.get('party.address.format')

        format_ = AddressFormat.get_street_format(self)
        substitutions = {
            k: v if k.lower().endswith('_number') else ''
            for k, v in self._get_street_substitutions().items()}
        numbers = Template(format_).substitute(**substitutions)
        return self._strip(numbers, doublespace=True)

    @fields.depends(
        'country', 'street_name', 'building_number', 'unit_number',
        'floor_number', 'room_number', 'post_box', 'private_bag',
        'post_office')
    def _get_street_substitutions(self):
        pool = Pool()
        AddressFormat = pool.get('party.address.format')

        substitutions = {
            'street_name': getattr(self, 'street_name', None) or '',
            'building_name': getattr(self, 'building_name', None) or '',
            'building_number': getattr(self, 'building_number', None) or '',
            'unit_number': getattr(self, 'unit_number', None) or '',
            'floor_number': getattr(self, 'floor_number', None) or '',
            'room_number': getattr(self, 'room_number', None) or '',
            'post_box': getattr(self, 'post_box', None) or '',
            'private_bag': getattr(self, 'private_bag', None) or '',
            'post_office': getattr(self, 'post_office', None) or '',
            }
        for number in [
                'building_number',
                'unit_number',
                'floor_number',
                'room_number',
                'post_box',
                'private_bag',
                'post_office',
                ]:
            if (substitutions[number]
                    and (format_ := AddressFormat.get_number_format(
                            number, self))):
                substitutions[number] = format_.format(substitutions[number])
        for key, value in list(substitutions.items()):
            substitutions[key.upper()] = value.upper()
        return substitutions

    @classmethod
    def _strip(cls, value, doublespace=False):
        value = re.sub(
            r'[\,\/,–][\s,\,\/]*([\,\/,–])', r'\1', value, flags=re.MULTILINE)
        if doublespace:
            value = re.sub(r' {1,}', r' ', value, flags=re.MULTILINE)
        value = value.splitlines()
        value = map(lambda x: x.strip(' ,/–'), value)
        return '\n'.join(filter(None, value))


    def get_rec_name(self, name):
        if self.street_single_line:
            street = self.street_single_line
        else:
            street = None
        if self.country:
            country = self.country.code
        else:
            country = None
        return ', '.join(
            filter(None, [
                    street,
                    self.postal_code,
                    self.city,
                    country]))

    @classmethod
    def search_rec_name(cls, name, clause):
        if clause[1].startswith('!') or clause[1].startswith('not '):
            bool_op = 'AND'
        else:
            bool_op = 'OR'
        return [bool_op,
            ('street',) + tuple(clause[1:]),
            ('postal_code',) + tuple(clause[1:]),
            ('city',) + tuple(clause[1:]),
            ('country',) + tuple(clause[1:]),
            ]

    @fields.depends('subdivision', 'country')
    def on_change_country(self):
        if (self.subdivision
                and self.subdivision.country != self.country):
            self.subdivision = None

    @classmethod
    def get_subdivision_types(cls):
        pool = Pool()
        Subdivision = pool.get('country.subdivision')
        selection = Subdivision.fields_get(['type'])['type']['selection']
        return [(k, v) for k, v in selection if k is not None]

    @fields.depends('country')
    def on_change_with_subdivision_types(self, name=None):
        pool = Pool()
        Types = pool.get('party.address.subdivision_type')
        return Types.get_types(self.country)

