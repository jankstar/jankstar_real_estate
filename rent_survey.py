'Rent survey (Mietspiegel) - classification and calculation of the local comparative rent (§ 558 BGB) - spezifikation-mietspiegel.md'
import csv
import datetime
import io
import json
from decimal import ROUND_HALF_UP, Decimal

from trytond.i18n import gettext
from trytond.model import (
    ModelSQL, ModelView, Unique, Workflow, fields, sequence_ordered)
from trytond.model.exceptions import AccessError, ValidationError
from trytond.modules.currency.fields import Monetary
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Bool, Eval, If, PYSONEncoder
from trytond.transaction import Transaction
from trytond.wizard import (
    Button, StateAction, StateTransition, StateView, Wizard)

LEVELS = [
    ('property', "Property"),
    ('building', "Building"),
    ('object', "Rental Unit"),
    ]
LEVEL_ORDER = ['object', 'building', 'property']


def _dec(value):
    if value is None:
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _round(value, digits=2):
    return value.quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)


def in_range(value, low, high):
    "low <= value < high, empty bounds are open"
    if value is None:
        return False
    return ((low is None or value >= low)
        and (high is None or value < high))


def _ends(record, date):
    """A removed assignment with a validity period starting before the date
    ends the day before; others (no period, or starting on the date) are
    deleted"""
    if record.valid_from and record.valid_from >= date:
        return False
    return bool(record.valid_from or record.valid_to)


def valid_on(record, date):
    "The validity period of the record contains the date (empty = open)"
    return ((not record.valid_from or record.valid_from <= date)
        and (not record.valid_to or record.valid_to >= date))


def compute_rent(method, lower, mean, upper, groups, group_percent=20,
        group_netting=True, spread_lower_percent=None,
        spread_upper_percent=None, round_digits=2):
    """Local comparative rent per m² of a rent survey (spec 6.2, steps 5-6)

    groups: list of (rule, features), a feature is (direction, effect,
    value) with direction 'plus'/'minus', effect 'vote'/'percent'/'amount'.
    Returns a dict with rent, lower, upper, net_votes and the group results
    (+1 / 0 / -1 for 'majority' groups, None for 'additive' ones)."""
    lower, mean, upper = _dec(lower), _dec(mean), _dec(upper)
    percent, amount = Decimal(0), Decimal(0)
    results = []
    for rule, features in groups:
        result = None
        if rule == 'majority':
            plus = len([f for f in features
                    if f[1] == 'vote' and f[0] == 'plus'])
            minus = len([f for f in features
                    if f[1] == 'vote' and f[0] == 'minus'])
            result = (plus > minus) - (plus < minus)
        for direction, effect, value in features:
            value = _dec(value) or Decimal(0)
            if direction == 'minus':
                value = -value
            if effect == 'percent':
                percent += value
            elif effect == 'amount':
                amount += value
        results.append(result)
    votes = [r for r in results if r is not None]
    net_votes = sum(votes)
    if method == 'regression':
        rent = mean * (1 + percent / 100) + amount
        result_lower = rent * (1 + (_dec(spread_lower_percent) or 0) / 100)
        result_upper = rent * (1 + (_dec(spread_upper_percent) or 0) / 100)
    else:
        share = _dec(group_percent) / 100
        if group_netting:
            if net_votes > 0:
                rent = mean + net_votes * share * (upper - mean)
            elif net_votes < 0:
                rent = mean + net_votes * share * (mean - lower)
            else:
                rent = mean
        else:
            rent = (mean + votes.count(1) * share * (upper - mean)
                - votes.count(-1) * share * (mean - lower))
        rent = min(max(rent, lower), upper)
        rent = rent * (1 + percent / 100) + amount
        result_lower, result_upper = lower, upper
    return {
        'rent': _round(rent, round_digits),
        'lower': _round(result_lower, round_digits),
        'upper': _round(result_upper, round_digits),
        'mean': mean,
        'net_votes': net_votes,
        'groups': results,
        }


def _object_level(obj):
    return obj.type if obj and obj.type in dict(LEVELS) else None


def _ancestor(obj, type_):
    node = obj
    while node and node.type != type_:
        node = node.parent
    return node


def _levels(obj):
    "level -> object of the tree (rental unit, building, property)"
    return {
        'object': obj if obj and obj.type == 'object' else None,
        'building': _ancestor(obj, 'building'),
        'property': _ancestor(obj, 'property'),
        }


def _apartment(obj):
    "Rental unit whose use class allows the comparative rent"
    UseClass = Pool().get('real_estate.use_class')
    return bool(obj and obj.type == 'object'
        and UseClass.allows([obj], 'comparative_rent'))


# domain of the rental units with rent survey data and calculations
APARTMENT_DOMAIN = [
    ('type', '=', 'object'),
    ('use_class.adjustment_procedures', 'in', ['comparative_rent']),
    ]


def _survey_version(obj, date):
    "Version of the rent survey of the object's property valid on date"
    prop = _ancestor(obj, 'property') if obj else None
    if not prop or not prop.rent_survey or not date:
        return None
    return prop.rent_survey.version_on(date)


#**********************************************************************
class RentSurvey(ModelSQL, ModelView):
    "Rent Survey"
    __name__ = 'real_estate.rent_survey'

    name = fields.Char("Name", required=True)
    company = fields.Many2One('company.company', "Company", required=True)
    municipality = fields.Char("Municipality",
        help="Area of application of the rent survey.")
    versions = fields.One2Many('real_estate.rent_survey.version', 'survey',
        "Versions")
    current_version = fields.Function(fields.Many2One(
            'real_estate.rent_survey.version', "Current Version"),
        'get_current_version')

    @staticmethod
    def default_company():
        return Transaction().context.get('company')

    def version_on(self, date):
        "Version valid on the date (latest valid_from <= date)"
        found = None
        for version in self.versions:
            if version.valid_from and version.valid_from <= date and (
                    not found or version.valid_from > found.valid_from):
                found = version
        return found

    def get_current_version(self, name):
        version = self.version_on(Pool().get('ir.date').today())
        return version.id if version else None


class _VersionChild:
    "Records of a version: read-only once the version is locked"
    __slots__ = ()

    @classmethod
    def _versions(cls, records, values=None):
        raise NotImplementedError

    @classmethod
    def check_modification(cls, mode, records, values=None, external=False):
        super().check_modification(
            mode, records, values=values, external=external)
        Version = Pool().get('real_estate.rent_survey.version')
        versions = cls._versions(records, values)
        for version in Version.browse([v for v in versions if v]):
            if version.locked:
                raise AccessError(gettext(
                        'real_estate.msg_rent_survey_version_locked',
                        version=version.rec_name))


