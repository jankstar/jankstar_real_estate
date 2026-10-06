.. _rent-adjustment-index:

****************
Rent Adjustments
****************

Overview
========

A rent adjustment (*Mietanpassung*) changes exactly one contract term by
one procedure (``contract_type.ADJUSTMENT_PROCEDURES``):

- **Graduated rent** (*Staffelmiete*, § 557a BGB): all steps are generated
  in advance as terms.
- **Index rent** (*Indexmiete*, § 557b BGB): agreement on a price index;
  the adjustment run calculates the change, followed by approval,
  declaration letter, receipt and execution.
- **Comparative rent, modernisation, operating cost billing/plan, free
  adjustment**: header records so far.

A procedure is possible only if both the contract type and the term type
allow it (``adjustment_procedures``); at most one agreed procedure
(graduated or index rent) per term.

Menus:

- *Real Estate › Contracts › Rent Adjustments*, in the order of the
  work: *Agreements* (the rent adjustments of all procedures), *Index
  Rents - Follow-up*, *Start Adjustment Run* (wizard), *Adjustments*
  (the contract term adjustments), *Capture Receipt*, *Adjustment Runs*
- *Real Estate › Configuration*: *Price Indices*, *Import Index Values*,
  *Index Rent Cap Rules*

On the contract: tab *Rent Adjustments*. Settings: ``receipt_days`` in the
real estate accounting, scheduled task ``price_index_import``, GENESIS
token in ``trytond.conf`` (see `Configuration <configuration.rst>`__ and
`Installation <installation.rst>`__). Tasks and the process template
*Index Rent Adjustment*: see `Tasks, Processes and Handover Reports
<tasks.rst>`__.

Rent adjustment
===============

``real_estate.contract.rent_adjustment``  (``contract_rent_adjustment.py``)
   **Rent Adjustments** (*Mietanpassungen*): one record per adjustment of
   one contract term, for every procedure, shown on the contract's *Rent
   Adjustments* tab (O2M ``rent_adjustments``) and in the menu *Contracts →
   Rent Adjustments*. A new record is created there via *New*: first the
   procedure, then the term.

   Procedures (``contract_type.ADJUSTMENT_PROCEDURES``): ``graduated_rent``
   (§ 557a BGB), ``index_rent`` (§ 557b), ``comparative_rent`` (§§ 558 ff.),
   ``modernisation`` (§§ 559 ff.), ``operation_costs_billing`` /
   ``operation_costs_plan`` (§ 560), ``free_adjustment``. Graduated
   rent and index rent have full processing (see below); the other
   procedures are header records so far.

   Header fields (all procedures): ``contract``, ``procedure``, ``term``
   (exactly one term - offered are terms of the contract whose contract
   type and term type both allow the procedure, and in state ``draft`` no
   term locked by a graduated rent), ``valid_from``, ``agreement_date``
   (required for graduated/index rent), ``written_form``, ``comment``,
   ``state`` (``draft`` / ``generated`` for a graduated rent, ``draft`` /
   ``active`` / ``closed`` for an index rent). Checks on save: term belongs
   to the contract, procedure allowed by contract type and term type, at
   most one agreed procedure (graduated or index rent) per term (§§ 557a,
   557b BGB; a closed index rent no longer counts), no comparative rent
   for a residential term with an active index rent. Only drafts can be
   deleted.

Graduated rent
==============

**Graduated rent** (``procedure = 'graduated_rent'``): all steps are
generated in advance as terms. The procedure-specific fields are only
visible (and required) for this procedure:

- Parameters: ``rhythm_months`` (≥ 12), ``step_count`` (≥ 1),
  ``increase_mode`` (``absolute`` € per period, ``per_area`` € per m²,
  ``percent``), ``increase_value``, ``percent_basis`` (``base`` = same
  increase for all steps, ``previous`` = compound). ``valid_from`` is
  always the start of the base term.
- Area for ``per_area``: the base term's informative measurement
  (``info_m_type``) as of its start, hierarchy-aware; fixed on
  generation (``generated_area``).
