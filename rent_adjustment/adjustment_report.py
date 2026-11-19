'Rent Adjustment Reports'
import datetime

from trytond.i18n import gettext
from trytond.model.exceptions import ValidationError
from trytond.pool import Pool
from trytond.report import Report

from ..contract.contract_report import ContractReport
from .contract_index_rent import LETTERS


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
            # no mark for the original and while it is sent (announced,
            # receipt not captured yet), 'Zweitschrift' afterwards
            if original or (record.state == 'declared'
                    and not record.receipt_date):
                marks[record.id] = ''
            elif record.state in ('declared', 'done', 'refused'):
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
class ComparativeRentLetterReport(IndexAdjustmentLetterReport):
    """Request for consent to a rent increase up to the local comparative
    rent (§§ 558, 558a BGB, spezifikation-anpassungslauf.md 10.5) - one
    letter per adjustment to all main tenants, with the reasons from the
    accepted calculation of the rent survey."""
    __name__ = 'real_estate.contract.comparative_rent.letter'

    @classmethod
    def get_context(cls, records, header, data):
        context = super().get_context(records, header, data)
        deadlines = {}
        for record in records:
            # End of the period for consideration (§ 558b BGB): the day
            # before the effective date (preview before the receipt)
            deadlines[record.id] = (record.planned_valid_from
                - datetime.timedelta(days=1)
                if record.planned_valid_from else None)
        context['consent_until'] = deadlines
        return context


#**********************************************************************
class AdjustmentRunSampleLetterReport(Report):
    """Sample letter of an adjustment run before the announcement: the
    letter of the first adjustment without error (else the first one not
    cancelled) of each run, rendered by the letter report of the
    procedure with the mark 'ENTWURF' - nothing is archived."""
    __name__ = 'real_estate.contract.term.adjustment.run.sample_letter'

    @classmethod
    def execute(cls, ids, data):
        pool = Pool()
        Run = pool.get('real_estate.contract.term.adjustment.run')
        samples = []
        for run in Run.browse(ids):
            candidates = [a for a in run.adjustments
                if a.state in ('draft', 'approved')
                and a.procedure in LETTERS]
            candidates.sort(key=lambda a: (a.check_state == 'error', a.id))
            if candidates:
                samples.append(candidates[0])
        if not samples:
            raise ValidationError(gettext(
                    'real_estate.msg_adjustment_run_no_sample',
                    run=', '.join(r.rec_name for r in Run.browse(ids))))
        procedures = {a.procedure for a in samples}
        if len(procedures) > 1:
            raise ValidationError(gettext(
                    'real_estate.msg_adjustment_run_letters_procedures'))
        Letter = pool.get(LETTERS[procedures.pop()], type='report')
        ext, content, direct_print, _ = Letter.execute(
            [a.id for a in samples], {
                'model': 'real_estate.contract.term.adjustment',
                })
        ActionReport = pool.get('ir.action.report')
        actions = ActionReport.search([
                ('report_name', '=', cls.__name__),
                ], limit=1)
        title = actions[0].name if actions else cls.__name__
        name = '-'.join([title] + [r.run_id for r in Run.browse(ids)])
        return ext, content, direct_print, name


#**********************************************************************
class AdjustmentRunLettersReport(Report):
    """All letters of an adjustment run to send in one document: the
    announced adjustments whose receipt is not captured yet, rendered by
    the letter report of the procedure (without mark)."""
    __name__ = 'real_estate.contract.term.adjustment.run.letters'

    @classmethod
    def execute(cls, ids, data):
        pool = Pool()
        Run = pool.get('real_estate.contract.term.adjustment.run')
        adjustments = [a for r in Run.browse(ids) for a in r.adjustments
            if a.state == 'declared' and not a.receipt_date
            and a.procedure in LETTERS]
        if not adjustments:
            raise ValidationError(gettext(
                    'real_estate.msg_adjustment_run_no_letters',
                    run=', '.join(r.rec_name for r in Run.browse(ids))))
        procedures = {a.procedure for a in adjustments}
        if len(procedures) > 1:
            raise ValidationError(gettext(
                    'real_estate.msg_adjustment_run_letters_procedures'))
        Letter = pool.get(LETTERS[procedures.pop()], type='report')
        ext, content, direct_print, _ = Letter.execute(
            [a.id for a in adjustments], {
                'model': 'real_estate.contract.term.adjustment',
                })
        ActionReport = pool.get('ir.action.report')
        actions = ActionReport.search([
                ('report_name', '=', cls.__name__),
                ], limit=1)
        title = actions[0].name if actions else cls.__name__
        name = '-'.join([title] + [r.run_id for r in Run.browse(ids)])
        return ext, content, direct_print, name