#**********************************************************************
class RentSurveyVersion(ModelSQL, ModelView):
    "Rent Survey Version"
    __name__ = 'real_estate.rent_survey.version'

    _locked = {'readonly': Eval('locked', False)}

    survey = fields.Many2One('real_estate.rent_survey', "Rent Survey",
        required=True, ondelete='CASCADE', states=_locked)
    name = fields.Char("Name", required=True)
    valid_from = fields.Date("Valid from", required=True, states=_locked)
    valid_to = fields.Function(fields.Date("Valid to"), 'get_valid_to')
    survey_date = fields.Date("Survey Date",
        help="Key date of the data collection (information).")
    kind = fields.Selection([
            ('simple', "Simple"),
            ('qualified', "Qualified"),
            ], "Kind", required=True, sort=False, states=_locked,
        help="Qualified rent survey: mandatory information in the rent "
             "increase request (§ 558a para. 3 BGB).")
    method = fields.Selection([
            ('table', "Table"),
            ('regression', "Regression"),
            ], "Method", required=True, sort=False, states=_locked,
        help="Table: the table cell gives the range, feature groups move "
             "from the mean towards the upper or lower value. Regression: "
             "the cell gives the base value, features add percentages or "
             "amounts.")
    rent_definition = fields.Text("Rent Definition",
        help="Definition of the rent and scope of application.")
    area_measurement_type = fields.Many2One('real_estate.measurement.type',
        "Living Space Measurement", required=True, ondelete='RESTRICT',
        states=_locked)
    measurement_types = fields.Many2Many(
        'real_estate.rent_survey.version-measurement.type', 'version',
        'measurement_type', "Further Measurements", states=_locked,
        help="Shown in the protocol (e.g. number of rooms).")
    group_percent = fields.Numeric("Group Effect (%)", digits=(16, 2),
        states={
            'invisible': Eval('method') != 'table',
            'readonly': Eval('locked', False),
            },
        help="Effect of one feature group in % of the distance from the "
             "mean to the upper resp. lower value.")
    group_netting = fields.Boolean("Net Groups",
        states={
            'invisible': Eval('method') != 'table',
            'readonly': Eval('locked', False),
            },
        help="Positive and negative groups are netted against each other.")
    spread_lower_percent = fields.Numeric("Spread Lower (%)",
        digits=(16, 2),
        states={
            'invisible': Eval('method') != 'regression',
            'readonly': Eval('locked', False),
            },
        help="E.g. -15: lower value = result - 15 %.")
    spread_upper_percent = fields.Numeric("Spread Upper (%)",
        digits=(16, 2),
        states={
            'invisible': Eval('method') != 'regression',
            'readonly': Eval('locked', False),
            },
        help="E.g. 15: upper value = result + 15 %.")
    round_digits = fields.Integer("Rounding Digits", required=True,
        states=_locked)
    dimensions = fields.One2Many('real_estate.rent_survey.dimension',
        'version', "Classification Features", states=_locked)
    cells = fields.One2Many('real_estate.rent_survey.cell', 'version',
        "Table Cells", states=_locked)
    groups = fields.One2Many('real_estate.rent_survey.group', 'version',
        "Feature Groups", states=_locked)
    source_document = fields.Char("Source Document",
        help="Reference or URL of the official document - the document "
             "itself is attached to the version.")
    check_result = fields.Text("Check Result", readonly=True)
    locked = fields.Function(fields.Boolean("Locked",
            help="An accepted calculation uses this version: classes, "
                 "table, features and rules are read-only (correction by "
                 "a new version)."), 'get_locked')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._order = [('valid_from', 'DESC'), ('id', 'DESC')]
        t = cls.__table__()
        cls._sql_constraints = [
            ('valid_from_unique', Unique(t, t.survey, t.valid_from),
                'real_estate.msg_rent_survey_version_unique'),
            ]
        cls._buttons.update({
            'check': {},
            'import_data': {
                'readonly': Eval('locked', False),
                'depends': ['locked'],
                },
            'new_version': {},
            })

    @staticmethod
    def default_kind():
        return 'qualified'

    @staticmethod
    def default_method():
        return 'table'

    @staticmethod
    def default_group_percent():
        return Decimal(20)

    @staticmethod
    def default_group_netting():
        return True

    @staticmethod
    def default_round_digits():
        return 2

    @staticmethod
    def default_area_measurement_type():
        try:
            return Pool().get('ir.model.data').get_id(
                'real_estate', 'measurement_living_space_type')
        except KeyError:
            return None

    @staticmethod
    def default_measurement_types():
        try:
            return [Pool().get('ir.model.data').get_id(
                    'real_estate', 'measurement_number_of_rooms_type')]
        except KeyError:
            return []

    def get_valid_to(self, name):
        later = [v.valid_from for v in self.survey.versions
            if v.valid_from and self.valid_from
            and v.valid_from > self.valid_from]
        return (min(later) - datetime.timedelta(days=1)) if later else None

    @classmethod
    def get_locked(cls, versions, name):
        Calculation = Pool().get('real_estate.rent_survey.calculation')
        locked = {c.version.id for c in Calculation.search([
                    ('version', 'in', [v.id for v in versions]),
                    ('state', '=', 'accepted'),
                    ])}
        return {v.id: v.id in locked for v in versions}

    @classmethod
    def check_modification(cls, mode, versions, values=None, external=False):
        super().check_modification(
            mode, versions, values=values, external=external)
        free = {'name', 'survey_date', 'rent_definition', 'source_document',
            'check_result'}
        if mode == 'delete' or (mode == 'write' and set(values or {}) - free):
            for version in versions:
                if version.locked:
                    raise AccessError(gettext(
                            'real_estate.msg_rent_survey_version_locked',
                            version=version.rec_name))

    def check_data(self):
        """Consistency of the version (spec 4.4): one class per
        classification feature in every cell, lower <= mean <= upper, no
        overlapping area ranges per class combination. Returns the list of
        problems."""
        problems = []
        dimension_ids = {d.id for d in self.dimensions}
        ranges = {}
        for cell in self.cells:
            dims = sorted(c.dimension.id for c in cell.classes)
            if sorted(dimension_ids) != dims:
                problems.append(gettext(
                        'real_estate.msg_rent_survey_cell_classes',
                        cell=cell.code))
            if self.method == 'table' and None not in (
                    cell.lower, cell.mean, cell.upper) and not (
                    cell.lower <= cell.mean <= cell.upper):
                problems.append(gettext(
                        'real_estate.msg_rent_survey_cell_values',
                        cell=cell.code))
            if cell.mean is None:
                problems.append(gettext(
                        'real_estate.msg_rent_survey_cell_values',
                        cell=cell.code))
            key = tuple(sorted(c.id for c in cell.classes))
            ranges.setdefault(key, []).append(cell)
        problems.extend(_overlaps(
                [(c.code, c.area_min, c.area_max, key)
                    for key, cells in ranges.items() for c in cells],
                key=lambda i: i[3]))
        return problems

    @classmethod
    @ModelView.button
    def check(cls, versions):
        Date = Pool().get('ir.date')
        for version in versions:
            problems = version.check_data()
            cls.write([version], {'check_result': '\n'.join(
                        [Date.today().strftime('%d.%m.%Y') + ': ' + (
                                gettext('real_estate.msg_rent_survey_check_ok')
                                if not problems else gettext(
                                    'real_estate.msg_rent_survey_check_problems',
                                    count=len(problems)))]
                        + problems)})

    @classmethod
    @ModelView.button_action('real_estate.wizard_rent_survey_import')
    def import_data(cls, versions):
        pass

    @classmethod
    @ModelView.button_action('real_estate.wizard_rent_survey_new_version')
    def new_version(cls, versions):
        pass

    def copy_to(self, values):
        """Copy the version with its classification features, classes,
        cells, groups and features (codes kept) - returns the new version"""
        pool = Pool()
        Dimension = pool.get('real_estate.rent_survey.dimension')
        Class = pool.get('real_estate.rent_survey.dimension.class')
        Cell = pool.get('real_estate.rent_survey.cell')
        Group = pool.get('real_estate.rent_survey.group')
        Feature = pool.get('real_estate.rent_survey.feature')
        version, = self.copy([self], default=dict(values, dimensions=None,
                cells=None, groups=None, check_result=None))
        class_map = {}
        for dimension in self.dimensions:
            new_dim, = Dimension.copy([dimension], default={
                    'version': version.id, 'classes': None})
            for class_ in dimension.classes:
                new_class, = Class.copy([class_], default={
                        'dimension': new_dim.id})
                class_map[class_.id] = new_class.id
        for cell in self.cells:
            Cell.copy([cell], default={'version': version.id,
                    'classes': [class_map[c.id] for c in cell.classes]})
        feature_map, exclusive = {}, []
        for group in self.groups:
            new_group, = Group.copy([group], default={
                    'version': version.id, 'features': None})
            for feature in group.features:
                new_feature, = Feature.copy([feature], default={
                        'group': new_group.id,
                        'applies_to_classes': [class_map[c.id]
                            for c in feature.applies_to_classes],
                        'exclusive_with': None,
                        })
                feature_map[feature.id] = new_feature.id
                exclusive.append(feature)
        for feature in exclusive:
            if feature.exclusive_with:
                Feature.write([Feature(feature_map[feature.id])], {
                        'exclusive_with': [('add', [feature_map[f.id]
                                    for f in feature.exclusive_with])]})
        return version


def _overlaps(ranges, key):
    """Problems of overlapping area ranges: ranges = (code, min, max),
    grouped by key"""
    problems, groups = [], {}
    for item in ranges:
        groups.setdefault(key(item), []).append(item)
    for items in groups.values():
        items = sorted(items, key=lambda i: (i[1] is not None, i[1] or 0))
        for a, b in zip(items, items[1:]):
            a_max = a[2]
            b_min = b[1]
            if a_max is None or b_min is None or b_min < a_max:
                problems.append(gettext(
                        'real_estate.msg_rent_survey_cell_overlap',
                        cell=a[0], other=b[0]))
    return problems


class RentSurveyVersionMeasurementType(ModelSQL):
    "Rent Survey Version - Measurement Type"
    __name__ = 'real_estate.rent_survey.version-measurement.type'

    version = fields.Many2One('real_estate.rent_survey.version', "Version",
        required=True, ondelete='CASCADE')
    measurement_type = fields.Many2One('real_estate.measurement.type',
        "Measurement Type", required=True, ondelete='CASCADE')


#**********************************************************************
class RentSurveyDimension(_VersionChild, sequence_ordered(), ModelSQL,
        ModelView):
    "Rent Survey Classification Feature"
    __name__ = 'real_estate.rent_survey.dimension'

    version = fields.Many2One('real_estate.rent_survey.version', "Version",
        required=True, ondelete='CASCADE')
    code = fields.Char("Code", required=True)
    name = fields.Char("Name", required=True)
    level = fields.Selection(LEVELS, "Level", required=True, sort=False,
        help="Level on which the class is normally assigned - a lower "
             "level overrides.")
    source = fields.Selection([
            ('manual', "Manual"),
            ('year_of_construction', "Year of Construction"),
            ('measurement', "Measurement"),
            ], "Source", required=True, sort=False,
        help="Manual selection, or derived from the year of construction "
             "of the building resp. a measurement (a manual assignment "
             "has priority).")
    measurement_type = fields.Many2One('real_estate.measurement.type',
        "Measurement Type", ondelete='RESTRICT',
        states={
            'invisible': Eval('source') != 'measurement',
            'required': Eval('source') == 'measurement',
            })
    classes = fields.One2Many('real_estate.rent_survey.dimension.class',
        'dimension', "Classes")

    @classmethod
    def __setup__(cls):
        super().__setup__()
        t = cls.__table__()
        cls._sql_constraints = [
            ('code_unique', Unique(t, t.version, t.code),
                'real_estate.msg_rent_survey_code_unique'),
            ]

    @staticmethod
    def default_level():
        return 'property'

    @staticmethod
    def default_source():
        return 'manual'

    @classmethod
    def _versions(cls, records, values=None):
        return [r.version.id for r in records] + [
            (values or {}).get('version')]

    def get_rec_name(self, name):
        return self.name or self.code


class RentSurveyDimensionClass(_VersionChild, sequence_ordered(), ModelSQL,
        ModelView):
    "Rent Survey Class"
    __name__ = 'real_estate.rent_survey.dimension.class'

    dimension = fields.Many2One('real_estate.rent_survey.dimension',
        "Classification Feature", required=True, ondelete='CASCADE')
    version = fields.Function(fields.Many2One(
            'real_estate.rent_survey.version', "Version"),
        'on_change_with_version', searcher='search_version')
    code = fields.Char("Code", required=True)
    name = fields.Char("Name", required=True)
    value_min = fields.Numeric("From Value", digits=(16, 2),
        help="Derived class: value_min <= value < value_max (empty = "
             "open), e.g. year of construction 1950 to 1965.")
    value_max = fields.Numeric("To Value (excl.)", digits=(16, 2))
    manual_only = fields.Boolean("Manual Only",
        help="Assigned manually only, never derived (e.g. special "
             "classes).")

    @classmethod
    def __setup__(cls):
        super().__setup__()
        t = cls.__table__()
        cls._sql_constraints = [
            ('code_unique', Unique(t, t.dimension, t.code),
                'real_estate.msg_rent_survey_code_unique'),
            ]

    @fields.depends('dimension', '_parent_dimension.version')
    def on_change_with_version(self, name=None):
        return self.dimension.version if self.dimension else None

    @classmethod
    def search_version(cls, name, clause):
        return [('dimension.version',) + tuple(clause[1:])]

    @classmethod
    def _versions(cls, records, values=None):
        Dimension = Pool().get('real_estate.rent_survey.dimension')
        result = [r.dimension.version.id for r in records]
        if (values or {}).get('dimension'):
            result.append(Dimension(values['dimension']).version.id)
        return result

    def get_rec_name(self, name):
        dimension = self.dimension.rec_name if self.dimension else ''
        return f'{dimension}: {self.name or self.code}'

    @classmethod
    def search_rec_name(cls, name, clause):
        return ['OR',
            ('name',) + tuple(clause[1:]),
            ('code',) + tuple(clause[1:]),
            ('dimension.name',) + tuple(clause[1:]),
            ('dimension.code',) + tuple(clause[1:]),
            ]


#**********************************************************************
class RentSurveyCell(_VersionChild, ModelSQL, ModelView):
    "Rent Survey Table Cell"
    __name__ = 'real_estate.rent_survey.cell'

    version = fields.Many2One('real_estate.rent_survey.version', "Version",
        required=True, ondelete='CASCADE')
    code = fields.Char("Code", required=True,
        help="Row resp. cell of the rent survey table.")
    classes = fields.Many2Many('real_estate.rent_survey.cell-class', 'cell',
        'class_', "Classes",
        domain=[('dimension.version', '=', Eval('version', -1))],
        help="Exactly one class per classification feature.")
    classes_text = fields.Function(fields.Char("Classes"),
        'get_classes_text')
    area_min = fields.Numeric("Area from", digits=(16, 2),
        help="area_min <= living space < area_max (empty = open).")
    area_max = fields.Numeric("Area to (excl.)", digits=(16, 2))
    lower = fields.Numeric("Lower Value", digits=(16, 2))
    mean = fields.Numeric("Mean Value", digits=(16, 2), required=True,
        help="Regression: base value.")
    upper = fields.Numeric("Upper Value", digits=(16, 2))
    qualified = fields.Boolean("Qualified",
        help="Cell within the qualified scope of the rent survey.")
    note = fields.Char("Note")

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._order = [('version', 'ASC'), ('code', 'ASC'), ('id', 'ASC')]
        t = cls.__table__()
        cls._sql_constraints = [
            ('code_unique', Unique(t, t.version, t.code),
                'real_estate.msg_rent_survey_code_unique'),
            ]

    @staticmethod
    def default_qualified():
        return True

    def get_classes_text(self, name):
        return ', '.join(c.name or c.code for c in sorted(self.classes,
                key=lambda c: (c.dimension.sequence or 0, c.dimension.id)))

    @classmethod
    def validate_fields(cls, cells, field_names):
        super().validate_fields(cells, field_names)
        for cell in cells:
            dims = [c.dimension.id for c in cell.classes]
            if len(dims) != len(set(dims)):
                raise ValidationError(gettext(
                        'real_estate.msg_rent_survey_cell_classes',
                        cell=cell.code))

    @classmethod
    def _versions(cls, records, values=None):
        return [r.version.id for r in records] + [
            (values or {}).get('version')]

    def get_rec_name(self, name):
        return f'{self.code} ({self.classes_text})'


