*******************************
BVED External Billing Interface
*******************************

Part of `Operating Cost Settlement <operating_cost_settlement.rst>`__.

Implements the BVED / ARGE-FHW "Standard-Datenaustausch" Version 3.10 —
the German fixed-width record format used to exchange operating-cost data
with an external Messdienstleister (heating-cost/consumption billing
service) — for billing units with ``external_billing = True`` (see
`Operating Cost Settlement <operating_cost_settlement.rst>`__). Exports the property/tenant master
data plus optional fuel and cost data the provider needs to bill
(A-/L-/M-/B-/K-Satz); imports the provider's response (D-Satz actual
costs, plus optional E835-/E898-/P-Satz) and applies it back onto
``real_estate.settlement_result``. Implemented in ``bved.py`` (Tryton
models) and ``bved_records.py`` (pure-Python fixed-width (de)serialization
with no Tryton dependency, unit-testable standalone).

Menu: *Real Estate → Operation Costs → Externe Abrechnung* (placed
immediately before *Betriebskostenabrechnung*), bundling all models below.

``real_estate.bved.unit``  (``bved.py``)
   Reference table mirroring BVED Tabelle 'E' ("Einheiten/Maßeinheiten",
   see ``bved_records.TABLE_E``) — ``code`` (3-digit key, e.g. ``'010'``),
   ``description`` (e.g. ``'m² Wohnfläche'``), and ``name`` (Function,
   ``"{code} - {description}"``, e.g. ``'010 - m² Wohnfläche'``). All 29
   entries from the table are loaded as default data at module
   installation, with ``measurement_type`` left unset — mapping a unit to
   a ``real_estate.measurement.type`` (e.g. ``'010 - m² Wohnfläche'`` →
   the "Living Space" measurement type) is a per-database configuration
   decision, made via the *BVED Units* list (menu: *Real Estate →
   Operation Costs → Externe Abrechnung → BVED Units*). Used by
   ``real_estate.bved.provider_assignment.allocation1_unit/
   allocation2_unit/allocation3_unit`` (below) to resolve M-Satz fields
   36-41.

