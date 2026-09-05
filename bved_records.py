"""Fixed-width (de)serialization for the BVED / ARGE FHW "Standard-Datenaustausch"
Version 3.10 (see rechercheergebnis-bved-schnittstelle.md for the full field
tables this module transcribes). Pure Python, no Tryton dependency, so it can
be unit-tested without a database.
"""
import datetime
from collections import namedtuple
from decimal import Decimal, ROUND_HALF_UP

FieldSpec = namedtuple('FieldSpec', ['name', 'start', 'length', 'kind', 'decimals'])


def _f(name, start, length, kind, decimals=0):
    return FieldSpec(name, start, length, kind, decimals)


# Record type -> total length in characters (fixed per BVED file convention).
RECORD_LENGTHS = {
    'A': 128,
    'L': 2048,
    'M': 2048,
    'B': 1024,
    'K': 1024,
    'D': 1024,
    'E835': 133,
    'E898': 120,
    'P': 95,
}

# Values auto-filled by pack() when the caller does not supply them.
DEFAULTS = {
    'A': {'satzart': 'A', 'satzende': 'A', 'arge_version': '03.10'},
    'L': {'satzart': 'L', 'satzende': 'L', 'arge_version': '03.10'},
    'M': {'satzart': 'M', 'satzende': 'M', 'arge_version': '03.10'},
    'B': {'satzart': 'B', 'satzende': 'B', 'arge_version': '03.10'},
    'K': {'satzart': 'K', 'satzende': 'K', 'arge_version': '03.10'},
    'D': {'satzart': 'D', 'satzende': 'D', 'arge_version': '03.10'},
    'E835': {'satzart': 'E835'},
    'E898': {'satzart': 'E898'},
    'P': {'satzart': 'P', 'arge_version': '03.10'},
}

# File name prefix (DTxxxx) each record type is delivered/collected under.
FILE_PREFIX = {
    'A': 'DTA310',
    'L': 'DTM310',
    'M': 'DTM310',
    'B': 'DTK310',
    'K': 'DTK310',
    'D': 'DTD310',
    'E835': 'DTE835',
    'E898': 'DTE898',
    'P': 'DTP310',
}

