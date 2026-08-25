Real Estate Module for Tryton
##############################

A Tryton ERP module for real estate management. Packaged as ``jankstar_real_estate``,
targeting Tryton 8.0.0 and Python 3.9–3.13.

Covers property management, lease and sales contracts, tenant/owner party roles,
operating cost settlement, CO2 cost allocation under the German CO2KostAufG,
and a German "Kontenrahmen der Wohnungswirtschaft" (WoWi) accounting chart.

.. toctree::
   :maxdepth: 2

   setup
   configuration
   usage
   design
   reference
   releases


Module Dependencies
===================

``ir``, ``res``, ``company``, ``party``, ``product``, ``currency``, ``country``,
``account``, ``account_invoice``, ``account_deposit``, ``account_payment_clearing``,
``account_tax_non_deductible``


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

``real_estate.use_class``
   Dynamic use-class catalogue replacing the former static selection field.
   Each record carries two boolean flags:

   ``has_basement_nr``
      Show/hide the *Basement Number* field on rental objects.

   ``has_parking_nr``
      Show/hide the *Parking Number* field on rental objects.

   Six default records are loaded at module installation:
   *Apartment* (has_basement_nr), *Office* (has_basement_nr),
   *Retail* (has_basement_nr), *Warehouse* (has_basement_nr),
   *Parking* (has_parking_nr), *Garage* (has_parking_nr).
   Additional classes can be created without changing code.

``real_estate.cost_category_group`` / ``real_estate.cost_type``
   Cost categories (e.g. *Heating*, *Water*) and individual cost types
   used to structure operating cost settlements.
   Default values for German BetrKV (§ 2) are loaded at module installation.

``real_estate.re_accounting``  (``re_accounting.py``)
   Standalone, company-scoped real-estate accounting configuration,
   referenced one-directionally from ``company.company.re_accounting``
   (``company.py``; optional — a company without a linked
   ``re_accounting`` record gets none of the automation below).

   ``re_account_allocation_by_owner``
      Vacancy cost account (debit and credit side of vacancy postings).

   ``re_journal_billing``
      Journal used for direct GL postings in operating cost settlements.

   ``re_payment_term_billing``
      Default payment term for operating cost settlement invoices, used
      when the contract itself has none set.

   ``create_moves_horizon_days``
      Number of days ahead of today the ``update_contract_cash_flow`` cron
      task (see below) recalculates cash flow for. Default 60.

   ``co2_landlord_share_commercial``
      Default CO2 cost landlord share (%, 0–100) for commercial properties,
      which are not covered by the residential 10-tier distribution model —
      see *CO2 Cost Allocation (CO2KostAufG)* under *Operating Cost
      Settlement* below. Shown right before the *Cron Tasks* table on the
      form.

   ``cron_tasks``
      One2Many to ``real_estate.cron_task`` — the company's scheduled
      task configuration, see below.

``real_estate.cron_task``  (``cron_task.py``)
   Per-``re_accounting`` (i.e. per-company) row configuring one recurring
   operation: ``task`` (selection, currently ``update_contract_status`` /
   ``update_contract_cash_flow`` / ``book_contract_cash_flow`` /
   ``update_option_rate``), ``valid_from``, ``valid_until``,
   ``interval_days``, ``interval_months``, ``schedule_day_of_month``,
   ``horizon_months_ahead``, ``last_run`` (updated by the dispatcher),
   ``active``. Task names are
   deliberately rhythm-agnostic (no "daily"/"rolling"/... in the name) —
   how often each task actually runs is a per-row configuration choice made
   by the user, not implied by the task itself; see *Scheduling and
   parameters* below. None of ``interval_days``/``interval_months``/
   ``schedule_day_of_month`` is individually required, but ``validate()``
   rejects a row that has none of the three set. A unique SQL constraint
   prevents duplicate rows for the same ``(re_accounting, task)`` pair. No
   rows are seeded
   automatically — a company gets no automatic behaviour until at least
   one row is added under the *Cron Tasks* tab of its
   ``real_estate.re_accounting`` record.

   **Dispatch.** A single ``ir.cron`` entry ("Real Estate Daily Tasks",
   method ``real_estate.contract|cron_daily`` — registered via a small
   ``ir.cron.method`` selection extension in ``ir.py``, since that field is
   otherwise a fixed core list) runs daily and calls
   ``Contract.cron_daily()`` (``contract_core.py``). It iterates all active
   ``cron_task`` rows and, for each one that is due (see *Scheduling*
   below), calls the matching ``Contract._cron_<task>(re_accounting, task)``
   classmethod and updates ``last_run``. A future recurring operation only
   needs a new ``_cron_<code>`` classmethod plus a new ``get_tasks()``
   option — no new ``ir.cron`` entry.

   **Scheduling and parameters.** Each ``cron_task`` row carries its own
   parameters, read by its handler from the ``task`` record passed in, and
   its own rhythm - e.g. ``update_contract_status`` daily
   (``interval_days = 1``), ``update_contract_cash_flow`` every six months
   (``interval_months = 6``), ``book_contract_cash_flow`` and
   ``update_option_rate`` monthly (``schedule_day_of_month`` set, e.g. 15
   and 1 respectively).

   ``valid_from``/``valid_until`` (both optional) are hard lower/upper
   bounds checked before all three modes below - the task never runs while
   ``today < valid_from`` or ``today > valid_until``. If the task has
   never run yet and today is already past ``valid_from``, it becomes due
   immediately (using today, not ``valid_from``, as the actual first
   ``last_run``). E.g. setting ``valid_from = 15.03.2026`` on a row
   activated on 20.03.2026 makes it run right away on 20.03.2026, not wait
   until the next scheduled date. ``valid_until`` just stops execution
   once passed - the row itself, and its ``last_run`` history, stay in
   place. ``validate()`` rejects a row where ``valid_until`` is before
   ``valid_from``.

   Three scheduling modes, checked by ``Contract._cron_task_is_due()`` in
   this priority order:

   1. **Day-of-month-based**: if ``schedule_day_of_month`` (1-31) is set,
      it takes priority over both interval fields — the task runs at most
      once a month, on or after that calendar day (capped to the last day
      of shorter months), guarded by comparing ``last_run``'s year/month
      to today's so a delayed run still catches up without re-running
      twice in the same month.
   2. **Month-interval-based**: otherwise, if ``interval_months`` is set,
      it takes priority over ``interval_days``. If ``valid_from`` is also
      set, ``Contract._add_months()`` computes the exact recurring date
      ``valid_from + k * interval_months`` months (same day-of-month as
      ``valid_from``, clamped to shorter months), advancing ``k`` past
      ``last_run`` each time - so e.g. ``valid_from = 15.03.2026`` with
      ``interval_months = 1`` runs on 15.03., 15.04., 15.05., ... and
      re-aligns to the correct slot even after a delayed run, instead of
      drifting from whatever date the delayed run actually happened on.
      Without ``valid_from``, falls back to a looser check: due once at
      least that many calendar months (year/month difference, not exact
      days) have passed since ``last_run`` - a convenience for longer
      rhythms (e.g. 6 for half-yearly) without day-of-month precision.
   3. **Day-interval-based** (default): otherwise, due once ``today -
      last_run >= interval_days`` (or ``last_run`` is unset).

   ``_cron_update_contract_status``
      Auto-terminates ``running`` contracts of the company whose
      ``end_date`` has passed and which have no active termination yet
      (``termination_date`` unset): sets ``state = 'terminated'``,
      ``termination_date = end_date``, ``terminated_by_type = 'expired'``,
      and a ``contract.log`` entry — reusing the existing ``terminated``
      state rather than adding a new one, so all state-dependent logic
      (occupancy, ``create_moves``, item validation) keeps working
      unchanged. See ``get_effective_end_date()`` (``termination_date`` if
      set and earlier than ``end_date``, else ``end_date``) which already
      governs occupancy for both ``running`` and ``terminated`` contracts
      regardless of whether this task has run yet.

   ``_cron_update_contract_cash_flow``
      **Cash-flow recalculation only** (``action='re_calc'``): calls
      ``Contract.call_create_moves()`` for all running/terminated contracts
      of the company up to ``today + create_moves_horizon_days``, so each
      term's ``ContractTermCashFlow`` stays generated ahead of time. It does
      **not** create invoices — booking is a separate, explicitly scheduled
      step, see ``_cron_book_contract_cash_flow`` below.

   ``_cron_book_contract_cash_flow``
      Books (creates draft invoices for) all due terms, using
      ``action='re_calc_and_create'`` so it is self-sufficient regardless of
      whether ``_cron_update_contract_cash_flow``'s horizon already covers
      the target date. The horizon is the end of the month that is
      ``horizon_months_ahead`` months after the run date — e.g. with
      ``schedule_day_of_month = 15`` and ``horizon_months_ahead = 1``, a run
      on 15.07 books everything due up to 31.08. Invoices are created in
      ``draft`` state — this task does **not** post them; posting remains a
      manual step.

   ``_cron_update_option_rate``
      Recomputes and, where the rate actually changed, books new option
      rates via ``OptionRate.process_update()`` (``option_rate.py`` — the
      same logic as the manual ``real_estate.option_rate_update.wizard``,
      see *Wizards* below) for every property of every company using this
      ``re_accounting`` configuration, as of today's date. Intended to run
      monthly with ``schedule_day_of_month = 1``, which also determines
      the ``effective_date`` used by ``process_update`` (the 1st of the
      current month). Per-record results (created/updated/unchanged/
      skipped counts, plus one detail line per processed object) go to the
      Python logger, not ``contract.log``, since this task is not tied to
      individual contracts.


