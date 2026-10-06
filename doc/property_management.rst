*******************
Property Management
*******************

``real_estate.address``  (``address.py``)
   Structured address with granular fields (``street_name``,
   ``building_number``, ``unit_number``, ``floor_number``, ``room_number``,
   ``post_box``) plus an unstructured fallback text field.
   Supports both formats and is linked to ``base_object`` records.

``real_estate.base_object``  (``base_object.py``)
   Central entity for every real estate asset.

   *Types:* ``property`` · ``building`` · ``object`` · ``land`` · ``equipment``

   *Workflow:* Draft → Active → Closed

   Key features:

   - Parent–child tree (``tree()`` mixin), e.g. Property → Building → Apartment
   - ``sequence`` unique per type and parent (constraint
     ``sequence_unique``); when parent and type are set and the sequence is
     empty, the next free one below the parent is proposed (step 10,
     ``on_change_with_sequence``). The object number is the parent's
     object number plus ``/`` and the sequence.
   - One2Many relations to ``Address``, ``ObjectParty``, ``Measurement``,
     and ``BillingUnit``
   - History tracking via ``BaseObjectOccupancy`` (tenant occupancy periods)
   - ``occupancy_state`` (Function field, ``type = 'object'`` only):
     rented / vacant / under negotiation as of the ``occupancy_date``
     context key (defaults to today), read from ``BaseObjectOccupancy``.
     Added as a column to the object search's default list view
     (``base_object_list_simple.xml``, priority 10 — the one actually
     used for a Many2One's pick dialog, not the higher-priority-number
     ``base_object_tree.xml``) so that picking an object for a contract
     item shows its status as of *that item's own* ``valid_from``
     (``ContractItem.objects``' own ``context={'occupancy_date':
     Eval('valid_from')}``), not just today.
   - Meter readings (``MeterReading``) linked to equipment objects
   - ``billing_as`` / ``collective_billing`` flags to control how operating
     cost billing is aggregated at property level
   - ``next_billing_start_date`` (function field, property only): the
     earliest ``start_date`` among all non-``billed`` billing units of the
     property. Drives the *ready for billing* checks and the green
     line-color highlight in the billing unit list view.
   - Buttons ``compute_value_shares``, ``compute_settlement_result_property``,
     and ``ready_for_billing_property`` delegate bulk settlement actions to
     all billing units of the property that share ``next_billing_start_date``.
     ``billing_property`` opens the ``real_estate.billing_unit.wizard``
     instead of billing directly.
   - ``call_billing`` / ``do_billing`` (classmethods) run the actual billing
     for one or more properties, optionally in the background queue
     (``execute_in_queue``). ``do_billing`` requires every billing unit that
     would be billed to already be in state ``ready_for_billing``; with
     ``collective_billing`` all billing units sharing the same start date
     must be included together, otherwise a ``ValidationError`` is raised.
   - ``bved_provider_assignments`` (function-less One2Many, ``readonly=True``,
     visible only for ``type in ('property', 'building')``) shows the
     ``real_estate.bved.provider_assignment`` records anchored on this
     object. The *BVED Provider Assignments* notebook page itself stays
     hidden until at least one such assignment actually exists — it is a
     read-only overview, not a way to create or edit assignments; those are
     always maintained on the dedicated *BVED Provider-Liegenschaft*
     screen (``real_estate.bved.provider_assignment``, see below).

   *Rental object fields* (visible only for ``type = 'object'``):

   ``type_of_use``
      Economic use: ``residential``, ``commercial``, ``property``
      (owner-occupied), or ``internal``. Drives the contract-type filter.

   ``use_class``
      Many2One to ``real_estate.use_class``. Controls which additional
      fields (``basement_nr`` / ``parking_nr``) appear on the form.

   *Meter fields* (visible only for ``type = 'equipment'``, ``e_type = 'meters'``):

   ``meter_no_decimals``
      Boolean, default ``True``. When set, meter readings are validated and
      rounded to integer values. The estimate-consumption wizard and
      ``simulate_estimate`` respect this flag and round accordingly.

   Context classes for list views (``BaseObjectEquipmentContext``,
   ``BaseObjectOccupancyContext``, ``MeterReadingContext``) provide
   filterable search panels. Selection fields shared with the underlying
   model (e.g. ``e_type``, ``state``) are derived dynamically so their
   labels stay in sync automatically.

