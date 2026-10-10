.. _rent-survey-index:

***********************************
Rent Survey (Comparative Rent)
***********************************

The local comparative rent (*ortsübliche Vergleichsmiete*, § 558 BGB) of a
residential rental unit is **calculated directly** from a rent survey
(*Mietspiegel*) mapped in the system: classification by classes and
features on the object tree, evaluation by the rules of the rent survey
version. The result is reproducible, comes with a protocol and has to be
accepted. There is no AI or external service involved.

Concept
=======

All rent surveys map the statutory residential value features (kind,
size, equipment, condition incl. energy, location) to a value in €/m²
net rent with a range. Two methods are supported:

- **Table** (``method = 'table'``, e.g. Berlin): a table cell (classes such
  as location and age, plus an area range) gives lower, mean and upper
  value; each feature group with the rule *Majority* counts +1 / 0 / -1
  (positive or negative features prevail) and moves the rent from the
  mean by ``group_percent`` (default 20 %) of the distance to the upper
  resp. lower value - netted (default) or separately; the result is
  limited to the range; groups with the rule *Additive* (special
  surcharges/reductions in €/m² or %) apply afterwards.
- **Regression** (``method = 'regression'``): the cell gives the base
  value; features add percentages and amounts; the range is the result
  ± the spread in %.

Classes and features are stored on the objects as **codes**, so they stay
valid for the next version of the rent survey with the same codes.

Customizing
===========

Menu *Configuration › Rent Surveys* (group *Real Estate Administration*;
read for object, contract, billing and view group).

``real_estate.rent_survey``  (``rent_survey.py``)
   Rent survey (name, municipality, company) with its versions; the
   ``current_version`` is the version valid today.

``real_estate.rent_survey.version``
   Version with ``valid_from`` (unique per survey; ``valid_to`` = day
   before the next version), survey date, kind (*Simple* / *Qualified*),
   method, rent definition, the living space measurement (default *Living
   Space*), further measurements for the protocol (default *Number of
   rooms*), ``group_percent``, ``group_netting``, spread (regression),
   rounding digits and ``source_document`` (reference/URL; the official
   document is attached to the version). Tabs: *General*,
   *Classification Features*, *Table Cells*, *Feature Groups*, *Check
   Result*. Buttons:

   - *Check*: one class per classification feature in every cell,
     lower ≤ mean ≤ upper, no overlapping area ranges per class
     combination - the result is written to *Check Result*.
   - *Import*: wizard for table cells or features from a CSV file with
     preview and problem list (import only without problems), optionally
     replacing the existing data.
   - *New Version*: copies the version with classification features,
     classes, cells, groups, features, exclusions and class conditions
     (codes kept) for a new ``valid_from`` and opens it.

   Once an accepted calculation uses the version it is **locked**
   (``locked``): classes, cells, features and rules are read-only;
   corrections by a new version.

``real_estate.rent_survey.dimension`` / ``…dimension.class``
   Classification feature (table axis, e.g. ``location``, ``age``) with
   ``level`` (property, building, rental unit), ``source`` (*Manual*, *Year
   of Construction* of the building, *Measurement*) and classes with code,
   name, value range ``value_min ≤ value < value_max`` for derived classes
   and ``manual_only`` (e.g. special classes, never derived).

``real_estate.rent_survey.cell``
   Table cell: code (row of the table), exactly one class per
   classification feature, area range ``area_min ≤ living space <
   area_max`` (empty = open), lower / mean / upper value, ``qualified``,
   note.

``real_estate.rent_survey.group`` / ``…feature``
   Feature group (code, name, rule *Majority* / *Additive*) with features:
   code (unique per version), name, wording, direction (+/−), effect
   (*Vote*, *Percent*, *Amount per m²*) and value, level, *Only for
   Classes* (e.g. only up to construction year 2009), automatic setting
   by a measurement range (``auto_measurement_type``, ``auto_min ≤ value
   < auto_max``, e.g. energy consumption value) and *Excludes* (features
   excluding each other).

