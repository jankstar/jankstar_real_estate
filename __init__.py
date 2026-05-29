from trytond.pool import Pool

from . import base_object
from . import measurement
from . import address
from . import object_party
from . import contract_core
from . import contract_type
from . import contract_item
from . import contract_term
from . import contract_wizard
from . import sequence
from . import res
from . import party
from . import invoice
from . import account_configuration
from . import billing_unit
from . import settlement_unit
from . import settlement_result

__all__ = ['register']


def register():
    Pool.register(
        address.Address,
        measurement.MeasurementType,
        measurement.Measurement,
        base_object.BaseObject,
        base_object.BaseObjectEquipmentContext,
        base_object.BaseObjectCompanyContext,
        base_object.BaseObjectContext,
        base_object.BaseObjectOccupancy,
        base_object.BaseObjectOccupancyContext,
        base_object.MeterReading,
        object_party.ObjectPartyRole,
        object_party.ObjectParty,
        contract_core.ContractContext,
        contract_core.ContractLog,
        contract_core.ContractLogContext,
        contract_core.AccountContract,
        contract_core.GeneralLedgerAccountContract,
        contract_core.Contract,
        contract_type.ContractTypeTax,
        contract_type.ContractType,
        contract_type.ContractTermType,
        contract_item.ContractItem,
        contract_term.ContractTermTax,
        contract_term.ContractTermCashFlow,
        contract_term.ContractTermCashFlowContext,
        contract_term.ContractTerm,
        contract_wizard.CreateMovesStart,
        contract_wizard.TerminateContractStart,
        #sequence.Sequence,
        res.User,
        party.Party,
        invoice.Invoice,
        invoice.InvoiceLine,
        invoice.AccountMoveLine,
        account_configuration.AccountConfigurationRealEstate,
        account_configuration.AccountConfiguration,
        billing_unit.CostCategoryGroup,
        billing_unit.CostType,
        billing_unit.BillingUnitContext,
        billing_unit.BillingUnitLogContext,
        billing_unit.BillingUnit,
        billing_unit.BillingUnitLog,
        billing_unit.BillingUnitMoves,
        billing_unit.BillingUnitMovesContext,
        settlement_unit.SettlementUnitContext,
        settlement_unit.SettlementUnit,
        settlement_result.CostShareContext,
        settlement_result.SettlementResultContext,
        settlement_result.CostShare,
        settlement_result.SettlementResult,
        module='real_estate', type_='model')
    Pool.register(
        contract_wizard.CreateMoves,
        contract_wizard.TerminateContractWizard,
        module='real_estate', type_='wizard')
    Pool.register(
        base_object.BaseObjectReport,
        contract_wizard.ContractReport,
        contract_wizard.ContractAnnex4Report,
        module='real_estate', type_='report')