RECORD_SPECS = {
    'A': [
        _f('satzart', 1, 1, 'AN'),
        _f('arge_version', 2, 5, 'AN'),
        _f('customer_number', 7, 10, 'N'),
        _f('provider_key', 17, 2, 'AN'),
        _f('provider_reference', 19, 13, 'N'),
        _f('internal_reference', 32, 20, 'AN'),
        _f('satzende', 128, 1, 'AN'),
    ],
    'L': [
        _f('satzart', 1, 1, 'AN'),
        _f('arge_version', 2, 5, 'AN'),
        _f('customer_number', 7, 10, 'N'),
        _f('provider_key', 17, 2, 'AN'),
        _f('provider_reference', 19, 13, 'N'),
        _f('vat_flag', 32, 1, 'N'),
        _f('street', 33, 35, 'AN'),
        _f('country', 68, 3, 'AN'),
        _f('postal_code', 71, 10, 'AN'),
        _f('city', 81, 35, 'AN'),
        _f('period_start', 116, 6, 'DATE'),
        _f('period_end', 122, 6, 'DATE'),
        _f('object_number', 128, 15, 'AN'),
        _f('vacancy_risk_flag', 143, 1, 'N'),
        _f('vacancy_risk_percent', 144, 3, 'DEC', 2),
        _f('labor_share_flag', 147, 1, 'N'),
        _f('currency', 148, 3, 'AN'),
        _f('weg_flag', 151, 1, 'N'),
        _f('total_area', 152, 7, 'DEC', 2),
        _f('non_residential_flag', 159, 1, 'N'),
        _f('energy_improvement_flag', 160, 1, 'N'),
        _f('heat_supply_flag', 161, 1, 'N'),
        _f('co2_landlord_share_percent', 162, 3, 'N'),
        _f('heat_connection_2023_flag', 165, 1, 'N'),
        _f('satzende', 2048, 1, 'AN'),
    ],
    'M': [
        _f('satzart', 1, 1, 'AN'),
        _f('arge_version', 2, 5, 'AN'),
        _f('customer_number', 7, 10, 'N'),
        _f('provider_key', 17, 2, 'AN'),
        _f('provider_reference', 19, 13, 'N'),
        _f('internal_reference', 32, 20, 'AN'),
        _f('address_flag', 52, 1, 'N'),
        _f('tenant_name1', 53, 35, 'AN'),
        _f('tenant_name2', 88, 35, 'AN'),
        _f('tenant_name3', 123, 35, 'AN'),
        _f('tenant_name4', 158, 35, 'AN'),
        _f('tenant_street', 193, 35, 'AN'),
        _f('tenant_country', 228, 3, 'AN'),
        _f('tenant_postal_code', 231, 10, 'AN'),
        _f('tenant_city', 241, 35, 'AN'),
        _f('owner_name1', 276, 35, 'AN'),
        _f('owner_name2', 311, 35, 'AN'),
        _f('owner_name3', 346, 35, 'AN'),
        _f('owner_name4', 381, 35, 'AN'),
        _f('owner_street', 416, 35, 'AN'),
        _f('owner_country', 451, 3, 'AN'),
        _f('owner_postal_code', 454, 10, 'AN'),
        _f('owner_city', 464, 35, 'AN'),
        _f('occupancy_start', 499, 6, 'DATE'),
        _f('occupancy_end', 505, 6, 'DATE'),
        _f('vat_treatment_flag', 511, 1, 'N'),
        _f('vacancy_risk_calc_flag', 512, 1, 'N'),
        _f('heating_base_share', 513, 10, 'DEC', 2),
        _f('heating_advance_gross', 523, 10, 'DEC', 2),
        _f('heating_advance_net', 533, 10, 'DEC', 2),
        _f('hotwater_base_share', 543, 10, 'DEC', 2),
        _f('hotwater_advance_gross', 553, 10, 'DEC', 2),
        _f('hotwater_advance_net', 563, 10, 'DEC', 2),
        _f('coldwater_base_share', 573, 10, 'DEC', 2),
        _f('coldwater_advance_gross', 583, 10, 'DEC', 2),
        _f('coldwater_advance_net', 593, 10, 'DEC', 2),
        _f('allocation1_key', 603, 3, 'N'),
        _f('allocation1_share', 606, 10, 'DEC', 2),
        _f('allocation2_key', 616, 3, 'N'),
        _f('allocation2_share', 619, 10, 'DEC', 2),
        _f('allocation3_key', 629, 3, 'N'),
        _f('allocation3_share', 632, 10, 'DEC', 2),
        _f('provider_org_name1', 642, 35, 'AN'),
        _f('provider_org_name2', 677, 35, 'AN'),
        _f('provider_org_name3', 712, 35, 'AN'),
        _f('provider_org_name4', 747, 35, 'AN'),
        _f('provider_org_street', 782, 35, 'AN'),
        _f('provider_org_country', 817, 3, 'AN'),
        _f('provider_org_postal_code', 820, 10, 'AN'),
        _f('provider_org_city', 830, 35, 'AN'),
        _f('tax_id_flag', 865, 1, 'N'),
        _f('tax_id', 866, 16, 'AN'),
        _f('tax_rate_flag', 882, 1, 'N'),
        _f('invoice_number_flag', 883, 1, 'N'),
        _f('invoice_number', 884, 25, 'AN'),
        _f('bank_account_number', 909, 18, 'AN'),
        _f('bank_code', 927, 15, 'AN'),
        _f('company_flag', 942, 1, 'N'),
        _f('direct_debit_flag', 943, 1, 'N'),
        _f('debtor_name1', 944, 35, 'AN'),
        _f('debtor_name2', 979, 35, 'AN'),
        _f('debtor_name3', 1014, 35, 'AN'),
        _f('debtor_name4', 1049, 35, 'AN'),
        _f('debtor_street', 1084, 35, 'AN'),
        _f('debtor_country', 1119, 3, 'AN'),
        _f('debtor_postal_code', 1122, 10, 'AN'),
        _f('debtor_city', 1132, 35, 'AN'),
        _f('vacancy_flag', 1167, 1, 'N'),
        _f('tenant_change_fee_flag', 1168, 1, 'N'),
        _f('heating_base_key', 1169, 3, 'N'),
        _f('hotwater_base_key', 1172, 3, 'N'),
        _f('satzende', 2048, 1, 'AN'),
    ],
    'B': [
        _f('satzart', 1, 1, 'AN'),
        _f('arge_version', 2, 5, 'AN'),
        _f('customer_number', 7, 10, 'N'),
        _f('provider_key', 17, 2, 'AN'),
        _f('provider_reference', 19, 13, 'N'),
        _f('currency', 32, 3, 'AN'),
        _f('period_start', 35, 6, 'DATE'),
        _f('period_end', 41, 6, 'DATE'),
        _f('fuel_type', 47, 3, 'N'),
        _f('heating_value', 50, 11, 'DEC', 4),
        _f('stock_start_date', 61, 6, 'DATE'),
        _f('stock_start_quantity', 67, 11, 'DEC', 3),
        _f('stock_start_amount_gross', 78, 10, 'DEC', 2),
        _f('stock_start_amount_net', 88, 10, 'DEC', 2),
        _f('stock_end_date', 98, 6, 'DATE'),
        _f('stock_end_quantity', 104, 11, 'DEC', 3),
        _f('stock_end_amount_gross', 115, 10, 'DEC', 2),
        _f('stock_end_amount_net', 125, 10, 'DEC', 2),
        _f('ww_temperature', 135, 4, 'DEC', 2),
        _f('ww_consumption_m3', 139, 9, 'DEC', 3),
        _f('ww_percentage', 148, 4, 'DEC', 2),
        _f('ww_meter_start', 152, 9, 'DEC', 3),
        _f('ww_meter_end', 161, 9, 'DEC', 3),
        _f('fuel_indicator_flag', 170, 1, 'N'),
        _f('supply_heating1_start', 171, 6, 'DATE'),
        _f('supply_heating1_end', 177, 6, 'DATE'),
        _f('supply_heating2_start', 183, 6, 'DATE'),
        _f('supply_heating2_end', 189, 6, 'DATE'),
        _f('supply_ww1_start', 195, 6, 'DATE'),
        _f('supply_ww1_end', 201, 6, 'DATE'),
        _f('supply_ww2_start', 207, 6, 'DATE'),
        _f('supply_ww2_end', 213, 6, 'DATE'),
        _f('meter_type', 219, 3, 'N'),
        _f('meter_unit', 222, 3, 'N'),
        _f('meter_number', 225, 20, 'AN'),
        _f('consumption', 245, 10, 'DEC', 3),
        _f('meter_reading_start', 255, 10, 'DEC', 3),
        _f('meter_reading_end', 265, 10, 'DEC', 3),
        _f('primary_energy_factor', 275, 3, 'DEC', 2),
        _f('satzende', 1024, 1, 'AN'),
    ],
    'K': [
        _f('satzart', 1, 1, 'AN'),
        _f('arge_version', 2, 5, 'AN'),
        _f('customer_number', 7, 10, 'N'),
        _f('provider_key', 17, 2, 'AN'),
        _f('provider_reference', 19, 13, 'N'),
        _f('cost_type_key', 32, 3, 'N'),
        _f('cost_type_text', 35, 25, 'AN'),
        _f('uniform_cost_flag', 60, 1, 'AN'),
        _f('invoice_date', 61, 6, 'DATE'),
        _f('quantity', 67, 11, 'DEC', 3),
        _f('amount_gross', 78, 10, 'DEC', 2),
        _f('amount_net', 88, 10, 'DEC', 2),
        _f('tax_service_type_key', 98, 2, 'N'),
        _f('labor_share_amount', 100, 10, 'DEC', 2),
        _f('fuel_indicator_flag', 110, 1, 'N'),
        _f('usage_group', 111, 4, 'AN'),
        _f('emission_type', 115, 2, 'AN'),
        _f('co2_emission_factor', 117, 9, 'DEC', 3),
        _f('co2_emission_quantity', 126, 9, 'DEC', 3),
        _f('co2_cost_gross', 135, 10, 'DEC', 2),
        _f('co2_cost_net', 145, 10, 'DEC', 2),
        _f('energy_source_1', 155, 2, 'AN'),
        _f('energy_share_1', 157, 3, 'DEC', 1),
        _f('energy_emission_factor_1', 160, 9, 'DEC', 3),
        _f('energy_source_2', 169, 2, 'AN'),
        _f('energy_share_2', 171, 3, 'DEC', 1),
        _f('energy_emission_factor_2', 174, 9, 'DEC', 3),
        _f('energy_source_3', 183, 2, 'AN'),
        _f('energy_share_3', 185, 3, 'DEC', 1),
        _f('energy_emission_factor_3', 188, 9, 'DEC', 3),
        _f('energy_source_4', 197, 2, 'AN'),
        _f('energy_share_4', 199, 3, 'DEC', 1),
        _f('energy_emission_factor_4', 202, 9, 'DEC', 3),
        _f('energy_source_5', 211, 2, 'AN'),
        _f('energy_share_5', 213, 3, 'DEC', 1),
        _f('energy_emission_factor_5', 216, 9, 'DEC', 3),
        _f('energy_source_6', 225, 2, 'AN'),
        _f('energy_share_6', 227, 3, 'DEC', 1),
        _f('energy_emission_factor_6', 230, 9, 'DEC', 3),
        _f('satzende', 1024, 1, 'AN'),
    ],
    'D': [
        _f('satzart', 1, 1, 'AN'),
        _f('arge_version', 2, 5, 'AN'),
        _f('customer_number', 7, 10, 'N'),
        _f('provider_key', 17, 2, 'AN'),
        _f('provider_reference', 19, 13, 'N'),
        _f('internal_reference', 32, 20, 'AN'),
        _f('period_end_date', 52, 6, 'DATE'),
        _f('total_costs_gross', 58, 10, 'DEC', 2),
        _f('total_costs_net', 68, 10, 'DEC', 2),
        _f('advance_payment_gross', 78, 10, 'DEC', 2),
        _f('advance_payment_net', 88, 10, 'DEC', 2),
        _f('new_monthly_advance_gross', 98, 10, 'DEC', 2),
        _f('new_monthly_advance_net', 108, 10, 'DEC', 2),
        _f('vacancy_risk_amount_gross', 118, 10, 'DEC', 2),
        _f('balance_gross', 128, 10, 'DEC', 2),
        _f('balance_net', 138, 10, 'DEC', 2),
        _f('cost_type_key', 148, 3, 'N'),
        _f('consumption_share', 151, 9, 'DEC', 3),
        _f('consumption_unit_key', 160, 3, 'N'),
        _f('reading_method_key', 163, 3, 'N'),
        _f('name1', 166, 35, 'AN'),
        _f('currency', 201, 3, 'AN'),
        _f('co2_allocated_gross', 204, 10, 'DEC', 2),
        _f('co2_allocated_net', 214, 10, 'DEC', 2),
        _f('co2_not_allocated_gross', 224, 10, 'DEC', 2),
        _f('co2_not_allocated_net', 234, 10, 'DEC', 2),
        _f('satzende', 1024, 1, 'AN'),
    ],
    'E835': [
        _f('satzart', 1, 4, 'AN'),
        _f('sequence_number', 5, 7, 'N'),
        _f('provider_key', 12, 2, 'AN'),
        _f('provider_reference', 14, 18, 'AN'),
        _f('internal_reference', 32, 20, 'AN'),
        _f('billing_sequence_flag', 52, 1, 'AN'),
        _f('cost_type_key', 53, 3, 'N'),
        _f('cost_type_text', 56, 25, 'AN'),
        _f('tax_service_type_key', 81, 2, 'N'),
        _f('total_invoice_amount_gross', 83, 10, 'DEC', 2),
        _f('user_share_amount', 93, 10, 'DEC', 2),
        _f('user_share_percent', 103, 5, 'DEC', 2),
        _f('labor_share_total', 108, 10, 'DEC', 2),
        _f('user_share_labor_amount', 118, 10, 'DEC', 2),
        _f('period_end_date', 128, 6, 'DATE'),
    ],
    'E898': [
        _f('satzart', 1, 4, 'AN'),
        _f('sequence_number', 5, 7, 'N'),
        _f('provider_key', 12, 2, 'AN'),
        _f('provider_reference', 14, 18, 'AN'),
        _f('internal_reference', 32, 20, 'AN'),
        _f('billing_sequence_flag', 52, 1, 'AN'),
        _f('document_path', 53, 56, 'AN'),
        _f('document_sequence_number', 109, 3, 'N'),
        _f('period_end_date', 112, 6, 'DATE'),
        _f('document_type', 118, 3, 'AN'),
    ],
    'P': [
        _f('satzart', 1, 1, 'AN'),
        _f('arge_version', 2, 5, 'AN'),
        _f('customer_number', 7, 10, 'N'),
        _f('provider_key', 17, 2, 'AN'),
        _f('provider_reference', 19, 13, 'N'),
        _f('internal_reference', 32, 20, 'AN'),
        _f('period_end_date', 52, 6, 'DATE'),
        _f('cost_type_key', 58, 3, 'N'),
        _f('total_amount_gross', 61, 10, 'DEC', 2),
        _f('total_amount_net', 71, 10, 'DEC', 2),
        _f('user_share_amount', 81, 10, 'DEC', 2),
        _f('user_share_percent', 91, 5, 'DEC', 2),
    ],
}


