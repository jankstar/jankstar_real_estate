Real Estate Module for Tryton
##############################

A Tryton ERP module for real estate management. Packaged as ``jankstar_real_estate``,
targeting Tryton 7.8.1 and Python 3.9–3.13.

Covers property management, lease and sales contracts, tenant/owner party roles,
operating cost settlement, and German SKR04 accounting templates.

.. toctree::
   :maxdepth: 2

   setup
   configuration
   design
   reference
   releases


Module Dependencies
===================

``ir``, ``res``, ``company``, ``party``, ``product``, ``currency``, ``country``,
``account``, ``account_invoice``, ``account_deposit``, ``account_payment_clearing``


Installation
============

.. code-block:: bash

   pip install -e .           # development install
   pip install -e '.[test]'   # with test dependencies

The module entry point is declared in ``setup.py``::

   [trytond.modules]
   real_estate = trytond.modules.real_estate

Link or install the package inside the Tryton modules directory so that
``trytond-admin -u real_estate`` can find it.


Configuration
=============

The following master data must be set up before the module can be used:

``real_estate.object_party.role``
   Partner roles in combination with the property type (``base_object.type``),
   e.g. *Tenant*, *Owner*, *Administrator*.

``real_estate.measurement.type``
   Named measurements linked to a unit of measure,
   e.g. *Living Area (m²)*, *Number of Rooms*, *Gross Floor Area (m²)*.

``real_estate.contract.type``
   Contract types defining invoice direction (in/out), default journal,
   tax defaults, contract number prefix, and whether occupancy exclusivity
   is enforced.

``real_estate.contract.term.type``
   Term type definitions with default rhythm (monthly / quarterly / …),
   default quantity source (measurement type), and default account.

``real_estate.cost_category_group`` / ``real_estate.cost_type``
   Cost categories (e.g. *Heating*, *Water*) and individual cost types
   used to structure operating cost settlements.


Data Model
==========

Property Management
-------------------

``real_estate.address``  (``address.py``)
   Structured address with granular fields (``street_name``,
   ``building_number``, ``unit_number``, ``floor_number``, ``room_number``,
   ``post_box``) plus an unstructured fallback text field.
   Supports both formats and is linked to ``base_object`` records.

``real_estate.base_object``  (``base_object.py``)
   Central entity for every real estate asset.

   *Types:* ``property`` · ``building`` · ``object`` · ``land`` · ``equipment``

   *Workflow:* Draft → Active → Closed

   Key features:

   - Parent–child tree (``tree()`` mixin), e.g. Property → Building → Apartment
   - One2Many relations to ``Address``, ``ObjectParty``, ``Measurement``,
     and ``BillingUnit``
   - History tracking via ``BaseObjectOccupancy`` (tenant occupancy periods)
   - Meter readings (``MeterReading``) linked to equipment objects
   - ``billing_as`` / ``collective_billing`` flags to control how operating
     cost billing is aggregated at property level
   - Buttons ``compute_value_shares``, ``compute_settlement_result_property``,
     and ``billing_property`` delegate bulk settlement actions to all
     billing units of the property

``real_estate.object_party.role``  (``object_party.py``)
   Configurable role definitions per object type
   (e.g. *Tenant* only for type ``object``, *Owner* for all types).

``real_estate.object_party``  (``object_party.py``)
   Links a ``party.party`` record to a ``BaseObject`` with a typed role
   and an optional validity period.

``real_estate.measurement.type``  (``measurement.py``)
   Named measurement type linked to a ``product.uom`` unit.

``real_estate.measurement``  (``measurement.py``)
   Associates a numeric value and measurement type with a ``BaseObject``
   for a given validity period.


Contract Management
-------------------

``real_estate.contract.type``  (``contract_type.py``)
   Template for contracts. Defines invoice direction (``in``/``out``),
   default taxes, accounting journal, number prefix, step sizes for item
   and term sequence numbers, and whether occupancy exclusivity is enforced.

``real_estate.contract.type.tax``  (``contract_type.py``)
   Many2Many relation table between ``ContractType`` and ``account.tax``.

``real_estate.contract.term.type``  (``contract_type.py``)
   Template for contract terms. Defines default rhythm, rhythm type
   (daily / weekly / monthly / quarterly / annually / one-time),
   rhythm start day, measurement type for quantity derivation,
   default quantity, and default account.

``real_estate.contract``  (``contract_core.py``)
   Main contract record.

   *Workflow:* Draft → Running → Terminated / Cancelled

   Key features:

   - Links to ``party.party`` (contractual partner), ``base_object``
     (property), and one or more ``ContractItem`` records
   - Generates Tryton accounting moves (invoices) for all active terms
     via ``create_moves`` / ``call_create_moves``
   - ``_refresh_occupancy_for_contracts`` updates occupancy records when
     a contract starts or is terminated
   - ``add_log`` appends timestamped ``ContractLog`` entries
   - ``next_item_sequence`` / ``next_term_sequence`` auto-increment helpers

