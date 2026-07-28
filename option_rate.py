'Option Rate'
from trytond.model import ModelSQL, ModelView, fields, Unique
from trytond.model.exceptions import ValidationError
from trytond.i18n import gettext


#**********************************************************************
class OptionRate(ModelSQL, ModelView):
    'Option Rate'
    __name__ = 'real_estate.option_rate'

    base_object = fields.Many2One('real_estate.base_object', 'Base Object',
        ondelete='CASCADE')
    settlement_unit = fields.Many2One('real_estate.settlement_unit',
        'Settlement Unit', ondelete='CASCADE')
    billing_unit = fields.Many2One('real_estate.billing_unit', 'Billing Unit',
        ondelete='CASCADE')
    valid_from = fields.Date('Valid From', required=True)
    option_rate = fields.Numeric('Option Rate', digits=(5, 2), required=True,
        domain=[
            ('option_rate', '>=', 0),
            ('option_rate', '<=', 100),
        ],
        help="Percentage (0-100) of input VAT deductible for this period.")

    @classmethod
    def __setup__(cls):
        super().__setup__()
        t = cls.__table__()
        cls._sql_constraints += [
            ('base_object_valid_from_unique',
                Unique(t, t.base_object, t.valid_from),
                'real_estate.msg_option_rate_valid_from_unique'),
            ('settlement_unit_valid_from_unique',
                Unique(t, t.settlement_unit, t.valid_from),
                'real_estate.msg_option_rate_valid_from_unique'),
            ('billing_unit_valid_from_unique',
                Unique(t, t.billing_unit, t.valid_from),
                'real_estate.msg_option_rate_valid_from_unique'),
        ]

    @classmethod
    def validate(cls, records):
        super().validate(records)
        for record in records:
            refs = [record.base_object, record.settlement_unit,
                record.billing_unit]
            if sum(1 for r in refs if r) != 1:
                raise ValidationError(gettext(
                    'real_estate.msg_option_rate_exactly_one_reference'))