class RentSurveyCellClass(ModelSQL):
    "Rent Survey Table Cell - Class"
    __name__ = 'real_estate.rent_survey.cell-class'

    cell = fields.Many2One('real_estate.rent_survey.cell', "Cell",
        required=True, ondelete='CASCADE')
    class_ = fields.Many2One('real_estate.rent_survey.dimension.class',
        "Class", required=True, ondelete='CASCADE')


#**********************************************************************
class RentSurveyGroup(_VersionChild, sequence_ordered(), ModelSQL,
        ModelView):
    "Rent Survey Feature Group"
    __name__ = 'real_estate.rent_survey.group'

    version = fields.Many2One('real_estate.rent_survey.version', "Version",
        required=True, ondelete='CASCADE')
    code = fields.Char("Code", required=True)
    name = fields.Char("Name", required=True)
    rule = fields.Selection([
            ('majority', "Majority"),
            ('additive', "Additive"),
            ], "Rule", required=True, sort=False,
        help="Majority: the group counts +1 / 0 / -1 depending on whether "
             "positive or negative features prevail. Additive: every "
             "feature acts with its own value (regression, special "
             "surcharges and reductions).")
    features = fields.One2Many('real_estate.rent_survey.feature', 'group',
        "Features")

    @classmethod
    def __setup__(cls):
        super().__setup__()
        t = cls.__table__()
        cls._sql_constraints = [
            ('code_unique', Unique(t, t.version, t.code),
                'real_estate.msg_rent_survey_code_unique'),
            ]

    @staticmethod
    def default_rule():
        return 'majority'

    @classmethod
    def _versions(cls, records, values=None):
        return [r.version.id for r in records] + [
            (values or {}).get('version')]

    def get_rec_name(self, name):
        return f'{self.code} {self.name}'


class RentSurveyFeature(_VersionChild, sequence_ordered(), ModelSQL,
        ModelView):
    "Rent Survey Feature"
    __name__ = 'real_estate.rent_survey.feature'

    group = fields.Many2One('real_estate.rent_survey.group', "Group",
        required=True, ondelete='CASCADE')
    version = fields.Function(fields.Many2One(
            'real_estate.rent_survey.version', "Version"),
        'on_change_with_version', searcher='search_version')
    code = fields.Char("Code", required=True,
        help="Unique per version and stable over the versions.")
    name = fields.Char("Name", required=True)
    description = fields.Text("Description",
        help="Wording of the rent survey.")
    direction = fields.Selection([
            ('plus', "Increasing (+)"),
            ('minus', "Reducing (-)"),
            ], "Direction", required=True, sort=False)
    effect = fields.Selection([
            ('vote', "Vote"),
            ('percent', "Percent"),
            ('amount', "Amount per m²"),
            ], "Effect", required=True, sort=False,
        help="Vote: counts for the majority of the group. Percent / "
             "amount: surcharge or reduction (sign by the direction).")
    value = fields.Numeric("Value", digits=(16, 2),
        states={
            'invisible': Eval('effect') == 'vote',
            'required': Eval('effect') != 'vote',
            })
    level = fields.Selection(LEVELS, "Level", required=True, sort=False,
        help="Level on which the feature is assigned.")
    applies_to_classes = fields.Many2Many(
        'real_estate.rent_survey.feature-class', 'feature', 'class_',
        "Only for Classes",
        domain=[('dimension.version', '=', Eval('version', -1))],
        help="The feature counts only with one of these classes (empty = "
             "always).")
    auto_measurement_type = fields.Many2One('real_estate.measurement.type',
        "Automatic by Measurement", ondelete='RESTRICT',
        help="Set automatically when the measurement of the object of the "
             "level is within the range.")
    auto_min = fields.Numeric("Automatic from", digits=(16, 2),
        states={'invisible': ~Eval('auto_measurement_type')})
    auto_max = fields.Numeric("Automatic to (excl.)", digits=(16, 2),
        states={'invisible': ~Eval('auto_measurement_type')})
    exclusive_with = fields.Many2Many(
        'real_estate.rent_survey.feature-feature', 'feature', 'other',
        "Excludes",
        domain=[
            ('version', '=', Eval('version', -1)),
            ('id', '!=', Eval('id', -1)),
            ])

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._order = [('group', 'ASC'), ('sequence', 'ASC'), ('id', 'ASC')]

    @staticmethod
    def default_direction():
        return 'plus'

    @staticmethod
    def default_effect():
        return 'vote'

    @staticmethod
    def default_level():
        return 'object'

    @fields.depends('group', '_parent_group.version')
    def on_change_with_version(self, name=None):
        return self.group.version if self.group else None

    @classmethod
    def search_version(cls, name, clause):
        return [('group.version',) + tuple(clause[1:])]

    @classmethod
    def validate_fields(cls, features, field_names):
        super().validate_fields(features, field_names)
        if field_names and not {'code', 'group'} & set(field_names):
            return
        for feature in features:
            others = cls.search([
                    ('code', '=', feature.code),
                    ('group.version', '=', feature.group.version.id),
                    ('id', '!=', feature.id),
                    ], limit=1)
            if others:
                raise ValidationError(gettext(
                        'real_estate.msg_rent_survey_code_unique'))

    @classmethod
    def _versions(cls, records, values=None):
        Group = Pool().get('real_estate.rent_survey.group')
        result = [r.group.version.id for r in records]
        if (values or {}).get('group'):
            result.append(Group(values['group']).version.id)
        return result

    def get_rec_name(self, name):
        sign = '+' if self.direction == 'plus' else '−'
        return f'{sign} {self.name}'

    @classmethod
    def search_rec_name(cls, name, clause):
        return ['OR',
            ('name',) + tuple(clause[1:]),
            ('code',) + tuple(clause[1:]),
            ]


class RentSurveyFeatureClass(ModelSQL):
    "Rent Survey Feature - Class"
    __name__ = 'real_estate.rent_survey.feature-class'

    feature = fields.Many2One('real_estate.rent_survey.feature', "Feature",
        required=True, ondelete='CASCADE')
    class_ = fields.Many2One('real_estate.rent_survey.dimension.class',
        "Class", required=True, ondelete='CASCADE')


class RentSurveyFeatureFeature(ModelSQL):
    "Rent Survey Feature - Excluded Feature"
    __name__ = 'real_estate.rent_survey.feature-feature'

    feature = fields.Many2One('real_estate.rent_survey.feature', "Feature",
        required=True, ondelete='CASCADE')
    other = fields.Many2One('real_estate.rent_survey.feature',
        "Excluded Feature", required=True, ondelete='CASCADE')


#**********************************************************************
# Import (spec 7, F9)

def _parse_decimal(text):
    text = (text or '').strip()
    if not text:
        return None
    return Decimal(text.replace('.', '').replace(',', '.')
        if ',' in text else text)


def _pairs(text):
    "'location=medium,age=to_1918' -> [('location', 'medium'), ...]"
    result = []
    for part in (text or '').split(','):
        part = part.strip()
        if part:
            dimension, _, class_ = part.partition('=')
            result.append((dimension.strip(), class_.strip()))
    return result


def parse_cells(content, version):
    """Parse the CSV of table cells - returns (values, problems); values
    are dicts for real_estate.rent_survey.cell (classes as ids)"""
    classes = {(c.dimension.code, c.code): c.id
        for d in version.dimensions for c in d.classes}
    values, problems = [], []
    for number, row in enumerate(csv.reader(
                io.StringIO(content), delimiter=';'), 1):
        if not row or not ''.join(row).strip() or row[0].strip() == 'code':
            continue
        row = (row + [''] * 9)[:9]
        code, dims, area_min, area_max, lower, mean, upper, qualified, note \
            = [c.strip() for c in row]
        try:
            class_ids = []
            for pair in _pairs(dims):
                if pair not in classes:
                    raise ValueError(gettext(
                            'real_estate.msg_rent_survey_import_class',
                            dimension=pair[0], class_=pair[1]))
                class_ids.append(classes[pair])
            value = {
                'code': code,
                'classes': [('add', class_ids)],
                'area_min': _parse_decimal(area_min),
                'area_max': _parse_decimal(area_max),
                'lower': _parse_decimal(lower),
                'mean': _parse_decimal(mean),
                'upper': _parse_decimal(upper),
                'qualified': qualified not in ('0', 'n', 'no', 'nein'),
                'note': note or None,
                '_key': tuple(sorted(class_ids)),
                }
        except Exception as exception:
            problems.append(f'{number}: {exception}')
            continue
        if value['mean'] is None or (version.method == 'table' and (
                    value['lower'] is None or value['upper'] is None
                    or not value['lower'] <= value['mean']
                    <= value['upper'])):
            problems.append(f'{number}: ' + gettext(
                    'real_estate.msg_rent_survey_cell_values', cell=code))
        if len(class_ids) != len(version.dimensions):
            problems.append(f'{number}: ' + gettext(
                    'real_estate.msg_rent_survey_cell_classes', cell=code))
        values.append(value)
    problems.extend(_overlaps(
            [(v['code'], v['area_min'], v['area_max'], v['_key'])
                for v in values], key=lambda i: i[3]))
    return values, problems


