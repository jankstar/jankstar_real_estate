.. _rent-adjustment-index:

****************
Rent Adjustments
****************

Overview
========

A rent adjustment (*Mietanpassung*) changes exactly one contract term by
one procedure (``contract_type.ADJUSTMENT_PROCEDURES``):

- `Graduated rent <rent_adjustment_graduated.rst>`__ (*Staffelmiete*, § 557a BGB): all steps are generated
  in advance as terms.
- `Index rent <rent_adjustment_index.rst>`__ (*Indexmiete*, § 557b BGB): agreement on a price index;
  the adjustment run calculates the change, followed by approval,
  declaration letter, receipt and execution.
- `Comparative rent <rent_adjustment_comparative.rst>`__ (*Vergleichsmiete*, §§ 558-558b BGB): the
  adjustment run selects the terms, uses the accepted calculations of the
  rent survey, applies the cap and requests the consent of the tenant.
- **Modernisation, operating cost billing/plan, free adjustment**: header
  records so far.

A procedure is possible only if the contract type, the term type and the
use class of at least one rental unit of the term's contract item allow
it (``adjustment_procedures``; rental units without use class: all
procedures except the comparative rent). By default the use class
*Apartment* allows all procedures, *Office*, *Retail*, *Warehouse*,
*Parking* and *Garage* all except the comparative rent and the
modernisation - the comparative rent (§ 558 BGB) is only possible for
apartments. At most one agreed procedure (graduated or index rent) per
term.

Menus:

- *Real Estate › Contracts › Rent Adjustments*, in the order of the
  work: *Agreements* (the rent adjustments of all procedures), *Index
  Rents - Follow-up*, *Adjustment Runs* (the central entry, see
  *Adjustment run*), *Adjustments* (the contract term adjustments),
  *Comparative Rent Calculations* - all lists with the selection
  *Company* (required) and *Property* (optional) above the list; the
  adjustment runs show a run without properties (= all) for every
  property; columns *Property* (agreements, adjustments) and *Properties*
  (runs)
- *Real Estate › Configuration*: *Price Indices*, *Import Index Values*,
  *Index Rent Cap Rules*

On the contract: tab *Rent Adjustments*. Settings: ``receipt_days`` in the
real estate accounting, scheduled task ``price_index_import``, GENESIS
token in ``trytond.conf`` (see `Configuration <configuration.rst>`__ and
`Installation <installation.rst>`__). Tasks and the process templates
of the adjustment run: see `Tasks, Processes and Handover Reports
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
   rent, index rent and comparative rent have full processing (see
   *Procedures*); modernisation, operating cost and free adjustment are header
   records so far.

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

Procedures
==========

The procedures with their own processing are described on separate
pages:

- `Graduated Rent <rent_adjustment_graduated.rst>`__ (*Staffelmiete*,
  § 557a BGB) - steps generated in advance as terms
- `Index Rent <rent_adjustment_index.rst>`__ (*Indexmiete*, § 557b BGB) -
  price indices, cap rules, agreement, adjustments, declaration
- `Comparative Rent (Rent Survey) <rent_adjustment_comparative.rst>`__
  (*Vergleichsmiete*, §§ 558-558b BGB) - rent survey and calculation of
  the comparative rent, selection, cap, request for consent, consent

Modernisation, operating cost billing/plan and free adjustment are header
records so far.


Adjustment run
==============

``real_estate.contract.term.adjustment.run``  (``adjustment_run.py``)
   One process for all subsequent procedures (so far *Index Rent* and
   *Comparative Rent*), menu *Contracts › Rent Adjustments ›
   Adjustment Runs* with the tabs *In Progress*, *Announced*, *Done*,
   *All*. A run (number ``AL-<year>-<n>``) has the procedure, company,
   optional properties and contracts as filter, key date, planned
   declaration date and the parameters of the procedure (index: series,
   index month, include decreases; comparative rent: minimum increase in
   amount and percent, create calculations). Tabs *Workflow* (process of
   the run), *Parameters*, *Adjustments* (editable list: approval reason,
   manual amount with reason), *Receipts / Consents* (editable list of
   the announced adjustments: receipt date, dispatch method, consent),
   *Protocol* (dated block per step). *Print Letters* (announced/ready)
   prints all letters still to send in one document; the archived
   originals hang on the adjustment and on the contract. *Add Terms*
   (wizard, selected or
   calculated run) adds single terms with the checks of the selection.

   Plausibility warnings (confirmable) when capturing receipt and
   consent: receipt before the declaration date or in the future,
   consent before the receipt - the effective date always follows the
   receipt.

   Manual amount (both procedures): ``manual_amount`` with
   ``override_reason`` replaces the computed amount (``computed_amount``)
   - only between the current and the computed amount (A02 error,
   A01 hint).

   Workflow: *Select* (draft → selected; the procedure creates draft
   adjustments, every candidate gets a protocol line with the result or
   the cause of the skip; existing adjustments of the run stay - an
   adjustment cancelled in the run excludes its agreement from a new
   selection) → *Calculate* (values and checks of the drafts) →
   *Approve* (drafts without findings; with a warning only with an
   *Approval Reason*; errors and warnings without reason are cancelled
   and listed) → *Announce* (letters of the approved adjustments,
   archived) → the run becomes *Ready* as soon as every needed receipt is
   (and every consent decided; this automatic state - also back to
   *Announced* or on to *Done* - writes a protocol line and completes the
   process step) → *Execute* (in the background: refused adjustments
   are closed at once, every consented one is executed by its own
   background job - an error is rolled back and written to the protocol,
   the adjustment stays announced; reload the run to see the result) (term split, refused
   adjustments are closed; the run is *Done* when no adjustment is
   open). *Reset to Draft* deletes the drafts, *Cancel* cancels the
   open adjustments and the process. All steps also work for several
   runs from the list.

   Process: the template *Index Rent Adjustment Run* (code
   ``adjustment_run_index_rent``) resp. *Comparative Rent Adjustment Run*
   (code ``adjustment_run_comparative_rent``), model of the run, is
   started with the first selection; its six steps complete themselves with the states of
   the run (``run_selected`` … ``run_done``); the steps replace separate
   tasks per adjustment.

Term adjustments
================

``real_estate.contract.term.adjustment``  (``contract_term.py``)
   History record documenting a single old-term → new-term adjustment
   (e.g. a rent/advance-payment change following an operating cost billing
   run, an operating cost plan, or a free percentage/absolute change).

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

   Created by the adjustment run (see *Adjustment run*); so far for the
   index rent and the comparative rent - the operating cost, free
   adjustment and modernisation procedures will follow as procedures of
   the run. States ``draft`` · ``approved`` · ``declared`` · ``done`` ·
   ``refused`` (comparative rent: consent refused) · ``cancelled``.