Access Control
==============

Four user groups are provided. Access is additive — a user may belong to
multiple groups.

``group_real_estate_admin`` — **Real Estate Administration**
   Full CRUD on all module models. Intended for system administrators and
   property managers with unrestricted access. The built-in ``admin`` user
   is automatically assigned to this group at installation.

``group_real_estate_object`` — **Real Estate Object**
   Full CRUD on property and object data (``base_object``, ``address``,
   ``measurement``, ``meter_reading``, ``object_party``, ``occupancy``).
   Read-only access to contract, billing, and configuration models.
   Intended for facility managers who maintain the property master data
   but do not manage contracts or run settlements.

   *Exception:* also has full CRUD on ``real_estate.option_rate`` (in
   addition to ``group_real_estate_admin``), since option rates are
   maintained together with the property/object master data via the
   *Update Option Rates* wizard — see *Option Rate* below. The
   ``group_real_estate_contract`` and ``group_real_estate_billing`` groups
   remain read-only on it.

``group_real_estate_contract`` — **Real Estate Contract**
   Full CRUD on contract data (``contract``, ``contract.term``,
   ``contract.item``, ``contract.log``, ``contract.term.cash_flow``,
   ``contract.term.tax``, ``account_contract``).
   Read-only access to property, billing, and configuration models.
   Intended for property managers / letting agents.

   *Exception:* also has full CRUD on
   ``real_estate.contract.term.adjustment`` (in addition to
   ``group_real_estate_admin``) — see *Contract Term Adjustment* below. The
   ``group_real_estate_object`` and ``group_real_estate_billing`` groups
   remain read-only on it.

``group_real_estate_billing`` — **Real Estate Billing**
   Full CRUD on all operating cost and settlement models
   (``billing_unit``, ``billing_unit.log``, ``billing_unit.moves``,
   ``settlement_unit``, ``settlement_result``, ``cost_share``,
   ``cost_category_group``, ``cost_type``,
   ``account.configuration.real_estate``).
   Read-only access to property and contract models.
   Intended for the operating cost accountant who runs the annual
   settlement but does not modify contracts or property master data.

Permission matrix (``C`` = CRUD · ``R`` = read · ``—`` = no access):

.. list-table::
   :header-rows: 1
   :widths: 42 10 10 10 10

   * - Model
     - admin
     - object
     - contract
     - billing
   * - ``real_estate.address``
     - C
     - C
     - R
     - R
   * - ``real_estate.base_object``
     - C
     - C
     - R
     - R
   * - ``real_estate.base_object.occupancy``
     - C
     - C
     - C
     - R
   * - ``real_estate.option_rate``
     - C
     - C
     - R
     - R
   * - ``real_estate.meter_reading``
     - C
     - C
     - R
     - R
   * - ``real_estate.measurement.type``
     - C
     - R
     - R
     - R
   * - ``real_estate.use_class``
     - C
     - R
     - R
     - R
   * - ``real_estate.measurement``
     - C
     - C
     - R
     - R
   * - ``real_estate.object_party``
     - C
     - C
     - R
     - R
   * - ``real_estate.object_party.role``
     - C
     - R
     - R
     - R
   * - ``real_estate.contract``
     - C
     - R
     - C
     - R
   * - ``real_estate.contract.item``
     - C
     - R
     - C
     - R
   * - ``real_estate.contract.term``
     - C
     - R
     - C
     - R
   * - ``real_estate.contract.term.tax``
     - C
     - R
     - C
     - R
   * - ``real_estate.contract.log``
     - C
     - R
     - C
     - R
   * - ``real_estate.contract.account_contract``
     - C
     - R
     - C
     - R
   * - ``real_estate.contract.term.cash_flow``
     - C
     - R
     - C
     - R
   * - ``real_estate.contract.term.adjustment``
     - C
     - R
     - C
     - R
   * - ``real_estate.account_contract``
     - C
     - R
     - R
     - R
   * - ``real_estate.contract.type``
     - C
     - R
     - R
     - R
   * - ``real_estate.contract.term.type``
     - C
     - R
     - R
     - R
   * - ``real_estate.re_accounting``
     - C
     - R
     - R
     - R
   * - ``real_estate.cron_task``
     - C
     - R
     - R
     - R
   * - ``real_estate.co2_emission_share``
     - C
     - R
     - R
     - R
   * - ``real_estate.contract.type.tax``
     - C
     - —
     - R
     - R
   * - ``real_estate.cost_category_group``
     - C
     - R
     - R
     - C
   * - ``real_estate.cost_type``
     - C
     - R
     - R
     - C
   * - ``real_estate.co2_kostaufg``
     - C
     - R
     - R
     - C
   * - ``real_estate.co2_kostaufg.consumption``
     - C
     - R
     - R
     - C
   * - ``real_estate.billing_unit``
     - C
     - R
     - R
     - C
   * - ``real_estate.billing_unit.log``
     - C
     - R
     - R
     - C
   * - ``real_estate.billing_unit.moves``
     - C
     - R
     - R
     - C
   * - ``real_estate.settlement_unit``
     - C
     - R
     - R
     - C
   * - ``real_estate.cost_share``
     - C
     - C
     - C
     - C
   * - ``real_estate.settlement_result``
     - C
     - C
     - C
     - C
   * - ``account.configuration.real_estate``
     - C
     - R
     - R
     - R


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
   - ``next_billing_start_date`` (function field, property only): the
     earliest ``start_date`` among all non-``billed`` billing units of the
     property. Drives the *ready for billing* checks and the green
     line-color highlight in the billing unit list view.
   - Buttons ``compute_value_shares``, ``compute_settlement_result_property``,
     and ``ready_for_billing_property`` delegate bulk settlement actions to
     all billing units of the property that share ``next_billing_start_date``.
     ``billing_property`` opens the ``real_estate.billing_unit.wizard``
     instead of billing directly.
   - ``call_billing`` / ``do_billing`` (classmethods) run the actual billing
     for one or more properties, optionally in the background queue
     (``execute_in_queue``). ``do_billing`` requires every billing unit that
     would be billed to already be in state ``ready_for_billing``; with
     ``collective_billing`` all billing units sharing the same start date
     must be included together, otherwise a ``ValidationError`` is raised.

   *Rental object fields* (visible only for ``type = 'object'``):

   ``type_of_use``
      Economic use: ``residential``, ``commercial``, ``property``
      (owner-occupied), or ``internal``. Drives the contract-type filter.

   ``use_class``
      Many2One to ``real_estate.use_class``. Controls which additional
      fields (``basement_nr`` / ``parking_nr``) appear on the form.

   *Meter fields* (visible only for ``type = 'equipment'``, ``e_type = 'meters'``):

   ``meter_no_decimals``
      Boolean, default ``True``. When set, meter readings are validated and
      rounded to integer values. The estimate-consumption wizard and
      ``simulate_estimate`` respect this flag and round accordingly.

   Context classes for list views (``BaseObjectEquipmentContext``,
   ``BaseObjectOccupancyContext``, ``MeterReadingContext``) provide
   filterable search panels. Selection fields shared with the underlying
   model (e.g. ``e_type``, ``state``) are derived dynamically so their
   labels stay in sync automatically.

