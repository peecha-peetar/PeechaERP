"""R374: گزارش‌ساز آزاد — تعریف گزارش روی یک مجموعه‌داده: ستون‌ها، فیلترها، گروه‌بندی با جمع/میانگین/کمینه/بیشینه/تعداد،
گروه‌بندی تاریخ به روز/ماه/سال شمسی، مرتب‌سازی و سقف ردیف.

- استفاده از هر مجموعه‌داده با مجوز «مشاهده»ی یکی از فرم‌های همان داده است (مدیر سیستم همه را دارد)؛ شعبه‌های مجاز کاربر
  در خواندن داده اعمال می‌شود. گزارش ذخیره‌شده شخصی است یا با دیگران به اشتراک گذاشته می‌شود؛ اشتراک فقط برای کسی که به همان
  داده دسترسی دارد نمایش داده می‌شود. ویرایش و حذف با سازنده یا مدیر سیستم است.
- فیلتر تاریخ در خود پایگاه داده اعمال می‌شود و بقیهٔ فیلترها روی ردیف‌های خوانده‌شده.
"""

from __future__ import annotations

import datetime
import decimal
from dataclasses import asdict, dataclass, field

import jdatetime
from sqlalchemy import or_, select

from peecha.db.base import new_session
from peecha.db.models.reporting import CustomReport
from peecha.services.report_builder.datasets import DATASETS, DATE, MAX_ROWS, NUMERIC, TEXT, Dataset

ZERO = decimal.Decimal(0)
OPS = {
    TEXT: {"CONTAINS": "شامل", "EQ": "برابر", "NE": "نابرابر", "STARTS": "شروع با", "EMPTY": "خالی", "NOT_EMPTY": "پر"},
    DATE: {"FROM": "از تاریخ", "TO": "تا تاریخ", "BETWEEN": "بین"},
    "NUM": {"EQ": "=", "NE": "≠", "GT": ">", "GE": "≥", "LT": "<", "LE": "≤", "BETWEEN": "بین"},
}
AGGREGATES = {"SUM": "جمع", "AVG": "میانگین", "MIN": "کمینه", "MAX": "بیشینه", "COUNT": "تعداد"}
DATE_GROUPS = {"DAY": "روز", "MONTH": "ماه", "YEAR": "سال"}
COUNT_KEY = "__count__"


@dataclass
class Filter:
    key: str
    op: str
    value: object = None
    value2: object = None


@dataclass
class Definition:
    dataset: str
    columns: list[str]
    filters: list[Filter] = field(default_factory=list)
    group: bool = False
    date_group: str = "DAY"
    aggregates: dict[str, str] = field(default_factory=dict)
    count_rows: bool = False
    sort_key: str | None = None
    sort_desc: bool = False
    limit: int | None = None

    def to_json(self) -> dict:
        data = asdict(self)
        for f in data["filters"]:
            for k in ("value", "value2"):
                if isinstance(f[k], datetime.date):
                    f[k] = {"date": f[k].isoformat()}
                elif isinstance(f[k], decimal.Decimal):
                    f[k] = {"dec": str(f[k])}
        return data

    @classmethod
    def from_json(cls, data: dict) -> Definition:
        def value(v):
            if isinstance(v, dict) and "date" in v:
                return datetime.date.fromisoformat(v["date"])
            if isinstance(v, dict) and "dec" in v:
                return decimal.Decimal(v["dec"])
            return v

        filters = [Filter(f["key"], f["op"], value(f.get("value")), value(f.get("value2"))) for f in data.get("filters", [])]
        return cls(data["dataset"], list(data.get("columns", [])), filters, bool(data.get("group")), data.get("date_group") or "DAY",
                   dict(data.get("aggregates") or {}), bool(data.get("count_rows")), data.get("sort_key"), bool(data.get("sort_desc")),
                   data.get("limit"))


@dataclass
class Result:
    title: str
    headers: list[str]
    kinds: list[str]
    rows: list[list]
    totals: list | None
    truncated: bool
    source: str
    filters_text: list[tuple[str, str]]
    row_count_before_limit: int = 0


