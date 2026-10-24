*******************
Module Dependencies
*******************

``ir``, ``res``, ``company``, ``party``, ``product``, ``currency``, ``country``,
``account``, ``account_invoice``, ``account_asset``, ``account_deposit``,
``account_payment_clearing``,
``account_tax_non_deductible``, ``bank``

``bank`` is used only by the BVED export's A-/M-Satz bank-field lookup
(``party.bank_accounts_used`` → IBAN → classic Kontonummer/Bankleitzahl) — see
`BVED External Billing Interface <bved.rst>`__.

``account_asset`` is used by the year-end closing process: the step *Post
the depreciation* opens its wizard *Create Assets Moves* (see `Tasks,
Processes and Handover Reports <tasks.rst>`__).
