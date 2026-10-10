*****************
Demo data scripts
*****************

Everything in ``tests/`` is instead a one-shot **proteus import script** that
generates demo data against a running trytond server. These are run
manually — ``python tests/<script>.py --database <db> [--config
trytond.conf]`` — not via tox/xmlrunner, in the following order (each step
builds on the previous one's data):

``tests/test_immo.py``
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
   from 01.01.2025) - the basis of the task responsibility by party role
   (see `Tasks, Processes and Handover Reports <tasks.rst>`__). Linking the
   employees to users is left to the administrator; the script prints a
   hint at the end. Each apartment gets a smoke detector equipment
   (equipment kind *Smoke Detector*, measurement *Number of items* = number
   of rooms) and each building the inspection plans *Annual Walkthrough*
   (due 01.04.2026) and *Smoke Detector Check* (due 15.05.2026) if the
   default inspection types exist. Looks up ``real_estate.use_class``,
   measurement types and object party roles by ``sequence``, equipment
   kind and inspection types by ``code`` (language-independent)::

      python tests/test_immo.py --database <db> [--config trytond.conf]

``tests/test_contracts.py``
   Requires ``test_immo.py``. Creates residential lease contracts for 15 of
   16 apartments per property (one left vacant), each with rent, operating
   cost, and heating terms; three contracts per property are terminated,
   two of them with a follow-up contract. The four parking spaces per
   property are split between existing apartment contracts (as an extra
   contract item) and new standalone parking contracts. Also creates
   commercial lease contracts for the retail units — one combined contract
   for all four retail units on *Musterstraße 1-4*, one contract per unit on
   *Musterstraße 5-8*. Terms are absolute amounts (price per m² × area,
   quantity 1). Up to three running apartment contracts per property get a
   graduated rent (rent adjustment with procedure ``graduated_rent`` on the
   rent term: 12-month rhythm, 5 steps, +30 € / +0.40 €/m² / +3 %), whose
   steps are generated; the procedure is allowed on the residential
   contract type and the rent term type first if missing. Up to two
   further running apartment contracts per property (without graduated
   rent) get an active index rent (procedure ``index_rent``: price index
   ``VPI-DE``, base month 01/2025, statutory effective date, no
   threshold, cap automatic); missing VPI values of the current base year
   are first taken over from ``tests/61111-0002_de.csv`` (GENESIS-Online
   table download, parsed like the CSV import wizard) - without the file
   or the base month value no index rents are created. The adjustment run
   itself is not executed::

      python tests/test_contracts.py --database <db> [--config trytond.conf]

``tests/test_billing_unit.py``
   Requires ``test_immo.py``. Creates two billing units per property:
   *Kalte Betriebskosten* (measurement- and consumption-based settlement
   units, vacancy allocated to the owner) and *Heizkosten*
   (``external_billing=True``, settlement units use
   ``allocation_from_external_billing``). Billing units are left in state
   ``draft`` — anything that requires a later state (e.g.
   ``test_invoices.py``'s settlement-unit lookup) needs the workflow
   advanced manually first::

      python tests/test_billing_unit.py --database <db> [--config trytond.conf]

``tests/test_kreditor.py``
   No prerequisites. Creates 11 supplier/creditor parties (property tax
   office, building insurer, utilities, cleaning, caretaker, gardening,
   chimney sweep, heating maintenance), each with an invoice/delivery
   address::

      python tests/test_kreditor.py --database <db> [--config trytond.conf]

``tests/test_invoices.py``
   Requires ``test_kreditor.py``, ``test_immo.py``, and
   ``test_billing_unit.py`` (with billing units advanced past ``draft`` so
   settlement units can be looked up). Creates the corresponding purchase
   invoices — one-off and recurring — for each property, linking each line
   to its ``settlement_unit`` where a match is found. Invoices are only
   saved, not posted (remain in state ``draft``)::

      python tests/test_invoices.py --database <db> [--config trytond.conf]

``tests/test_rent_survey.py``
   Creates the rent survey *Berliner Mietspiegel* with the complete
   version *Berliner Mietspiegel 2026* (valid from 28.05.2026, qualified,
   table method, 20 % per group, netted): classification features
   *Wohnlage* (manual) and *Bezugsfertigkeit* (from the year of
   construction; the classes 1973-1990 West/East manual only) with their
   classes, all 189 table cells and the 86 features of the guidance
   (no. 11) and the reduction for minor equipment (no. 9.4), imported
   from ``tests/mietspiegel_berlin_2026_felder.csv`` and
   ``tests/mietspiegel_berlin_2026_merkmale.csv`` via the import wizard.
   With ``--only-survey`` only the rent survey is created (no
   prerequisites). Otherwise it also requires ``test_immo.py`` and assigns
   it to *Musterstraße 1-4*: location medium on the property; year of
   construction 1958 (if empty), *Besonders ruhige Lage*, bike room,
   insulation and an energy consumption value of 130 kWh/(m²a) on every
   building; features of the groups 1-3 on *Wohnung 01*; then calculates
   its comparative rent (key date today, at the earliest 28.05.2026).
   Aborts if the rent survey already exists::

      python tests/test_rent_survey.py --database <db> [--config trytond.conf] [--only-survey] [--company <name>]

``tests/test_payment.py``
   Requires ``test_contracts.py`` and at least one run of the
   ``CreateContractMoves`` wizard so posted tenant invoices exist. Books one
   payment receipt per tenant/commercial-tenant party (debit account 1800
   Bank / credit the receivable account taken from that party's open lines)
   and reconciles the open items::

      python tests/test_payment.py --database <db> [--config trytond.conf]

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

