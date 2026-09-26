'Contract Party'
from collections import defaultdict

from trytond.model import (
    DeactivableMixin, ModelSQL, ModelView, fields, Unique, sequence_ordered)
from trytond.model.exceptions import ValidationError
from trytond.i18n import gettext
from trytond.pool import Pool
from trytond.pyson import Bool, Eval, If


#**********************************************************************
class ContractPartyRoleCType(ModelSQL):
    "Contract Party Role - Contract Type"
    __name__ = 'real_estate.contract.party.role-contract.type'

    role = fields.Many2One(
        'real_estate.contract.party.role', "Role",
        ondelete='CASCADE', required=True)
    c_type = fields.Many2One(
        'real_estate.contract.type', "Contract Type",
        ondelete='CASCADE', required=True)

    @classmethod
    def __setup__(cls):
        super().__setup__()
        t = cls.__table__()
        cls._sql_constraints += [
            ('role_c_type_unique', Unique(t, t.role, t.c_type),
                'real_estate.msg_contract_party_role_c_type_unique'),
            ]


#**********************************************************************
class ContractPartyRole(DeactivableMixin, sequence_ordered(), ModelSQL, ModelView):
    "Contract Party Role"
    __name__ = 'real_estate.contract.party.role'

    name = fields.Char("Name", required=True, translate=True)
    default = fields.Boolean("Default",
        help="Check to use as default role.")
    contract_types = fields.Many2Many(
        'real_estate.contract.party.role-contract.type', 'role', 'c_type',
        "Contract Types",
        help="Contract types this role can be used for. Leave empty to "
             "allow it for any contract type.")
    mandatory = fields.Boolean("Mandatory Role",
        help="If checked, this role must be assigned without gaps for the "
             "whole validity period of every applicable contract (from "
             "its start date to its effective end date, or indefinitely "
             "if the contract has none). Checked on save - only a "
             "warning while the contract is in 'Draft', an error "
             "otherwise.")
    only_once = fields.Boolean("Only Once",
        help="If checked, this role may be assigned to an applicable "
             "contract at most once at any given point in time (no "
             "overlapping valid from/to periods). Checked on save - only "
             "a warning while the contract is in 'Draft', an error "
             "otherwise.")


#**********************************************************************
class ContractParty(ModelSQL, ModelView):
    "Contract Party"
    __name__ = 'real_estate.contract.party'

    contract = fields.Many2One(
        'real_estate.contract', 'Contract', required=True,
        path='path', ondelete='CASCADE')
    party = fields.Many2One('party.party', 'Party', required=True)
    role = fields.Many2One(
        'real_estate.contract.party.role', "Role", required=True,
        domain=[If(Bool(Eval('c_type')),
            ['OR',
                ('contract_types', '=', None),
                ('contract_types', '=', Eval('c_type'))],
            ())])
    valid_from = fields.Date('Valid from')
    valid_to = fields.Date('Valid to')

    invoice_address = fields.Many2One('party.address', 'Invoice Address',
        domain=[('party', '=', Eval('party', -1))],
        depends=['party'])

    phone_partner = fields.Function(fields.Char("Phone Partner"),
        'get_phone_partner')

    name = fields.Function(fields.Char("Name"),
        'on_change_with_name', searcher='compute_name_search')

    c_type = fields.Function(
        fields.Many2One('real_estate.contract.type', "Contract Type"),
        'on_change_with_c_type')

    @fields.depends('party', 'role')
    def on_change_with_name(self, name=None):
        if self.party and self.role:
            return f"{self.party.name} ({self.role.name})"
        return " - "

    @fields.depends('party')
    def on_change_party(self):
        if self.party:
            self.invoice_address = self.party.address_get(type='invoice')

    def get_phone_partner(self, name=None):
        if self.party:
            phone = self.party.contact_mechanism_get(types='phone')
            if phone:
                return phone.value.replace('\n', ' / ')
        return ''

    @fields.depends('contract', '_parent_contract.c_type')
    def on_change_with_c_type(self, name=None):
        if self.contract:
            return self.contract.c_type
        return None

    @fields.depends('contract', 'valid_from', '_parent_contract.start_date')
    def on_change_with_valid_from(self, name=None):
        if self.contract and self.valid_from is None:
            return self.contract.start_date
        return self.valid_from

    @classmethod
    def __setup__(cls):
        super().__setup__()
        t = cls.__table__()
        cls._sql_constraints = [
            ('party_unique',
                Unique(t, t.party, t.contract, t.valid_from, t.role),
                'real_estate.msg_contract_party_unique'),
        ]

    @classmethod
    def delete(cls, records):
        """Block removing a party from a contract entirely (across all of
        its assignment rows, any role, regardless of valid_from/valid_to)
        if that party still has booked (state='done') cash flow entries
        on this contract - the party must stay traceable as a party of
        the contract even if its specific role assignment period is
        being corrected or removed."""
        pool = Pool()
        CashFlowLine = pool.get('real_estate.contract.term.cash_flow')

        groups = defaultdict(list)
        for cp in records:
            groups[(cp.contract.id, cp.party.id)].append(cp)
        deleted_ids = {cp.id for cp in records}

        for (contract_id, party_id), cps in groups.items():
            remaining = cls.search([
                ('contract', '=', contract_id),
                ('party', '=', party_id),
                ('id', 'not in', list(deleted_ids)),
            ], limit=1)
            if remaining:
                continue
            has_bookings = any(
                cf.invoice and cf.invoice.party.id == party_id
                for cf in CashFlowLine.search([
                    ('term.contract', '=', contract_id),
                    ('state', '=', 'done'),
                ]))
            if has_bookings:
                raise ValidationError(gettext(
                    'real_estate.msg_contract_party_delete_has_bookings',
                    party=cps[0].party.rec_name,
                    contract=cps[0].contract.rec_name))

        super().delete(records)

    @classmethod
    def compute_name_search(cls, name, clause):
        if clause[1].startswith('!') or clause[1].startswith('not '):
            bool_op = 'AND'
        else:
            bool_op = 'OR'
        return [bool_op,
            ('role.name',) + tuple(clause[1:]),
            ('party.name',) + tuple(clause[1:]),
        ]