def parse_features(content, version):
    """Parse the CSV of features - returns (values, problems); values are
    dicts with the group code and the codes of the exclusions"""
    MeasurementType = Pool().get('real_estate.measurement.type')
    ModelData = Pool().get('ir.model.data')
    classes = {(c.dimension.code, c.code): c.id
        for d in version.dimensions for c in d.classes}
    values, problems = [], []
    for number, row in enumerate(csv.reader(
                io.StringIO(content), delimiter=';'), 1):
        if (not row or not ''.join(row).strip()
                or row[0].strip() == 'group_code'):
            continue
        row = [c.strip() for c in (row + [''] * 13)[:13]]
        (group, code, direction, effect, value, level, applies_to, auto,
            auto_min, auto_max, name, description, exclusive) = row
        try:
            if direction not in ('plus', 'minus'):
                raise ValueError(f'direction "{direction}"')
            if effect not in ('vote', 'percent', 'amount'):
                raise ValueError(f'effect "{effect}"')
            if level not in dict(LEVELS):
                raise ValueError(f'level "{level}"')
            class_ids = []
            for pair in _pairs(applies_to):
                if pair not in classes:
                    raise ValueError(gettext(
                            'real_estate.msg_rent_survey_import_class',
                            dimension=pair[0], class_=pair[1]))
                class_ids.append(classes[pair])
            auto_type = None
            if auto:
                # XML id of a delivered type (language independent) or
                # the name of the measurement type
                data = ModelData.search([
                        ('model', '=', MeasurementType.__name__),
                        ('fs_id', '=', auto),
                        ], limit=1)
                types = (MeasurementType.browse([data[0].db_id]) if data
                    else MeasurementType.search([('name', '=', auto)],
                        limit=1))
                if not types:
                    raise ValueError(gettext(
                            'real_estate.msg_rent_survey_import_measurement',
                            measurement=auto))
                auto_type = types[0].id
            values.append({
                    '_group': group,
                    '_exclusive': [c.strip() for c in exclusive.split(',')
                        if c.strip()],
                    'code': code,
                    'name': name or code,
                    'description': description or None,
                    'direction': direction,
                    'effect': effect,
                    'value': _parse_decimal(value),
                    'level': level,
                    'applies_to_classes': [('add', class_ids)],
                    'auto_measurement_type': auto_type,
                    'auto_min': _parse_decimal(auto_min),
                    'auto_max': _parse_decimal(auto_max),
                    })
        except Exception as exception:
            problems.append(f'{number}: {exception}')
    codes = [v['code'] for v in values]
    for code in {c for c in codes if codes.count(c) > 1}:
        problems.append(gettext('real_estate.msg_rent_survey_code_unique')
            + f' ({code})')
    known = set(codes) | {f.code for g in version.groups for f in g.features}
    for value in values:
        for other in value['_exclusive']:
            if other not in known:
                problems.append(f'{value["code"]}: ' + gettext(
                        'real_estate.msg_rent_survey_import_feature',
                        feature=other))
    return values, problems


class RentSurveyImportStart(ModelView):
    "Import Rent Survey Data"
    __name__ = 'real_estate.rent_survey.import.start'

    kind = fields.Selection([
            ('cells', "Table Cells"),
            ('features', "Features"),
            ], "Data", required=True, sort=False)
    file_ = fields.Binary("CSV File", required=True,
        help="Separator ';', decimal comma or point, first line with "
             "'code' resp. 'group_code' is the header.")
    replace = fields.Boolean("Replace Existing",
        help="Delete the existing table cells resp. features of the "
             "version before the import.")

    @staticmethod
    def default_kind():
        return 'cells'


class RentSurveyImportPreview(ModelView):
    "Import Rent Survey Data - Preview"
    __name__ = 'real_estate.rent_survey.import.preview'

    preview = fields.Text("Preview", readonly=True)
    problems = fields.Text("Problems", readonly=True)


class RentSurveyImport(Wizard):
    "Import Rent Survey Data"
    __name__ = 'real_estate.rent_survey.import'

    start = StateView('real_estate.rent_survey.import.start',
        'real_estate.rent_survey_import_start_view_form', [
            Button("Cancel", 'end', 'tryton-cancel'),
            Button("Preview", 'preview', 'tryton-forward', default=True),
            ])
    preview = StateView('real_estate.rent_survey.import.preview',
        'real_estate.rent_survey_import_preview_view_form', [
            Button("Back", 'start', 'tryton-back'),
            Button("Import", 'import_', 'tryton-ok', default=True,
                states={'readonly': Bool(Eval('problems'))}),
            ])
    import_ = StateTransition()

    def _content(self):
        data = self.start.file_ or b''
        for encoding in ('utf-8-sig', 'cp1252'):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        return data.decode('latin-1')

    def _parse(self):
        parse = parse_cells if self.start.kind == 'cells' else parse_features
        return parse(self._content(), self.record)

    def default_preview(self, fields):
        values, problems = self._parse()
        if self.start.kind == 'cells':
            lines = [f"{v['code']}: {v['area_min'] or ''}–"
                f"{v['area_max'] or ''} m² {v['lower'] or ''} / {v['mean']}"
                f" / {v['upper'] or ''}" for v in values]
        else:
            lines = [f"{v['_group']} {v['code']} ({v['direction']}, "
                f"{v['effect']}): {v['name']}" for v in values]
        return {
            'preview': '\n'.join([gettext(
                        'real_estate.msg_rent_survey_import_count',
                        count=len(values))] + lines),
            'problems': '\n'.join(problems) or None,
            }

    def transition_import_(self):
        pool = Pool()
        Cell = pool.get('real_estate.rent_survey.cell')
        Group = pool.get('real_estate.rent_survey.group')
        Feature = pool.get('real_estate.rent_survey.feature')
        version = self.record
        values, problems = self._parse()
        if problems:
            raise ValidationError('\n'.join(problems))
        if self.start.kind == 'cells':
            if self.start.replace:
                Cell.delete(list(version.cells))
            Cell.create([dict({k: v for k, v in value.items()
                            if not k.startswith('_')}, version=version.id)
                    for value in values])
            return 'end'
        if self.start.replace:
            Feature.delete([f for g in version.groups for f in g.features])
        groups = {g.code: g for g in version.groups}
        for value in values:
            if value['_group'] not in groups:
                group, = Group.create([{
                            'version': version.id,
                            'code': value['_group'],
                            'name': value['_group'],
                            'rule': ('majority' if value['effect'] == 'vote'
                                else 'additive'),
                            }])
                groups[group.code] = group
        features = Feature.create([dict({k: v for k, v in value.items()
                        if not k.startswith('_')},
                    group=groups[value['_group']].id) for value in values])
        by_code = {f.code: f for g in Group.browse(
                [g.id for g in groups.values()]) for f in g.features}
        for feature, value in zip(features, values):
            if value['_exclusive']:
                Feature.write([feature], {'exclusive_with': [('add', [
                                by_code[c].id for c in value['_exclusive']
                                if c in by_code])]})
        return 'end'


class RentSurveyNewVersionStart(ModelView):
    "New Rent Survey Version"
    __name__ = 'real_estate.rent_survey.new_version.start'

    name = fields.Char("Name", required=True)
    valid_from = fields.Date("Valid from", required=True)
    survey_date = fields.Date("Survey Date")


class RentSurveyNewVersion(Wizard):
    "New Rent Survey Version"
    __name__ = 'real_estate.rent_survey.new_version'

    start = StateView('real_estate.rent_survey.new_version.start',
        'real_estate.rent_survey_new_version_start_view_form', [
            Button("Cancel", 'end', 'tryton-cancel'),
            Button("Create", 'create_', 'tryton-ok', default=True),
            ])
    create_ = StateAction('real_estate.act_rent_survey_version')

    def default_start(self, fields):
        return {'name': self.record.name}

    def do_create_(self, action):
        version = self.record.copy_to({
                'name': self.start.name,
                'valid_from': self.start.valid_from,
                'survey_date': self.start.survey_date,
                })
        action['pyson_domain'] = PYSONEncoder().encode(
            [('id', '=', version.id)])
        action['views'] = list(reversed(action['views']))
        # open the records themselves, not the first tab of the action
        action['domains'] = []
        # the client opens a form-first action without res_id as a new record
        action['res_id'] = [version.id]
        return action, {}


#**********************************************************************
# Data on the object tree (spec 5)

class BaseObjectRentSurveyValue(ModelSQL, ModelView):
    "Rent Survey Data of an Object"
    __name__ = 'real_estate.base_object.rent_survey_value'

    base_object = fields.Many2One('real_estate.base_object', "Object",
        required=True, ondelete='CASCADE')
    kind = fields.Selection([
            ('class', "Class"),
            ('feature', "Feature"),
            ], "Kind", required=True, sort=False)
    version = fields.Function(fields.Many2One(
            'real_estate.rent_survey.version', "Version"),
        'on_change_with_version')
    level = fields.Function(fields.Char("Level"), 'on_change_with_level')
    survey_class = fields.Function(fields.Many2One(
            'real_estate.rent_survey.dimension.class', "Class",
            # evaluated with the values of the object form: a new line
            # gets no client side computation of its own helper fields
            domain=[
                ('dimension.version', '=',
                    Eval('_parent_base_object', {}).get(
                        'rent_survey_version', -1)),
                # level of the classification feature or a higher one
                # (a lower level overrides, a higher one never)
                ('dimension.level', 'in', If(
                        Eval('_parent_base_object', {}).get('type')
                        == 'property', ['property'],
                        If(Eval('_parent_base_object', {}).get('type')
                            == 'building', ['property', 'building'],
                            ['property', 'building', 'object']))),
                ],
            states={
                'invisible': Eval('kind') != 'class',
                'required': Eval('kind') == 'class',
                }),
        'get_survey_class', setter='set_codes')
    survey_feature = fields.Function(fields.Many2One(
            'real_estate.rent_survey.feature', "Feature",
            domain=[
                ('group.version', '=',
                    Eval('_parent_base_object', {}).get(
                        'rent_survey_version', -1)),
                ('level', '=',
                    Eval('_parent_base_object', {}).get('type')),
                ],
            states={
                'invisible': Eval('kind') != 'feature',
                'required': Eval('kind') == 'feature',
                }),
        'get_survey_feature', setter='set_codes')
    dimension_code = fields.Char("Classification Feature Code",
        readonly=True)
    class_code = fields.Char("Class Code", readonly=True)
    feature_code = fields.Char("Feature Code", readonly=True)
    name = fields.Function(fields.Char("Name"), 'get_name',
        searcher='search_name')
    valid_from = fields.Date("Valid from")
    valid_to = fields.Date("Valid to",
        domain=[If(Bool(Eval('valid_to')) & Bool(Eval('valid_from')),
                ('valid_to', '>=', Eval('valid_from', None)), ())])
    evidence = fields.Char("Evidence",
        help="Evidence or note, e.g. 'energy certificate 2021'.")

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._order = [('kind', 'ASC'), ('dimension_code', 'ASC'),
            ('feature_code', 'ASC'), ('id', 'ASC')]

    @staticmethod
    def default_kind():
        return 'feature'

    @fields.depends('base_object', '_parent_base_object.id')
    def on_change_with_version(self, name=None):
        if self.base_object and self.base_object.id is not None \
                and self.base_object.id >= 0:
            return _survey_version(self.base_object,
                Pool().get('ir.date').today())
        return None

    @fields.depends('base_object', '_parent_base_object.type')
    def on_change_with_level(self, name=None):
        return _object_level(self.base_object)

    def get_survey_class(self, name):
        version = self.version
        if not version or self.kind != 'class':
            return None
        for dimension in version.dimensions:
            if dimension.code == self.dimension_code:
                for class_ in dimension.classes:
                    if class_.code == self.class_code:
                        return class_.id
        return None

    def get_survey_feature(self, name):
        version = self.version
        if not version or self.kind != 'feature':
            return None
        for group in version.groups:
            for feature in group.features:
                if feature.code == self.feature_code:
                    return feature.id
        return None

    @classmethod
    def set_codes(cls, records, name, value):
        pool = Pool()
        Class = pool.get('real_estate.rent_survey.dimension.class')
        Feature = pool.get('real_estate.rent_survey.feature')
        if name == 'survey_class':
            class_ = Class(value) if value else None
            cls.write(records, {
                    'dimension_code': class_.dimension.code if class_
                    else None,
                    'class_code': class_.code if class_ else None,
                    })
        else:
            feature = Feature(value) if value else None
            cls.write(records, {
                    'feature_code': feature.code if feature else None,
                    })

    @classmethod
    def search_name(cls, name, clause):
        return ['OR',
            ('class_code',) + tuple(clause[1:]),
            ('feature_code',) + tuple(clause[1:]),
            ]

    def get_name(self, name):
        if self.kind == 'class':
            if self.survey_class:
                return self.survey_class.rec_name
            return f'{self.dimension_code}: {self.class_code} (?)'
        if self.survey_feature:
            return self.survey_feature.rec_name
        return f'{self.feature_code} (?)'


