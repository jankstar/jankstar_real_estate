import datetime
from decimal import Decimal

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
        self.assertFalse({'meter_reading', 'index_receipt', 'Rauchmelder'}
            & contract)
        billing = codes('real_estate.billing_unit')
        self.assertTrue({'manual', 'billing_deadline', 'Rauchmelder',
                'Anrufen'} <= billing)
        # automatic-only codes are never offered for manual follow-ups
        self.assertNotIn('index_receipt',
            codes('real_estate.contract.term.adjustment'))
        receipt, = Type.search([('code', '=', 'index_receipt')])
        self.assertEqual(receipt.resource_models,
            ('real_estate.contract.term.adjustment',))
        self.assertFalse(receipt.manual)

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
                                    ])],
                        }])
            start = datetime.date(2026, 10, 1)
            process = Process.start(template, index, start)
            self.assertEqual(Process.start(template, index, start), process)
            self.assertEqual(process.anchor_date, datetime.date(2026, 8, 1))
            steps = {s.name: s for s in process.steps}
            # W26: the previous_done step is planned, no task yet
            self.assertEqual(steps['Danach'].state, 'planned')
            self.assertIsNone(steps['Danach'].task)
            self.assertEqual(steps['Start'].task.due_date,
                datetime.date(2026, 10, 4))
            self.assertEqual(steps['Anker'].task.due_date,
                datetime.date(2026, 9, 1))
            self.assertEqual(steps['Start'].task.process, process)

            # W25: result required
            with self.assertRaises(ValidationError):
                Task.done([steps['Start'].task])
            Task.write([steps['Start'].task], {'result': 'versendet'})
            Task.done([steps['Start'].task])

            # W11: anchor changed - open anchor tasks rescheduled
            Process.write([process], {
                    'anchor_date': datetime.date(2026, 9, 1)})
            Process.reschedule([process])
            self.assertEqual(Task(steps['Anker'].task.id).due_date,
                datetime.date(2026, 10, 1))
            self.assertIn('Anker', Process(process.id).history)

            # W12: previous_done step created after the previous one
            Task.done([steps['Anker'].task])
            danach = Process(process.id).steps[2]
            self.assertEqual(danach.name, 'Danach')
            self.assertEqual(danach.state, 'open')

            # W24: condition met - done by 'check'
            Index.write([index], {'residential_allowed': True})
            Process.check([process])
            self.assertEqual(Task(steps['Bedingung'].task.id).state, 'done')

            # W22: executing the action returns it for the reference
            # record and completes the step
            session_id, _, _ = Execute.create()
            aktion = steps['Aktion'].task
            with Transaction().set_context(active_model='real_estate.task',
                    active_id=aktion.id, active_ids=[aktion.id]):
                result = Execute.execute(session_id, {}, 'open_')
            action = result['actions'][0]
            self.assertEqual(action[0]['res_model'], 'real_estate.task')
            self.assertEqual(action[1]['model'], 'real_estate.price_index')
            self.assertEqual(action[1]['ids'], [index.id])
            self.assertEqual(Task(aktion.id).state, 'done')

            # W27: optional step cancelled = skipped; W13: process done
            optional = steps['Optional'].task
            Task.write([optional], {'result': 'nicht nötig'})
            Task.cancel([optional])
            self.assertEqual(Process(process.id).state, 'running')
            Task.done([danach.task])
            process = Process(process.id)
            self.assertEqual({s.name: s.state for s in process.steps}[
                    'Optional'], 'skipped')
            self.assertEqual(process.state, 'done')
            self.assertEqual(process.progress, '5 / 5 done')

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