``real_estate.object_party.role``  (``object_party.py``)
   Configurable role definitions per object type
   (e.g. *Tenant* only for type ``object``, *Owner* for all types).

``real_estate.object_party``  (``object_party.py``)
   Links a ``party.party`` record to a ``BaseObject`` with a typed role
   and an optional validity period.

``real_estate.measurement.type``  (``measurement.py``)
   Named measurement type linked to a ``product.uom`` unit.

   Supports a **group hierarchy**: a type with ``is_group = True`` acts as
   a container grouping one or more child types via the ``parent`` Many2One
   field. Multi-level hierarchies are supported — groups can themselves have
   a parent group (e.g. *Gross Floor Area* → *Net Floor Area* → *Living Area*).

   Constraints enforced at save time:

   - All child types must share the same unit as their parent group.
   - Circular references (a group referencing one of its own descendants
     as parent) are rejected.
   - Only **leaf** (non-group) types can be assigned to individual
     ``real_estate.measurement`` records on ``BaseObject`` instances.

   When a group type is referenced in ``ContractTermType.m_type`` or in
   ``SettlementUnit.m_type``, the system automatically expands the group to
   all descendant leaf type IDs at query time, so measurements of any child
   type are included in the calculation.

``real_estate.measurement``  (``measurement.py``)
   Associates a numeric value and measurement type with a ``BaseObject``
   for a given validity period.

``real_estate.meter_reading``  (``base_object.py``)
   Meter reading record linked to an equipment object of type ``meters``.

   Key fields: ``company`` (stored, auto-filled from ``base_object`` on change),
   ``base_object``, ``meter_id``, ``reading_date``, ``m_type``
   (``initial`` / ``reading`` / ``estimate`` / ``final``),
   ``value``, ``unit`` (derived from the meter's ``meter_unit``),
   ``consumption`` (difference to previous reading for counter meters),
   ``comment`` (free text).

   Browseable via the *Meter Readings* menu entry under *Master Data*,
   filterable by company, property, parent object, equipment (meters only),
   and date range (``from_date`` / ``to_date``).

   **Consumption estimate** (``simulate_estimate`` / ``create_estimate``):

   ``simulate_estimate(base_object, per_date, meter_id=None)``
      Returns ``(estimated_value, consumption, r1, r2)``.
      Prefers **interpolation** when readings exist both before and after
      ``per_date``: takes the closest reading on each side and interpolates
      linearly between them.
      Falls back to **extrapolation** using the last two readings within
      one year before ``per_date`` when no future reading is available.
      Rounds the result to the meter's UOM digit precision; if
      ``meter_no_decimals`` is set on the meter, rounds to integers.

   ``create_estimate(base_object, per_date, reason, meter_id=None)``
      Calls ``simulate_estimate`` and saves a new reading with
      ``m_type = 'estimate'``.


Contract Management
-------------------

``real_estate.contract.type``  (``contract_type.py``)
   Template for contracts. Defines invoice direction (``in``/``out``),
   default taxes, accounting journal, number prefix, step sizes for item
   and term sequence numbers, and whether occupancy exclusivity is enforced.

   ``oc_mark``
      Free-text label used in operating cost settlement invoice descriptions
      and invoice headers, e.g. ``"Betriebskostenabrechnung 2025"``. Falls
      back to ``"Operating Cost Settlement"`` / ``"Operating Costs"`` when
      empty.

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
     via ``CreateContractMoves`` wizard (``call_create_moves``)
   - Cash flow tabs on the contract form: *Draft* (invoice state
     ``draft``/``validated``), *Pending* (``posted``), *Paid* (``paid``)
   - ``_refresh_occupancy_for_contracts`` updates occupancy records when
     a contract starts or is terminated; cancelled contracts are excluded
     from occupancy calculations automatically
   - ``add_log`` appends timestamped ``ContractLog`` entries
   - ``next_item_sequence`` / ``next_term_sequence`` auto-increment helpers

   ``settlement_units`` (Function field, ``get_settlement_units``)
      The contract's *last valid* settlement units: settlement units of the
      property's billing units whose objects overlap with the objects
      assigned to this contract via its items. Billing units are restricted
      to the property's ``next_billing_start_date`` (the earliest non-billed
      billing unit start date); if the property has none set, the most
      recently ``billed`` period is used instead. Used by
      ``get_cost_shares`` (cost shares of these settlement units belonging
      to the contract) and by ``real_estate.contract.annex4.report`` for the
      Anlage 4 print (see *Reports* below) — the report intentionally reuses
      this field instead of re-deriving the billing unit itself.

   **Fixed term / termination.** ``unlimited`` (Boolean, default ``True``)
   determines whether the contract has a fixed end date. Editable only in
   ``draft``:

   - ``unlimited = True`` (default) — ``end_date`` is readonly and must be
     empty; ``on_change_unlimited`` clears it automatically when toggled on.
   - ``unlimited = False`` — ``end_date`` becomes required and editable
     (only in ``draft``).
   - The invariant ("unlimited contract must not have an end date",
     ``msg_contract_unlimited_with_end_date``) is enforced by
     ``validate_fields`` only in ``draft`` — once ``running``/``terminated``
     it is no longer checked, since termination legitimately sets
     ``end_date`` regardless of ``unlimited`` (see below).

   The *Terminate* button (``real_estate.terminate_contract.wizard``, see
   *Wizards*) now also writes the resolved ``termination_date`` into
   ``end_date`` — so ``end_date`` always reflects the contract's actual
   end once terminated, fixed-term or not.

   Reactivating a **terminated** contract no longer uses the *Running*
   button (that button is now only shown for ``draft``/``cancelled``).
   Instead, a dedicated *Revert Termination* button
   (``revert_termination``, same underlying ``terminated → running``
   transition) is shown only for ``state = 'terminated'``. Besides
   clearing the termination fields (``termination_date``,
   ``terminated_by_type``, ``receipt_of_termination_notice``,
   ``termination_notice``, ``termination_reason`` — same as *Running*
   already did), it additionally clears ``end_date`` back to empty, but
   **only if the contract is ``unlimited``** — a fixed-term contract that
   was terminated early keeps whatever is in ``end_date`` after being
   reactivated.

   See also the ``update_contract_status`` cron task (*Configuration*
   above) for the automatic ``expired`` termination of fixed-term
   contracts whose ``end_date`` has passed without an active termination.

   **Cancellation:** the *Cancel* button transitions the contract to
   *Cancelled*.  Before the transition:

   - If any cash flow entry in state ``done`` (already invoiced) exists,
     a ``ContractCancelWarning`` is shown explaining that existing postings
     will **not** be reversed automatically.  The user must confirm to proceed.
   - All cash flow entries still in state ``draft`` are deleted.
   - Occupancy records are recalculated; the cancelled contract is excluded.

``real_estate.contract.log``  (``contract_core.py``)
   Append-only audit log attached to a contract (event name + description).

``real_estate.contract.item``  (``contract_item.py``)
   Associates a ``base_object`` of type ``object`` (e.g. an apartment)
   with a contract for a given validity period.
   On create/write/delete, triggers occupancy refresh and re-runs
   BillingUnit selection and value-share calculation for the affected property.
   Validates that ``valid_from`` lies within the contract period and raises
   a warning (or error for active contracts) on overlapping occupancy.

   Each ``ContractItem`` can reference one or more rental objects via the
   ``real_estate.contract.item.object`` child model. The object selector
   always restricts to objects belonging to the **same property** as the
   contract (preventing cross-property assignments); it is additionally
   restricted to ``type = 'object'`` only for **occupancy contracts**
   (``contract.c_type.occupancy`` set — the Function field ``occupancy`` on
   ``ContractItemObject`` mirrors this from the contract type). Non-occupancy
   contract types may reference any ``base_object`` type (building, land,
   equipment, …) belonging to the property. A unique SQL constraint on
   ``(item, object)`` prevents assigning the same object twice to the same
   item; the same object may still be assigned to a different item (e.g. on
   another contract).

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

   *States:* ``draft`` (planned, no invoice line yet) · ``done`` (invoiced)

   *Invoice states* (computed from the linked invoice):
   ``draft`` / ``validated`` — not yet posted (excluded from settlement
   calculations); ``posted`` — open receivable; ``paid`` — settled.
   Only ``posted`` and ``paid`` entries appear in the balance sheet and
   are used as *advance payment* in operating cost settlement.

   Stores ``posting_date``, ``document_date``, ``due_date``, and a link to
   the ``account.invoice.line`` once billed.
   ``base_object`` (function field) is derived from the linked invoice line
   and used to key advance payments to a (contract, object) pair during
   operating cost settlement.
   ``create_moves_run_id`` (format ``YYYYMMDD-HHMMSS-U<userid>``) is set
   for all cash flow entries created in a single ``CreateContractMoves`` run,
   allowing traceability back to the wizard invocation.
   Supports date-pattern search (``YYYY/MM`` or ``YYYY/MM/DD``) in the name field.

