*******
Reports
*******

ODT templates (OpenDocument Text) are located in ``report/`` and rendered via
Genshi/relatorio; ``template_extension`` on the ``ir.action.report`` record is
``odt``. Values are inserted with ``text:span py:content="..."`` rather than
literal ``${...}`` interpolation (which relatorio escapes in ODT text), and
control flow (``py:if``/``py:for``/``py:choose``) is written as attributes on
the surrounding ODF elements. Older ``.html`` versions of these templates
remain in ``report/`` for reference only and are not registered.

Templates are maintained as ODF XML (``content.xml``/``styles.xml``), not by
re-saving the ``.odt`` in an office suite (which drops the ``py:``
attributes). Context helpers exposed to templates must not start with an
underscore and templates must not contain ``import`` statements (Genshi
sandbox); the shared ``format_value`` helper and ``Decimal`` are provided
via ``get_context()``.

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

``real_estate.contract.index_adjustment.letter``  (``contract_report.py``)
   Declaration of an index rent adjustment (§ 557b para. 3 BGB) on
   ``real_estate.contract.term.adjustment``. Template:
   ``index_adjustment_letter_de.odt`` - one letter per selected
   adjustment (page break), addressed jointly to all main tenants
   (``contract.main_tenant_party_ids``, invoice address). The button
   *Declare* renders it with ``data['original']`` and archives the
   original as attachment; printed from the print menu it is marked
   *Zweitschrift* (declared/done) or *ENTWURF* (before the declaration).
   Index values are formatted with one decimal (``format_index``).

``real_estate.contract.handover.report``  (``contract_report.py``)
   Handover report on ``real_estate.contract.handover``, template
   ``contract_handover_de.odt``: header with landlord, tenants, rented
   object, kind and date, tables of check items, keys (move-out: expected
   quantity) and meter readings, general condition, agreements and
   signature fields; ENTWURF until the report is done.

``real_estate.meter_reading.sheet.report``  (``meter_reading_sheet.py``)
   Meter reading sheet to take along, template
   ``meter_reading_sheet_de.odt`` (landscape): object, reading date,
   reader, selection and a table per meter with rental unit, tenant,
   meter, meter ID, previous reading, new value (empty until entered),
   unit and remarks, signature line; ENTWURF until the sheet is done.

``real_estate.base_object.report``  (``base_object.py``)
   Fact sheet for a property or object.
   Template: ``fact_sheet.odt``.
