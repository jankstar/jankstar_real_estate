*************
Source Layout
*************

.. code-block:: text

   real_estate/
   ├── __init__.py              # Pool registration of all models, wizards and reports
   ├── tryton.cfg               # module version, dependencies, XML data files
   ├── address.py               # real_estate.address
   ├── base_object.py           # real_estate.base_object, occupancy, meter readings
   ├── billing_unit.py          # real_estate.billing_unit, billing_unit.moves,
   │                            #   billing_unit.log, cost_type, cost_category_group
   ├── billing_unit_wizard.py   # real_estate.billing_unit.wizard (batch billing)
   ├── bved.py                  # BVED Tryton models: service_provider, provider_assignment,
   │                            #   object_number, export, import(.line)
   ├── bved_records.py          # BVED fixed-width record (de)serialization, no Tryton dependency
   ├── co2_kostaufg.py          # real_estate.co2_kostaufg(.consumption), co2_emission_share
   ├── company.py               # extension to company.company (re_accounting link)
   ├── contract_core.py         # real_estate.contract, contract.log, account views,
   │                            #   cron_daily dispatcher + cron task handlers
   ├── contract_item.py         # real_estate.contract.item, contract.item.object
   ├── contract_party.py        # real_estate.contract.party, contract.party.role
   │                            #   (+ role-contract.type relation)
   ├── contract_term.py         # real_estate.contract.term, term.tax, cash_flow,
   │                            #   term.adjustment, Quantitative
   ├── contract_type.py         # real_estate.contract.type, term.type
   ├── contract_report.py       # ContractReport, ContractAnnex4Report,
   │                            #   ContractTerminationConfirmationReport
   ├── contract_wizard.py       # wizards: TerminateContract, CreateContractMoves,
   │                            #   CancelPeriodBooking, ContractRunning,
   │                            #   ContractTermAdjustment, ChangeContractPartner
   ├── cron_task.py             # real_estate.cron_task (per-company scheduled task config)
   ├── invoice.py               # extensions to account.invoice / invoice.line /
   │                            #   move.line / general_ledger.line, receivable/payable
   │                            #   list context + report
   ├── ir.py                    # extension to ir.cron (registers the cron_daily method)
   ├── measurement.py           # real_estate.measurement.type, measurement
   ├── object_party.py          # real_estate.object_party, object_party.role
   ├── option_rate.py           # real_estate.option_rate, option_rate.context
   ├── option_rate_wizard.py    # real_estate.option_rate_update.wizard
   ├── party.py                 # extension to party.party
   ├── re_accounting.py         # real_estate.re_accounting (company-scoped RE config)
   ├── res.py                   # extension to res.user
   ├── settlement_result.py     # real_estate.settlement_result, cost_share
   ├── sequence.py              # extension to ir.sequence ("string timestamp" type)
   ├── settlement_unit.py       # real_estate.settlement_unit
   ├── report/                  # ODT report templates (rendered via Genshi/relatorio)
   ├── view/                    # XML form and tree view definitions
   ├── wowi/                    # German WoWi accounting templates
   └── locale/                  # Translations (de.po)
