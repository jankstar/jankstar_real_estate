import datetime
import json
from decimal import Decimal

from dateutil.relativedelta import relativedelta

from trytond.model.exceptions import ValidationError
from trytond.pool import Pool
from trytond.tests.test_tryton import ModuleTestCase, with_transaction


class _StubNamed:
    "Minimal duck-typed stand-in for a record with a .name/.symbol attribute"

    def __init__(self, name=None, symbol=None):
        self.name = name
        self.symbol = symbol


class _StubSettlementUnit:
    "Minimal duck-typed stand-in for a real_estate.settlement_unit record"

    def __init__(self, allocation_rule=None, m_type=None, meter_unit=None):
        self.allocation_rule = allocation_rule
        self.m_type = m_type
        self.meter_unit = meter_unit


class _StubRecord:
    "Generic duck-typed stand-in for a record: attributes from keywords"

    def __init__(self, **values):
        self.__dict__.update(values)


def _stub_term(term_type=None, payment_term=None):
    return _StubRecord(term_type=term_type, payment_term=payment_term)


def _stub_contract(Contract, invoice_type='out', payment_term=None,
        party=None):
    "Stand-in for a contract that borrows the real periodic posting helpers"
    contract = type('_StubContract', (), {
            '_move_term_type': staticmethod(Contract._move_term_type),
            '_move_group_key': classmethod(
                Contract._move_group_key.__func__),
            '_move_description': Contract._move_description,
            'get_move_payment_term': Contract.get_move_payment_term,
            })()
    contract.c_type = _StubRecord(
        mark='WM', name='Wohnungsmiete', invoice_type=invoice_type)
    contract.payment_term = payment_term
    contract.contractual_partner = party
    return contract


def _stub_index_agreement(RentAdjustment, values, quantity=Decimal(1),
        unit_price=Decimal('800.00'), residential=True, **kwargs):
    """Stand-in for an active index rent agreement that borrows the real
    calculation of RentAdjustment (values: {month: index value})."""
    index = _StubRecord(id=1, base_year=2020, rec_name='VPI-DE')
    index.get_value = lambda month: (_StubRecord(value=values[month])
        if month in values else None)
    term = _StubRecord(id=10, quantity=quantity, unit_price=unit_price,
        graduated_locked=False, rec_name='Miete', get_booked_to=lambda: None)
    contract = _StubRecord(state='running',
        currency=_StubRecord(digits=2), property=None,
        company=_StubRecord(re_accounting=_StubRecord(receipt_days=3)),
        rec_name='Vertrag', get_effective_end_date=lambda: None)
    agreement = type('_StubIndexRent', (), {
            'compute_index_adjustment':
                RentAdjustment.compute_index_adjustment,
            'planned_valid_from': RentAdjustment.planned_valid_from,
            '_receipt_days': RentAdjustment._receipt_days,
            '_declaration_deadline': RentAdjustment._declaration_deadline,
            })()
    agreement.__dict__.update({
            'id': 5, 'price_index': index, 'current_term': term,
            'procedure': 'index_rent', 'state': 'active',
            'contract': contract, '_residential': residential,
            'current_index_month': datetime.date(2025, 1, 1),
            'next_possible_date': datetime.date(2026, 3, 1),
            'threshold_type': 'none', 'threshold_value': None,
            'apply_cap': 'never', 'effective_rule': 'statutory',
            'effective_offset_months': None,
            })
    agreement.__dict__.update(kwargs)
    return agreement