class BaseObject(metaclass=PoolMeta):
    __name__ = 'real_estate.base_object'

    rent_survey = fields.Many2One('real_estate.rent_survey', "Rent Survey",
        ondelete='RESTRICT',
        domain=[('company', '=', Eval('company', -1))],
        states={'invisible': Eval('type') != 'property'},
        help="Rent survey for the residential rental units of the "
             "property.")
    rent_survey_active = fields.Function(fields.Boolean(
            "Rent Survey Active"), 'get_rent_survey_active')
    rent_survey_version = fields.Function(fields.Many2One(
            'real_estate.rent_survey.version', "Rent Survey Version",
            help="Version of the rent survey of the property valid today."),
        'on_change_with_rent_survey_version')
    rent_survey_values = fields.One2Many(
        'real_estate.base_object.rent_survey_value', 'base_object',
        "Rent Survey Classes and Features")
    rent_survey_data = fields.Text("Rent Survey Data",
        help="Remarks and reasons (e.g. reference in the street "
             "directory) - shown in the protocol, not used for the "
             "calculation.")
    rent_survey_calculations = fields.One2Many(
        'real_estate.rent_survey.calculation', 'base_object',
        "Comparative Rent Calculations", readonly=True)

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._buttons.update({
            'rent_survey_features': {
                'invisible': ~Eval('rent_survey_active', False),
                'depends': ['rent_survey_active'],
                },
            'rent_survey_copy': {
                'invisible': (~Eval('rent_survey_active', False)
                    | (Eval('type') != 'object')),
                'depends': ['rent_survey_active', 'type'],
                },
            'rent_survey_copy_building': {
                'invisible': (~Eval('rent_survey_active', False)
                    | (Eval('type') != 'building')),
                'depends': ['rent_survey_active', 'type'],
                },
            'rent_survey_matrix_export': {
                'invisible': (Eval('type') != 'property')
                | ~Eval('rent_survey'),
                'depends': ['type', 'rent_survey'],
                },
            'rent_survey_matrix_import': {
                'invisible': (Eval('type') != 'property')
                | ~Eval('rent_survey'),
                'depends': ['type', 'rent_survey'],
                },
            'rent_survey_calculate': {
                'invisible': (~Eval('rent_survey_active', False)
                    | (Eval('type') != 'object')),
                'depends': ['rent_survey_active', 'type'],
                },
            })

    @classmethod
    def view_attributes(cls):
        return super().view_attributes() + [
            ('//page[@id="page_rent_survey"]', 'states', {
                    'invisible': ~Eval('rent_survey_active', False)
                    & (Eval('type') != 'property'),
                    }, ['rent_survey_active', 'type']),
            # calculations only for rental units
            ('//page[@id="page_rent_survey_calculations"]', 'states', {
                    'invisible': Eval('type') != 'object',
                    }, ['type']),
            ]

    @fields.depends('type', 'rent_survey', 'parent', '_parent_parent.id')
    def on_change_with_rent_survey_version(self, name=None):
        "Valid today - the property's survey also before it is saved"
        if self.type not in dict(LEVELS):
            return None
        today = Pool().get('ir.date').today()
        if self.type == 'property':
            return self.rent_survey.version_on(today) \
                if self.rent_survey else None
        prop = _ancestor(self.parent, 'property') if self.parent else None
        if prop and prop.rent_survey:
            return prop.rent_survey.version_on(today)
        return None

    def get_rent_survey_active(self, name):
        if self.type not in dict(LEVELS):
            return False
        # rental units: only apartments - use class allowing the
        # comparative rent
        if self.type == 'object' and not _apartment(self):
            return False
        prop = _ancestor(self, 'property')
        return bool(prop and prop.rent_survey)

    @classmethod
    @ModelView.button_action('real_estate.wizard_rent_survey_features')
    def rent_survey_features(cls, objects):
        pass

    @classmethod
    @ModelView.button_action('real_estate.wizard_rent_survey_copy')
    def rent_survey_copy(cls, objects):
        pass

    @classmethod
    @ModelView.button_action('real_estate.wizard_rent_survey_copy')
    def rent_survey_copy_building(cls, objects):
        pass

    @classmethod
    @ModelView.button_action('real_estate.wizard_rent_survey_matrix_export')
    def rent_survey_matrix_export(cls, objects):
        pass

    @classmethod
    @ModelView.button_action('real_estate.wizard_rent_survey_matrix_import')
    def rent_survey_matrix_import(cls, objects):
        pass

    @classmethod
    @ModelView.button
    def rent_survey_calculate(cls, objects):
        "Calculate the comparative rent of the rental units as of today"
        pool = Pool()
        Calculation = pool.get('real_estate.rent_survey.calculation')
        Action = pool.get('ir.action')
        ModelData = pool.get('ir.model.data')
        Date = pool.get('ir.date')
        calculations = Calculation.calculate_for([{
                    'base_object': o.id,
                    'company': o.company.id,
                    'key_date': Date.today(),
                    } for o in objects])
        action = Action(ModelData.get_id('real_estate',
                'act_rent_survey_calculation')).get_action_value()
        action['pyson_domain'] = PYSONEncoder().encode(
            [('id', 'in', [c.id for c in calculations])])
        action['views'] = list(reversed(action['views']))
        # open the records themselves, not the first tab of the action
        action['domains'] = []
        # the client opens a form-first action without res_id as a new record
        action['res_id'] = [c.id for c in calculations]
        return action


class RentSurveyFeaturesStart(ModelView):
    "Assign Rent Survey Features"
    __name__ = 'real_estate.rent_survey.features.start'

    base_object = fields.Many2One('real_estate.base_object', "Object",
        readonly=True)
    version = fields.Many2One('real_estate.rent_survey.version', "Version",
        readonly=True)
    level = fields.Char("Level", readonly=True)
    key_date = fields.Date("Key Date", required=True,
        help="Features valid on this date are shown; removed features "
             "with a validity period end the day before.")
    features = fields.Many2Many('real_estate.rent_survey.feature', None,
        None, "Features",
        domain=[
            ('group.version', '=', Eval('version', -1)),
            ('level', '=', Eval('level')),
            ])


# Matrix of the classes and features of the objects of a property (one row
# per building resp. apartment, one column per classification feature and
# per feature of the level) - export, change externally, import

MATRIX_MARKS = {'x', '1', 'ja', 'j', 'yes', 'y', 'true', 'wahr'}


def _matrix_objects(prop, level):
    "Buildings resp. apartments of the property, by name"
    BaseObject = Pool().get('real_estate.base_object')
    domain = [('parent', 'child_of', [prop.id])]
    domain += ([('type', '=', 'building')] if level == 'building'
        else APARTMENT_DOMAIN)
    return BaseObject.search(domain, order=[('name', 'ASC'), ('id', 'ASC')])


def _matrix_columns(version, level):
    """(dimensions, features) of the matrix: classification features
    assignable on the level (their level or a higher one) and the features
    of the level"""
    allowed = {'building': ['property', 'building'],
        'object': ['property', 'building', 'object']}[level]
    dimensions = [d for d in version.dimensions if d.level in allowed]
    features = [f for g in version.groups for f in g.features
        if f.level == level]
    return dimensions, features


def _own_values(obj, date):
    "Assignments of the object valid on the date"
    return [v for v in obj.rent_survey_values if valid_on(v, date)]


def matrix_export(prop, level, date):
    "CSV content of the matrix (header with codes, line '#' with names)"
    version = prop.rent_survey.version_on(date) if prop.rent_survey \
        else None
    if not version:
        raise ValidationError(gettext(
                'real_estate.msg_rent_survey_no_version',
                object=prop.rec_name))
    dimensions, features = _matrix_columns(version, level)
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';', lineterminator='\n')
    writer.writerow(['id', 'object'] + [f'class:{d.code}'
            for d in dimensions] + [f.code for f in features])
    writer.writerow(['#', version.name] + [d.name for d in dimensions]
        + [f'{f.group.code} {f.rec_name}' for f in features])
    for obj in _matrix_objects(prop, level):
        values = _own_values(obj, date)
        classes = {v.dimension_code: v.class_code for v in values
            if v.kind == 'class'}
        codes = {v.feature_code for v in values if v.kind == 'feature'}
        writer.writerow([obj.id, obj.rec_name]
            + [classes.get(d.code, '') for d in dimensions]
            + ['x' if f.code in codes else '' for f in features])
    return output.getvalue()


def matrix_changes(prop, level, date, content):
    """Changes of an edited matrix - returns (changes, problems); a
    change is (object, to_create (values), to_remove (assignments))"""
    BaseObject = Pool().get('real_estate.base_object')
    version = prop.rent_survey.version_on(date) if prop.rent_survey \
        else None
    if not version:
        return [], [gettext('real_estate.msg_rent_survey_no_version',
                object=prop.rec_name)]
    dimensions, features = _matrix_columns(version, level)
    dims = {d.code: d for d in dimensions}
    feature_codes = {f.code for f in features}
    objects = {o.id: o for o in _matrix_objects(prop, level)}
    rows = [r for r in csv.reader(io.StringIO(content), delimiter=';')
        if r and ''.join(r).strip()]
    problems, changes = [], []
    if not rows or rows[0][:1] != ['id']:
        return [], [gettext('real_estate.msg_rent_survey_matrix_header')]
    header = [h.strip() for h in rows[0]]
    columns = []
    for index, code in enumerate(header[2:], 2):
        if code.startswith('class:') and code[6:] in dims:
            columns.append((index, 'class', code[6:]))
        elif code in feature_codes:
            columns.append((index, 'feature', code))
        elif code:
            problems.append(gettext(
                    'real_estate.msg_rent_survey_matrix_column', code=code))
    for number, row in enumerate(rows[1:], 2):
        if row[0].strip().startswith('#'):
            continue
        row = row + [''] * (len(header) - len(row))
        try:
            obj = objects[int(row[0])]
        except (ValueError, KeyError):
            problems.append(gettext(
                    'real_estate.msg_rent_survey_matrix_object',
                    line=number, object=row[0]))
            continue
        current = _own_values(obj, date)
        to_create, to_remove = [], []
        for index, kind, code in columns:
            cell = row[index].strip()
            if kind == 'class':
                present = [v for v in current if v.kind == 'class'
                    and v.dimension_code == code]
                if cell and cell not in {c.code for c in
                        dims[code].classes}:
                    problems.append(gettext(
                            'real_estate.msg_rent_survey_import_class',
                            dimension=code, class_=cell) + f' ({number})')
                    continue
                if [v.class_code for v in present] == ([cell] if cell
                        else []):
                    continue
                to_remove.extend(present)
                if cell:
                    to_create.append({'kind': 'class',
                            'dimension_code': code, 'class_code': cell})
            else:
                present = [v for v in current if v.kind == 'feature'
                    and v.feature_code == code]
                wanted = cell.lower() in MATRIX_MARKS
                if cell and not wanted:
                    problems.append(gettext(
                            'real_estate.msg_rent_survey_matrix_mark',
                            line=number, code=code, value=cell))
                    continue
                if wanted and not present:
                    to_create.append({'kind': 'feature',
                            'feature_code': code})
                elif not wanted and present:
                    to_remove.extend(present)
        if to_create or to_remove:
            changes.append((obj, to_create, to_remove))
    return changes, problems


