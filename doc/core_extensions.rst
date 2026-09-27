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
      Sets the invoice's ``contract`` on the receivable/payable move line
      as well, so the open item shown on the *Payable/Receivable Lines*
      list can be traced to its contract (revenue/expense lines get it
      via the invoice lines, see below).

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
      set, else the ``contract`` of whichever *other* line in the same
      ``reconciliation`` group has one. This way payment lines, which
      carry no ``contract`` of their own, are found by contract once they
      are reconciled with the invoice's receivable/payable line. The
      stored ``contract`` field is not changed.

*Payable/Receivable Lines* (``act_contract_move_line_payable_receivable`` in ``contract.xml``)
   Menu *Contracts*, between *Contract* and *Create Contract Moves*. Lists
   open (unreconciled) lines on receivable/payable accounts
   (``account.move.line``) across all parties — the same list as the core
   *Payable/Receivable Lines* relate action on the party form, but
   reachable from a menu without opening a party first.

   ``order``: ``[('payable_receivable_date', 'ASC NULLS FIRST'),
   ('move', 'ASC')]`` — by due date, then by move.

   Tree view: ``contract_move_line_view_list_payable_receivable``
   (``view/contract_move_line_payable_receivable_list.xml``, inherits
   ``account.move_line_view_list_payable_receivable``):

   - ``party`` — optional column.
   - ``payable_receivable_date`` ("Fälligkeitsdatum" — ``maturity_date``
     if set, else ``date``) and ``date`` ("Buchungsdatum") — both
     optional.
   - ``amount``, ``debit`` ("Soll"), ``credit`` ("Haben") — optional.
   - ``payable_receivable_balance`` ("Saldo") — optional.

   Filter panel (``real_estate.contract.move_line_payable_receivable.context``,
   own context model):

   - ``company`` (required)
   - ``party``, ``contract``, ``account`` — optional, exact match;
     ``contract`` filters via ``effective_contract`` (see
     ``account.move.line`` above), so reconciled payment lines are found
     too
   - ``date_from``/``date_to`` — restrict ``account.move.line.date``
   - ``receivable``/``payable``/``reconciled`` — checkboxes with the same
     defaults (``True``/``True``/``False``) and behaviour as the core
     party-form dialog; can be preset via the action context.

   *Relate button on the contract form itself*
   (``act_contract_move_line_payable_receivable_relate``) reuses the same
   tree view with its own, minimal context model
   ``real_estate.contract.move_line_payable_receivable.relate_context``
   (``date_from``/``date_to`` and the three toggles only). The list is
   restricted to the open contract via the action's static ``domain``
   ``('effective_contract', 'in', Eval('active_ids'))``.

   Print (``real_estate.contract.move_line_payable_receivable.report``)
      Class ``ContractMoveLinePayableReceivableReport`` in ``invoice.py``,
      template ``report/contract_move_line_payable_receivable_de.odt``.
      Registered as ``ir.action.report`` with an ``ir.action.keyword``
      (``keyword='form_print'``) on ``account.move.line,-1`` — select the
      desired rows in the list and use the client's *Print* action. The
      printed table has a fixed column set, independent of the list's
      column/sort settings: Datum (``payable_receivable_date`` — due date
      if set, else booking date, as in the list), Partei, Soll, Haben,
      Buchungssatz (``move``), Beschreibung (``description_used``) — plus
      a totals row (Soll/Haben summed). The filter panel's
      ``date_from``/``date_to`` restrict the booking date (``date``).

      ``get_context()`` adds ``lines`` (the selected records),
      ``total_debit``/``total_credit`` (summed), and the ``format_value``
      helper (date/number formatting, amounts with two decimal places)
      also used by ``ContractReport``/``ContractAnnex4Report``.

      ``_selection_summary()`` builds a one-line German summary of the
      filter panel's values ("Partei: …; Vertrag: …; Konto: …;
      Zeitraum: … - …; Forderungen, Verbindlichkeiten; inkl.
      ausgeglichene Posten") from ``Transaction().context``, printed near
      the report header (``selection_summary``); with no filter set it
      reads "keine Einschränkung". The action's ``context`` field forwards
      all filter panel fields into the transaction context for this
      purpose.

*Kontenblatt* (``act_contract_general_ledger_account_contract`` in ``contract.xml``)
   Menu *Contracts*, between *Payable/Receivable Lines* and *Create
   Contract Moves*. A standalone equivalent of the ``real_estate.contract``
   form's own *Party Ledger* ("Kontenblatt") button
   (``Contract.open_party_ledger()`` in ``contract_core.py``, opening
   ``act_general_ledger_account_contract_form_contract``, restricted to
   the open contract). Same underlying model
   (``real_estate.account_contract`` — per-(account, party) aggregated
   balance/debit/credit for the contract's own party), reachable directly
   from a menu without a fixed contract restriction, like core's
   *General Ledger - Accounts* menu entry. Default ``search_value``
   ``[('line_count', '!=', 0)]`` hides accounts with no activity.

   ``AccountContract.table_query()`` (``contract_core.py``) is restricted
   to the current company (``context['company']``) and joins at most one
   contract per contractual partner (the most recent one, ``Max(id)``).

   ``context_model``: ``real_estate.contract.general_ledger_account_contract.context``
   (``ContractGeneralLedgerAccountContractContext`` in ``contract_core.py``)
   — a subclass of core's ``GeneralLedgerAccountContext``
   (``account.general_ledger.account.context``) with its
   fiscalyear/period/date-range/company/posted/journal fields, plus two
   extra filter fields ``party`` and ``contract``, applied via the
   act_window's ``context_domain`` (no restriction when left empty).
   View: ``contract_general_ledger_account_contract_context_form.xml``.

   Tree view: ``contract_general_ledger_account_contract_view_list``
   (``view/contract_general_ledger_account_contract_list.xml``) inherits
   ``general_ledger_account_contract_list`` and adds the ``contract``
   column (``optional="1"``) right after ``party``.

   Print (``real_estate.contract.general_ledger_account_contract.report``)
      Class ``ContractGeneralLedgerAccountContractReport`` in
      ``contract_core.py``, template
      ``report/contract_general_ledger_account_contract_de.odt``.
      Registered the same way as the Payable/Receivable report above (on
      ``real_estate.account_contract,-1``) — select the desired rows in the
      *Kontenblatt* list and use the client's *Print* action. Fixed column
      set: Konto, Partei, Vertrag, Anfangssaldo, Soll, Haben, Endsaldo —
      plus a totals row.

      Same ``format_value`` helper and ``get_context()``/
      ``_selection_summary()`` pattern as the Payable/Receivable report;
      the summary reflects the *Kontenblatt* filter fields (Partei,
      Vertrag, Geschäftsjahr, Periode, Zeitraum, Journal, "nur gebuchte
      Bewegungen"), forwarded via the action's ``context`` field.

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

``res.user``  (``res.py``)
   Adds ``phone`` and ``mobile`` fields.