- Information: base amount (net, quantity × unit price), increase and
  increase % of the 1st step, final amount, total increase %, start of
  the last step, and a text preview of all steps (amount, increase and -
  with an informative area - the new amount per m²). Preview and
  generation use the same calculation ``compute_amounts()``: the
  increase is rounded (half up) per step, every step is an exact cent
  amount.
- Steps tab: the step terms, booking state (``booked``,
  ``last_booked_date``, ``last_booked_step``), ``predecessor`` /
  ``successor`` (chain of follow-up graduated rents) and
  ``generated_parameters`` (snapshot of the last generation).

Buttons (``ir.model.button`` records, restrictable per group):

*Generate* (``draft → generated``)
   Checks G01-G15 (errors: procedure allowed, rhythm ≥ 12, ≥ 1 step,
   increase ≥ 0.01 per step, base term not booked, no follow-up term,
   last step before the term's/contract's end with the maximum number of
   steps in the message, base term not an intermediate step of another
   graduated rent, contract draft/running without termination, written
   form for residential, area found, term type without ``m_type``;
   confirmable warnings: written form for commercial, termination waiver
   over 4 years, rounding with quantity ≠ 1, step start not matching the
   billing rhythm). Then the base term becomes step 0 and each step is
   created with ``ContractTerm._split()``; the last step takes over the
   original end of the base term (``base_valid_to_orig``). Cash flow is
   recalculated and the contract log gets parameters and step overview.
*Regenerate*
   Not booked: reset and generate again. Booked: after the graduated
   rent warning (below), only the steps after the last booked step are
   recalculated from that step on; booked steps keep amount and start.
   Refused if the next step would start inside a booked period.
*Reset* (``generated → draft``, not booked)
   Deletes steps 1…n and restores the base term (original end, no
   membership).
*End Graduated Rent* (booked)
   After the warning, deletes the steps not yet booked; the last booked
   step becomes the last step (open, unlocked, ``step_count`` adjusted).
   If only the base term is booked, the graduated rent is dissolved like
   *Reset*.

Lock (``ContractTerm.graduated_locked``): the base term and all steps
except the last one of a generated graduated rent - and the last step
carrying a follow-up graduated rent - cannot change ``valid_from``,
``valid_to``, ``term_type``, ``reference_item``, rhythm fields or
``taxes`` (readonly in the form, muted rows in the list, note in the
form), cannot be split and get no other rent adjustment (§ 557a para. 2
BGB). No term of a graduated rent can be deleted individually. Quantity
and unit price can be corrected; ``graduated_amount`` follows. Only the
graduated rent itself changes its terms (context
``_graduated_rent_generate``).

After the first booking every change (regenerate, end, manual amount
correction of a step) needs confirmation of
``ContractGraduatedRentChangeWarning``: the graduated rent is part of the
contract, a change requires an amendment agreed with the tenant. It
comes before the existing warnings for booked terms, is keyed on the new
parameters/values, and every confirmed change is logged in the contract
log (old/new parameters, steps before/after).

Follow-up graduated rent: the last step of graduated rent A can be the
base term of a new graduated rent B. The step stays a member of A and is
step 0 of B only via ``B.term``; while B exists (also as draft), A cannot
be regenerated, reset or ended.

Index rent
==========

Price index and cap rules
-------------------------

