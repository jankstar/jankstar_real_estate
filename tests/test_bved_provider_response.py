#!/usr/bin/env python3
"""Simulate a BVED Messdienstleister's response (D-Satz + E835 + P-Satz +
E898 with matching PDF settlement documents) from the A-/L-/M-/B-/K-Satz
files that `real_estate.bved.export` produced - so the import side
(`real_estate.bved.import` parse/match/apply) can be tested end-to-end
without a real service provider.

Pure Python, no trytond/database/proteus dependency: it only needs
bved_records.py (loaded directly from disk by path, not via the
`trytond.modules.real_estate` package, so this script also runs in a plain
Python environment without trytond installed).

Usage:
    python tests/test_bved_provider_response.py \\
        DTA310_....DAT DTM310_....DAT DTK310_....DAT \\
        [--out-dir DIR] [--seed N]

Distribution logic (see also the module docstrings below):
  - Costs are pooled per property (the 9-digit Liegenschaftsnummer prefix
    of "Ordnungsbegriff Abrechnungsunternehmen") from all K-Satz records of
    that property, then distributed across that property's M-Satz units.
  - The distribution weight per unit combines the two things actually
    available in the exported files that stand in for "Vorauszahlung" and
    "Mietvertragszeitraum": the M-Satz heating advance payment
    (`heating_advance_gross`, falling back to 1 if unset/zero) times the
    unit's occupancy period length in days. Apartment size itself is
    *not* part of the BVED interchange format (no per-unit area field
    exists in A-/M-/K-Satz) - in practice the advance payment already
    correlates with size, so it doubles as a reasonable stand-in here.
  - A small random jitter (+/- a few percent, seeded for reproducibility)
    is added to each unit's raw share before the final cent-exact
    largest-remainder correction, so shares look organically estimated
    rather than mathematically exact fractions of the total - while the
    corrected total still matches the K-Satz sum exactly, like a real
    settlement would.
  - E835 (Lohnanteil) is only generated where the source K-Satz carried a
    labor_share_amount > 0 (i.e. an estg_35a-classified cost), distributed
    the same way.
  - P-Satz (Energiepreisbremse) is a purely synthetic, small credit for
    structural testing only - the underlying 2022/23 support program has
    since ended, so treat this output as a format exercise, not a
    realistic figure for a later billing period.
  - E898 (Index Bilddatei) is emitted once per unit/period, referencing a
    generated single-page PDF "Heizkostenabrechnung" that lists the
    period, a per-cost-type breakdown (property total vs. this unit's
    share, plus energy/quantity total vs. share where the K-Satz carried
    a quantity), and the overall total/advance payment/balance - built
    with a hand-rolled, dependency-free minimal PDF writer (no reportlab
    requirement) so this script keeps working without extra packages.
"""
import argparse
import datetime
import importlib.util
import random
import re
import sys
from decimal import Decimal
from pathlib import Path


