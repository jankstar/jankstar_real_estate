.. _tasks-index:

*************************************
Tasks, Processes and Handover Reports
*************************************

Specifications: ``spezifikation-wiedervorlage.md`` (tasks, reminders,
rules, processes) and ``spezifikation-uebergabeprotokoll.md`` (handover
reports).

Overview
========

- **Tasks** (*Aufgaben*): follow-ups on a record - created manually,
  by hooks of the module (e.g. termination, index rent), by task rules
  or by process steps - with reminders and escalation.
- **Task rules**: scheduled creation of tasks from a date of a record
  (e.g. fixed-term contract ends, meter calibration expires).
- **Processes** (*Prozesse*): a sequence of tasks from a template
  (move-out, move-in, change of tenant, index rent adjustment), started
  manually or by the contract type.
- **Handover reports** (*Übergabeprotokolle*): move-in, pre-inspection
  and move-out reports of a contract; they complete the matching process
  steps.

Menus:

- *Real Estate › Tasks and Follow-ups*: *My Tasks*, *All Tasks*,
  *Processes*
- *Real Estate › Contracts › Handover Reports*
- *Real Estate › Configuration › Tasks and Processes*: *Task Types*,
  *Task Rules*, *Process Templates*, *Handover Checklists*

The contract, the objects (property, building, land, rental object,
equipment), the billing unit and the rent adjustment have a tab *Tasks
and Processes* with the sub tabs *Open* (open tasks - *+* creates a task
- and running processes) and *History* (done/cancelled tasks and
processes); the lists show the reference of each task and process.
What is listed:

- contract: all tasks of the contract (also of its rent adjustments and
  parties, stored ``contract``) and its processes;
- property: all tasks and processes of the property - its objects,
  contracts and billing units (stored ``property``; *+* creates a task
  for the property itself);
- rental object: its own tasks and processes plus, read-only, those of
  the contracts whose items contain it (function fields with one search
  each, ``contract.items.objects``);
- building, land, equipment, billing unit, rent adjustment: their own
  tasks and processes (by ``resource``).

The tab *Handover Reports* of the contract lists the handover reports.

Tasks
=====

``real_estate.task.type``  (``task.py``)
   Task type (menu *Configuration › Tasks and Processes › Task Types*). ``code`` is a
   selection from the fixed catalog ``TASK_CODES`` in ``task.py``
   (code → label, reference objects, manual or automatic only), unique
   and readonly once saved; hooks, rules and processes find their type by
   it. Types without code are own types without function in the module,
   their reference objects are selected in ``custom_models`` (empty = all,
   ``all_models``). ``resource_models`` (catalog or own selection) and
   ``manual`` are shown; ``for_model`` (searcher only) filters the types
   allowed for an object. Default responsibility
   (``responsible_group`` / ``responsible_user``, optionally
   ``responsible_role`` - see *Responsibility by party role* below),
   ``remind_days``,
   ``remind_daily``, escalation (``escalate_days``, ``escalation_group``),
   ``recurrence_months``, ``email``, ``icon``, ``note_on_done``. Default
   types (``task.xml``, ``noupdate``) for the uses of chapter 3 of the
   specification, e.g. ``manual``, ``contract_unsigned``,
   ``index_prepare``, ``index_receipt``, ``billing_deadline``,
   ``meter_calibration``, ``cron_error``.

