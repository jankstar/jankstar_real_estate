******
Design
******

This page describes the key architectural decisions, data model relationships,
and invariants of the ``real_estate`` module.  It is aimed at developers who
want to extend or maintain the module.


Object Hierarchy
================

All real estate assets are represented by a single self-referential model
``real_estate.base_object`` using Tryton's ``tree()`` mixin.  A single
table stores all object types; the ``type`` field (``property``,
``building``, ``land``, ``object``, ``equipment``) distinguishes them.

Allowed parent-child combinations:

.. list-table::
   :header-rows: 1
   :widths: 20 50

   * - Object type
     - Valid parent types
   * - property
     - — (root, no parent)
   * - building
     - property, building
   * - land
     - property
   * - object
     - property, building, land
   * - equipment
     - building, land, object, equipment

The ``property`` back-reference (stored Many2One, auto-computed from the
path) points to the root of the tree.  It is used extensively as a filter
in contract items, billing units, and occupancy records.

The ``path`` field (Tryton ``tree()`` mixin) stores the full ancestor chain
as a slash-separated string of IDs.  SQL index on ``path`` enables fast
subtree queries without recursive CTEs.

Single-table design rationale
-------------------------------

Using one table rather than separate tables per type simplifies cross-type
queries (e.g. "all objects under a property"), reduces join depth, and
keeps the view/form layer uniform.  Type-specific fields (meter fields,
rental-object fields) are simply hidden by PYSON ``states.invisible``
conditions on the form view; they are NULL in the database for inapplicable
types.


Measurement Group Hierarchy
============================

``real_estate.measurement.type`` supports an optional parent-group
relationship: a type with ``is_group = True`` acts as a container for
child types.  Groups can be nested arbitrarily (multi-level hierarchies,
e.g. *Usable Space* → *Living Space* + *Commercial Space*).

Two helper methods encapsulate hierarchy traversal:

``get_hierarchy_ids()`` (instance method)
   Returns ``[self.id]`` + all descendant IDs recursively, including
   intermediate group nodes.  Used in ``ContractTerm.get_term_measurements``
   to find all measurements relevant to a group m_type.

``get_effective_ids(cls, m_type)`` (classmethod)
   Returns only **leaf** (non-group) IDs, recursively expanded.
   Used in ``ContractTerm._sum_measurements`` and
   ``SettlementUnit._compute_value_shares`` so that allocation queries
   hit only concrete measurement records, not group containers.

Constraints enforced by ``validate_fields``:

- A type may not reference itself or any of its descendants as ``parent``
  (cycle detection via ancestor walk).
- All children must share the same UOM as their parent group.
- Only leaf types (``is_group = False``) may be assigned to individual
  ``real_estate.measurement`` records on objects.


Contract Architecture
=====================

A contract is assembled from three layers:

.. code-block:: text

   Contract (real_estate.contract)
     └── ContractItem  (real_estate.contract.item)          — "what is rented"
           └── ContractItemObject                            — rental objects
     └── ContractTerm  (real_estate.contract.term)          — "what is charged"
           └── ContractTermTax                              — taxes
           └── ContractTermCashFlow                         — cash flow entries

**ContractItem** links one or more ``BaseObject`` records of type
``object`` to the contract for a given validity period.  The object
selector is domain-restricted to the same property as the contract
(``property = Eval('property')``), preventing cross-property assignments.

**ContractTerm** defines a recurring charge.  A term always references a
``ContractItem`` (``reference_item``) so that measurement-based quantity
derivation and operating cost allocation can trace back to the physical
object.

**ContractTermCashFlow** is the projection / ledger entry:

- ``state = 'draft'`` — planned, no invoice yet
- ``state = 'done'`` — linked to an ``account.invoice.line``

Cash flow entries carry ``create_moves_run_id`` (``YYYYMMDD-HHMMSS-U<uid>``)
so every posting can be traced to the exact wizard run that created it.


Contract Workflow
=================

.. code-block:: text

   Draft ──► Running ──► Terminated
     │           │
     └───────────┴──► Cancelled

Transitions:

- **Draft → Running** (button *Running*): activates the contract; sets
  ``running_by``; triggers occupancy refresh.
- **Running → Terminated** (wizard *Terminate Contract*): records
  ``termination_date``, ``receipt_of_termination_notice``,
  ``terminated_by``; triggers occupancy refresh.
- **Terminated → Running**: re-activates a contract (e.g. after a
  termination was withdrawn).
- **Draft / Running → Cancelled** (button *Cancel*): shows
  ``ContractCancelWarning`` if any ``done`` cash flow entries exist;
  deletes ``draft`` cash flow entries; triggers occupancy refresh.
  Cancelled contracts are excluded from all occupancy calculations.


Occupancy Tracking
==================

``real_estate.base_object.occupancy`` is a derived, read-only table that
records the rental state of each ``object``-type asset over time.

It is **not** maintained manually.  Instead it is recomputed automatically
whenever:

- A ``ContractItem`` or ``ContractItemObject`` is created, modified, or
  deleted (``create`` / ``write`` / ``delete`` hooks).
- A contract changes state (via ``Contract.write()`` which checks
  ``_COMPUTE_VALUE_SHARES_FIELDS`` — this set includes ``'state'``).

The recomputation filters contracts by
``state in ('draft', 'running', 'terminated')``; cancelled contracts are
excluded automatically.

