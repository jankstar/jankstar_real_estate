*************
Running Tests
*************

.. warning::
   ``tests/`` currently has no ``unittest.TestCase``-based tests —
   ``test_module.py`` (the standard Tryton ``ModuleTestCase`` boilerplate)
   has been removed and not replaced. ``tox.ini`` still defines a real test
   matrix (``envlist = {py39,py310,py311,py312,py313}-{sqlite,postgresql}``)
   and the commands below run without error, but ``unittest``/``xmlrunner``
   discovery currently finds **zero** test cases in every environment and
   exits **0 (success)** regardless — i.e. ``tox`` reports a false-positive
   pass, not "no tests configured". There is no CI pipeline in this repo
   currently invoking it automatically, but running it manually and reading
   "OK" is misleading until a real test case is added back.

.. code-block:: bash

   # Full test matrix (sqlite + postgresql, py39–py313) — currently a
   # false-positive pass, see warning above
   tox

   # Single environment
   tox -e py311-sqlite

   # Direct run
   export TRYTOND_DATABASE_URI=sqlite://
   export DB_NAME=:memory:
   coverage run --omit=*/tests/* -m xmlrunner discover -s tests
   coverage report

See `Demo data scripts <demo_data_scripts.rst>`_ for the one-shot proteus import scripts under ``tests/``.