``real_estate.object_party.role``  (``object_party.py``)
   Configurable role definitions per object type
   (e.g. *Tenant* only for type ``object``, *Owner* for all types).

``real_estate.object_party``  (``object_party.py``)
   Links a ``party.party`` record to a ``BaseObject`` with a typed role
   and an optional validity period.

``real_estate.measurement.type``  (``measurement.py``)
   Named measurement type linked to a ``product.uom`` unit.

   Supports a **group hierarchy**: a type with ``is_group = True`` acts as
   a container grouping one or more child types via the ``parent`` Many2One
   field. Multi-level hierarchies are supported — groups can themselves have
   a parent group (e.g. *Gross Floor Area* → *Net Floor Area* → *Living Area*).

   Constraints enforced at save time:

   - All child types must share the same unit as their parent group.
   - Circular references (a group referencing one of its own descendants
     as parent) are rejected.
   - Only **leaf** (non-group) types can be assigned to individual
     ``real_estate.measurement`` records on ``BaseObject`` instances.

   When a group type is referenced in ``ContractTermType.m_type`` or in
   ``SettlementUnit.m_type``, the system automatically expands the group to
   all descendant leaf type IDs at query time, so measurements of any child
   type are included in the calculation.

   ``get_effective_ids(m_type)``
      Classmethod resolving `m_type` to the flat list of leaf type ids to
      search: itself if not a group, else all descendant leaf ids
      (recursively, for nested groups).

``real_estate.measurement``  (``measurement.py``)
   Associates a numeric value and measurement type with a ``BaseObject``
   for a given validity period.

   ``get_total_value(base_object_id, m_type, as_of_date=None)``
      The single, hierarchy-aware entry point for "the value of `m_type`
      on `base_object_id` as of `as_of_date`" — every computation in the
      module that needs a measurement value (as opposed to just listing
      raw rows for display) goes through this classmethod rather than
      querying ``real_estate.measurement`` directly. Resolves `m_type` via
      ``MeasurementType.get_effective_ids()`` and, for **each** effective
      leaf id independently, looks up the object's own latest row with
      ``valid_from <= as_of_date`` (or the single latest row ever, if
      `as_of_date` is ``None``) — then **sums** whatever was found. This
      matters for a "Summenbemessung" (group type) where a single object
      carries values under **several sibling leaf types** at once (e.g. a
      mixed-use object with both a residential and a commercial area
      entry): the object contributes all of them, not just whichever
      happens to be the most recently dated row. Returns ``None`` if
      `m_type` is falsy, resolves to no effective ids, or none of them has
      any matching row at all (true "not recorded", as opposed to a
      recorded value of zero) — callers use this to distinguish "no data"
      from a real zero. Used by ``real_estate.bved.provider_assignment``
      (L-Satz *Gesamtfläche*), ``BillingUnit.on_change_with_co2_total_area``,
      ``SettlementUnit.compute_value_shares`` (``allocation_by_measurement``),
      ``ContractTerm._sum_measurements``, and
      ``OptionRate._measurement_value`` (dynamic option-rate weighting).

   ``company`` / ``property`` (Function fields)
      Display/search-only, derived from ``base_object`` — ``company`` is
      simply ``base_object.company``; ``property`` is ``base_object``
      itself if its own ``type = 'property'``, else ``base_object.property``
      (the stored ancestor-property reference every ``base_object`` already
      carries). Used by the *Measurements* list below to show and filter
      by company/Wirtschaftseinheit without a join in the view itself.
      ``search_property`` matches either a row whose own ``property``
      field equals the given value, or a property-type row whose own
      ``id`` does (so filtering by a given property also finds that
      property's own direct measurements, not just its descendants').

   *Measurements* list (``act_measurement_tree`` in ``measurement.xml``)
      Menu *Master Data*, between *Rental Object* and *Equipment*. A
      plain, filterable browse list over ``real_estate.measurement``
      (columns: Company, Property, Object, From, Measurement Type, Value
      — summed — , Symbol), **not** a wizard and **not** hierarchy-aware
      the way ``get_total_value()`` is — it lists raw rows matching a
      simple filter, with no de-duplication to "the one currently
      effective row per (object, type)". The filter panel
      (``real_estate.measurement.context``, via the action's
      ``context_model``/``context_domain`` — same mechanism as
      ``real_estate.meter_reading.context`` above) offers:

      - ``company`` (required) — restricts to ``base_object.company``.
      - ``property`` — restricts the ``base_object`` picklist to that
        property's own subtree (via ``child_of``) and, if ``base_object``
        itself is left empty, restricts the list the same way.
      - ``base_object`` — if set, takes precedence over ``property`` and
        restricts the list to this object and **all** of its descendants
        (``('base_object', 'child_of', [base_object], 'parent')`` —
        inclusive of the object itself).
      - ``m_type`` — exact match, if set.
      - ``date`` ("Stichtag", required, default today) — a plain
        ``valid_from <= date`` filter; deliberately **not** the
        latest-row-per-group logic of ``get_total_value()`` — every row
        satisfying the date cutoff is shown (and contributes to the
        summed Value column), including any historical rows later
        superseded by a newer ``valid_from`` on the same object/type.