``real_estate.task``  (``task.py``)
   Task of a record (``resource``: contract, contract party, rent
   adjustment, term adjustment, object, billing unit, price index,
   scheduled task, party). ``contract`` and ``property`` are stored and
   derived from the reference. Fields: subject, type, ``due_date``,
   ``remind_date`` (default due date - remind days), responsible user
   and/or group (default from the type, else the creator), priority,
   description, result, ``recurrence_months``, ``previous``, ``origin`` /
   ``origin_key`` (rule or process, idempotence), ``notified_date`` /
   ``escalated_date`` (reminders, phase B), ``is_mine`` and ``overdue``
   (searchable).

   **Responsibility by party role.** With a ``responsible_role`` on the
   task type (or on the process template step, which takes precedence)
   the party holding this object party role (e.g. *Administrator*,
   *Caretaker*) on the objects of the reference on the **due date**
   becomes responsible: objects of the contract items (contract, contract
   party, rent and term adjustments) resp. the object itself or the
   property of a billing unit, then their parents up to the property -
   the most specific level wins, on one level the latest *valid from*
   (``Task._role_responsible``). The party is stored in
   ``responsible_party`` (shown, also without a user, e.g. an external
   caretaker). If exactly one active user is linked to an employee of the
   party in the company of the task (user form, field *Employees*), this
   user becomes the responsible user. Otherwise, for a task entered
   manually, the creator becomes responsible if the type has
   ``creator_responsible`` (*Creator Responsible on Manual Entry*); else
   the user of the type applies, which may be empty - the task is then
   visible to the group and can be taken over (*Take Over*). The group of
   the type is kept in every case; a task without user and group goes to
   the creator (``Task._default_responsible``). Resolved when a task
   is created without given responsibility and in the form when the type
   is chosen (``on_change_task_type``, also in *New Task*); open tasks are
   not reassigned when an assignment changes.

   States ``open → done / cancelled``: *Done* (done by/on; with a
   recurrence the next task n months later; optional note on the
   referenced record), *Cancel* (reason in *Result* required), *Reopen*
   (creator or administration), *Postpone* (wizard: new due date and
   reason, history in the description, reminder reset), *Take Over*
   (responsible user = current user).

   Menu *Real Estate › Tasks and Follow-ups › My Tasks* (tabs *Due*, *Overdue*,
   *Next 30 Days*, *All Open*, *Done* with counters; list, form, calendar)
   and *All Tasks*. Tab *Tasks* with *+* on contract (there: tab *Tasks
   and Processes*, sub tab *Open*)
   (``One2Many`` over the stored ``contract``: all tasks of the
   contract, also of its rent adjustments and parties; the contract is
   the reference of new ones), rent adjustment, object and billing unit
   (``One2Many`` over the reference ``resource``); a property additionally
   lists the tasks of all its objects (read-only). Action *New
   Task* on these forms. The type of a task is restricted to
   the types allowed for the reference object (``resource_model``) and,
   for manual tasks, to manual types; tasks created by the
   module are marked ``automatic``.

   Visibility: company rule; the groups Object/Contract/Billing/View see
   tasks assigned to them (user or group) or created by them, the
   administration sees all. For this the record rule context is extended
   by ``user_id`` (``ir.py``).

   Programming interface: ``Task.create_for(record, type_code,
   due_date, ...)`` (idempotent), ``close_for(record, type_code)``,
   ``cancel_for(record, type_code)``. Hooks: index rent *Declare* creates
   ``index_receipt`` (declaration date + 7 days), entering the receipt
   date closes it, *Execute* closes ``index_receipt`` /
   ``index_execute`` / ``index_declare`` and ``index_prepare`` of the
   agreement.

**Reminders and escalation** (phase B, ``Task.notify``)
   Scheduled task ``task_notify`` (*Real Estate Accounting › Scheduled
   Tasks*, daily): open tasks with ``remind_date`` reached notify the
   responsible user, else all active members of the responsible group
   (client notification ``res.notification`` with link to the task) -
   once (``notified_date``) or every day with ``remind_daily`` on the
   type. Open tasks ``escalate_days`` after the due date notify the
   ``escalation_group`` once (``escalated_date``). With ``email`` on the
   type an e-mail is sent in addition (``ir.email``) to users with an
   address and ``task_email`` (user preference, default on); without SMTP
   configuration the error is only logged. For the live display of
   notifications in the client the server needs ``[bus] allow_subscribe =
   True`` in ``trytond.conf``.

   ``Contract.cron_daily`` runs every due scheduled task in its own
   transaction (``_cron_run_task``): an error rolls back only this task,
   is logged and creates the task ``cron_error`` (*Scheduled task failed*,
   administration) for the scheduled task, further errors are appended
   to its description; the other scheduled tasks continue.


Task rules
==========

