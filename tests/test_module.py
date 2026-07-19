
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


class RealEstateTestCase(ModuleTestCase):
    "Test Real Estate module"
    module = 'real_estate'

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


del ModuleTestCase
