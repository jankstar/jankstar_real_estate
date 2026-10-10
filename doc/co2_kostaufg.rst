*********************************
CO2 Cost Allocation (CO2KostAufG)
*********************************

Part of `Operating Cost Settlement <operating_cost_settlement.rst>`__.

Implements the German *CO2-Kostenaufteilungsgesetz* (CO2KostAufG), which
splits the CO2 cost of heating fuel between tenant and landlord depending on
the building's emission intensity (kg CO2/m²/year). Applies via an optional
``co2_kostaufg`` reference on one or more of a billing unit's settlement
units (typically its *Heizkosten* settlement unit) — settlement units
without a reference are unaffected, and a billing unit with none of its
settlement units referencing one gets no *CO2 Costs* page at all.

.. note::
   The reference and the raw consumption-row table live on
   ``real_estate.settlement_unit``, but
   every *derived* figure (totals, area, per-m² emission, tenant/landlord
   shares) is aggregated on the parent ``real_estate.billing_unit`` instead
   — across **all** of its settlement units that carry a ``co2_kostaufg``
   reference, not just one. This matters when a billing unit's costs are
   split across more than one CO2KostAufG source (e.g. two heating
   circuits, two fuel deliveries under separate master records): the
   billing unit's total consumption/emission/cost figures, and the object
   set used for the area basis, are the union across all of them, not just
   whichever settlement unit happens to be entered first.

``real_estate.co2_kostaufg``  (``co2_kostaufg.py``)
   Master record for one CO2KostAufG data source (e.g. one heating
   installation/fuel), scoped to a ``property`` (required, ``type =
   'property'``) with ``company`` derived from it (Function field).
   Referenced from one or more settlement units of the same property via
   their ``co2_kostaufg`` field (domain-restricted to that property — a
   settlement unit can only pick a CO2KostAufG belonging to its own
   property).
   Menu: *Real Estate → Operation Costs → CO2 Kosten verwalten*.

``real_estate.co2_kostaufg.consumption``  (``co2_kostaufg.py``)
   Child records under a ``co2_kostaufg`` (``parent``, ``ondelete='CASCADE'``),
   one per billed/metered period: ``date_from``/``date_to``,
   ``consumption_kwh``, ``co2_kg_per_kwh`` (emission factor),
   ``co2_emission_kg``, ``co2_price_ct_per_kwh``, ``vat_rate``,
   ``co2_cost_net``, ``co2_cost_gross``.

   ``co2_emission_kg`` is pre-filled (``consumption_kwh × co2_kg_per_kwh``)
   only while still empty — once any value exists (auto-filled or typed by
   the user), later changes to ``consumption_kwh``/``co2_kg_per_kwh`` never
   overwrite it again, so it is always freely (re-)editable, e.g. to enter
   the supplier's own figure. ``co2_cost_net``/``co2_cost_gross`` behave
   differently **on purpose**: they are always recomputed from
   ``consumption_kwh``/``co2_price_ct_per_kwh``/``vat_rate`` whenever any of
   those three change; a manual override of net/gross only sticks until the
   next such recompute.

   ``split``
      Boolean. Set automatically by
      ``SettlementUnit.compute_value_shares()`` when this record was
      created by splitting an original record at a settlement-period
      boundary — see *Splitting at settlement-period boundaries* below.

   Uses ``DeactivableMixin`` — a record replaced by a split is deactivated
   (``active = False``), never physically deleted.

``real_estate.co2_emission_share``  (``co2_kostaufg.py``)
   Configuration table for the legal 10-tier distribution model (Anlage 1
   CO2KostAufG, residential rented buildings without separate sub-metering
   by usage type): ``emission_limit`` (kg CO2/m²/year — the *exclusive*
   upper bound of the tier), ``tenant_share`` / ``landlord_share`` (%, must
   sum to 100 — enforced in ``validate()``).
   ``get_share(value)`` returns the first row, in ``sequence`` order, whose
   ``emission_limit`` is strictly greater than ``value``; if ``value``
   reaches or exceeds every configured limit, the last row (by sequence) is
   used as an open-ended top tier regardless of its own stored limit value.
   Default data for all 10 legal tiers is loaded at module installation
   (< 12 kg → 0 % / 100 % landlord/tenant … ≥ 52 kg → 95 % / 5 %).
   Menu: *Real Estate → Configuration → Emission-CO2 Verteilung*.

Fields kept on ``real_estate.settlement_unit`` — a minimal *CO2 Costs* page
shows just these two:

   ``co2_kostaufg``
      Many2One reference, restricted to CO2KostAufG records of the same
      ``property`` as the settlement unit.

   ``co2_consumption``
      (Function, One2Many, readonly.) All consumption records of the
      referenced CO2KostAufG that overlap *this settlement unit's own*
      period — the raw, per-source audit table.

   The boundary-splitting logic (``_split_co2_consumption()``, see
   *Splitting at settlement-period boundaries* below) still operates per
   settlement unit and its own ``co2_kostaufg``/period, unaffected by the
   aggregation described next.