def _load_bved_records():
    path = Path(__file__).resolve().parent.parent / 'bved_records.py'
    spec = importlib.util.spec_from_file_location('bved_records', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bv = _load_bved_records()

_CENT = Decimal('0.01')


def read_lines(path):
    data = Path(path).read_bytes().decode('iso-8859-1')
    return [line for line in data.split('\r\n') if line.strip()]


def record_type_of(line):
    if line[:4] in ('E835', 'E898'):
        return line[:4]
    return line[0]


def read_records(path):
    """Return a list of (record_type, parsed_dict) for every line."""
    return [(record_type_of(line), bv.unpack(record_type_of(line), line))
        for line in read_lines(path)]


def property_number(provider_reference):
    return str(provider_reference).rjust(13, '0')[:9]


def distribute(total, weights, rng):
    """Split `total` across `weights` (list of Decimal >= 0), summing back
    to `total` exactly, with a small random jitter (+/- 4%) before the
    final largest-remainder rounding correction so shares don't look like
    exact fractions."""
    weight_sum = sum(weights) or Decimal(1)
    raw = []
    for weight in weights:
        base = (total * weight / weight_sum) if weight_sum else Decimal(0)
        jitter = Decimal(str(rng.uniform(-0.04, 0.04)))
        raw.append((base * (1 + jitter)).quantize(_CENT))
    diff = (total - sum(raw)).quantize(_CENT)
    if diff and raw:
        n = int(abs(diff) / _CENT)
        order = sorted(range(len(raw)), key=lambda i: raw[i],
            reverse=(diff < 0))
        for i in range(n):
            idx = order[i % len(order)]
            raw[idx] += _CENT if diff > 0 else -_CENT
    return raw


def build_cost_type_pools(k_records):
    """Group K-Satz records per property per cost type (key 'cost_type_key',
    falling back to the free-text 'cost_type_text' as the pool key when no
    numeric key is present), summing amounts and quantities. Returns
    {property: {pool_key: {'text', 'gross', 'net', 'quantity'}}}."""
    pools = {}
    for rec in k_records:
        prop = property_number(rec['provider_reference'])
        key = rec.get('cost_type_key') or (
            rec.get('cost_type_text') or '').strip() or 'unknown'
        bucket = pools.setdefault(prop, {})
        entry = bucket.setdefault(key, {
            'text': ((rec.get('cost_type_text') or '').strip()
                or ('Kostenart %s' % key)),
            'gross': Decimal(0), 'net': Decimal(0), 'quantity': Decimal(0),
            })
        entry['gross'] += rec.get('amount_gross') or Decimal(0)
        entry['net'] += rec.get('amount_net') or Decimal(0)
        entry['quantity'] += rec.get('quantity') or Decimal(0)
    return pools


def property_period_ends(lm_records):
    """Property -> L-Satz Abrechnungszeitraum-Ende ("period_end"), used
    as the fallback when a unit's own M-Satz occupancy_end is missing.
    "Letzter Tag Nutzungszeitraum" is an explicit Mussfeld on E835-, E898-
    and P-Satz (and very likely expected to be populated on D-Satz too,
    even though the available spec transcript leaves that field
    untagged there) - this generator must never emit a record without
    it."""
    l_records = [rec for rtype, rec in lm_records if rtype == 'L']
    return {
        property_number(rec['provider_reference']): rec.get('period_end')
        for rec in l_records}


def _resolve_period_ends(units, prop, l_period_ends, record_types):
    """One period-end date per unit (aligned by index with `units`), with
    a single stderr warning per unit that has none available at all -
    such a unit is then skipped entirely (see call sites) rather than
    emitting an invalid record."""
    resolved = []
    for unit in units:
        period_end = unit.get('occupancy_end') or l_period_ends.get(prop)
        if period_end is None:
            print(
                'WARNING: skipping %s for internal_reference=%s - no '
                'period end date available (M-Satz occupancy_end and '
                'L-Satz period_end both empty).' % (
                    '/'.join(record_types), unit.get('internal_reference')),
                file=sys.stderr)
        resolved.append(period_end)
    return resolved


def build_d_and_e835(a_records, lm_records, bk_records, rng):
    m_records = [rec for rtype, rec in lm_records if rtype == 'M']
    k_records = [rec for rtype, rec in bk_records if rtype == 'K']
    l_period_ends = property_period_ends(lm_records)

    units_by_property = {}
    for rec in m_records:
        units_by_property.setdefault(
            property_number(rec['provider_reference']), []).append(rec)

    costs_by_property = {}
    labor_by_property = {}
    for rec in k_records:
        prop = property_number(rec['provider_reference'])
        costs_by_property[prop] = costs_by_property.get(
            prop, (Decimal(0), Decimal(0)))
        gross, net = costs_by_property[prop]
        costs_by_property[prop] = (
            gross + (rec['amount_gross'] or Decimal(0)),
            net + (rec['amount_net'] or Decimal(0)))
        if rec.get('labor_share_amount'):
            labor_by_property[prop] = (
                labor_by_property.get(prop, Decimal(0))
                + rec['labor_share_amount'])

    cost_type_pools = build_cost_type_pools(k_records)

    d_lines = []
    e835_lines = []
    # internal_reference -> data needed to render the E898 PDF, keyed
    # separately from d_lines so build_e898() doesn't need to re-derive
    # (and re-distribute, with a different rng draw) the same shares.
    unit_details = {}
    for prop, units in units_by_property.items():
        total_gross, total_net = costs_by_property.get(
            prop, (Decimal(0), Decimal(0)))

        weights = []
        for unit in units:
            days = 1
            if unit.get('occupancy_start') and unit.get('occupancy_end'):
                days = max(1, (
                    unit['occupancy_end'] - unit['occupancy_start']).days + 1)
            advance = unit.get('heating_advance_gross') or Decimal(1)
            weights.append((advance or Decimal(1)) * days)

        gross_shares = distribute(total_gross, weights, rng)
        period_ends = _resolve_period_ends(
            units, prop, l_period_ends, ('D-Satz', 'E835-Satz'))

        pool = cost_type_pools.get(prop, {})
        per_type_gross_shares = {
            key: distribute(entry['gross'], weights, rng)
            for key, entry in pool.items()}
        per_type_quantity_shares = {
            key: (distribute(entry['quantity'], weights, rng)
                if entry['quantity'] else [Decimal(0)] * len(units))
            for key, entry in pool.items()}

        # net kept proportional to gross per unit rather than distributed
        # independently, so gross/net stay internally consistent per unit.
        for idx, (unit, gross_share) in enumerate(zip(units, gross_shares)):
            period_end = period_ends[idx]
            if period_end is None:
                continue
            net_share = (
                (gross_share * total_net / total_gross).quantize(_CENT)
                if total_gross else Decimal(0))
            advance_gross = unit.get('heating_advance_gross') or Decimal(0)
            advance_net = unit.get('heating_advance_net') or Decimal(0)
            balance_gross = gross_share - advance_gross
            d_lines.append(bv.pack('D', {
                'customer_number': unit['customer_number'],
                'provider_key': unit['provider_key'],
                'provider_reference': unit['provider_reference'],
                'internal_reference': unit['internal_reference'],
                'period_end_date': period_end,
                'total_costs_gross': gross_share,
                'total_costs_net': net_share,
                'advance_payment_gross': advance_gross,
                'advance_payment_net': advance_net,
                'balance_gross': balance_gross,
                'balance_net': net_share - advance_net,
                'currency': 'EUR',
                }))

            # Keyed by (internal_reference, period_end), not just
            # internal_reference: an object with multiple periods in the
            # year (tenant change, vacancy gap) produces multiple M-Satz
            # entries sharing the same internal_reference - keying on
            # that alone would let each later period silently overwrite
            # the earlier one's entry, losing its E898/PDF.
            unit_details[(unit['internal_reference'], period_end)] = {
                'customer_number': unit['customer_number'],
                'provider_key': unit['provider_key'],
                'provider_reference': unit['provider_reference'],
                'internal_reference': unit['internal_reference'],
                'period_start': unit.get('occupancy_start'),
                'period_end': period_end,
                'total_gross': gross_share,
                'total_net': net_share,
                'advance_gross': advance_gross,
                'balance_gross': balance_gross,
                'cost_types': [
                    {
                        'text': entry['text'],
                        'total_gross': entry['gross'],
                        'share_gross': per_type_gross_shares[key][idx],
                        'total_quantity': entry['quantity'],
                        'share_quantity': per_type_quantity_shares[key][idx],
                        }
                    for key, entry in pool.items()],
                }

        labor_total = labor_by_property.get(prop)
        if labor_total:
            labor_shares = distribute(labor_total, weights, rng)
            for idx, (unit, share, gross_share) in enumerate(
                    zip(units, labor_shares, gross_shares)):
                if not share or period_ends[idx] is None:
                    continue
                percent = (
                    (share / gross_share * 100).quantize(Decimal('0.01'))
                    if gross_share else Decimal(0))
                e835_lines.append(bv.pack('E835', {
                    'provider_key': unit['provider_key'],
                    'provider_reference': str(unit['provider_reference']),
                    'internal_reference': unit['internal_reference'],
                    'cost_type_key': 67,
                    'tax_service_type_key': 13,
                    'total_invoice_amount_gross': gross_share,
                    'user_share_amount': share,
                    'user_share_percent': percent,
                    'labor_share_total': labor_total,
                    'user_share_labor_amount': share,
                    'period_end_date': period_ends[idx],
                    }))

    return d_lines, e835_lines, unit_details


def build_p(lm_records, bk_records, rng):
    """Synthetic-only: a small (5-15%) credit on the property's heating
    cost pool, structural exercise for the historical EWPBG/StromPBG
    price-brake programs - not realistic for a period after they ended."""
    m_records = [rec for rtype, rec in lm_records if rtype == 'M']
    k_records = [rec for rtype, rec in bk_records if rtype == 'K']
    l_period_ends = property_period_ends(lm_records)

    units_by_property = {}
    for rec in m_records:
        units_by_property.setdefault(
            property_number(rec['provider_reference']), []).append(rec)
    costs_by_property = {}
    for rec in k_records:
        prop = property_number(rec['provider_reference'])
        costs_by_property[prop] = costs_by_property.get(prop, Decimal(0)) + (
            rec['amount_gross'] or Decimal(0))

    p_lines = []
    for prop, units in units_by_property.items():
        pool = costs_by_property.get(prop, Decimal(0))
        if not pool:
            continue
        credit_total = (pool * Decimal(str(rng.uniform(0.05, 0.15)))
            ).quantize(_CENT)
        weights = [
            (unit.get('heating_advance_gross') or Decimal(1))
            for unit in units]
        shares = distribute(credit_total, weights, rng)
        period_ends = _resolve_period_ends(
            units, prop, l_period_ends, ('P-Satz',))
        for idx, (unit, share) in enumerate(zip(units, shares)):
            if not share or period_ends[idx] is None:
                continue
            p_lines.append(bv.pack('P', {
                'customer_number': unit['customer_number'],
                'provider_key': unit['provider_key'],
                'provider_reference': unit['provider_reference'],
                'internal_reference': unit['internal_reference'],
                'period_end_date': period_ends[idx],
                'cost_type_key': 910,
                'total_amount_gross': credit_total,
                'total_amount_net': credit_total,
                'user_share_amount': share,
                'user_share_percent': (
                    (share / credit_total * 100).quantize(Decimal('0.01'))
                    if credit_total else Decimal(0)),
                }))
    return p_lines


def _fmt_amount(value):
    return '{:,.2f}'.format(float(value)).replace(',', 'T').replace(
        '.', ',').replace('T', '.')


def _fmt_date(value):
    return value.strftime('%d.%m.%Y') if value else '-'


def _pdf_escape(text):
    return text.replace('\\', r'\\').replace('(', r'\(').replace(')', r'\)')


def build_pdf_bytes(title, lines):
    """Build a minimal, dependency-free single-page A4 PDF (uncompressed,
    Helvetica text only) - no reportlab/weasyprint required."""
    stream_parts = []
    y = 800
    stream_parts.append(
        'BT /F1 14 Tf 50 %d Td (%s) Tj ET' % (y, _pdf_escape(title)))
    y -= 26
    for line in lines:
        stream_parts.append(
            'BT /F1 10 Tf 50 %d Td (%s) Tj ET' % (y, _pdf_escape(line)))
        y -= 16
    stream_bytes = '\n'.join(stream_parts).encode('latin-1', errors='replace')

    objects = [
        b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> '
        b'>> /MediaBox [0 0 595 842] /Contents 5 0 R >>',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
        ((b'<< /Length %d >>\nstream\n' % len(stream_bytes)) + stream_bytes
            + b'\nendstream'),
        ]

    buf = bytearray(b'%PDF-1.4\n')
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(buf))
        buf += ('%d 0 obj\n' % i).encode('ascii')
        buf += obj
        buf += b'\nendobj\n'
    xref_offset = len(buf)
    n = len(objects) + 1
    buf += ('xref\n0 %d\n' % n).encode('ascii')
    buf += b'0000000000 65535 f \n'
    for off in offsets:
        buf += ('%010d 00000 n \n' % off).encode('ascii')
    buf += b'trailer\n'
    buf += ('<< /Size %d /Root 1 0 R >>\n' % n).encode('ascii')
    buf += b'startxref\n'
    buf += (str(xref_offset) + '\n').encode('ascii')
    buf += b'%%EOF'
    return bytes(buf)


