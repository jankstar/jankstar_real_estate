import datetime

from trytond.modules.real_estate.tests.module_base import BaseTests
from trytond.modules.real_estate.tests.module_contract import ContractTests
from trytond.modules.real_estate.tests.module_core import CoreTests
from trytond.modules.real_estate.tests.module_operating_costs import (
    OperatingCostsTests)
from trytond.modules.real_estate.tests.module_rent_adjustment import (
    RentAdjustmentTests)
from trytond.modules.real_estate.tests.module_tasks import TasksTests
from trytond.pool import Pool
from trytond.tests.test_tryton import ModuleTestCase, with_transaction


class RealEstateTestCase(CoreTests, BaseTests, ContractTests,
        RentAdjustmentTests, OperatingCostsTests, TasksTests, ModuleTestCase):
    "Test Real Estate module"
    module = 'real_estate'

    @with_transaction()
    def test_sql_constraint_messages(self):
        "SQL constraints raise readable messages (message ids)"
        from trytond.modules.company.tests import create_company, set_company
        from trytond.model.exceptions import SQLConstraintError

        pool = Pool()
        BaseObject = pool.get('real_estate.base_object')
        Message = pool.get('ir.message')

        for name in ['real_estate.base_object', 'real_estate.measurement',
                'real_estate.object_party', 'real_estate.contract.type.tax',
                'real_estate.contract.term.tax']:
            for _, _, msg in pool.get(name)._sql_constraints:
                module, id_ = msg.split('.')
                self.assertIn(module, ['ir', 'real_estate'], msg)
                self.assertNotEqual(Message.gettext(module, id_, 'en'),
                    id_, msg)

        company = create_company()
        with set_company(company):
            values = {'name': 'P', 'type': 'property', 'sequence': 1,
                'company': company.id,
                'start_date': datetime.date(2025, 1, 1)}
            prop, = BaseObject.create([values])
            building = dict(values, name='B1', type='building',
                parent=prop.id)
            BaseObject.create([building])
            # The next free sequence below the parent is proposed
            b1, = BaseObject.search([('name', '=', 'B1')])
            new = BaseObject(parent=prop, type='building', sequence=None)
            self.assertEqual(new.on_change_with_sequence(), 10)
            BaseObject.write([b1], {'sequence': 17})
            self.assertEqual(new.on_change_with_sequence(), 20)
            new.type = 'land'
            self.assertEqual(new.on_change_with_sequence(), 10)
            BaseObject.write([b1], {'sequence': 1})
            with self.assertRaises(SQLConstraintError) as cm:
                BaseObject.create([dict(building, name='B2')])
            self.assertIn('sequence', str(cm.exception).lower())

    @with_transaction()
    def test_batch_jobs_lock_all_records_once(self):
        "Batch jobs lock all their records at once, before processing"
        from unittest.mock import patch
        pool = Pool()
        Contract = pool.get('real_estate.contract')
        BaseObject = pool.get('real_estate.base_object')

        class Stop(Exception):
            pass

        # Tryton restarts the transaction for every lock of records not
        # locked yet - one lock per record in the loop would process all
        # previous records again for every further record
        for Model, call in (
                (Contract, lambda: Contract.create_moves(
                        [1, 2, 3], datetime.date(2025, 1, 31))),
                (BaseObject, lambda: BaseObject.do_billing([1, 2, 3]))):
            with patch.object(Model, 'lock', side_effect=Stop) as lock:
                with self.assertRaises(Stop):
                    call()
                lock.assert_called_once()
                self.assertEqual(
                    sorted(int(r) for r in lock.call_args.args[0]),
                    [1, 2, 3])


del ModuleTestCase
