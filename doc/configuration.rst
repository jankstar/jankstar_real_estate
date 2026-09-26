*************
Configuration
*************

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
   ``horizon_months_ahead``, ``invoice_state``, ``future_contracts_horizon_days``,
   ``last_run`` (updated by the dispatcher), ``active``. Task names are
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
      ``Contract.call_create_moves()`` for running/terminated contracts of
      the company, and for not-yet-started contracts whose ``start_date``
      is within ``today + future_contracts_horizon_days`` (the row's own
      field, default 60) — already-running/-ended contracts are always
      included regardless of this value; it only decides how far ahead of
      their actual start not-yet-started contracts get pulled in early.
      For every contract included, ``Term.re_calc()`` (``contract_term.py``)
      recalculates that term's cash flow up to a **fixed** horizon of
      exactly 1 year from today (``_re_calc_year = 1``, not related to and
      not affected by ``future_contracts_horizon_days``). It does **not**
      create invoices — booking is a separate, explicitly scheduled step,
      see ``_cron_book_contract_cash_flow`` below.

   ``_cron_book_contract_cash_flow``
      Books (creates invoices for) all due terms, using
      ``action='re_calc_and_create'`` so it is self-sufficient regardless of
      whether ``_cron_update_contract_cash_flow``'s horizon already covers
      the target date. The horizon is the end of the month that is
      ``horizon_months_ahead`` months after the run date — e.g. with
      ``schedule_day_of_month = 15`` and ``horizon_months_ahead = 1``, a run
      on 15.07 books everything due up to 31.08. The row's own
      ``invoice_state`` (``draft``/``posted``, default ``draft``) is passed
      through to ``call_create_moves``/``_create_moves`` and determines
      whether the created invoices are posted immediately or left as
      drafts for manual review. Note: each invoice's own ``invoice_date``/
      ``accounting_date`` is *not* forced to this month-end horizon — it is
      the individual term's own computed ``document_date`` (see
      ``_create_moves``, ``inv_date = invoice_date or document_date`` with
      ``invoice_date=None`` here), which may differ per term/rhythm.

   ``_cron_update_option_rate``
      Recomputes and, where the rate actually changed, books new option
      rates via ``OptionRate.process_update()`` (``option_rate.py`` — the
      same logic as the manual ``real_estate.option_rate_update.wizard``,
      see `Wizards <wizards.rst>`__) for every property of every company using this
      ``re_accounting`` configuration, as of today's date. Intended to run
      monthly with ``schedule_day_of_month = 1``, which also determines
      the ``effective_date`` used by ``process_update`` (the 1st of the
      current month). Per-record results (created/updated/unchanged/
      skipped counts, plus one detail line per processed object) go to the
      Python logger, not ``contract.log``, since this task is not tied to
      individual contracts.
