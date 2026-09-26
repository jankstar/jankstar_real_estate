*******
Wizards
*******

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

``real_estate.change_contract_partner.wizard``  (``contract_wizard.py``, class ``ChangeContractPartnerWizard``)
   Reassigns a contract's main tenant as of a chosen ``change_date``
   (domain- and server-side restricted to the contract's own validity
   period), rebooking still-open invoices to the new party rather than
   just swapping a reference.

   *Start* — ``contract`` (readonly), ``current_party`` (Function),
   ``new_party`` (domain excludes the current party), ``change_date``
   (required, domain restricted to ``[contract's start_date,
   effective end date]`` via two Function fields — a plain Many2One
   reference field cannot use ``_parent_<field>`` PySON the way a true
   parent-child nested form can, so ``contract_start_date``/
   ``contract_end_date`` mirror those dates onto the wizard's own start
   state instead).

   *Process* (``Contract.execute_change_partner``):

   - Rejects reassigning to the same party
     (``msg_change_partner_same_party``) and a ``change_date`` outside
     the contract's validity (``msg_change_partner_date_out_of_range``).
   - Warns (confirmable, ``ContractPartnerChangeDraftInvoicesWarning``)
     if the outgoing party still has ``draft`` invoices on this contract
     — those are never picked up by the rebooking below (only posted,
     still-open items are), so they would otherwise silently stay with
     the old party.
   - Finds still-open (posted, unreconciled) invoices via the cash flow
     (``ContractTermCashFlow``, filtered by contract — deliberately not
     restricted to a specific term/condition, so rent *and* operating
     cost/heating advances on the contract are all rebooked together,
     matching what a real partner change should do). For each: a credit
     note closes the old party's open item (same mechanism as
     ``BillingUnit.cancel_units``), reconciled against it when balanced;
     a new invoice with lines copied 1:1 (same account/amount/taxes/
     ``contract``/``term``/``base_object`` — only ``party`` and
     ``accounting_date`` differ) reopens the same charge under the new
     party.
   - Ends the old party's open *Main Tenant Role* assignment the day
     before ``change_date``; optionally starts a *Secondary Tenant Role*
     assignment for the old party (if configured on the contract type);
     starts a new *Main Tenant Role* assignment for the new party
     (``invoice_address`` pre-filled from the new party's own default
     invoice address).
   - Re-runs the cash flow plan (``call_create_moves`` with
     ``action='re_calc'``, synchronous, invoice-less) for this one
     contract afterwards, so still-draft plan entries immediately
     reflect the new party instead of waiting for the next scheduled
     ``create_moves`` run to happen to process this contract.

   Button *Partner wechseln* on the contract form, "Parties" tab.

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
   Recomputes and books option rates (see `Option Rate <option_rate.rst>`__) for a
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