def _settlement_pdf_lines(detail):
    lines = [
        'Kundennummer: %s' % detail['customer_number'],
        'Objekt/Referenz: %s' % detail['internal_reference'],
        'Abrechnungszeitraum: %s - %s' % (
            _fmt_date(detail['period_start']),
            _fmt_date(detail['period_end'])),
        '',
        'Kostenart                      Gesamt Liegenschaft   Anteil Einheit',
        '-' * 76,
        ]
    for ct in detail['cost_types']:
        lines.append('%-28s %18s EUR   %14s EUR' % (
            ct['text'][:28], _fmt_amount(ct['total_gross']),
            _fmt_amount(ct['share_gross'])))
        if ct['total_quantity']:
            lines.append('    Energie/Menge: %s gesamt / %s Anteil' % (
                _fmt_amount(ct['total_quantity']),
                _fmt_amount(ct['share_quantity'])))
    lines.extend([
        '-' * 76,
        '',
        'Gesamtkosten (Anteil dieser Einheit): %s EUR' % _fmt_amount(
            detail['total_gross']),
        'Vorauszahlung: %s EUR' % _fmt_amount(detail['advance_gross']),
        'Saldo: %s EUR' % _fmt_amount(detail['balance_gross']),
        ])
    return lines


def build_e898(unit_details, out_dir):
    """Write one settlement-document PDF per unit/period and the matching
    E898-Satz record referencing it by filename."""
    pdf_dir = Path(out_dir)
    e898_lines = []
    pdf_paths = []
    for detail in unit_details.values():
        safe_ref = re.sub(
            r'[^A-Za-z0-9_-]+', '_', detail['internal_reference'])
        period_tag = (
            detail['period_end'].strftime('%Y%m%d')
            if detail['period_end'] else '00000000')
        filename = 'E898_%s_%s.pdf' % (safe_ref, period_tag)
        pdf_bytes = build_pdf_bytes(
            'Heizkostenabrechnung %s' % detail['internal_reference'],
            _settlement_pdf_lines(detail))
        path = pdf_dir / filename
        path.write_bytes(pdf_bytes)
        pdf_paths.append(path)

        e898_lines.append(bv.pack('E898', {
            'provider_key': detail['provider_key'],
            'provider_reference': str(detail['provider_reference']),
            'internal_reference': detail['internal_reference'],
            'billing_sequence_flag': '1',
            'document_path': filename,
            'document_sequence_number': 1,
            'period_end_date': detail['period_end'],
            'document_type': 'HKA',
            }))
    return e898_lines, pdf_paths


