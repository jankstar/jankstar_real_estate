'Contract Term Adjustment'
from trytond.model import ModelSQL, ModelView, Workflow, fields
from trytond.modules.currency.fields import Monetary


#**********************************************************************
class ContractTermAdjustment(Workflow, ModelSQL, ModelView):
    'Contract Term Adjustment'
    __name__ = 'real_estate.contract.term.adjustment'

    adjustment_mode = fields.Selection([
        (None, ''),
        ('percentage', 'Percentage'),
        ('absolute', 'Absolute'),
        ], 'Adjustment Mode', sort=False)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('approved', 'Approved'),
        ('declared', 'Declared'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled'),
        ], 'State', required=True, readonly=True, sort=False)

    term_old = fields.Many2One('real_estate.contract.term', 'Term Old',
        required=True, ondelete='RESTRICT')
    term_new = fields.Many2One('real_estate.contract.term', 'Term New',
        ondelete='RESTRICT')

    settlement_result = fields.Many2One('real_estate.settlement_result',
        'Settlement Result', ondelete='SET NULL')

    company = fields.Function(
        fields.Many2One('company.company', 'Company'), 'get_term_old_ref')
    property = fields.Function(
        fields.Many2One('real_estate.base_object', 'Property'),
        'get_term_old_ref')
    contract = fields.Function(
        fields.Many2One('real_estate.contract', 'Contract'),
        'get_term_old_ref')

    currency = fields.Function(
        fields.Many2One('currency.currency', 'Currency'), 'get_currency')

    valid_from_old = fields.Function(fields.Date('Valid From Old'),
        'get_term_old_fields')
    valid_to_old = fields.Function(fields.Date('Valid To Old'),
        'get_term_old_fields')
    amount_old = fields.Function(
        Monetary('Amount Old', currency='currency', digits='currency'),
        'get_term_old_fields')
    tax_amount_old = fields.Function(
        Monetary('Tax Amount Old', currency='currency', digits='currency'),
        'get_term_old_fields')
    total_amount_old = fields.Function(
        Monetary('Total Amount Old', currency='currency', digits='currency'),
        'get_term_old_fields')

    valid_from_new = fields.Function(fields.Date('Valid From New'),
        'get_term_new_fields')
    valid_to_new = fields.Function(fields.Date('Valid To New'),
        'get_term_new_fields')
    amount_new = fields.Function(
        Monetary('Amount New', currency='currency', digits='currency'),
        'get_term_new_fields')
    tax_amount_new = fields.Function(
        Monetary('Tax Amount New', currency='currency', digits='currency'),
        'get_term_new_fields')
    total_amount_new = fields.Function(
        Monetary('Total Amount New', currency='currency', digits='currency'),
        'get_term_new_fields')

    @staticmethod
    def default_state():
        return 'draft'

    def get_currency(self, name=None):
        if self.term_old and self.term_old.currency:
            return self.term_old.currency.id
        if self.term_new and self.term_new.currency:
            return self.term_new.currency.id
        return None

    @classmethod
    def get_term_old_ref(cls, records, names):
        field_map = {
            'company': 'company',
            'property': 'property',
            'contract': 'contract',
        }
        result = {name: {} for name in names}
        for record in records:
            term = record.term_old
            for name in names:
                related = getattr(term, field_map[name]) if term else None
                result[name][record.id] = related.id if related else None
        return result

    @classmethod
    def get_term_old_fields(cls, records, names):
        return cls._get_term_fields(records, names, 'term_old', '_old')

    @classmethod
    def get_term_new_fields(cls, records, names):
        return cls._get_term_fields(records, names, 'term_new', '_new')

    @classmethod
    def _get_term_fields(cls, records, names, term_field, suffix):
        result = {name: {} for name in names}
        for record in records:
            term = getattr(record, term_field)
            for name in names:
                source_name = (
                    name[:-len(suffix)] if name.endswith(suffix) else name)
                value = getattr(term, source_name) if term else None
                if hasattr(value, 'id'):
                    value = value.id
                result[name][record.id] = value
        return result
