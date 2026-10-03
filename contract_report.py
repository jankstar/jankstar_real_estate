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
        context['term_groups'] = {
            record.id: cls.get_term_groups(record) for record in records}
        return context

    @classmethod
    def get_term_groups(cls, contract):
        """Terms of the contract for § 4 of the contract letter:
        'initial' = recurring terms starting at the contract start (with
        their sum 'initial_total'), 'one_time' = one-time terms (e.g.
        deposit), 'later' = recurring terms starting after the contract
        start (e.g. graduated rent steps) - each ordered by start and
        sequence."""
        start = contract.start_date
        terms = sorted(contract.terms,
            key=lambda t: (t.valid_from or datetime.date.min,
                t.sequence or 0))
        one_time = [t for t in terms if t.rhythm_type == 'one_time']
        recurring = [t for t in terms if t.rhythm_type != 'one_time']
        initial = [t for t in recurring
            if not start or not t.valid_from or t.valid_from <= start]
        later = [t for t in recurring if t not in initial]
        return {
            'initial': initial,
            'initial_total': sum((t.total_amount for t in initial
                    if t.total_amount is not None), Decimal(0)),
            'one_time': one_time,
            'later': later,
            }


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


#**********************************************************************
class IndexAdjustmentLetterReport(Report):
    """Declaration of an index rent adjustment to the tenants (§ 557b
    para. 3 BGB, spezifikation-indexmiete.md 6.1) - one letter per
    adjustment, addressed jointly to all main tenants of the contract.
    'Declare' archives the original (data 'original'); later prints are
    marked as duplicate, prints before the declaration as draft."""
    __name__ = 'real_estate.contract.index_adjustment.letter'

    @classmethod
    def format_value(cls, value):
        return ContractReport.format_value(value)

    @classmethod
    def format_percent(cls, value):
        if value is None:
            return ''
        return cls.format_number(value, None, digits=2)

    @classmethod
    def format_index(cls, value):
        # Index values are published with one decimal
        if value is None:
            return ''
        return cls.format_number(value, None, digits=1)

    @classmethod
    def get_context(cls, records, header, data):
        pool = Pool()
        Party = pool.get('party.party')
        context = super().get_context(records, header, data)
        context['format_value'] = cls.format_value
        context['format_percent'] = cls.format_percent
        context['format_index'] = cls.format_index
        original = bool(data and data.get('original'))
        marks, tenants = {}, {}
        for record in records:
            if original:
                marks[record.id] = ''
            elif record.state in ('declared', 'done'):
                marks[record.id] = 'Zweitschrift'
            else:
                marks[record.id] = 'ENTWURF'
            contract = record.contract
            party_ids = (contract.main_tenant_party_ids or []
                if contract else [])
            parties = Party.browse(party_ids) if party_ids else (
                [contract.contractual_partner]
                if contract and contract.contractual_partner else [])
            tenants[record.id] = [
                (party, party.address_get(type='invoice'))
                for party in parties]
        context['marks'] = marks
        context['tenants'] = tenants
        return context


#**********************************************************************
class HandoverReport(Report):
    """Handover report (Übergabeprotokoll) of move-in, pre-inspection or
    move-out with check items, keys, meter readings and signature fields
    - marked ENTWURF before it is done (spezifikation-uebergabeprotokoll.md
    7)."""
    __name__ = 'real_estate.contract.handover.report'

    @classmethod
    def format_value(cls, value):
        return ContractReport.format_value(value)

    @classmethod
    def get_context(cls, records, header, data):
        pool = Pool()
        Handover = pool.get('real_estate.contract.handover')
        Line = pool.get('real_estate.contract.handover.line')
        Key = pool.get('real_estate.contract.handover.key')
        context = super().get_context(records, header, data)
        context['format_value'] = cls.format_value

        def labels(Model, field):
            return dict(Model.fields_get([field])[field]['selection'])
        context['kinds'] = labels(Handover, 'kind')
        context['general_conditions'] = labels(Handover, 'general_condition')
        context['conditions'] = labels(Line, 'condition')
        context['remedies'] = labels(Line, 'remedy_by')
        context['key_types'] = labels(Key, 'key_type')
        context['marks'] = {r.id: 'ENTWURF' if r.state == 'draft' else ''
            for r in records}
        context['tenants'] = {r.id: [(p, p.address_get(type='invoice'))
                for p in r.tenants] for r in records}
        return context
