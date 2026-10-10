.. _rent-adjustment-index-rent:

**********
Index Rent
**********

Part of `Rent Adjustments <rent_adjustment.rst>`__ (common header, adjustment run, term adjustments). Procedure ``index_rent`` (*Indexmiete*, § 557b BGB), processed by the adjustment run.

Price index and cap rules
=========================

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
=========================

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
tab): created by the adjustment run (see `Rent Adjustments <rent_adjustment.rst>`__, *Adjustment run*). Reference
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
*ENTWURF*. *Declare* and *Execute* are buttons of the adjustment run only.
Receipt date and dispatch method are entered in the
adjustment form or the editable list of the tab *Receipts* of the
adjustment run (declared adjustments). *Execute* (``declared → done``, for
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

Adjustment run with the procedure *Index Rent* (see `Rent Adjustments <rent_adjustment.rst>`__, *Adjustment run*);
declaration letter: see `Reports <reports.rst>`__.
