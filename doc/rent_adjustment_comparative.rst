.. _rent-adjustment-comparative:

****************
Comparative Rent
****************

Part of `Rent Adjustments <rent_adjustment.rst>`__ (common header, adjustment run, term adjustments). Procedure ``comparative_rent`` (*Vergleichsmiete*, §§ 558-558b BGB), processed by the adjustment run; the comparative rent itself comes from the `Rent Survey <rent_survey.rst>`__.

**Comparative rent** (``procedure = 'comparative_rent'``, §§ 558-558b
BGB, ``contract_comparative_rent.py``): increase of the net rent up to the
local comparative rent of the rent survey, only for apartments (use
class), never for a term with a graduated or index rent.

Agreement: the adjustment run creates one active rent adjustment
``comparative_rent`` per term chain (term = first term of the chain,
``valid_from`` = its start) when a term is selected the first time; it
keeps the history of the adjustments (lock of one year). *Close* ends it
(e.g. at the end of the contract), *Draft*/*Activate* as for the index
rent. Tab *Adjustments* of the agreement: current term and adjustments.

Cap (§ 558 para. 3 BGB): 20 % in three years, 15 % for a property with
``reduced_cap`` (*Reduced Cap 15 % (Regulation)* with validity
``reduced_cap_valid_from``/``reduced_cap_valid_to``, tab *General* of the
property, ``BaseObject.cap_percent(date)``).

Selection (procedure ``ComparativeRentProcedure``): current terms of
running contracts of the filters whose contract type and term type allow
the procedure, monthly rhythm (``rhythm_type = 'monthly'``,
``rhythm = 1``) and use class of the rental units. Excluded with a
protocol line: V01 graduated or index rent on the chain or term locked,
V02 open adjustment, V05 not exactly one apartment in the item, V06
contract ends before the effective date, V03 rent changed less than 15
months before the effective date (changes by modernisation and operating
cost adjustments do not count; protocol with the earliest date), V04 last
request less than one year before the declaration date. With *Create
Calculations* (default) the run creates or recalculates the calculation
of the rent survey of the apartment on the key date
(``calculate_for``); the button *Calculations* of the run opens them for
the common acceptance.

Calculation (``_comparative_compute``): effective date ``t`` = start of the
third month after the receipt (before: declaration date + receipt days),
comparative rent ``M_vgl`` = accepted calculation (key date at most one
year before the declaration date, V07), rent three years before ``t``
(``M_3J``, else the initial rent), increases not counted ``E_mod``
(modernisation / operating cost adjustments within the three years), cap
``M_kap = M_3J × (1 + q) + E_mod``, new rent = lower of ``M_vgl`` and
``M_kap``. Fields ``calculation``, ``comparative_amount``,
``cap_base_amount``, ``cap_excluded_amount``, ``cap_percent``,
``cap_amount``, ``limited_by``, ``calculation_text`` (tab *Comparative
Rent* of the adjustment). Checks: V03, V04, V06 again, V07 accepted
calculation (error), V08 calculation with warnings or cell outside the
qualified part (warning), V09 no increase or below the minimum increase of
the run (error), V10 the cap applies (hint), V11 term type with operating
costs (error), V12 booked beyond the effective date (warning).

Request for consent: report ``real_estate.contract.comparative_rent.letter``
(``report/comparative_rent_letter_de.odt``) with the current and the new
net rent, the effective date, the reasons from the calculation (rent
survey, version, table cell with lower/mean/upper value, classification
of the span from the calculation protocol, a deviating accepted rent with
its reason), the cap and the period for consideration, plus a consent
form. *Announce* archives the original at the adjustment.

Receipt and consent (tab *Receipts / Consents* of the run): receipt date
(→ ``consent_state = 'pending'``, task *Consent period of the rent
increase ends* at ``consent_deadline`` = end of the second month after the
receipt), then ``consent_state`` *Consented* / *Partially Consented*
(with ``consented_amount`` between current and requested rent) /
*Refused* with ``consent_date``. ``lawsuit_deadline`` = three months after
the consent deadline. The run is *Ready* when every decision is captured.
*Execute*: consented adjustments split the term at the effective date
with the requested resp. consented amount (contract log
``comparative_rent``), refused ones get the state *Refused* (no split,
task *Check the action for consent* 14 days before the lawsuit deadline,
contract log). The rule M09 *Consent period expired* creates the same task
when no decision is captured within the period.
