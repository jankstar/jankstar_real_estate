*************
API Reference
*************

This page lists every model provided by the ``real_estate`` module together
with its key fields, states, and notable methods.  Extension fields added
to Tryton core models are listed separately at the bottom.

Notation: **[R]** = readonly, **[F]** = Function field, **[R/O]** =
required on save.


Property Management
===================

``real_estate.use_class``
--------------------------

Configurable use class for rental objects (Apartment, Retail, Parking, …).

.. list-table::
   :header-rows: 1
   :widths: 25 15 60

   * - Field
     - Type
     - Description
   * - ``name``
     - Char [R/O]
     - Display name (translatable)
   * - ``sequence``
     - Integer [R/O]
     - Sort order; also used by demo scripts to find records
   * - ``has_basement_nr``
     - Boolean
     - Show *Basement Number* field on objects of this class
   * - ``has_parking_nr``
     - Boolean
     - Show *Parking Number* field on objects of this class


``real_estate.address``
------------------------

Structured address with granular sub-fields.

.. list-table::
   :header-rows: 1
   :widths: 25 15 60

   * - Field
     - Type
     - Description
   * - ``street_name``
     - Char
     - Street name without number
   * - ``building_number``
     - Char
     - House / building number
   * - ``unit_number``
     - Char
     - Apartment / unit identifier
   * - ``floor_number``
     - Char
     - Floor
   * - ``room_number``
     - Char
     - Room identifier
   * - ``post_box``
     - Char
     - Post box number
   * - ``postal_code``
     - Char
     - Postal code
   * - ``city``
     - Char
     - City
   * - ``country``
     - Many2One
     - ``country.country``
   * - ``street``
     - Char [F]
     - Composed ``street_name + building_number`` for display


``real_estate.base_object``
----------------------------

Central entity for every real estate asset.

*Types:* ``property`` · ``building`` · ``land`` · ``object`` · ``equipment``

*Workflow:* Draft → Approved → Locked (+ Deactivated)

.. list-table::
   :header-rows: 1
   :widths: 25 15 60

   * - Field
     - Type
     - Description
   * - ``name``
     - Char [R/O]
     - Description / display name
   * - ``type``
     - Selection [R/O]
     - Object type; controls visible fields
   * - ``type_of_use``
     - Selection
     - ``residential`` / ``commercial`` / ``property`` / ``internal``
   * - ``use_class``
     - Many2One
     - ``real_estate.use_class``; visible for type *object* only
   * - ``company``
     - Many2One [R/O]
     - ``company.company``
   * - ``start_date``
     - Date [R/O]
     - Date the asset was commissioned
   * - ``end_date``
     - Date
     - Date the asset was decommissioned
   * - ``address``
     - Many2One
     - ``real_estate.address``
   * - ``property``
     - Many2One [R] [F]
     - Root property object (auto-derived from tree path)
   * - ``parent``
     - Many2One
     - Direct parent in the object tree
   * - ``children``
     - One2Many
     - Direct children
   * - ``path``
     - Char [R]
     - Full ancestor path (tree mixin)
   * - ``state``
     - Selection
     - ``draft`` / ``approved`` / ``locked`` / ``deactivated``
   * - ``object_number``
     - Char [R]
     - Auto-generated object identifier
   * - ``measurements``
     - One2Many
     - ``real_estate.measurement`` records
   * - ``parties``
     - One2Many
     - ``real_estate.object_party`` (roles)
   * - ``billing_units``
     - One2Many
     - ``real_estate.billing_unit`` (property only)
   * - ``occupancy``
     - One2Many [R]
     - ``real_estate.base_object.occupancy`` (computed)
   * - ``billing_as``
     - Selection
     - ``single`` / ``collective`` — aggregation for cost billing
   * - ``collective_billing``
     - Boolean [F]
     - Derived from property's ``billing_as``
   * - ``year_of_construction``
     - Char
     - 4-digit year (building only)
   * - ``number_of_floors``
     - Integer
     - Number of floors (building only)
   * - ``floor``
     - Integer
     - Floor number (object only)
   * - ``basement_nr``
     - Char
     - Basement storage number (object, use_class dependent)
   * - ``parking_nr``
     - Char
     - Parking number (object, use_class dependent)
   * - ``e_type``
     - Selection
     - Equipment sub-type: ``meters`` / ``other`` (equipment only)
   * - ``meter_unit``
     - Many2One
     - UOM for meter readings (equipment/meters only)
   * - ``meter_is_counter``
     - Boolean
     - True for cumulative counters (consumption = diff to prev. reading)
   * - ``meter_factor``
     - Float
     - Conversion factor applied to raw readings (default 1.0)
   * - ``meter_no_decimals``
     - Boolean
     - Readings must be integer values
   * - ``meter_id``
     - Char [F]
     - ID of the most recent reading
   * - ``meter_last_value``
     - Quantitative [F]
     - Last recorded reading value
   * - ``meter_last_consumption``
     - Quantitative [F]
     - Consumption since the previous reading


