"Module tests of the area tasks (part of RealEstateTestCase)"
import datetime
from decimal import Decimal

from trytond.exceptions import UserWarning
from trytond.model.exceptions import ValidationError
from trytond.modules.real_estate.tests.common import _StubRecord
from trytond.pool import Pool
from trytond.tests.test_tryton import with_transaction


class TasksTests:
    "Tests of the area tasks, mixed into RealEstateTestCase"

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
        from trytond.modules.real_estate.tasks.inspection import next_due_date
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
    def test_inspection_plan_copy_property(self):
        """Copy of a property: plans follow the copied property and
        buildings, no billing units, next free sequence"""
        from trytond.modules.company.tests import create_company, set_company

        pool = Pool()
        BaseObject = pool.get('real_estate.base_object')
        Type = pool.get('real_estate.inspection.type')
        Plan = pool.get('real_estate.inspection.plan')
        BillingUnit = pool.get('real_estate.billing_unit')

        company = create_company()
        with set_company(company):
            prop, = BaseObject.create([{'name': 'P', 'type': 'property',
                        'sequence': 1, 'company': company.id,
                        'start_date': datetime.date(2025, 1, 1)}])
            building, = BaseObject.create([{'name': 'B', 'type': 'building',
                        'sequence': 1, 'company': company.id,
                        'parent': prop.id,
                        'start_date': datetime.date(2025, 1, 1)}])
            BillingUnit.create([{'property': prop.id,
                        'description': 'Kalte BK',
                        'start_date': datetime.date(2025, 1, 1)}])
            type_building, type_property = Type.create([
                    {'name': 'Walk', 'code': 'walk', 'scope': 'building'},
                    {'name': 'Roof', 'code': 'roof', 'scope': 'property'},
                    ])
            values = {'company': company.id, 'interval': 1,
                'interval_unit': 'year', 'interval_basis': 'fixed',
                'next_due_date': datetime.date(2027, 4, 1)}
            Plan.create([
                    dict(values, type=type_building.id,
                        building=building.id),
                    dict(values, type=type_property.id,
                        property=prop.id),
                    ])

            new_prop, = BaseObject.copy([prop])
            self.assertEqual(new_prop.sequence, 10)
            self.assertEqual(new_prop.billing_units, ())
            self.assertEqual(len(prop.billing_units), 1)
            new_building, = new_prop.children
            self.assertEqual(new_building.sequence, 1)
            self.assertEqual(
                [(p.type, p.building) for p in Plan.search(
                        [('property', '=', prop.id)],
                        order=[('id', 'ASC')])],
                [(type_building, building), (type_property, None)])
            self.assertEqual(
                [(p.type, p.building) for p in Plan.search(
                        [('property', '=', new_prop.id)],
                        order=[('id', 'ASC')])],
                [(type_building, new_building), (type_property, None)])

            # Copy of a building alone: plan on the copy, same property
            building2, = BaseObject.copy([building],
                default={'sequence': 2})
            plan, = building2.building_inspection_plans
            self.assertEqual(plan.property, prop)

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
            # Defect of an approved inspection: only the follow-up fields
            # can change (the state only by the buttons - readonly)
            with self.assertRaises(AccessError):
                Defect.check_modification('write', [defect],
                    values={'description': 'x'}, external=True)
            Defect.check_modification('write', [defect],
                values={'deadline': datetime.date(2026, 12, 31)},
                external=True)
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
    def test_year_end_closing_process(self):
        "Year-end closing: process on the fiscal year and its done checks"
        from trytond.modules.account.tests import (
            create_chart, get_fiscalyear)
        from trytond.modules.company.tests import create_company, set_company

        pool = Pool()
        Account = pool.get('account.account')
        FiscalYear = pool.get('account.fiscalyear')
        Journal = pool.get('account.journal')
        Move = pool.get('account.move')
        Period = pool.get('account.period')
        ModelData = pool.get('ir.model.data')
        Process = pool.get('real_estate.process')
        Template = pool.get('real_estate.process.template')

        company = create_company()
        with set_company(company):
            create_chart(company)
            fiscalyear = get_fiscalyear(company,
                today=datetime.date(2025, 1, 1))
            fiscalyear.save()
            FiscalYear.create_period([fiscalyear])
            template = Template(ModelData.get_id(
                    'real_estate', 'process_template_year_end_closing'))
            process = Process.start(template, fiscalyear)

            # the company comes from the fiscal year, the group
            # 'Accounting' is responsible, due dates from the year end
            self.assertEqual(process.company, company)
            self.assertEqual(process.anchor_date, datetime.date(2025, 12, 31))
            account_group = ModelData.get_id('account', 'group_account')
            self.assertTrue(process.tasks)
            self.assertTrue(all(t.responsible_group.id == account_group
                    for t in process.tasks))
            self.assertIn(process, fiscalyear.processes_open)

            def done(name):
                return getattr(Process(process.id), f'_step_done_{name}')()

            self.assertTrue(done('fiscalyear_no_drafts'))
            self.assertTrue(done('fiscalyear_oc_documents_confirmed'))
            # no contract of the company - nothing left to post
            self.assertTrue(done('fiscalyear_contract_moves_posted'))
            self.assertTrue(done('fiscalyear_income_balanced'))

            # following fiscal year
            self.assertFalse(done('fiscalyear_next_exists'))
            following = get_fiscalyear(company,
                today=datetime.date(2026, 1, 1))
            following.save()
            self.assertTrue(done('fiscalyear_next_exists'))

            # a draft move with an income statement account
            expense, = Account.search([
                    ('type.expense', '=', True),
                    ('company', '=', company.id),
                    ], limit=1)
            payable, = Account.search([
                    ('type.statement', '=', 'balance'),
                    ('type.receivable', '=', False),
                    ('type.payable', '=', False),
                    ('party_required', '=', False),
                    ('closed', '!=', True),
                    ('company', '=', company.id),
                    ], limit=1)
            journal, = Journal.search([('code', '=', 'EXP')])
            period, = Period.search([
                    ('fiscalyear', '=', fiscalyear.id),
                    ('start_date', '=', datetime.date(2025, 3, 1)),
                    ])
            move, = Move.create([{
                        'journal': journal.id,
                        'period': period.id,
                        'date': datetime.date(2025, 3, 15),
                        'lines': [('create', [
                                    {'account': expense.id,
                                        'debit': Decimal(100)},
                                    {'account': payable.id,
                                        'credit': Decimal(100)},
                                    ])],
                        }])
            self.assertFalse(done('fiscalyear_no_drafts'))
            self.assertFalse(done('fiscalyear_income_balanced'))
            Move.delete([move])
            self.assertTrue(done('fiscalyear_no_drafts'))
            self.assertTrue(done('fiscalyear_income_balanced'))

            # no billing unit ending in the year - nothing to reconcile
            self.assertTrue(done('fiscalyear_oc_reconciled'))

            # adjustment period and journal of type situation
            self.assertFalse(done('fiscalyear_closing_prepared'))
            # a step by condition set done by hand: warning, then noted
            from trytond.transaction import Transaction
            Task = pool.get('real_estate.task')
            task, = [t for t in Process(process.id).tasks
                if t.template_step and t.template_step.done_method
                == 'fiscalyear_closing_prepared']
            if task.state != 'open':
                Task.activate([task])
            with self.assertRaises(UserWarning):
                Task.done([Task(task.id)])
            with Transaction().set_context(_skip_warnings=True):
                Task.done([Task(task.id)])
            task = Task(task.id)
            self.assertEqual(task.state, 'done')
            self.assertIn('Set done by hand', task.result)
            Journal.create([{'name': 'Closing', 'code': 'CLO',
                        'type': 'situation'}])
            Period.create([{'name': 'Closing 2025',
                        'fiscalyear': fiscalyear.id,
                        'start_date': datetime.date(2025, 12, 31),
                        'end_date': datetime.date(2025, 12, 31),
                        'type': 'adjustment'}])
            self.assertTrue(done('fiscalyear_closing_prepared'))

            # periods and fiscal year closed
            self.assertFalse(done('fiscalyear_periods_closed'))
            self.assertFalse(done('fiscalyear_closed'))
            FiscalYear.close([FiscalYear(fiscalyear.id)])
            self.assertTrue(done('fiscalyear_periods_closed'))
            self.assertTrue(done('fiscalyear_closed'))

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
