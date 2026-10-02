'Price Index (index rent, § 557b BGB)'
import csv
import datetime
import io
import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from decimal import Decimal, InvalidOperation

from trytond import config
from trytond.i18n import gettext
from trytond.model import (
    DeactivableMixin, ModelSQL, ModelView, Unique, fields)
from trytond.model.exceptions import ValidationError
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Bool, Eval, If
from trytond.transaction import Transaction
from trytond.wizard import Button, StateTransition, StateView, Wizard

logger = logging.getLogger(__name__)

# GENESIS-Online web service (POST only since 30.06.2025, credentials in
# the request header - spezifikation-indexmiete.md 3.3 a)
GENESIS_URL = 'https://genesis.destatis.de/genesisWS/rest/2020/'
GENESIS_TIMEOUT = 60


class GenesisError(Exception):
    "Error of the GENESIS-Online web service (message for the user)"


# German month names as used in GENESIS-Online table downloads
_MONTH_NAMES = {
    'januar': 1, 'februar': 2, 'märz': 3, 'maerz': 3, 'april': 4,
    'mai': 5, 'juni': 6, 'juli': 7, 'august': 8, 'september': 9,
    'oktober': 10, 'november': 11, 'dezember': 12,
    }


def parse_month(text):
    """Month of a CSV cell as first day of the month: 'YYYY-MM' or
    'MM.YYYY' - None if the text is no month."""
    text = (text or '').strip()
    match = re.fullmatch(r'(\d{4})-(\d{1,2})', text)
    if match:
        year, month = int(match.group(1)), int(match.group(2))
    else:
        match = re.fullmatch(r'(\d{1,2})\.(\d{4})', text)
        if not match:
            return None
        month, year = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12:
        return None
    return datetime.date(year, month, 1)


def parse_value(text):
    """Index value of a CSV cell ('117,6' or '117.6') - None if the cell
    holds no number (e.g. '...' or '-' for values not yet published)."""
    text = (text or '').strip().replace(' ', '')
    if not text:
        return None
    if ',' in text:
        text = text.replace('.', '').replace(',', '.')
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    if not value.is_finite() or value <= 0:
        return None
    return value.quantize(Decimal('0.1'))


def parse_genesis_ffcsv(content, series=None):
    """Parse a GENESIS-Online flat file CSV (ffcsv) of a monthly price
    index (e.g. table 61111-0002). Every month has one index row (unit
    'YYYY=100') and rows with change rates (unit '%') - only the index rows
    are taken. Returns (values {month: value}, base_year, ignored count,
    errors [text])."""
    reader = csv.DictReader(io.StringIO(content), delimiter=';')
    values, base_years, errors = {}, set(), []
    ignored = 0
    for row in reader:
        unit = (row.get('value_unit') or '').strip()
        match = re.fullmatch(r'(\d{4})=100', unit)
        if not match:
            ignored += 1
            continue
        if series:
            codes = {(row.get(k) or '').strip() for k in row
                if k and (k == 'value_variable_code'
                    or k.endswith('_variable_attribute_code'))}
            if series not in codes:
                ignored += 1
                continue
        month_code = next((row[k] for k in row
                if k and k.endswith('_variable_attribute_code')
                and re.fullmatch(r'MONAT\d\d', (row[k] or '').strip())),
            None)
        try:
            year = int(row.get('time') or '')
            month = int(month_code.strip()[5:]) if month_code else None
        except ValueError:
            year = month = None
        value = parse_value(row.get('value'))
        if not year or not month or not 1 <= month <= 12 or value is None:
            ignored += 1
            continue
        base_years.add(int(match.group(1)))
        date = datetime.date(year, month, 1)
        if date in values and values[date] != value:
            errors.append(f'{date:%Y-%m}: {values[date]} / {value}')
            continue
        values[date] = value
    if len(base_years) > 1:
        errors.append('base years: ' + ', '.join(map(str, sorted(base_years))))
    base_year = base_years.pop() if len(base_years) == 1 else None
    return values, base_year, ignored, errors


