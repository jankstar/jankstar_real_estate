from trytond.pool import Pool

from . import base_object
from . import measurement
from . import address 
from . import object_party
from . import contract
from . import sequence
from . import res
from . import party
from . import invoice

__all__ = ['register']


def register():
    Pool.register(
        address.Address,
        measurement.MeasurementType,
        measurement.Measurement,
        base_object.BaseObject,
        base_object.MeterReading,
        object_party.ObjectPartyRole,
        object_party.ObjectParty,
        contract.ContractType,
        contract.ContractTypeTax,
        contract.ContractTerm,
        contract.ContractTermTax,
        contract.ContractTermType,
        contract.ContractItem,
        contract.ContractLog,
        contract.ContractTermCashFlow,
        contract.Contract,
        contract.CreateMovesStart,
        #sequence.Sequence,
        res.User,
        party.Party,
        invoice.Invoice,
        invoice.InvoiceLine,
        module='real_estate', type_='model')
    Pool.register(
        contract.CreateMoves,
        module='real_estate', type_='wizard')
    Pool.register(
        base_object.BaseObjectReport,
        contract.ContractReport,
        module='real_estate', type_='report')
