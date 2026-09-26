Real Estate Module for Tryton
##############################

A Tryton ERP module for real estate management. Packaged as ``jankstar_real_estate``,
targeting Tryton 8.0.0 and Python 3.9–3.13.

Covers property management, lease and sales contracts, tenant/owner party roles,
operating cost settlement, CO2 cost allocation under the German CO2KostAufG,
and a German "Kontenrahmen der Wohnungswirtschaft" (WoWi) accounting chart.

Full documentation (Configuration, Access Control, Data Model, Wizards,
Reports, …) is split into per-topic pages under
https://github.com/jankstar/jankstar_real_estate/tree/main/doc — the
*Contents* list below links each one directly; on GitHub these links are
clickable, but they only resolve when browsing the repository itself (as
plain links to local ``.rst`` files, not against this URL).

| ISO_4217 Currency https://de.wikipedia.org/wiki/ISO_4217
| ISO_3166 Country Codes https://www.laenderdaten.de/kuerzel/iso_3166-1.aspx
|

This module was developed with the support of AI cloude code — all requirements,
specifications, tests, corrections, and optimizations were carried out by
human contributors.

Contents
========

- `Module Dependencies <module_dependencies.rst>`_
- `Installation <installation.rst>`_
- `Configuration <configuration.rst>`_
- `Access Control <access_control.rst>`_
- `Data Model <data_model.rst>`_

  - `Property Management <property_management.rst>`_
  - `Contract Management <contract_management.rst>`_
  - `Operating Cost Settlement <operating_cost_settlement.rst>`_
  - `CO2 Cost Allocation (CO2KostAufG) <co2_kostaufg.rst>`_
  - `BVED External Billing Interface <bved.rst>`_
  - `Option Rate (Input VAT Deduction) <option_rate.rst>`_
  - `Extensions to Core Modules <core_extensions.rst>`_

- `Wizards <wizards.rst>`_
- `Reports <reports.rst>`_
- `Accounting / WoWi <accounting_wowi.rst>`_
- `Source Layout <source_layout.rst>`_
- `Running Tests <testing.rst>`_

  - `Demo data scripts <demo_data_scripts.rst>`_

- `Release notes <releases.rst>`_

.. toctree::
   :hidden:
   :maxdepth: 2

   module_dependencies
   installation
   configuration
   access_control
   data_model
   property_management
   contract_management
   operating_cost_settlement
   co2_kostaufg
   bved
   option_rate
   core_extensions
   wizards
   reports
   accounting_wowi
   source_layout
   testing
   demo_data_scripts
   releases