def parse_index_csv(content, base_year=None):
    """Parse index values from CSV text.

    Accepted rows (separator ';', ',' or tab):
    - 'Month;Value' with the month as 'YYYY-MM' or 'MM.YYYY'
    - 'Year;Month name;Value' (German month names, as in GENESIS-Online
      table downloads)
    - a GENESIS-Online flat file CSV (ffcsv, header with 'value_unit'),
      checked against 'base_year' if given
    Rows that are neither (headers, notes) are ignored. Returns
    (values {month: value}, ignored [(line number, text)],
    errors [(line number, text)])."""
    header = content.lstrip('\ufeff').split('\n', 1)[0]
    if 'value_unit' in header and 'time' in header:
        values, file_base_year, ignored, errors = parse_genesis_ffcsv(
            content)
        errors = [(0, e) for e in errors]
        if base_year and file_base_year and file_base_year != base_year:
            errors.append((0, f'{file_base_year}=100 / {base_year}=100'))
        return values, [(0, f'{ignored} rows')] if ignored else [], errors
    sample = content[:4096]
    delimiter = ';'
    if ';' not in sample:
        delimiter = '\t' if '\t' in sample else ','
    values, ignored, errors = {}, [], []
    reader = csv.reader(io.StringIO(content), delimiter=delimiter)
    for line_no, row in enumerate(reader, 1):
        cells = [c.strip() for c in row]
        if not any(cells):
            continue
        month = value = None
        if len(cells) >= 2:
            month = parse_month(cells[0])
            if month:
                value = parse_value(cells[1])
            elif (len(cells) >= 3 and re.fullmatch(r'\d{4}', cells[0])
                    and cells[1].lower() in _MONTH_NAMES):
                month = datetime.date(
                    int(cells[0]), _MONTH_NAMES[cells[1].lower()], 1)
                value = parse_value(cells[2])
        text = delimiter.join(row)
        if not month or value is None:
            ignored.append((line_no, text))
            continue
        if month in values and values[month] != value:
            errors.append((line_no, text))
            continue
        values[month] = value
    return values, ignored, errors