CSV formats (separator ``;``, decimal comma or point, a first line
starting with ``code`` resp. ``group_code`` is the header):

.. code-block:: text

   code;dims;area_min;area_max;lower;mean;upper;qualified;note
   85;location=medium,age=1950_1964;45;;5,90;7,08;9,25;1;

   group_code;code;direction;effect;value;level;applies_to;auto_measurement;auto_min;auto_max;name;description;exclusive_with
   5;u_quiet;plus;vote;;property;;;;;Besonders ruhige Lage;;u_noise
   S;s_minor_equipment;minus;amount;0,33;object;age=to_1918;;;;Minderausstattung;;

Missing feature groups are created by the feature import (*Majority* for
votes, else *Additive*); ``auto_measurement`` is the XML id of a delivered
measurement type (e.g. ``measurement_energy_consumption_type``,
language-independent) or the name of the measurement type.

Berlin rent survey 2026
=======================

The complete Berlin rent survey 2026 is provided as CSV files taken from
the official documents (*Berliner Mietspiegel 2026*, *Berliner
Mietspiegeltabelle 2026*):

- ``tests/mietspiegel_berlin_2026_felder.csv``: all 189 table cells of
  the tables 9.1-9.3 (simple, medium, good location × 12 classes of
  construction age × area ranges, all within the qualified scope).
- ``tests/mietspiegel_berlin_2026_merkmale.csv``: the guidance for the
  classification within the range (no. 11) with 85 features in the
  groups 1-5 - class conditions such as *only up to 2001* or *not for
  1973-1990 East*, the energy consumption value stages as automatic,
  cumulative features (e.g. 90 kWh/(m²a) counts *< 120* and *< 100*),
  *either insulation or energy value* resp. *either old heating or energy
  value* as exclusions - plus the reduction of 0.33 €/m² for minor
  equipment up to 1949 (no. 9.4, group S, not qualified).

``python tests/test_rent_survey.py --database <db> [--config
trytond.conf] --only-survey`` creates the rent survey with the version
2026 (classification features *Wohnlage* and *Bezugsfertigkeit* with
their classes; 1973-1985 West, 1986-1990 West and 1973-1990 East are
manual only as they depend on the district) and imports both files;
without ``--only-survey`` it also assigns demo data (see `Demo data
scripts <demo_data_scripts.rst>`__). The data have to be checked against
the original before productive use; the location of an address is taken
from the street directory.

Data on the object tree
=======================

Tab *Rent Survey* of the object form (property always; building and
apartment once the property has a rent survey). An **apartment** is a
rental unit whose use class allows the procedure *Comparative Rent*
(*Allowed Adjustment Procedures* of the use class, by default only
*Apartment*) - parking spaces, garages and commercial units have no rent
survey data, no buttons and no calculation:

- ``rent_survey`` (property): the rent survey of the residential rental
  units of the property.
- *Rent Survey Classes and Features* (``real_estate.base_object
  .rent_survey_value``): editable list of classes and features of this
  level with validity period and evidence; the selection offers the
  classes of the version valid today whose classification feature
  belongs to the level of the object or a higher one (e.g. the age class
  on the building or the rental unit, not on the property; the search
  list shows the classification feature) resp. the features of the
  level; stored are the codes.
- *Rent Survey Data*: remarks and reasons (e.g. reference in the street
  directory) - shown in the inputs of the calculation, not used for it.
- Button *Assign Features*: checklist of the features of the level;
  newly checked features are created without validity period, unchecked
  ones deleted (without period) resp. ended the day before the key date.
