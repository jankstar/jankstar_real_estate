"Module tests of the area operating_costs (part of RealEstateTestCase)"
import datetime
from decimal import Decimal

from trytond.exceptions import UserWarning
from trytond.model.exceptions import ValidationError
from trytond.pool import Pool
from trytond.tests.test_tryton import with_transaction
from trytond.transaction import Transaction


class OperatingCostsTests:
    "Tests of the area operating_costs, mixed into RealEstateTestCase"

    @with_transaction()
    def test_external_value_shares_keep_planned_costs(self):
        "External billing: computing the value shares keeps the planned costs"
        from types import SimpleNamespace as NS
        from unittest.mock import patch
        pool = Pool()
        SettlementUnit = pool.get('real_estate.settlement_unit')
        CostShare = pool.get('real_estate.cost_share')

        for external in (True, False):
            su = NS(id=1, billing_unit=NS(external_billing=external),
                actual_costs_gross=Decimal('100'),
                actual_costs_gross_from_references=Decimal(0),
                planned_costs_gross=Decimal('500'),
                planned_costs_net=Decimal('420'),
                planned_costs_gross_from_references=Decimal(0),
                planned_costs_net_from_references=Decimal(0),
                save=lambda: None, _compute_heizkostenv_split=lambda: None)
            with patch.object(CostShare, 'search', return_value=[]):
                SettlementUnit._compute_value_shares_external(su)
            self.assertEqual(su.planned_costs_gross, Decimal('500'))
            self.assertEqual(su.planned_costs_net, Decimal('420'))

    @with_transaction()
    def test_oc_object_booked(self):
        "Documents booked on a rental object: assignment only to it (E32)"
        from types import SimpleNamespace as NS
        from trytond.modules.real_estate.operating_costs.oc_document import _other_level
        pool = Pool()
        Line = pool.get('real_estate.oc_document.line')

        prop = NS(type='property', rec_name='P')
        flat = NS(type='object', rec_name='Flat')
        other_flat = NS(type='object', rec_name='Other')
        building = NS(type='building', rec_name='B')
        # no document for another level than property / rental object
        self.assertFalse(_other_level(NS(base_object=prop)))
        self.assertFalse(_other_level(NS(base_object=flat)))
        self.assertFalse(_other_level(NS(base_object=None)))
        self.assertTrue(_other_level(NS(base_object=building)))

        contract = NS(items=[NS(objects=[flat])])
        foreign = NS(items=[NS(objects=[other_flat])])

        def line(target, obj, doc_contract=None, contract=None,
                base_object=None):
            doc = NS(rec_name='D', contract=doc_contract,
                object_booked=lambda: obj if obj.type == 'object' else None)
            return NS(document=doc, target=target, contract=contract,
                base_object=base_object)

        # allowed
        for l in (line('settlement_unit', flat),
                line('contract', flat, contract=contract),
                line('contract', flat, contract, contract, flat),
                line('property', prop)):
            Line.check_object_booked(l)
        # not allowed
        for l in (line('property', flat),
                line('contract', flat, contract=foreign),
                line('contract', flat, contract, foreign),
                line('contract', flat, contract=contract,
                    base_object=other_flat)):
            with self.assertRaises(ValidationError):
                Line.check_object_booked(l)

    def test_oc_reclass_distribute_groups(self):
        "Cost reclassification: groups split exactly to the cent"
        from trytond.modules.real_estate.operating_costs.oc_reclass import distribute_groups

        groups = {('8000', ()): Decimal('100.00'),
            ('8002', ()): Decimal('-10.00')}
        result = distribute_groups(groups, {1: 1, 2: 1, 3: 1, 4: 0})
        for key, amount in groups.items():
            self.assertEqual(
                sum(r.get(key, Decimal(0)) for r in result.values()), amount)
        self.assertEqual(result[1][('8000', ())], Decimal('33.34'))
        self.assertEqual(result[2][('8000', ())], Decimal('33.33'))
        self.assertEqual(result[4], {})
        self.assertEqual(result[1][('8002', ())], Decimal('-3.34'))
        # proportional to the weights
        result = distribute_groups({'g': Decimal('1000.00')},
            {'commercial': Decimal('0.3'), 'apartment': Decimal('0.7')})
        self.assertEqual(result['commercial']['g'], Decimal('300.00'))
        self.assertEqual(result['apartment']['g'], Decimal('700.00'))
        self.assertEqual(distribute_groups({'g': Decimal(1)}, {1: 0}),
            {1: {}})

    @with_transaction()
    def test_bved_k_values_from_assignment(self):
        "BVED K record from a confirmed assignment line (spec 6.6, 3.6)"
        from types import SimpleNamespace as NS
        Export = Pool().get('real_estate.bved.export')
        export = NS(provider=NS(bved_key='P1'),
            _provider_reference=lambda bu: 'REF')
        invoice = NS(invoice_date=datetime.date(2025, 11, 25))
        line = NS(document=NS(invoice=invoice,
                date=datetime.date(2025, 11, 30)),
            amount_gross=Decimal('1190.00'), amount_net=Decimal('1000.00'),
            estg_35a='abs3', estg_35a_labor_share_percent=Decimal('40'),
            bved_fuel_quantity=Decimal('3500'), bved_fuel_type='01')
        su = NS(bved_cost_key='0310')
        values = Export._k_values(export, NS(), NS(customer_number='K1'),
            su, line)
        self.assertEqual((values['invoice_date'], values['amount_gross'],
                values['amount_net'], values['quantity'],
                values['tax_service_type_key'],
                values['labor_share_amount'], values['fuel_indicator_flag'],
                values['cost_type_key']),
            (datetime.date(2025, 11, 25), Decimal('1190.00'),
                Decimal('1000.00'), Decimal('3500'), '13',
                Decimal('476.00'), 1, '0310'))
        # manual posting without invoice: date of the posting, no § 35a
        line.document = NS(invoice=None, date=datetime.date(2025, 12, 31))
        line.estg_35a = ''
        line.estg_35a_labor_share_percent = None
        line.bved_fuel_type = ''
        values = Export._k_values(export, NS(), NS(customer_number='K1'),
            su, line)
        self.assertEqual((values['invoice_date'],
                values['tax_service_type_key'],
                values['labor_share_amount'], values['fuel_indicator_flag']),
            (datetime.date(2025, 12, 31), '00', None, 0))

    def test_oc_reconciliation_functions(self):
        "Reconciliation: distribution columns and account check (spec 8)"
        from trytond.modules.real_estate.operating_costs.oc_reconciliation import (
            account_check, distribution)
        # 119 gross / 100 net: flat 60 % gross (tenant), shop 40 % net
        # (vacancy) - completely distributed
        columns = distribution(Decimal('119.00'), Decimal(0), Decimal(0),
            [(Decimal('71.40'), False, True), (Decimal('40.00'), True,
                    False)], Decimal('119.00'), Decimal('100.00'))
        self.assertEqual(columns, {
                'tenants': Decimal('71.40'),
                'vacancy': Decimal('40.00'),
                'commercial_tax': Decimal('7.60'),
                'not_distributed': Decimal('0.00'),
                })
        # passed on: the source gives away, the target distributes more
        columns = distribution(Decimal('50.00'), Decimal(0),
            Decimal('-50.00'), [], Decimal(0), Decimal(0))
        self.assertEqual(columns['not_distributed'], Decimal('0.00'))
        # insurance 01.10.2025-30.09.2026, 1,200.00 booked in 2025:
        # 302.47 to the settlement unit 2025, 897.53 to 2026
        check = account_check(Decimal('1200.00'), Decimal('302.47'),
            Decimal(0), Decimal(0), Decimal(0), Decimal('897.53'),
            Decimal(0), Decimal(0))
        self.assertEqual(check['difference'], Decimal('0.00'))
        # 2026: reclassified without a booking in the period
        check = account_check(Decimal(0), Decimal('897.53'), Decimal(0),
            Decimal(0), Decimal(0), Decimal(0), Decimal('897.53'),
            Decimal(0))
        self.assertEqual((check['rest'], check['difference']),
            (Decimal('-897.53'), Decimal('0.00')))

    def test_oc_reclass_amounts(self):
        "Cost reclassification: example of the specification (6.5)"
        from trytond.modules.real_estate.operating_costs.oc_reclass import reclass_amounts

        rate_property = Decimal('0.3333')
        # commercial unit 30 %: 300 net, 57 VAT, charged at 100 %
        commercial = reclass_amounts(Decimal('300.00'),
            [('vat', Decimal('57.00'))], rate_property, 1)
        # apartment 70 %: 700 net, 133 VAT, charged at 0 %
        apartment = reclass_amounts(Decimal('700.00'),
            [('vat', Decimal('133.00'))], rate_property, 0)
        for amounts in (commercial, apartment):
            # every move is balanced
            self.assertEqual(
                amounts['credit_cost']
                + sum(t[1] for t in amounts['credit_taxes']),
                amounts['debit_cost']
                + sum(t[1] for t in amounts['debit_taxes']))
        self.assertEqual(commercial['credit_cost'], Decimal('338.00'))
        self.assertEqual(commercial['credit_taxes'][0][1], Decimal('19.00'))
        self.assertEqual(commercial['debit_cost'], Decimal('300.00'))
        self.assertEqual(commercial['debit_taxes'][0][1], Decimal('57.00'))
        self.assertEqual(apartment['credit_cost'], Decimal('788.67'))
        self.assertEqual(apartment['credit_taxes'][0][1], Decimal('44.33'))
        self.assertEqual(apartment['debit_cost'], Decimal('833.00'))
        self.assertEqual(apartment['debit_taxes'][0][1], Decimal('0.00'))
        # input tax of the invoice (63.33 at 33.33 %) after the
        # reclassification: exactly 19 % of the commercial share
        deducted = Decimal('63.33')
        for amounts in (commercial, apartment):
            deducted += (sum(t[1] for t in amounts['debit_taxes'])
                - sum(t[1] for t in amounts['credit_taxes']))
        self.assertEqual(deducted, Decimal('57.00'))

    def test_oc_distribute_and_split_by_days(self):
        "Operating cost assignment: exact cent split and day split"
        from trytond.modules.real_estate.operating_costs.oc_document import (
            distribute, split_by_days)

        self.assertEqual(distribute(Decimal('100.00'), [1, 1, 1]),
            [Decimal('33.33'), Decimal('33.33'), Decimal('33.34')])
        self.assertEqual(distribute(Decimal('10.00'), [0, 0]),
            [Decimal(0), Decimal(0)])
        self.assertEqual(distribute(Decimal('-7.00'), [50, 50]),
            [Decimal('-3.50'), Decimal('-3.50')])
        d = datetime.date
        self.assertEqual(split_by_days(d(2025, 7, 1), d(2026, 6, 30), [
                    ('a', d(2025, 1, 1), d(2025, 12, 31)),
                    ('b', d(2026, 1, 1), d(2026, 12, 31)),
                    ('c', d(2027, 1, 1), d(2027, 12, 31)),
                    ]), [
                ('a', d(2025, 7, 1), d(2025, 12, 31), 184),
                ('b', d(2026, 1, 1), d(2026, 6, 30), 181),
                ])

    @with_transaction()
    def test_oc_document_assignment(self):
        "Operating cost document: created on posting, proposed, confirmed, "
        "split by service period, locked by the billing unit"
        from trytond.model.exceptions import AccessError
        from trytond.modules.account.tests import (
            create_chart, get_fiscalyear)
        from trytond.modules.company.tests import create_company, set_company

        pool = Pool()
        Account = pool.get('account.account')
        Journal = pool.get('account.journal')
        Move = pool.get('account.move')
        Period = pool.get('account.period')
        FiscalYear = pool.get('account.fiscalyear')
        Party = pool.get('party.party')
        BaseObject = pool.get('real_estate.base_object')
        BillingUnit = pool.get('real_estate.billing_unit')
        SettlementUnit = pool.get('real_estate.settlement_unit')
        CostType = pool.get('real_estate.cost_type')
        Document = pool.get('real_estate.oc_document')

        company = create_company()
        with set_company(company):
            create_chart(company)
            for year in (2025, 2026):
                fiscalyear = get_fiscalyear(company,
                    today=datetime.date(year, 1, 1))
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
            journal, = Journal.search([('code', '=', 'EXP')])
            supplier = Party(name="Reinigung Müller")
            supplier.save()

            prop, = BaseObject.create([{'name': 'P', 'type': 'property',
                        'sequence': 10, 'company': company.id,
                        'start_date': datetime.date(2025, 1, 1)}])
            cost_type, = CostType.create([{'name': 'Hausreinigung',
                        'account': expense.id}])
            self.assertEqual(CostType(cost_type.id).account, expense)
            bu_2025, = BillingUnit.create([{'property': prop.id,
                        'description': 'Kalte BK',
                        'start_date': datetime.date(2025, 1, 1)}])
            su_2025, = SettlementUnit.create([{'billing_unit': bu_2025.id,
                        'type': cost_type.id, 'sequence': 10}])

            def post(date, amount, base_object=prop):
                period = Period.find(company, date=date)
                move = Move(journal=journal, period=period, date=date,
                    company=company)
                move.lines = [
                    {'account': expense.id, 'debit': amount,
                        'credit': Decimal(0), 'base_object':
                        base_object.id if base_object else None},
                    {'account': payable.id, 'debit': Decimal(0),
                        'credit': amount, 'party': supplier.id},
                    ]
                move.save()
                Move.post([move])
                return move

            # Posting creates the document (only the cost account line)
            post(datetime.date(2025, 3, 15), Decimal('120.00'))
            doc, = Document.search([])
            self.assertEqual((doc.property, doc.account, doc.state,
                    doc.amount_net, doc.amount_gross),
                (prop, expense, 'open', Decimal('120.00'),
                    Decimal('120.00')))
            # Without property: warning on posting (Z06), document
            # without property once confirmed
            with self.assertRaises(UserWarning):
                post(datetime.date(2025, 3, 16), Decimal('5.00'),
                    base_object=None)
            with Transaction().set_context(_skip_warnings=True):
                post(datetime.date(2025, 3, 16), Decimal('5.00'),
                    base_object=None)
            self.assertEqual(
                len(Document.search([('property', '=', None)])), 1)

            # Stage 1: account unique, one settlement unit
            Document.propose([doc])
            doc = Document(doc.id)
            self.assertEqual(doc.state, 'proposed')
            line, = doc.lines
            self.assertEqual((line.settlement_unit, line.amount_gross),
                (su_2025, Decimal('120.00')))
            Document.confirm([doc])
            self.assertEqual(Document(doc.id).state, 'confirmed')

            # Stage 2 (as last time) and split onto the next period
            BillingUnit.duplicate_next_period([bu_2025])
            su_2026, = SettlementUnit.search([('predecessor', '=', su_2025)])
            post(datetime.date(2025, 7, 1), Decimal('365.00'))
            doc2, = Document.search([('amount_net', '=', Decimal('365.00'))])
            Document.propose([doc2])
            doc2 = Document(doc2.id)
            self.assertEqual(doc2.lines[0].settlement_unit, su_2025)
            doc2.split_lines(datetime.date(2025, 7, 1),
                datetime.date(2026, 6, 30))
            doc2 = Document(doc2.id)
            self.assertEqual(
                sorted((l.settlement_unit.id, l.amount_net)
                    for l in doc2.lines),
                sorted([(su_2025.id, Decimal('184.00')),
                        (su_2026.id, Decimal('181.00'))]))
            self.assertEqual(doc2.state, 'proposed')

            # Locked once the billing unit is ready for billing
            BillingUnit.write([bu_2025], {'state': 'ready_for_billing'})
            with self.assertRaises(AccessError):
                Document.propose([doc2])
            with self.assertRaises(AccessError):
                Document.reset([Document(doc.id)])

    @with_transaction()
    def test_oc_billing_gross_net(self):
        "Settlement unit: actual costs gross/net from the confirmed "
        "assignment, distribution gross (0 %) / net (100 %) per object"
        from trytond.modules.account.tests import (
            create_chart, get_fiscalyear)
        from trytond.modules.company.tests import create_company, set_company

        pool = Pool()
        Account = pool.get('account.account')
        Journal = pool.get('account.journal')
        Move = pool.get('account.move')
        Period = pool.get('account.period')
        FiscalYear = pool.get('account.fiscalyear')
        BaseObject = pool.get('real_estate.base_object')
        UseClass = pool.get('real_estate.use_class')
        MeasurementType = pool.get('real_estate.measurement.type')
        Measurement = pool.get('real_estate.measurement')
        BillingUnit = pool.get('real_estate.billing_unit')
        SettlementUnit = pool.get('real_estate.settlement_unit')
        CostShare = pool.get('real_estate.cost_share')
        CostType = pool.get('real_estate.cost_type')
        Document = pool.get('real_estate.oc_document')
        start = datetime.date(2025, 1, 1)
        end = datetime.date(2025, 12, 31)

        company = create_company()
        with set_company(company):
            create_chart(company)
            fiscalyear = get_fiscalyear(company, today=start)
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
            journal, = Journal.search([('code', '=', 'EXP')])
            use_class, = UseClass.search([], limit=1)
            area, = MeasurementType.search([('sequence', '=', 10)])

            prop, = BaseObject.create([{'name': 'P', 'type': 'property',
                        'sequence': 10, 'company': company.id,
                        'start_date': start}])
            values = {'type': 'object', 'company': company.id,
                'parent': prop.id, 'start_date': start,
                'use_class': use_class.id}
            flat, shop = BaseObject.create([
                    dict(values, name='W', sequence=10,
                        type_of_use='residential', option_rate_method='fix_0'),
                    dict(values, name='G', sequence=20,
                        type_of_use='commercial',
                        option_rate_method='fix_100'),
                    ])
            # E15: a rental object only allows 0 % or 100 %
            with self.assertRaises(ValidationError):
                BaseObject.create([dict(values, name='X', sequence=30,
                            type_of_use='commercial',
                            option_rate_method='fix_value',
                            option_rate_value=Decimal(50))])
            Measurement.create([
                    {'base_object': flat.id, 'm_type': area.id,
                        'valid_from': start, 'value': 60.0},
                    {'base_object': shop.id, 'm_type': area.id,
                        'valid_from': start, 'value': 40.0},
                    ])
            cost_type, = CostType.create([{'name': 'Hausreinigung',
                        'account': expense.id}])
            bu, = BillingUnit.create([{'property': prop.id,
                        'description': 'Kalte BK', 'start_date': start}])
            su, = SettlementUnit.create([{'billing_unit': bu.id,
                        'type': cost_type.id, 'sequence': 10,
                        'allocation_rule': 'allocation_by_measurement',
                        'm_type': area.id}])
            CostShare.create([
                    {'settlement_unit': su.id, 'base_object': obj.id,
                        'start_date': start, 'end_date': end,
                        'state': 'selection'}
                    for obj in (flat, shop)])

            # Posting: net 100.00, gross 119.00 (invoice with tax)
            move = Move(journal=journal, company=company, date=start,
                period=Period.find(company, date=start))
            move.lines = [
                {'account': expense.id, 'debit': Decimal('100.00'),
                    'credit': Decimal(0), 'base_object': prop.id},
                {'account': payable.id, 'debit': Decimal(0),
                    'credit': Decimal('100.00'),
                    'party': company.party.id},
                ]
            move.save()
            Move.post([move])
            doc, = Document.search([])
            Document.write([doc], {'amount_gross': Decimal('119.00')})
            Document.propose([doc])

            # E16: a proposed document on the billing unit blocks
            with self.assertRaises(ValidationError):
                BillingUnit._check_oc_documents([bu])
            Document.confirm([Document(doc.id)])
            BillingUnit._check_oc_documents([bu])

            SettlementUnit(su.id).compute_value_shares()
            su = SettlementUnit(su.id)
            self.assertEqual((su.actual_costs_gross, su.actual_costs_net),
                (Decimal('119.00'), Decimal('100.00')))
            costs = {cs.base_object: cs.actual_costs
                for cs in CostShare.search([('settlement_unit', '=', su.id)])}
            # 60 % gross for the flat, 40 % net for the shop
            self.assertEqual(costs, {
                    flat: Decimal('71.40'),
                    shop: Decimal('40.00'),
                    })

            # Reconciliation (spec 8): distributed completely, not billed
            # yet - the costs are still on the property (pending)
            Reconciliation = pool.get('real_estate.oc_reconciliation')
            reconciliation, = Reconciliation.create([{
                        'company': company.id, 'property': prop.id,
                        'start_date': start}])
            Reconciliation.compute([reconciliation])
            reconciliation = Reconciliation(reconciliation.id)
            line, = [l for l in reconciliation.cost_lines
                if l.section == 'settlement_unit']
            self.assertEqual((line.assigned, line.vacancy,
                    line.commercial_tax, line.not_distributed),
                (Decimal('119.00'), Decimal('111.40'), Decimal('7.60'),
                    Decimal('0.00')))
            self.assertEqual(line.documents, (Document(doc.id),))
            self.assertEqual((reconciliation.booked, reconciliation.rest,
                    reconciliation.pending_booked,
                    reconciliation.difference),
                (Decimal('100.00'), Decimal('100.00'), Decimal('100.00'),
                    Decimal('0.00')))
            self.assertEqual(reconciliation.check_state, 'hints')
            self.assertIn(bu.rec_name, reconciliation.protocol)
            self.assertEqual(reconciliation.billing_units, (bu,))
            self.assertEqual(Reconciliation.search([
                        ('billing_units', '=', bu.id)]), [reconciliation])
            # report (phase 4b)
            Report = pool.get('real_estate.oc_reconciliation.report',
                type='report')
            ext, content, _, _ = Report.execute([reconciliation.id], {})
            self.assertEqual(ext, 'odt')
            self.assertTrue(content)
