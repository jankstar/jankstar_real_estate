"Stand-ins shared by the module tests of several areas"
import datetime
from decimal import Decimal


class _StubNamed:
    "Minimal duck-typed stand-in for a record with a .name/.symbol attribute"

    def __init__(self, name=None, symbol=None):
        self.name = name
        self.symbol = symbol


class _StubSettlementUnit:
    "Minimal duck-typed stand-in for a real_estate.settlement_unit record"

    def __init__(self, allocation_rule=None, m_type=None, meter_unit=None):
        self.allocation_rule = allocation_rule
        self.m_type = m_type
        self.meter_unit = meter_unit


class _StubRecord:
    "Generic duck-typed stand-in for a record: attributes from keywords"

    def __init__(self, **values):
        self.__dict__.update(values)


def _stub_term(term_type=None, payment_term=None):
    return _StubRecord(term_type=term_type, payment_term=payment_term)


def _stub_contract(Contract, invoice_type='out', payment_term=None,
        party=None):
    "Stand-in for a contract that borrows the real periodic posting helpers"
    contract = type('_StubContract', (), {
            '_move_term_type': staticmethod(Contract._move_term_type),
            '_move_group_key': classmethod(
                Contract._move_group_key.__func__),
            '_move_description': Contract._move_description,
            'get_move_payment_term': Contract.get_move_payment_term,
            })()
    contract.c_type = _StubRecord(
        mark='WM', name='Wohnungsmiete', invoice_type=invoice_type)
    contract.payment_term = payment_term
    contract.contractual_partner = party
    return contract


def _stub_index_agreement(RentAdjustment, values, quantity=Decimal(1),
        unit_price=Decimal('800.00'), residential=True, **kwargs):
    """Stand-in for an active index rent agreement that borrows the real
    calculation of RentAdjustment (values: {month: index value})."""
    index = _StubRecord(id=1, base_year=2020, rec_name='VPI-DE')
    index.get_value = lambda month: (_StubRecord(value=values[month])
        if month in values else None)
    term = _StubRecord(id=10, quantity=quantity, unit_price=unit_price,
        graduated_locked=False, rec_name='Miete', get_booked_to=lambda: None)
    contract = _StubRecord(state='running',
        currency=_StubRecord(digits=2), property=None,
        company=_StubRecord(re_accounting=_StubRecord(receipt_days=3)),
        rec_name='Vertrag', get_effective_end_date=lambda: None)
    agreement = type('_StubIndexRent', (), {
            'compute_index_adjustment':
                RentAdjustment.compute_index_adjustment,
            'planned_valid_from': RentAdjustment.planned_valid_from,
            '_receipt_days': RentAdjustment._receipt_days,
            '_declaration_deadline': RentAdjustment._declaration_deadline,
            })()
    agreement.__dict__.update({
            'id': 5, 'price_index': index, 'current_term': term,
            'procedure': 'index_rent', 'state': 'active',
            'contract': contract, '_residential': residential,
            'current_index_month': datetime.date(2025, 1, 1),
            'next_possible_date': datetime.date(2026, 3, 1),
            'threshold_type': 'none', 'threshold_value': None,
            'apply_cap': 'never', 'effective_rule': 'statutory',
            'effective_offset_months': None,
            })
    agreement.__dict__.update(kwargs)
    return agreement