#**********************************************************************
class PriceIndex(DeactivableMixin, ModelSQL, ModelView):
    "Price Index"
    __name__ = 'real_estate.price_index'

    name = fields.Char("Name", required=True, translate=True)
    code = fields.Char("Code", required=True,
        help="Unique short code of the index series, e.g. VPI-DE.")
    source = fields.Selection([
            ('destatis_genesis', "Destatis GENESIS-Online"),
            ('manual', "Manual"),
            ], "Source", required=True, sort=False,
        help="Origin of the values. Destatis GENESIS-Online: fetched by "
             "the button 'Fetch Values' and the scheduled task 'Import "
             "Price Index Values' (API token in trytond.conf, section "
             "[real_estate], genesis_token); CSV import and manual entry "
             "remain possible. Manual: CSV import and manual entry only.")
    genesis_table = fields.Char("GENESIS Table",
        states={'invisible': Eval('source') != 'destatis_genesis'},
        help="GENESIS-Online table code, e.g. 61111-0002 (consumer price "
             "index: Germany, months).")
    genesis_series = fields.Char("GENESIS Series",
        states={'invisible': Eval('source') != 'destatis_genesis'},
        help="Characteristic of the table if it holds several series.")
    base_year = fields.Integer("Base Year", required=True,
        help="Current base year of the series (base year = 100). Changes "
             "are always calculated within this base year.")
    residential_allowed = fields.Boolean("Allowed for Residential",
        help="Index allowed for residential index rents (§ 557b BGB: only "
             "the consumer price index for Germany of Destatis).")
    values = fields.One2Many(
        'real_estate.price_index.value', 'index', "Values")
    last_value_month = fields.Function(
        fields.Date("Last Final Month"), 'get_last_value_month')
    last_import_date = fields.DateTime("Last Import", readonly=True)
    last_import_message = fields.Text("Last Import Message", readonly=True)
    comment = fields.Text("Comment")

    @classmethod
    def __setup__(cls):
        super().__setup__()
        t = cls.__table__()
        cls._sql_constraints += [
            ('code_unique', Unique(t, t.code),
                'real_estate.msg_price_index_code_unique'),
            ]
        cls._order.insert(0, ('code', 'ASC'))
        genesis = Eval('source') == 'destatis_genesis'
        cls._buttons.update({
            'fetch': {
                'invisible': ~genesis,
                'depends': ['source'],
                },
            'fetch_full': {
                'invisible': ~genesis,
                'depends': ['source'],
                },
            })

    @classmethod
    def default_source(cls):
        return 'manual'

    @classmethod
    def default_residential_allowed(cls):
        return False

    def get_rec_name(self, name):
        return f'{self.code} - {self.name}'

    @classmethod
    def search_rec_name(cls, name, clause):
        _, operator, *_ = clause
        bool_op = 'AND' if operator.startswith('!') else 'OR'
        return [bool_op,
            ('code',) + tuple(clause[1:]),
            ('name',) + tuple(clause[1:]),
            ]

    @classmethod
    def get_last_value_month(cls, indices, name):
        Value = Pool().get('real_estate.price_index.value')
        result = {}
        for index in indices:
            values = Value.search([
                    ('index', '=', index.id),
                    ('base_year', '=', index.base_year),
                    ('final', '=', True),
                    ], order=[('month', 'DESC')], limit=1)
            result[index.id] = values[0].month if values else None
        return result

    def get_value(self, month, base_year=None, final_only=True):
        """Value record of the month in the given (default: current) base
        year - None if missing."""
        Value = Pool().get('real_estate.price_index.value')
        domain = [
            ('index', '=', self.id),
            ('base_year', '=', base_year or self.base_year),
            ('month', '=', month.replace(day=1)),
            ]
        if final_only:
            domain.append(('final', '=', True))
        values = Value.search(domain, limit=1)
        return values[0] if values else None

    @classmethod
    def import_values(cls, index, base_year, values, final=True,
            origin='csv'):
        """Create/update the index values {month: value} of a base year.
        Returns the counts {'created', 'updated', 'unchanged'}."""
        pool = Pool()
        Value = pool.get('real_estate.price_index.value')
        now = datetime.datetime.now()
        existing = {v.month: v for v in Value.search([
                    ('index', '=', index.id),
                    ('base_year', '=', base_year),
                    ('month', 'in', list(values)),
                    ])}
        counts = {'created': 0, 'updated': 0, 'unchanged': 0}
        to_create, to_write = [], []
        for month, value in sorted(values.items()):
            record = existing.get(month)
            if record is None:
                to_create.append({
                        'index': index.id,
                        'base_year': base_year,
                        'month': month,
                        'value': value,
                        'final': final,
                        'origin': origin,
                        'import_date': now,
                        })
                counts['created'] += 1
            elif record.value != value or record.final != final:
                to_write.extend(([record], {
                        'value': value,
                        'final': final,
                        'origin': origin,
                        'import_date': now,
                        }))
                counts['updated'] += 1
            else:
                counts['unchanged'] += 1
        if to_create:
            Value.create(to_create)
        if to_write:
            Value.write(*to_write)
        cls.write([index], {
                'last_import_date': now,
                'last_import_message': gettext(
                    'real_estate.msg_price_index_import_summary',
                    base_year=base_year, **counts),
                })
        return counts

    # ------------------------------------------------------------------
    # GENESIS-Online import (spezifikation-indexmiete.md 3.3 a)

    @classmethod
    def _genesis_request(cls, path, data):
        """POST to the GENESIS-Online web service - the only place with
        knowledge of the interface. Returns the response body; raises
        GenesisError with a message for the user."""
        token = config.get('real_estate', 'genesis_token', default=None)
        if not token:
            raise GenesisError(gettext(
                    'real_estate.msg_price_index_genesis_no_token'))
        url = config.get('real_estate', 'genesis_url', default=GENESIS_URL)
        timeout = config.getint('real_estate', 'genesis_timeout',
            default=GENESIS_TIMEOUT)
        request = urllib.request.Request(
            url.rstrip('/') + '/' + path,
            data=urllib.parse.urlencode(data).encode(),
            headers={
                'Content-Type': 'application/x-www-form-urlencoded',
                'username': token.strip(),
                'password': '',
                },
            method='POST')
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read()
        except (urllib.error.URLError, OSError) as e:
            raise GenesisError(gettext(
                    'real_estate.msg_price_index_genesis_connection',
                    error=str(e))) from e
        if body[:2] != b'PK':
            # Not a file: JSON status message of the web service
            try:
                status = json.loads(body).get('Status') or {}
                message = f"{status.get('Code', '')} {status.get('Content', '')}"
            except ValueError:
                message = body[:200].decode('utf-8', 'replace')
            raise GenesisError(gettext(
                    'real_estate.msg_price_index_genesis_status',
                    message=message.strip()))
        return body

    @classmethod
    def _used_months(cls, index, base_year):
        "Months of the series used by declared or executed adjustments"
        Adjustment = Pool().get('real_estate.contract.term.adjustment')
        months = set()
        for adjustment in Adjustment.search([
                    ('rent_adjustment.price_index', '=', index.id),
                    ('index_base_year', '=', base_year),
                    ('state', 'in', ['declared', 'done']),
                    ]):
            months.update(m for m in (adjustment.index_month_old,
                    adjustment.index_month_new) if m)
        return months

    @classmethod
    def fetch_values(cls, indices, full=False):
        """Fetch the monthly values of the GENESIS series from the web
        service (ffcsv) and import them (origin 'import'). Errors are
        stored in the series' import message and logged, never raised -
        a scheduled run continues with the next series. full: from the
        base year on, else from the year before the last value."""
        pool = Pool()
        Value = pool.get('real_estate.price_index.value')
        now = datetime.datetime.now()
        for index in indices:
            if index.source != 'destatis_genesis' or not index.genesis_table:
                continue
            start_year = index.base_year
            if not full:
                last = Value.search([
                        ('index', '=', index.id),
                        ('base_year', '=', index.base_year),
                        ], order=[('month', 'DESC')], limit=1)
                if last:
                    start_year = max(index.base_year, last[0].month.year - 1)
            try:
                body = cls._genesis_request('data/tablefile', {
                        'name': index.genesis_table,
                        'startyear': start_year,
                        'format': 'ffcsv',
                        'compress': 'true',
                        'language': 'de',
                        })
                with zipfile.ZipFile(io.BytesIO(body)) as archive:
                    content = archive.read(archive.namelist()[0]).decode(
                        'utf-8-sig')
                values, base_year, _, errors = parse_genesis_ffcsv(
                    content, series=index.genesis_series or None)
                if errors:
                    raise GenesisError(gettext(
                            'real_estate.msg_price_index_genesis_format',
                            errors='; '.join(errors[:5])))
                if base_year and base_year != index.base_year:
                    raise GenesisError(gettext(
                            'real_estate.msg_price_index_genesis_base_year',
                            file_base_year=base_year,
                            base_year=index.base_year))
                # Revisions of values used by declared/executed adjustments
                # are not taken over (spec 3.2)
                used = cls._used_months(index, index.base_year)
                existing = {v.month: v.value for v in Value.search([
                            ('index', '=', index.id),
                            ('base_year', '=', index.base_year),
                            ('month', 'in', list(used)),
                            ])}
                locked = sorted(m for m in used
                    if m in values and m in existing
                    and existing[m] != values[m])
                for month in locked:
                    values.pop(month)
                cls.import_values(index, index.base_year, values,
                    final=True, origin='import')
                if locked:
                    index = cls(index.id)
                    cls.write([index], {
                            'last_import_message': (
                                index.last_import_message + '\n'
                                + gettext(
                                    'real_estate.msg_price_index_genesis_locked',
                                    months=', '.join(
                                        f'{m:%m/%Y}' for m in locked))),
                            })
            except Exception as e:
                if isinstance(e, GenesisError):
                    logger.warning('GENESIS import of price index %s: %s',
                        index.code, e)
                else:
                    logger.exception(
                        'GENESIS import of price index %s failed', index.code)
                message = (str(e) if isinstance(e, GenesisError)
                    else gettext('real_estate.msg_price_index_genesis_error',
                        error=repr(e)))
                cls.write([index], {
                        'last_import_date': now,
                        'last_import_message': message,
                        })

    @classmethod
    @ModelView.button
    def fetch(cls, indices):
        cls.fetch_values(indices)

    @classmethod
    @ModelView.button
    def fetch_full(cls, indices):
        cls.fetch_values(indices, full=True)

