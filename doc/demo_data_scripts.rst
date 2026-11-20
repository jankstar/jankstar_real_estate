*****************
Demo data scripts
*****************

The scripts ``tests/demo_*.py`` are one-shot **proteus import scripts**
that generate demo data against a running trytond server (module tests are
``test_*.py`` and ``module_*.py``, see `Running Tests <testing.rst>`__). These are run
manually — ``python tests/<script>.py --database <db> [--config
trytond.conf]`` — not via tox/xmlrunner.

``tests/demo_run.py`` (recommended)
   Run script: starts the scripts below in this order, each as a process
   of its own with the same Python, the script output passes through.
   Steps (names for ``--only``/``--skip``): settings ``setup``, master data ``kreditor``,
   ``immo``, ``contracts``, ``billing_unit``; per month from ``--from`` to
   ``--to`` (format ``YYYY-MM``, default January to December of the start
   year), month by month: ``contract_moves``, ``invoices``, ``payment``
   with ``--year``/``--month`` of the month; then ``rent_survey`` and,
   with ``--modernisation`` (or in ``--only``), ``modernisation``
   (``--execute`` is passed on). ``--year`` is the start year (default
   current year − 1), ``--continue-on-error`` continues after a failed
   step (default: stop), ``--dry-run`` only prints the commands. Each step
   prints a header with name and command, then result, exit code and
   duration; an overview of all steps follows at the end, exit code 1 if a
   step failed, else 0. Exit codes of the scripts: 0 = done, 1 = error,
   2 = wrong call (argparse), 3 = data exist, nothing created
   (``EXIT_EXISTS`` in ``demo_setup.py``, ``demo_kreditor.py``, ``demo_immo.py``,
   ``demo_contracts.py``, ``demo_billing_unit.py``, which stop if their
   data exist) - ``demo_run.py`` shows 3 as *skipped (data exist)*, no
   error, and continues; so a further run (e.g. more months) works without
   ``--skip``, ``--skip setup,kreditor,immo,contracts,billing_unit`` remains
   possible. Months after the start
   year are allowed; purchase invoices then only find settlement units if
   billing units exist for that year (a hint is printed)::

      python tests/demo_run.py --database <db> [--config trytond.conf] [--year 2025] [--from 2025-01] [--to 2025-12] [--only <steps> | --skip <steps>] [--modernisation [--execute]] [--continue-on-error] [--dry-run]