``real_estate.price_index`` / ``real_estate.price_index.value``
   Price index series for index rents (§ 557b BGB) with their monthly
   values per base year (menu *Configuration › Price Indices*). Default
   series ``VPI-DE`` (consumer price index Germany, Destatis table
   61111-0002, base 2020, ``residential_allowed`` - the only index allowed
   for residential index rents) and ``HVPI-DE`` (manual template for
   commercial contracts). Values are imported with the wizard *Import
   Index Values* (CSV with ``Month;Value`` rows, month as ``YYYY-MM`` or
   ``MM.YYYY``, or ``Year;Month name;Value`` rows of a GENESIS-Online
   table download; preview before import) or entered manually in the
   editable value list. Only ``final`` values of the series' current
   ``base_year`` count (``last_value_month``, ``get_value()``).
   Maintenance is restricted to the administration group.

   **GENESIS-Online import** (series with ``source = 'destatis_genesis'``
   and ``genesis_table``): buttons *Fetch Values* (from the year before
   the last value, catches revisions) and *Fetch from Base Year* on the
   series form (tab *Import*, administration only) and the scheduled task
   ``price_index_import`` (*Real Estate Accounting › Scheduled Tasks*,
   e.g. *Run on Day of Month* 20 - Destatis publishes the VPI in the middle
   of the following month). The web service is called by POST with the
   API token in the request header (``data/tablefile``, format ``ffcsv``);
   only the index rows (unit ``YYYY=100``) are imported (origin
   ``import``), a different base year is refused, revisions of values
   used by declared or executed adjustments are not taken over. Result
   and errors are shown in *Last Import Message*; errors never abort the
   scheduled run. The token is configured in ``trytond.conf`` (not in the
   database)::

      [real_estate]
      genesis_token = <API token from GENESIS-Online, menu Webservice (API)>
      # optional
      genesis_url = https://genesis.destatis.de/genesisWS/rest/2020/
      genesis_timeout = 60

   The Tryton server and the cron process need outgoing HTTPS access to
   ``genesis.destatis.de``. A flat file CSV downloaded manually from
   GENESIS-Online can also be imported with *Import Index Values*.

``real_estate.index_cap_rule``
   Prepared cap rule for index rents ("Mietrecht II", not in force yet;
   menu *Configuration › Index Rent Cap Rules*): validity of the received
   declaration (``valid_from``/``valid_to``), ``threshold_percent``
   (default 3, counted in full per year), ``excess_share_percent`` (default
   50) and ``tight_market_only``. New rules are inactive by default.
   ``apply()`` computes the counted change in sections of 12 months (rest
   pro rata, compounded, no cap for decreases); ``find()`` returns the
   active rule for a receipt date and property. The tight housing market
   is marked on the property (``tight_market`` with validity
   ``tight_market_valid_from``/``tight_market_valid_to``, tab *General*).

Agreement and adjustments
-------------------------

**Index rent** (``procedure = 'index_rent'``, § 557b BGB):
agreement, adjustment run,
declaration, receipt and execution. Tab *Index*: ``price_index``
(residential: only series with ``residential_allowed``, i.e. the VPI),
``index_base_month`` (first of the month) with the contract's own
statement ``index_base_value_contract`` / ``index_base_year_contract``
(documentation) and the computed ``index_base_value`` from the current
base year of the series, ``threshold_type`` / ``threshold_value``
(none / percent / index points), ``effective_rule`` (``statutory`` -
mandatory for residential - or ``contract_month`` with
``effective_offset_months`` for commercial), ``apply_cap`` (``auto`` /
``never``). Information: ``current_term`` (latest term of the chain of
the same term type and item from ``term`` on, also after splits by other
procedures), ``current_index_month`` / ``current_index_value``,
``last_change_date`` (start of the agreement ``valid_from`` resp. later
the last executed adjustment) and ``next_possible_date`` (+12 months,
§ 557b para. 2 BGB). ``declaration_deadline`` (*Declaration until*,
searchable) is the follow-up date: latest date to send the declaration
so that the adjustment takes effect on the next possible date (receipt
in the month before last minus ``receipt_days``; none for the commercial
contract month rule). Menu *Contracts › Rent Adjustments › Index Rents -
Follow-up* lists the active index rents with the tabs *Due* / *Next 3
Months* / *All*.

*Activate* (``draft → active``) checks: written form and agreement date
(I01; residential error, commercial confirmable warning), statutory
effective rule for residential, index allowed for residential (I02),
final value of the base month in the current base year (I03), no
comparative rent on the term chain and a confirmable warning for a
modernisation adjustment (I10, residential), hint on the
Preisklauselgesetz for commercial contracts not fixed for at least 10
years (I12). *Draft* (``active → draft``) and *Close Index Rent*
(``active → closed``) change the state; in ``active`` index series,
base month and term are readonly, threshold and comment stay editable.
*Draft* is refused once an adjustment is approved, declared or done,
*Close* while an adjustment is open.

