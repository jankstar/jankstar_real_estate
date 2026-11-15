import re

from sql import Column

from trytond.i18n import gettext, lazy_gettext
from trytond.model import (
    DeactivableMixin, Index, ModelSQL, ModelView, fields)
from trytond.pool import PoolMeta
from trytond.pyson import Bool, Eval


def party_sequence(number, code):
    """Sequence of a party with a role number: the number of the role plus
    the digits of the party code ('K-42' counts as 42, like
    `party.party.code_digit`); None without a role number or without any
    digit in the code."""
    if number is None:
        return None
    digits = re.sub(r'\D', '', code or '')[-18:]
    if not digits:
        return None
    return number + int(digits)


class PartyRoleNumber(DeactivableMixin, ModelSQL, ModelView):
    __name__ = 'real_estate.party.role_number'

    name = fields.Char("Name", required=True, translate=True)
    number = fields.Integer(
        "Number", required=True,
        help="Added to the code of the party to get its sequence.")

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._order = [('number', 'ASC'), ('id', 'ASC')]


class Party(metaclass=PoolMeta):
    'User'
    __name__ = 'party.party'

    sequence = fields.Integer(
        lazy_gettext('ir.msg_sequence'),
        states={
            'readonly': Bool(Eval('role_number')),
            })

    salutation = fields.Char('Salutation')

    role_number = fields.Many2One(
        'real_estate.party.role_number', "Party Role", ondelete='RESTRICT',
        help="The sequence is computed from the number of the role "
        "and the code of the party.")

    @classmethod
    def __setup__(cls):
        super().__setup__()
        table = cls.__table__()
        cls._order = [('sequence', 'ASC NULLS FIRST')] + cls._order
        cls._sql_indexes.add(
            Index(table,
                (Column(table, 'sequence'),
                    Index.Range(order='ASC NULLS FIRST')),
                (table.id, Index.Range(order='ASC NULLS FIRST'))))

    @classmethod
    def default_salutation(cls):
        return gettext('real_estate.msg_salutation')

    @fields.depends('role_number', 'code')
    def on_change_role_number(self):
        # Without a role the sequence is emptied; the code of a new party
        # is only known after saving (compute_fields)
        self.sequence = party_sequence(
            self.role_number.number if self.role_number else None,
            self.code)

    @fields.depends('role_number', methods=['on_change_role_number'])
    def on_change_code(self):
        if self.role_number:
            self.on_change_role_number()

    def compute_fields(self, field_names=None):
        values = super().compute_fields(field_names=field_names)
        if self.role_number:
            if (field_names is None
                    or {'code', 'role_number', 'sequence'} & set(field_names)):
                sequence = party_sequence(self.role_number.number, self.code)
                if sequence != self.sequence:
                    values['sequence'] = sequence
        elif (field_names is not None and 'role_number' in field_names
                and 'sequence' not in field_names):
            # Role removed: the sequence is emptied unless set by hand
            if self.sequence is not None:
                values['sequence'] = None
        return values