``Quantitative``  (``contract_term.py``)
   Custom ``fields.Numeric`` subclass that carries a ``unit`` reference and
   sets ``quantitative=True`` in its field definition so the UI renders the
   associated unit symbol.

``real_estate.contract.term.adjustment``  (``contract_term.py``)
   History record documenting a single old-term → new-term adjustment
   (e.g. a rent/advance-payment change following an operating cost billing
   run, an operating cost plan, or a free percentage/absolute change).

   *States:* ``draft`` · ``approved``

   Key fields: ``adjustment_mode`` (``percentage`` / ``absolute``),
   ``term_old`` (required, ``ondelete='RESTRICT'``), ``term_new``
   (``ondelete='RESTRICT'``, set once the replacement term exists), and an
   optional ``settlement_result`` link when the adjustment originates from
   an operating cost billing run.

   Function fields mirror ``company`` / ``property`` / ``contract`` from
   ``term_old``, and ``valid_from`` / ``valid_to`` / ``amount`` /
   ``tax_amount`` / ``total_amount`` from both ``term_old`` (suffix
   ``_old``) and ``term_new`` (suffix ``_new``), so a reviewer can compare
   the before/after amounts without opening either term individually.

   Browseable read-only via the *Contract Term Adjustments* menu entry
   under *Contracts → Adjustment*.

   .. note::
      Only the data model and its history/comparison fields exist so far —
      nothing currently creates these records. See the *Adjustment of
      Contract Terms* wizard (below, under *Wizards*), which defines the
      full input mask but still has placeholder processing logic only.


Operating Cost Settlement
--------------------------

``real_estate.cost_category_group``  (``billing_unit.py``)
   Groups cost types for reporting, e.g. *Heating*, *Water*, *Janitorial*.

``real_estate.cost_type``  (``billing_unit.py``)
   Individual cost item (e.g. *Gas*, *Cold Water*) with optional
   ``category_group``, ``comment``, and ``no_print`` flag.

   For ``allocation_by_consumption`` settlement units, two fields control the
   meter-reading tolerance window around the start/end date of each cost share:

   ``reading_pre_days``
      Days *before* the target date within which a reading is accepted (default: 7).

   ``reading_post_days``
      Days *after* the target date within which a reading is accepted (default: 7).

   The reading closest to the target date within the window is used.
   If no reading is found, an error is stored on the cost share.

``real_estate.billing_unit``  (``billing_unit.py``)
   Annual (or period) operating cost settlement for one property.

   *Workflow:* Draft → Approved → Selection → Value Share → Ready for Billing → Billed

   ``external_billing``
      Boolean flag. When enabled, every settlement unit of the billing unit
      is forced to ``allocation_rule = allocation_from_external_billing``
      (see ``real_estate.settlement_unit`` below) and costs are entered
      manually instead of being computed internally.

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
      Available in states ``approved``, ``selection``, ``value_share``, and
      ``ready_for_billing`` (re-running from ``value_share`` /
      ``ready_for_billing`` revises the scope; existing settlement results
      are deleted after confirmation).

   ``compute_value_shares_button``
      Calculates allocation shares (``CostShare``) for each settlement unit.
      Available in states ``selection``, ``value_share``, and
      ``ready_for_billing``. If settlement results already exist for the
      billing unit, a confirmation warning is shown before they are deleted
      and value shares are recomputed. Does **not** automatically call
      ``compute_settlement_result``. If any settlement unit has
      ``sub_state = error`` the billing unit is *not* advanced to
      ``value_share``; the error is written to the billing unit log instead.

   ``compute_settlement_result``
      Derives ``SettlementResult`` records per (contract, base_object) pair —
      actual costs, advances paid (only ``posted``/``paid`` invoice lines),
      and the resulting refund or additional receivable. Advance payments
      are matched to cost shares by the same (contract, object) key. If an
      advance-payment cash flow line has no matching cost-share group
      (e.g. no object on older invoices, or several terms for the same
      object) a fallback ``SettlementResult`` with ``actual_costs = 0`` and
      a full refund is created for it; the fallback count is logged.
      Sets affected ``CostShare`` records to state ``error`` if any
      cash flow entries in the period are still in ``draft``/``validated``
      state; the error message is prefixed with ``[draft]`` so it can be
      reset on re-run once the drafts are posted or deleted.
      Resets a billing unit already in state ``ready_for_billing`` back to
      ``value_share`` before recomputing.

   ``check_ready_for_billing``
      Transitions ``value_share`` → ``ready_for_billing`` after validating:

      - no settlement unit has ``sub_state = error``;
      - every settlement unit (except ``no_allocation``) has reached
        ``sub_state = value_share``;
      - at least one ``approved`` ``SettlementResult`` exists and none has
        ``actual_costs = 0``;
      - every settlement result with a non-zero advance payment has both a
        ``term`` and a ``contract`` (a missing term usually means several
        term types contributed and the billing unit's term-type filter
        needs narrowing);
      - all advance-payment invoices are posted;
      - (unless ``external_billing``) the sum of settlement result actual
        costs matches the sum of cost share actual costs.

      Any failed check raises a ``ValidationError`` listing the offending
      records. Can also be triggered per property via
      ``BaseObject.ready_for_billing_property`` for all billing units
      sharing ``next_billing_start_date``.

   ``billing_wizard`` / ``billing``
      The form button ``billing_wizard`` opens the
      ``real_estate.billing_unit.wizard`` (see *Wizards* below), which
      calls the ``billing`` classmethod. ``billing`` creates, per
      settlement result, up to two invoice lines — advance-payment
      dissolution and actual costs — with taxes copied from the
      advance-payment term, then one invoice per contract. Invoices are
      created in state ``draft`` and posted immediately if the wizard's
      ``invoice_state`` is ``posted``. Each invoice's ``payment_term`` (and
      therefore its due date) is taken from the wizard's ``payment_term``
      field when set; otherwise the contract's own payment term is used,
      falling back to ``account.configuration``'s
      ``re_payment_term_billing``.
      Both ``invoice_date`` and ``accounting_date`` are set to the wizard's
      ``invoice_date`` (analogous to the ``accounting_date`` on contract
      invoices generated by ``CreateContractMovesWizard``), so the posting
      date matches the invoice date rather than the date the wizard was run.
      Refuses to proceed if ``sub_state`` is ``error`` or if draft cash
      flow lines still exist in the settlement period; with
      ``collective_billing`` all billing units of the property sharing the
      same start date must already be ``ready_for_billing``.
      Generates a ``billing_run_id`` (``YYYYMMDD-HHMMSS-U<userid>``) that
      is written to the billing unit and all ``BillingUnitMoves`` records
      of the same run, so every posting can be traced back to its run.
      Hidden when the property has ``collective_billing = True``; in that
      case the action is triggered from the property form instead
      (``BaseObject.billing_property`` → same wizard →
      ``BaseObject.do_billing``).

   ``billing_run_id``
      Char field set at the end of a successful ``billing()`` call,
      identical to the value written to all ``BillingUnitMoves`` of that run.

``real_estate.billing_unit.log``  (``billing_unit.py``)
   Timestamped log entries attached to a billing unit.