def write_file(out_dir, record_type, lines):
    if not lines:
        return None
    filename = bv.bved_filename(record_type, datetime.datetime.now())
    path = Path(out_dir) / filename
    content = ('\r\n'.join(lines) + '\r\n').encode(
        'iso-8859-1', errors='replace')
    path.write_bytes(content)
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('a_file', help='DTA310_*.DAT (A-Satz)')
    parser.add_argument('lm_file', help='DTM310_*.DAT (L-/M-Satz)')
    parser.add_argument('bk_file', help='DTK310_*.DAT (B-/K-Satz)')
    parser.add_argument('--out-dir', default=None,
        help='Output directory (default: same directory as a_file)')
    parser.add_argument('--seed', type=int, default=None,
        help='Random seed for reproducible jitter/credits')
    args = parser.parse_args(argv)

    rng = random.Random(args.seed)
    out_dir = args.out_dir or Path(args.a_file).resolve().parent

    a_records = read_records(args.a_file)
    lm_records = read_records(args.lm_file)
    bk_records = read_records(args.bk_file)

    d_lines, e835_lines, unit_details = build_d_and_e835(
        a_records, lm_records, bk_records, rng)
    p_lines = build_p(lm_records, bk_records, rng)
    e898_lines, pdf_paths = build_e898(unit_details, out_dir)

    written = []
    for record_type, lines in (('D', d_lines), ('E835', e835_lines),
            ('P', p_lines), ('E898', e898_lines)):
        path = write_file(out_dir, record_type, lines)
        if path:
            written.append((record_type, path, len(lines)))

    if not written:
        print('No output generated - check that the input files contain '
            'M-Satz and K-Satz records.', file=sys.stderr)
        return 1

    for record_type, path, count in written:
        print('%s-Satz: %d record(s) -> %s' % (record_type, count, path))
    for path in pdf_paths:
        print('PDF: -> %s' % path)
    return 0


if __name__ == '__main__':
    sys.exit(main())