Fields added to ``real_estate.billing_unit`` — a *CO2 Costs* page is shown
only when ``co2_relevant`` is true (i.e. at least one of the billing unit's
settlement units has ``co2_kostaufg`` set); a *Non-residential building >50%
commercial (§8)* flag at the top of the page then further splits which of
the remaining fields are shown:

   ``co2_relevant``
      (Function.) True if any settlement unit of this billing unit has
      ``co2_kostaufg`` set. Controls the page's own visibility.

   ``non_residential_flag``
      Boolean, default **false**. CO2KostAufG §8: sets whether this
      building is treated as predominantly commercial (>50 % of usable
      area) — where the residential emission-per-m² tier table (Anlage 1)
      does not apply and a flat, configured tenant/landlord split is used
      instead. This is also the corresponding BVED L-Satz field 19
      (Kennzeichen Nichtwohngebäude) — see *BVED External Billing
      Interface* below, whose provider-assignment L-Satz preview and real
      export both read this field directly.

      - **False** (default): ``co2_measurement_type``, ``co2_consumptions``,
        the four totals, ``co2_emission_per_m2``, and the residential-tier
        ``co2_tenant_share``/``co2_landlord_share`` are shown; the two
        commercial share fields are hidden.
      - **True**: only ``co2_commercial_tenant_share`` /
        ``co2_commercial_landlord_share`` are shown; all of the above are
        hidden. (The underlying values are always computed regardless of
        the flag — it only controls what the form displays.)

   ``co2_measurement_type``
      Many2One to ``real_estate.measurement.type`` (object-type
      measurements only) — which measurement to sum for the area basis
      below, across the union of every co2-relevant settlement unit's own
      ``objects`` (each object counted once even if covered by more than
      one such settlement unit).

   ``co2_consumptions``
      (Function, One2Many, readonly.) Union of the consumption records of
      *every* ``co2_kostaufg`` referenced by any settlement unit of this
      billing unit, overlapping the billing unit's own
      ``start_date``/``end_date`` — the aggregated audit table (as opposed
      to each settlement unit's own single-source ``co2_consumption``
      above).

   ``co2_total_consumption`` / ``co2_total_emission`` / ``co2_total_cost_gross``
      (Function.) Sum of ``consumption_kwh`` / ``co2_emission_kg`` /
      ``co2_cost_gross`` across ``co2_consumptions`` above, each weighted by
      the fraction of the record's *own* date range that actually falls
      inside the billing unit's period. A record fully inside the period
      contributes 100 %; a record extending beyond either boundary is
      interpolated pro-rata by days, always relative to its own actual
      range — a record that simply doesn't reach as far as the period's
      end (no later data booked yet) is never extrapolated, it only ever
      contributes its own days.

   ``co2_total_area``
      (Function.) Sum, across the union of objects covered by every
      co2-relevant settlement unit (deduplicated), of each object's latest
      ``real_estate.measurement`` value of ``co2_measurement_type`` (or its
      effective leaf types, if a measurement group) valid as of the billing
      unit's ``end_date``.

   ``co2_emission_per_m2``
      (Function.) ``co2_total_emission / co2_total_area``, annualized via
      ``× 365 / (end_date - start_date + 1)`` so that billing periods
      shorter or longer than a calendar year still yield a correct
      "kg CO2/m²/year" figure.

   ``co2_tenant_share`` / ``co2_landlord_share``
      (Function.) Looked up via
      ``Co2EmissionShare.get_share(co2_emission_per_m2)`` — the residential
      10-tier split. Always computed; only shown when
      ``non_residential_flag`` is false.

   ``co2_commercial_tenant_share`` / ``co2_commercial_landlord_share``
      (Function.) The flat split used for commercial properties (not
      covered by the residential tier model): the company's configured
      ``re_accounting.co2_landlord_share_commercial`` (landlord), and
      ``100 %`` minus that value (tenant). Always computed; only shown when
      ``non_residential_flag`` is true.

**Splitting at settlement-period boundaries.**
``SettlementUnit.compute_value_shares()`` ("Compute Value Shares" button,
also reachable via the billing unit's own button of the same name) calls
``_split_co2_consumption()`` first, before anything else. For each of
``start_date`` and ``end_date + 1 day``, every active consumption record of
the referenced CO2KostAufG whose own ``[date_from, date_to]`` strictly
contains that boundary date is split into two new records at that date:
amounts are interpolated pro-rata by day count (the second part is computed
as the remainder of the first, so the two new records always sum back
exactly to the original — no rounding drift); rate fields
(``co2_kg_per_kwh``, ``co2_price_ct_per_kwh``, ``vat_rate``) are copied
unchanged onto both. Both new records get ``split = True``; the original is
deactivated (soft-deleted via ``active``), never physically removed. A
record entirely inside the settlement period, or one that only covers part
of it because no later data has been booked yet, is never split or
extrapolated — only an *existing* record that actually spans across a
period boundary gets divided. Re-running is idempotent: already
boundary-aligned active records are left untouched, so repeated calls never
produce duplicate splits.
