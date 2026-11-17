"Module tests of the area core (part of RealEstateTestCase)"
import datetime
from decimal import Decimal

from trytond.pool import Pool
from trytond.tests.test_tryton import with_transaction


class CoreTests:
    "Tests of the area core, mixed into RealEstateTestCase"

    @with_transaction()
    def test_posted_invoice_line_assignment_locked(self):
        "Posted invoice: assignment of the invoice and move lines locked"
        from trytond.model.exceptions import AccessError
        from trytond.modules.account.tests import (
            create_chart, get_fiscalyear)
        from trytond.modules.account_invoice.tests import (
            set_invoice_sequences)
        from trytond.modules.company.tests import create_company, set_company

        pool = Pool()
        Account = pool.get('account.account')
        FiscalYear = pool.get('account.fiscalyear')
        Party = pool.get('party.party')
        Invoice = pool.get('account.invoice')
        InvoiceLine = pool.get('account.invoice.line')
        Journal = pool.get('account.journal')
        MoveLine = pool.get('account.move.line')
        BaseObject = pool.get('real_estate.base_object')

        # The client shows the fields read-only once posted
        for Model in [InvoiceLine, MoveLine]:
            for name in [
                    'assignment_control', 'contract', 'term', 'base_object']:
                self.assertIn('readonly', Model._fields[name].states,
                    msg='%s.%s' % (Model.__name__, name))

        company = create_company()
        with set_company(company):
            create_chart(company)
            fiscalyear = set_invoice_sequences(get_fiscalyear(company,
                    today=datetime.date(2025, 1, 1)))
            fiscalyear.save()
            FiscalYear.create_period([fiscalyear])
            expense, = Account.search([
                    ('type.expense', '=', True),
                    ('company', '=', company.id),
                    ], limit=1)
            payable, = Account.search([
                    ('type.payable', '=', True),
                    ('party_required', '=', True),
                    ('company', '=', company.id),
                    ], limit=1)
            supplier = Party(name="Reinigung Müller", addresses=[{}])
            supplier.save()
            prop, other = BaseObject.create([{
                        'name': name, 'type': 'property',
                        'sequence': sequence, 'company': company.id,
                        'start_date': datetime.date(2025, 1, 1)}
                    for name, sequence in [('P', 10), ('Q', 20)]])

            journal, = Journal.search([('code', '=', 'EXP')])
            invoice = Invoice(type='in', party=supplier, journal=journal,
                invoice_address=supplier.addresses[0], company=company,
                currency=company.currency, account=payable,
                invoice_date=datetime.date(2025, 3, 15))
            invoice.lines = [InvoiceLine(type='line', account=expense,
                    quantity=1, unit_price=Decimal('100.00'),
                    description="Hausreinigung", base_object=prop,
                    assignment_control='operating_costs')]
            invoice.save()
            Invoice.post([invoice])
            line, = invoice.lines
            move_line, = [l for l in invoice.move.lines
                if l.account == expense]
            self.assertEqual(move_line.base_object, prop)

            for values in [
                    {'base_object': other.id},
                    {'assignment_control': 'contract'}]:
                with self.assertRaises(AccessError):
                    InvoiceLine.write([line], values)
                with self.assertRaises(AccessError):
                    MoveLine.write([move_line], values)

    def test_party_sequence_function(self):
        "Sequence of a party: role number plus the digits of the code"
        from trytond.modules.real_estate.core.party import party_sequence

        self.assertEqual(party_sequence(700000, '42'), 700042)
        self.assertEqual(party_sequence(40000, 'K-42'), 40042)
        # No check of the range: plain addition
        self.assertEqual(party_sequence(10000, '10000'), 20000)
        self.assertIsNone(party_sequence(40000, 'ABC'))
        self.assertIsNone(party_sequence(40000, None))
        self.assertIsNone(party_sequence(None, '42'))

    @with_transaction()
    def test_party_role_number(self):
        "Party role number: sequence computed on create and write"
        pool = Pool()
        Party = pool.get('party.party')
        RoleNumber = pool.get('real_estate.party.role_number')
        ModelData = pool.get('ir.model.data')

        # Standard data
        supplier = RoleNumber(ModelData.get_id(
                'real_estate', 'party_role_number_supplier'))
        self.assertEqual(supplier.number, 40000)
        self.assertEqual(
            sorted(r.number for r in RoleNumber.search([])),
            [10000, 20000, 30000, 40000, 50000, 90000])

        role, = RoleNumber.create([{'name': 'Lieferant', 'number': 700000}])
        other, = RoleNumber.create([{'name': 'Kunde', 'number': 100000}])

        # T1: create with role
        party, = Party.create([{
                    'name': 'L', 'code': '42', 'role_number': role.id}])
        self.assertEqual(party.sequence, 700042)
        # code from the sequence of the party configuration
        auto, = Party.create([{'name': 'A', 'role_number': role.id}])
        self.assertEqual(auto.sequence, 700000 + auto.code_digit)

        # T2: without role the sequence stays as entered
        manual, = Party.create([{'name': 'M', 'code': '43', 'sequence': 7}])
        self.assertEqual(manual.sequence, 7)
        Party.write([manual], {'name': 'M2'})
        self.assertEqual(manual.sequence, 7)
        Party.write([manual], {'sequence': 8})
        self.assertEqual(manual.sequence, 8)

        # T3: set, change, remove the role; change the code
        Party.write([manual], {'role_number': role.id})
        self.assertEqual(manual.sequence, 700043)
        Party.write([manual], {'role_number': other.id})
        self.assertEqual(manual.sequence, 100043)
        Party.write([manual], {'code': 'K-44'})
        self.assertEqual(manual.sequence, 100044)
        # a sequence written by hand is overruled while the role is set
        Party.write([manual], {'sequence': 5})
        self.assertEqual(manual.sequence, 100044)
        Party.write([manual], {'role_number': None})
        self.assertIsNone(manual.sequence)

        # T4: a changed number does not recompute existing parties
        RoleNumber.write([role], {'number': 800000})
        self.assertEqual(Party(party.id).sequence, 700042)
        Party.write([party], {'code': '45'})
        self.assertEqual(party.sequence, 800045)

        # T5: code without digits
        Party.write([party], {'code': 'ABC'})
        self.assertIsNone(party.sequence)

        # on_change in the client
        party.code = '46'
        party.role_number = other
        party.on_change_role_number()
        self.assertEqual(party.sequence, 100046)
        party.role_number = None
        party.on_change_role_number()
        self.assertIsNone(party.sequence)
