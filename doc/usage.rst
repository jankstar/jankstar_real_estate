*****
Usage
*****

This page describes the end-to-end workflow for the ``real_estate`` module,
from setting up a property to running the annual operating cost settlement.
All steps assume the configuration described in :doc:`configuration` has
been completed.


Step 1 — Create a Property
===========================

Navigate to *Real Estate → Properties*.

1. Click **New** and set **Type** to *Property*.
2. Fill in **Name**, **Company**, **Start date**, and optionally assign an
   **Address** (select from *Real Estate → Master Data → Addresses*).
3. Set **Type of use** (e.g. *Residential*) — this filters which contract
   types are available later.
4. Optionally set **Billing as** and **Collective billing** to control how
   operating cost billing is aggregated across buildings.
5. Click **Active** to transition the property from *Draft* to *Active*
   (button on the form toolbar).

Under the property you can then create the sub-objects of the tree:

.. list-table::
   :header-rows: 1
   :widths: 20 30 50

   * - Type
     - Parent
     - Typical use
   * - Building
     - Property
     - Multi-unit residential or commercial building
   * - Land
     - Property
     - Plot without building (e.g. parking lot)
   * - Object
     - Building or Land
     - Rental unit: apartment, retail space, parking space
   * - Equipment
     - Building, Land, Object, or Equipment
     - Meters (water, heat), technical installations

For each **Object** set the **Use class** (Apartment, Retail, Parking, …)
and optionally enter the **Object number** (shown on invoices and reports).

For each **Equipment** of e_type *Meters* set:

- **Meter unit** — the UOM of the readings (e.g. m³)
- **Meter factor** — conversion factor (usually 1.0)
- **No decimals** — tick if readings must be integer values
- **Meter ID** — identifier printed on the physical meter

Activate each object with the **Active** button after completing it.


Step 2 — Enter Measurements
============================

Measurements record the physical size of an object for a given date.
They are used as the allocation base for operating cost settlement
(e.g. living area in m²) and as the default quantity on contract terms.

Navigate to the object's form and open the **Measurements** tab, or use
*Real Estate → Master Data → Measurements*.

For each rental object enter at least:

- **Living Space** (m²) — used by *Apartment rent* and *Operating costs*
  term types as default quantity
- **Number of rooms** — optional, for reports

For commercial objects enter:

- **Commercial Space** (m²) — used by *Commercial rent* term types

For buildings:

- **Gross floor area** (m²) — used in billing unit reports

The **Valid from** date determines from when the measurement applies.
Multiple measurements of the same type can coexist if the area changes
over time; the system always uses the latest measurement valid on or
before the reference date.


Step 3 — Assign Partners and Roles
====================================

Open the **Parties** tab on any property or object to assign
``party.party`` records with a role (e.g. Owner, Administrator).

For owners this is informational; for tenants the party is entered
directly on the contract (Step 4).


Step 4 — Create Contracts
==========================

Navigate to *Real Estate → Contracts*.

1. Click **New** and set:

   - **Contract type** — e.g. *Rental agreement* (residential)
   - **Property** — the parent property
   - **Contractual partner** — the tenant (``party.party``)
   - **Invoice address** — the partner's delivery/invoice address
   - **Start date** — first day of the tenancy
   - **Currency** — filled automatically from the company

2. On the **Items** tab, click **New** to add a ``ContractItem``:

   - **Valid from** — typically the contract start date
   - Add one or more rental objects in the **Objects** sub-table.
     The object selector is restricted to objects of type *object*
     that belong to the same property as the contract.

3. On the **Terms** tab, click **New** to add each charge
   (``ContractTerm``):

   - **Term type** — e.g. *Apartment rent (monthly)*
   - **Reference item** — the contract item this term refers to
   - **Valid from** — start of the charge period
   - **Rhythm** / **Rhythm type** — billing frequency (e.g. 1 × monthly)
   - **Quantity** — auto-filled from the measurement type linked to the
     term type (can be overridden)
   - **Unit price** — amount per unit per period
   - **Taxes** — pre-filled from the contract type defaults

   Typical term sequence for a residential contract:

   ====  ================================  ==================
   Seq.  Term type                         Note
   ====  ================================  ==================
   10    Apartment rent (monthly)          Net rent
   20    AP for Operating costs (monthly)  Cold costs advance
   30    AP for Heating costs (monthly)    Heating advance
   ====  ================================  ==================

