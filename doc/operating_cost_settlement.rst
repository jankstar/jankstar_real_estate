*************************
Operating Cost Settlement
*************************

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
      manually instead of being computed internally. Also reveals the
      *BVED* page and its ``bved_provider_assignment`` field — see *BVED
      External Billing Interface* below.

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
      ``real_estate.billing_unit.wizard`` (see `Wizards <wizards.rst>`__), which
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

   ``rental_objects``
      (Function, One2Many, readonly.) Distinct rental objects referenced
      by this billing unit's own ``settlment_results`` (via
      ``settlement_result_objects()``) — the objects that actually ended
      up with a settlement result, as opposed to
      ``bved_covered_object_ids()`` (derived from ``settlement_unit.objects``
      and used for BVED A-/D-Satz matching, which can include an object
      excluded during ``selection()``, e.g. a genuine vacancy edge case).
      Shown as a read-only *Rental Objects* tab, right after *Settlement
      Results*.

   ``covered_rental_objects()``
      Method (not a stored/Function field) used by the BVED L-Satz
      "Gesamtfläche" calculation — see *BVED External Billing Interface*
      below: returns ``settlement_result_objects()`` when non-empty, else
      falls back to the objects covered by this billing unit's own
      settlement units (``bved_covered_object_ids()``) for a billing unit
      that hasn't had "Compute Settlement Results" run yet. External
      callers (BVED included) always go through this one method rather
      than re-deriving the object set themselves.

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
      manually on the cost share. Automatically suggested (via
      ``on_change_external_billing``) on every settlement unit of a billing
      unit when that billing unit's ``external_billing`` flag is enabled
      (see ``real_estate.billing_unit`` below) — except units already set to
      ``allocation_via_cost_collector``, which are left alone. Enforced (not
      just suggested) by ``validate_fields``: for an externally billed
      billing unit, every settlement unit's ``allocation_rule`` must be
      either this or ``allocation_via_cost_collector``.

   ``allocation_via_cost_collector``
      No allocation of its own. Used to route one settlement unit's costs
      into another settlement unit of the *same* billing unit (its
      ``reference_settlement_unit``, required for this rule and restricted
      to a unit that does not itself use this rule — no chaining) for
      allocation there instead. Also selectable when the billing unit has
      ``external_billing`` enabled, as an alternative to
      ``allocation_from_external_billing`` (e.g. several fuel suppliers,
      each invoiced on their own settlement unit, feeding one externally
      billed heating settlement unit).

      A settlement unit with this rule:

      - determines no rental objects of its own — ``objects`` always
        mirrors ``reference_settlement_unit.objects``;
      - generates no cost shares and is excluded from
        ``Contract.get_settlement_units()`` (so it never appears twice,
        once under its own cost type and once under the reference's, in
        e.g. the Annex 4 report);
      - still tracks its own ``planned_costs``/``actual_costs`` (the latter
        from its own ``invoice_lines``, via the normal
        ``selection_actual_costs()``) — these are summed, across *all*
        settlement units referencing the same target, into the target's
        ``planned_costs_from_references``/``actual_costs_from_references``
        (Function fields, see below) and folded into the target's own
        ``planned_costs``/``actual_costs`` when it computes its value
        shares.

      ``BillingUnit.compute_value_shares_button`` processes all
      ``allocation_via_cost_collector`` units of a billing unit before any
      other settlement unit, so a reference target always sees its
      referencing units' up-to-date actual costs.
      ``BillingUnit.duplicate_next_period`` copies ``reference_settlement_unit``
      to point at the *newly created* successor of the original target (not
      the old period's unit) — non-cost-collector units are always copied
      first so that successor already exists by the time a referencing
      unit is copied.

   ``planned_costs_from_references`` / ``actual_costs_from_references``
      (Function fields, any settlement unit) Sum of ``planned_costs``/
      ``actual_costs`` of all settlement units of the same billing unit
      that reference this one via ``allocation_via_cost_collector``. Zero
      when nothing references this unit.

   Vacancy handling: unoccupied periods can be charged to the owner or left
   unallocated.

   When ``compute_value_shares`` is re-run, cost shares in state ``error``
   are automatically reset to ``selection`` and their ``error_message``
   cleared before the new calculation starts, so corrected readings or
   measurements take effect immediately.

   *Heating cost billing split (HeizkostenV §7/§8):*

   ``heating_billing_mode``
      Selection: ``none`` (default) / ``central_heating`` /
      ``central_hot_water``. Independent of ``allocation_rule``/``m_type``
      above (which govern how *this* settlement unit's own costs are
      allocated per tenant) — this models the legally mandated split, for a
      centrally supplied heating or hot water system, between the
      consumption-based and area-based portions of the heating cost
      statement itself.

   ``heating_consumption_share_percent``
      Numeric percentage entered by the user: the share of heating/hot
      water cost allocated by consumption ("Anteil nach
      Verbrauchsumlage"). Required and visible only when
      ``heating_billing_mode`` is ``central_heating`` or
      ``central_hot_water``; domain-restricted to 50–70 (statutory range,
      HeizkostenV §7/§8) — but only while one of those two modes is
      selected, so a value entered under a previous mode (or left over
      from an import) never blocks saving once the mode is set back to
      ``none``.

   ``heating_area_share_percent`` (Function field)
      Computed as ``100 − heating_consumption_share_percent``
      ("Anteil nach Flächenumlage"); read-only, same visibility as above.

   ``heating_area_measurement_type``
      Many2One to ``real_estate.measurement.type`` (object-level measurement
      types only): which measurement to use for the area-based portion of
      the heating cost split. Required and visible only under the same
      condition as the two fields above.

   ``total_value_consumption`` / ``total_value_area``
      Sum, across all of this unit's cost shares, of their
      ``consumption_share`` / ``area_share`` (see ``real_estate.cost_share``
      below). Read-only, visible only when ``heating_billing_mode`` is
      ``central_heating``/``central_hot_water``. Computed by
      ``_compute_heizkostenv_split()``, called at the end of
      ``compute_value_shares()`` (both the regular per-cost-share path and
      both branches of ``_compute_value_shares_external()``) — i.e.
      whenever *Compute Value Shares* is run on the billing unit.

``real_estate.cost_share``  (``settlement_result.py``)
   Intermediate allocation record: share of a specific cost type for one
   contract or object within a billing period.

   *States:* ``preparation`` · ``selection`` · ``estimated_value_share``
   · ``value_share`` · ``error``

   Stores ``value_share`` (time-weighted allocation factor — for
   ``allocation_by_measurement`` and ``allocation_per_rental_unit`` this
   already incorporates the occupancy fraction ``time_share / time_total``;
   for ``allocation_by_consumption`` it holds the raw consumption value,
   *unless* the settlement unit is HeizkostenV-split — see
   ``consumption_share`` below), ``time_share`` (days), ``planned_costs``,
   ``actual_costs``.
   ``error_message`` describes the problem; entries set by
   ``compute_settlement_result`` carry a ``[draft]`` prefix and are
   automatically cleared on the next successful re-run.

   ``allocation_rule`` / ``external_billing`` (Function fields, mirrored)
      Mirrored from the parent ``settlement_unit``.
      ``planned_costs``/``actual_costs`` are only editable
      (``readonly`` otherwise) when ``external_billing`` is set, i.e. for
      cost shares of a settlement unit with
      ``allocation_rule = allocation_from_external_billing``.

   ``heating_billing_mode`` (Function field, mirrored)
      Mirrored from the parent ``settlement_unit``; drives the visibility
      of the two fields below (only visible for ``central_heating``/
      ``central_hot_water``).

   ``consumption_share`` / ``area_share``
      The two HeizkostenV split components, computed by
      ``SettlementUnit._compute_heizkostenv_split()`` (called at the end
      of ``compute_value_shares()``) only when the parent settlement
      unit's ``heating_billing_mode`` is ``central_heating``/
      ``central_hot_water``:

      - ``consumption_share`` — only for ``allocation_rule =
        allocation_by_consumption``: the raw consumption value that would
        otherwise sit in ``value_share`` is moved here instead, and
        ``value_share`` is reset to ``0`` (so a HeizkostenV-split
        consumption-based unit currently distributes no
        ``planned_costs``/``actual_costs`` via
        ``compute_value_shares()``'s own ``_distribute()`` step — a
        deliberate, temporary state pending a follow-up that recombines
        ``consumption_share``/``area_share`` via
        ``heating_consumption_share_percent``/``heating_area_share_percent``
        into the actual cost distribution).
      - ``area_share`` — computed for *every* cost share of a
        HeizkostenV-split unit regardless of its ``allocation_rule``:
        the value of the unit's own ``heating_area_measurement_type`` for
        the cost share's ``base_object``, weighted by
        ``time_share / settlement_unit.time_total`` (same weighting as
        ``allocation_by_measurement`` above).

      Both values are summed into the parent settlement unit's
      ``total_value_consumption``/``total_value_area``.

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