``real_estate.billing_unit.moves``  (``billing_unit.py``)
   One record per invoice line created by ``billing()`` — a separate
   record for the advance-payment dissolution line and for the
   actual-costs line of the same settlement result (not combined into one
   record). Links the billing unit to the contract, settlement result,
   and the individual posting record:

   - ``moves_advanced_payment`` — ``account.invoice.line`` that reverses
     the operating-cost advance (credit note line)
   - ``moves_actual_costs`` — ``account.invoice.line`` for the actual costs
   - ``moves_alloc_by_owner`` — ``account.move.line`` for the owner
     allocation journal entry

   Function fields ``amount``, ``currency``, and ``invoice`` are derived
   from whichever of ``moves_advanced_payment`` / ``moves_actual_costs`` is
   set, for quick display in the tree view without opening the invoice line.
   For vacancy records (no ``contract``, but ``moves_alloc_by_owner`` set),
   ``amount`` is instead computed as ``debit - credit`` of that
   ``account.move.line``, ``currency`` from its own ``currency`` field, and
   ``invoice`` stays empty (move lines have no invoice reference).

   ``billing_run_id`` ties all moves of one billing run together
   (same value as on the parent ``BillingUnit``).
   Browseable via the *Billing Unit Moves* menu entry under
   *Operation Costs*, filtered by company, property, billing unit,
   contract, and date range.

``real_estate.settlement_unit``  (``settlement_unit.py``)
   One cost-type line within a billing unit, e.g. *Gas 2024*.

   *Allocation rules:*

   ``no_allocation``
      Entire cost stays unallocated.

   ``allocation_by_measurement``
      Allocated by a measurement value, e.g. living area.
      ``value_share`` = ``measurement_value × time_share / time_total``
      (time-weighted: a tenant occupying only part of the period receives
      a proportionally smaller share).

   ``allocation_by_consumption``
      Allocated by meter reading consumption (HeizkostenV).
      ``value_share`` = raw consumption (no time weighting applied).

      Meter readings are looked up within a tolerance window defined by
      ``reading_pre_days`` / ``reading_post_days`` on the cost type; the
      closest reading to the target date is chosen.

      **Vacancy handling:** cost shares without a contract receive
      ``value_share = 0`` automatically — no meter reading is required.
      For the immediately following contract cost share, if no start reading
      exists within the normal window, the system falls back to the reading
      taken at the start of the preceding vacancy. This allows a single
      read-out at move-out to serve as both the vacancy baseline and the
      contract's opening reading.

      Missing readings set the cost share to state ``error`` with one of:

      - *"Messwert für Anfangsverbrauch nicht ermittelt"* — start reading absent
      - *"Messwert für Endverbrauch nicht ermittelt"* — end reading absent

   ``allocation_per_rental_unit``
      Proportional share by occupancy duration.
      ``value_share`` = ``time_share / time_total``
      (full period = 1.0, half period = 0.5, etc.).

   ``allocation_from_external_billing``
      No internal calculation; ``planned_costs``/``actual_costs`` are entered
      manually on the cost share. Automatically set on every settlement unit
      of a billing unit when that billing unit's ``external_billing`` flag is
      enabled (see ``real_estate.billing_unit`` below); the settlement unit's
      ``allocation_rule`` then becomes read-only.

   Vacancy handling: unoccupied periods can be charged to the owner or left
   unallocated.

   When ``compute_value_shares`` is re-run, cost shares in state ``error``
   are automatically reset to ``selection`` and their ``error_message``
   cleared before the new calculation starts, so corrected readings or
   measurements take effect immediately.

``real_estate.cost_share``  (``settlement_result.py``)
   Intermediate allocation record: share of a specific cost type for one
   contract or object within a billing period.

   *States:* ``preparation`` · ``selection`` · ``estimated_value_share``
   · ``value_share`` · ``error``

   Stores ``value_share`` (time-weighted allocation factor — for
   ``allocation_by_measurement`` and ``allocation_per_rental_unit`` this
   already incorporates the occupancy fraction ``time_share / time_total``;
   for ``allocation_by_consumption`` it holds the raw consumption value),
   ``time_share`` (days), ``planned_costs``, ``actual_costs``.
   ``error_message`` describes the problem; entries set by
   ``compute_settlement_result`` carry a ``[draft]`` prefix and are
   automatically cleared on the next successful re-run.

   ``allocation_rule`` / ``external_billing`` (Function fields, mirrored)
      Mirrored from the parent ``settlement_unit``.
      ``planned_costs``/``actual_costs`` are only editable
      (``readonly`` otherwise) when ``external_billing`` is set, i.e. for
      cost shares of a settlement unit with
      ``allocation_rule = allocation_from_external_billing``.

``real_estate.settlement_result``  (``settlement_result.py``)
   Final settlement record per contract (or object) and billing unit.

   *States:* ``approved`` · ``billed``

   Stores ``planned_costs``, ``actual_costs``, ``advanced_payment``
   (sum of ``posted``/``paid`` operating-cost advance invoice lines during
   the period), and the derived ``refund_receivable`` (positive = refund
   to tenant, negative = additional receivable).
   Optionally links to the single ``ContractTerm`` that covered all advances
   when exactly one term was involved.
   The display name includes the record id in parentheses
   (e.g. ``"2026-01-01 – 2026-12-31 / Mieter 1 (42)"``) to disambiguate
   several results for the same contract/object; the id is also searchable
   via the name field.


CO2 Cost Allocation (CO2KostAufG)
-----------------------------------

Implements the German *CO2-Kostenaufteilungsgesetz* (CO2KostAufG), which
splits the CO2 cost of heating fuel between tenant and landlord depending on
the building's emission intensity (kg CO2/m²/year). Applies to
``real_estate.settlement_unit`` (typically the *Heizkosten* settlement unit
of a billing unit) via an optional reference to a ``real_estate.co2_kostaufg``
master record — settlement units without a reference are unaffected.

``real_estate.co2_kostaufg``  (``co2_kostaufg.py``)
   Master record for one CO2KostAufG data source (e.g. one heating
   installation/fuel), scoped to a ``property`` (required, ``type =
   'property'``) with ``company`` derived from it (Function field).
   Referenced from one or more settlement units of the same property via
   their ``co2_kostaufg`` field (domain-restricted to that property — a
   settlement unit can only pick a CO2KostAufG belonging to its own
   property).
   Menu: *Real Estate → Operation Costs → CO2 Kosten verwalten*.

``real_estate.co2_kostaufg.consumption``  (``co2_kostaufg.py``)
   Child records under a ``co2_kostaufg`` (``parent``, ``ondelete='CASCADE'``),
   one per billed/metered period: ``date_from``/``date_to``,
   ``consumption_kwh``, ``co2_kg_per_kwh`` (emission factor),
   ``co2_emission_kg``, ``co2_price_ct_per_kwh``, ``vat_rate``,
   ``co2_cost_net``, ``co2_cost_gross``.

   ``co2_emission_kg`` is pre-filled (``consumption_kwh × co2_kg_per_kwh``)
   only while still empty — once any value exists (auto-filled or typed by
   the user), later changes to ``consumption_kwh``/``co2_kg_per_kwh`` never
   overwrite it again, so it is always freely (re-)editable, e.g. to enter
   the supplier's own figure. ``co2_cost_net``/``co2_cost_gross`` behave
   differently **on purpose**: they are always recomputed from
   ``consumption_kwh``/``co2_price_ct_per_kwh``/``vat_rate`` whenever any of
   those three change; a manual override of net/gross only sticks until the
   next such recompute.

   ``split``
      Boolean. Set automatically by
      ``SettlementUnit.compute_value_shares()`` when this record was
      created by splitting an original record at a settlement-period
      boundary — see *Splitting at settlement-period boundaries* below.

   Uses ``DeactivableMixin`` — a record replaced by a split is deactivated
   (``active = False``), never physically deleted.

``real_estate.co2_emission_share``  (``co2_kostaufg.py``)
   Configuration table for the legal 10-tier distribution model (Anlage 1
   CO2KostAufG, residential rented buildings without separate sub-metering
   by usage type): ``emission_limit`` (kg CO2/m²/year — the *exclusive*
   upper bound of the tier), ``tenant_share`` / ``landlord_share`` (%, must
   sum to 100 — enforced in ``validate()``).
   ``get_share(value)`` returns the first row, in ``sequence`` order, whose
   ``emission_limit`` is strictly greater than ``value``; if ``value``
   reaches or exceeds every configured limit, the last row (by sequence) is
   used as an open-ended top tier regardless of its own stored limit value.
   Default data for all 10 legal tiers is loaded at module installation
   (< 12 kg → 0 % / 100 % landlord/tenant … ≥ 52 kg → 95 % / 5 %).
   Menu: *Real Estate → Configuration → Emission-CO2 Verteilung*.

