*************
Configuration
*************

This page describes every master-data record that must exist before the
``real_estate`` module can be used productively.  Records marked
**[auto]** are created automatically when the module is installed via
``trytond-admin -u real_estate``.  All other records must be set up
manually or confirmed after installation.


SKR04 Chart of Accounts **[auto]**
===================================

The module ships a complete German SKR04 chart of accounts under
``skr04/``.  It is loaded automatically at installation and provides:

- Account types and accounts (e.g. 4120 Mieterträge, 1600 Forderungen)
- Tax groups, tax templates (7 % / 19 % MwSt.)
- Tax code templates and tax rule templates

After installation, open *Accounting → Configuration → Account Templates*
and apply the chart to your company (button *Create Chart of Account*) if
it has not been applied yet.

Rental Book Journal **[auto]**
-------------------------------

A journal named **Rental Book** (code ``RE``, type *Revenue*) is created
automatically.  It is used as the default posting journal for all contract
types.  If you prefer a different journal, you can change it on each
contract type individually.


Account Configuration
=====================

Open *Accounting → Configuration → Configuration* and fill in the
real-estate-specific defaults (added by this module via
``account_configuration.py``, model ``account.configuration.real_estate``):

``Vacancy Cost Account`` (``re_account_allocation_by_owner``)
   Account used for direct GL postings of vacancy settlement results
   (cost shares with no contract, i.e. the owner's share of unoccupied
   periods) — both the debit and credit side of the posting.

``Operating Cost Settlement Journal`` (``re_journal_billing``)
   Journal used for the vacancy GL postings above.

``Operating Cost Billing Payment Term`` (``re_payment_term_billing``)
   Default payment term for operating cost settlement invoices, used
   whenever the contract itself has no payment term set.

``Vacancy Cost Account`` and ``Operating Cost Settlement Journal`` are
required before vacancy results can be billed (see
``BillingUnit.billing_wizard`` / ``billing`` in ``billing_unit.py``); tenant
invoices are unaffected and use the contract's own accounts/journal.


Use Classes **[auto]**
======================

Six use classes are loaded automatically:

.. list-table::
   :header-rows: 1
   :widths: 10 30 15 15

   * - Seq.
     - Name
     - Basement No.
     - Parking No.
   * - 10
     - Apartment
     - yes
     - —
   * - 20
     - Office
     - yes
     - —
   * - 30
     - Retail
     - yes
     - —
   * - 40
     - Warehouse
     - yes
     - —
   * - 50
     - Parking
     - —
     - yes
   * - 60
     - Garage
     - —
     - yes

Additional classes can be created under
*Real Estate → Configuration → Use Classes* without changing any code.
The ``has_basement_nr`` / ``has_parking_nr`` flags control which extra
fields appear on the rental-object form.


Measurement Types **[auto]**
=============================

The following measurement types are loaded automatically:

.. list-table::
   :header-rows: 1
   :widths: 10 35 15 20 10

   * - Seq.
     - Name
     - Unit
     - Applies to
     - Group
   * - 05
     - Usable Space
     - m²
     - object
     - yes (root)
   * - 10
     - Living Space
     - m²
     - object
     - child of *Usable Space*
   * - 15
     - Commercial Space
     - m²
     - object
     - child of *Usable Space*
   * - 20
     - Number of rooms
     - unit
     - object
     - —
   * - 30
     - Gross floor area
     - m²
     - building
     - —
   * - 40
     - Land area
     - m²
     - land
     - —
   * - 50
     - Number of items
     - unit
     - equipment
     - —
   * - 60
     - Property value
     - EUR
     - property
     - —

**Usable Space** is a group type: when it is referenced in a term type or
settlement unit, the system automatically includes measurements of all
child types (*Living Space*, *Commercial Space*) in the calculation.

Additional types can be created under
*Real Estate → Configuration → Measurement Types*.  All children of a
group must share the same unit; circular parent references are rejected.


Object Party Roles **[auto]**
==============================

Three roles are loaded automatically:

.. list-table::
   :header-rows: 1
   :widths: 10 30 30

   * - Seq.
     - Name
     - Applies to object types
   * - 10
     - Caretaker (default)
     - property
   * - 20
     - Administrator
     - property
   * - 30
     - Owner
     - property, object

Additional roles can be created under
*Real Estate → Configuration → Object Party Roles*.


Contract Types **[auto]**
==========================

Six contract types are loaded automatically:

