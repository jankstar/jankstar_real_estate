.. _rent-adjustment-modernisation:

*************
Modernisation
*************

Part of `Rent Adjustments <rent_adjustment.rst>`__ (common header,
adjustment run, term adjustments). Procedure ``modernisation``
(*Mieterhöhung nach Modernisierung*, §§ 555b-555f, 559-559e BGB): after a
modernisation the landlord may increase the annual rent by a share of the
costs. Unlike the index and the comparative rent the starting point is
not a single term but a **measure** on buildings of a property whose
costs are allocated to several rental units. The procedure has two
phases with their own correspondence:

.. code-block:: text

   Phase 1  Modernisation (measure) ─► announcement (§ 555c) ─► work
   Phase 2  Adjustment run 'modernisation' ─► increase declaration (§ 559b)
            ─► split of the rent term

**Implementation status:** all phases are available - the measure with
costs, funds, rental units, allocation preview, announcement and
deadlines (M1), the procedure in the adjustment run with the increase
declaration and the execution (M2), the processes and deadline tasks (M3)
and the planning calculation with planned rent survey features (M4). Commercial leases are out of scope - there the contract
alone applies (optionally with a free adjustment).

Customizing
===========

``real_estate.modernisation.rule``  (``modernisation.py``)
   Legal values valid from a date (menu *Configuration › Modernisation
   Rules*, writable for *Real Estate Administration* only): rate 8 % and
   heating rate 10 %, limit of the simplified procedure 10,000 € per
   apartment with its maintenance flat rate 30 % and lock of 5 years,
   heating maintenance flat rate 15 %, cap 3.00 €/m² (2.00 €/m² below a
   rent of 7.00 €/m²) within 6 years, heating cap 0.50 €/m²,
   announcement period 3 months, extension 6 months / tolerance 10 %, and
   the *Cap Measurement* giving the area for the cap per m² and the
   increase per m² in the letter (standard data: living space - required
   for *Announce*, check M02). The module ships the values as of
   01.01.2024; in an existing database the cap measurement has to be set
   once in the rule. The rule valid on the
   announcement date (else the planned start) applies.

The procedure must be allowed on the contract type and on the term type
of the rent term (``adjustment_procedures`` contains ``modernisation``);
only such a term becomes the *rent term* of a rental unit.

Measure
=======

Menu *Contracts › Rent Adjustments › Modernisations* (tabs *Planning*,
*In Progress*, *Completed*, *Settled*, *All*; selection of company and
property in the context).

``real_estate.modernisation``
   Number (sequence ``MOD-<year>-``), name, company, property and the
   buildings concerned (empty = all buildings of the property). Measure
   types according to § 555b BGB (nos. 1, 1a, 2, 3, 4, 4a, 5, 6, 7 - nos.
   2 and 7 alone do not allow an increase), variant *Standard (§ 559,
   8 %)*, *Simplified (§ 559c)* or *Heating system (§ 559e, 10 %)*,
   description and energy saving (flat values allowed), planned start and
   duration, actual start and end, expected costs and expected operating
   costs. Flags:

   - *Trivial measure* (§ 555c para. 4 BGB, reason required) and
     *Vacancy* (vacant apartments, no tenant): no announcement - the work
     starts directly; a vacancy measure is *settled* on completion, its
     amount per apartment is the basis for the next letting.
   - *Comprehensive modernisation* (§ 556f sentence 2 BGB, reason
     required) and *Not attributable to landlord* (§ 555b no. 6 BGB).
   - *Heat pump SPF proven* for the heating variant.

   Allocation key *Equal Shares*, *Measurement* (default) or *Manual* -
   no area is fixed in the program. With *Measurement* a measurement type
   is chosen (proposal: the cap measurement of the rule, e.g. living
   space; or e.g. number of windows) and the quantities of the units are
   taken from their measurements (on saving a changed key or measurement
   type and by *Determine Rental Units*); with *Manual* the quantity is
   entered per unit and the *Allocation Note* explaining it is required.
   The share is quantity / total of the participating units (check M10: a
   quantity is missing - 0 is allowed).