Fields added to ``real_estate.settlement_unit`` — a new *CO2 Costs* page is
always shown, but every field on it except ``co2_kostaufg`` itself stays
hidden (``invisible``) until a reference is actually set:

   ``co2_kostaufg``
      Many2One reference, restricted to CO2KostAufG records of the same
      ``property`` as the settlement unit.

   ``co2_measurement_type``
      Many2One to ``real_estate.measurement.type`` (object-type
      measurements only) — which measurement to sum across the settlement
      unit's ``objects`` for the area basis below. Independent of the
      settlement unit's own ``m_type`` (used for
      ``allocation_by_measurement``).

   ``co2_total_consumption`` / ``co2_total_emission`` / ``co2_total_cost_gross``
      (Function.) Sum of ``consumption_kwh`` / ``co2_emission_kg`` /
      ``co2_cost_gross`` across all consumption records of the referenced
      CO2KostAufG that overlap the settlement period (the parent billing
      unit's ``start_date``/``end_date``), each weighted by the fraction of
      the record's *own* date range that actually falls inside the period.
      A record fully inside the period contributes 100 %; a record
      extending beyond either boundary is interpolated pro-rata by days,
      always relative to its own actual range — a record that simply
      doesn't reach as far as the period's end (no later data booked yet)
      is never extrapolated, it only ever contributes its own days.

   ``co2_total_area``
      (Function.) Sum, across the settlement unit's ``objects``, of each
      object's latest ``real_estate.measurement`` value of
      ``co2_measurement_type`` (or its effective leaf types, if a
      measurement group) valid as of ``end_date``.

   ``co2_emission_per_m2``
      (Function.) ``co2_total_emission / co2_total_area``, annualized via
      ``× 365 / time_total`` so that settlement periods shorter or longer
      than a calendar year still yield a correct "kg CO2/m²/year" figure.

   ``co2_tenant_share`` / ``co2_landlord_share``
      (Function.) Looked up via
      ``Co2EmissionShare.get_share(co2_emission_per_m2)`` — the residential
      10-tier split.

   ``co2_commercial_tenant_share`` / ``co2_commercial_landlord_share``
      (Function.) The flat split used for commercial properties (not
      covered by the residential tier model): the company's configured
      ``re_accounting.co2_landlord_share_commercial`` (landlord), and
      ``100 %`` minus that value (tenant).

   ``co2_consumption``
      (Function, One2Many, readonly.) All consumption records of the
      referenced CO2KostAufG that overlap the settlement period — shown as
      an embedded, read-only table at the bottom of the *CO2 Costs* page.

**Splitting at settlement-period boundaries.**
``SettlementUnit.compute_value_shares()`` ("Compute Value Shares" button,
also reachable via the billing unit's own button of the same name) calls
``_split_co2_consumption()`` first, before anything else. For each of
``start_date`` and ``end_date + 1 day``, every active consumption record of
the referenced CO2KostAufG whose own ``[date_from, date_to]`` strictly
contains that boundary date is split into two new records at that date:
amounts are interpolated pro-rata by day count (the second part is computed
as the remainder of the first, so the two new records always sum back
exactly to the original — no rounding drift); rate fields
(``co2_kg_per_kwh``, ``co2_price_ct_per_kwh``, ``vat_rate``) are copied
unchanged onto both. Both new records get ``split = True``; the original is
deactivated (soft-deleted via ``active``), never physically removed. A
record entirely inside the settlement period, or one that only covers part
of it because no later data has been booked yet, is never split or
extrapolated — only an *existing* record that actually spans across a
period boundary gets divided. Re-running is idempotent: already
boundary-aligned active records are left untouched, so repeated calls never
produce duplicate splits.


Option Rate (Input VAT Deduction)
----------------------------------

Tracks, over time, what percentage of input VAT (Vorsteuer) on purchase invoices
related to a real estate object is deductible ("optiert") rather than treated
as a final cost (added to the gross expense) — relevant wherever the property
owner can opt for VAT liability on rent (§ 9 UStG). Applies to
``real_estate.base_object`` (property / building / land / rental object),
``real_estate.settlement_unit``, and ``real_estate.billing_unit``.

``account.invoice.line.taxes_deductible_rate`` auto-fill  (``invoice.py``)
   For purchase invoice lines (``invoice_type = 'in'``), the core
   ``taxes_deductible_rate`` field (0–1 fraction of input VAT that is
   deductible; core already forces it to ``0`` when
   ``company.purchase_taxes_expense`` is set, via its own
   ``on_change_company``) is auto-filled from the applicable option rate,
   divided by 100. Applies both interactively (``on_change_base_object`` /
   ``on_change_settlement_unit`` / ``on_change_billing_unit``) and to
   programmatic line creation (``InvoiceLine.create()`` override) — the
   latter only fills the field when the caller did **not** pass
   ``taxes_deductible_rate`` explicitly, so an explicit value is never
   overridden.

   The real-estate reference used is picked by
   ``InvoiceLine._option_rate_priority()`` in order of specificity:
   ``base_object`` → ``settlement_unit`` → ``billing_unit`` → the derived
   ``property`` (as a ``base_object`` reference, last-resort fallback via
   ``on_change_with_property`` / ``term.property``) — the first of these
   that is set on the line wins.
   ``OptionRate.get_current_rate_fraction(ref_field, record, date)`` then
   returns the record's latest ``option_rate`` at or before that date
   (``taxes_date`` if set, else the invoice's ``invoice_date``, else
   today), divided by 100; falling back to ``1``/``0`` for
   ``fix_100``/``fix_0`` if no history record exists yet, or ``None``
   (leaving the field untouched) for ``dynamic_measurement`` with no
   booked history.

   The auto-fill is skipped entirely (field left at its core default of
   ``1``) when: the line is not a purchase line, or the company has
   ``purchase_taxes_expense`` set (core's own logic already governs that
   case). The line's ``contract`` field has no bearing on this logic and
   is ignored — a real-estate reference is used whenever present, even on
   a line that also carries a ``contract``.

``real_estate.option_rate``  (``option_rate.py``)
   History-versioned option rate record, valid from a given date. Has three
   mutually exclusive Many2One reference fields — ``base_object``,
   ``settlement_unit``, ``billing_unit`` (all ``ondelete='CASCADE'``) — exactly
   one of which must be set (enforced in ``validate()``); a unique SQL
   constraint prevents two records for the same reference and ``valid_from``.
   ``option_rate`` is a percentage (``digits=(5, 2)``, domain 0–100).

Fields added to ``real_estate.base_object``, ``real_estate.settlement_unit``,
and ``real_estate.billing_unit`` (identical on all three):

   ``option_rate_method``
      Required selection: ``fix_0`` (always 0 %), ``fix_100`` (always 100 %),
      or ``dynamic_measurement`` (calculated — see the wizard below).
      Defaults to ``fix_0``. On a rental object (``base_object`` with
      ``type = 'object'``), changing ``type_of_use`` auto-sets it to
      ``fix_100`` for ``commercial`` and ``fix_0`` otherwise
      (``on_change_type_of_use``); ``dynamic_measurement`` is rejected by
      ``validate_fields`` for rental objects — only property/building/land/
      settlement unit/billing unit may use it.

   ``option_measurement_type``
      Many2One to ``real_estate.measurement.type``, required only for
      ``dynamic_measurement``. May reference a measurement **group**: all of
      its descendant leaf types are then summed per rental object (see the
      group hierarchy under ``real_estate.measurement.type`` above).

   ``option_rates``
      One2Many (readonly) to the object's own ``real_estate.option_rate``
      history.

   ``purchase_taxes_expense``
      Function field mirroring the pre-existing ``company.purchase_taxes_expense``
      field (added by ``account_invoice``). When set on the object's company,
      all input VAT is always booked as an expense (fully gross) —
      equivalent to a permanent option rate of 0 % — and the *Option Rate*
      notebook page is hidden on the form (also always hidden for
      ``type = 'equipment'``).

   Shown as a dedicated *Option Rate* page on the ``base_object``,
   ``settlement_unit``, and ``billing_unit`` forms (``page_option_rate``).

``real_estate.option_rate_update.wizard``  (see *Wizards* below)
   Batch recalculation entry point; see the *Wizards* section for the full
   selection/calculation logic.

**Selection / filter screen and standalone list.** Menu:
*Real Estate → Master Data → Update Option Rates*, with a child menu item
*Option Rates* opening a read-only list of all ``real_estate.option_rate``
records (both list and form views are fully non-editable —
``creatable="0"`` plus ``readonly="1"`` on every field; this applies only to
the standalone list, not to the ``option_rates`` tab embedded in the
base_object/settlement_unit/billing_unit forms, which remains editable
there). A *Selektion* context form — modelled on the *Occupancy* context
pattern (``real_estate.option_rate.context``, class ``OptionRateContext``) —
sits above the list with three optional filter fields, ``base_object``,
``billing_unit``, ``settlement_unit``; whichever one is set narrows the list
via ``context_domain`` (PYSON, evaluated independently per field, so any
combination — or none — can be applied).


Extensions to Core Modules
---------------------------

``party.party``  (``party.py``)
   Adds ``sequence`` (integer sort key) and ``salutation`` fields.

``account.invoice``  (``invoice.py``)
   Adds a ``contract`` Many2One field so invoices can be traced back to the
   originating contract. Shown on the invoice form's *Other Info* tab
   (view extension ``view/invoice_form.xml``, inherits
   ``account_invoice.invoice_view_form``).

``account.invoice.line``  (``invoice.py``)
   Adds real-estate assignment fields, gated by ``assignment_control``
   (Selection: *All*, ``contract``, ``operating_costs``,
   ``settlement_result_contract``, ``settlement_result_vacant`` — controls
   which of the fields below are visible/required for a given line):

   - ``contract`` / ``term`` — the originating ``real_estate.contract`` /
     ``ContractTerm``
   - ``base_object`` — the real-estate object the line relates to
   - ``billing_unit`` / ``settlement_unit`` — for operating-cost billing lines
   - ``property`` (Function) — derived from ``billing_unit``/``settlement_unit``
   - ``service_period_from`` / ``service_period_to`` — billed service period
   - ``estg_35a`` (Selection) — German §35a EStG tax-deduction category
     (household services / craftsmen services)
   - ``invoice_date``, ``tax_amount``, ``total_amount`` (Function fields)

   Indexed on ``contract``, ``term``, ``settlement_unit``, ``billing_unit``.

``account.move.line``  (``invoice.py``, class ``AccountMoveLine``)
   Mirrors the same real-estate fields as ``account.invoice.line`` above
   (``assignment_control``, ``contract``, ``term``, ``base_object``,
   ``billing_unit``, ``settlement_unit``, ``property``) directly on the
   journal entry line, so postings can be traced/filtered without going
   through the invoice line. Extended list view shows this context for
   journal entries.

``account.general_ledger.line``  (``invoice.py``, class ``GeneralLedgerLine``)
   Adds ``contract``, ``term``, ``base_object``, ``billing_unit``, and
   ``settlement_unit`` (all readonly Many2One) to Tryton's standard General
   Ledger — Lines report (German: *Kontenblätter – Positionen*), so the
   individual postings for an account can be filtered/traced back to the
   originating real-estate contract, term, object, billing unit, or
   settlement unit. No override of ``table_query`` is needed: it pulls any
   non-Function field straight from the ``account.move.line`` table by
   matching field name, and ``account.move.line`` already carries these same
   fields (see above). Shown as optional columns in the tree view
   (``view/general_ledger_line_list.xml``, inherits
   ``account.general_ledger_line_view_list``).

``account.configuration``  (``account_configuration.py``)
   Extends the standard account configuration with real-estate-specific
   defaults used during operating cost billing:

   ``re_account_allocation_by_owner``
      Vacancy cost account (debit and credit side of vacancy postings).

   ``re_journal_billing``
      Journal used for direct GL postings in vacancy settlements.

   ``re_payment_term_billing``
      Default payment term for operating cost settlement invoices. Pre-fills
      the ``payment_term`` field of the ``real_estate.billing_unit.wizard``;
      also used directly by ``BillingUnit.billing()`` as a final fallback
      when neither the wizard's ``payment_term`` nor the contract's own
      payment term is set.

   All three are per-company ``MultiValue`` fields backed by
   ``account.configuration.real_estate``.

``res.user``  (``res.py``)
   Adds ``phone`` and ``mobile`` fields.


Wizards
=======

``real_estate.contract.create_moves.wizard``  (``contract_wizard.py``, class ``CreateContractMovesWizard``)
   Batch invoice generation wizard. Supports three actions:

   ``create``
      Generate invoices up to a given date. All ``ContractTermCashFlow``
      entries created in this run share the same ``create_moves_run_id``
      (``YYYYMMDD-HHMMSS-U<userid>``).

   ``re_calc``
      Rebuild cash flow projections without creating invoices.

   ``re_calc_and_create``
      Combine both steps.

   Can be filtered by property and/or contract list.
   Optional queue execution via ``execute_in_queue``.

``real_estate.billing_unit.wizard``  (``billing_unit_wizard.py``, class ``BillingUnitWizard``)
   Batch billing wizard, opened via the ``billing_wizard`` button on the
   billing unit form or the ``billing_property`` button on the property form.

   *Start* — ``date`` (default: last day of the current month), ``company``,
   ``invoice_date`` (default: today; auto-set to the first of ``date``'s
   month when ``date`` lies in the past), ``invoice_state``
   (``draft`` / ``posted`` — invoices are posted immediately when
   ``posted``), ``payment_term`` (default: ``account.configuration``'s
   ``re_payment_term_billing``; written to every invoice created by the run
   and therefore drives its due date — takes priority over the contract's
   own payment term), ``execute_in_queue`` (default ``True``), optional
   ``propertys`` / ``billing_units`` filters (pre-filled from the active
   record when launched from a property or billing unit form/list).

   *Confirm* — read-only summary of the matching billing unit count and the
   selected filters before processing.

   *Process* (``transition_do_billing``) — calls
   ``BaseObject.call_billing`` for the resolved properties, which invokes
   ``BaseObject.do_billing`` either directly or via the background queue.
   Only billing units already in state ``ready_for_billing`` are billed;
   with ``collective_billing`` all billing units of a property sharing the
   same start date must be included, otherwise a ``ValidationError`` is
   raised.

   *Result* — reports how many billing units were queued or processed.

``real_estate.terminate_contract.wizard``  (``contract_wizard.py``)
   Sets a contract to *Terminated*, records ``terminated_by``,
   ``receipt_of_termination_notice``, ``termination_reason``, and
   calculates ``termination_date`` from the notice period
   (3 / 6 / 9 / 12 months to end of month); also writes the resolved
   ``termination_date`` into the contract's ``end_date`` (see *Fixed term /
   termination* under ``real_estate.contract`` above). ``terminated_by_type``
   is ``tenant`` or ``landlord`` for a manual termination via this wizard;
   see the ``update_contract_status`` cron task above for the automatic
   ``expired`` case (fixed-term contracts with no active termination), and
   the *Revert Termination* button to undo a termination.

``real_estate.estimate_consumption.wizard``  (``base_object.py``, class ``EstimateConsumptionWizard``)
   Two-step wizard launched from the *Meters* tab of any approved meter
   object. Estimates the meter reading for a chosen cut-off date and
   books it as an ``estimate`` reading.

   *Step 1 – Start:* displays the meter description, unit and factor,
   pre-fills ``meter_id`` from the last reading, and prompts for
   ``per_date`` (default: today) and a free-text ``reason``.

   *Step 2 – Result:* calls ``simulate_estimate`` and shows the two
   basis readings (``reading1`` / ``reading2``), the derived
   ``consumption``, and the editable ``estimated_value``. The user can
   adjust the value before booking.

   *Book:* saves a new ``MeterReading`` with ``m_type = 'estimate'``.
   The value is rounded to the meter's UOM digit precision (integer if
   ``meter_no_decimals`` is set) before saving.

