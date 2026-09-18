'Contract Reports'
import re
import datetime
from decimal import Decimal

from trytond.i18n import gettext
from trytond.model.exceptions import ValidationError
from trytond.pool import Pool
from trytond.report import Report


#**********************************************************************
class ContractReport(Report):
    "Contract Context"
    __name__ = 'real_estate.contract.report'

    @classmethod
    def format_value(cls, value):
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
        if type(value) == Decimal:
            return cls.format_number(value, None, digits=2)
        if type(value) == datetime.date:
            return cls.format_date(value)
        if type(value) == datetime.datetime:
            return cls.format_datetime(value)
        return value

    @classmethod
    def get_context(cls, records, header, data):
        context = super().get_context(records, header, data)
        context['format_value'] = cls.format_value
        # The template needs Decimal(0) as sum()'s start value for exact
        # arithmetic - Genshi's sandboxed template evaluator forbids any
        # import statement (including inside a template's own <?python?>
        # block), so it must be injected here instead, the same way core
        # itself injects 'datetime' in Report.get_context().
        context['Decimal'] = Decimal
        return context


#**********************************************************************
class ContractAnnex4Report(Report):
    "Contract Annex 4 – Betriebskostenaufstellung"
    __name__ = 'real_estate.contract.annex4.report'

    @classmethod
    def format_value(cls, value):
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
        if type(value) == Decimal:
            return cls.format_number(value, None, digits=2)
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
                return gettext(
                    'real_estate.msg_allocation_by_consumption_with_unit',
                    ).format(su.meter_unit.symbol)
            return gettext('real_estate.msg_allocation_by_consumption')
        elif rule == 'allocation_per_rental_unit':
            return gettext('real_estate.msg_allocation_per_rental_unit')
        elif rule == 'allocation_from_external_billing':
            return gettext('real_estate.msg_allocation_from_external_billing')
        elif rule == 'no_allocation':
            return gettext('real_estate.msg_allocation_none')
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
        record = context['record']
        context['format_value'] = cls.format_value

        bk_groups = []
        # use the contract's own settlement_units field (last valid
        # settlement units, see Contract.get_settlement_units) instead of
        # re-deriving the billing unit here
        sus = [
            su for su in record.settlement_units
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


#**********************************************************************
class ContractTerminationConfirmationReport(Report):
    """Prints a termination confirmation letter from the contract form -
    triggered by the 'print_termination_confirmation' button
    (Contract.print_termination_confirmation() in contract_core.py),
    itself only visible once the contract is in the 'terminated' state
    (i.e. an actual termination has been recorded, via
    TerminateContractWizard or manually)."""
    __name__ = 'real_estate.contract.termination_confirmation.report'

    @classmethod
    def format_value(cls, value):
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
        if type(value) == Decimal:
            return cls.format_number(value, None, digits=2)
        if type(value) == datetime.date:
            return cls.format_date(value)
        if type(value) == datetime.datetime:
            return cls.format_datetime(value)
        return value

    @classmethod
    def get_context(cls, records, header, data):
        pool = Pool()
        Contract = pool.get('real_estate.contract')

        # Defense in depth: the print button is only visible on a
        # 'terminated' contract, but the report itself is reachable by
        # any code that knows the action id (RPC, another button) - so
        # the actual state requirement is enforced here too, not just via
        # the button's own 'invisible' state.
        for record in records:
            if record.state != 'terminated':
                raise ValidationError(gettext(
                    'real_estate.'
                    'msg_contract_termination_confirmation_not_terminated',
                    name=record.rec_name))

        context = super().get_context(records, header, data)
        context['format_value'] = cls.format_value

        # Selection fields: resolve the translated label for the current
        # value directly (fields_get() already returns the selection
        # list translated into the active report language), rather than
        # exposing the raw storage key to the template.
        fields = Contract.fields_get(['terminated_by_type', 'termination_notice'])
        terminated_by_labels = dict(fields['terminated_by_type']['selection'])
        termination_notice_labels = dict(
            fields['termination_notice']['selection'])
        context['terminated_by_label'] = {
            record.id: terminated_by_labels.get(record.terminated_by_type, '')
            for record in records}
        context['termination_notice_label'] = {
            record.id: termination_notice_labels.get(
                record.termination_notice, '')
            for record in records}
        return context