``real_estate.modernisation.cost``
   Costs **per trade or service** (facade, windows, heating …), not per
   invoice: kind *Planned* / *Actual*, optional supplier invoice line
   (net amount and tax are taken over), net amount, tax and tax amount,
   gross amount, measure type, maintenance share (*None*, *Percent*,
   *Amount (net)* - only for the standard variant; flat rates otherwise)
   and an optional rental unit (costs of one unit only, e.g. a balcony).
   The invoice line shows the measure in the function field
   ``modernisation`` (searchable).

``real_estate.modernisation.fund``
   Third-party funds (§ 559a BGB): *Grant* and *Third-Party Payment*
   reduce the costs, the annual *Interest Advantage of a Loan* reduces the
   annual amount; optionally for one rental unit.

``real_estate.modernisation.unit``
   Rental unit of the measure, filled by the button *Determine Rental
   Units* (re-running it updates contract, term and quantity and keeps
   manual settings): object, contract (from the occupancy), rent term.

   - *In Allocation* (default yes): excluding a unit needs a reason and
     increases the share of the others; a vacant unit always takes part -
     its share is borne by the landlord (check M09).
   - *Input Tax Deductible*: proposed when a current term of the contract
     carries VAT (option § 9 UStG) - the costs of the unit are then taken
     net, otherwise gross.
   - *No Increase* with a reason (vacancy, commercial, no term with the
     procedure, graduated/index rent, hardship accepted, termination,
     waiver, other): the unit stays in the allocation but gets no
     increase and no letter. Vacancies and commercial units are flagged
     automatically.
   - *Allocation Quantity* for the keys *Measurement* and *Manual* - a
     unit entered by hand gets the quantity of the allocation measurement
     proposed (on choosing the object and on saving without quantity).
   - Share, allocable costs, current rent, *Expected Increase* (monthly,
     after the cap) and *Capped* are computed from the current costs;
     *Announced Increase* is frozen by *Announce*.
   - Announcement: document, receipt date (for all units with a contract
     and an increase at once with the button *Capture Receipts* of the
     measure, states announced / in progress; deviations per unit), *Announcement Defective* with
     the defect, *Hardship Notice Missing*; deadlines *Hardship Objection
     until* and *Special Termination until* (end of the month following
     the receipt; no hardship deadline when the notice was missing),
     hardship objection with date, note and decision, *Terminated*.

Calculation
-----------

The allocation is computed by the pure functions ``allocation_shares()``
and ``compute_allocation()`` of ``modernisation.py``:

1. Share per participating unit by the key (equal, or quantity / total
   quantity); costs and funds assigned to a unit go to that unit
   only.
2. Cost basis per unit net or gross (input tax deduction); a maintenance
   amount (entered net) is scaled to gross with the tax ratio of the
   cost line.
3. Allocable costs = costs − maintenance share (percent, amount or flat
   rate 30 % / 15 %) − grants and third-party payments.
4. Annual amount = allocable costs × rate (8 % / 10 %) − interest
   advantage; monthly amount = annual amount / 12, rounded half up.
5. Cap: area × 3.00 €/m² (2.00 €/m² if the rent before was below
   7.00 €/m²), heating variant additionally area × 0.50 €/m²; the area
   is the value of the *Cap Measurement* of the rule on the reference
   date (without it no cap). Previous
   increases within 6 years are taken into account by the adjustment run
   (next phase).

Example: building with 420 m², costs 180,000 €, maintenance 25 %, grant
15,000 € → allocable 120,000 €; apartment with 64.20 m² → 18,342.86 € ×
8 % = 1,467.43 € p. a. = **122.29 € per month**.

Workflow
========

