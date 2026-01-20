from trytond.pool import Pool

from . import base_object
from . import measurement
from . import address 
from . import object_party
from . import contract
from . import sequence
from . import res
from . import party

__all__ = ['register']


def register():
    Pool.register(
        address.Address,
        measurement.MeasurementType,
        measurement.Measurement,
        base_object.BaseObject,
        object_party.ObjectPartyRole,
        object_party.ObjectParty,
        contract.ContractType,
        contract.ContractTypeTax,
        contract.ContractTerm,
        contract.ContractTermTax,
        contract.ContractTermLine,
        contract.ContractTermType,
        contract.ContractItem,
        contract.Contract,
        #sequence.Sequence,
        res.User,
        party.Party,
        module='real_estate', type_='model')
    Pool.register(
        module='real_estate', type_='wizard')
    Pool.register(
        base_object.BaseObjectReport,
        contract.ContractReport,
        module='real_estate', type_='report')
