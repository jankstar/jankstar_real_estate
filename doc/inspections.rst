.. _inspections-index:

*********************
Recurring Inspections
*********************

Specification: ``spezifikation-pruefungen.md`` (recurring inspections,
processes and reports). Implemented so far: phase P1 - equipment kinds,
inspection types, checklists and inspection plans with due date rules -
phase P2 - inspections (protocols) with lines and results, validation,
approval, report and the scheduled creation -, phase P3 - conditional
process steps, next access attempt, tenant notice and letters to tenants
without access -, phase P4 - defects with deadlines, follow-up tasks
and escalation rules - and phase P5 - default data and demo data.

Concept
=======

An inspection type separates **where the inspection runs** (``scope``:
property or building - one inspection = one notice, one report, one
approval) from **where results are recorded** (``line_granularity``: none,
one line per rental unit, one line per equipment below the object). The
smoke detector check is one inspection per building with one line per
apartment. Equipment are the existing objects of type *Equipment* with an
equipment kind; quantities (e.g. number of smoke detectors) are the
measurement type *Number of items*. Steps of an inspection are the steps
of the process template of the type (process engine of `Tasks, Processes
and Handover Reports <tasks.rst>`__), anchored on the planned date.

Models
======

``real_estate.equipment.kind``  (``inspection.py``)
   Equipment kind (menu *Configuration › Inspections › Equipment Kinds*):
   name, code. Default kinds (``inspection.xml``, ``noupdate``): smoke
   detector, elevator, playground, fire extinguisher, backflow preventer,
   heating system, smoke and heat exhaust system. Field
   ``equipment_kind`` on objects of type *Equipment* (tab *Equipment*).

``real_estate.inspection.checklist`` / ``.item``  (``inspection.py``)
   Reusable checklists (menu *Configuration › Inspections › Inspection
   Checklists*), one for the header and one for the lines of a type.
   Item: section, question, ``answer_type`` (OK/not OK/n.a., yes/no,
   number with unit and min/max, text, date, selection), mandatory,
   ``photo_on_nok``, ``create_defect_on_nok`` with ``default_severity``.

``real_estate.inspection.type``  (``inspection.py``)
   Template (menu *Configuration › Inspections › Inspection Types*, not
   company dependent): category, legal basis, scope, line granularity,
   ``equipment_kind`` and ``line_filter`` (PYSON domain on the line
   objects), interval with unit and basis (fixed rhythm / from
   execution), ``preferred_month``, ``lead_time_days``,
   ``tolerance_days``, ``notice_days`` (warning only), responsible party
   role, contractor required, unit access with attempts, approval with
   ``approval_group``, header and line checklist, process template (model
   inspection), defect deadlines per severity (default 1 / 14 / 90 days).

``real_estate.inspection.plan``  (``inspection.py``)
   Inspection type assigned to a property or building (menu *Real Estate
   › Master Data › Inspections › Inspection Plans* with tabs *Due in 90 Days*,
   *Overdue*, *All*; tab *Inspections* on property and building): interval
   settings defaulted from the type, responsible user (overrides the
   role), contractor, ``owner_maintains``, ``last_done_date``,
   ``next_due_date`` (first one defaulted: today + interval, with the
   preferred month), ``overdue`` (due date + tolerance passed). One active
   plan per type and object; a building is required for scope building.
   With a building the property is always the one of the building
   (proposed when the building is chosen, set when saving - also for
   plans created in the tab *Inspections* of a building).

   **Due dates** (``next_due_date()``): fixed rhythm = previous due date +
   interval, repeated until after the execution date; from execution =
   execution date + interval. With a preferred month the date is moved to
   the first of that month in the same year, or of the following year if
   that is not after the execution date. Example (yearly, fixed): due
   15.04.2026, done 28.04.2026 → 15.04.2027 (from execution: 28.04.2027).

