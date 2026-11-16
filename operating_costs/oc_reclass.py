'''Operating cost reclassification (Kostenumbuchung) from the property to the
rental objects - pure functions (spezifikation-betriebskostenzuordnung.md
6.5, E22/E27/E29)'''
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

CENT = Decimal('0.01')


def distribute_groups(groups, weights):
    """Split every group amount in proportion to the weights.

    groups: {group key: amount}, weights: {target: weight >= 0}.
    Returns {target: {group key: amount}} - each group is rounded to cents
    and the remaining cents go to the targets with the largest remainder
    (ties: larger weight, then the order of the weights), so that the
    amounts of every group add up exactly to the group amount."""
    targets = [t for t, w in weights.items() if w]
    result = {t: {} for t in weights}
    total = sum(Decimal(str(weights[t])) for t in targets)
    if not total:
        return result
    for key, amount in groups.items():
        if not amount:
            continue
        sign = 1 if amount > 0 else -1
        absolute = abs(amount)
        rows = []
        for index, target in enumerate(targets):
            raw = absolute * Decimal(str(weights[target])) / total
            floor = raw.quantize(CENT, rounding=ROUND_DOWN)
            rows.append([target, floor, raw - floor,
                    Decimal(str(weights[target])), index])
        rest = int(((absolute - sum(r[1] for r in rows)) / CENT)
            .to_integral_value())
        for row in sorted(rows, key=lambda r: (-r[2], -r[3], r[4]))[:rest]:
            row[1] += CENT
        for target, value, _, _, _ in rows:
            if value:
                result[target][key] = sign * value
    return result


def split_tax(tax_amount, deductible_rate):
    """(deductible, non-deductible) part of a tax amount for the option
    rate as 0..1 fraction - the deductible part rounded to cents"""
    rate = Decimal(str(deductible_rate or 0))
    deductible = (tax_amount * rate).quantize(CENT, rounding=ROUND_HALF_UP)
    return deductible, tax_amount - deductible


def reclass_amounts(net, taxes, rate_from, rate_to):
    """Amounts of one reclassification (one account/tax group of one rental
    object): relief of the property with its option rate rate_from, charge
    of the rental object with its option rate rate_to (0..1).

    net: net amount, taxes: [(tax, full tax amount)].
    Returns {'credit_cost': net + non-deductible part at rate_from,
    'debit_cost': net + non-deductible part at rate_to,
    'credit_taxes': [(tax, deductible at rate_from, base)],
    'debit_taxes': [(tax, deductible at rate_to, base)]} - the credit side
    equals the debit side (net + full taxes)."""
    credit_cost = debit_cost = net
    credit_taxes, debit_taxes = [], []
    rate_from = Decimal(str(rate_from or 0))
    rate_to = Decimal(str(rate_to or 0))
    for tax, amount in taxes:
        deductible, non_deductible = split_tax(amount, rate_from)
        credit_cost += non_deductible
        credit_taxes.append((tax, deductible,
                (net * rate_from).quantize(CENT, rounding=ROUND_HALF_UP)))
        deductible, non_deductible = split_tax(amount, rate_to)
        debit_cost += non_deductible
        debit_taxes.append((tax, deductible,
                (net * rate_to).quantize(CENT, rounding=ROUND_HALF_UP)))
    return {
        'credit_cost': credit_cost,
        'debit_cost': debit_cost,
        'credit_taxes': credit_taxes,
        'debit_taxes': debit_taxes,
        }