``real_estate.option_rate_update.wizard``  (``option_rate_wizard.py``, class ``OptionRateUpdateWizard``)
   Recomputes and books option rates (see *Option Rate* above) for a
   selection of base objects, billing units, and/or settlement units, as of
   a cut-off date.

   *Start* — ``base_objects`` (Many2Many, restricted to
   property/building/land/rental object; an approved property/building/land
   is expanded to its building/land/rental-object descendants, and an
   approved property additionally cascades to its billing units and their
   settlement units), ``billing_units`` (expanded to their settlement
   units), ``settlement_units``, ``cutoff_date`` (default: today — booked
   option rates are always dated on the first of this month).

   *Confirm* — read-only counts of the directly selected base objects /
   billing units / settlement units, and the total number of objects that
   will actually be processed after expansion (``n_expanded``).

   *Process* (``OptionRate.process_update``) — for every expanded object:

   - Objects with ``option_rate_method`` ``fix_0`` / ``fix_100`` are booked
     at 0 % / 100 % directly, without looking at any sub-objects.
   - ``dynamic_measurement`` objects are calculated from their approved
     rental objects: for a rental object, itself; for a property/building/
     land, its approved rental-object descendants regardless of how many
     buildings/land lie in between (a non-approved intermediate object
     excludes its whole subtree — both from booking and as a calculation
     basis); for a settlement unit, its existing ``objects`` function field
     (i.e. whatever it already resolves to via its own allocation
     rule/regex — read-only here, never modified by this wizard); for a
     billing unit, the union of ``objects`` across all its settlement units
     that are not ``draft``/``billed``, deduplicated. Each contributing
     rental object is weighted by its measurement value (leaf types under
     ``option_measurement_type`` summed if it is a group) at the cut-off
     date, and contributes its own current option rate (its latest
     ``option_rate`` record at or before the cut-off date, else its own
     ``fix_0``/``fix_100`` default). The new rate is the resulting weighted
     average, rounded to 2 decimals.
   - Base objects not in state ``approved``, and billing/settlement units
     in state ``draft`` or ``billed``, are excluded entirely.
   - A new dated ``option_rate`` record is only written when the computed
     rate differs from the current one; a record already dated on the
     cut-off month's first day is updated in place rather than duplicated.

   *Result* — counts of created / updated / unchanged / skipped records,
   plus a per-record detail log.

   Menu: *Real Estate → Master Data → Update Option Rates*.