``real_estate.inspection``  (``inspection.py``, phase P2)
   Inspection (protocol) of a plan (menu *Real Estate › Master Data ›
   Inspections › Inspections* with tabs *Open*, *To Approve*, *Overdue*, *Approved*,
   *All*; also on the plan, on property/building in tab *Inspections* and
   - as reference with the stored ``property`` - in tab *Tasks and
   Processes* of the property). Number from the sequence *Inspection*
   (``PR-<year>-0001``).

   Created as draft by the button *Create Inspection* on the plan or by
   the scheduled task ``inspection_plans`` (*Real Estate Accounting ›
   Scheduled Tasks*, daily: plans whose ``next_due_date`` minus
   ``lead_time_days`` is reached and that have no open inspection). Lines
   are created from scope, granularity, equipment kind and line filter;
   a rental unit vacant on the due date (occupancy) gets the access
   ``vacant``; the expected quantity comes from the measurement *Number
   of items* of the equipment. Header and line results are created from
   the checklists as snapshot (section, question, answer type, limits).
   *Rebuild Lines* (draft only, with confirmation) creates the lines
   again from the current equipment, equipment kind and line filter -
   e.g. after an equipment kind was set or the filter was changed.

   States: *Schedule* (``draft → scheduled``, planned date required,
   confirmable warning below ``notice_days``) starts the process of the
   type with the inspection as reference and the planned date as anchor
   (steps with negative offsets before it); *Back to Draft* cancels it;
   the first answered result or *Start* → ``in_progress``; *Done* checks
   mandatory answers, photos (attachment) for "not OK" items with
   ``photo_on_nok``, a reason for lines not inspected, the contractor and
   external report (``contractor_required``), warns about lines not
   inspected after fewer access attempts than required, sets the done date
   and the overall result (OK or OK with defects, editable), updates
   ``last_done_date`` and ``next_due_date`` of the plan and - without
   required approval - approves at once; *Reopen* (``done →
   in_progress``); *Approve* (only members of the approval group) archives
   the report *Inspection Report (de)* (``report/inspection_protocol_de.odt``)
   as attachment (``report``) and locks inspection, lines and results;
   *Cancel* needs a reason and cancels the process. Process steps can be
   completed by the conditions ``inspection_done`` and
   ``inspection_approved``. Only draft or cancelled inspections can be
   deleted; corrections of an approved one by a new inspection
   (``previous``).

   **Undo** - every step can be taken back: *Back to Draft*
   (scheduled, cancels the process), *Back to Scheduled* (in progress,
   entries kept), *Reopen* (done; sets the plan back - next due date of
   this inspection, last execution of the previous one - and reopens the
   process step completed by ``inspection_done``), *Take Back Approval*
   (approved → done; approval group of the type or real estate
   administration; the archived report stays as attachment marked
   "(withdrawn)", the step completed by ``inspection_approved`` is
   reopened), *Reactivate* (cancelled → draft; lines and entries kept,
   scheduling starts a new process). The inspection leads its process: the
   process of an inspection cannot be cancelled or reactivated directly -
   cancelling the inspection or setting it back to draft cancels the
   process, reactivating and scheduling the inspection starts a new one.

   Results, access, quantities, visit dates and remarks of the lines are
   entered only while the inspection is *scheduled* or *in progress* -
   read-only in the draft, when done (*Reopen* to change), approved or
   cancelled (also checked on the server). *Schedule* creates the defects
   of "not OK" answers stored before.

``real_estate.inspection.line`` / ``.result``  (``inspection.py``)
   Line per rental unit or equipment: tenant (main tenant of the occupancy
   on the visit/planned/due date), access (accessed, no access, refused,
   vacant, not required), visit date, attempt, quantities expected /
   checked / OK / replaced, derived result (defect if an item is not OK or
   fewer OK than checked, not inspected without access), remarks, results.
   Result: typed value by answer type (OK/not OK/n.a., yes/no, number with
   limits, text, date, selection), comment, ``is_nok``. Rental units and
   equipment show their lines in tab *Inspections* (history).

   *Open Items OK* - on a line (form and list) and on the inspection
   (header and all lines with access): answers the items not yet answered
   with OK (OK/not OK/n.a.) resp. Yes (yes/no); answered items, also "not
   OK", and other answer types stay unchanged. On a line empty quantities
   checked/OK are filled with the expected quantity and an empty visit
   date with today. Lines without access, vacant lines and approved or
   cancelled inspections are skipped; the buttons are shown only while
   the inspection is scheduled or in progress.

**Conditional steps, notice, letters** (phase P3)
   A step of the process template can be created only once a condition
   is fulfilled (``create_condition`` = *By Method*, ``create_method``):
   ``inspection_no_access`` (a line has no access or access refused) and
   ``inspection_has_defects`` (a "not OK" result of an item that creates a
   defect with severity major or critical). Changes of the access of a
   line or of a result re-evaluate the process at once; a conditional
   step never created does not block the completion of the process and
   is transparent for following *previous done* steps.

   **Work in the inspection, tasks as worklist:** the tab *Workflow* is
   the first tab of the inspection as soon as it has a process (from
   *Schedule* on). It shows the process (the running one, else the last
   started), its state and progress (e.g. "2 / 5 done") and lists its
   steps (tasks) with number, state, due date and responsible. The steps close themselves from the
   work in the inspection: *Inspection date (attempt 1)* by
   ``inspection_attempt1_done`` (every line to visit has a visit date),
   *attempt 2* by ``inspection_attempt2_done`` (the lines of the next
   attempt have a visit date again), *Complete the report* and *Approve*
   by done / approved; notice and letters complete their step also when
   created directly on the inspection (``Task.complete_by_action``). Only
   steps outside the system (e.g. commission the contractor) are set
   done by hand.

   *Create Tenant Notice* (action on the inspection, usable as step
   action with completion *By Action*): archives the notice *Tenant
   Notice (de)* (``report/inspection_notice_de.odt``, one page per
   building: inspection type, legal basis, date window, time slots and
   contact - field ``time_slots`` -, contractor, request for access or
   key deposit, reply line) as attachment (``notice``, ``notice_date`` as
   proof) and prints it. *Create Letters No Access* archives and prints
   one letter per line without access to the tenant (*Letter No Access
   (de)*, ``report/inspection_access_letter_de.odt``) and sets
   ``letter_date`` of the lines. *Next Attempt* (in progress) increases
   the attempt of the inspection and of the lines without access.