The single scripts, in the order of the run (each step builds on the
previous one's data):

Start year: the scripts that set dates (``demo_setup.py``, ``demo_immo.py``,
``demo_contracts.py``, ``demo_billing_unit.py``,
``demo_contract_moves.py``, ``demo_invoices.py``, ``demo_rent_survey.py``)
take ``--year`` with the default *current year − 1*; all dates are formed
relative to it (same day and month, year = start year or the following
year). ``demo_kreditor.py`` has no ``--year`` (it sets no dates),
``demo_payment.py`` keeps ``--year`` without a default (without it all open
items), ``demo_modernisation.py`` works relative to today. The dates below
are given as day and month of the start year.

``tests/demo_setup.py``
   First step ``setup``. Prerequisites by hand: database with the module,
   company (ID 1, party ID 1) and the chart of accounts from the template
   *Kontenrahmen der Wohnungswirtschaft (WoWi)* (checked, exit code 1
   otherwise). Sets the company-dependent settings with the values of the
   test system: accounts, tax rules, payment terms, language, salutation and
   party role *Companies* of the company party, *Real Estate Accounting* of the company, default
   accounts of the accounting configuration, accounts of contract types,
   term types and cost types, process templates of the commercial lease
   agreement, task rules (active, company), cron tasks, company of the
   daily cron, term type ↔ contract type, strict sequences and fiscal
   years from the start year to start year + 2 with monthly periods. Sets
   only empty fields, creates only what is missing; a different existing
   value is kept and shown as a hint. Exit code 0 = something created or
   set, 3 = everything exists::

      python tests/demo_setup.py --database <db> [--config trytond.conf] [--year 2025]

``tests/demo_immo.py``
   No prerequisites. Creates two properties (*Musterstraße 1-4* and
   *Musterstraße 5-8*), each with four buildings. Every building has one
   ground-floor retail unit (``type_of_use='commercial'``, 140 m²) and four
   apartments (``type_of_use='residential'``, 57/83 m² alternating) — 16
   apartments, 4 retail units, and 20 water meters per property in total —
   plus one land parcel with four parking spaces. Meter names follow the
   pattern ``Wasser Zähler NN`` / ``Wasser Zähler EHNN``, each with an
   initial and a consumption reading. Beforehand it creates the parties
   *Verwalter 1* and *Hausmeister 1*, each with an employee of the company
   (existing ones are reused), and assigns them to both properties as
   object parties with the roles *Administrator* and *Caretaker* (valid
   from 01.01. of the start year) - the basis of the task responsibility by party role
   (see `Tasks, Processes and Handover Reports <tasks.rst>`__). Linking the
   employees to users is left to the administrator; the script prints a
   hint at the end. Each apartment gets a smoke detector equipment
   (equipment kind *Smoke Detector*, measurement *Number of items* = number
   of rooms) and each building the inspection plans *Annual Walkthrough*
   (due 01.04. of the following year) and *Smoke Detector Check* (due 15.05.
   of the following year) if the
   default inspection types exist. At the end it runs the option rate
   determination once - wizard *Update Option Rates*
   (``real_estate.option_rate_update.wizard``) for both properties with
   the cut-off date 01.01. of the start year, valid from that day (properties and
   buildings dynamic by usable space, land fixed 0 % as its parking spaces
   have no usable space, rental objects fixed: 0 % for apartments and
   parking, 100 % for retail). Looks up ``real_estate.use_class``,
   measurement types and object party roles by ``sequence``, equipment
   kind and inspection types by ``code`` (language-independent)::

      python tests/demo_immo.py --database <db> [--config trytond.conf] [--year 2025]

``tests/demo_contracts.py``
   Requires ``demo_immo.py``. Creates residential lease contracts for 15 of
   16 apartments per property (one left vacant), each with rent, operating
   cost, and heating terms; the first apartment contract additionally
   gets a one-time rent deposit (term type 1900, three times the rent, at
   the contract start), the second one a subletting surcharge (term
   type 1020, 20.00 EUR monthly from 01.07.) and the third one a rent
   reduction (term type 1010, -50.00 EUR monthly from 01.07.) - all
   three stay open-ended.
   Three other contracts per property are terminated, two of them with a
   follow-up contract. The four parking spaces per
   property are split between existing apartment contracts (as an extra
   contract item) and new standalone parking contracts (contract type
   *Parking Space Lease Agreement*, sequence 20). Also creates
   commercial lease contracts for the retail units — one combined contract
   for all four retail units on *Musterstraße 1-4*, one contract per unit on
   *Musterstraße 5-8*. Terms are absolute amounts (price per m² × area,
   quantity 1). Up to three running apartment contracts per property get a
   graduated rent (rent adjustment with procedure ``graduated_rent`` on the
   rent term: 12-month rhythm, 5 steps, +30 € / +0.40 €/m² / +3 %), whose
   steps are generated; both procedures must be allowed on the residential
   contract type and the rent term type (standard data - the script does
   not change settings). Up to two
   further running apartment contracts per property (without graduated
   rent) get an active index rent (procedure ``index_rent``: price index
   ``VPI-DE``, base month January of the start year, statutory effective date, no
   threshold, cap automatic); missing VPI values of the current base year
   are first taken over from ``tests/genesis_61111-0002_ffcsv.csv``
   (GENESIS-Online flat file download, parsed like the CSV import wizard),
   then *Fetch Values* runs once (button ``fetch``, GENESIS web service with
   ``genesis_token`` of ``trytond.conf``; creates only missing months and
   updates changed ones; a failure, e.g. without network, is only a
   warning and leaves the exit code unchanged) - without the file
   or the base month value (the CSV holds real values, e.g. none for a
   start year after the last published month) a hint is printed and no
   index rents are created. The adjustment run
   itself is not executed::

      python tests/demo_contracts.py --database <db> [--config trytond.conf] [--year 2025]

``tests/demo_billing_unit.py``
   Requires ``demo_immo.py``. Creates two billing units per property:
   *Kalte Betriebskosten* (measurement- and consumption-based settlement
   units, vacancy allocated to the owner) and *Heizkosten*
   (``external_billing=True``, settlement units use
   ``allocation_from_external_billing``). Billing units are left in state
   ``draft`` — anything that requires a later state (e.g.
   ``demo_invoices.py``'s settlement-unit lookup) needs the workflow
   advanced manually first::

      python tests/demo_billing_unit.py --database <db> [--config trytond.conf] [--year 2025]

``tests/demo_contract_moves.py``
   Requires ``demo_contracts.py`` and a fiscal year with periods and
   sequences for the month. Posts the contracts of one month periodically
   via the wizard *Create Moves* (``real_estate.contract.create_moves.wizard``,
   as a user would in the client): date *to* = last day of the month,
   invoice date = first day of the month, action *Re-Calculate and Create
   moves*, without queue (``Contract.create_moves`` runs directly), no
   filters. ``--month`` is required, ``--year`` defaults to the current year
   − 1, ``--state`` (invoice state) to ``posted``. A second run for the
   same month creates no duplicate postings (only draft cash flow lines up
   to the date are booked; the re-calculation rebuilds the booked ones from
   their invoice lines); a contract ending before the date is skipped, so
   post the months in order. Monthly run:
   ``demo_contract_moves.py`` → ``demo_invoices.py --month`` →
   ``demo_payment.py --year --month``::

      python tests/demo_contract_moves.py --database <db> [--config trytond.conf] --month 3 [--year 2025] [--state posted]

``tests/demo_kreditor.py``
   No prerequisites. Creates 11 supplier/creditor parties (property tax
   office, building insurer, utilities, cleaning, caretaker, gardening,
   chimney sweep, heating maintenance), each with an invoice/delivery
   address::

      python tests/demo_kreditor.py --database <db> [--config trytond.conf]

``tests/demo_invoices.py``
   Requires ``demo_kreditor.py``, ``demo_immo.py``, and
   ``demo_billing_unit.py`` (with billing units advanced past ``draft`` so
   settlement units can be looked up). Creates the corresponding purchase
   invoices — one-off and recurring — for each property. The lines only
   carry the property (assignment control *Operating Costs*); the invoices
   are posted, which creates one operating cost document per line, and each
   document is then assigned 100 % to its settlement unit and confirmed
   (what a user does in *Assign Operating Costs*). Accounts: property tax
   8910, heating 8002, all other operating costs 8000. ``--month`` creates
   only the invoices of that month (of ``--year``, default current year − 1) - for a
   monthly run together with the periodic contract posting
   (``demo_contract_moves.py``) and ``demo_payment.py --month``::

      python tests/demo_invoices.py --database <db> [--config trytond.conf] [--year 2025] [--month 3]

``tests/demo_rent_survey.py``
   The rent survey *Berliner Mietspiegel* with the complete version
   *Berliner Mietspiegel 2026* is standard data of the module
   (``rent_survey_berlin.xml``, see `Comparative rent
   <rent_adjustment_comparative.rst>`__) and exists after the module
   installation. The script requires ``demo_immo.py`` and assigns it to
   *Musterstraße 1-4*: location medium on the property; year of
   construction 1958 (if empty), *Besonders ruhige Lage*, bike room,
   insulation and an energy consumption value of 130 kWh/(m²a) on every
   building; features of the groups 1-3 on *Wohnung 01*; then calculates
   its comparative rent (key date today, at the earliest 28.05.2026).
   Assignments already present are skipped::

      python tests/demo_rent_survey.py --database <db> [--config trytond.conf] [--year 2025]

``tests/demo_modernisation.py``
   Requires ``demo_immo.py`` and ``demo_contracts.py``. Allows the
   procedure *Modernisation* for the term type 1000 and the contract types
   of the selected tenancies and sets the cap measurement of the
   modernisation rule to *Wohnfläche* if empty. On *Musterstraße 1-4* it
   creates the measure *Fassadendämmung Haus 2* (second building,
   standard § 559, allocation by living space, cost lines facade / windows
   / scaffolding with maintenance shares and 19 % input tax, grant
   10,000 EUR), announces it today, captures the receipts, starts the work
   after the announcement period and completes it two months later (the
   costs become actual costs); then an adjustment run *Modernisation*
   selected and calculated (``--execute``: also approved and announced -
   receipts and execution stay manual). If an apartment of the property is
   vacant, a comprehensive vacancy measure *Bad und Küche <unit>* is
   created and completed (basis of §§ 556e para. 2, 556f BGB in the new
   letting check). Dates relative to today, warnings confirmed
   automatically. Aborts if the measure exists::

      python tests/demo_modernisation.py --database <db> [--config trytond.conf] [--execute]

``tests/demo_payment.py``
   Requires ``demo_contracts.py`` and the periodic contract posting with
   ``demo_contract_moves.py`` so posted tenant invoices exist (and
   ``demo_invoices.py`` for the creditor side). Books one payment receipt per
   tenant/commercial-tenant party (debit 2740 Bank / credit the receivable
   account taken from that party's open lines) and one payment per creditor
   (debit the payable account / credit 2740 Bank) and reconciles the open
   items. ``--year`` [``--month``] restricts it to the open items dated in
   that year resp. month (payment date = latest date of those items)::

      python tests/demo_payment.py --database <db> [--config trytond.conf] [--year 2025 [--month 3]]

``tests/migrate_run_rents.py``
   Test migration for the comparative rent: sets the rent terms of the
   contracts of an adjustment run (default ``AL-2026-0001``; a run without
   adjustments takes the candidates of its filters, without active index
   rents) to about 6.00 EUR/m² (``--rent``, ± ``--spread`` 0.20 fixed per
   contract number, idempotent) from the contract start - area terms get
   the price per m², absolute terms price × living space. Only the open
   rent term is changed; posted invoices stay unchanged (test data), the
   booked-values warnings are confirmed. ``--recalculate`` calculates the
   run again, ``--dry-run`` only lists the new rents::

      python tests/migrate_run_rents.py --database <db> [--config trytond.conf] [--run AL-2026-0001] [--rent 6.00] [--spread 0.20] [--recalculate] [--dry-run]

