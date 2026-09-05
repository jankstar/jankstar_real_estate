import datetime
import unittest
from decimal import Decimal

from trytond.modules.real_estate import bved_records as bv


class BvedRecordsTestCase(unittest.TestCase):
    "Fixed-width pack/unpack round-trip for every BVED record type"

    def _round_trip(self, record_type, values):
        line = bv.pack(record_type, values)
        self.assertEqual(len(line), bv.RECORD_LENGTHS[record_type])
        parsed = bv.unpack(record_type, line)
        for key, expected in values.items():
            self.assertEqual(parsed[key], expected, key)
        return line, parsed

    def test_a_satz(self):
        self._round_trip('A', {
            'customer_number': 12345,
            'provider_key': '40',
            'provider_reference': 1000000001,
            'internal_reference': 'OBJ-1',
        })

    def test_l_satz(self):
        line, parsed = self._round_trip('L', {
            'customer_number': 12345,
            'provider_key': '40',
            'provider_reference': 100000000,
            'vat_flag': 3,
            'street': 'Musterstraße 1',
            'country': 'DEU',
            'postal_code': '14163',
            'city': 'Berlin',
            'period_start': datetime.date(2025, 1, 1),
            'period_end': datetime.date(2025, 12, 31),
            'total_area': Decimal('3500.00'),
            'co2_landlord_share_percent': 50,
        })
        self.assertEqual(parsed['satzart'], 'L')
        self.assertEqual(parsed['satzende'], 'L')

    def test_m_satz(self):
        self._round_trip('M', {
            'customer_number': 12345,
            'provider_key': '40',
            'provider_reference': 100000001,
            'internal_reference': 'OBJ-1',
            'address_flag': 1,
            'tenant_name1': 'Mieter Eins',
            'tenant_street': 'Musterstraße 1',
            'tenant_postal_code': '14163',
            'tenant_city': 'Berlin',
            'occupancy_start': datetime.date(2025, 1, 1),
            'occupancy_end': datetime.date(2025, 12, 31),
            'heating_advance_gross': Decimal('420.00'),
            'vacancy_flag': 0,
            'tenant_change_fee_flag': 0,
            'bank_account_number': '1234567890',
            'bank_code': '10070000',
        })

    def test_b_satz(self):
        self._round_trip('B', {
            'customer_number': 12345,
            'provider_key': '40',
            'provider_reference': 100000000,
            'currency': 'EUR',
            'period_start': datetime.date(2025, 1, 1),
            'period_end': datetime.date(2025, 12, 31),
            'fuel_type': 111,
            'heating_value': Decimal('9.8000'),
            'stock_start_date': datetime.date(2025, 1, 1),
            'stock_start_quantity': Decimal('1200.500'),
            'stock_end_quantity': Decimal('800.250'),
            'fuel_indicator_flag': 1,
            'meter_number': 'Z-2025-0001',
            'consumption': Decimal('35.500'),
            'primary_energy_factor': Decimal('1.10'),
        })

    def test_k_satz(self):
        self._round_trip('K', {
            'customer_number': 12345,
            'provider_key': '40',
            'provider_reference': 100000000,
            'cost_type_key': 111,
            'uniform_cost_flag': 'E',
            'invoice_date': datetime.date(2025, 11, 25),
            'quantity': Decimal('3500.000'),
            'amount_gross': Decimal('3860.00'),
            'amount_net': Decimal('3243.70'),
            'tax_service_type_key': 13,
            'labor_share_amount': Decimal('500.00'),
            'fuel_indicator_flag': 1,
            'energy_source_1': '04',
            'energy_share_1': Decimal('99.9'),  # max representable: 2+1 Stellen
            'energy_emission_factor_1': Decimal('0.201'),
        })

    def test_d_satz(self):
        self._round_trip('D', {
            'customer_number': 12345,
            'provider_key': '40',
            'provider_reference': 100000001,
            'internal_reference': 'OBJ-1',
            'period_end_date': datetime.date(2025, 12, 31),
            'total_costs_gross': Decimal('1234.56'),
            'total_costs_net': Decimal('1037.44'),
            'advance_payment_gross': Decimal('1000.00'),
            'balance_gross': Decimal('234.56'),
            'cost_type_key': 234,
            'currency': 'EUR',
        })

    def test_e835_satz(self):
        self._round_trip('E835', {
            'sequence_number': 1,
            'provider_key': '40',
            'provider_reference': 'ABC',
            'internal_reference': 'OBJ-1',
            'cost_type_key': 67,
            'tax_service_type_key': 13,
            'total_invoice_amount_gross': Decimal('758.00'),
            'user_share_amount': Decimal('758.00'),
            'user_share_percent': Decimal('100.00'),
            'labor_share_total': Decimal('300.00'),
            'user_share_labor_amount': Decimal('300.00'),
            'period_end_date': datetime.date(2025, 12, 31),
        })

    def test_e898_satz(self):
        self._round_trip('E898', {
            'sequence_number': 1,
            'provider_key': '40',
            'provider_reference': 'ABC',
            'internal_reference': 'OBJ-1',
            'document_path': 'C:\\ABR\\2025\\OBJ-1.PDF',
            'document_sequence_number': 1,
            'period_end_date': datetime.date(2025, 12, 31),
            'document_type': 'HKA',
        })

    def test_p_satz(self):
        self._round_trip('P', {
            'customer_number': 12345,
            'provider_key': '40',
            'provider_reference': 100000001,
            'internal_reference': 'OBJ-1',
            'period_end_date': datetime.date(2025, 12, 31),
            'cost_type_key': 910,
            'total_amount_gross': Decimal('100.00'),
            'user_share_amount': Decimal('12.34'),
            'user_share_percent': Decimal('12.34'),
        })

    def test_negative_decimal_round_trip(self):
        line, parsed = self._round_trip('D', {
            'customer_number': 1,
            'provider_key': '40',
            'provider_reference': 1,
            'balance_gross': Decimal('-45.67'),
        })
        self.assertEqual(parsed['balance_gross'], Decimal('-45.67'))

    def test_as_selection_and_fuel_unit(self):
        selection = bv.as_selection(bv.TABLE_B)
        self.assertIn(('111', '111 - Leichtes Heizöl in Liter'), selection)
        self.assertEqual(bv.get_fuel_unit('111'), 'Liter')
        self.assertEqual(bv.get_fuel_unit('200'), '')

    def test_estg35a_mapping_complete(self):
        for value in ('', 'abs1', 'abs2', 'abs3'):
            self.assertIn(bv.ESTG35A_TO_TABLE_L[value], bv.TABLE_L)

    def test_filename_convention(self):
        when = datetime.datetime(2026, 9, 2, 10, 30, 15, 123000)
        name = bv.bved_filename('A', when)
        self.assertEqual(name, 'DTA310_20260902103015123.DAT')


if __name__ == '__main__':
    unittest.main()
