*************
Source Layout
*************

.. code-block:: text

   real_estate/
   ├── __init__.py              # Pool registration of all models, wizards and reports
   ├── tryton.cfg               # module version, dependencies, XML data files
   ├── setup.py                 # packaging (jankstar_real_estate, trytond.modules entry point)
   ├── address.py               # real_estate.address
   ├── adjustment_run.py        # real_estate.contract.term.adjustment.run (adjustment
   │                            #   run, procedure registry, manual amount, consent)
   ├── base_object.py           # real_estate.base_object, occupancy, meter readings
   ├── billing_unit.py          # real_estate.billing_unit, billing_unit.moves,
   │                            #   billing_unit.log, cost_type, cost_category_group
   ├── billing_unit_wizard.py   # real_estate.billing_unit.wizard (batch billing)
   ├── bved.py                  # BVED Tryton models: service_provider, provider_assignment,
   │                            #   object_number, export, import(.line)
   ├── bved_records.py          # BVED fixed-width record (de)serialization, no Tryton dependency
   ├── co2_kostaufg.py          # real_estate.co2_kostaufg(.consumption), co2_emission_share
   ├── company.py               # extension to company.company (re_accounting link)
   ├── contract_comparative_rent.py  # comparative rent procedure (§ 558 BGB),
   │                            #   cap, consent, wizard Add Terms
   ├── contract_core.py         # real_estate.contract, contract.log, account views,
   │                            #   cron_daily dispatcher + cron task handlers
   ├── contract_index_rent.py   # index rent agreement and adjustments (§ 557b BGB)
   ├── contract_item.py         # real_estate.contract.item, contract.item.object
   ├── contract_party.py        # real_estate.contract.party, contract.party.role
   │                            #   (+ role-contract.type relation)
   ├── contract_term.py         # real_estate.contract.term, term.tax, cash_flow,
   │                            #   term.adjustment, Quantitative
   ├── contract_type.py         # real_estate.contract.type, term.type
   ├── contract_rent_adjustment.py  # real_estate.contract.rent_adjustment (rent
   │                            #   adjustments, graduated rent generation)
   ├── contract_report.py       # ContractReport, ContractAnnex4Report,
   │                            #   ContractTerminationConfirmationReport,
   │                            #   index declaration, comparative rent request
   ├── contract_wizard.py       # wizards: TerminateContract, CreateContractMoves,
   │                            #   CancelPeriodBooking, ContractRunning,
   │                            #   ChangeContractPartner
   ├── cron_task.py             # real_estate.cron_task (per-company scheduled task config)
   ├── handover.py              # real_estate.contract.handover(.line, .key, .meter),
   │                            #   handover.checklist(.line); process step conditions
   ├── inspection.py            # real_estate.inspection(.line, .result, .defect),
   │                            #   inspection.type, .plan, .checklist(.item),
   │                            #   equipment.kind; notice / access letter wizards
   │                            #   and reports, inspection report
   ├── invoice.py               # extensions to account.invoice / invoice.line /
   │                            #   move.line / general_ledger.line, receivable/payable
   │                            #   list context + report
   ├── ir.py                    # extension to ir.cron (registers the cron_daily method)
   ├── measurement.py           # real_estate.measurement.type, measurement
   ├── meter_reading_sheet.py   # real_estate.meter_reading.sheet(.line) and its report
   ├── object_party.py          # real_estate.object_party, object_party.role
   ├── option_rate.py           # real_estate.option_rate, option_rate.context
   ├── option_rate_wizard.py    # real_estate.option_rate_update.wizard
   ├── party.py                 # extension to party.party
   ├── price_index.py           # real_estate.price_index(.value), index_cap_rule
   ├── process.py               # real_estate.process.template(.step), process,
   │                            #   wizards Start Process / Execute Action, process
   │                            #   start hooks (termination, partner change)
   ├── re_accounting.py         # real_estate.re_accounting (company-scoped RE config)
   ├── rent_survey.py           # real_estate.rent_survey(.version, .dimension(.class),
   │                            #   .cell, .group, .feature, .calculation),
   │                            #   base_object.rent_survey_value, import/features wizards
   ├── res.py                   # extension to res.user
   ├── settlement_result.py     # real_estate.settlement_result, cost_share
   ├── sequence.py              # extension to ir.sequence ("string timestamp" type)
   ├── settlement_unit.py       # real_estate.settlement_unit
   ├── task.py                  # real_estate.task.type, task (follow-ups), wizards
   │                            #   Postpone / Create Task, task tabs on records
   ├── task_rule.py             # real_estate.task.rule (scheduled task rules)
   ├── report/                  # ODT report templates (rendered via Genshi/relatorio)
   ├── view/                    # XML form and tree view definitions
   ├── wowi/                    # German WoWi accounting templates
   ├── tests/                   # unit tests (test_module.py) and demo data scripts
   ├── doc/                     # this documentation (Sphinx)
   └── locale/                  # Translations (de.po)