Occupancy states:

- **rented** — contract running, object occupied
- **under_negotiation** — contract draft, object provisionally reserved
- **vacant** — no active contract for the object

Overlap validation in ``ContractItem._check_occupancy_overlap`` rejects
a second occupancy contract for the same object in the same period (hard
error for ``occupancy = True`` contract types).


Operating Cost Settlement Pipeline
====================================

The settlement follows a strict state machine on ``real_estate.billing_unit``:

.. code-block:: text

   Draft ──► Approved ──► Selection ──► Value Share ──► Billed
                  ▲                          │
                  └──────────────────────────┘ (re-run allowed)

Each stage builds on the previous:

1. **Approved** — billing unit is locked for editing; settlement units can
   be added.
2. **Selection** — ``_run_selection()`` identifies which objects and
   contracts fall inside the billing period.  Creates one ``CostShare``
   per (settlement_unit × object_or_contract) combination.
3. **Value Share** — ``_compute_value_shares()`` fills ``CostShare.value_share``
   according to the allocation rule (measurement, consumption, per-unit,
   external, none).  Errors are written to ``CostShare.error_message``;
   the billing unit sub-state reflects whether errors exist.
4. **Billed** — ``billing()`` creates invoices and credit notes from
   ``SettlementResult`` records; writes ``billing_run_id``.

Re-running *Selection* from *Value Share* deletes existing settlement results
after a user confirmation warning (``SelectionWarning``).

Re-running *Compute Value Shares* automatically resets cost shares in state
``error`` to ``selection`` before recalculating, so corrected readings or
measurements take effect without manual cleanup.


Allocation Rules
================

``SettlementUnit.allocation_rule`` determines how costs are split:

``allocation_by_measurement``
   Time-weighted share of a measurement value.

   ``value_share = measurement_value × time_share / time_total``

   The ``m_type`` field can reference a **group** measurement type; the
   system expands it to all leaf descendants via ``get_effective_ids()``.
   A unit-fallback applies for non-group types: if the exact type is not
   found on an object, the system falls back to any measurement with the
   same UOM.

``allocation_by_consumption``
   Raw meter reading consumption (HeizkostenV).

   ``value_share = end_reading − start_reading``

   Readings are looked up within a tolerance window
   (``reading_pre_days`` / ``reading_post_days`` on the cost type).
   If no reading is found, the cost share transitions to ``error``.

   **Vacancy fallback**: when the immediately following contract cost share
   has no start reading, the system uses the previous vacancy's start
   reading as a substitute, allowing a single read-out at move-out to serve
   both periods.

``allocation_per_rental_unit``
   Pure time share: ``value_share = time_share / time_total``.

``allocation_from_external_billing``
   No calculation.  Amounts are entered manually on the cost share.

``no_allocation``
   Entire cost remains unallocated.


Invoice Integration
===================

The module extends three core accounting models:

``account.invoice``
   Adds ``contract`` (Many2One to ``real_estate.contract``) so every
   invoice is traceable to its origin contract.

``account.invoice.line``
   Adds ``term`` (Many2One to ``real_estate.contract.term``) and
   ``settlement_unit`` (Many2One to ``real_estate.settlement_unit``).
   Term lines are created by ``CreateContractMovesWizard``; settlement
   lines are created by ``BillingUnit.billing()``.

``account.move.line``
   Extended list view to expose ``contract`` and ``term`` context for
   journal entries.

``AccountContract`` / ``GeneralLedgerAccountContract`` provide a
contract-filtered view of the general ledger, accessible from the
contract's *Account* tab.


Tryton Framework Patterns Used
===============================

``Workflow``
   Used by ``BaseObject``, ``Contract``, and ``BillingUnit``.  State
   transitions are declared in ``__setup__`` via ``cls._transitions`` and
   enforced by ``@Workflow.transition`` decorators on buttons.

``DeactivableMixin``
   Soft-delete for most master data and transactional records.  The
   ``active`` flag is ``True`` by default; filtering in list views excludes
   inactive records automatically.

``tree()``
   Self-referential parent-child for ``BaseObject`` and
   ``MeasurementType``.  Provides ``path`` field and subtree search helpers.

``sequence_ordered()`` / ``re_sequence_ordered()``
   Integer ``sequence`` field with auto-increment helpers; used for
   consistent ordering in all One2Many tabs.

``TaxableMixin``
   Tax calculation on ``Contract``; used to derive tax amounts for invoice
   line generation.

``Quantitative`` (custom ``fields.Numeric`` subclass)
   Carries a ``unit`` reference and ``quantitative=True`` flag so the SAO
   client renders the associated UOM symbol next to the numeric value.
   Used for meter reading values and contract term quantities.

``Cache``
   ``MeasurementType._get_default_type_cache`` and
   ``_get_window_domains_cache`` are invalidated in ``on_modification``
   whenever a measurement type record changes.

``UserWarning``
   ``ContractCancelWarning`` (cancel with existing postings),
   ``SelectionWarning`` (re-run selection), and
   ``OccupancyOverlapWarning`` follow the standard Tryton pattern:
   ``Warning.format(key, records)`` + ``Warning.check(key)`` + raise.

``@set_employee``
   Decorator used by workflow transitions to stamp ``running_by``,
   ``terminated_by``, and ``cancelled_by`` from the current user.