#**********************************************************************
class PriceIndexValue(ModelSQL, ModelView):
    "Price Index Value"
    __name__ = 'real_estate.price_index.value'

    index = fields.Many2One('real_estate.price_index', "Index",
        required=True, ondelete='CASCADE')
    base_year = fields.Integer("Base Year", required=True)
    month = fields.Date("Month", required=True,
        help="First day of the month.")
    value = fields.Numeric("Value", digits=(16, 1), required=True)
    final = fields.Boolean("Final",
        help="Only final values are used for rent adjustments.")
    origin = fields.Selection([
            ('import', "Import"),
            ('csv', "CSV"),
            ('manual', "Manual"),
            ], "Origin", required=True, readonly=True, sort=False)
    import_date = fields.DateTime("Import Date", readonly=True)

    @classmethod
    def __setup__(cls):
        super().__setup__()
        t = cls.__table__()
        cls._sql_constraints += [
            ('month_unique', Unique(t, t.index, t.base_year, t.month),
                'real_estate.msg_price_index_value_unique'),
            ]
        cls._order = [
            ('index', 'ASC'),
            ('base_year', 'DESC'),
            ('month', 'DESC'),
            ('id', 'DESC'),
            ]

    @classmethod
    def default_final(cls):
        return True

    @classmethod
    def default_origin(cls):
        return 'manual'

    @classmethod
    def default_base_year(cls):
        Index = Pool().get('real_estate.price_index')
        index_id = Transaction().context.get('price_index')
        if index_id:
            return Index(index_id).base_year

    @fields.depends('index', '_parent_index.base_year', 'base_year')
    def on_change_index(self):
        if self.index and not self.base_year:
            self.base_year = self.index.base_year

    @fields.depends('index', '_parent_index.base_year', 'base_year')
    def on_change_month(self):
        # New line in the index form: the parent's current base year
        if self.index and not self.base_year:
            self.base_year = self.index.base_year

    def get_rec_name(self, name):
        return (f'{self.index.code} {self.month:%Y-%m} '
            f'({self.base_year}): {self.value}')

    @classmethod
    def _check_used(cls, values):
        """Values used by a declared or executed index adjustment cannot
        be changed or deleted (spec 3.2) - matched by series, base year
        and month."""
        Adjustment = Pool().get('real_estate.contract.term.adjustment')
        for value in values:
            used = Adjustment.search([
                    ('rent_adjustment.price_index', '=', value.index.id),
                    ('index_base_year', '=', value.base_year),
                    ['OR',
                        ('index_month_old', '=', value.month),
                        ('index_month_new', '=', value.month)],
                    ('state', 'in', ['declared', 'done']),
                    ], limit=1)
            if used:
                raise ValidationError(gettext(
                        'real_estate.msg_price_index_value_used',
                        value=value.rec_name, adjustment=used[0].rec_name))

    @classmethod
    def write(cls, *args):
        actions = iter(args)
        for records, values in zip(actions, actions):
            if {'index', 'base_year', 'month', 'value', 'final'} & set(values):
                cls._check_used(records)
        super().write(*args)

    @classmethod
    def delete(cls, values):
        cls._check_used(values)
        super().delete(values)

    @classmethod
    def validate_fields(cls, values, field_names):
        super().validate_fields(values, field_names)
        if field_names & {'month', 'value'}:
            for value in values:
                if value.month and value.month.day != 1:
                    raise ValidationError(gettext(
                            'real_estate.msg_price_index_value_first_day',
                            value=value.rec_name))
                if value.value is not None and value.value <= 0:
                    raise ValidationError(gettext(
                            'real_estate.msg_price_index_value_positive',
                            value=value.rec_name))


