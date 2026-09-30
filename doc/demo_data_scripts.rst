*****************
Demo data scripts
*****************

Everything in ``tests/`` is instead a one-shot **proteus import script** that
generates demo data against a running trytond server. These are run
manually — ``python tests/<script>.py --database <db> [--config
trytond.conf]`` — not via tox/xmlrunner, in the following order (each step
builds on the previous one's data):

``tests/test_immo.py``
   No prerequisites. Creates two properties (*Musterstraße 1-4* and
   *Musterstraße 5-8*), each with four buildings. Every building has one
   ground-floor retail unit (``type_of_use='commercial'``, 140 m²) and four
   apartments (``type_of_use='residential'``, 57/83 m² alternating) — 16
   apartments, 4 retail units, and 20 water meters per property in total —
   plus one land parcel with four parking spaces. Meter names follow the
   pattern ``Wasser Zähler NN`` / ``Wasser Zähler EHNN``, each with an
   initial and a consumption reading. Looks up ``real_estate.use_class`` by
   ``sequence`` (language-independent) and measurement types by German name
   — the ``admin`` user must be set to German::

      python tests/test_immo.py --database <db> [--config trytond.conf]

``tests/test_contracts.py``
   Requires ``test_immo.py``. Creates residential lease contracts for 15 of
   16 apartments per property (one left vacant), each with rent, operating
   cost, and heating terms; three contracts per property are terminated,
   two of them with a follow-up contract. The four parking spaces per
   property are split between existing apartment contracts (as an extra
   contract item) and new standalone parking contracts. Also creates
   commercial lease contracts for the retail units — one combined contract
   for all four retail units on *Musterstraße 1-4*, one contract per unit on
   *Musterstraße 5-8*. Terms are absolute amounts (price per m² × area,
   quantity 1). Up to three running apartment contracts per property get a
   graduated rent (rent adjustment with procedure ``graduated_rent`` on the
   rent term: 12-month rhythm, 5 steps, +30 € / +0.40 €/m² / +3 %), whose
   steps are generated; the procedure is allowed on the residential
   contract type and the rent term type first if missing::

      python tests/test_contracts.py --database <db> [--config trytond.conf]

``tests/test_billing_unit.py``
   Requires ``test_immo.py``. Creates two billing units per property:
   *Kalte Betriebskosten* (measurement- and consumption-based settlement
   units, vacancy allocated to the owner) and *Heizkosten*
   (``external_billing=True``, settlement units use
   ``allocation_from_external_billing``). Billing units are left in state
   ``draft`` — anything that requires a later state (e.g.
   ``test_invoices.py``'s settlement-unit lookup) needs the workflow
   advanced manually first::

      python tests/test_billing_unit.py --database <db> [--config trytond.conf]

``tests/test_kreditor.py``
   No prerequisites. Creates 11 supplier/creditor parties (property tax
   office, building insurer, utilities, cleaning, caretaker, gardening,
   chimney sweep, heating maintenance), each with an invoice/delivery
   address::

      python tests/test_kreditor.py --database <db> [--config trytond.conf]

``tests/test_invoices.py``
   Requires ``test_kreditor.py``, ``test_immo.py``, and
   ``test_billing_unit.py`` (with billing units advanced past ``draft`` so
   settlement units can be looked up). Creates the corresponding purchase
   invoices — one-off and recurring — for each property, linking each line
   to its ``settlement_unit`` where a match is found. Invoices are only
   saved, not posted (remain in state ``draft``)::

      python tests/test_invoices.py --database <db> [--config trytond.conf]

``tests/test_payment.py``
   Requires ``test_contracts.py`` and at least one run of the
   ``CreateContractMoves`` wizard so posted tenant invoices exist. Books one
   payment receipt per tenant/commercial-tenant party (debit account 1800
   Bank / credit the receivable account taken from that party's open lines)
   and reconciles the open items::

      python tests/test_payment.py --database <db> [--config trytond.conf]