class RentSurveyMatrixExportStart(ModelView):
    "Export Rent Survey Matrix"
    __name__ = 'real_estate.rent_survey.matrix.export.start'

    property = fields.Many2One('real_estate.base_object', "Property",
        readonly=True)
    level = fields.Selection([
            ('object', "Apartments"),
            ('building', "Buildings"),
            ], "Rows", required=True, sort=False)
    key_date = fields.Date("Key Date", required=True,
        help="Assignments valid on this date, columns of the version "
             "valid on this date.")


class RentSurveyMatrixExportResult(ModelView):
    "Export Rent Survey Matrix"
    __name__ = 'real_estate.rent_survey.matrix.export.result'

    file_ = fields.Binary("File", readonly=True, filename='file_name')
    file_name = fields.Char("File Name", readonly=True)


class RentSurveyMatrixExport(Wizard):
    "Export Rent Survey Matrix"
    __name__ = 'real_estate.rent_survey.matrix.export'

    start = StateView('real_estate.rent_survey.matrix.export.start',
        'real_estate.rent_survey_matrix_export_start_view_form', [
            Button("Cancel", 'end', 'tryton-cancel'),
            Button("Export", 'result', 'tryton-ok', default=True),
            ])
    result = StateView('real_estate.rent_survey.matrix.export.result',
        'real_estate.rent_survey_matrix_export_result_view_form', [
            Button("Close", 'end', 'tryton-close', default=True),
            ])

    def default_start(self, fields):
        return {
            'property': self.record.id,
            'level': 'object',
            'key_date': Pool().get('ir.date').today(),
            }

    def default_result(self, fields):
        content = matrix_export(self.record, self.start.level,
            self.start.key_date)
        name = ''.join(c if c.isalnum() else '_'
            for c in self.record.name).strip('_')
        return {
            # BOM: spreadsheet programs recognize UTF-8
            'file_': content.encode('utf-8-sig'),
            'file_name': f'mietspiegel_{name}_{self.start.level}_'
            f'{self.start.key_date.isoformat()}.csv',
            }


class RentSurveyMatrixImportStart(ModelView):
    "Import Rent Survey Matrix"
    __name__ = 'real_estate.rent_survey.matrix.import.start'

    property = fields.Many2One('real_estate.base_object', "Property",
        readonly=True)
    level = fields.Selection([
            ('object', "Apartments"),
            ('building', "Buildings"),
            ], "Rows", required=True, sort=False)
    key_date = fields.Date("Key Date", required=True,
        help="Assignments valid on this date are compared; removed ones "
             "with a validity period end the day before.")
    file_ = fields.Binary("CSV File", required=True,
        help="Matrix exported for the same property and level, changed "
             "externally (mark 'x' = applies, class code in the class "
             "columns).")


class RentSurveyMatrixImportPreview(ModelView):
    "Import Rent Survey Matrix - Preview"
    __name__ = 'real_estate.rent_survey.matrix.import.preview'

    preview = fields.Text("Changes", readonly=True)
    problems = fields.Text("Problems", readonly=True)


class RentSurveyMatrixImport(Wizard):
    "Import Rent Survey Matrix"
    __name__ = 'real_estate.rent_survey.matrix.import'

    start = StateView('real_estate.rent_survey.matrix.import.start',
        'real_estate.rent_survey_matrix_import_start_view_form', [
            Button("Cancel", 'end', 'tryton-cancel'),
            Button("Preview", 'preview', 'tryton-forward', default=True),
            ])
    preview = StateView('real_estate.rent_survey.matrix.import.preview',
        'real_estate.rent_survey_matrix_import_preview_view_form', [
            Button("Back", 'start', 'tryton-back'),
            Button("Apply", 'apply', 'tryton-ok', default=True,
                states={'readonly': Bool(Eval('problems'))}),
            ])
    apply = StateTransition()

    def default_start(self, fields):
        return {
            'property': self.record.id,
            'level': 'object',
            'key_date': Pool().get('ir.date').today(),
            }

    def _changes(self):
        data = self.start.file_ or b''
        for encoding in ('utf-8-sig', 'cp1252'):
            try:
                content = data.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            content = data.decode('latin-1')
        return matrix_changes(self.record, self.start.level,
            self.start.key_date, content)

    def default_preview(self, fields):
        changes, problems = self._changes()
        lines = [gettext('real_estate.msg_rent_survey_matrix_count',
                count=len(changes))]
        for obj, to_create, to_remove in changes:
            added = [v.get('feature_code') or '%s=%s' % (
                    v['dimension_code'], v['class_code']) for v in to_create]
            removed = [v.feature_code or '%s=%s' % (
                    v.dimension_code, v.class_code) for v in to_remove]
            lines.append(f'{obj.rec_name}: '
                + ', '.join(['+ ' + c for c in added]
                    + ['− ' + c for c in removed]))
        return {
            'preview': '\n'.join(lines),
            'problems': '\n'.join(problems) or None,
            }

    def transition_apply(self):
        Value = Pool().get('real_estate.base_object.rent_survey_value')
        changes, problems = self._changes()
        if problems:
            raise ValidationError('\n'.join(problems))
        date = self.start.key_date
        to_delete, to_end, to_create = [], [], []
        for obj, create, remove in changes:
            for value in remove:
                if _ends(value, date):
                    to_end.append(value)
                else:
                    to_delete.append(value)
            to_create.extend(dict(v, base_object=obj.id) for v in create)
        if to_delete:
            Value.delete(to_delete)
        if to_end:
            Value.write(to_end, {
                    'valid_to': date - datetime.timedelta(days=1)})
        if to_create:
            Value.create(to_create)
        return 'end'


class RentSurveyCopyStart(ModelView):
    "Copy Rent Survey Data from Object"
    __name__ = 'real_estate.rent_survey.copy.start'

    base_object = fields.Many2One('real_estate.base_object', "Object",
        readonly=True)
    property = fields.Many2One('real_estate.base_object', "Property",
        readonly=True)
    type = fields.Char("Type", readonly=True)
    source = fields.Many2One('real_estate.base_object', "Copy from",
        required=True,
        domain=[
            If(Eval('type') == 'building',
                [('type', '=', 'building')], APARTMENT_DOMAIN),
            ('parent', 'child_of', [Eval('property', -1)]),
            ('id', '!=', Eval('base_object', -1)),
            ],
        help="Object of the same kind in the same property (apartment resp. "
             "building) whose classes and features are taken over.")
    key_date = fields.Date("Key Date", required=True,
        help="The assignments of the source valid on this date are "
             "copied.")
    with_classes = fields.Boolean("Including Classes",
        help="Also copy the classes assigned on the source (e.g. a "
             "different location).")
    replace = fields.Boolean("Replace Existing",
        help="Remove the assignments of this object valid on the key date "
             "first (with a validity period: ended the day before), else "
             "only missing ones are added.")


class RentSurveyCopy(Wizard):
    "Copy Rent Survey Data from Object"
    __name__ = 'real_estate.rent_survey.copy'

    start = StateView('real_estate.rent_survey.copy.start',
        'real_estate.rent_survey_copy_start_view_form', [
            Button("Cancel", 'end', 'tryton-cancel'),
            Button("Copy", 'copy_', 'tryton-ok', default=True),
            ])
    copy_ = StateTransition()

    def default_start(self, fields):
        obj = self.record
        prop = _ancestor(obj, 'property')
        return {
            'base_object': obj.id,
            'property': prop.id if prop else None,
            'type': obj.type,
            'key_date': Pool().get('ir.date').today(),
            'with_classes': True,
            }

    def transition_copy_(self):
        Value = Pool().get('real_estate.base_object.rent_survey_value')
        obj, date = self.record, self.start.key_date
        kinds = ['feature'] + (['class'] if self.start.with_classes else [])

        def key(value):
            return (value.kind, value.dimension_code, value.class_code,
                value.feature_code)
        source = [v for v in self.start.source.rent_survey_values
            if v.kind in kinds and valid_on(v, date)]
        current = [v for v in obj.rent_survey_values
            if v.kind in kinds and valid_on(v, date)]
        if self.start.replace:
            ended = [v for v in current if _ends(v, date)]
            Value.delete([v for v in current if v not in ended])
            if ended:
                Value.write(ended, {
                        'valid_to': date - datetime.timedelta(days=1)})
            present = set()
        else:
            # a class of the same classification feature is replaced by
            # the source's only with 'Replace Existing'
            present = {key(v) for v in current} | {
                ('class', v.dimension_code) for v in current
                if v.kind == 'class'}
        to_create = []
        for value in source:
            if key(value) in present or (value.kind == 'class'
                    and ('class', value.dimension_code) in present):
                continue
            to_create.append({
                    'base_object': obj.id,
                    'kind': value.kind,
                    'dimension_code': value.dimension_code,
                    'class_code': value.class_code,
                    'feature_code': value.feature_code,
                    'valid_from': value.valid_from,
                    'valid_to': value.valid_to,
                    'evidence': value.evidence,
                    })
        if to_create:
            Value.create(to_create)
        return 'end'