- Buttons *Export Matrix* / *Import Matrix* (property): CSV matrix of the
  property for a key date with one row per apartment resp. building
  (column ``id``, name) and one column per classification feature
  assignable on that level (``class:<code>``, value = class code) and per
  feature of the level (code, ``x`` = applies); a second line starting
  with ``#`` holds the names. The file (UTF-8 with BOM, separator ``;``)
  can be changed in a spreadsheet and imported again: compared with the
  own assignments valid on the key date, missing ones are created,
  removed ones deleted (without period) resp. ended the day before (with
  a period starting before the key date); assignments of codes not in the
  matrix stay untouched. Preview with the changes per object and the
  problems (unknown columns, objects, classes or marks); applied only
  without problems.
- Button *Copy from Building* (building): the same for the building -
  classes and features of another building of the same property.
- Button *Copy from Rental Unit* (rental unit): wizard to take over the
  features - optionally also the classes - of another rental unit of the
  same property valid on a key date (with validity period and evidence);
  only missing ones are added, a class of the same classification feature
  is kept, or with *Replace Existing* the current assignments are removed
  first (with a validity period: ended the day before).
- Button *Calculate Comparative Rent* (residential rental unit) and the
  list of its calculations.

Inheritance: a class on a lower level overrides the class of a higher
level (rental unit > building > property); **features add up** over the
three levels. The measurement type *Energy Consumption Value* (building,
kWh/(m²a)) holds the value already converted (demand value + 20 %,
+ 20 kWh/(m²a) without hot water); the conversion is noted in the
evidence or the rent survey data.

Calculation
===========

``real_estate.rent_survey.calculation`` - menu *Contracts › Rent
Adjustments › Comparative Rent Calculations* (tabs *Draft*, *Calculated*,
*Accepted*, *All*), tab *Rent Survey* of the rental unit. One calculation
= one residential rental unit on a key date; optional references to
contract, term and rent adjustment (procedure *Comparative Rent*).

*Calculate*:

1. version valid on the key date; living space (sum measurement) on the
   key date;
2. class per classification feature: manual assignment of the lowest
   level valid on the key date, else derived from the year of
   construction resp. the measurement (classes *Manual Only* are never
   derived);
3. table cell matching all classes and the living space;
4. features: assigned ones of the three levels valid on the key date plus
   automatic ones within their measurement range, minus those whose class
   condition does not match (listed as ignored);
5. method table resp. regression (see *Concept*), rounding;
6. protocol, snapshot of all inputs (``inputs_json``: classes with
   origin and level, features with source, measurements, year of
   construction, rent survey data), group results, checks.

Checks: B01 residential rental unit, rent survey and valid version; B02
living space; B03 one class per classification feature; B04 exactly one
table cell; B05 cell outside the qualified scope (warning); B06 excluding
features; B07 assigned code missing in the version (warning); B08 group
without feature (note); B09 missing measurement for automatic features
(warning). With an error the calculation stays *Draft* with protocol and
messages; else it is *Calculated*.

*Accept* (mandatory step, from *Calculated*) with the accepted rent per
m² (default the calculated one); a reason is required with warnings or a
different rent. *Reject*. *Calculate Comparative Rent* on the rental
unit and *Recalculate* calculate an open calculation (draft or
calculated) of the same rental unit and key date again with the current
data instead of creating another one; a new calculation is created only
once the existing ones are accepted or rejected - so there is at most one
open calculation per rental unit and key date. Calculated ones only
accept the acceptance fields, accepted and rejected ones are read-only;
accepted calculations can never be deleted (evidence, they lock the
version), all others can (group *Real Estate Contract*).
The comparative rent is rent per m² × living space.

Access: customizing *Real Estate Administration*; assignments on the
objects *Real Estate Object*; calculating and accepting *Real Estate
Contract*; reading *Real Estate View*.

The procedure *Comparative Rent* of the adjustment run (cap, periods,
consent, request letter) builds on the accepted calculation: the run
creates the calculations of the selected apartments on its key date, the
button *Calculations* of the run opens them for the acceptance - see
`Comparative Rent <rent_adjustment_comparative.rst>`__. The
calculation protocol (with translated levels) is part of the request
letter.
