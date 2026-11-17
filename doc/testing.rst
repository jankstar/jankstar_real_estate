*************
Running Tests
*************

The unit tests are in ``tests/``:

- ``tests/test_module.py`` defines ``RealEstateTestCase``, the only test
  class with a database. It derives from Tryton's ``ModuleTestCase``, which
  adds the generic module-consistency checks (``test_view``,
  ``test_xml_files``, ``test_model_access``, ``test_depends``,
  ``test_wizards`` …), and from six building-block classes, one per area
  folder of the module, which hold the 73 explicit tests:

  ==================================  =========================
  File                                Class
  ==================================  =========================
  ``tests/module_core.py``            ``CoreTests``
  ``tests/module_base.py``            ``BaseTests``
  ``tests/module_contract.py``        ``ContractTests``
  ``tests/module_rent_adjustment.py`` ``RentAdjustmentTests``
  ``tests/module_operating_costs.py`` ``OperatingCostsTests``
  ``tests/module_tasks.py``           ``TasksTests``
  ==================================  =========================

  The building-block classes have no ``unittest`` base class and are no
  test cases of their own; ``test_module.py`` imports them via the package
  name (``trytond.modules.real_estate.tests.module_contract``) and keeps
  only the tests across areas. The test database is created and the module
  activated once.
- ``tests/common.py`` holds the stand-ins used by the tests of several
  areas.
- ``tests/test_bved_records.py`` tests the fixed-width BVED records without
  a database.

A new test goes into the building-block file of the area whose program it
tests; if it tests several areas, into ``test_module.py``.

There is no CI pipeline in this repo; the tests are run manually.

.. code-block:: bash

   # Full test matrix (sqlite + postgresql, py39–py313)
   tox

   # Single environment
   tox -e py313-sqlite

   # Direct run
   export TRYTOND_DATABASE_URI=sqlite://
   export DB_NAME=:memory:
   coverage run --omit=*/tests/* -m xmlrunner discover -s tests
   coverage report

   # Single test or selection by name (a building-block file cannot run
   # on its own)
   python -m unittest discover -s tests -k test_base_object_hierarchy

See `Demo data scripts <demo_data_scripts.rst>`_ for the one-shot proteus import scripts under ``tests/``.