``real_estate.task.rule``  (``task_rule.py``, phase C)
   Task rule (menu *Configuration › Tasks and Processes › Task Rules*): reference object
   (``model``), restriction ``domain`` (PYSON, like an action domain),
   reference date from a date field of the model (also function fields)
   or a named method, offset in months/days, lead time
   (``horizon_days``), task type (only types for the object),
   ``name_template`` (``%(record)s``), ``done_domain`` and
   ``on_date_change`` (cancel or done when the reference date changed).
   The scheduled task ``task_rules`` (daily) and the button *Run Now*
   call ``TaskRule.run``: per record and reference date one task
   (``origin`` = rule, ``origin_key`` = record and date, marked
   ``automatic``) once its due date is within the lead time - also a
   task already done or cancelled is not created again for the same
   date. Open tasks of the rule are done automatically when the record
   matches ``done_domain`` or no longer matches ``domain``, and are
   cancelled (or done) with a new task when the reference date changed.
   Errors of a rule are logged and shown in *Last Result*.

   Named methods (``TaskRule._date_<name>``): ``billing_deadline``
   (billing units not billed: end of period + 12 months),
   ``meter_reading_due`` (properties whose meters lack a reading at the
   day before the next billing start, ±7 days), ``index_values_stale``
   (last final value older than 2 months), ``no_follow_up_contract``
   (terminated contracts without a later contract for their objects),
   ``state_since`` (date of the last state transition from
   ``ir.model.log``), ``cron_overdue`` (scheduled tasks not run for their
   interval + 3 days).

   Default rules (``task_rule.xml``, ``noupdate``, all **inactive**): V02
   contract not signed, V03 fixed-term contract ends, V07 contract party
   ends, V08 no follow-up contract, M01 prepare index rent adjustment, M02
   index adjustment not declared, M04 not executed, M05 graduated rent
   ends, M06 termination waiver ends, M07 index values outdated, M08 tight
   market regulation ends, B01 billing deadline, B02 adjust prepayments,
   O01 meter readings, O03 meter calibration, O04 object ends, S02
   scheduled task not run, P01 inspection overdue, P02 inspection defect
   overdue. Each default rule has a description
   (translatable, German in ``locale/de.po``) that is copied into the
   tasks it creates.

   Meter calibration (base object, tab *Meters*): ``meter_calibration_date``,
   ``meter_calibration_years``, ``meter_calibration_valid_to`` (proposed
   31.12. of the year of the last calibration + validity, can be
   overwritten) and ``meter_calibration_due`` (ends within 3 months,
   searchable); optional column in the object list.

Processes
=========

