*************
Source Layout
*************

The module is one Tryton module ``real_estate``. Its Python files and data
XML are grouped in six area folders; each folder has an empty
``__init__.py`` and imports nothing itself. All models, wizards and reports
are registered centrally in ``__init__.py`` of the module
(``from .contract import contract_core`` …, ``Pool.register(...)``);
``tryton.cfg`` lists the data XML with their folder. Views lie under
``view/<area>/`` and the ``name`` of the ``ir.ui.view`` record contains the
folder (``contract/contract_form``). A view lies in the folder of the area
whose data XML creates it.

New files go into the folder of their area, new views into
``view/<area>/``; nothing new directly in the module folder or in ``view/``.
Where a file belongs:

- **G1** - files that essentially extend Tryton standard models go to
  ``core/`` (e.g. ``invoice.py``); a single extension class that is part of
  an area program stays with that program.
- **G2** - programs that belong together lie together; the technical
  connection decides, not the business area (the year-end closing is a
  process template and lies in ``tasks/``).
- **G3** - a program and its data XML (views, actions, wizards, reports)
  lie together (``core/invoice.py`` with ``core/invoice.xml``).

.. code-block:: text

   real_estate/
   ├── __init__.py                  # Pool registration of all models, wizards and reports
   ├── tryton.cfg                   # module version, dependencies, XML data files
   ├── setup.py                     # packaging (jankstar_real_estate, trytond.modules entry point)
   ├── core/                        # extensions of standard models, helpers, groups and access, messages
   │   ├── __init__.py              # empty
   │   ├── basic_de.xml
   │   ├── company.py               # extension to company.company (re_accounting link)
   │   ├── group_account_view.xml
   │   ├── group_party_access.xml
   │   ├── group_real_estate_view.xml
   │   ├── invoice.py               # extensions to account.invoice / invoice.line /
   │   │                            #   move.line / general_ledger.line, receivable/payable
   │   │                            #   list context + report
   │   ├── invoice.xml
   │   ├── ir.py                    # extension to ir.cron (registers the cron_daily method)
   │   ├── message.xml
   │   ├── party.py                 # extension to party.party
   │   ├── party.xml
   │   ├── queue_tools.py           # queued_ids(): records waiting in ir.queue (no double
   │   │                            #   start of background jobs)
   │   ├── re_accounting.py         # real_estate.re_accounting (company-scoped RE config)
   │   ├── re_accounting.xml
   │   ├── res.py                   # extension to res.user
   │   ├── res.xml
   │   └── sequence.py              # extension to ir.sequence ("string timestamp" type)
   ├── base/                        # master data
   │   ├── __init__.py              # empty
   │   ├── address.py               # real_estate.address
   │   ├── address.xml
   │   ├── base_object.py           # real_estate.base_object, occupancy, meter readings
   │   ├── base_object.xml
   │   ├── measurement.py           # real_estate.measurement.type, measurement
   │   ├── measurement.xml
   │   ├── meter_reading_sheet.py   # real_estate.meter_reading.sheet(.line) and its report
   │   ├── meter_reading_sheet.xml
   │   ├── object_party.py          # real_estate.object_party, object_party.role
   │   ├── object_party.xml
   │   ├── option_rate.py           # real_estate.option_rate, option_rate.context
   │   ├── option_rate.xml
   │   └── option_rate_wizard.py    # real_estate.option_rate_update.wizard
   ├── contract/                    # contract management
   │   ├── __init__.py              # empty
   │   ├── contract.xml
   │   ├── contract_core.py         # real_estate.contract, contract.log, account views,
   │   │                            #   cron_daily dispatcher + cron task handlers
   │   ├── contract_item.py         # real_estate.contract.item, contract.item.object
   │   ├── contract_party.py        # real_estate.contract.party, contract.party.role
   │   │                            #   (+ role-contract.type relation)
   │   ├── contract_party.xml
   │   ├── contract_report.py       # ContractReport, ContractAnnex4Report,
   │   │                            #   ContractTerminationConfirmationReport,
   │   │                            #   index declaration, comparative rent request
   │   ├── contract_term.py         # real_estate.contract.term, term.tax, cash_flow,
   │   │                            #   term.adjustment, Quantitative
   │   ├── contract_type.py         # real_estate.contract.type, term.type
   │   └── contract_wizard.py       # wizards: TerminateContract, CreateContractMoves,
   │                                #   CancelPeriodBooking, ContractRunning,
   │                                #   ChangeContractPartner
   ├── rent_adjustment/             # rent adjustments
   │   ├── __init__.py              # empty
   │   ├── adjustment_run.py        # real_estate.contract.term.adjustment.run (adjustment
   │   │                            #   run, procedure registry, manual amount, consent)
   │   ├── adjustment_run.xml
   │   ├── contract_comparative_rent.py # comparative rent procedure (§ 558 BGB),
   │   │                            #   cap, consent, wizard Add Terms
   │   ├── contract_index_rent.py   # index rent agreement and adjustments (§ 557b BGB)
   │   ├── contract_modernisation.py # modernisation procedure of the adjustment
   │   │                            #   run (§§ 559-559e BGB), increase declaration
   │   ├── contract_rent_adjustment.py # real_estate.contract.rent_adjustment (rent
   │   │                            #   adjustments, graduated rent generation)
   │   ├── contract_rent_adjustment.xml
   │   ├── modernisation.py         # real_estate.modernisation(.cost, .fund, .unit,
   │   │                            #   .rule), allocation functions, announcement
   │   │                            #   letter, invoice line link
   │   ├── modernisation.xml
   │   ├── price_index.py           # real_estate.price_index(.value), index_cap_rule
   │   ├── price_index.xml
   │   ├── rent_survey.py           # real_estate.rent_survey(.version, .dimension(.class),
   │   │                            #   .cell, .group, .feature, .calculation),
   │   │                            #   base_object.rent_survey_value, import/features wizards
   │   ├── rent_survey.xml
   │   └── rent_survey_berlin.xml
   ├── operating_costs/             # operating costs
   │   ├── __init__.py              # empty
   │   ├── billing_unit.py          # real_estate.billing_unit, billing_unit.moves,
   │   │                            #   billing_unit.log, cost_type, cost_category_group
   │   ├── billing_unit.xml
   │   ├── billing_unit_wizard.py   # real_estate.billing_unit.wizard (batch billing)
   │   ├── bved.py                  # BVED Tryton models: service_provider, provider_assignment,
   │   │                            #   object_number, export, import(.line)
   │   ├── bved.xml
   │   ├── bved_records.py          # BVED fixed-width record (de)serialization, no Tryton dependency
   │   ├── co2_kostaufg.py          # real_estate.co2_kostaufg(.consumption), co2_emission_share
   │   ├── co2_kostaufg.xml
   │   ├── oc_document.py           # real_estate.oc_document(.line): operating cost
   │   │                            #   assignment, wizards update / history / split
   │   ├── oc_document.xml
   │   ├── oc_reclass.py            # pure functions of the cost reclassification
   │   │                            #   (property to rental objects)
   │   ├── oc_reconciliation.py     # real_estate.oc_reconciliation(.line) and its report
   │   ├── oc_reconciliation.xml
   │   ├── settlement_result.py     # real_estate.settlement_result, cost_share
   │   ├── settlement_result.xml
   │   ├── settlement_unit.py       # real_estate.settlement_unit
   │   └── settlement_unit.xml
   ├── tasks/                       # tasks, processes, inspections, handover
   │   ├── __init__.py              # empty
   │   ├── cron_task.py             # real_estate.cron_task (per-company scheduled task config)
   │   ├── cron_task.xml
   │   ├── fiscalyear_closing.py    # process template year_end_closing on the fiscal year,
   │   │                            #   done methods of its steps
   │   ├── fiscalyear_closing.xml
   │   ├── handover.py              # real_estate.contract.handover(.line, .key, .meter),
   │   │                            #   handover.checklist(.line); process step conditions
   │   ├── handover.xml
   │   ├── inspection.py            # real_estate.inspection(.line, .result, .defect),
   │   │                            #   inspection.type, .plan, .checklist(.item),
   │   │                            #   equipment.kind; notice / access letter wizards
   │   │                            #   and reports, inspection report
   │   ├── inspection.xml
   │   ├── process.py               # real_estate.process.template(.step), process,
   │   │                            #   wizards Start Process / Execute Action, process
   │   │                            #   start hooks (termination, partner change)
   │   ├── process.xml
   │   ├── task.py                  # real_estate.task.type, task (follow-ups), wizards
   │   │                            #   Postpone / Create Task, task tabs on records
   │   ├── task.xml
   │   ├── task_rule.py             # real_estate.task.rule (scheduled task rules)
   │   └── task_rule.xml
   ├── view/                        # XML form and tree view definitions in one folder
   │                                #   per area (core/ ... tasks/)
   ├── report/                      # ODT report templates (rendered via Genshi/relatorio)
   ├── icons/                       # SVG icons (ir.ui.icon)
   ├── wowi/                        # German WoWi accounting templates
   ├── tests/                       # unit tests (test_module.py) and demo data scripts
   ├── doc/                         # this documentation (Sphinx)
   └── locale/                      # Translations (de.po)
