'Contract Reports'
import re
import datetime

from trytond.pool import Pool
from trytond.report import Report


#**********************************************************************
class ContractReport(Report):
    "Contract Context"
    __name__ = 'real_estate.contract.report'

    @classmethod
    def _format(cls, value):
        if value is None:
            return ''
        if type(value) == str:
            return value
        if type(value) == bool:
            return str(value)
        if type(value) == int:
            return str(value)
        if type(value) == float:
            return cls.format_number(value, None)
        if type(value) == datetime.date:
            return cls.format_date(value)
        if type(value) == datetime.datetime:
            return cls.format_datetime(value)
        return value

    @classmethod
    def get_context(cls, records, header, data):
        context = super().get_context(records, header, data)
        context['_format'] = cls._format
        return context


#**********************************************************************
class ContractAnnex4Report(Report):
    "Contract Annex 4 – Betriebskostenaufstellung"
    __name__ = 'real_estate.contract.annex4.report'

    @classmethod
    def _format(cls, value):
        if value is None:
            return ''
        if type(value) == str:
            return value
        if type(value) == bool:
            return str(value)
        if type(value) == int:
            return str(value)
        if type(value) == float:
            return cls.format_number(value, None)
        if type(value) == datetime.date:
            return cls.format_date(value)
        if type(value) == datetime.datetime:
            return cls.format_datetime(value)
        return value

    @classmethod
    def _allocation_label(cls, su):
        rule = su.allocation_rule or 'no_allocation'
        if rule == 'allocation_by_measurement' and su.m_type:
            return su.m_type.name
        elif rule == 'allocation_by_consumption':
            if su.meter_unit:
                return 'nach Verbrauch (%s, HeizkostenV)' % su.meter_unit.symbol
            return 'nach Verbrauch (HeizkostenV)'
        elif rule == 'allocation_per_rental_unit':
            return 'je Wohneinheit'
        return '—'

    @classmethod
    def _betrKV_nr(cls, comment):
        if not comment:
            return ''
        m = re.search(r'Nr\.\s*(\d+[a-z]?)', comment)
        return ('Nr. ' + m.group(1)) if m else ''

    @classmethod
    def get_context(cls, records, header, data):
        context = super().get_context(records, header, data)
        pool = Pool()
        BillingUnit = pool.get('real_estate.billing_unit')
        record = context['record']
        context['_format'] = cls._format

        bk_groups = []
        if record.property:
            billing_units = BillingUnit.search([
                ('property', '=', record.property.id),
                ('state', 'not in', ['draft', 'billed']),
            ], order=[('start_date', 'DESC')], limit=1)

            if billing_units:
                bu = billing_units[0]
                sus = [
                    su for su in bu.settlement_units
                    if su.type and not su.type.no_print
                ]
                sus.sort(key=lambda su: (
                    su.type.category_group.sequence
                    if su.type.category_group else 9999,
                    su.type.sequence or 0,
                ))

                current_grp_name = None
                for su in sus:
                    grp = su.type.category_group
                    grp_name = grp.name if grp else '(Sonstige)'
                    if grp_name != current_grp_name:
                        bk_groups.append({'name': grp_name, 'rows': []})
                        current_grp_name = grp_name
                    bk_groups[-1]['rows'].append({
                        'betrKV_nr': cls._betrKV_nr(su.type.comment),
                        'name': su.type.name or '',
                        'allocation': cls._allocation_label(su),
                    })

        context['bk_groups'] = bk_groups
        return context