``real_estate.inspection.defect``  (``inspection.py``, phase P4)
   Defect (menu *Real Estate › Master Data ›
   Inspections › Defects* with tabs *Open*,
   *Overdue*, *To Verify*, *All*; tab *Defects* of the inspection; open
   defects in tab *Inspections* of property, building, rental unit and
   equipment): object (building, unit or equipment), description,
   severity (critical, major, minor, note), detection date, deadline
   (detection date plus ``defect_days_<severity>`` of the inspection type,
   none for notes), responsible (contractor), cost category (unknown,
   maintenance, operating costs), follow-up task, fixed / verified date.

   A "not OK" answer of an item with ``create_defect_on_nok`` creates the
   defect at once (severity from the item, description from section,
   question and comment); a withdrawn answer cancels the still open
   defect. Defects can also be entered by hand. From severity minor a
   follow-up task (type ``inspection_defect``, default role
   *Caretaker*) is created; *Fixed* sets it done, *Cancel* cancels it.

   States ``open → in_progress → fixed → verified`` (*Not Fixed*: back to
   in progress), ``cancelled`` (*Reopen*). Defects not yet verified are
   listed in the next inspection of the plan (*Open Defects of Previous
   Inspections*) and verified there (``verified_in``). Defects of an
   approved inspection keep only state, dates, responsible, deadline,
   cost category and follow-up task editable. The overall result of an
   inspection with a critical defect is *Not OK*; the report lists the
   defects and the open defects of previous inspections. The process
   condition ``inspection_has_defects`` also considers recorded defects
   of severity major or critical.

   Escalation by the default task rules (inactive) *P01 Inspection
   overdue* (date method ``inspection_overdue``: due date plus tolerance)
   and *P02 Inspection defect overdue* (``defect_overdue``: deadline),
   task types ``inspection_overdue`` / ``inspection_defect_overdue``
   (role *Administrator*). Overviews: inspection plans (tabs *Due in 90
   Days*, *Overdue*) and defects (tabs *Open*, *Overdue*, *To Verify*).

Default data (phase P5)
=======================

Delivered in ``inspection.xml`` (``noupdate``; changes in the database are
kept by later updates):

**Annual Walkthrough** (code ``walkthrough``, spec 7.1)
   Building, no lines, yearly fixed rhythm with preferred month April,
   lead time 30 days, role *Administrator*, approval by *Real Estate
   Administration*, legal basis § 823 BGB. Header checklist *Annual
   Walkthrough - Building* (21 items in the sections exterior and roof,
   entrance, staircase, basement and technical rooms, outdoor areas,
   notices, remarks; safety items create defects - escape routes, fire
   doors and combustible storage as critical). Process *Annual
   Walkthrough*: arrange the date with the caretaker (-21 days),
   walkthrough (done with the inspection), approve the report (+7, done
   with the approval), commission repairs (+7, only with major/critical
   defects, optional).

**Smoke Detector Check** (code ``smoke_detector``, spec 7.2)
   Building, one line per residential unit with a smoke detector
   equipment, yearly, lead time 60 days, notice 14 days, role
   *Caretaker*, unit access with 2 attempts, approval by *Real Estate
   Object*, legal basis state building code / DIN 14676-1. Line checklist
   *Smoke Detectors - per Apartment* (required rooms equipped, mounting,
   function test, smoke inlets free, earliest replacement date, remarks).
   Process *Smoke Detector Check*: commission the contractor (-42), notice
   in the building (-14, action *Create Tenant Notice*), inspection date
   attempt 1 (0), letter to tenants without access (+7, action *Create
   Letters No Access*, only without access), attempt 2 (+21, only without
   access), complete the report (+28), approve the report (+35).

The intervals are common practice and have to be checked per federal
state and contract. Further inspection types of spec 7.3 (elevator,
electrical installation, drinking water, fire extinguishers, smoke and
heat exhaust, playground, trees, backflow preventer, roof gutters,
heating, winter service, vacancy check) are created as own types.

Demo data: ``tests/test_immo.py`` creates a smoke detector equipment per
apartment (measurement *Number of items* = number of rooms) and per
building the plans *Annual Walkthrough* (due 01.04.2026) and *Smoke
Detector Check* (due 15.05.2026) - see `Demo data scripts
<demo_data_scripts.rst>`__.
