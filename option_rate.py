'Option Rate'
from decimal import Decimal

from trytond.model import ModelSQL, ModelView, fields, Unique
from trytond.model.exceptions import ValidationError
from trytond.i18n import gettext
from trytond.pool import Pool


#**********************************************************************
class OptionRateContext(ModelView):
    'Option Rate Context'
    __name__ = 'real_estate.option_rate.context'

    base_object = fields.Many2One('real_estate.base_object', 'Base Object',
        domain=[('type', 'in', ('property', 'building', 'land', 'object'))])
    billing_unit = fields.Many2One('real_estate.billing_unit', 'Billing Unit')
    settlement_unit = fields.Many2One('real_estate.settlement_unit',
        'Settlement Unit')


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

    #: billing_unit/settlement_unit states excluded from processing.
    _excluded_bu_su_states = ('draft', 'billed')

    @classmethod
    def _expand_selection(cls, base_objects, billing_units, settlement_units):
        """Expand a raw selection into (kind, record) tuples, kind being
        one of 'base_object', 'settlement_unit', 'billing_unit' - matching
        this model's own reference field names 1:1. Base objects of type
        property/building/land are expanded to include their building/
        land/object descendants; an approved property is additionally
        expanded to include its billing units, and each of those to
        include its settlement units; billing units are expanded to
        include their settlement units.

        Status filtering: base objects must be in state 'approved' (any
        other state is fully excluded, both from processing and as a
        basis for an ancestor's dynamic calculation); billing units and
        settlement units in state 'draft' or 'billed' are excluded."""
        result = []
        seen_base_object_ids = set()
        seen_settlement_unit_ids = set()

        def add_base_object(obj):
            if obj.id in seen_base_object_ids or obj.state != 'approved':
                return
            seen_base_object_ids.add(obj.id)
            result.append(('base_object', obj))

        seen_billing_unit_ids = set()

        def add_settlement_unit(su):
            if (su.id in seen_settlement_unit_ids
                    or su.state in cls._excluded_bu_su_states):
                return
            seen_settlement_unit_ids.add(su.id)
            result.append(('settlement_unit', su))

        def add_billing_unit(bu):
            if bu.id in seen_billing_unit_ids:
                return
            seen_billing_unit_ids.add(bu.id)
            if bu.state not in cls._excluded_bu_su_states:
                result.append(('billing_unit', bu))
            for su in bu.settlement_units:
                add_settlement_unit(su)

        for obj in base_objects:
            add_base_object(obj)
            if obj.type in ('property', 'building', 'land') and obj.state == 'approved':
                for desc in cls._approved_descendants(obj):
                    add_base_object(desc)
                if obj.type == 'property':
                    for bu in obj.billing_units:
                        add_billing_unit(bu)

        for bu in billing_units:
            add_billing_unit(bu)

        for su in settlement_units:
            add_settlement_unit(su)

        return result

    @classmethod
    def _current_rate(cls, ref_field, record_id, cutoff_date):
        records = cls.search([
            (ref_field, '=', record_id),
            ('valid_from', '<=', cutoff_date),
            ], order=[('valid_from', 'DESC')], limit=1)
        return records[0] if records else None

    @classmethod
    def get_current_rate_fraction(cls, ref_field, record, date):
        """Current option rate for record (a base_object, settlement_unit,
        or billing_unit - whichever ref_field names) as of date, expressed
        as a 0..1 fraction (e.g. for account.invoice.line.taxes_deductible_rate).
        Returns None if unknown (option_rate_method is dynamic_measurement
        and no rate has ever been booked for record via the update wizard)."""
        current = cls._current_rate(ref_field, record.id, date)
        if current:
            return current.option_rate / Decimal(100)
        if record.option_rate_method == 'fix_100':
            return Decimal(1)
        if record.option_rate_method == 'fix_0':
            return Decimal(0)
        return None

    @classmethod
    def _rental_object_rate(cls, rental_object, cutoff_date):
        current = cls._current_rate(
            'base_object', rental_object.id, cutoff_date)
        if current:
            return current.option_rate
        if rental_object.option_rate_method == 'fix_100':
            return Decimal(100)
        return Decimal(0)

    @classmethod
    def _measurement_type_leaves(cls, m_type):
        """Return the non-group measurement types to sum for m_type: itself
        if it is not a group, or its children (recursively, in case of
        nested groups) if it is."""
        if not m_type.is_group:
            return [m_type]
        leaves = []
        for child in m_type.children:
            leaves.extend(cls._measurement_type_leaves(child))
        return leaves

    @classmethod
    def _measurement_value(cls, base_object, m_type, cutoff_date):
        Measurement = Pool().get('real_estate.measurement')
        total = None
        for leaf in cls._measurement_type_leaves(m_type):
            records = Measurement.search([
                ('base_object', '=', base_object.id),
                ('m_type', '=', leaf.id),
                ('valid_from', '<=', cutoff_date),
                ], order=[('valid_from', 'DESC')], limit=1)
            if records:
                value = Decimal(str(records[0].value))
                total = value if total is None else total + value
        return total

    @classmethod
    def _approved_descendants(cls, base_object):
        """Approved building/land/object descendants of base_object, not
        descending into any non-approved intermediate object - a
        non-approved object excludes its whole subtree, both from
        processing and as a basis for an ancestor's calculation."""
        BaseObject = Pool().get('real_estate.base_object')
        result = []
        for child in BaseObject.search([
                ('parent', '=', base_object.id),
                ('state', '=', 'approved'),
                ('type', 'in', ('building', 'land', 'object')),
                ]):
            result.append(child)
            if child.type in ('building', 'land'):
                result.extend(cls._approved_descendants(child))
        return result

    @classmethod
    def _approved_rental_object_descendants(cls, base_object):
        """Approved rental-object (type='object') descendants of
        base_object (see _approved_descendants for the traversal rule)."""
        return [o for o in cls._approved_descendants(base_object)
            if o.type == 'object']

    @classmethod
    def _rental_objects_of(cls, kind, record):
        """Rental objects (state 'approved' only) feeding a dynamic
        measurement calculation for record."""
        if kind == 'base_object':
            if record.type == 'object':
                return [record] if record.state == 'approved' else []
            return cls._approved_rental_object_descendants(record)
        elif kind == 'settlement_unit':
            return [o for o in record.objects
                if o.type == 'object' and o.state == 'approved']
        elif kind == 'billing_unit':
            rental_objects = []
            seen_ids = set()
            for su in record.settlement_units:
                if su.state in cls._excluded_bu_su_states:
                    continue
                for o in su.objects:
                    if (o.type == 'object' and o.state == 'approved'
                            and o.id not in seen_ids):
                        seen_ids.add(o.id)
                        rental_objects.append(o)
            return rental_objects
        return []

    @classmethod
    def _compute_new_rate(cls, kind, record, cutoff_date):
        if record.option_rate_method == 'fix_0':
            return Decimal(0)
        if record.option_rate_method == 'fix_100':
            return Decimal(100)
        # dynamic_measurement
        m_type = record.option_measurement_type
        if not m_type:
            return None
        numerator = Decimal(0)
        denominator = Decimal(0)
        for rental_object in cls._rental_objects_of(kind, record):
            weight = cls._measurement_value(rental_object, m_type, cutoff_date)
            if weight is None:
                continue
            rate = cls._rental_object_rate(rental_object, cutoff_date)
            numerator += weight * rate
            denominator += weight
        if denominator == 0:
            return None
        return (numerator / denominator).quantize(Decimal('0.01'))

    @classmethod
    def _update_rate(cls, ref_field, record, cutoff_date, effective_date, new_rate):
        if new_rate is None:
            return 'skipped'
        current = cls._current_rate(ref_field, record.id, cutoff_date)
        if current and current.option_rate == new_rate:
            return 'unchanged'
        if current and current.valid_from == effective_date:
            current.option_rate = new_rate
            current.save()
            return 'updated'
        new = cls(**{ref_field: record.id})
        new.valid_from = effective_date
        new.option_rate = new_rate
        new.save()
        return 'created'

    @classmethod
    def process_update(cls, base_objects, billing_units, settlement_units,
            cutoff_date):
        """Recompute and book option rates for the given selection (and its
        descendants) as of cutoff_date. Returns (counts, log) where counts
        is a dict of status -> number of records, and log is a list of
        per-record detail lines."""
        effective_date = cutoff_date.replace(day=1)
        expanded = cls._expand_selection(
            base_objects, billing_units, settlement_units)
        counts = {'created': 0, 'updated': 0, 'unchanged': 0, 'skipped': 0}
        log = []
        for kind, record in expanded:
            new_rate = cls._compute_new_rate(kind, record, cutoff_date)
            status = cls._update_rate(
                kind, record, cutoff_date, effective_date, new_rate)
            counts[status] += 1
            detail = f'{record.rec_name} ({kind}): {status}'
            if new_rate is not None:
                detail += f' -> {new_rate} %'
            log.append(detail)
        return counts, log
