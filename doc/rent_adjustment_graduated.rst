.. _rent-adjustment-graduated:

**************
Graduated Rent
**************

Part of `Rent Adjustments <rent_adjustment.rst>`__ (common header, adjustment run, term adjustments). Procedure ``graduated_rent`` (*Staffelmiete*, § 557a BGB).

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
