*********************************
Option Rate (Input VAT Deduction)
*********************************

Tracks, over time, what percentage of input VAT (Vorsteuer) on purchase invoices
related to a real estate object is deductible ("optiert") rather than treated
as a final cost (added to the gross expense) — relevant wherever the property
owner can opt for VAT liability on rent (§ 9 UStG). Applies to
``real_estate.base_object`` (property / building / land / rental object),
``real_estate.settlement_unit``, and ``real_estate.billing_unit``.

``account.invoice.line.taxes_deductible_rate`` auto-fill  (``invoice.py``)
   For purchase invoice lines (``invoice_type = 'in'``), the core
   ``taxes_deductible_rate`` field (0–1 fraction of input VAT that is
   deductible; core already forces it to ``0`` when
   ``company.purchase_taxes_expense`` is set, via its own
   ``on_change_company``) is auto-filled from the applicable option rate,
   divided by 100. Applies both interactively (``on_change_base_object`` /
   ``on_change_settlement_unit`` / ``on_change_billing_unit``) and to
   programmatic line creation (``InvoiceLine.create()`` override) — the
   latter only fills the field when the caller did **not** pass
   ``taxes_deductible_rate`` explicitly, so an explicit value is never
   overridden.

   The real-estate reference used is picked by
   ``InvoiceLine._option_rate_priority()`` in order of specificity:
   ``base_object`` → ``settlement_unit`` → ``billing_unit`` → the derived
   ``property`` (as a ``base_object`` reference, last-resort fallback via
   ``on_change_with_property`` / ``term.property``) — the first of these
   that is set on the line wins.
   ``OptionRate.get_current_rate_fraction(ref_field, record, date)`` then
   returns the record's latest ``option_rate`` at or before that date
   (``taxes_date`` if set, else the invoice's ``invoice_date``, else
   today), divided by 100; falling back to ``1``/``0`` for
   ``fix_100``/``fix_0`` if no history record exists yet, or ``None``
   (leaving the field untouched) for ``dynamic_measurement`` with no
   booked history.

   The auto-fill is skipped entirely (field left at its core default of
   ``1``) when: the line is not a purchase line, or the company has
   ``purchase_taxes_expense`` set (core's own logic already governs that
   case). The line's ``contract`` field has no bearing on this logic and
   is ignored — a real-estate reference is used whenever present, even on
   a line that also carries a ``contract``.

``real_estate.option_rate``  (``option_rate.py``)
   History-versioned option rate record, valid from a given date. Has three
   mutually exclusive Many2One reference fields — ``base_object``,
   ``settlement_unit``, ``billing_unit`` (all ``ondelete='CASCADE'``) — exactly
   one of which must be set (enforced in ``validate()``); a unique SQL
   constraint prevents two records for the same reference and ``valid_from``.
   ``option_rate`` is a percentage (``digits=(5, 2)``, domain 0–100).

Fields added to ``real_estate.base_object``, ``real_estate.settlement_unit``,
and ``real_estate.billing_unit`` (identical on all three):

   ``option_rate_method``
      Required selection: ``fix_0`` (always 0 %), ``fix_100`` (always 100 %),
      or ``dynamic_measurement`` (calculated — see the wizard below).
      Defaults to ``fix_0``. On a rental object (``base_object`` with
      ``type = 'object'``), changing ``type_of_use`` auto-sets it to
      ``fix_100`` for ``commercial`` and ``fix_0`` otherwise
      (``on_change_type_of_use``); ``dynamic_measurement`` is rejected by
      ``validate_fields`` for rental objects — only property/building/land/
      settlement unit/billing unit may use it.

   ``option_measurement_type``
      Many2One to ``real_estate.measurement.type``, required only for
      ``dynamic_measurement``. May reference a measurement **group**: all of
      its descendant leaf types are then summed per rental object (see the
      group hierarchy under ``real_estate.measurement.type`` above).

   ``option_rates``
      One2Many (readonly) to the object's own ``real_estate.option_rate``
      history.

   ``purchase_taxes_expense``
      Function field mirroring the pre-existing ``company.purchase_taxes_expense``
      field (added by ``account_invoice``). When set on the object's company,
      all input VAT is always booked as an expense (fully gross) —
      equivalent to a permanent option rate of 0 % — and the *Option Rate*
      notebook page is hidden on the form (also always hidden for
      ``type = 'equipment'``).

   Shown as a dedicated *Option Rate* page on the ``base_object``,
   ``settlement_unit``, and ``billing_unit`` forms (``page_option_rate``).

``real_estate.option_rate_update.wizard``  (see `Wizards <wizards.rst>`__)
   Batch recalculation entry point; see the `Wizards <wizards.rst>`__ page for the full
   selection/calculation logic.

**Selection / filter screen and standalone list.** Menu:
*Real Estate → Master Data → Update Option Rates*, with a child menu item
*Option Rates* opening a read-only list of all ``real_estate.option_rate``
records (both list and form views are fully non-editable —
``creatable="0"`` plus ``readonly="1"`` on every field; this applies only to
the standalone list, not to the ``option_rates`` tab embedded in the
base_object/settlement_unit/billing_unit forms, which remains editable
there). A *Selektion* context form — modelled on the *Occupancy* context
pattern (``real_estate.option_rate.context``, class ``OptionRateContext``) —
sits above the list with three optional filter fields, ``base_object``,
``billing_unit``, ``settlement_unit``; whichever one is set narrows the list
via ``context_domain`` (PYSON, evaluated independently per field, so any
combination — or none — can be applied).