``real_estate.bved.service_provider``  (``bved.py``)
   The Messdienstleister itself: ``party``, ``bved_key`` (2-char code from
   BVED Tabelle 'U', e.g. ``'40'`` for ista — not enforced as a fixed
   selection since the table changes over time), ``bved_version``
   (currently only ``'3.10'``), ``transport_type`` (only ``'manual'``
   file download/upload is actually implemented; ``email``/``sftp``/
   ``webservice_api`` are reserved for a future automated transport layer).

   *M-Satz field 7 (Kennzeichen Adressfeld) and address-source rules:*

   ``field7_mode``
      Selection ``'1'``\ =Nutzer / ``'2'``\ =Eigentümer /
      ``'3'``\ =Eigentümer/Nutzer / ``'4'``\ =Leistungsnehmer (default
      ``'1'``, matching the field's old hardcoded value). Written
      unchanged into M-Satz field 7 of every record generated for this
      provider, and controls which address block(s)
      ``BvedObjectNumber._m_satz_values()`` actually fills:

      - ``'1'``/``'3'`` — fields 8-15 (Nutzer) from the occupying
        contract's own party (``entry.contract.contractual_partner``).
      - ``'2'``/``'3'`` — fields 16-23 (Eigentümer) per ``owner_rule``.
      - ``'4'`` — fields 59-66 (Leistungsnehmer) per ``tenant_rule``.

   ``owner_rule``
      Selection ``'company'``\ =Gesellschaft ist Eigentümer /
      ``'role'``\ =Eigentümer über Rolle (default ``'role'``). Visible/
      required only when ``field7_mode`` is ``'2'``/``'3'``, but always
      *evaluated* (see ``provider_org_rule`` below) regardless of
      ``field7_mode``. ``'company'``: the Eigentümer block is filled
      from the company party/address (the same ones passed as
      ``company_party``/``company_address``). ``'role'``: filled via
      ``owner_role`` instead.

   ``owner_role``
      Many2One to ``real_estate.object_party.role`` — which role counts
      as "Eigentümer" (used when ``owner_rule = 'role'``), resolved via
      ``BvedObjectNumber._find_party_by_role()`` below. Defaults to the
      module's built-in "Owner" role (``object_party_owner_role``) for
      new records; a provider that needs a different role (e.g. one
      that also covers ``building``/``land``, since the built-in role
      only covers ``property``/``object``) can override it here.

   ``tenant_rule``
      Selection ``'tenant'``\ =Mieter / ``'role'``\ =über Partner-Rolle
      (default ``'tenant'``). Visible/required only when ``field7_mode``
      is ``'4'``. ``'tenant'``: the Leistungsnehmer block (59-66) is
      filled the same way as the Nutzer block (the occupying contract's
      own party — reproducing the module's original, unconditional
      "debtor mirrors tenant" behavior). ``'role'``: filled via
      ``tenant_role`` instead.

   ``tenant_role``
      Many2One to ``real_estate.object_party.role`` — which role counts
      as "Leistungsnehmer" (used when ``tenant_rule = 'role'``), looked
      up the same way as ``owner_role``.

   ``provider_org_rule``
      Selection ``'owner'``\ =Leistungsgeber wie Eigentümer /
      ``'role'``\ =über Partner-Rolle (required, default ``'owner'``).
      Fills M-Satz fields 42-49 (Leistungsgeber name/address) —
      **independent of** ``field7_mode`` (fields 42-49 are always
      attempted, regardless of what field 7 selects). ``'owner'``:
      reuses whichever party/address ``owner_rule`` resolved to, even
      if ``field7_mode`` itself isn't ``'2'``/``'3'`` (so a provider can
      have field 7 = "Nutzer" while still deriving the Leistungsgeber
      block from the configured Eigentümer source). ``'role'``: filled
      via ``provider_org_role`` instead.

   ``provider_org_role``
      Many2One to ``real_estate.object_party.role`` — which role counts
      as "Leistungsgeber" (used when ``provider_org_rule = 'role'``),
      looked up the same way as ``owner_role``.

   ``tax_id_type``
      Selection sourced from ``party.identifier.get_types()`` (all
      globally-configured identification types, e.g. ``'de_vat'``) —
      which type on the company party (Leistungsgeber, the same party
      used for M-Satz fields 42-49) provides M-Satz field 51 (USt-ID-Nr.
      oder Steuernummer). When set and the company party has a matching
      ``party.identifier``, field 51 gets that identifier's ``code`` and
      field 50 gets ``tax_id_flag`` below; both fields stay unset if
      left empty or no matching identifier exists.

   ``tax_id_flag``
      Selection ``'1'``\ =USt-ID-Nr. / ``'2'``\ =Steuernummer (visible/
      required only when ``tax_id_type`` is set; default ``'2'``,
      matching the field's old hardcoded value). Written into M-Satz
      field 50 (Kennzeichen USt-ID/Steuernummer) whenever field 51 is —
      the admin's own classification of what the configured
      ``tax_id_type`` actually represents, since Tabelle 'E' has no
      generic notion of "this is a USt-ID vs. a Steuernummer" built in.

   ``tax_rate_flag``
      Selection ``'1'``\ =Regelsteuersatz / ``'2'``\ =ermäßigt,
      optional (Kann-Feld). Written unchanged into M-Satz field 52
      (Kennzeichen Steuersatz) of every record for this provider; left
      unset, field 52 stays unset too.

   ``invoice_number_flag``
      Selection ``'0'``\ =keine Rechnung §14 UStG / ``'1'``\ =aus Feld
      54 / ``'2'``\ =vom Abrechnungsunternehmen erstellt, optional
      (Kann-Feld). Written unchanged into M-Satz field 53 (Kennzeichen
      Rechnungsnummer). ``'1'`` additionally requires
      ``invoice_number_rule`` to fill field 54 itself.

   ``invoice_number_rule``
      Selection ``'contract'``\ =Nr. Mietvertrag / ``'object'``\ =Nr.
      Mietobjekt / ``'settlement_result'``\ =ID Settlement result.
      Visible/required only when ``invoice_number_flag`` is ``'1'``.
      Fills M-Satz field 54 (Rechnungsnummer, max. 25 chars) per
      occupancy segment: ``'contract'`` — the occupying contract's own
      ``contract_number``; ``'object'`` — this mapping's own
      ``base_object.object_number``; ``'settlement_result'`` — the
      ``id`` of the ``real_estate.settlement_result`` matching this
      object (and contract, or ``None`` for a vacancy segment) whose
      ``billing_unit`` period overlaps ``[period_start, period_end]``.
      Field 54 stays unset if no matching value/record is found.

   ``direct_debit_flag``
      Selection ``'0'``\ =keine Abbuchungserlaubnis /
      ``'1'``\ =Abbuchungserlaubnis, default ``'0'``. Written unchanged
      into M-Satz field 58 (Kennzeichen Zahlungsart) of every record
      for this provider.

   The optional selection fields ``owner_rule``, ``tenant_rule``,
   ``invoice_number_rule``, ``tax_id_flag``, ``tax_rate_flag``,
   ``invoice_number_flag`` and ``direct_debit_flag`` include a blank
   choice, so they can be left empty.

``real_estate.bved.provider_assignment``  (``bved.py``, form label "BVED Provider-Liegenschaft")
   Anchors one provider + customer number + 9-digit Liegenschaftsnummer
   (``external_property_number``) to a ``base_object`` of type
   ``property`` or ``building``, with ``valid_from``/``valid_to`` so a
   provider change over time doesn't destroy history. Unique per
   ``(base_object, provider, valid_from)`` — a property/building may have
   several *concurrent* assignments for different providers (e.g. heating
   via Techem, water via ista, both on the same building). Referenced
   explicitly from ``billing_unit.bved_provider_assignment`` (never
   derived from the object tree), since one building can have more than
   one active assignment and only the user knows which one a given
   billing unit means.

   ``object_numbers``
      One2Many to ``real_estate.bved.object_number`` (below).

   ``allocation1_unit`` / ``allocation2_unit`` / ``allocation3_unit``
      ("M-Satz Allocation Key 1/2/3") Many2One to ``real_estate.bved.unit``
      each. Resolve M-Satz fields 36/37, 38/39, 40/41 (Schlüssel/Anteil
      Umlage 1-3) for every object number mapping under this assignment,
      via ``BvedObjectNumber._allocation_shares()``: field 36/38/40 gets
      the unit's own ``code`` (Tabelle 'E'), field 37/39/41 gets the
      rental object's own measurement value (as of the M-Satz row's
      ``occupancy_end``) for the unit's mapped ``measurement_type`` — left
      unset if the unit has no ``measurement_type`` mapped (the key is
      still written on its own in that case) or if the slot itself is
      left empty.

   ``tenant_change_fee_flag``
      Selection ``'0'``\ =keine Umlage / ``'1'``\ =Umlage (required,
      default ``'0'``). Written unchanged into M-Satz field 68
      (Kennzeichen Umlage Nutzerwechselgebühr) of every record generated
      for this provider assignment — unlike the other M-Satz catalog
      settings (on ``real_estate.bved.service_provider``), this one is
      set per assignment, since it may differ per Liegenschaft under the
      same provider.

   *L-Satz Preview* page — read-only preview of how this assignment's
   L-Satz (Liegenschaft) record would look today, split into two field
   groups:

   - **Automatic** — ``l_period_start``/``l_period_end`` (always the most
     recently completed calendar year), ``l_provider_key``, ``l_street``/
     ``l_country``/``l_postal_code``/``l_city`` (from the property's/
     building's address), ``l_vat_flag`` (from the covered billing units'
     Optionssatz: 100 % → net/fully opted, 0 % → no VAT shown, mixed →
     per M-Satz field 25/user), ``l_weg_flag`` (from ``calculation_method``
     — Cash basis sets it, Accrual basis doesn't), ``l_non_residential_flag``
     (true if any covered billing unit's own ``non_residential_flag`` is
     set — see `CO2 Cost Allocation <co2_kostaufg.rst>`__), ``l_co2_landlord_share_percent``
     (from the covered heating-cost billing unit's own
     ``co2_landlord_share``/``co2_commercial_landlord_share``),
     ``l_total_area`` (computed once a measurement type is selected below).
   - **To Be Entered** — ``gross_floor_area_measurement_type`` (drives
     ``l_total_area``: summed, as of each billing unit's own end date,
     over the union of every assigned billing unit's own
     ``covered_rental_objects()`` — objects with a settlement result
     where one exists, else every object covered by a settlement unit;
     each object counted once even if covered by several billing units),
     plus six purely-manual fields with no derivable source:
     ``vacancy_risk_flag``/``vacancy_risk_percent``, ``labor_share_flag``,
     ``energy_improvement_flag``, ``heat_supply_flag``,
     ``heat_connection_2023_flag`` (various L-Satz Kann-/Muss-Felder —
     legal facts about the building not represented anywhere else in the
     data model). ``vacancy_risk_flag`` is also reused, unchanged, for
     M-Satz field 26 (Kennzeichen Umlageausfallwagnis) — see
     ``BvedObjectNumber._m_satz_values()`` below.

   The preview always uses the most recently completed calendar year
   across every billing unit currently assigned; the real export
   (``BvedExport._build_l_m_records()``) recomputes the same underlying
   helpers per specific billing unit and its own period instead, so
   preview and actual export can differ if a billing unit's period
   doesn't align with a plain calendar year.

``real_estate.bved.object_number``  (``bved.py``)
   Maps one rental object to its ``internal_reference`` ("Ordnungsbegriff
   des Auftraggebers") and 4-digit ``external_unit_number`` under a
   provider assignment, with its own ``valid_from``/``valid_to`` — a
   provider renumbering (e.g. after a renovation) should close the old row
   and add a new one rather than overwrite ``internal_reference`` in
   place, otherwise already-imported historical D-Satz lines referencing
   the old number can no longer be resolved. Numbers are assigned
   automatically (``BvedExport._ensure_object_numbers()``) the first time
   an object is exported — scoped per assignment (not per billing unit)
   and counted all-time, so a closed mapping's number is never reused by a
   later one.

   ``_m_satz_values(period_start, period_end, provider, company_party=None, company_address=None, warnings=None, refresh_occupancy=True)``
      Returns the list of M-Satz value dicts for this mapping's object
      over the given period — one dict per
      ``real_estate.base_object.occupancy`` segment overlapping it
      (vacancy periods included with ``vacancy_flag=1``). Field 25
      (Kennzeichen MwSt, ``vat_treatment_flag``) is derived per segment
      from the object's own Optionssatz as of that segment's
      ``occupancy_end``: ``0`` (kein Ausweis) if 0 % (or unknown), else
      ``1`` (gewerbl. Vermietung). Field 7 (``address_flag``) and the
      Nutzer/Eigentümer/Leistungsnehmer/Leistungsgeber blocks are
      governed by ``provider.field7_mode``/``owner_rule``/
      ``tenant_rule``/``provider_org_rule`` — see
      ``real_estate.bved.service_provider`` above for the full rule
      description. Bank account fields (55/56) and ``vacancy_flag``
      keep coming unconditionally from the occupying contract's own
      party, independent of ``field7_mode``. Field 51 (USt-ID-Nr. oder
      Steuernummer) comes from ``company_party``'s own
      ``party.identifier`` of the type configured on
      ``provider.tax_id_type`` — always the company party specifically,
      never the ``field7_mode``/``provider_org_rule``-resolved
      Leistungsgeber party; field 50 (Kennzeichen USt-ID/Steuernummer)
      is ``provider.tax_id_flag`` whenever field 51 is set, otherwise
      both fields stay unset. Field 52 (Kennzeichen Steuersatz) is
      ``provider.tax_rate_flag`` unchanged, if set. Fields 53/54
      (Kennzeichen Rechnungsnummer / Rechnungsnummer) come from
      ``provider.invoice_number_flag`` and, when that is ``'1'``,
      ``provider.invoice_number_rule``. Field 58 (Kennzeichen
      Zahlungsart) is ``provider.direct_debit_flag`` unchanged (see
      ``real_estate.bved.service_provider`` above for all of these).
      Field 68 (Kennzeichen Umlage Nutzerwechselgebühr) is
      ``assignment.tenant_change_fee_flag`` unchanged — this one comes
      from the provider *assignment* (``real_estate.bved.
      provider_assignment`` above), not the provider itself. Field 26
      (Kennzeichen Umlageausfallwagnis) is ``1`` if
      ``assignment.vacancy_risk_flag`` (the assignment's own L-Satz
      field 13) is set, else ``0`` — reusing the L-Satz value directly
      rather than a separate M-Satz-specific setting. The single,
      shared implementation of the M-Satz record content — used both by
      the real export
      (``BvedExport._build_l_m_records()``) and by
      ``refresh_m_satz_preview()`` below, so they can never diverge.
      ``refresh_occupancy`` (default ``True``) recomputes
      ``real_estate.base_object.occupancy`` first.

   ``_find_party_by_role(ObjectParty, role_id, as_of_date)``
      Generic role-based party lookup — shared by the Eigentümer
      (``owner_role``), Leistungsnehmer (``tenant_role``), and
      Leistungsgeber (``provider_org_role``) resolutions alike: searches
      ``real_estate.object_party`` for ``role_id``, valid *exactly on*
      ``as_of_date`` (a point-in-time check — ``valid_from <= as_of_date``
      and no ``valid_to`` or ``valid_to >= as_of_date`` — not merely
      overlapping the billing period), walking up from this mapping's own
      ``base_object`` through its ``parent`` chain (rental object →
      building/land → property) until a match is found or the top of the
      tree is reached. Returns ``None`` immediately if ``role_id`` is
      ``None``. All three call sites in ``_m_satz_values()`` use
      ``period_end`` as ``as_of_date`` (resolved once per call, not
      per occupancy segment).

   ``_area_share_by_mode(mode, as_of_date)``
      Shared by ``_heating_base_share()`` (``mode='central_heating'``,
      M-Satz fields 27/69) and ``_hotwater_base_share()``
      (``mode='central_hot_water'``, fields 30/70). Returns
      ``(share, key)``:

      - ``share`` — the object's own **direct** measurement value (via
        ``Measurement.get_total_value()``, as of ``as_of_date``) for the
        ``heating_area_measurement_type`` of the (first, if several)
        settlement unit belonging to this mapping's object's property
        with ``heating_billing_mode = mode``. Deliberately **not**
        time-weighted by the occupancy segment (unlike
        ``cost_share.area_share``, which drives the actual cost
        allocation and is prorated by ``time_share``/``time_total``) and
        **not** affected by the
        ``heating_consumption_share_percent``/``heating_area_share_percent``
        split — fields 27/30 always report the object's plain Bemessung.
        Does not require ``compute_value_shares()`` to have been run at
        all (no cost share involved). ``None`` — leaving the field
        unset (Kann-Feld) — if no qualifying settlement unit has a
        ``heating_area_measurement_type`` set, or the object has no
        matching measurement recorded.
      - ``key`` — the BVED Tabelle 'E' code (see ``real_estate.bved.unit``
        above) of the unit whose own ``measurement_type`` matches that
        measurement type — i.e. the unit ``share`` is actually expressed
        in. ``None`` if none is mapped.

      ``_heating_base_share(as_of_date)`` and
      ``_hotwater_base_share(as_of_date)`` are thin wrappers writing
      into fields 27/69 and 30/70 respectively (called with the M-Satz
      row's own ``occupancy_end`` as ``as_of_date``) — the two are fully
      independent (a property can have both a central-heating and a
      central-hot-water settlement unit, each with its own
      ``heating_area_measurement_type``/mapped ``real_estate.bved.unit``).

   ``_mode_settlement_unit(mode)``
      The first ``real_estate.settlement_unit`` of this mapping's own
      object's property with ``heating_billing_mode = mode``, or
      ``None`` — the same lookup ``_area_share_by_mode()`` performs
      inline, factored out since ``_advance_by_mode()`` below needs it
      independently of any ``heating_area_measurement_type``.

   ``_advance_by_mode(mode, contract, start_date, end_date)``
      M-Satz fields 28/29 (Heizung Vorauszahlung Brutto/Netto,
      ``mode='central_heating'``) or 31/32 (Warmwasser Vorauszahlung
      Brutto/Netto, ``mode='central_hot_water'``) — **not** 30/31, which
      is the Warmwasser Grundanteil/Vorauszahlung-Brutto pair
      respectively; field 30 itself is the (already-implemented)
      Warmwasser Grundanteil, see ``_area_share_by_mode()`` above.
      Returns ``(gross, net)``, either possibly ``None``:

      - Resolves the qualifying settlement unit via
        ``_mode_settlement_unit(mode)`` and, through it, its own
        ``billing_unit`` — the billing unit whose *Konditionstyp*
        (``term_types_of_use``) and *Vorauszahlungen* tab
        (``cash_flow_lines``) define which advance-payment condition
        applies. ``(None, None)`` if no qualifying settlement unit, or
        it has no ``billing_unit``.
      - For ``mode='central_hot_water'``: if the property's own
        central-heating settlement unit exists and shares the *same*
        ``billing_unit`` as the central-hot-water one, returns
        ``(None, None)`` unconditionally — German rental contracts
        normally carry a single combined "Heizkosten" advance payment
        covering both heating and hot water; attributing it to both
        fields would double it. Sharing a billing unit is the normal
        setup where one annual "Heizkosten" cost group contains both a
        central-heating and a central-hot-water settlement unit side by
        side (see ``tests/test_billing_unit.py``'s two-Settlement-Unit
        "Heizkosten" billing unit).
      - Otherwise, sums ``total_amount`` (gross) and ``amount`` (net)
        over every entry of the billing unit's own ``cash_flow_lines``
        (already filtered there by ``term_types_of_use``/invoice state,
        see `Operating Cost Settlement <operating_cost_settlement.rst>`__) whose own ``contract``
        matches ``contract`` and ``base_object`` matches this mapping's
        own object, restricted to ``document_date`` within
        ``[start_date, end_date]``. ``(None, None)`` if nothing matches
        (a genuine Kann-Feld, not a zero).

      ``_heating_advance(contract, start_date, end_date)`` and
      ``_hotwater_advance(contract, start_date, end_date)`` are thin
      wrappers, called from ``_m_satz_values()`` with the M-Satz row's
      own ``occupancy_start``/``occupancy_end`` (not the whole export
      period) and its resolved tenant contract (``None`` for a vacancy
      segment, in which case both return ``(None, None)`` immediately).

      .. note::
         Fields 33-35 (Kaltwasser Grundanteil/Vorauszahlung) already
         exist as Kann-Felder on ``real_estate.bved.object_number.m_satz_line``
         (``coldwater_base_share``/``coldwater_advance_gross``/``_net``)
         but are not populated by ``_m_satz_values()`` — there is no
         ``heating_billing_mode`` value for a centrally-billed cold-water
         system (cold water is always metered per object via
         ``allocation_by_consumption`` in this module), so
         ``_mode_settlement_unit()``/``_advance_by_mode()`` have no
         analogous "central cold water" case to resolve them from.

   ``_allocation_shares(as_of_date)``
      Resolves M-Satz fields 36-41 (Schlüssel/Anteil Umlage 1-3): for
      each of the provider assignment's ``allocation1_unit``/
      ``allocation2_unit``/``allocation3_unit`` slots (in order), returns
      ``(code, share)`` — ``code`` is the ``real_estate.bved.unit``'s own
      Tabelle 'E' code, ``share`` is this mapping's own ``base_object``'s
      measurement value (via ``Measurement.get_total_value()``, no
      time-weighting) for the unit's ``measurement_type`` as of
      ``as_of_date`` — or ``(code, None)`` if the unit has no
      ``measurement_type`` mapped, or ``None`` for an unset slot. Always
      returns exactly 3 entries. Called with each M-Satz row's own
      ``occupancy_end`` as ``as_of_date``.

   ``m_satz_lines`` / ``refresh_m_satz_preview``
      A stored (not Function) One2Many to
      ``real_estate.bved.object_number.m_satz_line`` (below), populated
      by the ``refresh_m_satz_preview`` button: deletes any existing
      preview lines for the mapping, then rebuilds them from
      ``_m_satz_values()`` for the most recently completed calendar year
      (same period as the provider assignment's L-Satz preview,
      ``BvedProviderAssignment._last_full_year()``) — one line per
      occupancy segment. Deliberately a real, explicitly-triggered
      button rather than a Function field: a Function getter runs inside
      a *read-only* database transaction (plain ``read()`` RPCs), where
      ``_m_satz_values(refresh_occupancy=True)``'s
      delete-and-recreate inside ``Occupancy.refresh()`` would fail
      outright — and a true multi-row, per-field table needs real
      addressable child records for Tryton's list/form widgets anyway.

``real_estate.bved.object_number.m_satz_line``  (``bved.py``)
   One row per occupancy segment, generated only by
   ``BvedObjectNumber.refresh_m_satz_preview()`` — never created or
   edited directly (every field is readonly). Holds all 70 M-Satz fields
   from the BVED Nutzer/Eigentümer-Satz spec (field number prefixed in
   each field's label, e.g. "8. Tenant Name 1"), grouped on the form by
   spec section (identification, tenant, owner, occupancy period,
   VAT/vacancy-risk/heating-hotwater-coldwater shares, allocations,
   provider organization, tax/invoice/bank/payment, debtor, other
   flags/keys). The embedded list view shows just
   ``occupancy_start``/``occupancy_end``/``vacancy_flag``/``tenant_name1``
   for a quick overview across several tenants/vacancy periods; opening a
   row shows the full detail form.

Fields added to ``real_estate.billing_unit``:

   ``bved_provider_assignment``
      Which provider assignment applies (domain: same property/building
      subtree, validity window covering the billing unit's start date).
      Only visible when ``external_billing`` is set.

   ``bved_object_numbers``
      (Function, One2Many.) The assignment's object numbers, restricted to
      objects actually covered by this billing unit
      (``bved_covered_object_ids()`` — type ``object`` base objects
      reachable via at least one non-``no_allocation`` settlement unit).

   ``check_bved_provider_assignment()``
      Validation (run from ``pre_validate``) rejecting a billing unit
      whose covered objects include one that is neither the assignment's
      own ``base_object`` nor a descendant of it (e.g. an object from a
      different building than the one referenced).

   Shown on a dedicated *BVED* page, visible only when ``external_billing``
   is set.

Fields added to ``real_estate.settlement_unit`` (B-Satz — fuel/stock/hot-water
data, typically entered only on the heating-cost settlement unit):

   ``bved_fuel_data``
      Enables the rest of the B-Satz fields below; also identifies "the"
      heating-cost unit representative of a billing unit's CO2 landlord
      share (see `CO2 Cost Allocation <co2_kostaufg.rst>`__).

   ``bved_fuel_type`` (BVED Tabelle 'B'), ``bved_heating_value``,
   ``bved_fuel_indicator`` (field 23, Kennzeichen Brennstoffart —
   Selection ``'0'``-``'9'``, default ``'0'``), and ``bved_fuel_rule``
   (``'stock'``/``'meter'``, default ``'stock'``) — selects which of two
   mutually exclusive field groups below the *B-Satz / Brennstoff* page
   shows; two further groups apply either way and are always shown.

   ``bved_fuel_indicator`` distinguishes several concurrent B-Satz fuel
   records for the same property/period (e.g. two fuel suppliers each
   feeding their own externally-billed settlement unit within the same
   billing period). ``'0'`` if field 8 (``bved_fuel_type``) is left
   empty, else ``'1'``-``'9'``. ``on_change_bved_fuel_type`` keeps it
   consistent automatically: clearing field 8 resets it to ``'0'``;
   setting field 8 bumps it from ``'0'``/empty to ``'1'`` (the user may
   raise it to ``'2'``-``'9'`` by hand for an additional concurrent fuel
   record). ``SettlementUnit.validate_fields`` enforces, whenever
   ``bved_fuel_data`` is set: the '0' ↔ empty-field-8 correspondence
   above, and — for a non-``'0'`` value — uniqueness across every other
   settlement unit of the same property (``billing_unit.property``)
   whose billing period overlaps this one's
   (``billing_unit.start_date``/``end_date``).

   ``'stock'`` (Bestandsführung, B-Satz fields 10-17 — storable fuels
   like heating oil, tracked via initial/closing stock only): stock
   start/end date + quantity + amount (gross/net). Hidden when
   ``bved_fuel_rule = 'meter'``.

   *WW-Anteil* (B-Satz fields 18-22 — hot-water average
   temperature/consumption/flat-rate percentage/meter start-end) and
   *Versorgungszeitraum* (B-Satz fields 24-27 — up to two heating and
   two hot-water supply periods, start/end each) apply to both
   ``bved_fuel_rule`` values and are always shown (once
   ``bved_fuel_data`` is set) regardless of it.

   ``'meter'`` (Zähler, B-Satz fields 28-34 — district heating or other
   supply metered directly, without a storable stock):
   ``bved_meter_type`` (BVED Tabelle 'G'), ``bved_meter_measurement_unit``
   (Many2One to ``real_estate.bved.unit``, BVED Tabelle 'E' — the same
   model used for the M-Satz allocation keys above, reused here since it
   already covers the full Tabelle 'E' code list), ``bved_meter_number``,
   ``bved_meter_consumption``, ``bved_meter_reading_start``/
   ``bved_meter_reading_end``. ``bved_primary_energy_factor`` (field 34)
   is shown as part of this group, per the standard's field-position
   grouping, even though it is a property of the fuel type (mandatory for
   Fernwärme) rather than of the metering method itself. Hidden when
   ``bved_fuel_rule = 'stock'``.

   All four groups are always packed into the B-Satz record regardless
   of ``bved_fuel_rule`` — the fields belonging to the currently hidden
   group are simply left empty by the user and packed blank/zero as
   usual.

   .. note::
      Every field label in this section (and the L-Satz Preview fields
      on ``real_estate.bved.provider_assignment`` below) is prefixed
      with its record field number, e.g. "10. Stock Start Date" —
      matching the convention already used by the M-Satz Preview line
      model. ``bved_fuel_data`` and ``bved_fuel_rule`` are left
      unnumbered since they are module-only controls, not fields of the
      B-Satz record itself.

   K-Satz cost records (``BvedExport._build_b_k_records()``) are built not
   only from invoice lines booked directly on the externally-billed
   settlement unit, but also from every settlement unit of the same
   billing unit that uses ``allocation_via_cost_collector`` with it as
   ``reference_settlement_unit`` (e.g. several fuel suppliers, each
   invoiced separately, feeding one heating settlement unit) — each such
   invoice line keeps its own settlement unit's ``type.bved_cost_key``
   rather than the referenced unit's, since the underlying invoices may
   carry a different cost-type classification. B-Satz (fuel/stock data
   above) is unaffected — it stays tied to the externally-billed
   settlement unit itself.

Export (``real_estate.bved.export``, workflow Draft → Generated → Sent):

   ``provider`` + ``cutoff_date`` (default: 31 December of the previous
   year — a still-running billing period shouldn't be exported yet since
   its cost data isn't final) default-select the eligible ``billing_units``
   (assigned to this provider, ``external_billing = True``,
   ``end_date <= cutoff_date``); the list stays editable.
   ``record_types`` (multi-select A/L/M/B/K, default all five) controls
   which files get built.

   ``generate``
      Validates every selected billing unit has a provider assignment
      matching this export's provider and a complete property address,
      auto-creates any missing object numbers, then builds one ``.DAT``
      file per requested record-type group (A; L+M combined; B+K
      combined) and attaches them (ISO-8859-1 encoded, CRLF line
      endings) to the export record. Sets ``export_date`` and moves to
      ``generated``.

   ``mark_sent``
      Moves to ``sent`` — the actual transmission happens outside the
      app (manual file handoff, per the provider's ``transport_type``).

   All activity (files built, warnings such as a missing German IBAN for
   the A-/M-Satz bank fields) is appended to ``activity_log``.

Import (``real_estate.bved.import``, workflow Draft → Parsed → Matched →
Processed):

   Attach the provider's response file(s) as ``ir.attachment`` on the
   import record (filename prefix determines the record type: D/E835/
   E898/P), then:

   ``parse``
      Full fresh snapshot on every click: deletes every not-yet-``applied``
      line and rebuilds ``real_estate.bved.import.line`` rows from
      whatever is currently attached, so re-running after attaching a
      corrected/additional file never leaves stale duplicates.
      Already-``applied`` lines are never touched.

   ``match``
      Re-evaluates every line not yet ``applied`` (including previously
      ``error``/``skipped`` ones, so fixing a missing object number and
      clicking again re-checks them too). Resolves
      ``internal_reference`` + provider to a ``bved.object_number`` valid
      on the line's period end date, then the matching
      ``settlement_result`` for that object — cross-checked against the
      result's own billing unit's provider assignment, so an object with
      two concurrent externally-billed billing units (e.g. heating via
      one provider, water via another) cannot be matched to the wrong
      result. E835-/E898-/P-Satz lines missing "Letzter Tag
      Nutzungszeitraum" (a Mussfeld per spec for these three types) are
      flagged as an error rather than guessed. A line with no data and no
      match is ``skipped`` (not an error); one with data and no match is
      an ``error``.

   ``apply``
      Writes matched data onto the ``settlement_result``:

      - **D-Satz** — lines for the same result are grouped by
        ``d_cost_key`` (BVED Tabelle 'K' cost-type code): different keys
        are summed (e.g. Heizung + Warmwasser), two lines sharing the
        same key (including both empty) are treated as a duplicate
        delivery and only the last is kept, with a warning. Sets
        ``actual_costs`` (re-running ``on_change_actual_costs()`` so
        ``refund_receivable`` updates immediately), plus a plausibility
        check (total − advance ≈ balance per the D-Satz's own figures;
        reported advance vs. the internally computed
        ``advanced_payment`` — skipped when the reported sum is exactly
        0, since BVED's fixed-width numeric fields can't distinguish
        "blank" from "genuinely zero"). Sets ``bved_state`` to
        ``validated`` or ``validation_error`` (with the concatenated
        messages in ``bved_check_message``). Already-``applied`` D-Satz
        lines whose result is still ``validation_error`` are re-evaluated
        on every subsequent Apply run too, so a plausibility-check fix
        (e.g. a corrected advance payment) takes effect without
        re-parsing.
      - **E898-Satz** — copies the referenced PDF attachment (matched by
        filename) from the import onto the settlement result.
      - **E835-/P-Satz** — informational only; no settlement-result field
        exists to write them back to, browsable via the result's own
        ``bved_e835_lines``/``bved_p_lines`` tabs.

      Afterwards, logs which of a touched billing unit's covered objects
      still have no D-Satz result (``bved_state`` not yet
      ``imported``/``validated``/``validation_error``) as a completeness
      check.

   ``line_summary``
      (Function.) A per-record-type/state line count plus amount summary
      (D-Satz total, E835/P-Satz user-share subtotal) shown on the import
      form.

``real_estate.bved.import.line``  (``bved.py``)
   One row per parsed fixed-width record, typed fields for all four
   import record types (D/E835/E898/P) plus ``raw_line``/``raw_data``
   (full field dump as JSON) for audit. States: ``parsed`` → ``matched``
   → ``applied`` (or ``skipped``/``error``). Form notebook pages
   *D-Satz*/*E835-Satz*/*E898-Satz*/*P-Satz* show/hide automatically based
   on ``record_type`` (``view_attributes()``); the *Row* page (raw data)
   is always visible.

Fields added to ``real_estate.settlement_result``:

   ``bved_state``
      Selection (awaiting_import / imported / validated /
      validation_error) tracking the data-exchange progress independently
      of ``state`` (approved/billed); editable until billed, e.g. to
      manually clear a plausibility-check false positive.

   ``bved_import_date`` / ``bved_check_message`` / ``bved_import_line``
      (readonly) — when the last D-Satz was applied, its check messages
      (if any), and the import line that last wrote ``actual_costs``.

   ``bved_matched_lines``
      (Function, One2Many.) Every import line matched to this result,
      regardless of type/state, shown as one unified, detailed table.

   ``bved_e835_lines`` / ``bved_p_lines`` / ``bved_e835_labor_share_user_total`` / ``bved_p_user_amount_total``
      (Function.) Informational subsets of ``bved_matched_lines`` by
      record type, and their summed amounts.

**Demo / test tooling.** ``tests/test_bved_provider_response.py`` has no
trytond/database dependency (it loads ``bved_records.py`` directly from
disk by path) and simulates a provider's response from a set of exported
A-/L-/M-/K-Satz files: pools K-Satz costs per property, distributes them
across M-Satz units weighted by heating advance payment × occupancy-period
length in days (with reproducible random jitter and a largest-remainder,
cent-exact correction so the total still matches exactly), emits D-Satz
plus, where applicable, E835-Satz (labor share) and a small synthetic
P-Satz (Energiepreisbremse — format exercise only, the underlying support
program has since ended), and one E898-Satz record per unit/period
referencing a generated single-page PDF "Heizkostenabrechnung" (period,
per-cost-type total vs. share, overall total/advance payment/balance)
built with a dependency-free, hand-rolled minimal PDF writer::

   python tests/test_bved_provider_response.py DTA310_....DAT DTM310_....DAT \
       DTK310_....DAT [--out-dir DIR] [--seed N]