def pack_value(value, spec):
    if spec.kind == 'AN':
        text = '' if value is None else str(value)
        return text[:spec.length].ljust(spec.length)
    if spec.kind == 'DATE':
        if value is None:
            return ' ' * spec.length
        return value.strftime('%d%m%y')
    if spec.kind in ('N', 'DEC'):
        if value is None:
            return '0' * spec.length
        if spec.kind == 'DEC' and spec.decimals:
            scaled = int((Decimal(value) * (Decimal(10) ** spec.decimals))
                .quantize(Decimal(1), rounding=ROUND_HALF_UP))
        else:
            scaled = int(value)
        negative = scaled < 0
        digits = str(abs(scaled)).rjust(
            spec.length - (1 if negative else 0), '0')
        text = ('-' + digits) if negative else digits
        return text[-spec.length:].rjust(spec.length, '0')
    raise ValueError('Unknown field kind %r for %s' % (spec.kind, spec.name))


def unpack_value(raw, spec):
    raw = raw[:spec.length]
    if spec.kind == 'AN':
        return raw.rstrip()
    if spec.kind == 'DATE':
        raw = raw.strip()
        if not raw or raw == '0' * len(raw):
            return None
        try:
            return datetime.datetime.strptime(raw, '%d%m%y').date()
        except ValueError:
            return None
    if spec.kind in ('N', 'DEC'):
        raw = raw.strip()
        if not raw:
            return None
        negative = raw.startswith('-')
        digits = raw.lstrip('-').strip() or '0'
        num = int(digits)
        if negative:
            num = -num
        if spec.kind == 'DEC' and spec.decimals:
            return Decimal(num).scaleb(-spec.decimals)
        return num
    raise ValueError('Unknown field kind %r for %s' % (spec.kind, spec.name))


