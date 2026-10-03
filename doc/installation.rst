************
Installation
************

.. code-block:: bash

   pip install -e .           # development install
   pip install -e '.[test]'   # with test dependencies

The module entry point is declared in ``setup.py``::

   [trytond.modules]
   real_estate = trytond.modules.real_estate

Link or install the package inside the Tryton modules directory so that
``trytond-admin -u real_estate`` can find it.

trytond.conf
============

Entries in the server configuration used by the module (all optional):

.. code-block:: ini

   [real_estate]
   # GENESIS-Online (Destatis) API token for the import of price index
   # values (button "Fetch Values" and scheduled task price_index_import);
   # without a token only the CSV import is available
   genesis_token = <API token from GENESIS-Online, menu Webservice (API)>
   #genesis_url = https://genesis.destatis.de/genesisWS/rest/2020/
   #genesis_timeout = 60

   [email]
   # SMTP server and sender for task reminders by e-mail (task types with
   # "E-Mail"); without it the error is only logged
   uri = smtp+tls://user:password@smtp.example.com:587
   from = tryton@example.com

   [bus]
   # live display of task notifications in the client
   allow_subscribe = True

Processes
=========

Besides the server (``trytond``) the scheduled tasks need the cron
process (``trytond-cron``): a single ``ir.cron`` entry *Real Estate
Daily Tasks* dispatches the per-company scheduled tasks (see
`Configuration <configuration.rst>`__, ``real_estate.cron_task``).
After ``trytond-admin -u real_estate`` restart server, worker and cron -
the cron process otherwise keeps running the old code.