.. code-block:: text

   Planning ─Take Over Planning─► Draft ─Announce─► Announced ─Start Work─► In Progress
                                     │                                       │
                                     └── Start Work (vacancy / trivial) ─────┘
   In Progress ─Complete─► Completed ─(adjustment run)─► Settled
                               └── vacancy: settled at once
   Cancel: from Planning up to Completed

   *Settled*: once the adjustment run of the measure is done (all its
   adjustments executed, refused or cancelled).

   *Completed* means the work is finished (German *Fertiggestellt*,
   button *Fertigstellen*); the rent increase follows in the adjustment
   run, the measure ends with *Settled*. In the state *Completed* without
   an adjustment run (not for a vacancy) the button *Create Adjustment
   Run* creates the run of the procedure Modernisation for the measure
   (company, property, the measure as parameter, key and declaration date
   today - at the earliest the completion) and opens it in its form for
   the selection. The header of the measure shows the latest adjustment
   run not cancelled (*Adjustment Run*).

*Announce* checks the measure and creates the letters:

======  ==============================================================
Check   Meaning
======  ==============================================================
M01     At least one measure type allowing an increase (error)
M02     Description, planned start and duration, expected costs and
        operating costs are filled (error)
M03     Planned start at least 3 months after the announcement (error)
M04     Heating variant requires measure type 1a (error)
M05     Simplified variant: costs per unit above the limit (warning)
M06     *Start Work*: start less than 3 months after the receipt of the
        announcement at a unit with an increase (warning)
M07     *Complete*: costs present; standard variant: maintenance share
        chosen on every cost line (error)
M08     From *Completed* on: input tax of the units with deduction
        compared with the option rate of the property - hint in the tab
        *Check Messages*, computed on reading with the current costs
        (*No messages.* without a deviation; before the completion an
        information; consult a tax advisor, § 15a UStG)
M09     Saving a unit: exclusion from the allocation needs a reason,
        a vacancy always takes part (error)
M10     *Announce* / *Complete*: allocation by measurement or manual -
        a participating unit has no quantity (error)
======  ==============================================================

Announcement letter
-------------------

Report *Modernisation Announcement (de)*
(``report/modernisation_announcement_de.odt``, model
``real_estate.modernisation.unit``): one letter per rental unit with an
increase, to all main tenants of the contract - kind and scope with the
measure types, energy saving, start and duration, expected increase per
month and per m², future operating costs, hardship objection with form
and deadline (§ 555d BGB) and the special termination right (§ 555e
BGB). *Announce* archives the original at the rental unit (field
*Announcement (Document)*) and at the contract; later prints via *Print*
on the rental units. Each letter starts on a new page with its own page
numbering. Before the announcement the button *Sample Letter* (state
planning/draft) shows the letter of the first rental unit with a
contract and an increase, marked *ENTWURF*, without archiving it; a print
via *Print* on a single rental unit is marked the same way.

Adjustment run
==============

Procedure ``modernisation`` of the adjustment run (``contract_modernisation.py``,
class ``ModernisationProcedure``). The run gets the parameter
*Modernisations* (completed measures of the company; the column
*Modernisation* is a link that opens the measure in its own tab); the
filters *Properties* and *Contracts* restrict the rental units further.

Selection
   One adjustment per rental unit of the measures: units with *No
   Increase* (vacancy, commercial, hardship, ...), without contract or rent
   term, with an adjustment of the unit already (not cancelled/refused) or
   whose contract type, term type or use class does not allow the
   procedure are excluded with a reason in the protocol (D-M1). The
   adjustment refers to the current term of the chain of the unit's rent
   term; the rent adjustment ``modernisation`` per term chain (technical
   bracket, state active) is created by the selection.