.. list-table::
   :header-rows: 1
   :widths: 5 35 10 10 10 10

   * - Seq.
     - Name
     - Prefix
     - Direction
     - Occupancy
     - Type of use
   * - 10
     - Rental agreement
     - 1
     - Debit (out)
     - yes
     - residential
   * - 20
     - Parking Space Lease Agreement
     - 2
     - Debit (out)
     - yes
     - residential
   * - 30
     - Debit Costs Agreement
     - 3
     - Debit (out)
     - —
     - all
   * - 40
     - Credit Costs Agreement
     - 4
     - Credit (in)
     - —
     - all
   * - 50
     - Commercial lease agreement
     - 5
     - Debit (out)
     - yes
     - commercial
   * - 80
     - Condominium fee agreement
     - 8
     - Debit (out)
     - yes
     - property

For each contract type you should check and set, if not already done:

- **Default account** — the revenue/expense account for invoice lines
- **Default taxes** — e.g. 19 % USt. for commercial contracts
- **Payment term** — optional default payment term


Contract Term Types **[auto]**
===============================

Seven term types are loaded automatically:

.. list-table::
   :header-rows: 1
   :widths: 10 35 15 20

   * - Seq.
     - Name
     - Rhythm
     - Type of use / m_type
   * - 1000
     - Apartment rent (monthly)
     - 1 × monthly
     - residential / Living Space
   * - 1100
     - Parking space rent (monthly)
     - 1 × monthly
     - residential, commercial, internal / —
   * - 2000
     - AP for Operating costs (monthly)
     - 1 × monthly
     - all / Living Space
   * - 3000
     - AP for Heating costs (monthly)
     - 1 × monthly
     - all / Living Space
   * - 8000
     - Commercial rent (monthly)
     - 1 × monthly
     - commercial / Commercial Space
   * - 9000
     - Condominium fees (monthly)
     - 1 × monthly
     - property / —

For each term type you can optionally set:

- **Default account** — pre-filled on the contract term when this type is
  selected
- **m_type** — measurement type used to derive the default quantity
  (the value is looked up from the referenced contract item's objects)


Cost Category Groups **[auto]**
================================

Five groups are loaded automatically, following the BetrKV paragraph
structure:

- I · Grundbesitzabgaben & Versicherungen (seq. 100)
- II · Ver- und Entsorgung (seq. 200)
- III · Reinigung, Pflege & Sicherheit (seq. 300)
- IV · Sonstige Betriebskosten (seq. 400)
- V · Keine Umlage (seq. 900)


Cost Types (§ 2 BetrKV) **[auto]**
=====================================

The following cost types are loaded automatically, covering the standard
positions of § 2 BetrKV:

.. list-table::
   :header-rows: 1
   :widths: 8 45 10

   * - Seq.
     - Name (§ 2 BetrKV)
     - Group
   * - 100
     - Grundsteuer (Nr. 1)
     - I
   * - 110
     - Gebäudeversicherung (Nr. 13)
     - I
   * - 200
     - Wasserversorgung, Abwasser (Nr. 2 + 3)
     - II
   * - 300
     - Heizung – Brennstoff (Nr. 4)
     - II
   * - 310
     - Heizung – Wartung (Nr. 4)
     - II
   * - 320
     - Warmwasser (Nr. 5)
     - II
   * - 330
     - Verbundene Heizungs- und Warmwasserversorgung (Nr. 6)
     - II
   * - 400
     - Aufzug (Nr. 7)
     - II
   * - 500
     - Straßenreinigung (Nr. 8)
     - III
   * - 510
     - Müllabfuhr (Nr. 8)
     - III
   * - 520
     - Hausreinigung (Nr. 9)
     - III
   * - 600
     - Gartenpflege (Nr. 10)
     - III
   * - 610
     - Hausstrom (Nr. 11)
     - III
   * - 620
     - Schornsteinfeger (Nr. 12)
     - III
   * - 700
     - Hausmeister (Nr. 14)
     - IV

Additional cost types (e.g. antenna, broadband, communal laundry) can be
added freely under *Real Estate → Configuration → Cost Types*.


Taxes
=====

The SKR04 templates include tax records for 7 % and 19 % VAT.  After
applying the chart of accounts, verify that the tax record
*USt. 19 % Umsatzsteuer voller Satz Waren Inland* exists under
*Accounting → Taxes*.  This tax is used by ``test_contracts.py`` for
commercial leases and should be assigned to the *Commercial lease
agreement* contract type as a default tax.
