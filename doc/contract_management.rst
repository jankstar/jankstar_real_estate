*******************
Contract Management
*******************

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

   - Links to ``party.party`` (contractual partner, see
     ``real_estate.contract.party`` above), ``base_object`` (property),
     and one or more ``ContractItem`` records
   - Generates Tryton accounting moves (invoices) for all active terms
     via ``CreateContractMoves`` wizard (``call_create_moves``)
   - Cash flow tabs on the contract form: *Draft* (invoice state
     ``draft``/``validated``), *Pending* (``posted``), *Paid* (``paid``)
   - ``_refresh_occupancy_for_contracts`` updates occupancy records when
     a contract starts or is terminated; cancelled contracts are excluded
     from occupancy calculations automatically
   - ``add_log`` appends timestamped ``ContractLog`` entries
   - ``next_item_sequence`` / ``next_term_sequence`` auto-increment helpers
   - ``sequence`` is only editable in ``draft``; readonly once
     ``running``/``terminated``/``cancelled``.

   **Contract type before type of use.** ``c_type`` is picked first (its
   domain filters by the company's accounting scheme, ``re_accounting``).
   ``type_of_use`` is only editable (Function field ``c_type_multi_use``)
   once a contract type is chosen **and** it allows more than one type of
   use (its ``types_of_use`` ``MultiSelection``); the selection is then
   restricted to the contract type's allowed values. If the contract type
   allows only one, ``on_change_c_type`` presets ``type_of_use`` to it
   (readonly).

   ``settlement_units`` (Function field, ``get_settlement_units``)
      The contract's *last valid* settlement units: settlement units of the
      property's billing units whose objects overlap with the objects
      assigned to this contract via its items. Billing units are restricted
      to the property's ``next_billing_start_date`` (the earliest non-billed
      billing unit start date); if the property has none set, the most
      recently ``billed`` period is used instead. Used by
      ``get_cost_shares`` (cost shares of these settlement units belonging
      to the contract) and by ``real_estate.contract.annex4.report`` for the
      Anlage 4 print (see `Reports <reports.rst>`__) — the report intentionally reuses
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
   *Wizards*) also writes the resolved ``termination_date`` into
   ``end_date`` — so ``end_date`` always reflects the contract's actual
   end once terminated, fixed-term or not.

   The *Running* button is only shown for ``draft``/``cancelled``. A
   **terminated** contract is reactivated via the *Revert Termination*
   button (``revert_termination``, transition ``terminated → running``,
   only shown for ``state = 'terminated'``). It clears the termination
   fields (``termination_date``, ``terminated_by_type``,
   ``receipt_of_termination_notice``, ``termination_notice``,
   ``termination_reason``) and, **only if the contract is
   ``unlimited``**, also ``end_date`` — a fixed-term contract that was
   terminated early keeps its ``end_date``.

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

``real_estate.contract.party.role``  (``contract_party.py``)
   Configurable role definitions for the "Parties" tab on a contract
   (e.g. *Hauptmieter* / Main Tenant, *Nebenmieter* / Secondary Tenant,
   *Eigentümer* / Owner — shipped as default data), optionally restricted
   to specific contract types via the ``contract_types`` Many2Many
   (``real_estate.contract.party.role-contract.type``); left empty, a
   role applies to every contract type.

   ``mandatory``
      If set, this role must be assigned without gaps for the contract's
      *whole* validity period (``start_date`` to its effective end date,
      or indefinitely if open-ended) — checked via
      ``Contract._check_party_roles`` (``validate_fields``, so on every
      create/write): a *warning* while the contract is still ``draft``
      (the user may still be assembling the party list), a hard
      ``ValidationError`` otherwise.

   ``only_once``
      If set, this role may only be assigned once at any given point in
      time on a contract (no two overlapping ``valid_from``/``valid_to``
      assignments) — same warning-in-draft/error-otherwise split as
      ``mandatory``.

   Confirmed warnings of both checks are remembered per role (not per
   contract): confirming a missing/overlapping role once also skips the
   warning for other draft contracts with the same gap.

``real_estate.contract.party``  (``contract_party.py``)
   One party assignment row (``party``, ``role``, ``valid_from``/
   ``valid_to``) on a contract's "Parties" tab, plus
   ``invoice_address`` (domain-restricted to the assigned party's own
   addresses) and a read-only ``phone_partner`` (first phone contact
   mechanism of the party). A unique SQL constraint on
   ``(party, contract, valid_from, role)`` prevents exact duplicates.

   ``Contract.contractual_partner`` is **derived** from whichever party
   currently holds the contract type's configured *Main Tenant Role*
   here, not set directly — ``on_change_parties`` keeps it in sync. It is
   a stored, required ``Many2One`` column (used by the *Kontenblatt*
   query ``AccountContract.table_query()``).

   ``delete()`` blocks removing the *last* assignment row for a party
   that still has booked (``state='done'``) cash flow entries on the
   contract (``msg_contract_party_delete_has_bookings``) — the party
   must stay traceable even if its specific role/period is being
   corrected, as long as some assignment row for it remains.

   *Change Partner* (see `Wizards <wizards.rst>`__) is the supported way to swap
   the main tenant on a running contract, including rebooking still-open
   invoices — editing the "Parties" tab directly for that purpose is
   still possible but only warns (``ContractPartnerChangedWarning``,
   confirmable) when the outgoing party already has booked entries,
   rather than doing any of the rebooking itself.

``real_estate.contract.item``  (``contract_item.py``)
   Associates one or more rental objects with a contract for a given
   validity period (``label``, ``valid_from``/``valid_to``).

   ``objects`` is a ``Many2Many`` to ``real_estate.base_object`` via the
   relation model ``real_estate.contract.item.object``; the client shows
   the objects with their normal list/form views (including
   ``occupancy_state``). The object selector is restricted to objects of
   the **same property** as the contract, and additionally to
   ``type = 'object'`` for **occupancy contracts**
   (``contract.c_type.occupancy``, mirrored by the Function field
   ``occupancy``). A unique SQL constraint on ``(item, object)`` prevents
   assigning the same object twice to the same item; the same object may
   be assigned to an item of another contract.

   On create/write/delete, triggers occupancy refresh and re-runs
   BillingUnit selection and value-share calculation for the affected
   property.

   ``_check_occupancy_overlap`` — only for occupancy contracts, only
   while the contract isn't ``cancelled`` — checks at save time, for every
   assigned object, whether this item's ``valid_from``/``valid_to`` range
   overlaps an existing ``BaseObjectOccupancy`` period of a *different*
   contract:

   - Overlap with a ``rented`` period → ``ValidationError``
     (``msg_occupancy_overlap``).
   - Overlap with an ``under_negotiation`` period only → confirmable
     ``ContractItemOccupancyWarning`` (``msg_occupancy_overlap_warning``),
     remembered per object.

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