def can_use(company_id: int, user_id: int, dataset_code: str) -> bool:
    from peecha.services import roles

    dataset = DATASETS.get(dataset_code)
    if dataset is None:
        return False
    return roles.is_manager(user_id, company_id) or any(
        roles.user_has_permission(user_id, company_id, form, "VIEW") for form in dataset.forms)


def available(company_id: int, user_id: int) -> list[Dataset]:
    return [d for d in DATASETS.values() if can_use(company_id, user_id, d.code)]


def ops_for(kind: str) -> dict[str, str]:
    return OPS[kind] if kind in (TEXT, DATE) else OPS["NUM"]


def validate(definition: Definition) -> Dataset:
    dataset = DATASETS.get(definition.dataset)
    if dataset is None:
        raise ValueError("مجموعه‌دادهٔ گزارش نامعتبر است.")
    if not definition.columns:
        raise ValueError("دست‌کم یک ستون برای گزارش انتخاب کنید.")
    for key in definition.columns:
        if dataset.column(key) is None:
            raise ValueError("ستون انتخاب‌شده در این مجموعه‌داده نیست.")
    if len(set(definition.columns)) != len(definition.columns):
        raise ValueError("یک ستون دو بار انتخاب شده است.")
    for f in definition.filters:
        col = dataset.column(f.key)
        if col is None or f.op not in ops_for(col.kind):
            raise ValueError("فیلتر گزارش نامعتبر است.")
        needs_value = f.op not in ("EMPTY", "NOT_EMPTY")
        if needs_value and (f.value is None or f.value == ""):
            raise ValueError(f"مقدار فیلتر «{col.label}» را وارد کنید.")
        if f.op == "BETWEEN" and (f.value2 is None or f.value2 == ""):
            raise ValueError(f"مقدار دوم فیلتر «{col.label}» را وارد کنید.")
    for key, agg in definition.aggregates.items():
        col = dataset.column(key)
        if col is None or col.kind not in NUMERIC or agg not in AGGREGATES:
            raise ValueError("جمع‌بندی ستون نامعتبر است.")
    if definition.date_group not in DATE_GROUPS:
        raise ValueError("گروه‌بندی تاریخ نامعتبر است.")
    if definition.sort_key and definition.sort_key not in definition.columns + [COUNT_KEY]:
        raise ValueError("ستون مرتب‌سازی باید از ستون‌های گزارش باشد.")
    if definition.limit is not None and not 1 <= int(definition.limit) <= MAX_ROWS:
        raise ValueError("سقف ردیف نامعتبر است.")
    if definition.group and not any(dataset.column(k).kind not in NUMERIC for k in definition.columns):
        raise ValueError("برای گروه‌بندی دست‌کم یک ستون متنی یا تاریخ انتخاب کنید.")
    return dataset


def _date_range(dataset: Dataset, filters: list[Filter]) -> tuple[datetime.date | None, datetime.date | None]:
    lo = hi = None
    for f in filters:
        if f.key != dataset.date_key:
            continue
        if f.op in ("FROM", "BETWEEN"):
            lo = max(lo, f.value) if lo else f.value
        if f.op == "TO":
            hi = min(hi, f.value) if hi else f.value
        if f.op == "BETWEEN":
            hi = min(hi, f.value2) if hi else f.value2
    return lo, hi


def parse_number(value) -> decimal.Decimal:
    from peecha import numerals

    return decimal.Decimal(numerals.to_ascii_digits(str(value)).replace(",", "").replace("٬", "").replace("٫", ".").strip())


def _match(row: dict, f: Filter, kind: str) -> bool:
    v = row.get(f.key)
    if kind == TEXT:
        text, needle = str(v or ""), str(f.value or "").strip()
        return {"CONTAINS": lambda: needle in text, "EQ": lambda: text == needle, "NE": lambda: text != needle,
                "STARTS": lambda: text.startswith(needle), "EMPTY": lambda: not text, "NOT_EMPTY": lambda: bool(text)}[f.op]()
    if kind == DATE:
        if v is None:
            return False
        return {"FROM": lambda: v >= f.value, "TO": lambda: v <= f.value, "BETWEEN": lambda: f.value <= v <= f.value2}[f.op]()
    x, a = decimal.Decimal(v or 0), parse_number(f.value)
    b = parse_number(f.value2) if f.op == "BETWEEN" else None
    return {"EQ": x == a, "NE": x != a, "GT": x > a, "GE": x >= a, "LT": x < a, "LE": x <= a,
            "BETWEEN": b is not None and a <= x <= b}[f.op]