``real_estate.meter_reading``  (``base_object.py``)
   Meter reading record linked to an equipment object of type ``meters``.

   Key fields: ``company`` (stored, auto-filled from ``base_object`` on change),
   ``base_object``, ``meter_id``, ``reading_date``, ``m_type``
   (``initial`` / ``reading`` / ``estimate`` / ``final``),
   ``value``, ``unit`` (derived from the meter's ``meter_unit``),
   ``consumption`` (difference to previous reading for counter meters),
   ``comment`` (free text).

   Browseable via the *Meter Readings* menu entry under *Master Data*,
   filterable by company, property, parent object, equipment (meters only),
   and date range (``from_date`` / ``to_date``).

``real_estate.meter_reading.sheet``  (``meter_reading_sheet.py``)
   Meter reading sheet (*Zählerableseliste*) for the collective entry of
   meter readings, menu *Master Data › Meter Reading Sheets* and relate
   *Meter Reading Sheets* on an object (sheets of the object and below).

   Header: ``base_object`` (property, building or rental unit; the
   ``property`` is derived), ``reading_date``, optional selection of the
   meters by ``equipment_kind`` and ``name_filter`` (``ilike``, e.g.
   *Warmwasser*), ``reader`` (reading user of the readings created),
   ``progress`` (*entered / meters*), state *Draft / Done / Cancelled*.

   Lines (``real_estate.meter_reading.sheet.line``), one per meter, in an
   editable list: rental unit and main tenant on the reading date (via the
   occupancy), meter, meter ID, previous reading (date and value, last
   reading before the reading date), **new value**, unit, consumption
   (counters), remarks, link to the meter reading created.

   Buttons:

   - *Load Meters* (also on create, e.g. a new sheet, a copy or a
     follow-up sheet): adds the meters below the object not yet listed
     (not deactivated, filtered) and refreshes unit, tenant and previous
     reading; values entered are kept.
   - *Complete*: confirmable warning for meters without value; creates
     one meter reading (``m_type='reading'``) per line with value - an
     existing reading of the meter on the reading date is linked instead
     (as in the handover report). The validation of the meter reading
     applies (same meter ID, counter value not lower).
   - *Reset to Draft*: deletes the meter readings created by the sheet
     (``reading_created``), linked ones are kept; completing again creates
     them anew.
   - *Follow-up Sheet* (done): new sheet with the same object and filter,
     reading date + 1 year, lines loaded with this reading as previous
     value, opened at once.

   A done sheet cannot be deleted. The sheet can be the reference of tasks
   and processes. Reminder: task rule O01 *Record meter readings* (done as
   soon as every meter has a reading, e.g. by completing the sheet).
   Print: *Meter Reading Sheet* (see :doc:`reports`).

   **Consumption estimate** (``simulate_estimate`` / ``create_estimate``):

   ``simulate_estimate(base_object, per_date, meter_id=None)``
      Returns ``(estimated_value, consumption, r1, r2)``.
      Prefers **interpolation** when readings exist both before and after
      ``per_date``: takes the closest reading on each side and interpolates
      linearly between them.
      Falls back to **extrapolation** using the last two readings within
      one year before ``per_date`` when no future reading is available.
      Rounds the result to the meter's UOM digit precision; if
      ``meter_no_decimals`` is set on the meter, rounds to integers.

   ``create_estimate(base_object, per_date, reason, meter_id=None)``
      Calls ``simulate_estimate`` and saves a new reading with
      ``m_type = 'estimate'``.
