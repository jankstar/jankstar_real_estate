"Module tests of the area base (part of RealEstateTestCase)"
import datetime
from decimal import Decimal

from trytond.model.exceptions import ValidationError
from trytond.modules.real_estate.tests.common import _StubRecord
from trytond.pool import Pool
from trytond.tests.test_tryton import with_transaction


class BaseTests:
    "Tests of the area base, mixed into RealEstateTestCase"

    def test_tight_market_validity(self):
        "Tight housing market only within the regulation's validity"
        from trytond.modules.real_estate.base.base_object import BaseObject

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
    def test_base_object_hierarchy(self):
        "Object number and property set on the server, also for subtrees"
        from trytond.modules.company.tests import create_company, set_company

        pool = Pool()
        BaseObject = pool.get('real_estate.base_object')
        UseClass = pool.get('real_estate.use_class')
        start = datetime.date(2025, 1, 1)

        company = create_company()
        with set_company(company):
            use_class, = UseClass.search([], limit=1)
            values = {'company': company.id, 'start_date': start}
            p1, p2 = BaseObject.create([
                    dict(values, name='P1', type='property', sequence=10),
                    dict(values, name='P2', type='property', sequence=20),
                    ])
            building, = BaseObject.create([dict(values, name='B',
                        type='building', sequence=10, parent=p1.id)])
            flat, = BaseObject.create([dict(values, name='W',
                        type='object', sequence=10, parent=building.id,
                        type_of_use='residential', use_class=use_class.id)])
            self.assertEqual(
                [(o.object_number, o.property)
                    for o in BaseObject.browse([p1, building, flat])],
                [('10', None), ('10/10', p1), ('10/10/10', p1)])

            # Moving the building moves the whole subtree
            BaseObject.write([building], {'parent': p2.id, 'sequence': 30})
            self.assertEqual(
                [(o.object_number, o.property)
                    for o in BaseObject.browse([building, flat])],
                [('20/30', p2), ('20/30/10', p2)])
            self.assertEqual(
                {o.property for o in BaseObject(flat.id).occupancy}, {p2})
            BaseObject.write([p2], {'sequence': 40})
            self.assertEqual(BaseObject(flat.id).object_number, '40/30/10')

            # Equipment directly below the property (domain of parent)
            equipment, = BaseObject.create([dict(values, name='E',
                        type='equipment', e_type='structure', sequence=10,
                        parent=p1.id)])
            self.assertEqual(
                (equipment.object_number, equipment.property), ('10/10', p1))

            # The sequence of a property is unique within the company
            with self.assertRaises(ValidationError):
                BaseObject.create([dict(values, name='P3',
                            type='property', sequence=10)])
            BaseObject.write([p1], {'active': False})
            with self.assertRaises(ValidationError):
                BaseObject.create([dict(values, name='P3',
                            type='property', sequence=10)])
            new = BaseObject(company=company, type='property',
                sequence=None, parent=None)
            self.assertEqual(new.on_change_with_sequence(), 50)

        other = create_company()
        with set_company(other):
            BaseObject.create([dict(values, company=other.id, name='P',
                        type='property', sequence=10)])

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