def _date_key(value: datetime.date | None, group: str):
    if value is None:
        return ""
    if group == "DAY":
        return value
    j = jdatetime.date.fromgregorian(date=value)
    from peecha import numerals

    return numerals.to_persian_digits(f"{j.year}/{j.month:02d}" if group == "MONTH" else str(j.year))


def _aggregate(values: list[decimal.Decimal], agg: str):
    if agg == "COUNT":
        return len(values)
    if not values:
        return ZERO
    if agg == "SUM":
        return sum(values, ZERO)
    if agg == "AVG":
        return (sum(values, ZERO) / len(values)).quantize(decimal.Decimal("0.01"))
    return min(values) if agg == "MIN" else max(values)


def _sort_value(v):
    if v is None or v == "":
        return (0, "")
    if isinstance(v, (int, decimal.Decimal)):
        return (1, v)
    if isinstance(v, datetime.date):
        return (2, v)
    return (3, str(v))


def filters_text(dataset: Dataset, filters: list[Filter]) -> list[tuple[str, str]]:
    from peecha import numerals

    def show(v):
        return numerals.format_jalali_date(v) if isinstance(v, datetime.date) else numerals.to_persian_digits(str(v))

    out = []
    for f in filters:
        col = dataset.column(f.key)
        op = ops_for(col.kind)[f.op]
        value = "" if f.op in ("EMPTY", "NOT_EMPTY") else show(f.value) + (f" و {show(f.value2)}" if f.op == "BETWEEN" else "")
        out.append((col.label, f"{op} {value}".strip()))
    return out


def run(company_id: int, user_id: int, definition: Definition, title: str = "") -> Result:
    dataset = validate(definition)
    if not can_use(company_id, user_id, dataset.code):
        raise ValueError(f"به داده‌های «{dataset.label}» دسترسی ندارید.")
    date_from, date_to = _date_range(dataset, definition.filters)
    raw = dataset.fetch(company_id, user_id, date_from, date_to)
    truncated = len(raw) > MAX_ROWS
    raw = raw[:MAX_ROWS]
    kinds = {c.key: c.kind for c in dataset.columns}
    rows = [r for r in raw if all(_match(r, f, kinds[f.key]) for f in definition.filters)]
    cols = [dataset.column(k) for k in definition.columns]
    if definition.group:
        keys = [c for c in cols if c.kind not in NUMERIC]
        groups: dict[tuple, list[dict]] = {}
        for r in rows:
            key = tuple(_date_key(r.get(c.key), definition.date_group) if c.kind == DATE else r.get(c.key) for c in keys)
            groups.setdefault(key, []).append(r)
        out_rows, headers, out_kinds = [], [], []
        for c in cols:
            agg = definition.aggregates.get(c.key, "SUM") if c.kind in NUMERIC else None
            headers.append(c.label if agg is None else f"{AGGREGATES[agg]} {c.label}")
            out_kinds.append("INT" if agg == "COUNT" else (TEXT if c.kind == DATE and definition.date_group != "DAY" else c.kind))
        if definition.count_rows:
            headers.append("تعداد ردیف")
            out_kinds.append("INT")
        for key, members in groups.items():
            values = dict(zip([c.key for c in keys], key))
            line = []
            for c in cols:
                if c.kind in NUMERIC:
                    line.append(_aggregate([decimal.Decimal(m.get(c.key) or 0) for m in members], definition.aggregates.get(c.key, "SUM")))
                else:
                    line.append(values[c.key])
            if definition.count_rows:
                line.append(len(members))
            out_rows.append(line)
    else:
        headers = [c.label for c in cols]
        out_kinds = [c.kind for c in cols]
        out_rows = [[r.get(c.key) for c in cols] for r in rows]
    order = definition.columns + ([COUNT_KEY] if definition.group and definition.count_rows else [])
    if definition.sort_key and definition.sort_key in order:
        index = order.index(definition.sort_key)
        out_rows.sort(key=lambda line: _sort_value(line[index]), reverse=definition.sort_desc)
    before = len(out_rows)
    if definition.limit:
        out_rows = out_rows[:int(definition.limit)]
    totals = None
    summable = [i for i, c in enumerate(cols) if c.kind in NUMERIC and (
        definition.aggregates.get(c.key, "SUM") == "COUNT" or (c.additive and (not definition.group
                                                                               or definition.aggregates.get(c.key, "SUM") == "SUM")))]
    if definition.group and definition.count_rows:
        summable.append(len(cols))
    if out_rows and summable:
        totals = [None] * len(headers)
        for i in summable:
            totals[i] = sum((decimal.Decimal(line[i] or 0) for line in out_rows), ZERO)
    source = f"{dataset.label} — {dataset.description}"
    return Result(title or dataset.label, headers, out_kinds, out_rows, totals, truncated, source,
                  filters_text(dataset, definition.filters), before)