#**********************************************************************
class PriceIndexValueContext(ModelView):
    "Price Index Value Context"
    __name__ = 'real_estate.price_index.value.context'

    price_index = fields.Many2One('real_estate.price_index', "Index")
    base_year = fields.Integer("Base Year")


#**********************************************************************
class PriceIndexImportStart(ModelView):
    "Import Price Index Values - Start"
    __name__ = 'real_estate.price_index.import.start'

    price_index = fields.Many2One('real_estate.price_index', "Index",
        required=True)
    base_year = fields.Integer("Base Year", required=True,
        help="Base year of the values in the file.")
    final = fields.Boolean("Final Values",
        help="Mark the imported values as final (only final values are "
             "used for rent adjustments).")
    file = fields.Binary("File", required=True, filename='filename',
        help="CSV file with the columns 'Month;Value' (month as YYYY-MM or "
             "MM.YYYY), 'Year;Month name;Value' (GENESIS-Online table "
             "download) or a GENESIS-Online flat file CSV (ffcsv). Other "
             "rows are ignored.")
    filename = fields.Char("File Name")

    @classmethod
    def default_final(cls):
        return True

    @fields.depends('price_index', 'base_year')
    def on_change_price_index(self):
        if self.price_index:
            self.base_year = self.price_index.base_year


