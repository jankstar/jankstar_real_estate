**************************
Extensions to Core Modules
**************************

``party.party``  (``party.py``)
   Adds ``sequence`` (integer sort key) and ``salutation`` fields.

``account.invoice``  (``invoice.py``)
   Adds a ``contract`` Many2One field so invoices can be traced back to the
   originating contract. Shown on the invoice form's *Other Info* tab
   (view extension ``view/invoice_form.xml``, inherits
   ``account_invoice.invoice_view_form``).

   ``_get_move_line(date, amount)``
      Core builds the invoice's receivable/payable move line directly
      from the invoice header via this method, bypassing
      ``InvoiceLine.get_move_lines()`` entirely (that one only copies
      ``contract`` etc. onto the regular revenue/expense lines, one per
      invoice line — see below). Without this override, the one line
      actually shown on the *Payable/Receivable Lines* list
      (``account.type.receivable``/``payable``) never got a ``contract``,
      even though the invoice header itself has one. Overridden here to
      call ``super()`` then set ``line.contract = self.contract`` before
      returning — takes effect only for invoices posted from now on;
      already-posted invoices' receivable/payable lines cannot be
      corrected retroactively (core blocks writes to a posted move's
      business fields).

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

   ``effective_contract`` (Function field)
      Getter ``on_change_with_effective_contract``, searcher
      ``search_effective_contract``. This line's own ``contract`` if
      set, else the ``contract`` of
      whichever *other* line in the same ``reconciliation`` group has
      one. Needed because a payment line never gets its own ``contract``
      at booking time (``Invoice._get_move_line()`` below only sets it
      on the invoice's own receivable/payable line) — once that line is
      reconciled against the payment, ``effective_contract`` lets the
      payment line be found too when filtering/searching by contract,
      without writing anything onto the (typically already posted)
      payment line itself. The stored ``contract`` field is left
      untouched either way. ``search_effective_contract`` expands to
      ``['OR', ('contract', ...), ('reconciliation.lines.contract', ...)]``
      — a plain dotted domain through the O2M ``reconciliation.lines``,
      no custom SQL needed.

*Payable/Receivable Lines* (``act_contract_move_line_payable_receivable`` in ``contract.xml``)
   Menu *Contracts*, between *Contract* and *Create Contract Moves*. A
   standalone equivalent of the core ``party.party`` form's own
   *Payable/Receivable Lines* relate action
   (``act_move_line_payable_receivable`` in the ``account`` module,
   ``account.move.line.receivable_payable.context``) — same underlying
   list (open, i.e. unreconciled, lines on a receivable- or
   payable-type account, ``account.move.line``) but reachable directly
   from a menu instead of requiring an already-open party record — the
   core action's own ``domain`` is fixed to
   ``('party', 'in', Eval('active_ids'))``, which only resolves once a
   specific party is already open.

   ``order``: ``[('payable_receivable_date', 'ASC NULLS FIRST'),
   ('move', 'ASC')]`` — sorted by the "Datum" column first, then by
   "Buchungssatz" (``move``) as the tiebreaker within the same date
   (core's own action instead falls back to ``('id', 'DESC')`` for that
   second key).

   Tree view: ``contract_move_line_view_list_payable_receivable``
   (``view/contract_move_line_payable_receivable_list.xml``) inherits
   the core ``account.move_line_view_list_payable_receivable`` — none of
   the changes below touch the core view itself, only this module's own
   copy:

   - ``party`` becomes ``optional="1"`` (core's own copy shows it
     unconditionally) — needed here since, unlike the party-form relate
     action, this list isn't already scoped to one party, so hiding the
     column is a real, useful option once a specific ``party``/
     ``contract`` filter is applied.
   - ``payable_receivable_date`` (``maturity_date`` if set, else
     ``date`` — core's own "Date"/"Datum" column) is relabelled
     "Fälligkeitsdatum" and made ``optional="1"``; a second column for
     the plain ``date`` field ("Buchungsdatum") is added right after it,
     also ``optional="1"`` — so both the due date and the booking date
     can be shown side by side, or either hidden, instead of only the
     due-date-if-set column core shows.
   - ``amount`` becomes ``optional="1"`` (core always shows it). Right
     after it, ``debit``/``credit`` (German "Soll"/"Haben", already
     existing ``account.move.line`` fields — a line's debit and credit
     are always mutually exclusive, so no derivation from the signed
     ``amount`` column is needed) are added, both ``optional="1"``.
   - ``payable_receivable_balance`` is relabelled "Saldo" (matching
     core's own override, kept here since the field node was replaced
     for the ``optional="1"`` addition) and made ``optional="1"``
     (core always shows it).

   Filter panel (``real_estate.contract.move_line_payable_receivable.context``,
   own model, not an extension of the core context — the core one has no
   ``contract``/``account``/date-range fields to add to without also
   changing the party form's own relate dialog):

   - ``company`` (required)
   - ``party``, ``contract`` — filters via ``effective_contract`` (see
     ``account.move.line`` above), not the plain stored ``contract``
     field, so a reconciled payment line is found too, not just the
     invoice's own receivable/payable line — ``account`` — all optional,
     exact match
   - ``date_from``/``date_to`` — restrict ``account.move.line.date``
     (the line's own Effective Date)
   - ``receivable``/``payable``/``reconciled`` — same three checkboxes,
     same defaults (``True``/``True``/``False``, also readable from the
     action context, e.g. when reached from elsewhere with
     ``receivable``/``payable``/``reconciled`` pre-set) and the same
     ``context_domain`` shape as the core context's own
     ``account.move.line.receivable_payable.context`` (each unchecked
     toggle exclusion falls back to ``('id', '<', 0)`` — an always-false
     clause — inside its ``OR`` branch, and ``reconciled`` unchecked adds
     ``('reconciliation', '=', None)``).

   *Relate button on the contract form itself*
   (``act_contract_move_line_payable_receivable_relate``) reuses the same
   tree view but **not** the same context model — it has its own, minimal
   ``real_estate.contract.move_line_payable_receivable.relate_context``
   (``date_from``/``date_to`` and the three toggles only, no
   ``company``/``party``/``contract``/``account`` fields). Scoping to the
   contract that was open when the button was pressed is done via a
   plain, static ``domain`` (``('effective_contract', 'in',
   Eval('active_ids'))``), **not** via the context model's own
   ``default_get`` — a ``context_model`` action's ``default_<field>()``
   methods can never see ``active_id``/``active_ids``/``active_model``:
   Sao explicitly strips those from the request context before building
   the RPC payload used to fetch a context model's defaults (unlike a
   wizard's start state, which does receive them). A first attempt at
   pre-filling ``contract`` (later ``party``) via such a
   ``default_contract``/``default_party`` therefore silently never fired;
   the fix was to drop the field-prefill idea entirely for the relate
   case and scope through the static ``domain`` instead, which *is*
   reliably evaluated with ``active_ids`` available (the same PySON
   decoder pass that resolves the action's own ``context``/``order``).
   Consequently company/party/contract/account are not shown as
   selectable fields here at all, since none of them could ever be
   usefully pre-filled or interactively changed on top of the fixed
   contract scoping.

   Print (``real_estate.contract.move_line_payable_receivable.report``)
      Class ``ContractMoveLinePayableReceivableReport`` in ``invoice.py``,
      template ``report/contract_move_line_payable_receivable_de.odt``.
      Registered like any other report in this module (``ir.action.report``
      + an ``ir.action.keyword`` with ``keyword='form_print'`` on
      ``account.move.line,-1``) — select the desired rows in the list
      (e.g. "Select All" after applying the filter panel above) and use
      the client's *Print* action. Not tied to the list's own live
      column/sort choices, since those are client-side UI state the
      report engine cannot see: the printed table always shows a fixed
      column set — Datum (``payable_receivable_date`` —
      ``maturity_date`` if set, else ``date``, matching the list's own
      "Datum" column exactly; using the plain ``date`` field here would
      print the booking date instead of the due date shown in the list
      whenever a line has its own ``maturity_date``), Partei, Soll,
      Haben, Buchungssatz (``move``), Beschreibung (``description_used``
      — the line's own ``description``, falling back to its origin's,
      via the ``DescriptionOriginMixin`` already used by core) — plus a
      totals row (Soll/Haben summed).

      .. note::
         The filter panel's own ``date_from``/``date_to`` still restrict
         the plain ``date`` field (see above), not
         ``payable_receivable_date`` — a related, but distinct,
         inconsistency between the list/report's *display* field and
         the *filter*'s field, left as-is since it wasn't reported as a
         problem; flag if it should also switch to
         ``payable_receivable_date`` for full consistency.

      ``get_context()`` adds ``lines`` (the selected records),
      ``total_debit``/``total_credit`` (summed), and the same
      ``format_value`` helper (date/number formatting) used by
      ``ContractReport``/``ContractAnnex4Report``, extended here with an
      explicit ``Decimal`` branch (the existing helper only handled
      ``float``, needed for ``debit``/``credit``) and now passes
      ``digits=2`` explicitly, so amounts always show exactly two decimal
      places regardless of the underlying ``Decimal``'s own precision.

      .. note::
         **Naming fix:** this helper and its template placeholder were
         originally named ``_format`` (leading underscore). Trytond's
         report rendering runs Genshi templates through a
         ``SafeASTTransformer`` (``trytond/_safe_genshi.py``) that
         rejects any bare name starting with ``_`` (except a small
         allow-list, e.g. ``__class__``) to keep templates from reaching
         private/dunder attributes — so ``py:content="_format(...)"``
         raised ``ValueError: invalid name '_format'`` the moment the
         report was actually printed (``Report.execute()``), even though
         the module installed and all module-consistency tests passed
         (they never render a template). Renamed to ``format_value``
         throughout (Python class and ``content.xml``) to fix this for
         both this report and the *Kontenblatt* one below, which reuses
         the same pattern. Lesson: any context variable/helper exposed
         to a Genshi report template must not start with an underscore.

      ``_selection_summary()`` builds a one-line German summary of the
      filter panel's own values ("Partei: …; Vertrag: …; Konto: …;
      Zeitraum: … - …; Forderungen, Verbindlichkeiten; inkl.
      ausgeglichene Posten") from ``Transaction().context`` — printed
      near the report header (``selection_summary`` in the template) so
      the applied filter is visible on the printout itself, not just on
      screen. This only works because
      ``act_contract_move_line_payable_receivable`` (unlike the plain
      party-form relate action, and unlike most other
      ``context_model``-based actions in this codebase) also declares
      its own ``context`` field forwarding every
      ``real_estate.contract.move_line_payable_receivable.context``
      field into the transaction context — ``context_domain`` alone
      only uses those values to build the search ``domain`` client-side,
      it does **not** by itself make them available server-side for
      anything else (like this report). If a value was never set in the
      panel, its section is simply omitted; with nothing set at all the
      summary reads "keine Einschränkung".

      .. note::
         The template's own formatting (10pt table font, right-aligned
         Soll/Haben, per-column widths — narrow throughout except a wide
         Beschreibung column) is defined via
         ``<office:automatic-styles>`` directly inside
         ``content.xml`` (``PHead10``/``PHead10Right``/``PContent10``/
         ``PContent10Right`` paragraph styles, ``Col*`` table-column
         styles) rather than by editing the ``.odt`` in LibreOffice:
         LibreOffice does not recognize the ``py:`` (Genshi) namespace
         used for the template's placeholders and drops those attributes
         entirely on save, silently breaking the report. Any further
         layout change to this report should go through
         ``content.xml``/``styles.xml`` as text, never through opening
         and re-saving the ``.odt`` itself in an office suite.

*Kontenblatt* (``act_contract_general_ledger_account_contract`` in ``contract.xml``)
   Menu *Contracts*, between *Payable/Receivable Lines* and *Create
   Contract Moves*. A standalone equivalent of the ``real_estate.contract``
   form's own *Party Ledger* ("Kontenblatt") button
   (``Contract.open_party_ledger()`` in ``contract_core.py``, opening
   ``act_general_ledger_account_contract_form_contract`` — a
   ``form_relate`` action whose ``domain`` is fixed to
   ``('contract', 'in', Eval('active_ids'))``, so it only ever shows the
   already-open contract's own rows). Same underlying model
   (``real_estate.account_contract`` — per-(account, party) aggregated
   balance/debit/credit for the contract's own party, joined to
   ``real_estate.contract`` via ``contractual_partner`` in
   ``GeneralLedgerAccountContract.table_query()``), reachable directly
   from a menu, with no ``active_ids``-dependent domain and no fixed
   contract restriction — matching how core's own analogous standalone
   *General Ledger - Accounts* menu entry
   (``act_general_ledger_account_form``) works. Carries over the same
   ``search_value`` default as that core action
   (``[('line_count', '!=', 0)]`` — hides accounts with no activity).

   ``context_model``: ``real_estate.contract.general_ledger_account_contract.context``
   (``ContractGeneralLedgerAccountContractContext`` in ``contract_core.py``)
   — a Python subclass of core's own ``GeneralLedgerAccountContext``
   (``account.general_ledger.account.context``), inheriting its
   fiscalyear/period/date-range/company/posted/journal fields and
   defaults unchanged, and adding two extra filter fields on top:
   ``party`` and ``contract``. Registered under its own model name
   (not by extending core's context model directly) so that other,
   unrelated General Ledger views keep using core's context model
   as-is. The act_window's ``context_domain`` translates these two
   extra fields into a domain on ``real_estate.account_contract`` (which
   already exposes ``party``/``contract`` as plain columns):
   ``If(Eval('party', None), [('party', '=', Eval('party', None))], [])``
   and the analogous clause for ``contract`` — an empty clause (``[]``)
   when the field is left blank, so leaving both empty behaves exactly
   as before (no restriction beyond ``search_value``). View:
   ``contract_general_ledger_account_contract_context_form.xml`` (a
   full, standalone form — not an ``inherit`` of core's own context
   form, since inheriting requires the same model — with ``party`` and
   ``contract`` added above the unchanged core fields).

   Tree view: ``contract_general_ledger_account_contract_view_list``
   (``view/contract_general_ledger_account_contract_list.xml``) inherits
   ``general_ledger_account_contract_list`` and adds the ``contract``
   column (``optional="1"``) right after ``party`` — present but
   commented out in the base view (redundant there, since every row is
   always the one already-open contract; useful here since rows for
   every contract are mixed together in one list).

   .. note::
      **Company scoping fix in** ``AccountContract.table_query()``
      (``real_estate.contract.account_contract``, ``contract_core.py``) —
      a pre-existing gap only exposed once this standalone menu removed
      the implicit company-scoping that the ``form_relate`` button always
      had via its ``active_ids``-restricted domain. The (account, party)
      grouping's join to ``real_estate.contract`` (to populate the
      ``contract`` column) previously matched on
      ``contractual_partner`` alone, with no ``company`` filter anywhere
      in the query. Once reachable without an ``active_ids`` restriction,
      this could return rows from other companies, and — worse — yield
      *more than one* joined ``contract`` row for the same
      (account, party) pair whenever that party has more than one
      contract (a follow-up contract after termination, or contracts in
      different companies), breaking the SQL view's id uniqueness and
      raising ``RuntimeError: Undetected access error`` on read. Fixed by
      (1) filtering the query by
      ``account.company == context.get('company')``, matching core's own
      ``_GeneralLedgerAccount.table_query()`` pattern, and (2) joining
      against a grouped subquery of ``real_estate.contract`` (one row per
      ``contractual_partner``, restricted to the current company,
      ``Max(id)`` picking the most recent contract when several match)
      instead of the raw table directly, guaranteeing at most one match
      per party. Both the pre-existing ``form_relate`` button and this
      new standalone menu use the same underlying model and benefit from
      the fix.

   Print (``real_estate.contract.general_ledger_account_contract.report``)
      Class ``ContractGeneralLedgerAccountContractReport`` in
      ``contract_core.py``, template
      ``report/contract_general_ledger_account_contract_de.odt``.
      Registered the same way as the Payable/Receivable report above
      (``ir.action.report`` + an ``ir.action.keyword`` with
      ``keyword='form_print'`` on ``real_estate.account_contract,-1``) —
      select the desired rows in the *Kontenblatt* list and use the
      client's *Print* action. Fixed column set (independent of the
      list's own live column/sort choices): Konto, Partei, Vertrag,
      Anfangssaldo, Soll, Haben, Endsaldo — plus a totals row (all four
      numeric columns summed, matching the list's own ``sum="1"``
      columns).

      Same ``format_value`` helper and ``get_context()``/
      ``_selection_summary()`` pattern as the Payable/Receivable report
      (see above, including the leading-underscore naming pitfall this
      new report deliberately avoided from the start). ``_selection_summary()``
      here reflects the *Kontenblatt* context model's own fields instead
      (Partei, Vertrag, Geschäftsjahr, Periode, Zeitraum, Journal,
      "nur gebuchte Bewegungen") — available server-side only because
      ``act_contract_general_ledger_account_contract`` declares an
      explicit ``context`` field forwarding all ten
      ``ContractGeneralLedgerAccountContractContext`` fields into the
      transaction context, on top of them already feeding
      ``context_domain`` (for ``party``/``contract``) resp. being read
      directly via ``Transaction().context.get(...)`` inside
      ``table_query()`` (for the core fiscalyear/period/date/company/
      posted/journal fields, unaffected by ``context_domain``).

      .. note::
         Without that explicit ``context`` field, the generic
         ``test_ir_action_window`` module-consistency test caught an
         unrelated but real bug during development: ``pyson.Eval(name)``
         without an explicit default decodes to an empty string
         (``''``), not ``None``, whenever the variable is absent from
         the evaluation context. ``account.general_ledger.account.
         context``'s ``default_fiscalyear()`` then does
         ``fiscalyear_id >= 0`` on that empty string and raises
         ``TypeError``. Fixed by giving every ``Eval(...)`` in this
         action's ``context`` field an explicit ``None`` (``False`` for
         ``posted``) default. The pre-existing Payable/Receivable
         action's own ``context`` field has the same latent gap, left
         unchanged here since it happens to be harmless there
         (``account.move.line`` never reads those keys inside a
         ``table_query()``, unlike this General-Ledger-based model).

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
