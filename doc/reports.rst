*******
Reports
*******

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

   .. note::
      **Two genuine, pre-existing bugs found and fixed** while
      implementing the termination confirmation report below (both had
      always been broken — module-consistency tests never render a
      template, so neither was ever caught):

      1. The context helper was named ``_format`` (leading underscore).
         Trytond's report rendering runs Genshi templates through a
         ``SafeASTTransformer`` (``trytond/_safe_genshi.py``) that
         rejects any bare name starting with ``_`` — so
         ``py:content="_format(...)"`` raised
         ``ValueError: invalid name '_format'`` the moment
         ``contract_letter_de.odt`` was actually printed. Renamed to
         ``format_value`` throughout (also in
         ``ContractAnnex4Report``/``anlage4_contract_de.odt``, which had
         the same issue).
      2. ``contract_letter_de.odt`` additionally had a literal
         ``from decimal import Decimal`` inside its ``<?python?>`` block
         (needed for ``sum(..., Decimal(0))``). The same
         ``SafeASTTransformer`` unconditionally forbids *any* import
         statement, raising ``ValueError: invalid import from`` —
         independently of the ``_format`` issue, and would have kept the
         report broken even after fixing that. Fixed by injecting
         ``Decimal`` via ``get_context()`` instead (the same pattern
         core itself uses for ``datetime``), removing the import from
         the template entirely. Also added a ``Decimal`` branch to
         ``format_value()`` (previously missing, so ``total_amount``
         would have rendered as Python's own ``str(Decimal(...))``
         instead of a properly formatted German amount once the import
         itself was fixed).

``real_estate.contract.annex4.report``  (``contract_report.py``)
   Annex 4 – Betriebskostenaufstellung.
   Template: ``anlage4_contract_de.odt``.
   Renders grouped operating cost positions with BetrKV paragraph references
   and allocation method labels, sourced from the contract's own
   ``settlement_units`` field (see ``real_estate.contract`` below) rather than
   re-deriving the billing unit independently. Allocation labels are
   translatable messages (``real_estate.msg_allocation_*`` in ``message.xml``).

``real_estate.contract.termination_confirmation.report``  (``contract_report.py``)
   Termination confirmation letter ("Kündigungsbestätigung").
   Template: ``contract_termination_confirmation_de.odt``.
   Registered exactly like the Contract Letter/Annex 4 reports above — an
   ``ir.action.report`` plus an ``ir.action.keyword`` with
   ``keyword='form_print'`` on ``real_estate.contract,-1`` — so it appears
   in the standard Print toolbar for every contract, not behind a
   dedicated button. "Only available once a termination is recorded" is
   therefore enforced entirely inside ``get_context()``: it checks
   ``record.state == 'terminated'`` for every selected record and raises
   ``msg_contract_termination_confirmation_not_terminated`` (a clear,
   translated error) otherwise, rather than by hiding the menu entry
   itself. Resolves the translated labels for
   ``terminated_by_type``/``termination_notice`` (both ``Selection``
   fields) via ``Contract.fields_get()`` rather than exposing the raw
   storage keys to the template.

``real_estate.base_object.report``  (``base_object.py``)
   Fact sheet for a property or object.
   Template: ``fact_sheet.odt``.