#**********************************************************************
class PriceIndexImportPreview(ModelView):
    "Import Price Index Values - Preview"
    __name__ = 'real_estate.price_index.import.preview'

    n_values = fields.Integer("Values", readonly=True)
    n_new = fields.Integer("New", readonly=True)
    n_changed = fields.Integer("Changed", readonly=True)
    n_unchanged = fields.Integer("Unchanged", readonly=True)
    n_ignored = fields.Integer("Ignored Rows", readonly=True)
    n_errors = fields.Integer("Errors", readonly=True)
    details = fields.Text("Details", readonly=True)


#**********************************************************************
class PriceIndexImportResult(ModelView):
    "Import Price Index Values - Result"
    __name__ = 'real_estate.price_index.import.result'

    message = fields.Text("Result", readonly=True)


#**********************************************************************
class PriceIndexImport(Wizard):
    "Import Price Index Values"
    __name__ = 'real_estate.price_index.import'

    start = StateView('real_estate.price_index.import.start',
        'real_estate.price_index_import_start_view_form', [
            Button("Cancel", 'end', 'tryton-cancel'),
            Button("Preview", 'preview', 'tryton-forward', default=True),
            ])
    preview = StateView('real_estate.price_index.import.preview',
        'real_estate.price_index_import_preview_view_form', [
            Button("Cancel", 'end', 'tryton-cancel'),
            Button("Back", 'start', 'tryton-back'),
            Button("Import", 'do_import', 'tryton-ok', default=True,
                states={'readonly': Bool(Eval('n_errors'))
                    | ~Eval('n_values')}),
            ])
    do_import = StateTransition()
    result = StateView('real_estate.price_index.import.result',
        'real_estate.price_index_import_result_view_form', [
            Button("Close", 'end', 'tryton-ok', default=True),
            ])

    def default_start(self, fields):
        pool = Pool()
        Index = pool.get('real_estate.price_index')
        values = {'final': True}
        if (Transaction().context.get('active_model')
                == 'real_estate.price_index' and self.model
                and self.record):
            values['price_index'] = self.record.id
            values['base_year'] = self.record.base_year
        else:
            indices = Index.search([], limit=2)
            if len(indices) == 1:
                values['price_index'] = indices[0].id
                values['base_year'] = indices[0].base_year
        return values

    def _parse(self):
        data = self.start.file or b''
        for encoding in ('utf-8-sig', 'cp1252'):
            try:
                content = bytes(data).decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        return parse_index_csv(content, self.start.base_year)

    def default_preview(self, fields):
        pool = Pool()
        Value = pool.get('real_estate.price_index.value')
        values, ignored, errors = self._parse()
        existing = {v.month: v.value for v in Value.search([
                    ('index', '=', self.start.price_index.id),
                    ('base_year', '=', self.start.base_year),
                    ('month', 'in', list(values)),
                    ])}
        new = [m for m in values if m not in existing]
        changed = [m for m in values
            if m in existing and existing[m] != values[m]]
        lines = []
        if errors:
            lines.append(gettext('real_estate.msg_price_index_import_errors'))
            lines.extend(f'  {n}: {t}' for n, t in errors)
        if changed:
            lines.append(gettext(
                    'real_estate.msg_price_index_import_changed'))
            lines.extend(f'  {m:%Y-%m}: {existing[m]} -> {values[m]}'
                for m in sorted(changed))
        if values:
            months = sorted(values)
            lines.append(gettext(
                    'real_estate.msg_price_index_import_range',
                    first=f'{months[0]:%Y-%m}', last=f'{months[-1]:%Y-%m}'))
        if ignored:
            lines.append(gettext(
                    'real_estate.msg_price_index_import_ignored'))
            lines.extend(f'  {n}: {t[:80]}' for n, t in ignored[:20])
            if len(ignored) > 20:
                lines.append('  ...')
        return {
            'n_values': len(values),
            'n_new': len(new),
            'n_changed': len(changed),
            'n_unchanged': len(values) - len(new) - len(changed),
            'n_ignored': len(ignored),
            'n_errors': len(errors),
            'details': '\n'.join(lines),
            }

    def transition_do_import(self):
        Index = Pool().get('real_estate.price_index')
        values, _, errors = self._parse()
        if errors:
            raise ValidationError(gettext(
                    'real_estate.msg_price_index_import_errors'))
        counts = Index.import_values(
            self.start.price_index, self.start.base_year, values,
            final=self.start.final, origin='csv')
        self.result.message = gettext(
            'real_estate.msg_price_index_import_summary',
            base_year=self.start.base_year, **counts)
        return 'result'

    def default_result(self, fields):
        return {'message': self.result.message}


