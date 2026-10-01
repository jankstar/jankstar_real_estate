import datetime

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

del ModuleTestCase