class RealEstateTestCase(ModuleTestCase):
    "Test Real Estate module"
    module = 'real_estate'

    @with_transaction()
    def test_betrkv_nr_extracts_paragraph_number(self):
        "ContractAnnex4Report._betrKV_nr extracts the '§ 2 Nr. N' reference"
        pool = Pool()
        Report = pool.get(
            'real_estate.contract.annex4.report', type='report')

        self.assertEqual(
            Report._betrKV_nr('Grundsteuer, § 2 Nr. 1 BetrKV'), 'Nr. 1')
        self.assertEqual(
            Report._betrKV_nr('Sonstige Kosten, § 2 Nr. 17a BetrKV'),
            'Nr. 17a')
        self.assertEqual(Report._betrKV_nr(''), '')
        self.assertEqual(Report._betrKV_nr(None), '')
        self.assertEqual(Report._betrKV_nr('kein Verweis enthalten'), '')

    @with_transaction()
    def test_allocation_label_by_measurement(self):
        "allocation_by_measurement uses the measurement type's own name"
        pool = Pool()
        Report = pool.get(
            'real_estate.contract.annex4.report', type='report')

        su = _StubSettlementUnit(
            allocation_rule='allocation_by_measurement',
            m_type=_StubNamed(name='Wohnfläche'))
        self.assertEqual(Report._allocation_label(su), 'Wohnfläche')

    @with_transaction()
    def test_allocation_label_by_measurement_without_type(self):
        "allocation_by_measurement without a measurement type falls back"
        pool = Pool()
        Report = pool.get(
            'real_estate.contract.annex4.report', type='report')

        su = _StubSettlementUnit(allocation_rule='allocation_by_measurement')
        self.assertEqual(Report._allocation_label(su), '—')

    @with_transaction()
    def test_allocation_label_by_consumption(self):
        "allocation_by_consumption mentions the meter unit and HeizkostenV"
        pool = Pool()
        Report = pool.get(
            'real_estate.contract.annex4.report', type='report')

        su = _StubSettlementUnit(
            allocation_rule='allocation_by_consumption',
            meter_unit=_StubNamed(symbol='m³'))
        label = Report._allocation_label(su)
        self.assertIn('m³', label)
        self.assertIn('HeizkostenV', label)

        su_no_unit = _StubSettlementUnit(
            allocation_rule='allocation_by_consumption')
        self.assertIn('HeizkostenV', Report._allocation_label(su_no_unit))

    @with_transaction()
    def test_allocation_label_per_rental_unit(self):
        "allocation_per_rental_unit has its own message, not the dash fallback"
        pool = Pool()
        Report = pool.get(
            'real_estate.contract.annex4.report', type='report')

        su = _StubSettlementUnit(allocation_rule='allocation_per_rental_unit')
        label = Report._allocation_label(su)
        self.assertTrue(label)
        self.assertNotEqual(label, '—')

    @with_transaction()
    def test_allocation_label_from_external_billing(self):
        "allocation_from_external_billing has its own message"
        pool = Pool()
        Report = pool.get(
            'real_estate.contract.annex4.report', type='report')

        su = _StubSettlementUnit(
            allocation_rule='allocation_from_external_billing')
        self.assertNotEqual(Report._allocation_label(su), '—')

    @with_transaction()
    def test_allocation_label_no_allocation(self):
        "no_allocation (including a missing allocation_rule) has its own message"
        pool = Pool()
        Report = pool.get(
            'real_estate.contract.annex4.report', type='report')

        su_explicit = _StubSettlementUnit(allocation_rule='no_allocation')
        su_missing = _StubSettlementUnit(allocation_rule=None)
        label = Report._allocation_label(su_explicit)
        self.assertNotEqual(label, '—')
        self.assertEqual(label, Report._allocation_label(su_missing))


    @with_transaction()
    def test_move_group_key_mixed_contract(self):
        "Regular terms share one move, separate_move term types get own ones"
        Contract = Pool().get('real_estate.contract')
        date = datetime.date(2025, 1, 1)
        regular = _StubRecord(id=1, separate_move=False)
        deposit = _StubRecord(id=2, separate_move=True)
        other = _StubRecord(id=3, separate_move=True)
        own_term = _StubRecord(id=7)

        rent = Contract._move_group_key(_stub_term(regular), date)
        costs = Contract._move_group_key(_stub_term(regular), date)
        deposit_1 = Contract._move_group_key(_stub_term(deposit), date)
        deposit_2 = Contract._move_group_key(_stub_term(deposit), date)
        deposit_own = Contract._move_group_key(
            _stub_term(deposit, own_term), date)
        other_key = Contract._move_group_key(_stub_term(other), date)

        self.assertEqual(rent, costs)
        self.assertEqual(rent, (date, 0, 0))
        self.assertEqual(deposit_1, deposit_2)
        self.assertEqual(len({rent, deposit_1, deposit_own, other_key}), 4)
        # A payment term on a regular term does not split the move
        self.assertEqual(
            Contract._move_group_key(_stub_term(regular, own_term), date),
            rent)
        self.assertNotEqual(
            Contract._move_group_key(
                _stub_term(regular), datetime.date(2025, 2, 1)),
            rent)

    @with_transaction()
    def test_move_description_fallback(self):
        "Move description of the term type, else the contract type default"
        Contract = Pool().get('real_estate.contract')
        contract = _stub_contract(Contract)
        date = datetime.date(2025, 3, 1)

        self.assertEqual(
            contract._move_description(None, date), 'WM - 2025-03-01')
        self.assertEqual(
            contract._move_description(
                _StubRecord(move_description=None), date),
            'WM - 2025-03-01')
        self.assertEqual(
            contract._move_description(
                _StubRecord(move_description='Mietkaution'), date),
            'Mietkaution - 2025-03-01')
        contract.c_type.mark = None
        self.assertEqual(
            contract._move_description(None, date),
            'Wohnungsmiete - 2025-03-01')

    @with_transaction()
    def test_move_payment_term_hierarchy(self):
        "Payment term: separate term, else contract, else party"
        Contract = Pool().get('real_estate.contract')
        term_pt = _StubRecord(name='term')
        contract_pt = _StubRecord(name='contract')
        customer_pt = _StubRecord(name='customer')
        supplier_pt = _StubRecord(name='supplier')
        party = _StubRecord(
            customer_payment_term=customer_pt,
            supplier_payment_term=supplier_pt)
        separate = _StubRecord(id=2, separate_move=True)
        regular = _StubRecord(id=1, separate_move=False)

        contract = _stub_contract(
            Contract, payment_term=contract_pt, party=party)
        self.assertIs(contract.get_move_payment_term(
                _stub_term(separate, term_pt)), term_pt)
        # The term's own payment term only applies to a separate move
        self.assertIs(contract.get_move_payment_term(
                _stub_term(regular, term_pt)), contract_pt)
        self.assertIs(contract.get_move_payment_term(
                _stub_term(separate)), contract_pt)

        contract.payment_term = None
        self.assertIs(contract.get_move_payment_term(), customer_pt)
        contract.c_type.invoice_type = 'in'
        self.assertIs(contract.get_move_payment_term(), supplier_pt)

        # Supplier side has no accounting default
        party.supplier_payment_term = None
        self.assertIsNone(contract.get_move_payment_term())

    def test_price_index_csv_parsing(self):
        "CSV import: month formats, decimal comma, GENESIS rows, conflicts"
        from trytond.modules.real_estate.price_index import parse_index_csv

        content = (
            'Monat;Wert\n'
            '2025-01;117,0\n'
            '02.2025;117.6\n'
            '2025;März;118,1\n'
            '2025;April;...\n'
            'Hinweis: vorläufige Werte\n'
            '2025-01;117,0\n'
            '2025-02;999,9\n')
        values, ignored, errors = parse_index_csv(content)
        self.assertEqual(values, {
                datetime.date(2025, 1, 1): Decimal('117.0'),
                datetime.date(2025, 2, 1): Decimal('117.6'),
                datetime.date(2025, 3, 1): Decimal('118.1'),
                })
        # header, '...' value and note row are ignored
        self.assertEqual([n for n, _ in ignored], [1, 5, 6])
        # same month with a different value is a conflict
        self.assertEqual([n for n, _ in errors], [8])

    @with_transaction()
    def test_price_index_values(self):
        "Import, last final month, value lookup and validation"
        pool = Pool()
        Index = pool.get('real_estate.price_index')
        Value = pool.get('real_estate.price_index.value')

        index, = Index.create([{
                    'code': 'TEST', 'name': 'Test', 'base_year': 2020}])
        counts = Index.import_values(index, 2020, {
                datetime.date(2025, 1, 1): Decimal('117.0'),
                datetime.date(2025, 2, 1): Decimal('117.6'),
                })
        self.assertEqual(counts, {'created': 2, 'updated': 0, 'unchanged': 0})
        counts = Index.import_values(index, 2020, {
                datetime.date(2025, 1, 1): Decimal('117.0'),
                datetime.date(2025, 2, 1): Decimal('117.8'),
                })
        self.assertEqual(counts, {'created': 0, 'updated': 1, 'unchanged': 1})
        # provisional value of another base year does not count
        Index.import_values(index, 2025, {
                datetime.date(2025, 3, 1): Decimal('100.4')}, final=False)

        self.assertEqual(index.last_value_month, datetime.date(2025, 2, 1))
        self.assertEqual(
            index.get_value(datetime.date(2025, 2, 15)).value,
            Decimal('117.8'))
        self.assertIsNone(index.get_value(datetime.date(2025, 3, 1)))
        self.assertIsNotNone(index.get_value(
                datetime.date(2025, 3, 1), base_year=2025, final_only=False))

        with self.assertRaises(ValidationError):
            Value.create([{'index': index.id, 'base_year': 2020,
                        'month': datetime.date(2025, 4, 2),
                        'value': Decimal('118')}])

    @with_transaction()
    def test_index_cap_rule_apply(self):
        "Cap rule: threshold in full, half of the excess, per 12 months"
        Rule = Pool().get('real_estate.index_cap_rule')
        rule = Rule(threshold_percent=Decimal(3), excess_share_percent=Decimal(50))
        jan25, jan26, jul26 = (datetime.date(2025, 1, 1),
            datetime.date(2026, 1, 1), datetime.date(2026, 7, 1))

        # X15: +5 % in 12 months -> 3 % + 2 % x 50 % = 4 %
        values = {jan25: Decimal('100.0'), jan26: Decimal('105.0')}
        self.assertEqual(
            round(rule.apply(values.get, jan25, jan26), 4), Decimal('4'))
        # below the threshold: counted in full
        values = {jan25: Decimal('100.0'), jan26: Decimal('102.0')}
        self.assertEqual(
            round(rule.apply(values.get, jan25, jan26), 4), Decimal('2'))
        # decrease: no cap
        values = {jan25: Decimal('100.0'), jan26: Decimal('98.0')}
        self.assertEqual(
            round(rule.apply(values.get, jan25, jan26), 4), Decimal('-2'))
        # 18 months: 12-month section +5 % -> 4 %, 6-month rest +2 % with
        # threshold 1.5 % -> 1.75 %; compounded 1.04 x 1.0175
        values = {jan25: Decimal('100.0'), jan26: Decimal('105.0'),
            jul26: Decimal('107.1')}
        self.assertEqual(
            round(rule.apply(values.get, jan25, jul26), 4), Decimal('5.82'))

    def test_tight_market_validity(self):
        "Tight housing market only within the regulation's validity"
        from trytond.modules.real_estate.base_object import BaseObject

        prop = _StubRecord(tight_market=True,
            tight_market_valid_from=datetime.date(2025, 1, 1),
            tight_market_valid_to=datetime.date(2029, 12, 31))
        self.assertFalse(BaseObject.is_tight_market(
                prop, datetime.date(2024, 12, 31)))
        self.assertTrue(BaseObject.is_tight_market(
                prop, datetime.date(2026, 10, 15)))
        self.assertFalse(BaseObject.is_tight_market(
                prop, datetime.date(2030, 1, 1)))
        prop.tight_market = False
        self.assertFalse(BaseObject.is_tight_market(
                prop, datetime.date(2026, 10, 15)))

    @with_transaction()
    def test_index_adjustment_calculation(self):
        "Index rent: change, new amount, effective date (X04, X08)"
        RentAdjustment = Pool().get('real_estate.contract.rent_adjustment')
        jan25, aug26 = datetime.date(2025, 1, 1), datetime.date(2026, 8, 1)
        agreement = _stub_index_agreement(RentAdjustment,
            {jan25: Decimal('117.0'), aug26: Decimal('122.1')})

        values, findings, flags = agreement.compute_index_adjustment(
            datetime.date(2026, 8, 20), receipt_date=datetime.date(2026, 10, 15))
        self.assertEqual(values['index_month_new'], aug26)
        self.assertEqual(values['index_change_percent'], Decimal('4.36'))
        self.assertEqual(values['planned_amount'], Decimal('834.87'))
        self.assertEqual(values['direction'], 'increase')
        # X08: receipt 15.10. -> from 01.12.
        self.assertEqual(
            values['planned_valid_from'], datetime.date(2026, 12, 1))
        self.assertEqual(findings, [])
        self.assertTrue(flags['threshold_reached'])
        # Receipt at the end/start of a month
        for received, expected in [
                (datetime.date(2026, 10, 31), datetime.date(2026, 12, 1)),
                (datetime.date(2026, 11, 1), datetime.date(2027, 1, 1))]:
            self.assertEqual(agreement.planned_valid_from(
                    aug26, receipt_date=received), expected)
        # Preview before the receipt: declaration date + 3 receipt days
        self.assertEqual(agreement.planned_valid_from(
                aug26, declaration_date=datetime.date(2026, 10, 29)),
            datetime.date(2027, 1, 1))

    @with_transaction()
    def test_index_adjustment_checks(self):
        "Index rent: threshold, lock period, decrease, rounding (X05-X07)"
        RentAdjustment = Pool().get('real_estate.contract.rent_adjustment')
        jan25, aug26 = datetime.date(2025, 1, 1), datetime.date(2026, 8, 1)
        values = {jan25: Decimal('117.0'), aug26: Decimal('122.1')}
        receipt = datetime.date(2026, 10, 15)

        def codes(agreement):
            _, findings, flags = agreement.compute_index_adjustment(
                aug26, receipt_date=receipt)
            return {c: lv for c, lv, _ in findings}, flags

        # X06: threshold 5 % not reached by 4.36 %
        found, flags = codes(_stub_index_agreement(RentAdjustment, values,
                threshold_type='percent', threshold_value=Decimal(5)))
        self.assertFalse(flags['threshold_reached'])
        self.assertEqual(found['S01'], 'error')
        # X07: threshold 3 points reached by 5.1 points
        found, flags = codes(_stub_index_agreement(RentAdjustment, values,
                threshold_type='points', threshold_value=Decimal(3)))
        self.assertTrue(flags['threshold_reached'])
        # X05: lock period - error for residential, warning for commercial
        found, _ = codes(_stub_index_agreement(RentAdjustment, values,
                next_possible_date=datetime.date(2027, 1, 1)))
        self.assertEqual(found['I04'], 'error')
        found, _ = codes(_stub_index_agreement(RentAdjustment, values,
                residential=False,
                next_possible_date=datetime.date(2027, 1, 1)))
        self.assertEqual(found['I04'], 'warning')
        # X13: decrease
        found, flags = codes(_stub_index_agreement(RentAdjustment,
                {jan25: Decimal('122.1'), aug26: Decimal('117.0')}))
        self.assertTrue(flags['decrease'])
        self.assertEqual(found['I13'], 'warning')
        # X21: amount per m² - the new amount is decisive, the unit price
        # (4 digits) only warns when quantity x unit price differs
        agreement = _stub_index_agreement(RentAdjustment, values,
            quantity=Decimal('72.35'), unit_price=Decimal('11.06'))
        result, findings, _ = agreement.compute_index_adjustment(
            aug26, receipt_date=receipt)
        self.assertEqual(result['planned_amount'], Decimal('835.07'))
        self.assertEqual(result['planned_unit_price'], Decimal('11.5421'))
        self.assertNotIn('I08', {c for c, _, _ in findings})
        agreement = _stub_index_agreement(RentAdjustment, values,
            quantity=Decimal('997.37'), unit_price=Decimal('0.80'))
        result, findings, _ = agreement.compute_index_adjustment(
            aug26, receipt_date=receipt)
        self.assertEqual(result['planned_amount'], Decimal('832.68'))
        self.assertIn('I08', {c for c, _, _ in findings})
        # I05: no value for the new month
        found, _ = codes(_stub_index_agreement(RentAdjustment,
                {jan25: Decimal('117.0')}))
        self.assertEqual(found['I05'], 'error')

    @with_transaction()
    def test_index_adjustment_contract_month(self):
        "Index rent, commercial: effective from index month + offset (X18)"
        RentAdjustment = Pool().get('real_estate.contract.rent_adjustment')
        agreement = _stub_index_agreement(RentAdjustment, {},
            residential=False, effective_rule='contract_month',
            effective_offset_months=1)
        self.assertEqual(agreement.planned_valid_from(
                datetime.date(2026, 8, 1)), datetime.date(2026, 9, 1))

    @with_transaction()
    def test_index_rent_declaration_deadline(self):
        "Follow-up: latest declaration date for the next possible date"
        RentAdjustment = Pool().get('real_estate.contract.rent_adjustment')
        agreement = _stub_index_agreement(RentAdjustment, {},
            next_possible_date=datetime.date(2026, 1, 1))
        # receipt by 30.11.2025 (-> 01.01.2026) minus 3 receipt days
        self.assertEqual(agreement._declaration_deadline(),
            datetime.date(2025, 11, 27))
        self.assertEqual(agreement.planned_valid_from(
                datetime.date(2025, 9, 1),
                declaration_date=agreement._declaration_deadline()),
            datetime.date(2026, 1, 1))
        # next possible date in the middle of a month: one month later
        agreement.next_possible_date = datetime.date(2026, 1, 15)
        self.assertEqual(agreement._declaration_deadline(),
            datetime.date(2025, 12, 28))
        # commercial contract month rule: no deadline
        agreement.effective_rule = 'contract_month'
        self.assertIsNone(agreement._declaration_deadline())

    def test_index_adjustment_letter_template(self):
        "Declaration template renders all mandatory contents (spec 6.1)"
        import io
        import os
        import re
        import zipfile

        from relatorio.templates.opendocument import Template

        address = _StubRecord(street_single_line='Musterstraße 1',
            postal_code='14163', city='Berlin')
        contract = _StubRecord(contract_number='1-20-191',
            company=_StubRecord(party=_StubRecord(name='Immo GmbH',
                    addresses=[address])),
            property=_StubRecord(address=address))
        record = _StubRecord(id=1, contract=contract, state='declared',
            direction='increase', cap_rule=None, index_base_year=2020,
            rent_adjustment=_StubRecord(agreement_date=None,
                price_index=_StubRecord(name='VPI')),
            term_old=_StubRecord(reference_item=None),
            index_month_old=datetime.date(2025, 1, 1),
            index_value_old=Decimal('117.0'),
            index_month_new=datetime.date(2026, 8, 1),
            index_value_new=Decimal('122.1'),
            index_change_percent=Decimal('4.36'),
            applied_change_percent=Decimal('4.36'),
            amount_old=Decimal('800.00'), planned_amount=Decimal('834.87'),
            difference_amount=Decimal('34.87'),
            planned_valid_from=datetime.date(2026, 12, 1),
            declaration_date=datetime.date(2026, 10, 2))
        tenant = _StubRecord(full_name='Rudi Völler', name='Rudi Völler')
        path = os.path.join(os.path.dirname(__file__), '..', 'report',
            'index_adjustment_letter_de.odt')
        data = Template(source=None, filepath=path).generate(
            records=[record], record=record, datetime=datetime,
            format_value=str, format_percent=str, format_index=str,
            marks={1: 'Zweitschrift'},
            tenants={1: [(tenant, address)]}).render().getvalue()
        with zipfile.ZipFile(io.BytesIO(data)) as odt:
            content = odt.read('content.xml').decode()
        text = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', content))
        for expected in ['Zweitschrift', 'Rudi Völler', 'Mieterhöhung',
                '117.0', '122.1', '4.36', '800.00', '834.87', '34.87',
                '2026-12-01']:
            self.assertIn(expected, text)

    def test_genesis_ffcsv_parsing(self):
        "GENESIS ffcsv of 61111-0002: only index rows, base year 2020"
        import os

        from trytond.modules.real_estate.price_index import (
            parse_genesis_ffcsv, parse_index_csv)

        path = os.path.join(os.path.dirname(__file__),
            'genesis_61111-0002_ffcsv.csv')
        content = open(path, encoding='utf-8-sig').read()
        values, base_year, ignored, errors = parse_genesis_ffcsv(content)
        self.assertEqual(base_year, 2020)
        self.assertEqual(errors, [])
        self.assertEqual(len(values), 80)
        self.assertEqual(ignored, 152)
        self.assertEqual(values[datetime.date(2020, 1, 1)], Decimal('99.8'))
        self.assertEqual(values[datetime.date(2025, 1, 1)], Decimal('120.3'))
        self.assertEqual(values[datetime.date(2026, 8, 1)], Decimal('125.8'))
        # The CSV import wizard detects the same file, checks the base year
        values, _, errors = parse_index_csv(content, base_year=2020)
        self.assertEqual((len(values), errors), (80, []))
        _, _, errors = parse_index_csv(content, base_year=2025)
        self.assertTrue(errors)

    @with_transaction()
    def test_genesis_fetch_values(self):
        "GENESIS import with a replaced web service call"
        import io
        import os
        import zipfile

        from trytond.modules.real_estate.price_index import GenesisError

        pool = Pool()
        Index = pool.get('real_estate.price_index')
        path = os.path.join(os.path.dirname(__file__),
            'genesis_61111-0002_ffcsv.csv')
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as zip_:
            zip_.write(path, '61111-0002_de_flat.csv')
        requests = []

        def fake_request(path, data):
            requests.append((path, data))
            return archive.getvalue()

        index, = Index.create([{'code': 'VPI-T', 'name': 'VPI',
                    'base_year': 2020, 'source': 'destatis_genesis',
                    'genesis_table': '61111-0002'}])
        original = Index._genesis_request
        Index._genesis_request = classmethod(
            lambda cls, path, data: fake_request(path, data))
        try:
            Index.fetch_values([index])
            index = Index(index.id)
            self.assertEqual(index.last_value_month, datetime.date(2026, 8, 1))
            self.assertEqual(len(index.values), 80)
            self.assertEqual(requests[0][1]['startyear'], 2020)
            # Next run: from the year before the last value, unchanged
            Index.fetch_values([index])
            self.assertEqual(requests[1][1]['startyear'], 2025)
            self.assertIn('80', Index(index.id).last_import_message)
            # Base year of the file differs: nothing imported, message
            index.base_year = 2025
            index.save()
            Index.fetch_values([index])
            self.assertIn('2020', Index(index.id).last_import_message)
            self.assertEqual(len([v for v in Index(index.id).values
                        if v.base_year == 2025]), 0)

            # Web service error: message, no exception
            def failing(cls, path, data):
                raise GenesisError('98 Tabelle zu gross')
            Index._genesis_request = classmethod(failing)
            Index.fetch_values([index])
            self.assertEqual(
                Index(index.id).last_import_message, '98 Tabelle zu gross')
        finally:
            Index._genesis_request = original

    @with_transaction()
    def test_task_basics(self):
        "Follow-up: defaults, idempotent hooks, recurrence, cancel, mine"
        from trytond.modules.company.tests import create_company, set_company
        from trytond.transaction import Transaction

        pool = Pool()
        Task = pool.get('real_estate.task')
        Type = pool.get('real_estate.task.type')
        Index = pool.get('real_estate.price_index')
        ModelData = pool.get('ir.model.data')
        User = pool.get('res.user')
        admin_group = ModelData.get_id('real_estate', 'group_real_estate_admin')

        company = create_company()
        with set_company(company):
            index, = Index.create([{'code': 'T', 'name': 'T',
                        'base_year': 2020}])
            type_, = Type.search([('code', '=', 'manual')])
            Type.write([type_], {'remind_days': 3,
                    'responsible_group': admin_group})

            # Hook API: idempotent, responsibility and reminder from type
            due = datetime.date(2026, 3, 31)
            first = Task.create_for(index, 'manual', due)
            second = Task.create_for(index, 'manual', due)
            self.assertEqual(first, second)
            self.assertEqual(first.responsible_group.id, admin_group)
            self.assertEqual(first.remind_date, datetime.date(2026, 3, 28))
            self.assertEqual(first.company, company)

            # Mine: via the group of the user
            user = User(Transaction().user)
            self.assertEqual(admin_group in User.get_groups(),
                first.is_mine)
            self.assertEqual(
                bool(Task.search([('is_mine', '=', True)])),
                admin_group in User.get_groups())

            # close_for: done (W06-like hook)
            Task.close_for(index, 'manual', result='ok')
            first = Task(first.id)
            self.assertEqual(first.state, 'done')
            self.assertEqual(first.result, 'ok')

            # W02: recurrence creates the next follow-up
            recurring, = Task.create([{'name': 'Jährlich',
                        'task_type': type_.id, 'resource': str(index),
                        'due_date': due, 'recurrence_months': 12}])
            Task.done([recurring])
            following, = Task.search([('previous', '=', recurring.id)])
            self.assertEqual(following.due_date, datetime.date(2027, 3, 31))
            self.assertEqual(following.remind_date, datetime.date(2027, 3, 28))
            self.assertEqual(following.state, 'open')

            # Cancel needs a reason
            with self.assertRaises(ValidationError):
                Task.cancel([following])
            Task.cancel_for(index, 'manual')
            self.assertEqual(Task(following.id).state, 'cancelled')

    @with_transaction()
    def test_task_role_responsible(self):
        "Responsibility by party role and creator on manual entry"
        from trytond.modules.company.tests import create_company, set_company
        from trytond.transaction import Transaction

        pool = Pool()
        Task = pool.get('real_estate.task')
        Type = pool.get('real_estate.task.type')
        BaseObject = pool.get('real_estate.base_object')
        Role = pool.get('real_estate.object_party.role')
        ObjectParty = pool.get('real_estate.object_party')
        Party = pool.get('party.party')
        Employee = pool.get('company.employee')
        User = pool.get('res.user')
        ModelData = pool.get('ir.model.data')
        group = ModelData.get_id('real_estate', 'group_real_estate_object')

        company = create_company()
        with set_company(company):
            prop, = BaseObject.create([{'name': 'P', 'type': 'property',
                        'sequence': 1,
                        'company': company.id,
                        'start_date': datetime.date(2025, 1, 1)}])
            role, = Role.create([{'name': 'Admin', 'types': ['property']}])
            party, = Party.create([{'name': 'Verwalter'}])
            employee, = Employee.create([{'party': party.id,
                        'company': company.id}])
            verwalter, = User.create([{'name': 'V', 'login': 'verwalter',
                        'employees': [('add', [employee.id])]}])
            creator = User(Transaction().user)
            type_, = Type.search([('code', '=', 'manual')])
            Type.write([type_], {'responsible_role': role.id,
                    'responsible_group': group, 'responsible_user': None})
            due = datetime.date(2026, 3, 31)

            def manual():
                return Task._default_responsible(Type(type_.id), prop, due,
                    company, manual=True)

            # Without assignment of the role, creator flag off: no user
            user, grp, prt = manual()
            self.assertEqual((user, grp.id, prt), (None, group, None))
            # creator flag on: the creator (manual entry only)
            Type.write([type_], {'creator_responsible': True})
            user, grp, prt = manual()
            self.assertEqual(user, creator)
            self.assertIsNone(Task._default_responsible(Type(type_.id),
                    prop, due, company, manual=False)[0])

            # Assignment valid on the due date: the user of the party
            ObjectParty.create([{'base_object': prop.id, 'party': party.id,
                        'role': role.id,
                        'valid_from': datetime.date(2025, 1, 1)}])
            user, grp, prt = manual()
            self.assertEqual((user, grp.id, prt), (verwalter, group, party))
            # Not yet valid on the due date
            self.assertIsNone(Task._role_responsible(role, prop,
                    datetime.date(2024, 12, 31), company)[0])

            # create: role user, party stored, group of the type kept
            task, = Task.create([{'name': 'T', 'task_type': type_.id,
                        'resource': str(prop), 'due_date': due}])
            self.assertEqual(task.responsible_user, verwalter)
            self.assertEqual(task.responsible_party, party)
            self.assertEqual(task.responsible_group.id, group)

    def test_inspection_next_due_date(self):
        "Inspection due dates: fixed rhythm, from execution, month (spec 5)"
        from trytond.modules.real_estate.inspection import next_due_date
        d = datetime.date
        # Example of the spec: due 15.04.2026, done 28.04.2026, yearly
        self.assertEqual(next_due_date(d(2026, 4, 15), d(2026, 4, 28), 1,
                'year', 'fixed'), d(2027, 4, 15))
        self.assertEqual(next_due_date(d(2026, 4, 15), d(2026, 4, 28), 1,
                'year', 'done'), d(2027, 4, 28))
        # Fixed rhythm repeated until after a late execution
        self.assertEqual(next_due_date(d(2025, 1, 31), d(2025, 5, 2), 1,
                'month', 'fixed'), d(2025, 5, 28))
        # Preferred month April: first of April of the computed year
        self.assertEqual(next_due_date(d(2026, 4, 15), d(2026, 4, 28), 1,
                'year', 'fixed', '4'), d(2027, 4, 1))
        # Preferred month not after the execution: following year
        self.assertEqual(next_due_date(None, d(2026, 11, 20), 2, 'week',
                'done', '11'), d(2027, 11, 1))
        self.assertIsNone(next_due_date(None, d(2026, 1, 1), 0, 'year',
                'done'))

    @with_transaction()
    def test_inspection_plan(self):
        "Inspection plan: defaults from the type, building, uniqueness"
        from trytond.modules.company.tests import create_company, set_company

        pool = Pool()
        BaseObject = pool.get('real_estate.base_object')
        Type = pool.get('real_estate.inspection.type')
        Plan = pool.get('real_estate.inspection.plan')

        company = create_company()
        with set_company(company):
            prop, = BaseObject.create([{'name': 'P', 'type': 'property',
                        'sequence': 1, 'company': company.id,
                        'start_date': datetime.date(2025, 1, 1)}])
            building, = BaseObject.create([{'name': 'B', 'type': 'building',
                        'sequence': 1, 'company': company.id,
                        'parent': prop.id,
                        'start_date': datetime.date(2025, 1, 1)}])
            type_, = Type.create([{'name': 'Walk', 'code': 'walk',
                        'scope': 'building', 'preferred_month': '4'}])

            plan = Plan(company=company, type=type_, property=prop)
            plan.next_due_date = None
            plan.on_change_type()
            self.assertEqual((plan.interval, plan.interval_unit,
                    plan.preferred_month), (1, 'year', '4'))
            self.assertEqual(plan.next_due_date.month, 4)
            self.assertEqual(plan.next_due_date.day, 1)
            plan.building = building
            plan.save()
            self.assertEqual(plan.compute_next_due(
                    datetime.date(plan.next_due_date.year, 4, 20)),
                datetime.date(plan.next_due_date.year + 1, 4, 1))
            self.assertEqual(
                [p.id for p in building.building_inspection_plans],
                [plan.id])
            self.assertEqual(
                [p.id for p in prop.property_inspection_plans], [plan.id])
            # The property is taken over from the building
            prop2, = BaseObject.create([{'name': 'P2', 'type': 'property',
                        'sequence': 2, 'company': company.id,
                        'start_date': datetime.date(2025, 1, 1)}])
            Plan.write([plan], {'property': prop2.id,
                    'building': building.id})
            self.assertEqual(Plan(plan.id).property, prop)
            new = Plan(building=building)
            new.on_change_building()
            self.assertEqual(new.property, prop)
            # One active plan per type and object
            with self.assertRaises(ValidationError):
                Plan.copy([plan])
            # Scope building: building required
            with self.assertRaises(ValidationError):
                Plan.create([{'company': company.id, 'type': type_.id,
                            'property': prop.id, 'interval': 1,
                            'interval_unit': 'year',
                            'interval_basis': 'fixed',
                            'next_due_date': datetime.date(2027, 4, 1)}])

    @with_transaction()
    def test_inspection_flow(self):
        "Inspection: lines, results, validation, done, plan, approval"
        from trytond.modules.company.tests import create_company, set_company
        from trytond.model.exceptions import AccessError
        from trytond.transaction import Transaction

        pool = Pool()
        BaseObject = pool.get('real_estate.base_object')
        Kind = pool.get('real_estate.equipment.kind')
        Measurement = pool.get('real_estate.measurement')
        Checklist = pool.get('real_estate.inspection.checklist')
        Type = pool.get('real_estate.inspection.type')
        Plan = pool.get('real_estate.inspection.plan')
        Inspection = pool.get('real_estate.inspection')
        Line = pool.get('real_estate.inspection.line')
        Result = pool.get('real_estate.inspection.result')
        ModelData = pool.get('ir.model.data')
        User = pool.get('res.user')
        start = datetime.date(2025, 1, 1)

        company = create_company()
        with set_company(company):
            counter = iter(range(1, 100))

            def obj(name, type_, parent=None, **kw):
                record, = BaseObject.create([dict({'name': name,
                                'type': type_, 'sequence': next(counter),
                                'company': company.id, 'start_date': start,
                                'parent': parent.id if parent else None},
                            **kw)])
                return record
            apartment = ModelData.get_id('real_estate', 'use_class_apartment')
            prop = obj('P', 'property')
            building = obj('B', 'building', prop)
            unit1 = obj('U1', 'object', building,
                type_of_use='residential', use_class=apartment)
            unit2 = obj('U2', 'object', building,
                type_of_use='residential', use_class=apartment)
            obj('U3', 'object', building,
                type_of_use='residential', use_class=apartment)
            smoke, = Kind.search([('code', '=', 'smoke_detector')])
            e_type = BaseObject.fields_get(['e_type'])['e_type'][
                'selection'][0][0]
            det1 = obj('RWM 1', 'equipment', unit1,
                equipment_kind=smoke.id, e_type=e_type)
            obj('RWM 2', 'equipment', unit2, equipment_kind=smoke.id,
                e_type=e_type)
            Measurement.create([{'base_object': det1.id, 'valid_from': start,
                        'value': 3, 'm_type': ModelData.get_id('real_estate',
                            'measurement_re_number_of_items_type')}])
            header, line_list = Checklist.create([
                    {'name': 'H', 'items': [('create', [{
                                        'question': 'Fluchtwege frei',
                                        'section': 'Treppenhaus'}])]},
                    {'name': 'L', 'items': [('create', [{
                                        'question': 'Funktion',
                                        'create_defect_on_nok': True,
                                        'default_severity': 'major'}])]},
                    ])
            group = sorted(User.get_groups())[0]
            Template = pool.get('real_estate.process.template')
            TaskType = pool.get('real_estate.task.type')
            step_type, = TaskType.search([('code', '=', 'process_step')])
            template, = Template.create([{'name': 'RWM-Prozess',
                        'code': 'rwm', 'model': 'real_estate.inspection',
                        'anchor_field': 'planned_date',
                        'steps': [('create', [{'name': 'Aushang',
                                        'sequence': 10,
                                        'task_type': step_type.id,
                                        'due_base': 'anchor',
                                        'offset_days': -14,
                                        'action': pool.get(
                                            'ir.action.wizard')(
                                            ModelData.get_id('real_estate',
                                                'wizard_inspection_notice')
                                            ).action.id,
                                        'completion': 'action'}, {
                                        'name': 'Prüfung',
                                        'sequence': 20,
                                        'task_type': step_type.id,
                                        'due_base': 'anchor',
                                        'offset_days': 0,
                                        'completion': 'condition',
                                        'done_method': 'inspection_done'}, {
                                        'name': 'Anschreiben',
                                        'sequence': 30,
                                        'task_type': step_type.id,
                                        'due_base': 'anchor',
                                        'offset_days': 7,
                                        'completion': 'manual',
                                        'create_condition': 'method',
                                        'create_method':
                                            'inspection_no_access'}])]}])
            type_, = Type.create([{'name': 'RWM', 'scope': 'building',
                        'process_template': template.id,
                        'line_granularity': 'unit',
                        'equipment_kind': smoke.id,
                        'requires_approval': True,
                        'approval_group': group,
                        'header_checklist': header.id,
                        'line_checklist': line_list.id,
                        'notice_days': 0}])
            plan, = Plan.create([{'company': company.id, 'type': type_.id,
                        'property': prop.id, 'building': building.id,
                        'interval': 1, 'interval_unit': 'year',
                        'interval_basis': 'fixed',
                        'next_due_date': datetime.date(2026, 4, 15)}])

            # Draft: one line per unit with a smoke detector, snapshot
            inspection, = Inspection.create_from_plans([plan])
            self.assertEqual(Inspection.create_from_plans([plan]), [])
            self.assertTrue(inspection.number)
            self.assertEqual(inspection.state, 'draft')
            self.assertEqual(sorted(l.base_object.name
                    for l in inspection.lines), ['U1', 'U2'])
            line1, = [l for l in inspection.lines if l.base_object == unit1]
            line2, = [l for l in inspection.lines if l.base_object == unit2]
            self.assertEqual(line1.qty_expected, 3)
            self.assertEqual(len(inspection.header_results), 1)
            self.assertEqual(len(line1.results), 1)
            self.assertEqual(line1.results[0].inspection, inspection)

            # Rebuild the lines: a new smoke detector in unit 3
            unit3, = BaseObject.search([('name', '=', 'U3')])
            obj('RWM 3', 'equipment', unit3, equipment_kind=smoke.id,
                e_type=e_type)
            Inspection.rebuild_lines([inspection])
            inspection = Inspection(inspection.id)
            self.assertEqual(sorted(l.base_object.name
                    for l in inspection.lines), ['U1', 'U2', 'U3'])
            self.assertTrue(all(r.inspection == inspection
                    for l in inspection.lines for r in l.results))
            line1, = [l for l in inspection.lines if l.base_object == unit1]
            line2, = [l for l in inspection.lines if l.base_object == unit2]
            self.assertEqual(line1.qty_expected, 3)

            # Schedule needs the planned date
            with self.assertRaises(ValidationError):
                Inspection.schedule([inspection])
            Inspection.write([inspection],
                {'planned_date': datetime.date(2026, 4, 15)})
            # No entries in a draft (client write)
            with self.assertRaises(AccessError):
                Result.check_modification('write', list(line2.results),
                    values={'value_ok': 'nok'}, external=True)
            # an answer 'not OK' stored in the draft before (e.g. older
            # data) gets its defect when scheduling
            Defect = pool.get('real_estate.inspection.defect')
            Result.write(list(line2.results), {'value_ok': 'nok'})
            self.assertFalse(Defect.search([('line', '=', line2.id)]))
            Inspection.schedule([inspection])
            early, = Defect.search([('line', '=', line2.id)])
            Result.write(list(Line(line2.id).results), {'value_ok': None})
            self.assertEqual(Defect(early.id).state, 'cancelled')
            process = Inspection(inspection.id).process
            self.assertEqual(process.anchor_date, datetime.date(2026, 4, 15))
            # the conditional step is planned (not due) yet
            self.assertEqual(sorted(t.due_date for t in process.tasks
                    if t.state == 'open'),
                [datetime.date(2026, 4, 1), datetime.date(2026, 4, 15)])
            planned, = [t for t in process.tasks if t.state == 'planned']
            self.assertEqual(planned.template_step.name, 'Anschreiben')
            self.assertEqual(process.property, prop)
            # The workflow tab shows the running process and its steps
            shown = Inspection(inspection.id)
            self.assertEqual(shown.process_state, 'running')
            self.assertEqual(shown.process_progress, process.progress)
            self.assertEqual(len(shown.process_tasks), 3)
            # The process of an inspection is only cancelled by it
            Process = pool.get('real_estate.process')
            with self.assertRaises(ValidationError):
                Process.cancel([process])
            # Tasks show and sort by the number of their process step
            Task = pool.get('real_estate.task')
            tasks = Task.search([('process', '=', process.id)],
                order=[('step_number', 'DESC')])
            self.assertEqual([t.step_number for t in tasks], [30, 20, 10])
            self.assertEqual(tasks[1].template_step.name, 'Prüfung')
            # A cancelled process can be reactivated: its tasks come back
            with Transaction().set_context(_inspection_process_cancel=True):
                Process.cancel([process])
                self.assertFalse([t for t in Process(process.id).tasks
                        if t.state == 'open'])
                Process.reactivate([process])
            process = Process(process.id)
            self.assertEqual(process.state, 'running')
            self.assertEqual(len([t for t in process.tasks
                        if t.state == 'open']), 2)
            # The first result starts the inspection
            Result.write(list(inspection.header_results), {'value_ok': 'ok'})
            inspection = Inspection(inspection.id)
            self.assertEqual(inspection.state, 'in_progress')

            # Open items of a line set to OK, quantities and date filled
            Line.all_ok([Line(line1.id)])
            line1 = Line(line1.id)
            self.assertEqual([r.value_ok for r in line1.results], ['ok'])
            self.assertEqual((line1.qty_checked, line1.qty_ok), (3, 3))
            self.assertTrue(line1.visit_date)
            # Mandatory answers missing
            with self.assertRaises(ValidationError):
                Inspection.done([inspection])
            Result.write(list(line1.results), {'value_ok': 'nok'})
            # A not OK answer creates a defect with deadline and task
            defect, = Defect.search([('inspection', '=', inspection.id),
                    ('line', '=', line1.id)])
            self.assertEqual(defect.severity, 'major')
            self.assertEqual(defect.base_object, unit1)
            self.assertEqual(defect.deadline,
                defect.detected_date + datetime.timedelta(days=14))
            self.assertEqual(defect.follow_up_task.state, 'open')
            self.assertEqual(defect.plan, plan)
            # withdrawn and set again: cancelled, a new one
            Result.write(list(line1.results), {'value_ok': 'ok'})
            self.assertEqual(Defect(defect.id).state, 'cancelled')
            self.assertEqual(Defect(defect.id).follow_up_task.state,
                'cancelled')
            Result.write(list(line1.results), {'value_ok': 'nok'})
            defect, = Defect.search([('inspection', '=', inspection.id),
                    ('line', '=', line1.id), ('state', '=', 'open')])
            Line.write([line2], {'access_status': 'no_access'})
            # Units without access: the conditional step is created
            process = Inspection(inspection.id).process
            self.assertIn(datetime.date(2026, 4, 22),
                [t.due_date for t in process.tasks])
            # Tenant notice and letters are archived as attachments
            Attachment = pool.get('ir.attachment')
            for wizard_name in ['real_estate.inspection.notice.create',
                    'real_estate.inspection.access_letter.create']:
                Wizard = pool.get(wizard_name, type='wizard')
                session_id, _, _ = Wizard.create()
                with Transaction().set_context(
                        active_model='real_estate.inspection',
                        active_id=inspection.id,
                        active_ids=[inspection.id]):
                    Wizard.execute(session_id, {}, 'archive')
                Wizard.delete(session_id)
            inspection = Inspection(inspection.id)
            # the notice created on the inspection completes its step
            aushang, = [t for t in inspection.process.tasks
                if t.template_step.name == 'Aushang']
            self.assertEqual(aushang.state, 'done')
            self.assertTrue(inspection.notice_date)
            self.assertTrue(inspection.notice)
            self.assertTrue(Line(line2.id).letter_date)
            self.assertEqual(len(Attachment.search(
                        [('resource', '=', str(inspection))])), 2)
            # Visit conditions of the attempts
            process = Inspection(inspection.id).process
            self.assertFalse(process._step_done_inspection_attempt1_done())
            Line.write([Line(line2.id)],
                {'visit_date': datetime.date(2026, 4, 15)})
            line3, = [l for l in Inspection(inspection.id).lines
                if l.base_object == unit3]
            Line.write([line3], {'access_status': 'not_required'})
            self.assertTrue(process._step_done_inspection_attempt1_done())
            # Next attempt for the lines without access
            Inspection.next_attempt([inspection])
            self.assertFalse(process._step_done_inspection_attempt2_done())
            Line.write([Line(line2.id)],
                {'visit_date': datetime.date(2026, 5, 6)})
            self.assertTrue(process._step_done_inspection_attempt2_done())
            self.assertEqual(Line(line2.id).attempt, 2)
            self.assertEqual(Inspection(inspection.id).attempt, 2)
            # Not inspected without reason
            with self.assertRaises(ValidationError):
                Inspection.done([inspection])
            Line.write([line2], {'remarks': 'Mieter nicht angetroffen'})
            line3, = [l for l in Inspection(inspection.id).lines
                if l.base_object == unit3]
            Line.write([line3], {'access_status': 'not_required'})
            self.assertEqual(Line(line1.id).result, 'defect')
            self.assertEqual(Line(line2.id).result, 'not_inspected')
            Inspection.done([inspection])
            inspection = Inspection(inspection.id)
            self.assertEqual(inspection.state, 'done')
            # done: entries locked (reopen to change), buttons hidden
            self.assertTrue(Line(line1.id).locked)
            with self.assertRaises(AccessError):
                Result.check_modification('write', list(line1.results),
                    values={'value_ok': 'ok'}, external=True)
            self.assertEqual(inspection.overall_result, 'ok_with_defects')
            step_task, = [t for t in inspection.process.tasks
                if t.template_step.name == 'Prüfung']
            self.assertEqual(step_task.state, 'done')
            plan = Plan(plan.id)
            self.assertEqual(plan.last_done_date, inspection.done_date)
            self.assertEqual(plan.next_due_date, plan.compute_next_due(
                    inspection.done_date,
                    due_date=datetime.date(2026, 4, 15)))

            # Approval: report archived, records locked
            Inspection.approve([inspection])
            inspection = Inspection(inspection.id)
            self.assertEqual(inspection.state, 'approved')
            self.assertTrue(inspection.report)
            self.assertEqual(inspection.approved_by.id, Transaction().user)
            done_date = inspection.done_date
            # Undo: take back the approval, reopen - plan and process back
            report = inspection.report
            Inspection.unapprove([inspection])
            inspection = Inspection(inspection.id)
            self.assertEqual(inspection.state, 'done')
            self.assertIsNone(inspection.report)
            self.assertIn('(withdrawn)', Attachment(report.id).name)
            Inspection.reopen([inspection])
            inspection = Inspection(inspection.id)
            self.assertEqual(inspection.state, 'in_progress')
            plan = Plan(plan.id)
            self.assertEqual((plan.next_due_date, plan.last_done_date),
                (datetime.date(2026, 4, 15), None))
            self.assertEqual(inspection.process.state, 'running')
            step_task, = [t for t in inspection.process.tasks
                if t.template_step.name == 'Prüfung']
            self.assertEqual(step_task.state, 'open')
            # done and approved again
            Inspection.done([inspection])
            Inspection.approve([inspection])
            inspection = Inspection(inspection.id)
            self.assertEqual(inspection.state, 'approved')
            self.assertEqual(Plan(plan.id).last_done_date, done_date)
            with self.assertRaises(AccessError):
                Line.check_modification('write', [Line(line1.id)],
                    external=True)
            with self.assertRaises(AccessError):
                Inspection.check_modification('delete', [inspection])
            # Defect of an approved inspection: only its state can change
            with self.assertRaises(AccessError):
                Defect.check_modification('write', [defect],
                    values={'description': 'x'}, external=True)
            Defect.check_modification('write', [defect],
                values={'state': 'fixed'}, external=True)
            # Next inspection possible again, shows the open defect
            following, = Inspection.create_from_plans([plan])
            self.assertEqual(list(following.previous_defects), [defect])
            Defect.fix([defect])
            self.assertEqual(Defect(defect.id).follow_up_task.state, 'done')
            with Transaction().set_context(inspection=following.id):
                Defect.verify([defect])
            defect = Defect(defect.id)
            self.assertEqual((defect.state, defect.verified_in),
                ('verified', following))
            self.assertEqual(list(Inspection(following.id).previous_defects),
                [])

    @with_transaction()
    def test_sql_constraint_messages(self):
        "SQL constraints raise readable messages (message ids)"
        from trytond.modules.company.tests import create_company, set_company
        from trytond.model.exceptions import SQLConstraintError

        pool = Pool()
        BaseObject = pool.get('real_estate.base_object')
        Message = pool.get('ir.message')

        for name in ['real_estate.base_object', 'real_estate.measurement',
                'real_estate.object_party', 'real_estate.contract.type.tax',
                'real_estate.contract.term.tax']:
            for _, _, msg in pool.get(name)._sql_constraints:
                module, id_ = msg.split('.')
                self.assertIn(module, ['ir', 'real_estate'], msg)
                self.assertNotEqual(Message.gettext(module, id_, 'en'),
                    id_, msg)

        company = create_company()
        with set_company(company):
            values = {'name': 'P', 'type': 'property', 'sequence': 1,
                'company': company.id,
                'start_date': datetime.date(2025, 1, 1)}
            prop, = BaseObject.create([values])
            building = dict(values, name='B1', type='building',
                parent=prop.id)
            BaseObject.create([building])
            # The next free sequence below the parent is proposed
            b1, = BaseObject.search([('name', '=', 'B1')])
            new = BaseObject(parent=prop, type='building', sequence=None)
            self.assertEqual(new.on_change_with_sequence(), 10)
            BaseObject.write([b1], {'sequence': 17})
            self.assertEqual(new.on_change_with_sequence(), 20)
            new.type = 'land'
            self.assertEqual(new.on_change_with_sequence(), 10)
            BaseObject.write([b1], {'sequence': 1})
            with self.assertRaises(SQLConstraintError) as cm:
                BaseObject.create([dict(building, name='B2')])
            self.assertIn('sequence', str(cm.exception).lower())

    @with_transaction()
    def test_inspection_default_data(self):
        "Default inspection types 7.1 / 7.2 with checklists and processes"
        pool = Pool()
        Type = pool.get('real_estate.inspection.type')
        walk, = Type.search([('code', '=', 'walkthrough')])
        smoke, = Type.search([('code', '=', 'smoke_detector')])
        self.assertEqual((walk.scope, walk.line_granularity,
                walk.preferred_month), ('building', 'none', '4'))
        self.assertEqual(len(walk.header_checklist.items), 21)
        self.assertEqual(len(walk.process_template.steps), 4)
        self.assertEqual(smoke.line_granularity, 'unit')
        self.assertEqual(smoke.equipment_kind.code, 'smoke_detector')
        self.assertEqual(len(smoke.line_checklist.items), 6)
        steps = {s.sequence: s for s in smoke.process_template.steps}
        self.assertEqual(len(steps), 7)
        self.assertEqual(steps[20].action.get_action_value()['type'],
            'ir.action.wizard')
        self.assertEqual(steps[20].action.get_action_value()['wiz_name'],
            'real_estate.inspection.notice.create')
        self.assertEqual(steps[40].create_method, 'inspection_no_access')
        self.assertEqual(steps[20].offset_days, -14)
        self.assertEqual(smoke.process_template.anchor_field, 'planned_date')

    @with_transaction()
    def test_task_postpone(self):
        "W03: postpone - new due date, history, reminder reset"
        from trytond.modules.company.tests import create_company, set_company
        from trytond.transaction import Transaction

        pool = Pool()
        Task = pool.get('real_estate.task')
        Type = pool.get('real_estate.task.type')
        Index = pool.get('real_estate.price_index')
        Postpone = pool.get('real_estate.task.postpone', type='wizard')

        company = create_company()
        with set_company(company):
            index, = Index.create([{'code': 'T', 'name': 'T',
                        'base_year': 2020}])
            manual, = Type.search([('code', '=', 'manual')])
            Type.write([manual], {'remind_days': 2})
            task = Task.create_for(index, 'manual',
                datetime.date(2026, 3, 31))
            Task.write([task], {
                    'notified_date': datetime.date(2026, 3, 29)})
            session_id, _, _ = Postpone.create()
            with Transaction().set_context(
                    active_model='real_estate.task',
                    active_id=task.id, active_ids=[task.id]):
                Postpone.execute(session_id, {'start': {
                            'due_date': datetime.date(2026, 4, 30),
                            'reason': 'Mieter im Urlaub'}}, 'postpone')
            task = Task(task.id)
            self.assertEqual(task.due_date, datetime.date(2026, 4, 30))
            self.assertEqual(task.remind_date, datetime.date(2026, 4, 28))
            self.assertIsNone(task.notified_date)
            self.assertIn('Mieter im Urlaub', task.description)
            self.assertIn('31.03.2026', task.description)

    @with_transaction()
    def test_task_visibility(self):
        "W15: users see own and group follow-ups, administration all"
        from trytond.modules.company.tests import create_company, set_company
        from trytond.transaction import Transaction

        pool = Pool()
        Task = pool.get('real_estate.task')
        Type = pool.get('real_estate.task.type')
        Index = pool.get('real_estate.price_index')
        User = pool.get('res.user')
        ModelData = pool.get('ir.model.data')
        group = lambda name: ModelData.get_id('real_estate', name)

        company = create_company()
        with set_company(company):
            index, = Index.create([{'code': 'T', 'name': 'T',
                        'base_year': 2020}])
            Type.search([('code', '=', 'manual')])
            contract_user, billing_user, admin_user = User.create([{
                        'name': name, 'login': name,
                        'groups': [('add', [group(g)])],
                        'companies': [('add', [company.id])],
                        'company': company.id,
                        } for name, g in [
                        ('vertrag', 'group_real_estate_contract'),
                        ('abrechnung', 'group_real_estate_billing'),
                        ('verwaltung', 'group_real_estate_admin')]])
            for_contract = Task.create_for(index, 'manual',
                datetime.date(2026, 3, 31),
                group=group('group_real_estate_contract'))
            for_billing_user = Task.create_for(index, 'manual',
                datetime.date(2026, 4, 30), user=billing_user,
                origin_key='second')

            def visible(user):
                # Record rules only apply with access checks (as for
                # client calls)
                with Transaction().set_user(user.id), \
                        Transaction().set_context(company=company.id,
                            _check_access=True):
                    return set(Task.search([]))
            self.assertEqual(visible(contract_user), {for_contract})
            self.assertEqual(visible(billing_user), {for_billing_user})
            self.assertEqual(visible(admin_user),
                {for_contract, for_billing_user})

    @with_transaction()
    def test_task_type_catalog(self):
        "Follow-up types: catalog codes, reference objects, manual filter"
        from trytond.model.exceptions import DomainValidationError
        from trytond.modules.company.tests import create_company, set_company

        pool = Pool()
        Type = pool.get('real_estate.task.type')
        Task = pool.get('real_estate.task')
        Index = pool.get('real_estate.price_index')

        def codes(model):
            return {t.code or t.name for t in Type.search([
                        ('for_model', '=', model), ('manual', '=', True)])}

        own_billing, own_all = Type.create([
                {'name': 'Rauchmelder', 'custom_models': [
                        'real_estate.billing_unit']},
                {'name': 'Anrufen'}])
        self.assertTrue(own_all.all_models)
        self.assertEqual(own_all.resource_models, ())
        self.assertFalse(own_billing.all_models)

        contract = codes('real_estate.contract')
        self.assertTrue({'manual', 'contract_unsigned', 'contract_end',
                'Anrufen'} <= contract)
        self.assertFalse({'meter_reading', 'index_values', 'Rauchmelder'}
            & contract)
        billing = codes('real_estate.billing_unit')
        self.assertTrue({'manual', 'billing_deadline', 'Rauchmelder',
                'Anrufen'} <= billing)
        # automatic-only codes are never offered for manual follow-ups
        self.assertNotIn('index_values',
            codes('real_estate.price_index'))
        values, = Type.search([('code', '=', 'index_values')])
        self.assertEqual(values.resource_models,
            ('real_estate.price_index',))
        self.assertFalse(values.manual)

        company = create_company()
        with set_company(company):
            index, = Index.create([{'code': 'T', 'name': 'T',
                        'base_year': 2020}])
            meter, = Type.search([('code', '=', 'meter_reading')])
            # a type for another object is refused
            with self.assertRaises(DomainValidationError):
                Task.create([{'name': 'x', 'task_type': meter.id,
                            'resource': str(index),
                            'due_date': datetime.date(2026, 1, 1)}])
            # automatic follow-up of the price index (hook)
            self.assertTrue(Task.create_for(index, 'index_values',
                    datetime.date(2026, 1, 1)).automatic)

    @with_transaction()
    def test_task_notify(self):
        "W07-W09, W19: reminders per user/group, once a day, escalation"
        from trytond.modules.company.tests import create_company, set_company
        from trytond.transaction import Transaction

        pool = Pool()
        Task = pool.get('real_estate.task')
        Type = pool.get('real_estate.task.type')
        Index = pool.get('real_estate.price_index')
        User = pool.get('res.user')
        Group = pool.get('res.group')
        Email = pool.get('ir.email')
        transaction = Transaction()

        company = create_company()
        with set_company(company):
            index, = Index.create([{'code': 'T', 'name': 'T',
                        'base_year': 2020}])
            group, escalation = Group.create([{'name': 'Team'},
                    {'name': 'Leitung'}])
            u1, u2, u3, boss = User.create([{'name': n, 'login': n,
                        'email': mail, 'groups': [('add', [g.id])]}
                    for n, mail, g in [('u1', 'u1@example.com', group),
                        ('u2', None, group), ('u3', None, group),
                        ('boss', None, escalation)]])
            User.write([u3], {'active': False})
            type_, = Type.search([('code', '=', 'manual')])
            Type.write([type_], {'remind_days': 0, 'escalate_days': 2,
                    'escalation_group': escalation.id, 'email': True})
            today = datetime.date(2026, 10, 2)
            for_group, = Task.create([{'name': 'Gruppe',
                        'task_type': type_.id, 'resource': str(index),
                        'due_date': today, 'responsible_group': group.id}])
            for_user, = Task.create([{'name': 'Benutzer',
                        'task_type': type_.id, 'resource': str(index),
                        'due_date': today + datetime.timedelta(days=1),
                        'remind_date': today, 'responsible_user': u2.id}])

            sent = []
            original = Email.send
            Email.send = classmethod(lambda cls, **kw: sent.append(kw['to']))
            try:
                del transaction.user_notifications[:]
                self.assertEqual(Task.notify(date=today), (2, 0))
                users = sorted(int(n.user) for n in transaction.user_notifications)
                # group: 2 active members, user: 1
                self.assertEqual(users, sorted([u1.id, u2.id, u2.id]))
                # e-mail only to the member with an address (W09)
                self.assertEqual(sent, ['u1@example.com'])
                # second run on the same day: nothing (W07)
                del transaction.user_notifications[:]
                self.assertEqual(Task.notify(date=today), (0, 0))
                self.assertEqual(transaction.user_notifications, [])
                # W19: no e-mail when the user disabled it
                User.write([u1], {'task_email': False})
                Type.write([type_], {'remind_daily': True})
                sent.clear()
                self.assertEqual(Task.notify(
                        date=today + datetime.timedelta(days=1)), (2, 0))
                self.assertEqual(sent, [])
                # W08: escalation after 2 days, once
                del transaction.user_notifications[:]
                later = today + datetime.timedelta(days=3)
                self.assertEqual(Task.notify(date=later)[1], 2)
                self.assertIn(boss.id,
                    [int(n.user) for n in transaction.user_notifications])
                self.assertEqual(Task.notify(date=later)[1], 0)
                self.assertEqual(Task(for_group.id).escalated_date, later)
            finally:
                Email.send = original

    @with_transaction()
    def test_task_rule_run(self):
        "W04-W06: idempotent rule run, changed date, done condition"
        from trytond.modules.company.tests import create_company, set_company

        pool = Pool()
        Rule = pool.get('real_estate.task.rule')
        Task = pool.get('real_estate.task')
        Type = pool.get('real_estate.task.type')
        Index = pool.get('real_estate.price_index')
        Value = pool.get('real_estate.price_index.value')

        company = create_company()
        with set_company(company):
            index, = Index.create([{'code': 'T', 'name': 'T',
                        'base_year': 2020}])
            Value.create([{'index': index.id, 'base_year': 2020,
                        'month': datetime.date(2026, 8, 1),
                        'value': Decimal('125.8')}])
            type_, = Type.create([{'name': 'Index prüfen',
                        'custom_models': ['real_estate.price_index']}])
            rule, = Rule.create([{'name': 'Test',
                        'model': 'real_estate.price_index',
                        'domain': '[["code", "=", "T"]]',
                        'date_source': 'field',
                        'date_field': 'last_value_month',
                        'offset_months': 2, 'horizon_days': 30,
                        'task_type': type_.id,
                        'done_domain': '[["residential_allowed", "=", true]]',
                        }])
            today = datetime.date(2026, 9, 10)

            def tasks(state='open'):
                return Task.search([('origin', '=', str(rule)),
                        ('state', '=', state)])

            # due 01.10.2026 within 30 days: created once (W04)
            Rule.run([rule], date=today)
            Rule.run([rule], date=today)
            created, = tasks()
            self.assertEqual(created.due_date, datetime.date(2026, 10, 1))
            self.assertTrue(created.automatic)
            self.assertEqual(created.company, company)
            self.assertEqual(Rule(rule.id).last_run, today)

            # W05: new value - old task cancelled, new one for 01.11.
            Value.create([{'index': index.id, 'base_year': 2020,
                        'month': datetime.date(2026, 9, 1),
                        'value': Decimal('126.0')}])
            Rule.run([rule], date=datetime.date(2026, 10, 5))
            self.assertEqual(Task(created.id).state, 'cancelled')
            renewed, = tasks()
            self.assertEqual(renewed.due_date, datetime.date(2026, 11, 1))

            # W06: done condition met - done, no new task
            Index.write([index], {'residential_allowed': True})
            Rule.run([rule], date=datetime.date(2026, 10, 6))
            self.assertEqual(Task(renewed.id).state, 'done')
            Rule.run([rule], date=datetime.date(2026, 10, 7))
            self.assertEqual(tasks(), [])

            # a done task is not created again for the same date; a new
            # date (new value 10/2026, due 01.12.) respects the lead time
            Index.write([index], {'residential_allowed': False})
            Rule.run([rule], date=datetime.date(2026, 10, 7))
            self.assertEqual(tasks(), [])
            Value.create([{'index': index.id, 'base_year': 2020,
                        'month': datetime.date(2026, 10, 1),
                        'value': Decimal('126.2')}])
            Rule.run([rule], date=datetime.date(2026, 10, 7))
            self.assertEqual(tasks(), [])
            Rule.run([rule], date=datetime.date(2026, 11, 2))
            again, = tasks()
            self.assertEqual(again.due_date, datetime.date(2026, 12, 1))
            # record no longer matching the domain: done automatically
            Index.write([index], {'code': 'X'})
            Rule.run([rule], date=datetime.date(2026, 11, 3))
            self.assertEqual(Task(again.id).state, 'done')

    @with_transaction()
    def test_task_rule_methods(self):
        "Named date methods: index values stale, meter calibration (W17)"
        pool = Pool()
        Rule = pool.get('real_estate.task.rule')
        BaseObject = pool.get('real_estate.base_object')

        rule = Rule()
        stale = _StubRecord(__name__='real_estate.price_index',
            last_value_month=datetime.date(2026, 6, 1))
        current = _StubRecord(__name__='real_estate.price_index',
            last_value_month=datetime.date(2026, 8, 1))
        result = rule._date_index_values_stale([stale, current],
            datetime.date(2026, 10, 2))
        self.assertEqual(result, [(stale, datetime.date(2026, 8, 1))])

        # W17: last calibration 15.03.2021, 6 years -> 31.12.2027
        meter = BaseObject()
        meter.meter_calibration_date = datetime.date(2021, 3, 15)
        meter.meter_calibration_years = 6
        meter.on_change_meter_calibration_years()
        self.assertEqual(meter.meter_calibration_valid_to,
            datetime.date(2027, 12, 31))
        rule = Rule(offset_months=-3, offset_days=0)
        self.assertEqual(rule._due_date(meter.meter_calibration_valid_to),
            datetime.date(2027, 9, 30))

    @with_transaction()
    def test_process(self):
        "W11-W13, W22, W24-W27: process steps, progress, actions"
        from trytond.modules.company.tests import create_company, set_company
        from trytond.transaction import Transaction

        pool = Pool()
        Template = pool.get('real_estate.process.template')
        Process = pool.get('real_estate.process')
        Task = pool.get('real_estate.task')
        Type = pool.get('real_estate.task.type')
        Index = pool.get('real_estate.price_index')
        Value = pool.get('real_estate.price_index.value')
        ModelData = pool.get('ir.model.data')
        Execute = pool.get('real_estate.task.execute_action', type='wizard')

        company = create_company()
        with set_company(company):
            index, = Index.create([{'code': 'T', 'name': 'T',
                        'base_year': 2020}])
            Value.create([{'index': index.id, 'base_year': 2020,
                        'month': datetime.date(2026, 8, 1),
                        'value': Decimal('125.8')}])
            step_type, = Type.search([('code', '=', 'process_step')])
            action_id = ModelData.get_id('real_estate', 'act_task_mine')
            template, = Template.create([{
                        'name': 'Test', 'model': 'real_estate.price_index',
                        'anchor_field': 'last_value_month',
                        'steps': [('create', [
                                    {'sequence': 10, 'name': 'Start',
                                        'task_type': step_type.id,
                                        'due_base': 'start',
                                        'offset_days': 3,
                                        'result_required': True},
                                    {'sequence': 20, 'name': 'Anker',
                                        'task_type': step_type.id,
                                        'due_base': 'anchor',
                                        'offset_months': 1},
                                    {'sequence': 30, 'name': 'Danach',
                                        'task_type': step_type.id,
                                        'due_base': 'previous_done',
                                        'offset_days': 2},
                                    {'sequence': 40, 'name': 'Optional',
                                        'task_type': step_type.id,
                                        'due_base': 'start',
                                        'mandatory': False},
                                    {'sequence': 50, 'name': 'Bedingung',
                                        'task_type': step_type.id,
                                        'due_base': 'anchor',
                                        'completion': 'condition',
                                        'done_condition':
                                            '[["residential_allowed", "=", true]]'},
                                    {'sequence': 60, 'name': 'Aktion',
                                        'task_type': step_type.id,
                                        'due_base': 'start',
                                        'action': action_id,
                                        'completion': 'action'},
                                    {'sequence': 70, 'name': 'Bedingt',
                                        'task_type': step_type.id,
                                        'due_base': 'start',
                                        'create_condition': 'method',
                                        'create_method':
                                            'inspection_no_access'},
                                    ])],
                        }])
            start = datetime.date(2026, 10, 1)
            process = Process.start(template, index, start)
            self.assertEqual(Process.start(template, index, start), process)
            self.assertEqual(process.anchor_date, datetime.date(2026, 8, 1))
            def steps():
                return {t.template_step.name: t
                    for t in Process(process.id).tasks}
            # every step is a task; W26: the previous_done step is planned
            self.assertEqual(len(process.tasks), 7)
            self.assertEqual(steps()['Danach'].state, 'planned')
            self.assertEqual(steps()['Bedingt'].state, 'planned')
            self.assertIsNone(steps()['Danach'].due_date)
            self.assertEqual(steps()['Start'].due_date,
                datetime.date(2026, 10, 4))
            self.assertEqual(steps()['Anker'].due_date,
                datetime.date(2026, 9, 1))
            self.assertEqual(steps()['Start'].step_number, 10)
            self.assertEqual(steps()['Start'].process, process)
            # planned tasks are no open tasks
            self.assertNotIn(steps()['Danach'],
                Task.search([('state', '=', 'open')]))

            # W25: result required
            with self.assertRaises(ValidationError):
                Task.done([steps()['Start']])
            Task.write([steps()['Start']], {'result': 'versendet'})
            Task.done([steps()['Start']])

            # W11: anchor changed - open anchor tasks rescheduled
            Process.write([process], {
                    'anchor_date': datetime.date(2026, 9, 1)})
            Process.reschedule([process])
            self.assertEqual(steps()['Anker'].due_date,
                datetime.date(2026, 10, 1))
            self.assertIn('Anker', Process(process.id).history)

            # W12: previous_done step opened after the previous one
            Task.done([steps()['Anker']])
            self.assertEqual(steps()['Danach'].state, 'open')
            self.assertTrue(steps()['Danach'].due_date)

            # W24: condition met - done by 'check'
            Index.write([index], {'residential_allowed': True})
            Process.check([process])
            self.assertEqual(steps()['Bedingung'].state, 'done')

            # W22: executing the action returns it for the reference
            # record and completes the step
            session_id, _, _ = Execute.create()
            aktion = steps()['Aktion']
            with Transaction().set_context(active_model='real_estate.task',
                    active_id=aktion.id, active_ids=[aktion.id]):
                result = Execute.execute(session_id, {}, 'open_')
            action = result['actions'][0]
            self.assertEqual(action[0]['res_model'], 'real_estate.task')
            self.assertEqual(action[1]['model'], 'real_estate.price_index')
            self.assertEqual(action[1]['ids'], [index.id])
            self.assertEqual(Task(aktion.id).state, 'done')

            # W27: optional step cancelled = skipped; W13: process done
            optional = steps()['Optional']
            Task.write([optional], {'result': 'nicht nötig'})
            Task.cancel([optional])
            self.assertEqual(Process(process.id).state, 'running')
            Task.done([steps()['Danach']])
            process = Process(process.id)
            self.assertEqual(steps()['Optional'].state, 'cancelled')
            self.assertEqual(process.state, 'done')
            self.assertEqual(process.progress, '5 / 5 done')
            # A conditional step never created is cancelled as not required
            # when the process is done, and planned again on reopen
            bedingt = steps()['Bedingt']
            self.assertEqual(bedingt.state, 'cancelled')
            self.assertEqual(bedingt.result, 'Not required (process done).')
            Process.reopen([process])
            self.assertEqual(Process(process.id).state, 'running')
            self.assertEqual(steps()['Bedingt'].state, 'planned')
            self.assertEqual(steps()['Optional'].state, 'cancelled')
            # Cancelling the last open steps cancels (not completes) it
            Process.cancel([Process(process.id)])
            self.assertEqual(Process(process.id).state, 'cancelled')
            self.assertEqual(steps()['Bedingt'].state, 'cancelled')

    @with_transaction()
    def test_meter_reading_sheet(self):
        "Meter reading sheet: load, done creates readings, reset, follow-up"
        from trytond.modules.company.tests import create_company, set_company
        from trytond.exceptions import UserWarning
        from trytond.model.exceptions import AccessError
        from trytond.transaction import Transaction

        pool = Pool()
        BaseObject = pool.get('real_estate.base_object')
        Reading = pool.get('real_estate.meter_reading')
        Sheet = pool.get('real_estate.meter_reading.sheet')
        Line = pool.get('real_estate.meter_reading.sheet.line')
        ModelData = pool.get('ir.model.data')
        start = datetime.date(2025, 1, 1)

        company = create_company()
        with set_company(company):
            counter = iter(range(1, 100))

            def obj(name, type_, parent=None, **kw):
                record, = BaseObject.create([dict({'name': name,
                                'type': type_, 'sequence': next(counter),
                                'company': company.id, 'start_date': start,
                                'parent': parent.id if parent else None},
                            **kw)])
                return record
            apartment = ModelData.get_id('real_estate', 'use_class_apartment')
            prop = obj('P', 'property')
            building = obj('B', 'building', prop)
            unit = obj('U1', 'object', building,
                type_of_use='residential', use_class=apartment)
            m3 = ModelData.get_id('product', 'uom_cubic_meter')
            warm = obj('Warmwasser Zähler', 'equipment', unit,
                e_type='meters', meter_is_counter=True, meter_unit=m3)
            cold = obj('Kaltwasser Zähler', 'equipment', unit,
                e_type='meters', meter_is_counter=True, meter_unit=m3)
            Reading.create([{'company': company.id, 'base_object': m.id,
                        'meter_id': f'Z-{m.id}', 'reading_date': start,
                        'm_type': 'initial', 'value': Decimal(10)}
                    for m in [warm, cold]])

            # Filter by name: only the warm water meter, with its previous
            # reading and the unit; the property is derived
            sheet, = Sheet.create([{'base_object': building.id,
                        'reading_date': datetime.date(2025, 12, 31),
                        'name_filter': 'warm'}])
            self.assertEqual(sheet.property, prop)
            line, = sheet.lines
            self.assertEqual((line.meter, line.unit), (warm, unit))
            self.assertEqual(line.meter_id, f'Z-{warm.id}')
            self.assertEqual(line.previous_value, Decimal(10))
            self.assertEqual(line.previous_date, start)
            self.assertEqual(sheet.progress, '0 / 1')

            # Reload without filter adds the other meter, keeps the value
            Line.write([line], {'value': Decimal(25)})
            Sheet.write([sheet], {'name_filter': None})
            Sheet.load_meters([sheet])
            sheet = Sheet(sheet.id)
            self.assertEqual(len(sheet.lines), 2)
            self.assertEqual(Line(line.id).value, Decimal(25))
            self.assertEqual(Line(line.id).consumption, Decimal(15))
            self.assertEqual(sheet.progress, '1 / 2')

            # Done: a reading for the line with value only, after the
            # warning for the missing value
            with self.assertRaises(UserWarning):
                Sheet.done([sheet])
            with Transaction().set_context(_skip_warnings=True):
                Sheet.done([sheet])
            reading = Line(line.id).reading
            self.assertTrue(reading)
            self.assertTrue(Line(line.id).reading_created)
            self.assertEqual((reading.value, reading.m_type,
                    reading.reading_date, reading.meter_id),
                (Decimal(25), 'reading', datetime.date(2025, 12, 31),
                    f'Z-{warm.id}'))

            # Follow-up: one year later, previous value = this reading
            action = Sheet.follow_up([sheet])
            self.assertEqual(action['res_model'], Sheet.__name__)
            following, = Sheet.search([('id', '!=', sheet.id)])
            self.assertEqual(following.reading_date,
                datetime.date(2026, 12, 31))
            self.assertEqual(following.state, 'draft')
            warm_line, = [l for l in following.lines if l.meter == warm]
            self.assertEqual(warm_line.previous_value, Decimal(25))
            self.assertIsNone(warm_line.value)

            # Reset to draft deletes the created reading
            Sheet.draft([sheet])
            self.assertFalse(Reading.search([('id', '=', reading.id)]))
            self.assertIsNone(Line(line.id).reading)

            # An existing reading of the day is linked, not duplicated
            Line.write([line], {'value': Decimal(26)})
            existing, = Reading.create([{'company': company.id,
                        'base_object': warm.id, 'meter_id': f'Z-{warm.id}',
                        'reading_date': datetime.date(2025, 12, 31),
                        'm_type': 'reading', 'value': Decimal(24)}])
            with Transaction().set_context(_skip_warnings=True):
                Sheet.done([sheet])
            self.assertEqual(Line(line.id).reading, existing)
            self.assertFalse(Line(line.id).reading_created)
            Sheet.draft([sheet])
            self.assertTrue(Reading.search([('id', '=', existing.id)]))

            # A done sheet cannot be deleted
            with Transaction().set_context(_skip_warnings=True):
                Sheet.done([sheet])
            with self.assertRaises(AccessError):
                Sheet.delete([sheet])

    def test_meter_reading_sheet_template(self):
        "Meter reading sheet template renders the meter lines"
        import io
        import os
        import re
        import zipfile

        from relatorio.templates.opendocument import Template

        line = _StubRecord(unit=_StubRecord(rec_name='Wohnung 01'),
            tenant=_StubRecord(rec_name='Mieter 1'),
            meter=_StubRecord(rec_name='Wasser Zähler'),
            meter_id='Z-2025-0001', previous_date=datetime.date(2025, 4, 30),
            previous_value=Decimal('23.5'), value=None,
            uom=_StubRecord(symbol='m³'), remarks=None)
        record = _StubRecord(id=1, state='draft',
            company=_StubRecord(party=_StubRecord(name='Immo GmbH')),
            base_object=_StubRecord(rec_name='Haus 1'),
            property=_StubRecord(rec_name='Musterstraße 1-4'),
            reading_date=datetime.date(2025, 12, 31), reader=None,
            equipment_kind=None, name_filter='Wasser', notes=None,
            lines=[line])
        path = os.path.join(os.path.dirname(__file__), '..', 'report',
            'meter_reading_sheet_de.odt')
        data = Template(source=None, filepath=path).generate(
            records=[record], format_value=str).render().getvalue()
        with zipfile.ZipFile(io.BytesIO(data)) as odt:
            content = odt.read('content.xml').decode()
        text = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', content))
        for expected in ['ENTWURF', 'Zählerableseliste', 'Haus 1',
                'Musterstraße 1-4', '2025-12-31', 'Wasser', 'Wohnung 01',
                'Mieter 1', 'Wasser Zähler', 'Z-2025-0001', '23.5',
                'm³', 'Unterschrift']:
            self.assertIn(expected, text)

    def test_rent_survey_compute(self):
        "Rent survey: table and regression method (M01-M03, M10, M11)"
        from trytond.modules.real_estate.rent_survey import compute_rent
        D = Decimal

        def table(votes, extra=()):
            groups = [('majority', [('plus' if v > 0 else 'minus', 'vote',
                            None)] if v else []) for v in votes]
            groups.append(('additive', list(extra)))
            return compute_rent('table', D('5.90'), D('7.08'), D('9.25'),
                groups)
        # M01: net +4 -> 7.08 + 4 x 20 % x (9.25 - 7.08) = 8.82
        result = table([1, 0, 1, 1, 1])
        self.assertEqual((result['rent'], result['net_votes']),
            (D('8.82'), 4))
        self.assertEqual(result['groups'], [1, 0, 1, 1, 1, None])
        self.assertEqual(D('8.82') * D('64.20'), D('566.2440'))
        # M02: net -2 -> 6.61; M03: net 0 -> mean
        self.assertEqual(table([-1, -1, 0, 0, 0])['rent'], D('6.61'))
        self.assertEqual(table([0, 0, 0, 0, 0])['rent'], D('7.08'))
        # Majority within a group: 2 plus, 1 minus -> +1
        self.assertEqual(compute_rent('table', 5, 7, 9, [('majority', [
                            ('plus', 'vote', None), ('plus', 'vote', None),
                            ('minus', 'vote', None)])])['net_votes'], 1)
        # Limited to the upper value; reduction after the classification
        self.assertEqual(table([1] * 6)['rent'], D('9.25'))
        self.assertEqual(table([0] * 5, [('minus', 'amount', D('0.33'))])[
                'rent'], D('6.75'))
        # Without netting: plus towards the upper, minus towards the lower
        result = compute_rent('table', D('5.90'), D('7.08'), D('9.25'), [
                ('majority', [('plus', 'vote', None)]),
                ('majority', [('minus', 'vote', None)])],
            group_netting=False)
        self.assertEqual(result['rent'], D('7.28'))
        # M11: regression 9.00 + 5 % - 3 % + 0.20 = 9.38, spread +-15 %
        result = compute_rent('regression', None, D('9.00'), None, [
                ('additive', [('plus', 'percent', D(5)),
                        ('minus', 'percent', D(3)),
                        ('plus', 'amount', D('0.20'))])],
            spread_lower_percent=D(-15), spread_upper_percent=D(15))
        self.assertEqual((result['rent'], result['lower'], result['upper']),
            (D('9.38'), D('7.97'), D('10.79')))

    @with_transaction()
    def test_rent_survey(self):
        "Rent survey: import, classification, calculation, acceptance"
        from trytond.modules.company.tests import create_company, set_company
        from trytond.model.exceptions import AccessError
        from trytond.transaction import Transaction

        pool = Pool()
        BaseObject = pool.get('real_estate.base_object')
        Measurement = pool.get('real_estate.measurement')
        Survey = pool.get('real_estate.rent_survey')
        Version = pool.get('real_estate.rent_survey.version')
        Dimension = pool.get('real_estate.rent_survey.dimension')
        Cell = pool.get('real_estate.rent_survey.cell')
        Feature = pool.get('real_estate.rent_survey.feature')
        Class = pool.get('real_estate.rent_survey.dimension.class')
        Value = pool.get('real_estate.base_object.rent_survey_value')
        Calculation = pool.get('real_estate.rent_survey.calculation')
        Import = pool.get('real_estate.rent_survey.import', type='wizard')
        Features = pool.get('real_estate.rent_survey.features',
            type='wizard')
        ModelData = pool.get('ir.model.data')
        start = datetime.date(2025, 1, 1)
        key_date = datetime.date(2026, 11, 1)

        company = create_company()
        with set_company(company):
            counter = iter(range(1, 100))

            def obj(name, type_, parent=None, **kw):
                record, = BaseObject.create([dict({'name': name,
                                'type': type_, 'sequence': next(counter),
                                'company': company.id, 'start_date': start,
                                'parent': parent.id if parent else None},
                            **kw)])
                return record

            def measure(record, xml_id, value):
                Measurement.create([{'base_object': record.id,
                            'valid_from': start, 'value': value,
                            'm_type': ModelData.get_id('real_estate',
                                xml_id)}])
            apartment = ModelData.get_id('real_estate', 'use_class_apartment')
            prop = obj('P', 'property')
            building = obj('B', 'building', prop, year_of_construction='1958')
            unit = obj('U1', 'object', building,
                type_of_use='residential', use_class=apartment)
            measure(unit, 'measurement_living_space_type', 64.20)
            measure(unit, 'measurement_number_of_rooms_type', 2)
            measure(building, 'measurement_energy_consumption_type', 130)

            survey, = Survey.create([{'name': 'Berliner Mietspiegel'}])
            version, = Version.create([{'survey': survey.id,
                        'name': 'Berliner Mietspiegel 2026',
                        'valid_from': datetime.date(2026, 5, 28)}])
            self.assertEqual(version.area_measurement_type.id,
                ModelData.get_id('real_estate',
                    'measurement_living_space_type'))
            Dimension.create([{'version': version.id, 'code': 'location',
                        'name': 'Wohnlage', 'level': 'property',
                        'source': 'manual', 'classes': [('create', [
                                    {'code': c, 'name': c} for c in [
                                        'simple', 'medium', 'good']])]}, {
                        'version': version.id, 'code': 'age',
                        'name': 'Baualter', 'level': 'building',
                        'source': 'year_of_construction',
                        'classes': [('create', [
                                    {'code': 'to_1918', 'name': 'bis 1918',
                                        'value_max': 1919},
                                    {'code': '1950_1964',
                                        'name': '1950-1964',
                                        'value_min': 1950,
                                        'value_max': 1965},
                                    {'code': '1973_1990_o',
                                        'name': '1973-1990 Ost',
                                        'manual_only': True},
                                    {'code': '2010_2015',
                                        'name': '2010-2015',
                                        'value_min': 2010,
                                        'value_max': 2016},
                                    ])]}])

            def run_import(kind, content, replace=False):
                session_id, _, _ = Import.create()
                with Transaction().set_context(
                        active_model=Version.__name__,
                        active_id=version.id, active_ids=[version.id]):
                    data = {'start': {'kind': kind, 'replace': replace,
                            'file_': content.encode('utf-8')}}
                    result = Import.execute(session_id, data, 'preview')
                    preview = result['view']['defaults']
                    if not preview.get('problems'):
                        Import.execute(session_id, data, 'import_')
                Import.delete(session_id)
                return preview

            # M14: overlapping area ranges are reported in the preview
            preview = run_import('cells', '68;location=medium,age=to_1918;'
                ';40;8,07;11,05;14,35;1;\n69;location=medium,age=to_1918;'
                '35;45;8,44;11,06;15,13;1;\n')
            self.assertIn('68', preview['problems'])
            self.assertFalse(version.cells)
            preview = run_import('cells', '\n'.join([
                        'code;dims;area_min;area_max;lower;mean;upper;'
                        'qualified;note',
                        '68;location=medium,age=to_1918;;35;8,07;11,05;'
                        '14,35;1;',
                        '69;location=medium,age=to_1918;35;40;8,44;11,06;'
                        '15,13;1;',
                        '70;location=medium,age=to_1918;40;65;6,46;8,49;'
                        '12,59;1;',
                        '84;location=medium,age=1950_1964;40;45;6,70;7,72;'
                        '10,01;1;',
                        '85;location=medium,age=1950_1964;45;;5,90;7,08;'
                        '9,25;1;',
                        '99;location=medium,age=2010_2015;;;9,00;10,00;'
                        '12,00;0;',
                        ]))
            self.assertIsNone(preview['problems'])
            self.assertEqual(len(Version(version.id).cells), 6)
            energy = 'Energy Consumption Value'
            run_import('features', '\n'.join([
                        'group_code;code;direction;effect;value;level;'
                        'applies_to;auto_measurement;auto_min;auto_max;'
                        'name;description;exclusive_with',
                        '1;b_wc_wall;plus;vote;;object;;;;;WC;;',
                        '1;b_towel;plus;vote;;object;;;;;Handtuch;;',
                        '2;k_fitted;plus;vote;;object;;;;;EBK;;',
                        '2;k_no_dishwasher;minus;vote;;object;;;;;GSP;;',
                        '2;k_floor;plus;vote;;object;age=to_1918,'
                        'age=1950_1964;;;;Boden;;',
                        '3;w_balcony;plus;vote;;object;;;;;Balkon;;',
                        '3;w_windows;plus;vote;;object;;;;;Fenster;;',
                        '4;g_bike;plus;vote;;building;;;;;Fahrrad;;',
                        '4;g_insulation;plus;vote;;building;;;;;Daemmung;;',
                        f'4;g_energy_lt100;plus;vote;;building;;{energy};'
                        '80;100;< 100;;',
                        f'4;g_energy_lt120;plus;vote;;building;;{energy};'
                        '100;120;< 120;;',
                        '5;u_quiet;plus;vote;;property;;;;;ruhig;;u_noise',
                        '5;u_noise;minus;vote;;property;;;;;laut;;',
                        'S;s_minor;minus;amount;0,33;object;age=to_1918;;;;'
                        'Minderausstattung;;',
                        ]))
            version = Version(version.id)
            self.assertEqual([g.rule for g in version.groups],
                ['majority'] * 5 + ['additive'])
            u_quiet, = Feature.search([('code', '=', 'u_quiet')])
            self.assertEqual([f.code for f in u_quiet.exclusive_with],
                ['u_noise'])
            Version.check([version])
            self.assertIn('Check without problems',
                Version(version.id).check_result)

            # Assignments: class at the property, features on 3 levels
            BaseObject.write([prop], {'rent_survey': survey.id})
            self.assertTrue(BaseObject(unit.id).rent_survey_active)
            medium = [c for d in version.dimensions for c in d.classes
                if c.code == 'medium'][0]
            Value.create([{'base_object': prop.id, 'kind': 'class',
                        'survey_class': medium.id}])
            self.assertEqual(Value.search([('base_object', '=', prop.id)])[
                    0].class_code, 'medium')
            # Selection of classes/features: version and level of the
            # object (domain on the values of the object form)
            for record in [prop, building, unit]:
                self.assertEqual(BaseObject(record.id).rent_survey_version,
                    version)
            unsaved = BaseObject(type='property', rent_survey=survey)
            self.assertEqual(unsaved.on_change_with_rent_survey_version(),
                version)
            g_bike, = Feature.search([('code', '=', 'g_bike')])
            with self.assertRaises(ValidationError):
                Value.create([{'base_object': unit.id, 'kind': 'feature',
                            'survey_feature': g_bike.id}])
            Value.create([{'base_object': building.id, 'kind': 'feature',
                        'survey_feature': g_bike.id}])
            Value.delete(Value.search([('feature_code', '=', 'g_bike')]))
            # Classes only on the level of their classification feature or
            # below: the age (building) not on the property
            age_class = [c for d in version.dimensions for c in d.classes
                if c.code == '1950_1964'][0]
            with self.assertRaises(ValidationError):
                Value.create([{'base_object': prop.id, 'kind': 'class',
                            'survey_class': age_class.id}])
            Value.create([{'base_object': unit.id, 'kind': 'class',
                        'survey_class': age_class.id}])
            # (the failed create leaves its row in the test transaction)
            Value.delete(Value.search([('class_code', '=', '1950_1964')]))
            self.assertEqual(len(Class.search([
                        ('rec_name', 'ilike', '%Baualter%')])), 4)

            def assign(record, codes):
                Value.create([{'base_object': record.id, 'kind': 'feature',
                            'feature_code': c} for c in codes])
            assign(prop, ['u_quiet'])
            assign(building, ['g_bike', 'g_insulation'])
            # Wizard "Assign Features": checklist of the level
            session_id, _, _ = Features.create()
            with Transaction().set_context(
                    active_model=BaseObject.__name__, active_id=unit.id,
                    active_ids=[unit.id]):
                defaults = Features.execute(session_id, {}, 'start')[
                    'view']['defaults']
                self.assertEqual(defaults['features'], [])
                codes = ['b_wc_wall', 'b_towel', 'k_fitted',
                    'k_no_dishwasher', 'w_balcony', 'w_windows']
                defaults = {k: v for k, v in defaults.items()
                    if '.' not in k}
                Features.execute(session_id, {'start': dict(defaults,
                            features=[f.id for f in Feature.search([
                                        ('code', 'in', codes)])])},
                    'save')
            Features.delete(session_id)
            self.assertEqual(sorted(v.feature_code
                    for v in BaseObject(unit.id).rent_survey_values),
                sorted(codes))
            # Wizard "Copy from Object": features of another unit of the
            # property, missing ones only, no duplicates on a second run
            Copy = pool.get('real_estate.rent_survey.copy', type='wizard')
            unit2 = obj('U2', 'object', building,
                type_of_use='residential', use_class=apartment)
            Value.create([{'base_object': unit2.id, 'kind': 'feature',
                        'feature_code': 'b_wc_wall'}])

            def copy(replace=False):
                session_id, _, _ = Copy.create()
                with Transaction().set_context(
                        active_model=BaseObject.__name__,
                        active_id=unit2.id, active_ids=[unit2.id]):
                    defaults = Copy.execute(session_id, {}, 'start')[
                        'view']['defaults']
                    self.assertEqual(defaults['property'], prop.id)
                    defaults = {k: v for k, v in defaults.items()
                        if '.' not in k}
                    Copy.execute(session_id, {'start': dict(defaults,
                                source=unit.id, replace=replace)}, 'copy_')
                Copy.delete(session_id)
                return sorted(v.feature_code
                    for v in BaseObject(unit2.id).rent_survey_values)
            self.assertEqual(copy(), sorted(codes))
            self.assertEqual(copy(), sorted(codes))
            self.assertEqual(copy(replace=True), sorted(codes))
            Value.delete(list(BaseObject(unit2.id).rent_survey_values))
            # ... also between buildings of the property (classes too)
            building2 = obj('B2', 'building', prop)
            session_id, _, _ = Copy.create()
            with Transaction().set_context(
                    active_model=BaseObject.__name__,
                    active_id=building2.id, active_ids=[building2.id]):
                defaults = {k: v for k, v in Copy.execute(session_id, {},
                        'start')['view']['defaults'].items() if '.' not in k}
                self.assertEqual(defaults['type'], 'building')
                Copy.execute(session_id, {'start': dict(defaults,
                            source=building.id)}, 'copy_')
            Copy.delete(session_id)
            self.assertEqual(
                sorted((v.kind, v.class_code, v.feature_code)
                    for v in BaseObject(building2.id).rent_survey_values),
                sorted((v.kind, v.class_code, v.feature_code)
                    for v in BaseObject(building.id).rent_survey_values))
            self.assertTrue(BaseObject(building2.id).rent_survey_values)

            # Matrix: export the apartments, change externally, import
            import csv
            import io
            from trytond.modules.real_estate.rent_survey import (
                matrix_changes, matrix_export)
            today = datetime.date.today()
            content = matrix_export(prop, 'object', today)
            rows = list(csv.reader(io.StringIO(content), delimiter=';'))
            header = rows[0]
            self.assertEqual(header[:2], ['id', 'object'])
            self.assertIn('class:location', header)
            self.assertIn('k_fitted', header)
            self.assertNotIn('g_bike', header)
            self.assertEqual(rows[1][0], '#')
            data = {int(r[0]): r for r in rows[2:]}
            self.assertEqual(set(data), {unit.id, unit2.id})
            col = header.index
            self.assertEqual(data[unit.id][col('k_fitted')], 'x')
            data[unit.id][col('k_fitted')] = ''
            data[unit2.id][col('b_towel')] = 'X'
            data[unit2.id][col('class:location')] = 'good'

            def write(rows):
                output = io.StringIO()
                csv.writer(output, delimiter=';').writerows(rows)
                return output.getvalue()
            edited = write(rows[:2] + list(data.values()))
            changes, problems = matrix_changes(prop, 'object', today,
                edited)
            self.assertEqual(problems, [])
            self.assertEqual(len(changes), 2)
            MatrixImport = pool.get('real_estate.rent_survey.matrix.import',
                type='wizard')
            session_id, _, _ = MatrixImport.create()
            with Transaction().set_context(
                    active_model=BaseObject.__name__,
                    active_id=prop.id, active_ids=[prop.id]):
                data_ = {'start': {'property': prop.id, 'level': 'object',
                        'key_date': today,
                        'file_': edited.encode('utf-8-sig')}}
                preview = MatrixImport.execute(session_id, data_,
                    'preview')['view']['defaults']
                self.assertIsNone(preview['problems'])
                self.assertIn('− k_fitted', preview['preview'])
                MatrixImport.execute(session_id, data_, 'apply')
            MatrixImport.delete(session_id)
            self.assertNotIn('k_fitted', [v.feature_code
                    for v in BaseObject(unit.id).rent_survey_values])
            self.assertEqual(sorted((v.kind, v.class_code, v.feature_code)
                    for v in BaseObject(unit2.id).rent_survey_values),
                [('class', 'good', None), ('feature', None, 'b_towel')])
            # unchanged export -> no changes; errors are reported
            self.assertEqual(matrix_changes(prop, 'object', today,
                    matrix_export(prop, 'object', today))[0], [])
            bad = write([header + ['nonsense'], ['999999', 'X'],
                    [str(unit.id), 'U1'] + ['?'] * (len(header) - 2)])
            problems = matrix_changes(prop, 'object', today, bad)[1]
            self.assertTrue(any('nonsense' in p for p in problems))
            self.assertTrue(any('999999' in p for p in problems))
            # restore
            Value.delete(list(BaseObject(unit2.id).rent_survey_values))
            Value.create([{'base_object': unit.id, 'kind': 'feature',
                        'feature_code': 'k_fitted'}])

            def calculate(**kw):
                calculation, = Calculation.create([dict({
                                'base_object': unit.id,
                                'key_date': key_date}, **kw)])
                Calculation.calculate([calculation])
                return Calculation(calculation.id)

            # M01: cell 85, net +4, 8.82 EUR/m², 566.24 EUR
            calc = calculate()
            self.assertEqual(calc.state, 'calculated')
            self.assertEqual(calc.check_state, 'ok')
            self.assertEqual((calc.cell.code, calc.net_votes,
                    calc.rent_per_sqm, calc.area, calc.comparative_rent),
                ('85', 4, Decimal('8.82'), Decimal('64.20'),
                    Decimal('566.24')))
            self.assertEqual(calc.building, building)
            self.assertRegex(calc.protocol, r'8[.,]82 €/m²')
            self.assertRegex(calc.protocol, r'566[.,]24 €')
            inputs = json.loads(calc.inputs_json)
            self.assertEqual({c['dimension']: (c['class'], c['source'])
                    for c in inputs['classes']}, {
                    'location': ('medium', 'manual'),
                    'age': ('1950_1964', 'derived')})

            # M13: calculated -> only acceptance fields; accepted locked
            with self.assertRaises(AccessError):
                Calculation.check_modification('write', [calc],
                    values={'key_date': key_date}, external=True)
            Calculation.accept([calc])
            calc = Calculation(calc.id)
            self.assertEqual((calc.state, calc.accepted_rent_per_sqm),
                ('accepted', Decimal('8.82')))
            with self.assertRaises(AccessError):
                Calculation.check_modification('write', [calc],
                    values={'deviation_reason': 'x'}, external=True)
            with self.assertRaises(AccessError):
                Calculation.delete([calc])
            # ... and the version is locked
            self.assertTrue(Version(version.id).locked)
            with self.assertRaises(AccessError):
                Cell.check_modification('write', list(version.cells),
                    values={'mean': 1}, external=True)
            Calculation.recalculate([calc])
            self.assertEqual(Calculation.search_count([
                        ('base_object', '=', unit.id)]), 2)

            # M07: energy value 98 -> automatic feature "< 100" only
            Measurement.create([{'base_object': building.id,
                        'valid_from': datetime.date(2026, 1, 1),
                        'value': 98, 'm_type': ModelData.get_id(
                            'real_estate',
                            'measurement_energy_consumption_type')}])
            inputs = json.loads(calculate().inputs_json)
            self.assertIn({'code': 'g_energy_lt100', 'level': 'building',
                    'source': 'auto'}, inputs['features'])
            self.assertNotIn('g_energy_lt120',
                [f['code'] for f in inputs['features']])

            # M04 / M10: year 1910 - cell by living space, reduction 0.33
            BaseObject.write([building], {'year_of_construction': '1910'})
            assign(unit, ['s_minor'])
            calc = calculate()
            self.assertEqual(calc.cell.code, '70')
            # net +4: 8.49 + 4 x 0.2 x (12.59 - 8.49) = 11.77 - 0.33
            self.assertEqual(calc.rent_per_sqm, Decimal('11.44'))
            for area, code in [(39.99, '69'), (40.00, '70')]:
                Measurement.create([{'base_object': unit.id,
                            'valid_from': datetime.date(2026, 2, 1),
                            'value': area, 'm_type': ModelData.get_id(
                                'real_estate',
                                'measurement_living_space_type')}])
                self.assertEqual(calculate().cell.code, code)
                Measurement.delete(Measurement.search([
                            ('base_object', '=', unit.id),
                            ('valid_from', '=', datetime.date(2026, 2, 1)),
                            ]))

            # M08: feature only for older classes ignored with 2012
            BaseObject.write([building], {'year_of_construction': '2012'})
            assign(unit, ['k_floor'])
            calc = calculate()
            self.assertEqual(calc.cell.code, '99')
            self.assertEqual(sorted(json.loads(calc.inputs_json)['ignored']),
                ['k_floor', 's_minor'])
            # B05: cell outside the qualified scope -> warning, reason
            self.assertEqual(calc.check_state, 'warning')
            with self.assertRaises(ValidationError):
                Calculation.accept([calc])
            Calculation.write([calc], {'deviation_reason': 'Hinweis'})
            Calculation.accept([calc])

            # M05: year 1975 - only a manual class -> B03, stays draft
            BaseObject.write([building], {'year_of_construction': '1975'})
            calc = calculate()
            self.assertEqual((calc.state, calc.check_state),
                ('draft', 'error'))
            self.assertIn('B03', calc.check_message)

            # M06: the building overrides the location of the property
            BaseObject.write([building], {'year_of_construction': '1958'})
            simple = [c for d in version.dimensions for c in d.classes
                if c.code == 'simple'][0]
            Value.create([{'base_object': building.id, 'kind': 'class',
                        'survey_class': simple.id}])
            calc = calculate()
            location, = [c for c in json.loads(calc.inputs_json)['classes']
                if c['dimension'] == 'location']
            self.assertEqual((location['class'], location['level']),
                ('simple', 'building'))
            self.assertIn('B04', calc.check_message)
            Value.delete(Value.search([('base_object', '=', building.id),
                        ('kind', '=', 'class')]))

            # M09: features excluding each other -> B06
            assign(prop, ['u_noise'])
            calc = calculate()
            self.assertIn('B06', calc.check_message)
            Value.delete(Value.search([('feature_code', '=', 'u_noise')]))

            # M12: new version with the same codes - assignments apply
            NewVersion = pool.get('real_estate.rent_survey.new_version',
                type='wizard')
            session_id, _, _ = NewVersion.create()
            with Transaction().set_context(
                    active_model=Version.__name__, active_id=version.id,
                    active_ids=[version.id]):
                NewVersion.execute(session_id, {'start': {
                            'name': 'Berliner Mietspiegel 2028',
                            'valid_from': datetime.date(2028, 5, 1),
                            'survey_date': None}}, 'create_')
            NewVersion.delete(session_id)
            new_version, = Version.search([('id', '!=', version.id)])
            self.assertFalse(new_version.locked)
            self.assertEqual(len(new_version.cells), 6)
            new_quiet, = Feature.search([('code', '=', 'u_quiet'),
                    ('group.version', '=', new_version.id)])
            self.assertEqual([f.code for f in new_quiet.exclusive_with],
                ['u_noise'])
            # k_floor now counts (1958): all 5 groups +1 -> upper value
            calc = calculate(key_date=datetime.date(2028, 6, 1))
            self.assertEqual((calc.version, calc.cell.version,
                    calc.net_votes, calc.rent_per_sqm), (new_version,
                    new_version, 5, Decimal('9.25')))

            # Button on the rental unit: calculation of the unit, opened
            # directly (not on the first tab of the action)
            action = BaseObject.rent_survey_calculate([unit])
            self.assertEqual(action['domains'], [])
            self.assertEqual(action['views'][0][1], 'form')
            last, = Calculation.search([], order=[('id', 'DESC')], limit=1)
            self.assertEqual((last.base_object, last.key_date),
                (unit, datetime.date.today()))
            self.assertIn(str(last.id), action['pyson_domain'])
            self.assertEqual(action['res_id'], [last.id])
            # Pressed again on the same day: the open calculation is
            # calculated again, no duplicate
            count = Calculation.search_count([])
            BaseObject.rent_survey_calculate([unit])
            Calculation.recalculate([Calculation(last.id)])
            self.assertEqual(Calculation.search_count([]), count)
            # Not accepted calculations can be deleted
            Calculation.delete([Calculation(last.id)])
            self.assertEqual(Calculation.search_count([]), count - 1)
            # Only apartments: a parking space (use class without the
            # comparative rent) has no rent survey data and no calculation
            UseClass = pool.get('real_estate.use_class')
            parking_class = UseClass(ModelData.get_id('real_estate',
                    'use_class_parking'))
            self.assertIn('comparative_rent', UseClass(apartment)
                .adjustment_procedures)
            self.assertNotIn('comparative_rent',
                parking_class.adjustment_procedures)
            parking = obj('P1', 'object', building,
                type_of_use='residential', use_class=parking_class.id)
            self.assertFalse(BaseObject(parking.id).rent_survey_active)
            self.assertTrue(BaseObject(unit.id).rent_survey_active)
            self.assertFalse(UseClass.allows([parking], 'comparative_rent'))
            self.assertTrue(UseClass.allows([parking, unit],
                    'comparative_rent'))
            self.assertTrue(UseClass.allows([parking], 'index_rent'))
            self.assertFalse(UseClass.allows([], 'comparative_rent'))
            self.assertTrue(UseClass.allows([], 'index_rent'))
            with self.assertRaises(ValidationError):
                Calculation.create([{'base_object': parking.id,
                            'key_date': key_date}])

            # B01: no rent survey on the property
            BaseObject.write([prop], {'rent_survey': None})
            self.assertIn('B01', calculate().check_message)

    @with_transaction()
    def test_rent_survey_berlin_2026(self):
        "Berlin rent survey 2026: CSV files and examples of the brochure"
        import importlib.util
        import os

        from trytond.modules.company.tests import create_company, set_company
        from trytond.transaction import Transaction

        pool = Pool()
        BaseObject = pool.get('real_estate.base_object')
        Measurement = pool.get('real_estate.measurement')
        Survey = pool.get('real_estate.rent_survey')
        Version = pool.get('real_estate.rent_survey.version')
        Dimension = pool.get('real_estate.rent_survey.dimension')
        Value = pool.get('real_estate.base_object.rent_survey_value')
        Calculation = pool.get('real_estate.rent_survey.calculation')
        Import = pool.get('real_estate.rent_survey.import', type='wizard')
        ModelData = pool.get('ir.model.data')
        here = os.path.dirname(__file__)
        spec = importlib.util.spec_from_file_location('berlin',
            os.path.join(here, 'test_rent_survey.py'))
        berlin = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(berlin)
        start = datetime.date(2025, 1, 1)
        key_date = datetime.date(2026, 11, 1)

        company = create_company()
        with set_company(company):
            survey, = Survey.create([{'name': 'Berliner Mietspiegel'}])
            version, = Version.create([{'survey': survey.id,
                        'name': 'Berliner Mietspiegel 2026',
                        'valid_from': berlin.VALID_FROM}])
            Dimension.create([{'version': version.id, 'code': 'location',
                        'name': 'Wohnlage', 'level': 'property',
                        'source': 'manual', 'classes': [('create', [
                                    {'code': c, 'name': n}
                                    for c, n in berlin.LOCATIONS])]}, {
                        'version': version.id, 'code': 'age',
                        'name': 'Bezugsfertigkeit', 'level': 'building',
                        'source': 'year_of_construction',
                        'classes': [('create', [{'code': c, 'name': n,
                                        'value_min': lo, 'value_max': hi,
                                        'manual_only': m}
                                    for c, n, lo, hi, m in berlin.AGES])]}])
            for kind, path in [('cells', berlin.CELLS_FILE),
                    ('features', berlin.FEATURES_FILE)]:
                session_id, _, _ = Import.create()
                with open(path, encoding='utf-8') as file, \
                        Transaction().set_context(
                            active_model=Version.__name__,
                            active_id=version.id, active_ids=[version.id]):
                    data = {'start': {'kind': kind, 'replace': False,
                            'file_': file.read().encode('utf-8')}}
                    preview = Import.execute(session_id, data, 'preview')[
                        'view']['defaults']
                    self.assertIsNone(preview['problems'], kind)
                    Import.execute(session_id, data, 'import_')
                Import.delete(session_id)
            version = Version(version.id)
            self.assertEqual(len(version.cells), 189)
            self.assertEqual(sum(len(g.features) for g in version.groups),
                86)
            self.assertEqual(version.check_data(), [])

            counter = iter(range(1, 100))
            apartment = ModelData.get_id('real_estate', 'use_class_apartment')
            living = ModelData.get_id('real_estate',
                'measurement_living_space_type')
            energy = ModelData.get_id('real_estate',
                'measurement_energy_consumption_type')
            classes = {(c.dimension.code, c.code): c
                for d in version.dimensions for c in d.classes}

            def unit(location, year, area, age_class=None):
                prop, = BaseObject.create([{'name': 'P', 'type': 'property',
                            'sequence': next(counter), 'start_date': start,
                            'company': company.id,
                            'rent_survey': survey.id}])
                building, = BaseObject.create([{'name': 'B',
                            'type': 'building', 'parent': prop.id,
                            'sequence': next(counter), 'start_date': start,
                            'company': company.id,
                            'year_of_construction': year}])
                record, = BaseObject.create([{'name': 'U', 'type': 'object',
                            'parent': building.id, 'company': company.id,
                            'sequence': next(counter), 'start_date': start,
                            'type_of_use': 'residential',
                            'use_class': apartment}])
                Measurement.create([{'base_object': record.id,
                            'valid_from': start, 'value': area,
                            'm_type': living}])
                values = [{'base_object': prop.id, 'kind': 'class',
                        'survey_class': classes[('location', location)].id}]
                if age_class:
                    values.append({'base_object': building.id,
                            'kind': 'class',
                            'survey_class': classes[('age', age_class)].id})
                Value.create(values)
                return prop, building, record

            def calculate(record):
                calculation, = Calculation.create([{
                            'base_object': record.id, 'key_date': key_date}])
                Calculation.calculate([calculation])
                return Calculation(calculation.id)

            def assign(record, codes):
                Value.create([{'base_object': record.id, 'kind': 'feature',
                            'feature_code': c} for c in codes])

            # Brochure no. 8: simple, built 1910, 80 m² -> row 10; good,
            # 1987 West (manual class), 65 m² -> row 161
            self.assertEqual(calculate(unit('simple', '1910', 80)[2])
                .cell.code, '10')
            self.assertEqual(calculate(unit('good', '1987', 65,
                        '1986_1990_w')[2]).cell.code, '161')
            # Without a manual class 1973-1990 cannot be derived (B03)
            self.assertIn('B03',
                calculate(unit('good', '1987', 65)[2]).check_message)

            # Brochure no. 10.4 B: medium, 1919-1949, 60 m² (row 81),
            # groups +,+,+,-,- -> +20 % of 2.25 -> 7.75 EUR/m²
            prop, building, record = unit('medium', '1930', 60)
            assign(record, ['b_second_wc', 'k_fitted', 'w_storage'])
            assign(building, ['g_no_intercom', 'u_smell'])
            calc = calculate(record)
            self.assertEqual((calc.cell.code, calc.net_votes,
                    calc.rent_per_sqm), ('81', 1, Decimal('7.75')))

            # Energy value 90: the two upper stages count (no. 10.4 A),
            # either the insulation or the energy value (B06)
            Measurement.create([{'base_object': building.id,
                        'valid_from': start, 'value': 90, 'm_type': energy}])
            features = {f['code'] for f in json.loads(
                    calculate(record).inputs_json)['features']}
            self.assertTrue({'g_energy_lt120', 'g_energy_lt100'} <= features)
            self.assertNotIn('g_energy_lt80', features)
            assign(building, ['g_insulation'])
            self.assertIn('B06', calculate(record).check_message)

    @with_transaction()
    def test_adjustment_run(self):
        "Adjustment run: workflow, protocol, process, reset, cancel"
        from trytond.modules.company.tests import create_company, set_company

        pool = Pool()
        Run = pool.get('real_estate.contract.term.adjustment.run')
        PriceIndex = pool.get('real_estate.price_index')
        Process = pool.get('real_estate.process')

        company = create_company()
        with set_company(company):
            index, = PriceIndex.search([('code', '=', 'VPI-DE')], limit=1) \
                or PriceIndex.create([{'code': 'VPI-DE', 'name': 'VPI',
                            'base_year': 2020}])
            run, = Run.create([{'procedure': 'index_rent',
                        'price_index': index.id,
                        'index_month': datetime.date(2026, 8, 1),
                        'key_date': datetime.date(2026, 10, 1)}])
            self.assertTrue(run.run_id.startswith('AL-'))
            self.assertEqual(run.state, 'draft')
            # Select: no agreements - protocol, process of the run
            Run.select([run])
            run = Run(run.id)
            self.assertEqual(run.state, 'selected')
            self.assertIn('0', run.summary)
            process = run.process
            self.assertTrue(process)
            self.assertEqual(process.template.code,
                'adjustment_run_index_rent')
            steps = {t.template_step.done_method: t for t in process.tasks}
            self.assertEqual(steps['run_selected'].state, 'done')
            self.assertEqual(len(run.process_tasks), 6)
            # Calculate: next step done
            Run.calculate([run])
            run = Run(run.id)
            self.assertEqual(run.state, 'calculated')
            self.assertEqual(Process(process.id).tasks and {
                    t.template_step.done_method: t.state
                    for t in Process(process.id).tasks}['run_calculated'],
                'done')
            # Reset to draft and select again
            Run.reset([run])
            self.assertEqual(Run(run.id).state, 'draft')
            Run.select([Run(run.id)])
            Run.calculate([Run(run.id)])
            self.assertEqual(len(Process.search([
                        ('resource', '=', str(run))])), 1)
            # Cancel: run and process cancelled, deletable
            Run.cancel([Run(run.id)])
            run = Run(run.id)
            self.assertEqual(run.state, 'cancelled')
            self.assertEqual(run.process.state, 'cancelled')
            self.assertIn('\n', run.protocol)
            Run.delete([run])
            # Approve without adjustments is refused
            run2, = Run.create([{'procedure': 'index_rent',
                        'price_index': index.id,
                        'index_month': datetime.date(2026, 8, 1),
                        'key_date': datetime.date(2026, 10, 1)}])
            Run.select([run2])
            Run.calculate([Run(run2.id)])
            with self.assertRaises(ValidationError):
                Run.approve([Run(run2.id)])

    @with_transaction()
    def test_comparative_rent_rules(self):
        "Comparative rent: cap, chain history, dates (V-T01 to V-T04, V-T06)"
        from trytond.modules.real_estate.contract_comparative_rent import (
            chain_history, comparative_cap, earliest_first, effective_date)

        # V-T01: 8.82 €/m² × 64.20 m² = 566.24, rent 480 unchanged, cap 15 %
        comparative = Decimal('566.24')
        self.assertEqual(comparative_cap(comparative, Decimal('480.00'),
                Decimal(0), Decimal(15)),
            (Decimal('552.00'), Decimal('552.00'), 'cap'))
        # V-T02: cap 20 % - the comparative rent is decisive
        self.assertEqual(comparative_cap(comparative, Decimal('480.00'),
                Decimal(0), Decimal(20)),
            (Decimal('576.00'), Decimal('566.24'), 'comparative'))
        valid_from = datetime.date(2026, 12, 1)
        # unchanged chain: last change = start, base = initial rent
        chain = [(datetime.date(2020, 1, 1), Decimal('480.00'), False)]
        self.assertEqual(chain_history(chain, valid_from),
            (datetime.date(2020, 1, 1), Decimal('480.00'), Decimal(0)))
        # V-T03: increase 10 months before - waiting period not reached
        chain = [(datetime.date(2020, 1, 1), Decimal('450.00'), False),
            (datetime.date(2026, 2, 1), Decimal('480.00'), False)]
        last_change, base, excluded = chain_history(chain, valid_from)
        self.assertEqual(last_change, datetime.date(2026, 2, 1))
        self.assertEqual(base, Decimal('450.00'))
        self.assertEqual(earliest_first(last_change
                + relativedelta(months=15)), datetime.date(2027, 5, 1))
        # V-T04: modernisation 6 months before - no new waiting period,
        # the increase is added to the cap and not counted
        chain = [(datetime.date(2020, 1, 1), Decimal('480.00'), False),
            (datetime.date(2026, 6, 1), Decimal('530.00'), True)]
        last_change, base, excluded = chain_history(chain, valid_from)
        self.assertEqual(last_change, datetime.date(2020, 1, 1))
        self.assertEqual(base, Decimal('480.00'))
        self.assertEqual(excluded, Decimal('50.00'))
        self.assertEqual(comparative_cap(Decimal('700.00'), base, excluded,
                Decimal(15))[0], Decimal('602.00'))
        # V-T06: receipt 15.03. - consent until 31.05., effective 01.06.
        self.assertEqual(effective_date(datetime.date(2027, 3, 15)),
            datetime.date(2027, 6, 1))
        self.assertEqual(earliest_first(datetime.date(2027, 5, 2)),
            datetime.date(2027, 6, 1))

    @with_transaction()
    def test_comparative_rent_deadlines(self):
        "Comparative rent: consent and lawsuit deadline (V-T06), cap"
        pool = Pool()
        Adjustment = pool.get('real_estate.contract.term.adjustment')
        BaseObject = pool.get('real_estate.base_object')
        RentAdjustment = pool.get('real_estate.contract.rent_adjustment')
        adjustment = Adjustment()
        adjustment.rent_adjustment = RentAdjustment(
            procedure='comparative_rent')
        adjustment.receipt_date = datetime.date(2027, 3, 15)
        self.assertEqual(adjustment.get_deadlines('consent_deadline'),
            datetime.date(2027, 5, 31))
        self.assertEqual(adjustment.get_deadlines('lawsuit_deadline'),
            datetime.date(2027, 8, 31))
        # D4: reduced cap with validity on the property
        prop = BaseObject(type='property', parent=None, reduced_cap=True,
            reduced_cap_valid_from=datetime.date(2025, 1, 1),
            reduced_cap_valid_to=datetime.date(2027, 12, 31))
        self.assertEqual(prop.cap_percent(datetime.date(2026, 6, 1)),
            Decimal(15))
        self.assertEqual(prop.cap_percent(datetime.date(2028, 1, 1)),
            Decimal(20))
        unit = BaseObject(type='object', parent=prop)
        self.assertEqual(unit.cap_percent(datetime.date(2026, 6, 1)),
            Decimal(15))

    @with_transaction()
    def test_comparative_rent_letter_template(self):
        "Request for consent renders the mandatory contents (spec 10.5)"
        import io
        import os
        import re
        import zipfile

        from relatorio.templates.opendocument import Template

        address = _StubRecord(street_single_line='Musterstraße 1',
            postal_code='14163', city='Berlin')
        contract = _StubRecord(contract_number='1-20-191',
            company=_StubRecord(party=_StubRecord(name='Immo GmbH',
                    addresses=[address])),
            property=_StubRecord(address=address))
        version = _StubRecord(name='Berliner Mietspiegel 2026',
            kind='qualified',
            survey=_StubRecord(name='Berliner Mietspiegel'))
        cell = _StubRecord(code='F85', lower=Decimal('6.50'),
            mean=Decimal('8.13'), upper=Decimal('9.94'), qualified=True)
        calculation = _StubRecord(version=version, cell=cell,
            area=Decimal('64.20'), accepted_rent_per_sqm=Decimal('8.82'),
            rent_per_sqm=Decimal('8.82'), deviation_reason=None,
            protocol='Gruppe 1: + Einbauküche → +1')
        record = _StubRecord(id=1, contract=contract, state='declared',
            term_old=_StubRecord(reference_item=None),
            calculation=calculation, amount_old=Decimal('480.00'),
            planned_amount=Decimal('552.00'),
            difference_amount=Decimal('72.00'),
            comparative_amount=Decimal('566.24'),
            cap_percent=Decimal('15'), cap_base_amount=Decimal('480.00'),
            cap_excluded_amount=Decimal(0), cap_amount=Decimal('552.00'),
            limited_by='cap',
            planned_valid_from=datetime.date(2027, 2, 1),
            declaration_date=datetime.date(2026, 10, 30))
        tenant = _StubRecord(full_name='Rudi Völler', name='Rudi Völler')
        path = os.path.join(os.path.dirname(__file__), '..', 'report',
            'comparative_rent_letter_de.odt')
        data = Template(source=None, filepath=path).generate(
            records=[record], record=record, datetime=datetime,
            format_value=str, format_percent=str,
            marks={1: ''}, tenants={1: [(tenant, address)]},
            consent_until={1: datetime.date(2027, 1, 31)},
            ).render().getvalue()
        with zipfile.ZipFile(io.BytesIO(data)) as odt:
            content = odt.read('content.xml').decode()
        text = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', content))
        for expected in ['Rudi Völler', 'Mieterhöhungsverlangen', '480.00',
                '552.00', '72.00', '566.24', 'F85', '8.82', '64.20',
                'Einbauküche', 'qualifizierter Mietspiegel',
                'Kappungsgrenze', '2027-01-31', '2027-02-01']:
            self.assertIn(expected, text)

    @with_transaction()
    def test_comparative_rent_run(self):
        "Comparative rent run: no candidates, process template"
        from trytond.modules.company.tests import create_company, set_company

        pool = Pool()
        Run = pool.get('real_estate.contract.term.adjustment.run')
        company = create_company()
        with set_company(company):
            run, = Run.create([{'procedure': 'comparative_rent',
                        'key_date': datetime.date(2026, 10, 1)}])
            self.assertTrue(run.create_calculations)
            Run.select([run])
            run = Run(run.id)
            self.assertEqual(run.state, 'selected')
            self.assertEqual(run.process.template.code,
                'adjustment_run_comparative_rent')
            self.assertTrue(run.protocol)
            Run.calculate([run])
            with self.assertRaises(ValidationError):
                Run.approve([Run(run.id)])

    def test_handover_report_template(self):
        "Handover report template renders check items, keys and meters"
        import io
        import os
        import re
        import zipfile

        from relatorio.templates.opendocument import Template

        address = _StubRecord(street_single_line='Musterstraße 1',
            postal_code='14163', city='Berlin')
        contract = _StubRecord(contract_number='1-20-191',
            company=_StubRecord(party=_StubRecord(name='Immo GmbH',
                    addresses=[address])),
            property=_StubRecord(address=address))
        record = _StubRecord(id=1, contract=contract, kind='move_out',
            date=datetime.date(2026, 3, 31), time='10:00',
            objects=[_StubRecord(rec_name='Wohnung 01', address=address)],
            tenant_present=False, landlord_employee=None,
            other_participants=None, general_condition='defects',
            cleaned=True, notes='Mieter beseitigt Bohrlöcher bis 15.04.',
            lines=[_StubRecord(room='Bad', item='Fliesen',
                    condition='damage', description='Sprung',
                    remedy_by='tenant',
                    remedy_until=datetime.date(2026, 4, 15))],
            keys=[_StubRecord(key_type='apartment', description='',
                    quantity=2, quantity_expected=3)],
            meters=[_StubRecord(meter=_StubRecord(rec_name='Wasser'),
                    meter_id='Z-2025-0001', value=Decimal('42.5'))])
        tenant = _StubRecord(full_name='Rudi Völler', name='Rudi Völler')
        path = os.path.join(os.path.dirname(__file__), '..', 'report',
            'contract_handover_de.odt')
        data = Template(source=None, filepath=path).generate(
            records=[record], record=record, format_value=str,
            kinds={'move_out': 'Auszug'},
            general_conditions={'defects': 'Mängel'},
            conditions={'damage': 'Schaden'},
            remedies={'tenant': 'Mieter'},
            key_types={'apartment': 'Wohnungstür'},
            marks={1: 'ENTWURF'},
            tenants={1: [(tenant, address)]}).render().getvalue()
        with zipfile.ZipFile(io.BytesIO(data)) as odt:
            content = odt.read('content.xml').decode()
        text = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', content))
        for expected in ['ENTWURF', 'Übergabeprotokoll', 'Auszug',
                'in Abwesenheit des Mieters', 'Rudi Völler', 'Bad',
                'Fliesen', 'Schaden', 'Mieter 2026-04-15', 'Wohnungstür',
                'zurückgegeben', 'Z-2025-0001', '42.5', 'Mängel',
                'besenrein: ja', 'Bohrlöcher']:
            self.assertIn(expected, text)

del ModuleTestCase