#**********************************************************************
class IndexCapRule(DeactivableMixin, ModelSQL, ModelView):
    "Index Rent Cap Rule"
    # Prepared for the planned cap of index rents ("Mietrecht II", not in
    # force yet - spezifikation-indexmiete.md 2.3, 4.4, 6.3): inactive by
    # default, activated only once the law is in force
    __name__ = 'real_estate.index_cap_rule'

    name = fields.Char("Name", required=True, translate=True)
    valid_from = fields.Date("Valid from",
        help="Applies to declarations received from this date on.")
    valid_to = fields.Date("Valid to",
        domain=[If(Bool(Eval('valid_to')) & Bool(Eval('valid_from')),
                ('valid_to', '>=', Eval('valid_from', None)), ())])
    threshold_percent = fields.Numeric("Threshold (%)", digits=(16, 2),
        required=True,
        help="Yearly index change counted in full.")
    excess_share_percent = fields.Numeric("Share of Excess (%)",
        digits=(16, 2), required=True,
        help="Share of the change above the threshold that is counted.")
    tight_market_only = fields.Boolean("Tight Housing Market Only",
        help="Only for properties in a tight housing market area.")
    comment = fields.Text("Comment")

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._order.insert(0, ('valid_from', 'DESC'))

    @classmethod
    def default_active(cls):
        # Activate only after the law has come into force
        return False

    @classmethod
    def default_threshold_percent(cls):
        return Decimal(3)

    @classmethod
    def default_excess_share_percent(cls):
        return Decimal(50)

    @classmethod
    def default_tight_market_only(cls):
        return True

    @classmethod
    def find(cls, date, property_=None):
        """Active cap rule for a declaration received on 'date' and the
        property (tight housing market) - None if no rule applies."""
        if not date:
            return None
        for rule in cls.search([('active', '=', True)]):
            if rule.valid_from and date < rule.valid_from:
                continue
            if rule.valid_to and date > rule.valid_to:
                continue
            if rule.tight_market_only and not (
                    property_ and property_.is_tight_market(date)):
                continue
            return rule
        return None

    def apply(self, value_of, month_from, month_to):
        """Counted index change in percent between month_from and
        month_to (preliminary rule, spec 6.3): the period is split into
        sections of 12 months (rest last), each section's change c above
        the pro rata threshold t counts only with the excess share, the
        sections are compounded. value_of(month) returns the index value
        of a month. No cap for decreases."""
        total = value_of(month_to) / value_of(month_from) - 1
        if total <= 0:
            return total * 100
        threshold = self.threshold_percent / 100
        share = self.excess_share_percent / 100
        factor = Decimal(1)
        start = month_from
        while start < month_to:
            end = min(_add_months(start, 12), month_to)
            months = _months_between(start, end)
            change = value_of(end) / value_of(start) - 1
            limit = threshold * months / 12
            if change > limit:
                change = limit + (change - limit) * share
            factor *= 1 + change
            start = end
        return (factor - 1) * 100


def _add_months(date, months):
    month = date.month - 1 + months
    return date.replace(year=date.year + month // 12, month=month % 12 + 1)


def _months_between(start, end):
    return (end.year - start.year) * 12 + end.month - start.month


#**********************************************************************
class Contract(metaclass=PoolMeta):
    __name__ = 'real_estate.contract'

    @classmethod
    def _cron_price_index_import(cls, re_accounting, task=None):
        """Scheduled task 'price_index_import' (dispatched by
        Contract.cron_daily): fetch all active GENESIS series. The series
        are not company specific - several task rows only lead to
        'unchanged' imports."""
        PriceIndex = Pool().get('real_estate.price_index')
        PriceIndex.fetch_values(PriceIndex.search([
                    ('source', '=', 'destatis_genesis'),
                    ('genesis_table', '!=', None),
                    ]))