def pack(record_type, values):
    """Build one fixed-width BVED record line for record_type from values
    (dict of field name -> python value). Missing satzart/satzende/
    arge_version are filled in from DEFAULTS."""
    specs = RECORD_SPECS[record_type]
    length = RECORD_LENGTHS[record_type]
    merged = dict(DEFAULTS.get(record_type, {}))
    merged.update(values)
    buf = [' '] * length
    for spec in specs:
        text = pack_value(merged.get(spec.name), spec)
        buf[spec.start - 1:spec.start - 1 + spec.length] = list(text)
    return ''.join(buf)


def unpack(record_type, line):
    """Parse one fixed-width BVED record line of record_type into a dict of
    field name -> typed python value (str/int/Decimal/date)."""
    specs = RECORD_SPECS[record_type]
    result = {}
    for spec in specs:
        raw = line[spec.start - 1:spec.start - 1 + spec.length]
        result[spec.name] = unpack_value(raw, spec)
    return result


def bved_filename(record_type, when):
    """DTxxxx_JJJJMMTThhmmssSSS.DAT per the BVED file naming convention."""
    prefix = FILE_PREFIX[record_type]
    stamp = when.strftime('%Y%m%d%H%M%S') + ('%03d' % (when.microsecond // 1000))
    return '%s_%s.DAT' % (prefix, stamp)


def as_selection(table):
    """Turn a {code: label} table into a sorted [(code, "code - label")]
    list suitable for a Tryton Selection field."""
    return sorted(
        ((code, '%s - %s' % (code, label)) for code, label in table.items()),
        key=lambda item: item[0])


def get_fuel_unit(code):
    """Return the unit text embedded in a Tabelle B label, e.g. code '111'
    ("Leichtes Heizöl in Liter") -> "Liter". Empty string if the label has
    no " in " unit suffix (e.g. "Erdwärme")."""
    label = TABLE_B.get(code, '')
    if ' in ' in label:
        return label.rsplit(' in ', 1)[1]
    return ''


# --- Anhang 2: Referenzierte Schlüsseltabellen (Version 3.10) ---

TABLE_K = {
    '050': 'Arbeitspreis Raumheizung',
    '051': 'Netzverlust Raumheizung',
    '052': 'Grundpreis Raumheizung',
    '053': 'Mengenpreis Raumheizung',
    '054': 'Eichgebühr Raumheizung',
    '055': 'Umweltschutzkosten Raumheizung',
    '056': 'Strom- und Regelkosten Raumheizung',
    '057': 'Anschaffungskosten Messeinrichtungen Raumheizung',
    '058': 'Servicekosten der Messdienstfirma Raumheizung',
    '059': 'Arbeitspreis Warmwasser',
    '060': 'Grundpreis Warmwasser',
    '061': 'Mengenpreis Warmwasser',
    '062': 'Eichgebühr Warmwasser',
    '063': 'Umweltschutzkosten Warmwasser',
    '064': 'Strom- und Regelkosten Warmwasser',
    '065': 'Anschaffungskosten Messeinrichtungen Warmwasser',
    '066': 'Servicekosten der Messdienstfirma Warmwasser',
    '067': 'Dienstleistung',
    '068': 'Gerätevertrag Miete',
    '069': 'Gerätevertrag Wartung',
    '070': 'Sonstige Leistungen',
    '200': 'Anfangsstand',
    '201': 'Lieferung / Rechnung',
    '202': 'Restbestand',
    '203': 'Brennstoffverbrauch',
    '220': 'Betriebsstrom',
    '221': 'Wartungskosten',
    '222': 'Bedienungskosten',
    '223': 'Reinigungskosten',
    '224': 'Immissionsmessung',
    '225': 'Kaminfeger',
    '226': 'Tankreinigung',
    '227': 'Servicekosten der Messdienstfirma',
    '228': 'variables Textfeld HZG + WW',
    '229': 'Brennerwartung',
    '230': 'Gesamtkosten',
    '231': 'Kosten HZG + WW',
    '232': 'Kaltwasser für Warmwasser, Währungseinheit/Gesamt',
    '233': 'Kaltwasser für Warmwasser, Währungseinheit/m³',
    '234': 'Kosten HZG',
    '235': 'Kosten WW',
    '236': 'Kosten Frisch- und Abwasser',
    '237': 'Kosten Frischwasser',
    '238': 'Kosten Abwasser',
    '239': 'Kosten Oberflächenentwässerung',
    '240': 'Kaltwasser Betrag',
    '241': 'Kaltwasser Preis/m³',
    '242': 'variables Textfeld BKA',
    '243': 'Eichgebühr Kaltwasser',
    '244': 'Kaltwasser, Abwasser und weitere (sonstige kalte) Betriebskosten',
    '245': 'Frisch- und Abwasser Preis/m³',
    '246': 'Abwasser Preis/m³',
    '247': 'Trinkwasserprüfung',
    '248': 'Wartung Kaltwasserbereich (z. B. Wasserfilter)',
    '249': 'Kanalgebühr',
    '250': 'Zwischenablesung',
    '251': 'Kosten Nutzerwechsel',
    '252': 'Kosten Schätzung',
    '253': 'Kosten MwSt-Errechnung',
    '254': 'variables Textfeld direktzugeordnete Nebenkosten',
    '255': 'Zusätzlicher Ablesetermin',
    '256': 'Zwischenablese- und Nutzerwechselkosten',
    '257': 'Summe Sonderkosten',
    '258': 'Direktkosten (Nutzer)',
    '259': 'Weitere Betriebskosten',
    '260': 'Nicht umlagefähige Kosten',
    '300': 'Gerätemiete Heizkostenverteiler',
    '301': 'Gerätemiete Warmwasserzähler',
    '302': 'Gerätemiete Wärmemengenzähler',
    '303': 'Gerätemiete Kaltwasserzähler',
    '304': 'Verbrauchsanalyse',
    '305': 'Gerätewartung Warmwasserzähler',
    '306': 'Gerätewartung Wärmemengenzähler',
    '307': 'Gerätewartung Kaltwasserzähler',
    '308': 'Gerätemiete Rauchwarnmelder',
    '309': 'Gerätewartung Rauchwarnmelder',
    '310': 'Funktionsprüfung Rauchwarnmelder',
    '311': 'variables Textfeld Rauchwarnmelder',
    '400': 'Allgemeinstrom (nur Hausnebenkosten/Betriebskosten)',
    '901': 'Preisbremse Erdgas/Wärme (nach EWPBG)',
    '902': 'Staatliche Hilfe Öl/Pellets/Flüssiggas',
    '910': 'Preisbremse Strom/Heizenergie (nach StromPBG)',
    '911': 'Preisbremse Strom/Betriebsstrom (nach StromPBG)',
    '912': 'Preisbremse Strom/Allgemeinstrom (nach StromPBG)',
}

TABLE_L = {
    '00': 'keine steuerliche Leistungsart',
    '11': 'Haushaltsnahe geringfügige Beschäftigungsverhältnisse, § 35a Abs. 1 EStG',
    '12': 'Haushaltsnahe Beschäftigungsverhältnisse, nicht unter Abs. 1 oder 3, § 35a Abs. 2 EStG',
    '13': 'Handwerkerleistungen, § 35a Abs. 3 EStG',
}

# InvoiceLine.estg_35a ('', 'abs1', 'abs2', 'abs3') -> Tabelle L key.
ESTG35A_TO_TABLE_L = {
    '': '00',
    'abs1': '11',
    'abs2': '12',
    'abs3': '13',
}

TABLE_B = {
    '111': 'Leichtes Heizöl in Liter',
    '112': 'Leichtes Heizöl in kg',
    '119': 'Leichtes Heizöl lt. Uhr',
    '122': 'Koks in kg',
    '123': 'Holzpellets in kg',
    '124': 'Holzpellets in Tonnen',
    '125': 'Holzpellets in kWh',
    '133': 'Erdgas L (leicht) in m³',
    '134': 'Erdgas L (leicht) in kWh',
    '135': 'Erdgas L (leicht) in MWh',
    '136': 'Erdgas L (leicht) in GJ',
    '142': 'Nahwärme in kWh',
    '143': 'Nahwärme in MWh',
    '144': 'Fernwärme in kWh',
    '145': 'Fernwärme in MWh',
    '146': 'Fernwärme in GJ',
    '147': 'Fernwärme in Tonnen',
    '148': 'Fernwärme in m³',
    '151': 'Flüssiggas in Liter',
    '152': 'Flüssiggas in kg',
    '153': 'Flüssiggas in m³',
    '154': 'Flüssiggas in kWh',
    '164': 'Strom in kWh',
    '165': 'Strom in MWh',
    '173': 'Kokereigas in m³',
    '174': 'Kokereigas in kWh',
    '175': 'Kokereigas in MWh',
    '176': 'Kokereigas in GJ',
    '193': 'Erdgas H (schwer) in m³',
    '194': 'Erdgas H (schwer) in kWh',
    '195': 'Erdgas H (schwer) in MWh',
    '196': 'Erdgas H (schwer) in GJ',
    '197': 'Holz in Ster',
    '198': 'Holz (lufttrocken) in kg',
    '199': 'Holzhackschnitzel in SRm',
    '200': 'Erdwärme',
    '201': 'Schweres Heizöl in Liter',
    '202': 'Braunkohle in kg',
    '203': 'Steinkohle in kg',
    '204': 'Bio-Gas in m³',
    '205': 'Bio-Gas in kWh',
    '206': 'Strom für Wärmepumpe in kWh',
    '207': 'Strom für Wärmepumpe in MWh',
    '208': 'Strom für Wärmepumpe in GJ',
    '209': 'Solar-Energie in kWh',
    '211': 'Holzhackschnitzel in kg',
}

TABLE_G = {
    '400': 'Heizkostenverteiler nach dem Verdunstungsprinzip',
    '401': 'Elektronische Heizkostenverteiler',
    '402': 'Wärmezähler gesamt für Heizung und Warmwasser',
    '403': 'Kaltwasserzähler',
    '404': 'Warmwasserzähler',
    '405': 'Wärmezähler für Warmwasser',
    '406': 'Wärmezähler für Heizung',
    '407': 'Warmwasserkostenverteiler auf Verdunstungsbasis',
    '408': 'Warmwasserkostenverteiler nach mechanischem Prinzip',
    '409': 'Kondensatzähler Heizung',
    '410': 'Kondensatzähler Warmwasser',
    '411': 'Ölzähler',
    '412': 'Stromzähler',
    '413': 'Gaszähler',
    '414': 'Rohrwärmeabgabe nach VDI 2077, Beiblatt (fiktives Gerät)',
}

TABLE_M = {
    '01': 'Braunkohle',
    '02': 'Steinkohle',
    '03': 'Erdöl/Heizöl',
    '04': 'Erdgas',
    '05': 'Kernenergie',
    '06': 'Erneuerbare Energien',
    '99': 'Sonstige',
}

TABLE_S = {
    '1': 'Schätzung',
    '2': 'Schätzung nach Vorjahr',
    '3': 'Schätzung nach Normwärmeleistung',
    '4': 'Schätzung nach Grundanteil (z. B. 1 WMZ pro Nutzeinheit)',
    '5': 'Teilschätzung',
    '6': 'Schätzung nach Fläche',
    '7': 'Schätzung nach vergleichbaren Zeiträumen',
    '8': 'Schätzung nach Durchschnittsverbrauch',
    '10': 'Nur Kostenlieferung',
    '11': 'Hauptablesung',
    '12': 'Zwischenablesung',
    '13': 'Aufteilung nach Tagen',
    '14': 'Aufteilung nach Gradtagen',
    '15': 'Schätzung nach vergleichbaren Räumen',
}

TABLE_E = {
    '001': 'GJ',
    '002': 'MWh',
    '003': 'm³',
    '004': 'kcal',
    '005': 'kWh',
    '010': 'm² Wohnfläche',
    '011': 'm² beheizte Wohnfläche',
    '012': 'm³ umbauter Raum',
    '014': 'm³ beheizter umbauter Wohnraum',
    '015': 'variables Textfeld für Schlüssel',
    '016': 'Miteigentumsanteil',
    '017': 'm² Nutzfläche',
    '020': 'Anschlusswert',
    '021': 'Zähler',
    '022': 'Wohnung',
    '023': 'Abrechnung',
    '030': 'Verbrauchseinheiten (VE)',
    '031': 'Verbrauchswerte',
    '032': 'Striche (Venturi)',
    '033': '1000 J/Sec.',
    '034': 'Personen x Monate',
    '035': 'Personen',
    '040': 'Prozent',
    '041': 'Jahr',
    '042': 'Monat',
    '043': 'Tage',
    '044': 'Gradtage',
    '045': '‰-Anteile',
    '046': 'Anzahl Rauchwarnmelder',
}
