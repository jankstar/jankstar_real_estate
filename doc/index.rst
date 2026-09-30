Real Estate Module for Tryton
##############################

A Tryton ERP module for real estate management. Packaged as ``jankstar_real_estate``,
targeting Tryton 8.0.0 and Python 3.9–3.13.

Covers property management, lease and sales contracts, tenant/owner party roles,
operating cost settlement, CO2 cost allocation under the German CO2KostAufG,
and a German "Kontenrahmen der Wohnungswirtschaft" (WoWi) accounting chart.

Structure
=========

- **Master data** — real-estate objects in a tree (property → building →
  apartment/commercial unit/parking, equipment such as meters), addresses,
  measurements (areas, rooms, meter readings), occupancy, and party roles
  per object.
- **Contracts** — contract types, contract parties with roles and validity
  periods, items (rented objects) and terms (recurring charges such as rent
  and operating cost advances); terms generate a planned cash flow that is
  booked as invoices via the *Create Contract Moves* wizard or a cron task.
  Rent adjustments per term (graduated rent generated in advance; index,
  comparative rent, modernisation and operating cost procedures as
  headers).
- **Operating cost settlement** — billing units and settlement units
  allocate supplier invoice costs to contracts (by measurement,
  consumption, external billing, …), including CO2 cost allocation
  (CO2KostAufG) and the BVED interface to external metering providers.
- **Accounting** — German WoWi chart of accounts, company-specific
  real-estate accounting configuration, input VAT option rate, and
  real-estate fields on invoices and journal lines.

Full documentation is split into per-topic pages under ``doc/`` — see
*Contents* below and *Source Layout* for the file-to-model mapping.

| ISO_4217 Currency https://de.wikipedia.org/wiki/ISO_4217
| ISO_3166 Country Codes https://www.laenderdaten.de/kuerzel/iso_3166-1.aspx
|

This module was developed with the support of Claude Code — all requirements,
specifications, tests, corrections, and optimizations were carried out by
human contributors.

Contents
========

..
   The links below are absolute GitHub URLs because this file is also
   shown as the repository's root README.rst (symlink) and on PyPI.

- `Module Dependencies <https://github.com/jankstar/jankstar_real_estate/blob/main/doc/module_dependencies.rst>`_
- `Installation <https://github.com/jankstar/jankstar_real_estate/blob/main/doc/installation.rst>`_
- `Configuration <https://github.com/jankstar/jankstar_real_estate/blob/main/doc/configuration.rst>`_
- `Access Control <https://github.com/jankstar/jankstar_real_estate/blob/main/doc/access_control.rst>`_
- `Data Model <https://github.com/jankstar/jankstar_real_estate/blob/main/doc/data_model.rst>`_

  - `Property Management <https://github.com/jankstar/jankstar_real_estate/blob/main/doc/property_management.rst>`_
  - `Contract Management <https://github.com/jankstar/jankstar_real_estate/blob/main/doc/contract_management.rst>`_
  - `Operating Cost Settlement <https://github.com/jankstar/jankstar_real_estate/blob/main/doc/operating_cost_settlement.rst>`_
  - `CO2 Cost Allocation (CO2KostAufG) <https://github.com/jankstar/jankstar_real_estate/blob/main/doc/co2_kostaufg.rst>`_
  - `BVED External Billing Interface <https://github.com/jankstar/jankstar_real_estate/blob/main/doc/bved.rst>`_
  - `Option Rate (Input VAT Deduction) <https://github.com/jankstar/jankstar_real_estate/blob/main/doc/option_rate.rst>`_
  - `Extensions to Core Modules <https://github.com/jankstar/jankstar_real_estate/blob/main/doc/core_extensions.rst>`_

- `Wizards <https://github.com/jankstar/jankstar_real_estate/blob/main/doc/wizards.rst>`_
- `Reports <https://github.com/jankstar/jankstar_real_estate/blob/main/doc/reports.rst>`_
- `Accounting / WoWi <https://github.com/jankstar/jankstar_real_estate/blob/main/doc/accounting_wowi.rst>`_
- `Source Layout <https://github.com/jankstar/jankstar_real_estate/blob/main/doc/source_layout.rst>`_
- `Running Tests <https://github.com/jankstar/jankstar_real_estate/blob/main/doc/testing.rst>`_

  - `Demo data scripts <https://github.com/jankstar/jankstar_real_estate/blob/main/doc/demo_data_scripts.rst>`_

- `Release notes <https://github.com/jankstar/jankstar_real_estate/blob/main/doc/releases.rst>`_

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