# --- گزارش‌های ذخیره‌شده ------------------------------------------------------------------------------------
@dataclass
class SavedReport:
    report_id: int
    name: str
    dataset_code: str
    dataset_label: str
    owner_user_id: int
    is_shared: bool
    definition: Definition
    updated_at: datetime.datetime

    def editable_by(self, company_id: int, user_id: int) -> bool:
        from peecha.services import roles

        return self.owner_user_id == user_id or roles.is_manager(user_id, company_id)


def _saved(row: CustomReport) -> SavedReport:
    return SavedReport(row.report_id, row.name, row.dataset_code, DATASETS[row.dataset_code].label if row.dataset_code in DATASETS else "",
                       row.owner_user_id, row.is_shared, Definition.from_json(row.definition), row.updated_at)


def list_reports(company_id: int, user_id: int) -> list[SavedReport]:
    with new_session() as session:
        rows = list(session.scalars(select(CustomReport).where(
            CustomReport.company_id == company_id, or_(CustomReport.owner_user_id == user_id, CustomReport.is_shared.is_(True)))
            .order_by(CustomReport.name)))
    return [_saved(r) for r in rows if r.dataset_code in DATASETS and can_use(company_id, user_id, r.dataset_code)]


def get_report(company_id: int, user_id: int, report_id: int) -> SavedReport:
    found = next((r for r in list_reports(company_id, user_id) if r.report_id == report_id), None)
    if found is None:
        raise ValueError("گزارش پیدا نشد یا به آن دسترسی ندارید.")
    return found


def save_report(company_id: int, user_id: int, name: str, definition: Definition, is_shared: bool = False,
                report_id: int | None = None) -> int:
    name = (name or "").strip()
    if not name:
        raise ValueError("نام گزارش را بنویسید.")
    validate(definition)
    if not can_use(company_id, user_id, definition.dataset):
        raise ValueError("به این مجموعه‌داده دسترسی ندارید.")
    with new_session() as session:
        row = None
        if report_id is not None:
            row = session.get(CustomReport, report_id)
            if row is None or row.company_id != company_id:
                raise ValueError("گزارش نامعتبر است.")
            if not _saved(row).editable_by(company_id, user_id):
                raise ValueError("فقط سازندهٔ گزارش یا مدیر سیستم آن را تغییر می‌دهد.")
        clash = session.scalar(select(CustomReport.report_id).where(
            CustomReport.company_id == company_id, CustomReport.owner_user_id == (row.owner_user_id if row else user_id),
            CustomReport.name == name, CustomReport.report_id != (report_id or 0)))
        if clash:
            raise ValueError(f"گزارشی با نام «{name}» دارید.")
        if row is None:
            row = CustomReport(company_id=company_id, owner_user_id=user_id, name=name, dataset_code=definition.dataset)
            session.add(row)
        row.name, row.dataset_code, row.definition, row.is_shared = name, definition.dataset, definition.to_json(), bool(is_shared)
        row.updated_at = datetime.datetime.now(datetime.timezone.utc)
        session.commit()
        return row.report_id


def delete_report(company_id: int, user_id: int, report_id: int) -> None:
    with new_session() as session:
        row = session.get(CustomReport, report_id)
        if row is None or row.company_id != company_id:
            raise ValueError("گزارش نامعتبر است.")
        if not _saved(row).editable_by(company_id, user_id):
            raise ValueError("فقط سازندهٔ گزارش یا مدیر سیستم آن را حذف می‌کند.")
        session.delete(row)
        session.commit()