``real_estate.contract_term_adjustment.wizard``  (``contract_wizard.py``, class ``ContractTermAdjustmentWizard``)
   .. note::
      **Skeleton only.** The *Start* → *Confirm* → *Process* → *Result*
      flow and every field below already work end-to-end, but the actual
      selection of contracts/terms and the write-back to ``ContractTerm`` /
      ``real_estate.contract.term.adjustment`` are not implemented yet.
      ``transition_do_adjustment`` dispatches by ``procedure`` to one of
      three placeholder methods (``_adjustment_operation_costs_billing``,
      ``_adjustment_operation_costs_plan``, ``_adjustment_free_adjustment``),
      each of which currently just returns ``processed = 0`` and a
      "not yet implemented" message without changing any data.

   *Start* — ``procedure`` (``operation_costs_billing`` / ``operation_costs_plan``
   / ``free_adjustment``, required), ``company``, ``property`` (defaulted
   from the active property record when launched from a property
   form/list), ``valid_from_new`` (effective date of the replacement term —
   the old term is intended to close the day before). Only for
   ``free_adjustment``: ``adjustment_mode`` (``percentage`` / ``absolute``).
   Only for ``operation_costs_billing``: ``billing_run_id`` (Selection,
   populated from ``billed`` billing units matching ``company``/``property``),
   guard flags ``no_terminated_contracts``, ``no_future_terms``,
   ``no_booked_terms``, ``only_rhythm_monthly_1`` (all default ``True``),
   and caps ``max_adjustment_percent`` (default 10 %) /
   ``max_adjustment_absolute`` (default 50, in the company currency).

   *Confirm* — read-only echo of every *Start* value (no match count, since
   selection logic does not exist yet).

   *Result* — ``processed`` count and a details message.

   Menu: *Real Estate → Contracts → Adjustment* (submenu with the wizard
   itself and a read-only list of ``real_estate.contract.term.adjustment``
   records).


Reports
=======

ODT templates (OpenDocument Text) are located in ``report/`` and rendered via
Genshi/relatorio; ``template_extension`` on the ``ir.action.report`` record is
``odt``. Values are inserted with ``text:span py:content="..."`` rather than
literal ``${...}`` interpolation (which relatorio escapes in ODT text), and
control flow (``py:if``/``py:for``/``py:choose``) is written as attributes on
the surrounding ODF elements. Superseded ``.html`` versions of these templates
remain in ``report/`` for reference but are no longer registered.

``real_estate.contract.report``  (``contract_report.py``)
   General contract report.
   Templates: ``contract_en.odt``, ``contract_letter_de.odt``.

``real_estate.contract.annex4.report``  (``contract_report.py``)
   Annex 4 – Betriebskostenaufstellung.
   Template: ``anlage4_contract_de.odt``.
   Renders grouped operating cost positions with BetrKV paragraph references
   and allocation method labels, sourced from the contract's own
   ``settlement_units`` field (see ``real_estate.contract`` below) rather than
   re-deriving the billing unit independently. Allocation labels are
   translatable messages (``real_estate.msg_allocation_*`` in ``message.xml``).

``real_estate.base_object.report``  (``base_object.py``)
   Fact sheet for a property or object.
   Template: ``fact_sheet.odt``.


Accounting / WoWi
=================

The ``wowi/`` directory contains a German "Kontenrahmen der
Wohnungswirtschaft" (WoWi, housing-industry chart of accounts) as XML
templates loaded at module installation:

- Account types and accounts
- Tax groups, tax templates, tax code templates, tax code line templates
- Tax rule templates

https://www.intex-publishing.de/pdf/Kontenrahmen_Wohnungswirtschaft.pdf
https://www.intex-publishing.de/pdf/Kontenrahmen_Immobilienwirtschaft.pdf

Source Layout
=============

.. code-block:: text

   real_estate/
   ├── address.py               # real_estate.address
   ├── base_object.py           # real_estate.base_object, occupancy, meter readings
   ├── billing_unit.py          # real_estate.billing_unit, billing_unit.moves,
   │                            #   billing_unit.log, cost_type, cost_category_group
   ├── billing_unit_wizard.py   # real_estate.billing_unit.wizard (batch billing)
   ├── co2_kostaufg.py          # real_estate.co2_kostaufg(.consumption), co2_emission_share
   ├── company.py               # extension to company.company (re_accounting link)
   ├── contract_core.py         # real_estate.contract, contract.log, account views,
   │                            #   cron_daily dispatcher + cron task handlers
   ├── contract_item.py         # real_estate.contract.item, contract.item.object
   ├── contract_term.py         # real_estate.contract.term, cash_flow, Quantitative
   ├── contract_type.py         # real_estate.contract.type, term.type
   ├── contract_report.py       # ContractReport, ContractAnnex4Report
   ├── contract_wizard.py       # wizards (CreateContractMovesWizard, TerminateContractWizard, …)
   ├── cron_task.py             # real_estate.cron_task (per-company scheduled task config)
   ├── invoice.py               # extensions to account.invoice / invoice.line
   ├── ir.py                    # extension to ir.cron (registers the cron_daily method)
   ├── measurement.py           # real_estate.measurement.type, measurement
   ├── object_party.py          # real_estate.object_party, object_party.role
   ├── option_rate.py           # real_estate.option_rate, option_rate.context
   ├── option_rate_wizard.py    # real_estate.option_rate_update.wizard
   ├── party.py                 # extension to party.party
   ├── re_accounting.py         # real_estate.re_accounting (company-scoped RE config)
   ├── res.py                   # extension to res.user
   ├── settlement_result.py     # real_estate.settlement_result, cost_share
   ├── settlement_unit.py       # real_estate.settlement_unit
   ├── report/                  # ODT report templates (rendered via Genshi/relatorio)
   ├── view/                    # XML form and tree view definitions
   ├── wowi/                    # German WoWi accounting templates
   └── locale/                  # Translations (de.po)


Running Tests
=============

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

Demo data scripts
------------------

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
   initial and a consumption reading. Looks up ``real_estate.use_class`` by
   ``sequence`` (language-independent) and measurement types by German name
   — the ``admin`` user must be set to German::

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
   *Musterstraße 5-8*::

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

``tests/test_payment.py``
   Requires ``test_contracts.py`` and at least one run of the
   ``CreateContractMoves`` wizard so posted tenant invoices exist. Books one
   payment receipt per tenant/commercial-tenant party (debit account 1800
   Bank / credit the receivable account taken from that party's open lines)
   and reconciles the open items::

      python tests/test_payment.py --database <db> [--config trytond.conf]