``real_estate.base_object.occupancy``
--------------------------------------

Read-only occupancy ledger; recomputed automatically on contract changes.

.. list-table::
   :header-rows: 1
   :widths: 25 15 60

   * - Field
     - Type
     - Description
   * - ``base_object``
     - Many2One [R]
     - The object being tracked
   * - ``property``
     - Many2One [R]
     - Root property (denormalized)
   * - ``start_date``
     - Date [R]
     - First day of occupancy period
   * - ``end_date``
     - Date [R]
     - Last day (None = open-ended)
   * - ``state``
     - Selection [R]
     - ``rented`` / ``vacant`` / ``under_negotiation``
   * - ``contract``
     - Many2One [R]
     - Source contract (None for vacancy periods)


``real_estate.measurement.type``
----------------------------------

Named measurement type linked to a UOM.  Supports group hierarchy.

.. list-table::
   :header-rows: 1
   :widths: 25 15 60

   * - Field
     - Type
     - Description
   * - ``name``
     - Char [R/O]
     - Display name (translatable)
   * - ``unit``
     - Many2One [R/O]
     - ``product.uom``
   * - ``types``
     - MultiSelection
     - Object types this measurement applies to
   * - ``is_group``
     - Boolean
     - Marks this type as a group container
   * - ``parent``
     - Many2One
     - Parent group (``is_group = True`` required on parent)
   * - ``children``
     - One2Many
     - Child types (visible when ``is_group = True``)
   * - ``default``
     - Boolean
     - Use as default type for the object type
   * - ``no_print``
     - Boolean
     - Exclude from printed reports

Key methods:

``get_hierarchy_ids()``
   Returns self.id plus all descendant IDs recursively (including groups).

``get_effective_ids(cls, m_type)``
   Returns only leaf (non-group) IDs, recursively expanded from m_type.


``real_estate.measurement``
-----------------------------

Associates a numeric value with a ``BaseObject`` for a given date.

.. list-table::
   :header-rows: 1
   :widths: 25 15 60

   * - Field
     - Type
     - Description
   * - ``base_object``
     - Many2One [R/O]
     - The object being measured
   * - ``m_type``
     - Many2One [R/O]
     - ``real_estate.measurement.type`` (leaf types only)
   * - ``valid_from``
     - Date [R/O]
     - Date from which this measurement applies
   * - ``value``
     - Float [R/O]
     - Measured value
   * - ``symbol``
     - Char [F]
     - UOM symbol (derived from m_type)
   * - ``no_print``
     - Boolean
     - Exclude from printed reports


``real_estate.meter_reading``
------------------------------

Meter reading linked to an equipment object of type *meters*.