Index adjustments (``real_estate.contract.term.adjustment`` with
``rent_adjustment``, ``contract_index_rent.py``, list on the *Index*
tab): created by the adjustment run (see *Wizards*). Reference
(``index_month_old``/``index_value_old``) is the agreement's current
index (last executed adjustment, else the base month), the new value
the run's index month - both from the current base year.
``compute_index_adjustment`` calculates the change (exact ratio, shown
with 2 digits), the threshold (percent or points, on the uncapped
change), the cap (``apply_cap = 'auto'``, active cap rule for the
planned receipt date and the property's tight market), the new amount
``planned_amount`` = old amount × ratio (resp. × capped change), rounded
half up to the cent - the decisive amount - and ``planned_unit_price``
= amount / quantity (4 digits). ``planned_valid_from``: statutory first
day of the month after next following ``receipt_date`` (before that a
preview from ``declaration_date`` + ``receipt_days`` of the real estate
accounting, default 3), for ``contract_month`` the index month +
offset. Check protocol ``check_state``/``check_message`` (codes I04
lock period, I05 index values, I06 contract running/end, I08 rounding,
I09 booked beyond the effective date, I13 decrease, I14 graduated rent
lock, S01 threshold). States ``draft → approved → declared → done``,
``cancelled``: *Recompute* (draft), *Approve* (refused with errors,
confirmable warning with findings), *Cancel* (warning if declared),
*Draft* (from cancelled, at most one open adjustment per agreement).
*Declare* (``approved → declared``, declaration date default today)
renders the declaration ``real_estate.contract.index_adjustment.letter``
(``report/index_adjustment_letter_de.odt``: one letter per adjustment,
addressed jointly to all main tenants, with index series and base
year, reference and new index month/value, change in percent and
points, cap rule if applied, old and new net rent and the difference,
expected effective date) and archives the original as attachment
(``letter``); the values are frozen from then on. Printing it again
from the print menu marks it *Zweitschrift*, before the declaration
*ENTWURF*. Receipt date and dispatch method are entered in the
adjustment form or the editable list *Contracts › Rent Adjustments ›
Capture Receipt* (declared adjustments). *Execute* (``declared → done``, for
the statutory rule only with a receipt date) recalculates the
effective date from the receipt, checks again (I04, I06, I09, I14, the
current term must still be ``term_old``) and I11 (the declared rent
must not exceed the rent allowed by the cap rule on the actual receipt
date), splits the term (``ContractTerm._split`` with the new unit
price from the effective date), recalculates the cash flow, sets
``term_new``, ``executed_by``/``executed_date`` and logs the
adjustment in the contract log (event ``index_rent``). The agreement
then takes the executed adjustment as reference for the next one.
Index values used by a declared or executed adjustment cannot be
changed or deleted.

Adjustment run: wizard *Adjustment of Contract Terms*, procedure
*Index Rent* (see `Wizards <wizards.rst>`__); declaration letter: see
`Reports <reports.rst>`__.

Term adjustments
================

``real_estate.contract.term.adjustment``  (``contract_term.py``)
   History record documenting a single old-term → new-term adjustment
   (e.g. a rent/advance-payment change following an operating cost billing
   run, an operating cost plan, or a free percentage/absolute change).

   *States:* ``draft`` · ``approved``

   Key fields: ``adjustment_mode`` (``percentage`` / ``absolute``),
   ``term_old`` (required, ``ondelete='RESTRICT'``), ``term_new``
   (``ondelete='RESTRICT'``, set once the replacement term exists), and an
   optional ``settlement_result`` link when the adjustment originates from
   an operating cost billing run.

   Function fields mirror ``company`` / ``property`` / ``contract`` from
   ``term_old``, and ``valid_from`` / ``valid_to`` / ``amount`` /
   ``tax_amount`` / ``total_amount`` from both ``term_old`` (suffix
   ``_old``) and ``term_new`` (suffix ``_new``), so a reviewer can compare
   the before/after amounts without opening either term individually.

   List *Contracts › Rent Adjustments › Adjustments*.

   Created by the adjustment run of the index rent (see *Index rent*
   below); the operating cost and free adjustment procedures of the
   wizard *Adjustment of Contract Terms* still have placeholder processing
   only (see `Wizards <wizards.rst>`__).
