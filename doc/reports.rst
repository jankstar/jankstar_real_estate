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

Several records in one document (letters, protocols, meter reading
sheets): every record starts on a new page and the page numbering
restarts at 1 - the first paragraph of a record uses the paragraph style
``PBreak`` (break before page, master page *Standard*, page number 1),
chosen with two paragraphs and ``py:if="index"`` / ``py:if="not
(index)"``; expressions inside ODF attributes (``text:style-name="${...}"``)
are not evaluated. The master page has a footer *Seite N*.

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
   original as attachment of the adjustment and of the contract (copy
   sharing the stored file). Mark: *ENTWURF* before the announcement, none while announced and the receipt is not captured (dispatch), *Zweitschrift* afterwards.
   Index values are formatted with one decimal (``format_index``).

``real_estate.contract.comparative_rent.letter``  (``contract_report.py``)
   Request for consent to a rent increase up to the local comparative
   rent (§§ 558, 558a BGB) on ``real_estate.contract.term.adjustment``.
   Template: ``comparative_rent_letter_de.odt`` - one letter per
   adjustment to all main tenants (as the index declaration) with current
   and new net rent, increase, effective date, reasons (rent survey,
   version and kind, table cell, classification from the calculation
   protocol, deviating accepted rent with reason), cap with its basis,
   period for consideration (``consent_until``) and a consent form.
   *Announce* of the adjustment run archives the original.

``real_estate.modernisation.announcement_letter``  (``modernisation.py``)
   Announcement of a modernisation (§ 555c BGB) on
   ``real_estate.modernisation.unit``. Template:
   ``modernisation_announcement_de.odt`` - one letter per rental unit
   (page break, page numbering per letter) to all main tenants with kind
   and scope of the measure, energy saving, start and duration, expected
   increase per month and per m², future operating costs, hardship
   objection (§ 555d BGB) and special termination right (§ 555e BGB).
   *Announce* on the measure archives the original at the unit and the
   contract. Mark *ENTWURF* only for a print before the announcement.

``real_estate.modernisation.increase_letter``  (``contract_modernisation.py``)
   Declaration of a modernisation increase (§ 559b BGB) on
   ``real_estate.contract.term.adjustment``. Template:
   ``modernisation_increase_de.odt`` - one letter per adjustment to all
   main tenants (as the index declaration, same marks) with the
   reference to the announcement, the measure, costs per trade on the
   basis of the unit with maintenance share, third-party funds,
   allocation key, calculation, cap, rent before/increase/new rent,
   effective date and the special termination right (§ 561 BGB).
   *Announce* of the adjustment run archives the original.

``real_estate.contract.term.adjustment.run.letters``  (``contract_report.py``)
   *Letters to Send* on the adjustment run (button *Print Letters*,
   state announced/ready): all announced adjustments without captured
   receipt in one document, rendered by the letter report of the
   procedure without mark; error if none is left.

``real_estate.contract.term.adjustment.run.sample_letter``  (``contract_report.py``)
   *Sample Letter* on the adjustment run (button *Sample Letter*, state
   selected/calculated/approved - before the announcement): the letter of
   the first adjustment without error (else the first one not cancelled)
   of the run, rendered by the letter report of the procedure with the
   mark *ENTWURF*; nothing is archived. Error if the run has no
   adjustment with a letter.

``real_estate.modernisation.sample_letter``  (``modernisation.py``)
   *Sample Announcement* on the modernisation (button *Sample Letter*,
   state planning/draft, not for a vacancy or trivial measure): the
   announcement of the first rental unit with a contract and an increase
   with the mark *ENTWURF*; nothing is archived. Error if no such unit
   exists (determine the rental units first).

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