Computation (``_modernisation_compute``)
   - Rent before the increase: the amount of the current rent term.
   - Allocation of the measure (``Modernisation.allocation()``) with the
     rent before and the **previous increases** of the apartment: executed
     modernisation adjustments of all contracts of the object within the
     cap period (6 years) before the effective date
     (``previous_increases()``); heating increases separately for the
     heating cap. The costs count the actual cost lines once there is
     one, else the planned ones.
   - New rent = rent before + increase after the cap; unit price =
     new rent / quantity of the term.
   - **Effective date** (``modernisation_valid_from()``): start of the third
     month after the receipt of the declaration (before the receipt: the
     declaration date + receipt days of the real estate accounting),
     6 months later (``extension_reason()``) if the measure was not
     announced or the receipt of the announcement is missing (not for a
     trivial measure), the unit is flagged *Announcement Defective*, or the
     increase exceeds the announced increase by more than 10 %.
   - Values on the adjustment (tab *Modernisation*): costs of the unit,
     allocable costs, annual amount, monthly amount before the cap, area
     of the cap measurement, previous increases, allowed by the cap,
     extension and the calculation text.

======  ==============================================================
Check   Meaning
======  ==============================================================
E01     Running residential contract on the effective date (error)
E02     No running graduated rent - locked or future steps (error)
E03     Active index rent: only for circumstances not attributable to
        the landlord, never § 559e (error)
E04     Hardship objection not decided or accepted (error; not for the
        simplified procedure)
E05     Cap applied (hint)
E06     Simplified procedure: costs of the unit plus costs claimed
        within 5 years above the limit (error)
E07     Effective date postponed by 6 months (warning)
E08     Heating system: no grant (error); heat pump SPF not proven
        (hint, 50 % rule to check manually)
E09     Lock by a simplified increase within 5 years (error)
E10     No area of the cap measurement (error)
E11     Tenant terminated after the announcement (§ 555e, error)
E12     Declaration before the completion of the measure (error)
E13     No increase (error)
E14     Periods already booked from the effective date (warning)
======  ==============================================================

Declaration, receipt, execution
   *Announce* of the run creates the **increase declaration** (report
   *Modernisation Increase Declaration (de)*,
   ``report/modernisation_increase_de.odt``, model
   ``real_estate.contract.term.adjustment``): reference to the
   announcement, the measure, costs per trade on the basis of the unit
   (gross/net) with maintenance share, third-party funds, allocation key,
   share of the apartment, allocable costs, rate, annual and monthly
   amount, rent before, increase, new rent, effective date, cap and
   extension if applicable, and the special termination right (§ 561
   BGB). The original is archived at the adjustment and the contract;
   *Print Letters* of the run prints all letters still to send. Before
   the announcement *Sample Letter* of the run shows one declaration
   marked *ENTWURF* (nothing archived).

   The receipt is captured in the run (tab *Receipts*); the adjustment
   shows *Special Termination until* (end of the second month after the
   receipt) and the flag *Terminated (§ 561)* - such an adjustment is not
   executed (cancel it). *Execute* splits the rent term from the
   effective date with the new unit price (in the background, like the
   other procedures), writes the contract log ``modernisation`` and, once
   the run is done, sets the measures of the run to *Settled*.

   The rental unit of the measure shows its adjustment and its state
   (columns *Increase (Adjustment)*, *Increase State*).

New letting (§ 556e para. 2 BGB)
   The wizard *Check Comparative Rent (New Letting)* raises the limit in a
   tight housing market by the modernisation amount of the apartment
   (column *Modernisation*): the increase per month of the measures
   completed within the 3 years before the contract start
   (``Modernisation.new_letting_amount()``), also for measures in a
   vacancy. The first letting after a **comprehensive modernisation**
   (flag on the measure, completed before the contract start, no other
   contract of the apartment started since) has no limit of the rent
   brake (§ 556f sentence 2 BGB, ``comprehensive_first_letting()``) - the
   line shows the result without limit, the information text the measure.

Processes and tasks
===================

Process *Modernisation* (template code ``modernisation``, model
``real_estate.modernisation``) - started automatically when a measure is
created (tab *Workflow* on the measure; for older measures with *Start
Process*). The steps are done by the state of the measure (*By
Condition*, named methods ``modernisation_*`` of ``real_estate.process``):

==  ==============================================  =====================================
No  Step                                            Done by / created when
==  ==============================================  =====================================
10  Plan and calculate (optional)                   state draft reached
20  Determine the rental units                      rental units exist
30  Announce the measure                            state announced; not for vacancy or
                                                    trivial measures