4. Click **Running** to activate the contract.
   The state changes from *Draft* → *Running*.

Terminating a contract
----------------------

Click **Terminate** on a running contract.  The wizard asks for:

- **Terminated by** — tenant or landlord
- **Receipt of termination notice** — date the notice was received
- **Termination reason** — free text
- **Termination date** — last day of the tenancy (calculated from the
  notice period or entered manually)

The contract moves to *Terminated*.  Occupancy records are updated
automatically; the object becomes available for a new contract.

Cancelling a contract
----------------------

The **Cancel** button is available on *Draft* contracts.  If cash flow
entries in state *done* (already invoiced) exist, a warning is shown:
existing postings will **not** be reversed automatically.  Draft cash flow
entries are deleted automatically on cancellation.


Step 5 — Generate Invoices (CreateContractMoves)
=================================================

Navigate to *Real Estate → Create Contract Moves* or click the
**Create Moves** button on a contract.

The wizard offers three actions:

``Create``
   Generate invoices up to a given cut-off date.  For each contract term
   with pending future cash flow entries up to the date, one invoice line
   is created and the cash flow entry transitions to *done*.

``Re-calc``
   Rebuild the cash flow projection without creating invoices.  Useful
   after changing a term's rhythm, unit price, or validity dates.

``Re-calc and Create``
   Rebuild first, then create invoices in one step.

You can filter by **Property** and/or **Contract** to limit the run to
a subset of contracts.

After the wizard completes, the generated invoices appear under
*Accounting → Invoices* and can be posted and sent from there.

The **Cash Flow** tabs on the contract form show:

- **Draft** — planned entries not yet invoiced
- **Pending** — posted (open) invoices
- **Paid** — settled invoices


Step 6 — Meter Readings
========================

Navigate to *Real Estate → Master Data → Meter Readings*, or open the
**Meters** tab on an equipment object.

Reading types:

``initial``
   First reading when the meter is commissioned (or a new tenant moves in).
   Must be the first reading for a given meter.

``reading``
   Periodic reading.  The meter ID must match the previous reading.
   For counter meters, the **Consumption** is computed automatically
   (current value minus previous value).

``estimate``
   Created by the **Estimate Consumption** wizard on the equipment form.
   The wizard interpolates between surrounding readings or extrapolates
   from the last two readings within one year.

``final``
   Last reading when a meter is decommissioned or replaced.

The **Meter ID** groups readings that belong to the same physical meter.
When a meter is replaced, a new initial reading with a different Meter ID
starts a new series.


Step 7 — Operating Cost Settlement (Billing Unit)
==================================================

The annual settlement is managed through *Billing Units*.
Navigate to *Real Estate → Operation Costs → Billing Units*.

7.1 Create a Billing Unit
--------------------------

1. Click **New** and set:

   - **Property** — the property to settle
   - **Start date** — first day of the settlement period (e.g. 01.01.2025)
   - **End date** — last day (e.g. 31.12.2025); leave blank for open-ended
   - **Calculation method** — *Rental apartment* (§§ 1–2 BetrKV) or
     *WEG billing* (condominium law)
   - **Description** — e.g. "Kalte Betriebskosten 2025"
   - **Term types of use** — which contract term types count as advance
     payments (e.g. *AP for Operating costs*)

2. Click **Approved** to activate the billing unit.

7.2 Add Settlement Units
-------------------------

Under the **Settlement Units** tab, add one row per cost type:

