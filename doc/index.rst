Real Estate Module for Tryton
##############################

A Tryton ERP module for real estate management. Packaged as ``jankstar_real_estate``,
targeting Tryton 8.0.0 and Python 3.9–3.13.

Covers property management, lease and sales contracts, tenant/owner party roles,
operating cost settlement, CO2 cost allocation under the German CO2KostAufG,
and a German "Kontenrahmen der Wohnungswirtschaft" (WoWi) accounting chart.

Full documentation (Configuration, Access Control, Data Model, Wizards,
Reports, …) is split into per-topic pages under ``doc/`` — see *Contents*
below.

| ISO_4217 Currency https://de.wikipedia.org/wiki/ISO_4217
| ISO_3166 Country Codes https://www.laenderdaten.de/kuerzel/iso_3166-1.aspx
|

This module was developed with the support of AI cloude code — all requirements,
specifications, tests, corrections, and optimizations were carried out by
human contributors.

Contents
========

.. note::
   The links below are absolute GitHub URLs, not relative paths — this
   file is also displayed as the repository's ``README.rst`` via a
   symlink at the repo root, and GitHub resolves relative links against
   *that* location, not against ``doc/`` where the target files actually
   live; a plain relative link (e.g. ``module_dependencies.rst``) 404s
   when opened from the root-level README. Absolute URLs work correctly
   from both places (and also from PyPI's rendered description).

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