class RentSurveyFeatures(Wizard):
    "Assign Rent Survey Features"
    __name__ = 'real_estate.rent_survey.features'

    start = StateView('real_estate.rent_survey.features.start',
        'real_estate.rent_survey_features_start_view_form', [
            Button("Cancel", 'end', 'tryton-cancel'),
            Button("Save", 'save', 'tryton-ok', default=True),
            ])
    save = StateTransition()

    def default_start(self, fields):
        obj = self.record
        today = Pool().get('ir.date').today()
        version = _survey_version(obj, today)
        if not version:
            raise ValidationError(gettext(
                    'real_estate.msg_rent_survey_no_version',
                    object=obj.rec_name))
        codes = {v.feature_code for v in obj.rent_survey_values
            if v.kind == 'feature' and valid_on(v, today)}
        return {
            'base_object': obj.id,
            'version': version.id,
            'level': _object_level(obj),
            'key_date': today,
            'features': [f.id for g in version.groups for f in g.features
                if f.code in codes and f.level == _object_level(obj)],
            }

    def transition_save(self):
        Value = Pool().get('real_estate.base_object.rent_survey_value')
        obj = self.record
        date = self.start.key_date
        level_codes = {f.code for g in self.start.version.groups
            for f in g.features if f.level == _object_level(obj)}
        selected = {f.code for f in self.start.features}
        current = [v for v in obj.rent_survey_values
            if v.kind == 'feature' and valid_on(v, date)
            and v.feature_code in level_codes]
        present = {v.feature_code for v in current}
        to_delete, to_end = [], []
        for value in current:
            if value.feature_code not in selected:
                if _ends(value, date):
                    to_end.append(value)
                else:
                    to_delete.append(value)
        if to_delete:
            Value.delete(to_delete)
        if to_end:
            Value.write(to_end, {
                    'valid_to': date - datetime.timedelta(days=1)})
        Value.create([{
                    'base_object': obj.id,
                    'kind': 'feature',
                    'feature_code': code,
                    } for code in sorted(selected - present)])
        return 'end'


#**********************************************************************
# Calculation (spec 6)

