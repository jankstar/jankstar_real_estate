*********************************
Option Rate (Input VAT Deduction)
*********************************

Tracks, over time, what percentage of input VAT (Vorsteuer) on purchase invoices
related to a real estate object is deductible ("optiert") rather than treated
as a final cost (added to the gross expense) — relevant wherever the property
owner can opt for VAT liability on rent (§ 9 UStG). Applies to
``real_estate.base_object`` only (property / building / land / rental
object) - billing units and settlement units have no option rate (they are
not booked on; the operating cost settlement relieves the property and
charges the rental objects with their own option rates).

``account.invoice.line.taxes_deductible_rate`` auto-fill  (``invoice.py``)
   For purchase invoice lines (``invoice_type = 'in'``), the core
   ``taxes_deductible_rate`` field (0–1 fraction of input VAT that is
   deductible; core already forces it to ``0`` when
   ``company.purchase_taxes_expense`` is set, via its own
   ``on_change_company``) is auto-filled from the applicable option rate,
   divided by 100. Applies both interactively (``on_change_base_object``
   and the other ``on_change_*`` of the line) and to
   programmatic line creation (``InvoiceLine.create()`` override) — the
   latter only fills the field when the caller did **not** pass
   ``taxes_deductible_rate`` explicitly, so an explicit value is never
   overridden.

   The object used is picked by ``InvoiceLine._option_rate_priority()``:
   the booked ``base_object``, else the derived ``property`` (fallback via
   ``on_change_with_property`` / ``term.property``).
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
   History-versioned option rate record of an object (``base_object``,
   required, ``ondelete='CASCADE'``), valid from a given date; a unique SQL
   constraint prevents two records for the same object and ``valid_from``.
   ``option_rate`` is a percentage (``digits=(5, 2)``, domain 0–100).

Fields added to ``real_estate.base_object``:

   ``option_rate_method``
      Required selection: ``fix_0`` (always 0 %), ``fix_100`` (always 100 %),
      or ``dynamic_measurement`` (calculated — see the wizard below).
      Defaults to ``fix_0``. On a rental object (``base_object`` with
      ``type = 'object'``), changing ``type_of_use`` auto-sets it to
      ``fix_100`` for ``commercial`` and ``fix_0`` otherwise
      (``on_change_type_of_use``). A rental object only allows ``fix_0``
      and ``fix_100`` (``validate_fields``,
      ``msg_option_rate_method_object_fixed``): the operating cost billing
      distributes its costs gross (0 %) or net (100 %); ``fix_value`` and
      ``dynamic_measurement`` are left to property/building/land.

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

   Shown as a dedicated *Option Rate* page on the ``base_object`` form
   (``page_option_rate``).

``real_estate.option_rate_update.wizard``  (see `Wizards <wizards.rst>`__)
   Batch recalculation entry point; see the `Wizards <wizards.rst>`__ page for the full
   selection/calculation logic.

**Selection / filter screen and standalone list.** Menu:
*Real Estate → Master Data → Update Option Rates*, with a child menu item
*Option Rates* opening a read-only list of all ``real_estate.option_rate``
records (both list and form views are fully non-editable —
``creatable="0"`` plus ``readonly="1"`` on every field; this applies only to
the standalone list, not to the ``option_rates`` tab embedded in the
base_object form, which remains editable
there). A *Selektion* context form — modelled on the *Occupancy* context
pattern (``real_estate.option_rate.context``, class ``OptionRateContext``) —
sits above the list with the optional filter field ``base_object``, which
narrows the list via ``context_domain`` (PYSON).