.. list-table::
   :header-rows: 1
   :widths: 25 15 60

   * - Field
     - Type
     - Description
   * - ``base_object``
     - Many2One [R/O]
     - Equipment object (``e_type = 'meters'``)
   * - ``meter_id``
     - Char [R/O]
     - Physical meter identifier
   * - ``reading_date``
     - Date [R/O]
     - Date of reading
   * - ``m_type``
     - Selection [R/O]
     - ``initial`` / ``reading`` / ``estimate`` / ``final``
   * - ``value``
     - Quantitative [R/O]
     - Raw meter value
   * - ``unit``
     - Many2One [F]
     - UOM (derived from equipment's ``meter_unit``)
   * - ``consumption``
     - Quantitative [F]
     - Value minus previous reading (counter meters only)
   * - ``reading_user``
     - Many2One
     - User who recorded the reading
   * - ``comment``
     - Char
     - Free text


``real_estate.object_party.role``
-----------------------------------

Configurable role definition for object parties.

Fields: ``name`` (Char), ``sequence`` (Integer), ``types`` (MultiSelection
of object types), ``default`` (Boolean).


``real_estate.object_party``
------------------------------

Links a ``party.party`` to a ``BaseObject`` with a typed role.

Fields: ``base_object`` (Many2One), ``party`` (Many2One), ``role``
(Many2One → ``object_party.role``), ``valid_from`` (Date),
``valid_to`` (Date).


Contract Management
===================

``real_estate.contract.type``
------------------------------

Template controlling contract behaviour.

.. list-table::
   :header-rows: 1
   :widths: 25 15 60

   * - Field
     - Type
     - Description
   * - ``name``
     - Char [R/O]
     - Display name (translatable)
   * - ``sequence``
     - Integer [R/O]
     - Sort order
   * - ``types_of_use``
     - MultiSelection
     - Which ``type_of_use`` values this type applies to
   * - ``invoice_type``
     - Selection
     - ``out`` (debit/receivable) or ``in`` (credit/payable)
   * - ``account``
     - Many2One
     - Default party account for invoice lines
   * - ``taxes``
     - Many2Many
     - Default taxes applied to all terms
   * - ``account_journal``
     - Many2One
     - Default posting journal
   * - ``prefix``
     - Char [R/O]
     - Contract number prefix (e.g. ``1``)
   * - ``start_number``
     - Integer [R/O]
     - First contract number
   * - ``step_item``
     - Integer [R/O]
     - Sequence step for contract items
   * - ``step_term``
     - Integer [R/O]
     - Sequence step for contract terms
   * - ``occupancy``
     - Boolean
     - Enforce occupancy exclusivity for this contract type
   * - ``mark``
     - Char
     - Periodic posting mark (``Debit`` / ``Credit``)


``real_estate.contract.term.type``
------------------------------------

Template for a recurring charge line.

.. list-table::
   :header-rows: 1
   :widths: 25 15 60

   * - Field
     - Type
     - Description
   * - ``name``
     - Char [R/O]
     - Display name (translatable)
   * - ``sequence``
     - Integer [R/O]
     - Sort order; also used by scripts to locate records
   * - ``types_of_use``
     - MultiSelection
     - Applicable type-of-use values
   * - ``m_type``
     - Many2One
     - Measurement type for default quantity derivation
   * - ``default_quantity``
     - Float
     - Fallback quantity when no measurement is found
   * - ``account``
     - Many2One
     - Default account for invoice lines
   * - ``rhythm``
     - Integer
     - Number of rhythm units per invoice
   * - ``rhythm_type``
     - Selection
     - ``daily`` / ``weekly`` / ``monthly`` / ``quarterly`` /
       ``annually`` / ``one_time``
   * - ``rhythm_start``
     - Selection
     - Day of month (1–28) when the first invoice of the period is due


``real_estate.contract``
-------------------------

Main contract record.

*Workflow:* Draft → Running → Terminated / Cancelled

.. list-table::
   :header-rows: 1
   :widths: 25 15 60

   * - Field
     - Type
     - Description
   * - ``c_type``
     - Many2One [R/O]
     - ``real_estate.contract.type``
   * - ``property``
     - Many2One [R/O]
     - Root property
   * - ``contractual_partner``
     - Many2One [R/O]
     - ``party.party`` (tenant / owner)
   * - ``invoice_address``
     - Many2One
     - ``party.address`` used on invoices
   * - ``type_of_use``
     - Selection
     - ``residential`` / ``commercial`` / ``property`` / ``internal``
   * - ``currency``
     - Many2One [R/O]
     - Billing currency
   * - ``start_date``
     - Date [R/O]
     - Contract start
   * - ``end_date``
     - Date [F]
     - Effective end (max of item valid_to dates)
   * - ``state``
     - Selection
     - ``draft`` / ``running`` / ``terminated`` / ``cancelled``
   * - ``items``
     - One2Many
     - ``real_estate.contract.item``
   * - ``terms``
     - One2Many
     - ``real_estate.contract.term``
   * - ``logs``
     - One2Many [R]
     - ``real_estate.contract.log``
   * - ``running_by``
     - Many2One [R]
     - User who activated the contract
   * - ``terminated_by``
     - Many2One [R]
     - User who terminated the contract
   * - ``cancelled_by``
     - Many2One [R]
     - User who cancelled the contract
   * - ``termination_date``
     - Date
     - Last day of the tenancy
   * - ``receipt_of_termination_notice``
     - Date
     - Date the termination notice was received
   * - ``termination_reason``
     - Text
     - Free-text reason


``real_estate.contract.item``
------------------------------

Assigns rental objects to a contract for a validity period.

.. list-table::
   :header-rows: 1
   :widths: 25 15 60

   * - Field
     - Type
     - Description
   * - ``contract``
     - Many2One [R/O]
     - Parent contract
   * - ``label``
     - Char
     - Optional label (overrides auto-name)
   * - ``valid_from``
     - Date [R/O]
     - Start of object assignment
   * - ``valid_to``
     - Date
     - End of object assignment (open if None)
   * - ``objects``
     - One2Many
     - ``real_estate.contract.item.object`` (rental objects)
   * - ``property``
     - Many2One [F]
     - Derived from ``contract.property``


``real_estate.contract.item.object``
--------------------------------------

Junction between a ``ContractItem`` and a ``BaseObject``.

.. list-table::
   :header-rows: 1
   :widths: 25 15 60

   * - Field
     - Type
     - Description
   * - ``item``
     - Many2One [R/O]
     - Parent ``ContractItem``
   * - ``object``
     - Many2One [R/O]
     - ``real_estate.base_object`` (type *object*); domain-restricted to
       objects of the same property as the contract
   * - ``property``
     - Many2One [F]
     - Derived from ``item.contract.property``


``real_estate.contract.term``
------------------------------

Recurring charge line on a contract.

.. list-table::
   :header-rows: 1
   :widths: 25 15 60

   * - Field
     - Type
     - Description
   * - ``contract``
     - Many2One [R/O]
     - Parent contract
   * - ``term_type``
     - Many2One [R/O]
     - ``real_estate.contract.term.type``
   * - ``reference_item``
     - Many2One
     - ``ContractItem`` this charge relates to
   * - ``valid_from``
     - Date [R/O]
     - Start of charge period
   * - ``valid_to``
     - Date
     - End of charge period (open if None)
   * - ``rhythm``
     - Integer
     - Billing frequency count
   * - ``rhythm_type``
     - Selection
     - ``daily`` / ``weekly`` / ``monthly`` / ``quarterly`` /
       ``annually`` / ``one_time``
   * - ``rhythm_start``
     - Selection
     - Day-of-month start (1–28)
   * - ``quantity``
     - Quantitative
     - Units per billing period
   * - ``unit``
     - Many2One [F]
     - UOM (from term_type.m_type.unit)
   * - ``unit_price``
     - Monetary
     - Price per unit per period
   * - ``taxes``
     - Many2Many
     - Applied taxes
   * - ``cash_flows``
     - One2Many
     - ``real_estate.contract.term.cash_flow``


``real_estate.contract.term.cash_flow``
-----------------------------------------

Single projected or realised cash flow entry.

.. list-table::
   :header-rows: 1
   :widths: 25 15 60

   * - Field
     - Type
     - Description
   * - ``term``
     - Many2One [R/O]
     - Parent ``ContractTerm``
   * - ``state``
     - Selection
     - ``draft`` (planned) / ``done`` (invoiced)
   * - ``posting_date``
     - Date
     - Invoice / posting date
   * - ``document_date``
     - Date
     - Document date on the invoice
   * - ``due_date``
     - Date
     - Payment due date
   * - ``invoice_line``
     - Many2One [R]
     - ``account.invoice.line`` (set when state = done)
   * - ``create_moves_run_id``
     - Char [R]
     - Run ID of the ``CreateContractMoves`` wizard invocation
   * - ``invoice_state``
     - Selection [F]
     - Derived from linked invoice: ``draft`` / ``validated`` /
       ``posted`` / ``paid``


``real_estate.contract.log``
-----------------------------

Append-only audit log entry on a contract.

Fields: ``contract`` (Many2One), ``event`` (Char), ``description``
(Text), ``create_date`` (DateTime [R]), ``create_uid`` (Many2One [R]).


Operating Cost Settlement
==========================

``real_estate.cost_category_group``
-------------------------------------

Groups cost types for reporting.

Fields: ``name`` (Char [R/O]), ``sequence`` (Integer [R/O]).


``real_estate.cost_type``
--------------------------

Individual operating cost item (e.g. *Grundsteuer*).

.. list-table::
   :header-rows: 1
   :widths: 25 15 60

   * - Field
     - Type
     - Description
   * - ``name``
     - Char [R/O]
     - Display name (translatable)
   * - ``sequence``
     - Integer [R/O]
     - Sort order; used by scripts to locate records
   * - ``category_group``
     - Many2One
     - ``real_estate.cost_category_group``
   * - ``comment``
     - Text
     - BetrKV paragraph reference or free text
   * - ``no_print``
     - Boolean
     - Exclude from settlement printout
   * - ``reading_pre_days``
     - Integer
     - Days before target date within which a meter reading is accepted
       (default 7; ``allocation_by_consumption`` only)
   * - ``reading_post_days``
     - Integer
     - Days after target date within which a meter reading is accepted
       (default 7; ``allocation_by_consumption`` only)


``real_estate.billing_unit``
-----------------------------

Annual (or period) operating cost settlement for one property.

*Workflow:* Draft → Approved → Selection → Value Share → Billed

.. list-table::
   :header-rows: 1
   :widths: 25 15 60

   * - Field
     - Type
     - Description
   * - ``property``
     - Many2One [R/O]
     - Root property
   * - ``description``
     - Char [R/O]
     - Free-text label (e.g. "Kalte Betriebskosten 2025")
   * - ``start_date``
     - Date [R/O]
     - First day of settlement period
   * - ``end_date``
     - Date [F]
     - Last day (defaults to end of calendar year of start_date)
   * - ``calculation_method``
     - Selection
     - ``rental_apartment`` (§§ 1–2 BetrKV) / ``WEG_billing``
   * - ``billing_type``
     - Selection
     - ``planned_billing`` / ``actual_billing``
   * - ``state``
     - Selection
     - ``draft`` / ``approved`` / ``selection`` / ``value_share`` /
       ``billed``
   * - ``sub_state``
     - Selection [F]
     - ``ok`` / ``error`` / ``warning`` (derived from cost share states)
   * - ``term_types_of_use``
     - MultiSelection
     - Term type sequences counted as advance payments
   * - ``settlement_units``
     - One2Many
     - ``real_estate.settlement_unit``
   * - ``settlment_results``
     - One2Many
     - ``real_estate.settlement_result``
   * - ``moves``
     - One2Many
     - ``real_estate.billing_unit.moves``
   * - ``billing_run_id``
     - Char [R]
     - ``YYYYMMDD-HHMMSS-U<uid>`` stamped at end of ``billing()``
   * - ``sum_planned_costs``
     - Monetary [F]
     - Sum of planned costs across all settlement units
   * - ``sum_actual_costs``
     - Monetary [F]
     - Sum of actual costs
   * - ``sum_advanced_payment``
     - Monetary [F]
     - Sum of posted/paid advance payments
   * - ``sum_refund_receivable``
     - Monetary [F]
     - sum_actual_costs − sum_advanced_payment


``real_estate.settlement_unit``
--------------------------------

One cost-type line within a billing unit.

.. list-table::
   :header-rows: 1
   :widths: 25 15 60

   * - Field
     - Type
     - Description
   * - ``billing_unit``
     - Many2One [R/O]
     - Parent billing unit
   * - ``type``
     - Many2One [R/O]
     - ``real_estate.cost_type``
   * - ``allocation_rule``
     - Selection [R/O]
     - ``allocation_by_measurement`` / ``allocation_by_consumption`` /
       ``allocation_per_rental_unit`` /
       ``allocation_from_external_billing`` / ``no_allocation``
   * - ``vacancy``
     - Selection
     - ``by_owner`` / ``unallocated``
   * - ``m_type``
     - Many2One
     - Measurement type for measurement-based allocation
   * - ``meter_unit``
     - Many2One
     - UOM for consumption-based allocation
   * - ``reg_ex_object``
     - Char
     - Regex to filter rental objects (applied to ``base_object.name``)
   * - ``reg_ex_meter``
     - Char
     - Regex to filter meter equipment (applied to ``base_object.name``)
   * - ``value_total``
     - Float
     - Total allocation base (sum of all cost shares' value_share)
   * - ``cost_shares``
     - One2Many
     - ``real_estate.cost_share``


``real_estate.cost_share``
---------------------------

Intermediate allocation record: share of one cost type for one
contract/object within a billing period.

*States:* ``preparation`` → ``selection`` → ``estimated_value_share``
→ ``value_share`` · ``error``

.. list-table::
   :header-rows: 1
   :widths: 25 15 60

   * - Field
     - Type
     - Description
   * - ``settlement_unit``
     - Many2One [R/O]
     - Parent settlement unit
   * - ``contract``
     - Many2One
     - Contract occupying the object (None = vacancy)
   * - ``base_object``
     - Many2One
     - The rental object
   * - ``start_date``
     - Date
     - Start of this share's occupancy period
   * - ``end_date``
     - Date
     - End of this share's occupancy period
   * - ``state``
     - Selection
     - See states above
   * - ``value_share``
     - Float
     - Allocation factor (measurement value × time fraction, or
       raw consumption, or time fraction)
   * - ``time_share``
     - Integer [F]
     - Days within the billing period
   * - ``planned_costs``
     - Monetary
     - Budgeted cost for this share
   * - ``actual_costs``
     - Monetary
     - Real cost for this share
   * - ``error_message``
     - Char [R]
     - Human-readable error (set when state = error)


``real_estate.settlement_result``
----------------------------------

Final per-contract settlement for one billing unit.

*States:* ``approved`` → ``billed``

.. list-table::
   :header-rows: 1
   :widths: 25 15 60

   * - Field
     - Type
     - Description
   * - ``billing_unit``
     - Many2One [R/O]
     - Parent billing unit
   * - ``contract``
     - Many2One
     - Tenant contract
   * - ``base_object``
     - Many2One
     - Rental object (denormalized)
   * - ``start_date``
     - Date
     - Settlement period start
   * - ``end_date``
     - Date
     - Settlement period end
   * - ``state``
     - Selection
     - ``approved`` / ``billed``
   * - ``planned_costs``
     - Monetary
     - Sum of planned costs from cost shares
   * - ``actual_costs``
     - Monetary
     - Sum of actual costs from cost shares
   * - ``advanced_payment``
     - Monetary
     - Sum of posted/paid advance invoice lines
   * - ``refund_receivable``
     - Monetary [F]
     - actual_costs − advanced_payment (positive = refund)
   * - ``term``
     - Many2One
     - The single advance-payment term (if unambiguous)
   * - ``invoice``
     - Many2One [R]
     - Settlement invoice created by ``billing()``


``real_estate.billing_unit.moves``
------------------------------------

One record per posting created by ``billing()``.

.. list-table::
   :header-rows: 1
   :widths: 25 15 60

   * - Field
     - Type
     - Description
   * - ``billing_unit``
     - Many2One [R/O]
     - Parent billing unit
   * - ``settlement_result``
     - Many2One
     - Source settlement result
   * - ``contract``
     - Many2One
     - Source contract
   * - ``billing_run_id``
     - Char [R]
     - Same value as parent ``BillingUnit.billing_run_id``
   * - ``moves_advanced_payment``
     - Many2One
     - Credit-note line reversing advance payments
   * - ``moves_actual_costs``
     - Many2One
     - Invoice line for actual costs
   * - ``moves_alloc_by_owner``
     - Many2One
     - Journal move line for owner allocation (WEG only)


Extensions to Core Modules
===========================

``party.party``  (``party.py``)
   Adds ``sequence`` (Integer, sort key) and ``salutation`` (Char).

``account.invoice``  (``invoice.py``)
   Adds ``contract`` (Many2One → ``real_estate.contract``).

``account.invoice.line``  (``invoice.py``)
   Adds ``term`` (Many2One → ``real_estate.contract.term``) and
   ``settlement_unit`` (Many2One → ``real_estate.settlement_unit``).

``account.configuration``  (``account_configuration.py``)
   Adds three default accounts for operating cost billing:
   ``account_operation_cost_actual_costs``,
   ``account_operation_cost_advanced_payment``,
   ``account_operation_cost_alloc_by_owner``.

``res.user``  (``res.py``)
   Adds ``phone`` (Char) and ``mobile`` (Char).


Wizards
=======

``real_estate.contract.create_moves.wizard``
   Batch invoice generation.  Start state ``start`` collects
   ``create_date``, optional ``property`` and ``contract`` filters, and
   ``action`` (``create`` / ``re_calc`` / ``re_calc_and_create``).

``real_estate.terminate_contract.wizard``
   Terminates a running contract.  Collects ``terminated_by_type``,
   ``receipt_of_termination_notice``, ``termination_reason``, and
   ``termination_date`` (or computes it from a notice period in months).

``real_estate.estimate_consumption.wizard``
   Two-step wizard on meter equipment objects.  Step 1 collects
   ``per_date``, ``meter_id``, and ``reason``; step 2 shows the
   simulated consumption and lets the user confirm or adjust the
   ``estimated_value`` before saving a new ``MeterReading``.