``real_estate.contract.log``  (``contract_core.py``)
   Append-only audit log attached to a contract (event name + description).

``real_estate.contract.item``  (``contract_item.py``)
   Associates a ``base_object`` of type ``object`` (e.g. an apartment)
   with a contract for a given validity period.
   On create/write/delete, triggers occupancy refresh and re-runs
   BillingUnit selection and value-share calculation for the affected property.
   Validates that ``valid_from`` lies within the contract period and raises
   a warning (or error for active contracts) on overlapping occupancy.

``real_estate.contract.term``  (``contract_term.py``)
   A recurring charge line on a contract (rent, operating cost advance, etc.).

   Key fields: ``term_type``, ``reference_item``, ``valid_from``/``valid_to``,
   ``rhythm`` + ``rhythm_type`` + ``rhythm_start``, ``quantity``,
   ``unit``, ``unit_price``, ``taxes``.

   Key methods:

   ``re_calc()``
      Rebuilds the ``CashFlow`` list from existing invoice lines and
      projects future entries up to ``_re_calc_year`` years ahead.

   ``_next_document_date()``
      Calculates the next invoice date based on rhythm and last posting date.

   ``_on_change_with_next_due_date()``
      Applies the contract's payment term to derive the due date.

``real_estate.contract.term.tax``  (``contract_term.py``)
   Many2Many relation table between ``ContractTerm`` and ``account.tax``.

``real_estate.contract.term.cash_flow``  (``contract_term.py``)
   Projected or realised cash flow entry for a term.

   *States:* ``draft`` (planned) · ``done`` (invoiced)

   Stores ``posting_date``, ``document_date``, ``due_date``, and a link to
   the ``account.invoice.line`` once billed.
   Supports date-pattern search (``YYYY/MM`` or ``YYYY/MM/DD``) in the name field.

``Quantitative``  (``contract_term.py``)
   Custom ``fields.Numeric`` subclass that carries a ``unit`` reference and
   sets ``quantitative=True`` in its field definition so the UI renders the
   associated unit symbol.


Operating Cost Settlement
--------------------------

``real_estate.cost_category_group``  (``billing_unit.py``)
   Groups cost types for reporting, e.g. *Heating*, *Water*, *Janitorial*.

``real_estate.cost_type``  (``billing_unit.py``)
   Individual cost item (e.g. *Gas*, *Cold Water*) with optional
   ``category_group``, ``comment``, and ``no_print`` flag.

``real_estate.billing_unit``  (``billing_unit.py``)
   Annual (or period) operating cost settlement for one property.

   *Workflow:* Draft → Approved → Selection → Value Share → Billed

   Two calculation methods:

   ``rental_apartment``
      Operating cost settlement for residential tenancies under §§ 1–2 BetrKV.
      Costs are allocated to tenants proportionally.

   ``WEG_billing``
      Annual statement for condominium owners under WEG (German condo law).
      Costs are allocated to co-owners by ownership share.

   Key actions (buttons):

   ``approved``
      Activates the billing unit.

   ``selection``
      Identifies which contracts/objects are in scope for the billing period.

   ``compute_value_shares_button``
      Calculates allocation shares (``CostShare``) for each settlement unit.

   ``compute_settlement_result``
      Derives ``SettlementResult`` records per contract — actual costs,
      advances paid, and the resulting refund or additional receivable.

   ``billing``
      Creates invoices/credit notes from the settlement results.
      Hidden when the property has ``collective_billing = True``; in that
      case the action is triggered from the property form instead.

``real_estate.billing_unit.log``  (``billing_unit.py``)
   Timestamped log entries attached to a billing unit.

``real_estate.settlement_unit``  (``settlement_unit.py``)
   One cost-type line within a billing unit, e.g. *Gas 2024*.

   *Allocation rules:*

   ``no_allocation``
      Entire cost stays unallocated.

   ``allocation_by_measurement``
      Allocated by a measurement value, e.g. living area.

   ``allocation_by_consumption``
      Allocated by meter reading consumption (HeizkostenV).

   ``allocation_per_rental_unit``
      Equal share per rental unit.

   Vacancy handling: unoccupied periods can be charged to the owner or left
   unallocated.

``real_estate.cost_share``  (``settlement_result.py``)
   Intermediate allocation record: share of a specific cost type for one
   contract or object within a billing period.

   *States:* ``preparation`` · ``selection`` · ``estimated_value_share``
   · ``value_share`` · ``error``

   Stores ``value_share`` (allocation factor), ``time_share`` (days),
   ``planned_costs``, ``actual_costs``.