class RentSurveyCalculation(Workflow, ModelSQL, ModelView):
    "Comparative Rent Calculation"
    __name__ = 'real_estate.rent_survey.calculation'

    _draft = {'readonly': Eval('state') != 'draft'}

    company = fields.Many2One('company.company', "Company", required=True,
        states=_draft)
    base_object = fields.Many2One('real_estate.base_object', "Rental Unit",
        required=True, ondelete='RESTRICT', states=_draft,
        domain=APARTMENT_DOMAIN + [
            ('company', '=', Eval('company', -1)),
            ])
    building = fields.Many2One('real_estate.base_object', "Building",
        readonly=True)
    property = fields.Many2One('real_estate.base_object', "Property",
        readonly=True)
    contract = fields.Many2One('real_estate.contract', "Contract",
        ondelete='RESTRICT', states=_draft,
        domain=[('company', '=', Eval('company', -1))])
    term = fields.Many2One('real_estate.contract.term', "Term",
        ondelete='RESTRICT', states=_draft,
        domain=[If(Bool(Eval('contract')),
                ('contract', '=', Eval('contract', -1)), ())])
    rent_adjustment = fields.Many2One(
        'real_estate.contract.rent_adjustment', "Rent Adjustment",
        ondelete='RESTRICT', states=_draft,
        domain=[('procedure', '=', 'comparative_rent')])
    key_date = fields.Date("Key Date", required=True, states=_draft)
    version = fields.Many2One('real_estate.rent_survey.version', "Version",
        readonly=True)
    calculated_at = fields.Timestamp("Calculated at", readonly=True)
    inputs_json = fields.Text("Inputs", readonly=True)
    cell = fields.Many2One('real_estate.rent_survey.cell', "Table Cell",
        readonly=True)
    lower = fields.Numeric("Lower Value", digits=(16, 2), readonly=True)
    mean = fields.Numeric("Mean Value", digits=(16, 2), readonly=True)
    upper = fields.Numeric("Upper Value", digits=(16, 2), readonly=True)
    group_results = fields.Text("Group Results", readonly=True)
    net_votes = fields.Integer("Net Groups", readonly=True)
    rent_per_sqm = fields.Numeric("Rent per m²", digits=(16, 2),
        readonly=True)
    area = fields.Numeric("Living Space", digits=(16, 2), readonly=True)
    currency = fields.Function(fields.Many2One('currency.currency',
            "Currency"), 'on_change_with_currency')
    comparative_rent = fields.Function(Monetary("Comparative Rent",
            currency='currency', digits='currency'),
        'get_comparative_rent')
    protocol = fields.Text("Protocol", readonly=True)
    check_state = fields.Selection([
            (None, ''),
            ('ok', "OK"),
            ('warning', "Warning"),
            ('error', "Error"),
            ], "Check", readonly=True, sort=False)
    check_message = fields.Text("Check Messages", readonly=True)
    accepted_rent_per_sqm = fields.Numeric("Accepted Rent per m²",
        digits=(16, 2),
        states={'readonly': Eval('state') != 'calculated'})
    deviation_reason = fields.Text("Reason",
        states={'readonly': Eval('state') != 'calculated'},
        help="Required for the acceptance with warnings or a different "
             "accepted rent per m².")
    accepted_by = fields.Many2One('res.user', "Accepted by", readonly=True)
    accepted_date = fields.Date("Accepted on", readonly=True)
    state = fields.Selection([
            ('draft', "Draft"),
            ('calculated', "Calculated"),
            ('accepted', "Accepted"),
            ('rejected', "Rejected"),
            ], "State", readonly=True, required=True, sort=False)

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._order = [('key_date', 'DESC'), ('id', 'DESC')]
        cls._transitions |= {
            ('calculated', 'accepted'),
            ('calculated', 'rejected'),
            }
        cls._buttons.update({
            'calculate': {
                'invisible': Eval('state') != 'draft',
                'depends': ['state'],
                },
            'accept': {
                'invisible': Eval('state') != 'calculated',
                'depends': ['state'],
                },
            'reject': {
                'invisible': Eval('state') != 'calculated',
                'depends': ['state'],
                },
            'recalculate': {
                'invisible': Eval('state') == 'draft',
                'depends': ['state'],
                },
            })

    @staticmethod
    def default_company():
        return Transaction().context.get('company')

    @staticmethod
    def default_state():
        return 'draft'

    @staticmethod
    def default_key_date():
        return Pool().get('ir.date').today()

    @fields.depends('company')
    def on_change_with_currency(self, name=None):
        return self.company.currency if self.company else None

    def get_comparative_rent(self, name):
        rent = (self.accepted_rent_per_sqm if self.state == 'accepted'
            and self.accepted_rent_per_sqm is not None
            else self.rent_per_sqm)
        if rent is None or self.area is None:
            return None
        return _round(rent * self.area, 2)

    def get_rec_name(self, name):
        return ' '.join(filter(None, [
                    self.base_object.rec_name if self.base_object else '',
                    self.key_date.strftime('%d.%m.%Y')
                    if self.key_date else '']))

    @classmethod
    def search_rec_name(cls, name, clause):
        return [('base_object.rec_name',) + tuple(clause[1:])]

    @classmethod
    def create(cls, vlist):
        BaseObject = Pool().get('real_estate.base_object')
        vlist = [v.copy() for v in vlist]
        for values in vlist:
            if values.get('base_object'):
                obj = BaseObject(values['base_object'])
                building = _ancestor(obj, 'building')
                prop = _ancestor(obj, 'property')
                values['building'] = building.id if building else None
                values['property'] = prop.id if prop else None
        return super().create(vlist)

    @classmethod
    def check_modification(cls, mode, records, values=None, external=False):
        super().check_modification(
            mode, records, values=values, external=external)
        if mode == 'delete':
            # accepted calculations are evidence (version locked)
            for record in records:
                if record.state == 'accepted':
                    raise AccessError(gettext(
                            'real_estate.msg_rent_survey_calculation_delete',
                            calculation=record.rec_name))
        if mode == 'write' and external:
            # acceptance fields, the acceptance itself and the transition
            allowed = {'accepted_rent_per_sqm', 'deviation_reason',
                'accepted_by', 'accepted_date', 'state'}
            for record in records:
                if record.state in ('accepted', 'rejected') or (
                        record.state == 'calculated'
                        and set(values or {}) - allowed):
                    raise AccessError(gettext(
                            'real_estate.msg_rent_survey_calculation_locked',
                            calculation=record.rec_name))

    # ------------------------------------------------------------------
    # Inputs (spec 6.2 steps 1-4)

    def _measurement(self, obj, m_type):
        Measurement = Pool().get('real_estate.measurement')
        if not obj or not m_type:
            return None
        value = Measurement.get_total_value(obj.id, m_type, self.key_date)
        return _dec(value) if value is not None else None

    @staticmethod
    def _year(building):
        try:
            return Decimal(int((building.year_of_construction or '').strip()))
        except (ValueError, AttributeError):
            return None

    def _assignments(self, levels, kind):
        "(level, assignment) valid on the key date, lowest level first"
        result = []
        for level in LEVEL_ORDER:
            obj = levels[level]
            if obj:
                result.extend((level, v) for v in obj.rent_survey_values
                    if v.kind == kind and valid_on(v, self.key_date))
        return result

    def _classify(self, version, levels, inputs, messages):
        "Class per classification feature: manual (lowest level) or derived"
        classes = {}
        assignments = self._assignments(levels, 'class')
        for dimension in version.dimensions:
            by_code = {c.code: c for c in dimension.classes}
            found, origin = None, None
            for level, value in assignments:
                if value.dimension_code == dimension.code:
                    found = by_code.get(value.class_code)
                    origin = ('manual', level, value.evidence)
                    if not found:
                        messages.append(('warning', gettext(
                                    'real_estate.msg_rent_survey_b07',
                                    code=f'{value.dimension_code}='
                                    f'{value.class_code}', level=level)))
                    break
            source_value = None
            if not found and dimension.source != 'manual':
                if dimension.source == 'year_of_construction':
                    source_value = self._year(levels['building'])
                else:
                    source_value = self._measurement(
                        levels[dimension.level], dimension.measurement_type)
                for class_ in dimension.classes:
                    if not class_.manual_only and in_range(source_value,
                            class_.value_min, class_.value_max):
                        found = class_
                        origin = ('derived', dimension.level, source_value)
                        break
            if not found:
                messages.append(('error', gettext(
                            'real_estate.msg_rent_survey_b03',
                            dimension=dimension.name)))
                continue
            classes[dimension.id] = found
            inputs['classes'].append({
                    'dimension': dimension.code,
                    'dimension_name': dimension.name, 'class': found.code,
                    'name': found.name, 'source': origin[0],
                    'level': origin[1],
                    'value': str(origin[2]) if origin[2] is not None
                    else None,
                    })
        return classes

    def _features(self, version, levels, classes, inputs, messages):
        "Assigned and automatic features valid on the key date (spec 6.2.4)"
        by_code = {f.code: f for g in version.groups for f in g.features}
        selected = {}
        for level, value in self._assignments(levels, 'feature'):
            feature = by_code.get(value.feature_code)
            if not feature:
                messages.append(('warning', gettext(
                            'real_estate.msg_rent_survey_b07',
                            code=value.feature_code, level=level)))
                continue
            selected.setdefault(feature.id, (feature, 'manual', level))
        auto_types = set()
        for feature in by_code.values():
            if not feature.auto_measurement_type:
                continue
            auto_types.add(feature.auto_measurement_type)
            value = self._measurement(levels[feature.level],
                feature.auto_measurement_type)
            if in_range(value, feature.auto_min, feature.auto_max):
                selected.setdefault(feature.id,
                    (feature, 'auto', feature.level))
        for m_type in auto_types:
            levels_used = {f.level for f in by_code.values()
                if f.auto_measurement_type == m_type}
            if all(self._measurement(levels[l], m_type) is None
                    for l in levels_used):
                messages.append(('warning', gettext(
                            'real_estate.msg_rent_survey_b09',
                            measurement=m_type.rec_name)))
        class_ids = {c.id for c in classes.values()}
        result = []
        for feature, source, level in selected.values():
            applies = {c.id for c in feature.applies_to_classes}
            if applies and not applies & class_ids:
                inputs['ignored'].append(feature.code)
                continue
            result.append(feature)
            inputs['features'].append({
                    'code': feature.code, 'level': level, 'source': source})
        ids, pairs = {f.id for f in result}, set()
        for feature in result:
            for other in feature.exclusive_with:
                pair = tuple(sorted((feature.id, other.id)))
                if other.id in ids and pair not in pairs:
                    pairs.add(pair)
                    messages.append(('error', gettext(
                                'real_estate.msg_rent_survey_b06',
                                feature=feature.name, other=other.name)))
        return result

    # ------------------------------------------------------------------
    # Workflow

    @classmethod
    @ModelView.button
    def calculate(cls, calculations):
        for calculation in calculations:
            if calculation.state != 'draft':
                continue
            cls.write([calculation], calculation._calculate())

    def _calculate(self):
        pool = Pool()
        Lang = pool.get('ir.lang')
        lang = Lang.get()
        obj = self.base_object
        levels = _levels(obj)
        messages = []
        inputs = {'key_date': str(self.key_date), 'classes': [],
            'features': [], 'ignored': [], 'measurements': {},
            'data': {}}
        values = {
            'calculated_at': datetime.datetime.now(),
            'version': None, 'cell': None, 'lower': None, 'mean': None,
            'upper': None, 'group_results': None, 'net_votes': None,
            'rent_per_sqm': None, 'area': None,
            }

        def num(value, digits=2):
            return lang.format_number(value, digits) if value is not None \
                else ''

        def finish(protocol):
            order = {'error': 0, 'warning': 1, 'info': 2}
            messages.sort(key=lambda m: order[m[0]])
            state = ('error' if any(m[0] == 'error' for m in messages)
                else 'warning' if any(m[0] == 'warning' for m in messages)
                else 'ok')
            labels = {
                'error': gettext('real_estate.msg_rent_survey_error'),
                'warning': gettext('real_estate.msg_rent_survey_warning'),
                'info': gettext('real_estate.msg_rent_survey_info'),
                }
            values.update({
                    'inputs_json': json.dumps(inputs, ensure_ascii=False,
                        indent=1),
                    'protocol': '\n'.join(protocol),
                    'check_state': state,
                    'check_message': '\n'.join(
                        f'{labels[m[0]]}: {m[1]}' for m in messages) or None,
                    'state': 'draft' if state == 'error' else 'calculated',
                    })
            if state != 'error' and self.accepted_rent_per_sqm is None:
                values['accepted_rent_per_sqm'] = values['rent_per_sqm']
            return values

        # B01: residential rental unit, rent survey, valid version
        version = (_survey_version(obj, self.key_date)
            if _apartment(obj) else None)
        if not version:
            messages.append(('error', gettext(
                        'real_estate.msg_rent_survey_b01',
                        object=obj.rec_name if obj else '',
                        date=lang.strftime(self.key_date))))
            return finish([])
        values['version'] = version.id
        inputs['version'] = version.name
        protocol = [gettext('real_estate.msg_rent_survey_protocol_header',
                version=version.name,
                valid_from=lang.strftime(version.valid_from),
                date=lang.strftime(self.key_date))]
        # B02: living space
        area = self._measurement(obj, version.area_measurement_type)
        inputs['area'] = str(area) if area is not None else None
        for m_type in version.measurement_types:
            value = self._measurement(obj, m_type)
            inputs['measurements'][m_type.rec_name] = (
                str(value) if value is not None else None)
        year = self._year(levels['building'])
        inputs['year_of_construction'] = str(year) if year else None
        for level, record in levels.items():
            if record and record.rent_survey_data:
                inputs['data'][level] = record.rent_survey_data
        if not area or area <= 0:
            messages.append(('error', gettext(
                        'real_estate.msg_rent_survey_b02',
                        object=obj.rec_name)))
            return finish(protocol)
        values['area'] = _round(area, 2)
        # B03 / classes
        classes = self._classify(version, levels, inputs, messages)
        if classes:
            protocol.append(' · '.join(
                    gettext('real_estate.msg_rent_survey_protocol_class',
                        dimension=c['dimension_name'], name=c['name'],
                        origin=' '.join(filter(None, [gettext(
                                    'real_estate.msg_rent_survey_origin_'
                                    + c['source']), c['value']])),
                        level=dict(LEVELS)[c['level']])
                    for c in inputs['classes']))
        if any(m[0] == 'error' for m in messages):
            return finish(protocol)
        # B04: table cell
        class_ids = sorted(c.id for c in classes.values())
        cells = [c for c in version.cells
            if sorted(x.id for x in c.classes) == class_ids
            and in_range(area, c.area_min, c.area_max)]
        if len(cells) != 1:
            messages.append(('error', gettext(
                        'real_estate.msg_rent_survey_b04',
                        count=len(cells), area=num(area))))
            return finish(protocol)
        cell, = cells
        values['cell'] = cell.id
        if not cell.qualified:
            messages.append(('warning', gettext(
                        'real_estate.msg_rent_survey_b05', cell=cell.code)))
        protocol.append(gettext('real_estate.msg_rent_survey_protocol_cell',
                area=num(area), cell=cell.code, lower=num(cell.lower),
                mean=num(cell.mean), upper=num(cell.upper)))
        # Features, B06
        features = self._features(version, levels, classes, inputs,
            messages)
        if any(m[0] == 'error' for m in messages):
            return finish(protocol)
        groups, group_rows = [], []
        for group in version.groups:
            members = [f for f in features if f.group == group]
            groups.append((group.rule, [(f.direction, f.effect, f.value)
                        for f in members]))
            if group.rule == 'majority' and not [
                    f for f in members if f.effect == 'vote']:
                messages.append(('info', gettext(
                            'real_estate.msg_rent_survey_b08',
                            group=group.rec_name)))
            group_rows.append((group, members))
        result = compute_rent(version.method, cell.lower, cell.mean,
            cell.upper, groups, version.group_percent or 0,
            version.group_netting, version.spread_lower_percent,
            version.spread_upper_percent, version.round_digits)
        summary = []
        for (group, members), group_result in zip(group_rows,
                result['groups']):
            names = ', '.join(('+ ' if f.direction == 'plus' else '− ')
                + f.name + (f' ({num(f.value)})'
                    if f.effect != 'vote' else '') for f in members)
            shown = (f'{group_result:+d}' if group_result
                else '0') if group_result is not None else ''
            protocol.append(f'{group.rec_name}: {names or "–"}'
                + (f' → {shown}' if shown else ''))
            summary.append({'group': group.code, 'name': group.name,
                    'plus': [f.code for f in members
                        if f.direction == 'plus'],
                    'minus': [f.code for f in members
                        if f.direction == 'minus'],
                    'result': group_result})
        for code in inputs['ignored']:
            protocol.append(gettext(
                    'real_estate.msg_rent_survey_protocol_ignored',
                    feature=code))
        rent = result['rent']
        if version.method == 'table':
            protocol.append(gettext(
                    'real_estate.msg_rent_survey_protocol_table',
                    votes=f"{result['net_votes']:+d}", mean=num(cell.mean),
                    percent=num(version.group_percent or 0, 0),
                    rent=num(rent)))
        else:
            protocol.append(gettext(
                    'real_estate.msg_rent_survey_protocol_regression',
                    mean=num(cell.mean), rent=num(rent),
                    lower=num(result['lower']), upper=num(result['upper'])))
        protocol.append(gettext(
                'real_estate.msg_rent_survey_protocol_result',
                rent=num(rent), area=num(area),
                total=num(_round(rent * values['area'], 2))))
        values.update({
                'lower': result['lower'],
                'mean': _dec(cell.mean),
                'upper': result['upper'],
                'net_votes': result['net_votes'],
                'group_results': json.dumps(summary, ensure_ascii=False,
                    indent=1),
                'rent_per_sqm': rent,
                })
        return finish(protocol)

    @classmethod
    @ModelView.button
    @Workflow.transition('accepted')
    def accept(cls, calculations):
        pool = Pool()
        Date = pool.get('ir.date')
        for calculation in calculations:
            rent = (calculation.accepted_rent_per_sqm
                if calculation.accepted_rent_per_sqm is not None
                else calculation.rent_per_sqm)
            if ((calculation.check_state == 'warning'
                        or rent != calculation.rent_per_sqm)
                    and not (calculation.deviation_reason or '').strip()):
                raise ValidationError(gettext(
                        'real_estate.msg_rent_survey_reason_required',
                        calculation=calculation.rec_name))
            cls.write([calculation], {
                    'accepted_rent_per_sqm': rent,
                    'accepted_by': Transaction().user,
                    'accepted_date': Date.today(),
                    })

    @classmethod
    @ModelView.button
    @Workflow.transition('rejected')
    def reject(cls, calculations):
        pass

    @classmethod
    def calculate_for(cls, vlist):
        """Calculate for the values (object, key date, references): an
        open calculation (draft or calculated) of the same object and key
        date is calculated again instead of creating another one - a new
        one only once the existing ones are accepted or rejected"""
        result = []
        for values in vlist:
            open_ = cls.search([
                    ('base_object', '=', values['base_object']),
                    ('key_date', '=', values['key_date']),
                    ('state', 'in', ['draft', 'calculated']),
                    ], order=[('id', 'DESC')], limit=1)
            if open_:
                calculation, = open_
                refs = {k: v for k, v in values.items()
                    if k in ('contract', 'term', 'rent_adjustment') and v}
                cls.write([calculation], dict(refs, state='draft',
                        accepted_rent_per_sqm=None))
            else:
                calculation, = cls.create([values])
            result.append(calculation)
        cls.calculate(cls.browse([c.id for c in result]))
        return cls.browse([c.id for c in result])

    @classmethod
    @ModelView.button
    def recalculate(cls, calculations):
        """Calculate again with the current data: in place while not
        accepted or rejected, else as a new calculation"""
        pool = Pool()
        Action = pool.get('ir.action')
        ModelData = pool.get('ir.model.data')
        new = cls.calculate_for([{
                    'company': c.company.id,
                    'base_object': c.base_object.id,
                    'key_date': c.key_date,
                    'contract': c.contract.id if c.contract else None,
                    'term': c.term.id if c.term else None,
                    'rent_adjustment': (c.rent_adjustment.id
                        if c.rent_adjustment else None),
                    } for c in calculations])
        action = Action(ModelData.get_id('real_estate',
                'act_rent_survey_calculation')).get_action_value()
        action['pyson_domain'] = PYSONEncoder().encode(
            [('id', 'in', [c.id for c in new])])
        action['views'] = list(reversed(action['views']))
        # open the records themselves, not the first tab of the action
        action['domains'] = []
        # the client opens a form-first action without res_id as a new record
        action['res_id'] = [c.id for c in new]
        return action
