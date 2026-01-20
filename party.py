from functools import total_ordering

from sql import Column

from trytond.i18n import lazy_gettext, gettext
from trytond.model import Index, Model, ModelSQL, fields
from trytond.pool import Pool, PoolMeta


class Party(metaclass=PoolMeta):
    'User'
    __name__ = 'party.party'

    sequence = fields.Integer(lazy_gettext('ir.msg_sequence'), )

    salutation = fields.Char('Salutation')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        table = cls.__table__()
        cls._order = [('sequence', 'ASC NULLS FIRST')] + cls._order
        cls._sql_indexes.add(
            Index(table,
                (Column(table, 'sequence'), Index.Range(order='ASC NULLS FIRST')),
                (table.id, Index.Range(order='ASC NULLS FIRST'))))        

    @classmethod
    def default_salutation(cls):
        return gettext('real_estate.msg_salutation') 