``real_estate.settlement_result``  (``settlement_result.py``)
   Final settlement record per contract (or object) and billing unit.

   *States:* ``approved`` · ``billed``

   Stores ``planned_costs``, ``actual_costs``, ``advanced_payment``
   (sum of operating-cost advance invoices during the period), and the
   derived ``refund_receivable`` (positive = refund to tenant,
   negative = additional receivable).
   Optionally links to the single ``ContractTerm`` that covered all advances
   when exactly one term was involved.


Extensions to Core Modules
---------------------------

``party.party``  (``party.py``)
   Adds ``sequence`` (integer sort key) and ``salutation`` fields.

``account.invoice``  (``invoice.py``)
   Adds a ``contract`` Many2One field so invoices can be traced back to the
   originating contract.

``account.invoice.line``  (``invoice.py``)
   Adds a ``term`` Many2One field linking invoice lines to the
   ``ContractTerm`` that generated them.

``res.user``  (``res.py``)
   Adds ``phone`` and ``mobile`` fields.


Wizards
=======

``real_estate.contract.create_moves``  (``contract_wizard.py``)
   Batch invoice generation wizard. Supports three actions:

   ``create``
      Generate invoices up to a given date.

   ``re_calc``
      Rebuild cash flow projections without creating invoices.

   ``re_calc_and_create``
      Combine both steps.

   Can be filtered by property and/or contract list.
   Optional queue execution via ``execute_in_queue``.

``real_estate.terminate_contract.wizard``  (``contract_wizard.py``)
   Sets a contract to *Terminated*, records ``terminated_by``,
   ``receipt_of_termination_notice``, ``termination_reason``, and
   calculates ``termination_date`` from the notice period
   (3 / 6 / 9 / 12 months to end of month).


Reports
=======

HTML templates are located in ``report/``.

``real_estate.contract.report``  (``contract_wizard.py``)
   General contract report.
   Templates: ``contract_en.html``, ``contract_letter_de.html``.

``real_estate.contract.annex4.report``  (``contract_wizard.py``)
   Annex 4 – Betriebskostenaufstellung.
   Template: ``anlage4_contract_de.html``.
   Renders grouped operating cost positions with BetrKV paragraph references
   and allocation method labels.

``real_estate.base_object.report``  (``base_object.py``)
   Fact sheet for a property or object.
   Template: ``fact_sheet.html``.


Accounting / SKR04
==================

The ``skr04/`` directory contains German Standardized Chart of Accounts
(SKR04) XML templates loaded at module installation:

- Account types and accounts
- Tax groups, tax templates, tax code templates, tax code line templates
- Tax rule templates


Source Layout
=============

.. code-block:: text

   real_estate/
   ├── address.py               # real_estate.address
   ├── base_object.py           # real_estate.base_object, occupancy, meter readings
   ├── billing_unit.py          # real_estate.billing_unit, cost_type, cost_category_group
   ├── contract_core.py         # real_estate.contract, contract.log, account views
   ├── contract_item.py         # real_estate.contract.item
   ├── contract_term.py         # real_estate.contract.term, cash_flow, Quantitative
   ├── contract_type.py         # real_estate.contract.type, term.type
   ├── contract_wizard.py       # wizards, ContractReport, ContractAnnex4Report
   ├── invoice.py               # extensions to account.invoice / invoice.line
   ├── measurement.py           # real_estate.measurement.type, measurement
   ├── object_party.py          # real_estate.object_party, object_party.role
   ├── party.py                 # extension to party.party
   ├── res.py                   # extension to res.user
   ├── settlement_result.py     # real_estate.settlement_result, cost_share
   ├── settlement_unit.py       # real_estate.settlement_unit
   ├── report/                  # HTML report templates
   ├── view/                    # XML form and tree view definitions
   ├── skr04/                   # German SKR04 accounting templates
   └── locale/                  # Translations (de.po)


Running Tests
=============

.. code-block:: bash

   # Full test matrix (sqlite + postgresql, py39–py313)
   tox

   # Single environment
   tox -e py311-sqlite

   # Direct run
   export TRYTOND_DATABASE_URI=sqlite://
   export DB_NAME=:memory:
   coverage run --omit=*/tests/* -m xmlrunner discover -s tests
   coverage report

Demo data scripts in ``tests/`` (proteus-based, not unit tests):

``tests/test_immo.py``
   Creates one property with building, four rental objects, and meter readings.
   Run once against a populated database::

      python tests/test_immo.py --database <db> [--config trytond.conf]

``tests/test_contracts.py``
   Creates tenants and lease contracts for three apartments.
   Requires data from ``test_immo.py``::

      python tests/test_contracts.py --database <db> [--config trytond.conf]