40  Capture the receipts of the announcement        receipt at every unit with increase
50  Handle hardship objections and special          periods of all units ended, no
    terminations                                    objection undecided
60  Start the work                                  state in progress
70  Complete the work and determine the costs       state completed
80  Start the adjustment run (action: runs)         measure settled; not for a vacancy
90  Update the rent survey features (manual,        created once completed, only with a
    result required)                                rent survey of the property
==  ==============================================  =====================================

Process *Modernisation Adjustment Run* (``adjustment_run_modernisation``):
select, calculate, approve, send the declarations, capture the receipts,
execute - completed by the state of the run.

Deadline tasks (see `Tasks <tasks.rst>`__): ``modernisation_objection``
per unit, ``modernisation_start``, ``modernisation_declaration`` on the
measure and ``modernisation_termination`` (§ 561 BGB) on the adjustment.

Vacancy process: the optional step *Plan a modernisation* (sequence 25)
executes the wizard *Plan Modernisation (Vacancy)*
(``real_estate.modernisation.plan_vacancy``): it creates a measure
*vacancy* in the state planning for the rental unit (allocation quantity
from the measurement, no increase - vacancy) or opens an open one of the
unit; executing the action completes the step.

Planning calculation
====================

Tab *Calculation* of the measure (states *Planning* and *Draft*).

``real_estate.modernisation.planned_value``  (*Planned Features*)
   Classes, features and measurements of the rent survey after the
   modernisation, per object of the measure: the buildings of the
   measure (all buildings of the property if none is chosen) and their
   rental units (``planning_objects``). Kind *Feature* / *Class* (chosen
   from the version of the rent survey of the property valid today -
   features of the level of the object, classes of classification
   features of the level or a higher one, checked on saving; stored as
   codes) with the action *Add* / *Remove* - a planned class
   replaces the class of its classification feature -, or kind
   *Measurement* with a measurement type and the planned value (e.g. the
   energy consumption value after the modernisation).

*Calculate* (``real_estate.modernisation.calculation``, lines created
again on every calculation, nothing else is stored) - per rental unit:

- costs of the unit, allocable costs, current rent, **increase after
  § 559** (with the cap and the previous increases of the last 6 years)
  and the rent after § 559;
- **comparative rent before and after** (per m² and per month): the
  calculation of the rent survey on today without storing it, the second
  time with the planned features ("what if" - ``rent_survey.PLANNED`` /
  ``planned_values()``, applied by ``apply_planned()`` to the
  assignments and measurements of the calculation);
- **rent after § 558** after the modernisation: comparative rent after,
  limited by the cap of the rent term chain (rent 3 years before + 20 % /
  15 %, increases after §§ 559, 560 not counted), not below the current
  rent; *§ 558 from*: waiting period 15 months since the last change, at
  the earliest a request today;
- **new letting limit**: tight housing market 110 % of the comparative
  rent after, at least 110 % of the comparative rent before + the
  increase after § 559 (§ 556e para. 2 BGB); otherwise 120 % (§ 5 WiStG);
  none after a comprehensive modernisation (§ 556f BGB);
- a message when a participating unit has no allocation quantity
  (measurement or manual key - the unit gets no share of the costs);
- additional rent p. a. after § 559 and § 558 and the yield (additional
  rent p. a. / costs of the unit) - the basis of the decision between the
  cost allocation (§ 559) and a later comparative rent in the modernised
  state (§ 558).

*Apply Planned Features* (states *Completed* / *Settled*, once - the date
is shown in *Planned Features Applied*) stores the planned values at the
objects valid from the completion: classes and features as rent survey
values (a removed or replaced assignment ends the day before, resp. is
deleted if it starts on the date - as *Assign Rent Survey Features*;
evidence "Planned feature of the modernisation ..."), measurements as new
measurement rows from the completion. This supports the process step
*Update the rent survey features*.