``real_estate.process.template`` / ``real_estate.process``  (``process.py``, phase D)
   Process templates (menu *Configuration › Tasks and Processes ›
   Process Templates*):
   reference object, anchor date field (e.g. ``termination_date``) and
   steps. A template step has a task type (reminder, escalation,
   responsibility) and optionally a responsible group, the due date base
   (start of the process, anchor date, previous step done or a method,
   e.g. ``billing_deadline_for_contract``) with an offset - or the offset
   in months from the real estate accounting setting
   ``deposit_task_months`` (default 6) - mandatory/optional, a work
   instruction, an **action** (report, wizard or list) and the
   **completion** (manual, by executing the action, or by condition:
   PYSON domain on the reference record or a method ``deposit_paid``,
   ``meter_readings_complete``, ``billing_settled``, ``handover_*_done``,
   ``inspection_done``, ``inspection_approved``), optionally with a
   required result, and the **creation** (always, or by a method such as
   ``inspection_no_access`` / ``inspection_has_defects``: the task is
   created only once the condition is fulfilled; such a step never
   created does not block the completion).

   A process (menu *Tasks and Follow-ups › Processes*, tab *Tasks and
   Processes*
   on the contract) is started with the action *Start Process* on
   contract, rent adjustment, object or billing unit, or automatically
   by the templates set on the contract type: *Process at Contract Start*
   (contract set to running), *Process at Termination* (termination
   wizard), *Process at Partner Change* (partner change wizard). **Every
   step is a task**: at the start the process creates one task per
   template step in the state **planned** (no due date, no reminder, not
   in *My Tasks*; fields ``template_step`` and ``step_number``); a planned
   task is opened (due date, reminder, responsibility by the party role
   on the due date) as soon as it is due - start, anchor and method
   steps at once, *previous step done* steps once the previous one is
   done or skipped, conditional steps once their condition is fulfilled.
   The process form lists its tasks by step number (tab *Steps*). A task
   of a process shows below its reference the **process**, the
   **process step** and the **step number**, both opening the record; the
   task lists have the sortable column *Step No.*, the template step list
   the column *No.*. (Until version 1.7 of the specification the steps
   were separate records ``real_estate.process.step``; the update takes
   their data over into the tasks.) The task of a step with an action shows the button
   *Execute Action*: it opens the action for the reference record (and
   completes the step for completion *by action*). *Check State* evaluates
   the conditions (also daily with the scheduled task ``task_rules``),
   *Reschedule* moves the open anchor tasks after a change of the anchor
   date (history), *Cancel* cancels the open and planned tasks. When all mandatory
   steps are done or skipped the process is done (progress "n / m
   done"). *Reopen* sets a done process running again (also
   automatically when one of its tasks is reopened); *Reactivate* sets a
   cancelled process running again and sets the tasks cancelled with the
   process back to planned (steps skipped before stay skipped). Both are noted
   in the history. The process of an inspection follows the inspection and
   cannot be cancelled or reactivated directly (see `Recurring Inspections
   <inspections.rst>`__).

   Default templates (``process.xml``, ``noupdate``, not assigned to a
   contract type): *Move-out* (10 steps: confirmation with the report
   *Termination Confirmation*, pre-inspection, handover, meter readings,
   keys, deposit after ``deposit_task_months``, remaining deposit and
   claims check optional, final operating cost billing), *Move-in* (5
   steps: deposit received - ``deposit_paid``, handover, meter readings,
   keys, direct debit mandate), *Change of Tenant in the Contract* (4
   steps), *Index Rent Adjustment* (run, declare, receipt, execute) and
   *Vacancy / Reletting* on an object (6 steps: meter readings and
   securing, inspection and repairs - both with role *Caretaker* -, new
   rent, advertisement, viewings and tenant selection, new lease contract;
   started with *Start Process* on the rental object).
   Every default step has a work instruction (translatable, German in
   ``locale/de.po``); it is copied into the task in the language of the
   user creating it, so existing tasks keep their text.

Handover reports
================

``real_estate.contract.handover``  (``handover.py``)
   **Handover report** (*Übergabeprotokoll*, menu *Contracts › Handover
   Reports*, tab *Handover Reports* on the contract) of a ``move_in``, ``pre_inspection`` or
   ``move_out`` (``spezifikation-uebergabeprotokoll.md``): date and time,
   objects handed over, tenants present (or absent), landlord
   representative, other participants, check items (room, item,
   condition ok / normal wear / damage / missing, description, photos as
   attachments, remedy by tenant or landlord until a date, estimated
   costs - total ``cost_total`` as basis for the deposit settlement),
   keys (type, description, quantity; for a move-out the quantity of the
   move-in report is shown and deviations are marked), meter readings,
   general condition, swept clean, agreements and the scan of the signed
   report (``signed_document``).

   Proposals (on creation, when choosing contract/kind, button *Apply
   Proposals*): the objects of the contract items, the main tenants, the
   check items of the checklist chosen by the contract's type of use
   (*Configuration › Tasks and Processes › Handover Checklists*, default *Apartment* and
   *Commercial unit*), the meters below the objects, for a move-out the
   keys of the move-in report and the open defects of the last
   pre-inspection.

   *Complete* (``draft → done``) checks objects, keys (move-in/out) and
   one done report per contract and kind (several pre-inspections
   allowed), warns about missing meter readings (confirmable), creates
   the meter readings at the handover date (``real_estate.meter_reading``,
   existing readings of the day are linked), logs the report in the
   contract log and completes the matching process steps at once. Only
   the administration can reset a done report to draft. Report *Handover
   Report (de)* (``report/contract_handover_de.odt``) with signature
   fields, marked ENTWURF before completion.

   Process integration: actions *Move-in / Pre-inspection / Move-out
   Report* (opened for the contract with ``default_kind``) and the done
   methods ``handover_move_in_done``, ``handover_pre_inspection_done``,
   ``handover_move_out_done``, used by the default templates *Move-out*
   (pre-inspection, handover, keys) and *Move-in* (handover, keys).