- **Cost type** — e.g. *Grundsteuer* (seq. 100)
- **Allocation rule**:

  ``allocation_by_measurement``
     Allocated proportionally to a measurement value (e.g. living area).
     Set **Measurement type** — e.g. *Usable Space* (group, expands to
     Living Space + Commercial Space automatically).

  ``allocation_by_consumption``
     Allocated by meter reading consumption (e.g. water m³).
     Set **Meter unit** and **Meter regex** to filter the relevant meters.

  ``allocation_per_rental_unit``
     Allocated proportionally to occupancy duration.

  ``allocation_from_external_billing``
     No allocation calculation; amounts are entered manually from an
     external bill (e.g. heat cost allocator result).

  ``no_allocation``
     Entire cost stays unallocated (e.g. maintenance reserve).

- **Object regex** — regular expression to filter which rental objects
  are included (e.g. ``Wohnung|Einzelhandel``).
- **Vacancy** — how to handle unoccupied periods:
  *by_owner* (costs go to the owner) or *unallocated*.

7.3 Run Selection
------------------

Click **Selection** to identify which contracts and objects fall within
the settlement period.  The system creates ``CostShare`` records for every
object × settlement unit combination.

Selection can be re-run from the *Value Share* state to revise the scope;
existing settlement results are deleted after confirmation.

7.4 Compute Value Shares
-------------------------

Click **Compute Value Shares** to calculate the allocation factor for each
cost share:

- Measurement-based: ``value_share = measurement × time_share / time_total``
- Consumption-based: ``value_share = consumption``
- Per rental unit: ``value_share = time_share / time_total``

Cost shares that cannot be computed (e.g. missing meter reading) are set
to state *error* with an explanatory message.  Fix the underlying data and
click **Compute Value Shares** again — error shares are automatically reset
before the recalculation.

7.5 Compute Settlement Result
------------------------------

Click **Compute Settlement Result** to aggregate cost shares per contract
and produce one ``SettlementResult`` per contract:

- **Planned costs** — budgeted amount (from cost share)
- **Actual costs** — real costs entered or allocated
- **Advanced payment** — sum of *posted* and *paid* invoice lines for the
  term types of use during the settlement period
- **Refund / receivable** = actual costs − advanced payment
  (positive = refund to tenant, negative = additional charge)

If any cash flow entries in the settlement period are still in state
*draft* or *validated* (not yet posted), the affected cost share is
marked *error* with a ``[draft]`` prefix.  Post or delete those invoice
drafts and re-run.

7.6 Billing
-----------

Click **Billing** to create invoices and credit notes from the settlement
results.  For each contract with a settlement result the system creates:

- A credit note line reversing the advance payments booked during the year
- An invoice line for the actual costs allocated to the contract
- Optionally a journal entry for the owner allocation (WEG billing)

All postings of one billing run share a ``billing_run_id``
(``YYYYMMDD-HHMMSS-U<userid>``) for traceability.

If the property has **Collective billing** enabled, the *Billing* button
is not shown on individual billing units; instead use the
**Billing Property** button on the property form to trigger all billing
units at once.


Typical Annual Workflow Summary
================================

.. list-table::
   :header-rows: 1
   :widths: 5 30 30

   * - #
     - Action
     - Where
   * - 1
     - Create / update properties and objects
     - *Real Estate → Properties*
   * - 2
     - Enter measurements (area, rooms)
     - Object form → Measurements tab
   * - 3
     - Enter meter readings (initial, periodic)
     - *Real Estate → Master Data → Meter Readings*
   * - 4
     - Create / update contracts and terms
     - *Real Estate → Contracts*
   * - 5
     - Generate invoices monthly (CreateContractMoves)
     - *Real Estate → Create Contract Moves*
   * - 6
     - Post invoices in accounting
     - *Accounting → Invoices*
   * - 7
     - Create billing unit for the settlement year
     - *Real Estate → Operation Costs → Billing Units*
   * - 8
     - Add settlement units (cost types + allocation rules)
     - Billing unit form → Settlement Units tab
   * - 9
     - Run Selection → Compute Value Shares
     - Billing unit form (buttons)
   * - 10
     - Enter actual costs on settlement units
     - Settlement unit form
   * - 11
     - Compute Settlement Result
     - Billing unit form (button)
   * - 12
     - Run Billing → post invoices / credit notes
     - Billing unit form → button / property form
