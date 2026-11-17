"Module tests of the area rent_adjustment (part of RealEstateTestCase)"
import datetime
import json
from decimal import Decimal

from dateutil.relativedelta import relativedelta

from trytond.model.exceptions import ValidationError
from trytond.modules.real_estate.tests.common import (
    _StubRecord, _stub_index_agreement)
from trytond.pool import Pool
from trytond.tests.test_tryton import with_transaction


class RentAdjustmentTests:
    "Tests of the area rent_adjustment, mixed into RealEstateTestCase"

    def test_price_index_csv_parsing(self):
        "CSV import: month formats, decimal comma, GENESIS rows, conflicts"
        from trytond.modules.real_estate.rent_adjustment.price_index import parse_index_csv

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

        from trytond.modules.real_estate.rent_adjustment.price_index import (
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

        from trytond.modules.real_estate.rent_adjustment.price_index import GenesisError

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
    def test_execute_in_run_one_transaction_per_adjustment(self):
        "Adjustment run: each adjustment executed in a transaction of its own"
        from unittest.mock import patch
        from trytond.exceptions import UserError
        pool = Pool()
        Adjustment = pool.get('real_estate.contract.term.adjustment')
        Run = pool.get('real_estate.contract.term.adjustment.run')

        transactions = []

        def in_new_transaction(lock_records, func):
            # stands for a committed resp. rolled back transaction
            transactions.append(lock_records)
            return func()

        def execute_declared(adjustment_id, run_id):
            if adjustment_id == 2:
                raise UserError('term split failed')

        with patch.object(Adjustment, '_in_new_transaction',
                    side_effect=in_new_transaction), \
                patch.object(Adjustment, '_execute_declared',
                    side_effect=execute_declared) as execute, \
                patch.object(Adjustment, '_log_execute_error') as log:
            for adjustment_id in (1, 2, 3):
                Adjustment._execute_in_run_one(
                    adjustment_id, 7, f'A{adjustment_id}')

        # the error of the second one does not stop the third one
        self.assertEqual([c.args for c in execute.call_args_list],
            [(1, 7), (2, 7), (3, 7)])
        log.assert_called_once_with(7, 'A2', 'term split failed')
        # adjustment and run locked from the start, the error logged in a
        # transaction of its own with the run locked
        self.assertEqual(transactions, [
                {Adjustment._table: [1], Run._table: [7]},
                {Adjustment._table: [2], Run._table: [7]},
                {Run._table: [7]},
                {Adjustment._table: [3], Run._table: [7]},
                ])

    @with_transaction()
    def test_in_new_transaction_restarts_for_further_locks(self):
        "New transaction: started again with further records locked"
        from contextlib import contextmanager
        from unittest.mock import patch
        from trytond.transaction import Transaction, TransactionError
        pool = Pool()
        Adjustment = pool.get('real_estate.contract.term.adjustment')

        class LockError(TransactionError):
            def fix(self, extras):
                extras['_lock_records'].setdefault('t2', []).append(9)

        started = []

        @contextmanager
        def new_transaction(self, **extras):
            started.append({k: list(v)
                    for k, v in extras['_lock_records'].items()})
            yield self

        calls = []

        def func():
            calls.append(1)
            if len(calls) == 1:
                raise LockError()
            return 'done'

        with patch.object(Transaction, 'new_transaction', new_transaction):
            result = Adjustment._in_new_transaction({'t1': [1]}, func)
        self.assertEqual(result, 'done')
        self.assertEqual(started, [{'t1': [1]}, {'t1': [1], 't2': [9]}])

    def test_rent_survey_compute(self):
        "Rent survey: table and regression method (M01-M03, M10, M11)"
        from trytond.modules.real_estate.rent_adjustment.rent_survey import compute_rent
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
            u_quiet, = Feature.search([('code', '=', 'u_quiet'),
                    ('group.version', '=', version.id)])
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
            g_bike, = Feature.search([('code', '=', 'g_bike'),
                    ('group.version', '=', version.id)])
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
            from trytond.modules.real_estate.rent_adjustment.rent_survey import (
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
            new_version, = Version.search([('id', '!=', version.id),
                    ('survey', '=', survey.id)])
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
        "Berlin rent survey 2026: standard data and examples of the brochure"
        from trytond.modules.company.tests import create_company, set_company

        pool = Pool()
        BaseObject = pool.get('real_estate.base_object')
        Measurement = pool.get('real_estate.measurement')
        Survey = pool.get('real_estate.rent_survey')
        Version = pool.get('real_estate.rent_survey.version')
        Value = pool.get('real_estate.base_object.rent_survey_value')
        Calculation = pool.get('real_estate.rent_survey.calculation')
        ModelData = pool.get('ir.model.data')
        start = datetime.date(2025, 1, 1)
        key_date = datetime.date(2026, 11, 1)

        company = create_company()
        with set_company(company):
            # Standard data rent_survey_berlin.xml (for all companies)
            survey = Survey(ModelData.get_id('real_estate',
                    'rent_survey_berlin'))
            version = Version(ModelData.get_id('real_estate',
                    'rent_survey_berlin_2026'))
            self.assertEqual(version.survey, survey)
            self.assertEqual(version.valid_from, datetime.date(2026, 5, 28))
            self.assertEqual(len(version.dimensions), 2)
            self.assertEqual(
                sum(len(d.classes) for d in version.dimensions), 15)
            self.assertEqual(len(version.cells), 189)
            self.assertEqual(sum(len(g.features) for g in version.groups),
                86)
            self.assertEqual([m.id for m in version.measurement_types],
                Version.default_measurement_types())
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
        from trytond.modules.real_estate.rent_adjustment.contract_comparative_rent import (
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
    def _modernisation_rule(self):
        return {
            'rate_standard': Decimal('8'), 'rate_heating': Decimal('10'),
            'simplified_limit': Decimal('10000'),
            'simplified_maintenance_percent': Decimal('30'),
            'heating_maintenance_percent': Decimal('15'),
            'cap_years': 6, 'cap_high': Decimal('3.00'),
            'cap_low': Decimal('2.00'), 'cap_threshold': Decimal('7.00'),
            'cap_heating': Decimal('0.50'),
            }

    def _modernisation_units(self, rent_per_sqm=Decimal('8.82')):
        "Six apartments, 420 m², apartment 1 with 64.20 m²"
        areas = [Decimal('64.20'), Decimal('71.80'), Decimal('64.20'),
            Decimal('71.80'), Decimal('74.00'), Decimal('74.00')]
        return [{'key': i + 1, 'area': a, 'in_allocation': True,
                'quantity': a, 'vat_deductible': False,
                'rent': a * rent_per_sqm, 'previous': 0,
                'previous_heating': 0} for i, a in enumerate(areas)]

    def test_modernisation_examples(self):
        "Calculation examples A-D of the modernisation (spec 6.7)"
        from trytond.modules.real_estate.rent_adjustment.modernisation import (
            compute_allocation)
        rule = self._modernisation_rule()
        units = self._modernisation_units()
        # A - standard: 180,000 €, maintenance 25 %, grant 15,000 €
        result = compute_allocation(
            [{'net': Decimal('180000'), 'tax': 0,
                    'maintenance_mode': 'percent',
                    'maintenance_value': Decimal('25'), 'unit': None}],
            [{'kind': 'grant', 'amount': Decimal('15000'), 'unit': None}],
            units, 'standard_559', 'measurement', rule)
        self.assertEqual(result[1]['allocable'], Decimal('18342.86'))
        self.assertEqual(result[1]['annual'], Decimal('1467.43'))
        self.assertEqual(result[1]['increase'], Decimal('122.29'))
        self.assertFalse(result[1]['limited'])
        # rounded per unit - the total differs by at most a few cents
        self.assertLessEqual(abs(sum(r['allocable']
                    for r in result.values()) - Decimal('120000')),
            Decimal('0.05'))
        # B - simplified: 9,000 € per apartment, flat rate 30 %
        single = [dict(units[0], key='b')]
        result = compute_allocation(
            [{'net': Decimal('9000'), 'tax': 0, 'unit': None}], [],
            single, 'simplified_559c', 'measurement', rule)
        self.assertEqual(result['b']['increase'], Decimal('42.00'))
        # C - heating: 60,000 €, flat rate 15 %, grant 18,000 €
        result = compute_allocation(
            [{'net': Decimal('60000'), 'tax': 0, 'unit': None}],
            [{'kind': 'grant', 'amount': Decimal('18000'), 'unit': None}],
            units, 'heating_559e', 'measurement', rule)
        self.assertEqual(result[1]['monthly'], Decimal('42.04'))
        self.assertEqual(result[1]['increase'], Decimal('32.10'))
        self.assertTrue(result[1]['limited'])
        # D - cap 2 €/m²: 6.50 €/m², 50 m², 130.00 € computed, 20.00 €
        # previous increase
        unit = {'key': 'd', 'area': Decimal('50'), 'quantity': Decimal('50'),
            'in_allocation': True,
            'vat_deductible': False, 'rent': Decimal('325.00'),
            'previous': Decimal('20.00')}
        result = compute_allocation(
            [{'net': Decimal('19500'), 'tax': 0,
                    'maintenance_mode': 'none', 'unit': None}], [],
            [unit], 'standard_559', 'measurement', rule)
        self.assertEqual(result['d']['monthly'], Decimal('130.00'))
        self.assertEqual(result['d']['cap'], Decimal('80.00'))
        self.assertEqual(result['d']['increase'], Decimal('80.00'))
        # without an area of the cap measurement: no cap
        result = compute_allocation(
            [{'net': Decimal('19500'), 'tax': 0,
                    'maintenance_mode': 'none', 'unit': None}], [],
            [dict(unit, area=None)], 'standard_559', 'measurement', rule)
        self.assertIsNone(result['d']['cap'])
        self.assertEqual(result['d']['increase'], Decimal('130.00'))
        self.assertFalse(result['d']['limited'])

    def test_modernisation_allocation(self):
        "Single assignment, exclusion and net/gross basis (X13, X24, X25)"
        from trytond.modules.real_estate.rent_adjustment.modernisation import (
            allocation_shares, compute_allocation)
        rule = self._modernisation_rule()
        units = self._modernisation_units()
        # X13: balcony only for apartment 3, the rest by the key
        result = compute_allocation([
                {'net': Decimal('42000'), 'tax': 0,
                    'maintenance_mode': 'none', 'unit': None},
                {'net': Decimal('8000'), 'tax': 0,
                    'maintenance_mode': 'none', 'unit': 3},
                ], [], units, 'standard_559', 'measurement', rule)
        self.assertEqual(result[3]['costs'], Decimal('14420.00'))
        self.assertEqual(result[1]['costs'], Decimal('6420.00'))
        # X24: unit 6 excluded - the others bear its share
        units[5]['in_allocation'] = False
        shares = allocation_shares(units, 'measurement')
        self.assertEqual(shares[6], 0)
        self.assertAlmostEqual(sum(shares.values()), Decimal(1))
        self.assertEqual(shares[1], Decimal('64.20') / Decimal('346.00'))
        units[5]['in_allocation'] = True
        # X25: apartments gross, commercial unit with option net
        units[5]['vat_deductible'] = True
        result = compute_allocation(
            [{'net': Decimal('100000'), 'tax': Decimal('19000'),
                    'maintenance_mode': 'amount',
                    'maintenance_value': Decimal('10000'), 'unit': None}],
            [], units, 'standard_559', 'measurement', rule)
        self.assertEqual(result[1]['costs'], Decimal('18190.00'))
        self.assertEqual(result[1]['maintenance'], Decimal('1819.00'))
        self.assertEqual(result[6]['costs'], Decimal('17619.05'))
        self.assertEqual(result[6]['maintenance'], Decimal('1761.90'))
        # equal key
        self.assertEqual(allocation_shares(units, 'equal')[2],
            Decimal(1) / 6)
        # measurement / manual: windows 4, 5, 4, 5, 6, 6 = 30
        for unit, windows in zip(units, [4, 5, 4, 5, 6, 6]):
            unit['quantity'] = Decimal(windows)
        for key in ['measurement', 'manual']:
            shares = allocation_shares(units, key)
            self.assertEqual(shares[1], Decimal(4) / 30)
            self.assertEqual(shares[5], Decimal(6) / 30)
        result = compute_allocation(
            [{'net': Decimal('30000'), 'tax': 0,
                    'maintenance_mode': 'none', 'unit': None}],
            [], [dict(u, vat_deductible=False) for u in units],
            'standard_559', 'manual', rule)
        self.assertEqual(result[1]['costs'], Decimal('4000.00'))
        self.assertEqual(result[5]['costs'], Decimal('6000.00'))
        # excluded unit: the others share its quantity
        units[5]['in_allocation'] = False
        self.assertEqual(allocation_shares(units, 'manual')[5],
            Decimal(6) / 24)

    def test_modernisation_deadlines(self):
        "Hardship objection / special termination: end of next month"
        from trytond.modules.real_estate.rent_adjustment.modernisation import (
            _end_of_next_month)
        self.assertEqual(_end_of_next_month(datetime.date(2026, 10, 15)),
            datetime.date(2026, 11, 30))
        self.assertEqual(_end_of_next_month(datetime.date(2026, 12, 31)),
            datetime.date(2027, 1, 31))
        self.assertEqual(_end_of_next_month(datetime.date(2027, 1, 1)),
            datetime.date(2027, 2, 28))
        self.assertIsNone(_end_of_next_month(None))

    def test_modernisation_letter_template(self):
        "Announcement renders the mandatory contents (§ 555c BGB)"
        import io
        import os
        import re
        import zipfile

        from relatorio.templates.opendocument import Template

        address = _StubRecord(street_single_line='Musterstraße 1',
            postal_code='14163', city='Berlin')
        company = _StubRecord(party=_StubRecord(name='Immo GmbH',
                addresses=[address]))
        measure = _StubRecord(company=company,
            property=_StubRecord(address=address),
            rec_name='MOD-2026-0001 Fassade',
            announcement_date=datetime.date(2026, 10, 30),
            description='Wärmedämmung der Fassade',
            energy_saving_note='Pauschalwerte U-Wert',
            planned_start=datetime.date(2027, 3, 1),
            planned_duration='3 Monate',
            expected_operating_costs='keine Änderung')
        records = [_StubRecord(id=i, modernisation=measure,
                contract=_StubRecord(contract_number='1-20-191'),
                object=_StubRecord(name='Wohnung 01', address=address),
                announced_increase=Decimal('122.29'),
                expected_increase=None,
                hardship_deadline=datetime.date(2026, 11, 30),
                special_termination_deadline=datetime.date(2026, 11, 30))
            for i in (1, 2)]
        tenant = _StubRecord(full_name='Rudi Völler', name='Rudi Völler')
        path = os.path.join(os.path.dirname(__file__), '..', 'report',
            'modernisation_announcement_de.odt')
        data = Template(source=None, filepath=path).generate(
            records=records, datetime=datetime, format_value=str,
            marks={1: '', 2: ''},
            tenants={1: [(tenant, address)], 2: [(tenant, address)]},
            measure_labels={1: ['Nr. 1'], 2: ['Nr. 1']},
            areas={1: Decimal('64.20'), 2: None},
            ).render().getvalue()
        with zipfile.ZipFile(io.BytesIO(data)) as odt:
            content = odt.read('content.xml').decode()
        self.assertIn('text:style-name="PBreak"', content)
        text = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', content))
        for expected in ['Rudi Völler', 'Ankündigung einer Modernisierung',
                'Wärmedämmung der Fassade', '2027-03-01', '3 Monate',
                '122.29', '1.90', '64.20', 'keine Änderung', '2026-11-30', '§ 555e',
                'Pauschalwerte']:
            self.assertIn(expected, text)

    def test_modernisation_effective_date(self):
        "Effective date, extension and deadlines of the increase (6.5, 6.6)"
        from trytond.modules.real_estate.rent_adjustment.contract_modernisation import (
            extension_reason, modernisation_valid_from, previous_increases,
            termination_deadline)
        # receipt 15.03. -> start of the third month 01.06.
        self.assertEqual(modernisation_valid_from(
                datetime.date(2027, 3, 15)), datetime.date(2027, 6, 1))
        self.assertEqual(modernisation_valid_from(
                datetime.date(2027, 3, 15), True),
            datetime.date(2027, 12, 1))
        self.assertIsNone(modernisation_valid_from(None))
        receipt = datetime.date(2026, 11, 2)
        ten = Decimal(10)
        # announced correctly, increase within 110 %
        self.assertIsNone(extension_reason(False, True, receipt, False,
                Decimal('130.00'), Decimal('122.29'), ten))
        self.assertEqual(extension_reason(False, True, receipt, False,
                Decimal('140.00'), Decimal('122.29'), ten), 'exceeded')
        self.assertEqual(extension_reason(False, False, None, False,
                Decimal('10'), None, ten), 'missing')
        self.assertEqual(extension_reason(False, True, None, False,
                Decimal('10'), Decimal('10'), ten), 'missing')
        self.assertEqual(extension_reason(False, True, receipt, True,
                Decimal('10'), Decimal('10'), ten), 'defective')
        # trivial measure without announcement is in order
        self.assertIsNone(extension_reason(True, False, None, False,
                Decimal('10'), None, ten))
        # previous increases within 6 years before the effective date
        history = [
            (datetime.date(2020, 1, 1), Decimal('30'), False),
            (datetime.date(2022, 6, 1), Decimal('20'), False),
            (datetime.date(2024, 1, 1), Decimal('15'), True),
            ]
        self.assertEqual(previous_increases(history,
                datetime.date(2027, 1, 1), 6),
            (Decimal('35'), Decimal('15')))
        # special termination § 561: end of the second month after receipt
        self.assertEqual(termination_deadline(datetime.date(2027, 3, 15)),
            datetime.date(2027, 5, 31))

    def test_modernisation_increase_letter_template(self):
        "Increase declaration renders the mandatory contents (spec 8.2)"
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
        measure = _StubRecord(rec_name='MOD-2026-0001 Fassade',
            announcement_date=datetime.date(2026, 10, 30),
            actual_end=datetime.date(2027, 5, 31),
            description='Wärmedämmung der Fassade',
            energy_saving_note=None, variant='standard_559',
            allocation_key='measurement', allocation_note='nach Wohnfläche',
            allocation_m_type=_StubRecord(rec_name='Wohnfläche'),
            funds=[_StubRecord(kind='grant', source='BEG EM',
                    amount=Decimal('15000'))])
        cost = _StubRecord(description='Fassade', amount=Decimal('180000'),
            tax_amount=Decimal('0'), maintenance_mode='percent',
            maintenance_value=Decimal('25'))
        unit = _StubRecord(object=_StubRecord(name='Wohnung 01',
                address=address))
        records = [_StubRecord(id=i, contract=contract,
                declaration_date=datetime.date(2027, 6, 15),
                amount_old=Decimal('566.24'),
                planned_amount=Decimal('688.53'),
                planned_valid_from=datetime.date(2027, 9, 1),
                modernisation_costs=Decimal('27514.29'),
                modernisation_allocable=Decimal('18342.86'),
                modernisation_annual=Decimal('1467.43'),
                modernisation_monthly=Decimal('122.29'),
                modernisation_cap=Decimal('192.60'),
                modernisation_area=Decimal('64.20'),
                modernisation_previous=Decimal('0'),
                modernisation_extension=None)
            for i in (1, 2)]
        info = {'measure': measure, 'unit': unit, 'types': ['Nr. 1'],
            'key': 'Bemessung', 'variant': 'Standard (§ 559, 8 %)',
            'costs': [cost], 'gross': True, 'rate': Decimal('8'),
            'cap_rate': Decimal('3.00')}
        tenant = _StubRecord(full_name='Rudi Völler', name='Rudi Völler')
        path = os.path.join(os.path.dirname(__file__), '..', 'report',
            'modernisation_increase_de.odt')
        data = Template(source=None, filepath=path).generate(
            records=records, datetime=datetime, format_value=str,
            format_percent=str, marks={1: '', 2: ''},
            tenants={1: [(tenant, address)], 2: [(tenant, address)]},
            measures={1: info, 2: info},
            termination_until={1: datetime.date(2027, 8, 31), 2: None},
            ).render().getvalue()
        with zipfile.ZipFile(io.BytesIO(data)) as odt:
            content = odt.read('content.xml').decode()
        self.assertIn('text:style-name="PBreak"', content)
        text = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', content))
        for expected in ['Rudi Völler', 'Mieterhöhung nach Modernisierung',
                '2026-10-30', 'Wärmedämmung der Fassade', 'Fassade',
                '180000', '25 %', 'BEG EM', 'nach Wohnfläche',
                '18342.86', '1467.43', '122.29', '566.24', '688.53',
                '2027-09-01', '§ 561', '2027-08-31', 'brutto']:
            self.assertIn(expected, text)

    def test_modernisation_planned_values(self):
        "What-if: planned classes and features replace the assignments"
        from types import SimpleNamespace

        from trytond.modules.real_estate.rent_adjustment.rent_survey import apply_planned

        def value(kind, dimension=None, class_=None, feature=None):
            return SimpleNamespace(kind=kind, dimension_code=dimension,
                class_code=class_, feature_code=feature, evidence=None)
        values = [
            value('class', 'energy', 'high'),
            value('class', 'location', 'medium'),
            value('feature', feature='bath_old'),
            value('feature', feature='balcony'),
            ]
        planned = [
            {'kind': 'class', 'action': 'add', 'dimension_code': 'energy',
                'class_code': 'low', 'feature_code': None},
            {'kind': 'feature', 'action': 'remove', 'dimension_code': None,
                'class_code': None, 'feature_code': 'bath_old'},
            {'kind': 'feature', 'action': 'add', 'dimension_code': None,
                'class_code': None, 'feature_code': 'heating_modern'},
            {'kind': 'feature', 'action': 'add', 'dimension_code': None,
                'class_code': None, 'feature_code': 'balcony'},
            ]
        result = apply_planned(values, planned)
        classes = [(v.dimension_code, v.class_code) for v in result
            if v.kind == 'class']
        features = [v.feature_code for v in result if v.kind == 'feature']
        # the planned class replaces the class of its dimension and comes
        # first; other dimensions stay
        self.assertEqual(classes, [('energy', 'low'),
                ('location', 'medium')])
        self.assertNotIn('bath_old', features)
        self.assertIn('heating_modern', features)
        # an existing feature planned again is kept once
        self.assertEqual(features.count('balcony'), 1)
        # without planned values nothing changes
        self.assertEqual(apply_planned(values, []), values)

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
