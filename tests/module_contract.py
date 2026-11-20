"Module tests of the area contract (part of RealEstateTestCase)"
import datetime
from decimal import Decimal

from trytond.model.exceptions import ValidationError
from trytond.modules.real_estate.tests.common import (
    _StubNamed, _StubRecord, _StubSettlementUnit, _stub_contract, _stub_term)
from trytond.pool import Pool
from trytond.tests.test_tryton import with_transaction


class ContractTests:
    "Tests of the area contract, mixed into RealEstateTestCase"

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
    def test_contract_type_mark_translated(self):
        "mark/oc_mark of the contract types in English and German (O4)"
        import os
        from trytond.modules.real_estate.contract.contract_core import (
            partner_text)
        from trytond.transaction import Transaction
        pool = Pool()
        ModelData = pool.get('ir.model.data')
        Lang = pool.get('ir.lang')
        Translation = pool.get('ir.translation')
        ContractType = pool.get('real_estate.contract.type')
        german, = Lang.search([('code', '=', 'de')])
        Lang.write([german], {'translatable': True})
        Translation.translation_import('de', 'real_estate', os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                'locale', 'de.po'))
        texts = {
            'contract_rental_agreement_type': (
                'Rent Invoice', 'Mietrechnung',
                'Operating Cost Settlement', 'Betriebskostenabrechnung'),
            'contract_parking_space_lease_agreement_type': (
                'Rent Invoice', 'Mietrechnung',
                'Operating Cost Settlement', 'Betriebskostenabrechnung'),
            'contract_debit_costs_agreement_type': (
                'Invoice', 'Rechnung',
                'Operating Cost Settlement', 'Betriebskostenabrechnung'),
            'contract_credit_costs_agreement_type': (
                'Invoice', 'Rechnung', 'Operating Costs', 'Betriebskosten'),
            'contract_commercial_lease_agreement_type': (
                'Rent Invoice', 'Mietrechnung',
                'Operating Cost Settlement', 'Betriebskostenabrechnung'),
            'contract_condominium_fee_agreement_type': (
                'Condominium Fee', 'Hausgeld',
                'Condominium Fee Settlement', 'Hausgeldabrechnung'),
            }
        for fs_id, (mark_en, mark_de, oc_en, oc_de) in texts.items():
            db_id = ModelData.get_id('real_estate', fs_id)
            with Transaction().set_context(language='en'):
                c_type = ContractType(db_id)
                self.assertEqual((c_type.mark, c_type.oc_mark),
                    (mark_en, oc_en), fs_id)
            with Transaction().set_context(language='de'):
                c_type = ContractType(db_id)
                self.assertEqual((c_type.mark, c_type.oc_mark),
                    (mark_de, oc_de), fs_id)

        # invoice texts in the language of the contract partner, also
        # when the context has another language (cron)
        db_id = ModelData.get_id('real_estate', 'contract_rental_agreement_type')
        with Transaction().set_context(language='en'):
            c_type = ContractType(db_id)
            contract = _StubRecord(contractual_partner=_StubRecord(
                    lang=german))
            self.assertEqual(partner_text(contract, c_type, 'mark'),
                'Mietrechnung')
            self.assertEqual(partner_text(contract, c_type, 'oc_mark'),
                'Betriebskostenabrechnung')
            contract = _StubRecord(contractual_partner=_StubRecord(lang=None))
            self.assertEqual(partner_text(contract, c_type, 'mark'),
                'Rent Invoice')

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

    def test_amount_sign_violated(self):
        "Term amount sign: any / positive only / negative only, 0 allowed"
        from trytond.modules.real_estate.contract.contract_term import (
            amount_sign_violated)

        for sign in ('any', 'positive', 'negative', None):
            self.assertFalse(amount_sign_violated(sign, Decimal(0)))
        self.assertFalse(amount_sign_violated('any', Decimal('-50')))
        self.assertFalse(amount_sign_violated('any', Decimal('50')))
        self.assertFalse(amount_sign_violated('positive', Decimal('50')))
        self.assertTrue(amount_sign_violated('positive', Decimal('-0.01')))
        self.assertFalse(amount_sign_violated('negative', Decimal('-50')))
        self.assertTrue(amount_sign_violated('negative', Decimal('0.01')))

    @with_transaction()
    def test_term_amount_sign_check(self):
        "Saving a term checks the amount sign of its term type"
        from types import SimpleNamespace
        pool = Pool()
        ContractTerm = pool.get('real_estate.contract.term')
        TermType = pool.get('real_estate.contract.term.type')

        reduction, = TermType.search([('sequence', '=', 1010)])
        rent, = TermType.search([('sequence', '=', 1000)])
        self.assertEqual(reduction.amount_sign, 'negative')
        self.assertEqual(rent.amount_sign, 'positive')

        def term(term_type, quantity, unit_price):
            return SimpleNamespace(term_type=term_type, quantity=quantity,
                unit_price=unit_price, rec_name='T')

        # allowed: negative reduction, positive rent, 0 for both
        ContractTerm._check_amount_sign([
                term(reduction, Decimal(1), Decimal('-50')),
                term(rent, Decimal(1), Decimal('800')),
                term(reduction, Decimal(1), Decimal(0)),
                term(rent, Decimal(0), Decimal('800')),
                ])
        with self.assertRaises(ValidationError):
            ContractTerm._check_amount_sign([
                    term(reduction, Decimal(1), Decimal('50'))])
        with self.assertRaises(ValidationError):
            ContractTerm._check_amount_sign([
                    term(rent, Decimal(1), Decimal('-800'))])
        # the sign of the product counts (negative quantity)
        with self.assertRaises(ValidationError):
            ContractTerm._check_amount_sign([
                    term(rent, Decimal(-1), Decimal('800'))])
