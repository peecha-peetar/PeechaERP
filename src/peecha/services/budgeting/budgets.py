"""تعریف بودجه (R313): بودجه، دوره‌ها، کلید کنترل، نسخه، ردیف و توزیع دوره‌ای.

- بودجه = یک سال مالی + نوع دوره (سالانه/فصلی/ماهانه، بر پایهٔ ماه‌های شمسی).
- هر ترکیب ابعاد یک «کلید کنترل» ثابت دارد که میان نسخه‌ها مشترک است؛ مصرف به کلید وصل است.
- ردیف فقط در پیش‌نویس (تهیه‌کننده)، ارسال‌شده (بررسی‌کننده) و بررسی‌شده (تأییدکننده) قابل تغییر است؛
  پس از تأیید، تریگر پایگاه داده هر تغییری را رد می‌کند و اصلاح فقط با «اصلاحیه» یا «بودجهٔ تکمیلی» ممکن است.
- جمع مبلغ دوره‌ها باید دقیقاً برابر مبلغ ردیف (مصوب، یا پیشنهادی تا پیش از تعیین مصوب) باشد.
"""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass
from types import SimpleNamespace

import jdatetime
from sqlalchemy import func, select

from peecha import numerals
from peecha.db.base import new_session
from peecha.db.models.accounting import ChartOfAccount, DetailAccount, FiscalYear
from peecha.db.models.budgeting import (
    Budget, BudgetLine, BudgetPeriod, BudgetVersion, ConsumptionEntry, ControlKey, LinePeriodAmount, VersionDecision,
)
from peecha.services.budgeting import common as c

_MONTHS = ("فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند")
_STEP = {"YEAR": 12, "QUARTER": 3, "MONTH": 1}
_DIM_FIELDS = ("account_id", "cost_center_detail_account_id", "project_detail_account_id", "branch_id", "org_unit_id",
               "category_id", "purchase_type_id")
# وزن دقیق‌بودن کلید (توان‌های ۲: دو مجموعهٔ بُعد متفاوت هرگز وزن برابر ندارند)
SPECIFICITY = {"cost_center_detail_account_id": 32, "project_detail_account_id": 16, "org_unit_id": 8, "branch_id": 4,
               "purchase_type_id": 2, "category_id": 1}


@dataclass
class Dims:
    basis_code: str = "PURCHASE"
    account_id: int | None = None
    cost_center_detail_account_id: int | None = None
    project_detail_account_id: int | None = None
    branch_id: int | None = None
    org_unit_id: int | None = None
    category_id: int | None = None
    purchase_type_id: int | None = None


# --- دوره‌ها -------------------------------------------------------------------------------------------------
def _add_months(d: jdatetime.date, months: int, day: int) -> jdatetime.date:
    total = d.year * 12 + (d.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    days = 30 if month == 12 and jdatetime.date(year, 1, 1).isleap() else (29 if month == 12 else jdatetime.j_days_in_month[month - 1])
    return jdatetime.date(year, month, min(day, days))


def split_periods(date_from: datetime.date, date_to: datetime.date, period_type: str) -> list[tuple[int, datetime.date, datetime.date, str]]:
    """(شماره، از، تا، برچسب) بر پایهٔ ماه‌های شمسی از روز شروع سال مالی."""
    if period_type not in _STEP:
        raise ValueError("نوع دورهٔ بودجه نامعتبر است.")
    start = jdatetime.date.fromgregorian(date=date_from)
    out, no, cursor = [], 1, start
    while cursor.togregorian() <= date_to:
        nxt = _add_months(start, _STEP[period_type] * no, start.day)
        end = min(nxt.togregorian() - datetime.timedelta(days=1), date_to)
        if period_type == "MONTH":
            label = f"{_MONTHS[cursor.month - 1]} {cursor.year}"
        elif period_type == "QUARTER":
            label = f"فصل {no} سال {start.year}"
        else:
            label = f"سال {start.year}"
        out.append((no, cursor.togregorian(), end, numerals.to_persian_digits(label)))
        cursor, no = nxt, no + 1
    return out


def period_of(periods, when: datetime.date):
    for p in periods:
        if p.date_from <= when <= p.date_to:
            return p
    return None


# --- برچسب‌ها ------------------------------------------------------------------------------------------------
class Lookups:
    """نام ابعاد برای نمایش (یک‌بار برای هر صفحه/گزارش)."""

    def __init__(self, company_id: int) -> None:
        from peecha.services import chart_of_accounts as coa_service
        from peecha.services import inventory_catalog as catalog_service
        from peecha.services import procurement_masters as masters

        self.accounts = {a.account_id: f"{a.full_code} — {a.name}" for a in coa_service.list_accounts(company_id)}
        with new_session() as session:
            self.details = {d: f"{code} — {name or ''}" for d, code, name in session.execute(
                select(DetailAccount.detail_account_id, DetailAccount.code, DetailAccount.name)
                .where(DetailAccount.company_id == company_id))}
        self.branches = {b.branch_id: b.name for b in masters.list_branches(company_id)}
        self.departments = {d.org_unit_id: d.name for d in masters.list_departments(company_id)}
        self.categories = {g.category_id: f"{g.code} — {g.name}" for g in catalog_service.list_categories(company_id)}
        self.purchase_types = {t.purchase_type_id: t.name for t in masters.list_purchase_types(company_id)}

    def key_parts(self, key) -> list[tuple[str, str]]:
        parts = []
        if key.account_id:
            parts.append(("حساب", self.accounts.get(key.account_id, "")))
        for attr, label, names in (("cost_center_detail_account_id", "مرکز هزینه", self.details),
                                   ("project_detail_account_id", "پروژه", self.details), ("branch_id", "شعبه", self.branches),
                                   ("org_unit_id", "دپارتمان", self.departments), ("category_id", "گروه کالا", self.categories),
                                   ("purchase_type_id", "نوع خرید", self.purchase_types)):
            value = getattr(key, attr)
            if value:
                parts.append((label, names.get(value, str(value))))
        return parts

    def key_label(self, key) -> str:
        parts = self.key_parts(key)
        if not parts:
            return "کل خرید" if key.basis_code == "PURCHASE" else "—"
        return " / ".join(f"{label}: {value}" for label, value in parts)


# --- بودجه ---------------------------------------------------------------------------------------------------
def _budget(session, company_id: int, budget_id: int, lock: bool = False) -> Budget:
    q = select(Budget).where(Budget.budget_id == budget_id)
    row = session.scalar(q.with_for_update() if lock else q)
    if row is None or row.company_id != company_id:
        raise ValueError("بودجه نامعتبر است.")
    return row


def _version(session, company_id: int, version_id: int, lock: bool = False) -> tuple[BudgetVersion, Budget]:
    q = select(BudgetVersion).where(BudgetVersion.version_id == version_id)
    v = session.scalar(q.with_for_update() if lock else q)
    if v is None:
        raise ValueError("نسخهٔ بودجه نامعتبر است.")
    return v, _budget(session, company_id, v.budget_id)


def decide(session, version: BudgetVersion, action: str, old: str | None, new: str, user_id: int | None,
           comment: str | None = None) -> None:
    session.add(VersionDecision(version_id=version.version_id, action_code=action, from_status=old, to_status=new,
                                user_id=user_id, comment=(comment or None)))


def create_budget(company_id: int, user_id: int, fiscal_year_id: int, code: str, name: str, period_type: str = "MONTH",
                  owner_user_id: int | None = None, description: str | None = None) -> int:
    code, name = (code or "").strip().upper(), (name or "").strip()
    if not code or not name:
        raise ValueError("کد و نام بودجه الزامی است.")
    if period_type not in c.PERIOD_TYPE_LABELS:
        raise ValueError("نوع دورهٔ بودجه نامعتبر است.")
    c.require(company_id, user_id, c.FORM_PREPARE)
    with new_session() as session:
        fy = session.get(FiscalYear, fiscal_year_id)
        if fy is None or fy.company_id != company_id:
            raise ValueError("سال مالی نامعتبر است.")
        if fy.is_closed:
            raise ValueError("سال مالی بسته است؛ برای آن بودجهٔ جدید تعریف نمی‌شود.")
        if session.scalar(select(Budget.budget_id).where(Budget.company_id == company_id, Budget.code == code)):
            raise ValueError("این کد بودجه قبلاً تعریف شده است.")
        budget = Budget(company_id=company_id, fiscal_year_id=fiscal_year_id, code=code, name=name, period_type=period_type,
                        date_from=fy.start_date, date_to=fy.end_date, owner_user_id=owner_user_id, description=description or None,
                        created_by_user_id=user_id)
        session.add(budget)
        session.flush()
        for no, start, end, label in split_periods(fy.start_date, fy.end_date, period_type):
            session.add(BudgetPeriod(budget_id=budget.budget_id, period_no=no, date_from=start, date_to=end, label=label))
        version = BudgetVersion(budget_id=budget.budget_id, version_no=1, kind_code="ORIGINAL", status_code="DRAFT",
                                title="نسخهٔ اولیه", valid_from=fy.start_date, valid_to=fy.end_date, prepared_by_user_id=user_id)
        session.add(version)
        session.flush()
        decide(session, version, "CREATE", None, "DRAFT", user_id)
        c.audit(session, company_id, user_id, c.ENTITY_BUDGET, budget.budget_id, "CREATE",
                {"code": code, "fiscal_year": fy.code, "period_type": period_type})
        session.commit()
        return budget.budget_id


def update_budget(company_id: int, user_id: int, budget_id: int, name: str, owner_user_id: int | None,
                  description: str | None, is_active: bool = True) -> None:
    if not (name or "").strip():
        raise ValueError("نام بودجه الزامی است.")
    c.require(company_id, user_id, c.FORM_PREPARE)
    with new_session() as session:
        b = _budget(session, company_id, budget_id, lock=True)
        before = {"name": b.name, "owner": b.owner_user_id, "active": b.is_active}
        b.name, b.owner_user_id, b.description, b.is_active = name.strip(), owner_user_id, description or None, is_active
        session.flush()
        c.audit(session, company_id, user_id, c.ENTITY_BUDGET, budget_id, "UPDATE",
                {"before": before, "after": {"name": b.name, "owner": owner_user_id, "active": is_active}})
        session.commit()


def set_period_closed(company_id: int, user_id: int, budget_id: int, period_no: int, closed: bool, note: str | None = None) -> None:
    """دورهٔ بسته اصلاحیه نمی‌پذیرد و افزایش مصرف در آن فقط با مجوز استثنای ویژه ممکن است."""
    c.require(company_id, user_id, c.FORM_PERIOD)
    if not closed and not (note or "").strip():
        raise ValueError("علت بازگشایی دوره را بنویسید.")
    with new_session() as session:
        _budget(session, company_id, budget_id)
        p = session.scalar(select(BudgetPeriod).where(BudgetPeriod.budget_id == budget_id, BudgetPeriod.period_no == period_no)
                           .with_for_update())
        if p is None:
            raise ValueError("دورهٔ بودجه نامعتبر است.")
        if p.is_closed == closed:
            return
        p.is_closed = closed
        p.closed_by_user_id, p.closed_at, p.close_note = (user_id, c.now(), note or None) if closed else (None, None, note or None)
        session.flush()
        c.audit(session, company_id, user_id, c.ENTITY_BUDGET, budget_id, "PERIOD_CLOSE" if closed else "PERIOD_REOPEN",
                {"period": p.label, "note": note})
        session.commit()


# --- کلید کنترل ----------------------------------------------------------------------------------------------
def _validate_dims(session, company_id: int, dims: Dims) -> None:
    if dims.basis_code not in c.BASIS_LABELS:
        raise ValueError("مبنای ردیف بودجه نامعتبر است.")
    if dims.basis_code == "ACCOUNT":
        if not dims.account_id:
            raise ValueError("برای ردیف «حساب دفتر کل» حساب را انتخاب کنید.")
        acc = session.get(ChartOfAccount, dims.account_id)
        if acc is None or acc.company_id != company_id:
            raise ValueError("حساب نامعتبر است.")
        if dims.branch_id or dims.org_unit_id or dims.category_id or dims.purchase_type_id:
            raise ValueError("ردیف «حساب دفتر کل» فقط با حساب، مرکز هزینه و پروژه سنجیده می‌شود.")
    elif dims.account_id:
        raise ValueError("ردیف «خرید و تعهد» حساب نمی‌گیرد؛ مبنا را «حساب دفتر کل» بگذارید.")
    for attr in ("cost_center_detail_account_id", "project_detail_account_id"):
        value = getattr(dims, attr)
        if value:
            d = session.get(DetailAccount, value)
            if d is None or d.company_id != company_id:
                raise ValueError("مرکز هزینه یا پروژه نامعتبر است.")


def key_for(session, budget_id: int, dims: Dims) -> ControlKey:
    q = select(ControlKey).where(ControlKey.budget_id == budget_id, ControlKey.basis_code == dims.basis_code)
    for attr in _DIM_FIELDS:
        value = getattr(dims, attr)
        q = q.where(getattr(ControlKey, attr).is_(None) if value is None else getattr(ControlKey, attr) == value)
    key = session.scalar(q)
    if key is None:
        key = ControlKey(budget_id=budget_id, basis_code=dims.basis_code, **{a: getattr(dims, a) for a in _DIM_FIELDS})
        session.add(key)
        session.flush()
    return key


def specificity(key) -> int:
    return sum(w for attr, w in SPECIFICITY.items() if getattr(key, attr))


# --- توزیع دوره‌ای -------------------------------------------------------------------------------------------
def _periods(session, budget_id: int) -> list[BudgetPeriod]:
    return list(session.scalars(select(BudgetPeriod).where(BudgetPeriod.budget_id == budget_id).order_by(BudgetPeriod.period_no)))


def spread(amount: decimal.Decimal, period_nos: list[int], weights: list | None = None) -> dict[int, decimal.Decimal]:
    """توزیع با گرد کردن؛ باقی‌ماندهٔ گرد کردن به آخرین دوره می‌رود تا جمع دقیقاً برابر بماند."""
    amount = c.money(amount)
    if not period_nos:
        return {}
    ws = [c.dec(w) for w in (weights or [1] * len(period_nos))]
    if len(ws) != len(period_nos) or any(w < 0 for w in ws) or sum(ws) <= 0:
        raise ValueError("الگوی توزیع باید برای هر دوره یک وزن نامنفی داشته باشد و جمع وزن‌ها صفر نباشد.")
    total_w = sum(ws)
    out, used = {}, c.ZERO
    for i, (no, w) in enumerate(zip(period_nos, ws)):
        share = amount - used if i == len(period_nos) - 1 else c.money(amount * w / total_w)
        out[no] = share
        used += share
    if out[period_nos[-1]] < 0:
        raise ValueError("توزیع نامعتبر است.")
    return out


def _write_periods(session, line: BudgetLine, amounts: dict[int, decimal.Decimal]) -> None:
    existing = {p.period_no: p for p in session.scalars(select(LinePeriodAmount).where(LinePeriodAmount.line_id == line.line_id))}
    for no, value in amounts.items():
        if value < 0:
            raise ValueError("مبلغ دوره نمی‌تواند منفی باشد.")
        row = existing.pop(no, None)
        if row is None:
            session.add(LinePeriodAmount(line_id=line.line_id, period_no=no, amount=c.money(value)))
        elif row.amount != c.money(value):
            row.amount = c.money(value)
    for row in existing.values():
        session.delete(row)


def line_amount(line) -> decimal.Decimal:
    return c.dec(line.approved_amount if line.approved_amount is not None else line.proposed_amount)


def _editor_form(status: str) -> str:
    if status == "DRAFT":
        return c.FORM_PREPARE
    if status == "SUBMITTED":
        return c.FORM_REVIEW
    if status == "REVIEWED":
        return c.FORM_APPROVE
    raise ValueError(f"نسخه در وضعیت «{c.VERSION_STATUS_LABELS.get(status, status)}» قابل تغییر نیست؛ اصلاحیه بسازید.")


def _closed_periods(session, budget_id: int) -> set[int]:
    return {p.period_no for p in _periods(session, budget_id) if p.is_closed}


def _previous_period_amounts(session, version: BudgetVersion, key_id: int) -> dict[int, decimal.Decimal]:
    if not version.based_on_version_id:
        return {}
    prev = session.scalar(select(BudgetLine).where(BudgetLine.version_id == version.based_on_version_id, BudgetLine.key_id == key_id))
    if prev is None:
        return {}
    return {p.period_no: p.amount for p in session.scalars(select(LinePeriodAmount).where(LinePeriodAmount.line_id == prev.line_id))}


def _distribute(session, version: BudgetVersion, line: BudgetLine, method: str = "EQUAL", weights: list | None = None) -> None:
    """دوره‌های بسته مبلغ نسخهٔ قبل را نگه می‌دارند؛ بقیهٔ مبلغ میان دوره‌های باز توزیع می‌شود."""
    periods = _periods(session, version.budget_id)
    closed = {p.period_no for p in periods if p.is_closed}
    frozen = {no: amt for no, amt in _previous_period_amounts(session, version, line.key_id).items() if no in closed}
    open_nos = [p.period_no for p in periods if p.period_no not in closed]
    rest = line_amount(line) - sum(frozen.values(), c.ZERO)
    if rest < 0:
        raise ValueError("مبلغ ردیف از مبلغ دوره‌های بستهٔ همین ردیف کمتر است.")
    if method == "PROPORTIONAL":
        current = {p.period_no: p.amount for p in session.scalars(select(LinePeriodAmount).where(LinePeriodAmount.line_id == line.line_id))}
        weights = [current.get(no, c.ZERO) for no in open_nos]
        if sum(weights, c.ZERO) <= 0:
            weights = None
    elif method != "WEIGHTS":
        weights = None
    amounts = spread(rest, open_nos, weights) if open_nos else {}
    if not open_nos and rest != 0:
        raise ValueError("همهٔ دوره‌ها بسته‌اند؛ مبلغ ردیف تغییر نمی‌کند.")
    for no in closed:
        amounts[no] = frozen.get(no, c.ZERO)
    _write_periods(session, line, amounts)


# --- ردیف ----------------------------------------------------------------------------------------------------
def add_line(company_id: int, user_id: int, version_id: int, dims: Dims, proposed_amount, *, responsible_user_id: int | None = None,
             policy_code: str | None = None, warn_percent=None, note: str | None = None, method: str = "EQUAL",
             weights: list | None = None) -> int:
    amount = c.money(proposed_amount)
    if amount < 0:
        raise ValueError("مبلغ پیشنهادی نمی‌تواند منفی باشد.")
    if policy_code is not None and policy_code not in c.POLICY_LABELS:
        raise ValueError("سیاست ردیف نامعتبر است.")
    with new_session() as session:
        version, budget = _version(session, company_id, version_id, lock=True)
        if version.status_code != "DRAFT":
            raise ValueError("ردیف جدید فقط در نسخهٔ پیش‌نویس اضافه می‌شود.")
        c.require(company_id, user_id, c.FORM_PREPARE)
        _validate_dims(session, company_id, dims)
        key = key_for(session, budget.budget_id, dims)
        if session.scalar(select(BudgetLine.line_id).where(BudgetLine.version_id == version_id, BudgetLine.key_id == key.key_id)):
            raise ValueError("ردیفی با همین ابعاد در این نسخه هست؛ همان را ویرایش کنید.")
        no = (session.scalar(select(func.max(BudgetLine.line_no)).where(BudgetLine.version_id == version_id)) or 0) + 1
        line = BudgetLine(version_id=version_id, key_id=key.key_id, line_no=no, proposed_amount=amount, policy_code=policy_code,
                          warn_percent=c.dec(warn_percent) if warn_percent else None, responsible_user_id=responsible_user_id,
                          note=note or None)
        session.add(line)
        session.flush()
        _distribute(session, version, line, method, weights)
        c.audit(session, company_id, user_id, c.ENTITY_VERSION, version_id, "LINE_ADD", {"key": key.key_id, "amount": amount})
        session.commit()
        return line.line_id


def update_line(company_id: int, user_id: int, line_id: int, proposed_amount, *, responsible_user_id: int | None = None,
                policy_code: str | None = None, warn_percent=None, note: str | None = None, method: str = "EQUAL",
                weights: list | None = None) -> None:
    amount = c.money(proposed_amount)
    if amount < 0:
        raise ValueError("مبلغ پیشنهادی نمی‌تواند منفی باشد.")
    if policy_code is not None and policy_code not in c.POLICY_LABELS:
        raise ValueError("سیاست ردیف نامعتبر است.")
    with new_session() as session:
        line = session.get(BudgetLine, line_id)
        if line is None:
            raise ValueError("ردیف بودجه نامعتبر است.")
        version, _b = _version(session, company_id, line.version_id, lock=True)
        if version.status_code != "DRAFT":
            raise ValueError("مبلغ پیشنهادی فقط در پیش‌نویس تغییر می‌کند.")
        c.require(company_id, user_id, c.FORM_PREPARE)
        before = str(line.proposed_amount)
        line.proposed_amount, line.responsible_user_id, line.policy_code = amount, responsible_user_id, policy_code
        line.warn_percent, line.note = (c.dec(warn_percent) if warn_percent else None), note or None
        session.flush()
        _distribute(session, version, line, method, weights)
        c.audit(session, company_id, user_id, c.ENTITY_VERSION, version.version_id, "LINE_UPDATE",
                {"line": line_id, "before": before, "after": str(amount)})
        session.commit()


def delete_line(company_id: int, user_id: int, line_id: int) -> None:
    with new_session() as session:
        line = session.get(BudgetLine, line_id)
        if line is None:
            raise ValueError("ردیف بودجه نامعتبر است.")
        version, _b = _version(session, company_id, line.version_id, lock=True)
        if version.status_code != "DRAFT":
            raise ValueError("ردیف فقط در پیش‌نویس حذف می‌شود.")
        c.require(company_id, user_id, c.FORM_PREPARE)
        if version.based_on_version_id and session.scalar(select(ConsumptionEntry.entry_id).where(
                ConsumptionEntry.key_id == line.key_id).limit(1)):
            raise ValueError("برای این ردیف مصرف ثبت شده است؛ به‌جای حذف، مبلغ آن را تغییر دهید.")
        session.delete(line)
        session.flush()
        c.audit(session, company_id, user_id, c.ENTITY_VERSION, version.version_id, "LINE_DELETE", {"key": line.key_id})
        session.commit()


def set_period_amounts(company_id: int, user_id: int, line_id: int, amounts: dict[int, decimal.Decimal]) -> None:
    """توزیع دستی؛ جمع باید دقیقاً برابر مبلغ ردیف باشد و دورهٔ بسته تغییر نکند."""
    with new_session() as session:
        line = session.get(BudgetLine, line_id)
        if line is None:
            raise ValueError("ردیف بودجه نامعتبر است.")
        version, _b = _version(session, company_id, line.version_id, lock=True)
        c.require(company_id, user_id, _editor_form(version.status_code))
        periods = _periods(session, version.budget_id)
        nos = {p.period_no for p in periods}
        clean = {int(k): c.money(v) for k, v in amounts.items()}
        if set(clean) - nos:
            raise ValueError("دورهٔ نامعتبر در توزیع.")
        full = {no: clean.get(no, c.ZERO) for no in nos}
        if sum(full.values(), c.ZERO) != line_amount(line):
            raise ValueError(f"جمع دوره‌ها ({numerals.format_money(sum(full.values(), c.ZERO), 0, None)}) با مبلغ ردیف "
                             f"({numerals.format_money(line_amount(line), 0, None)}) برابر نیست.")
        frozen = _previous_period_amounts(session, version, line.key_id)
        current = {p.period_no: p.amount for p in session.scalars(select(LinePeriodAmount).where(LinePeriodAmount.line_id == line_id))}
        for no in _closed_periods(session, version.budget_id):
            if full[no] != frozen.get(no, current.get(no, c.ZERO)):
                raise ValueError("مبلغ دورهٔ بسته تغییر نمی‌کند.")
        _write_periods(session, line, full)
        session.flush()
        c.audit(session, company_id, user_id, c.ENTITY_VERSION, version.version_id, "LINE_PERIODS",
                {"line": line_id, "amounts": {str(k): str(v) for k, v in full.items()}})
        session.commit()


def redistribute(company_id: int, user_id: int, line_id: int, method: str = "EQUAL", weights: list | None = None) -> None:
    with new_session() as session:
        line = session.get(BudgetLine, line_id)
        if line is None:
            raise ValueError("ردیف بودجه نامعتبر است.")
        version, _b = _version(session, company_id, line.version_id, lock=True)
        c.require(company_id, user_id, _editor_form(version.status_code))
        _distribute(session, version, line, method, weights)
        session.commit()


def set_approved_amount(company_id: int, user_id: int, line_id: int, amount, note: str | None = None) -> None:
    """بررسی‌کننده (در ارسال‌شده) یا تأییدکننده (در بررسی‌شده) مبلغ مصوب را تعیین می‌کند؛ توزیع به همان نسبت."""
    amount = c.money(amount)
    if amount < 0:
        raise ValueError("مبلغ مصوب نمی‌تواند منفی باشد.")
    with new_session() as session:
        line = session.get(BudgetLine, line_id)
        if line is None:
            raise ValueError("ردیف بودجه نامعتبر است.")
        version, _b = _version(session, company_id, line.version_id, lock=True)
        if version.status_code not in ("SUBMITTED", "REVIEWED"):
            raise ValueError("مبلغ مصوب فقط هنگام بررسی یا تأیید تعیین می‌شود.")
        c.require(company_id, user_id, _editor_form(version.status_code))
        before = line.approved_amount
        line.approved_amount = amount
        session.flush()
        _distribute(session, version, line, "PROPORTIONAL")
        decide(session, version, "ADJUST", version.status_code, version.status_code, user_id,
               f"ردیف {line.line_no}: {numerals.format_money(c.dec(before if before is not None else line.proposed_amount), 0, None)} ← "
               f"{numerals.format_money(amount, 0, None)}" + (f" — {note}" if note else ""))
        c.audit(session, company_id, user_id, c.ENTITY_VERSION, version.version_id, "APPROVED_AMOUNT",
                {"line": line_id, "before": before, "after": amount, "note": note})
        session.commit()


def validate(session, version: BudgetVersion) -> list[str]:
    problems = []
    lines = list(session.scalars(select(BudgetLine).where(BudgetLine.version_id == version.version_id).order_by(BudgetLine.line_no)))
    if not lines:
        problems.append("نسخه هیچ ردیفی ندارد.")
    amounts: dict[int, list] = {}
    for p in session.scalars(select(LinePeriodAmount).where(LinePeriodAmount.line_id.in_([ln.line_id for ln in lines] or [0]))):
        amounts.setdefault(p.line_id, []).append(p.amount)
    for ln in lines:
        total = sum(amounts.get(ln.line_id, []), c.ZERO)
        if total != line_amount(ln):
            problems.append(f"ردیف {numerals.to_persian_digits(str(ln.line_no))}: جمع دوره‌ها با مبلغ ردیف برابر نیست.")
        if version.kind_code == "SUPPLEMENT" and ln.previous_amount is not None and line_amount(ln) < ln.previous_amount:
            problems.append(f"ردیف {numerals.to_persian_digits(str(ln.line_no))}: بودجهٔ تکمیلی فقط مبلغ را افزایش می‌دهد؛ "
                            "برای کاهش اصلاحیه بسازید.")
    return problems


# --- اصلاحیه و تکمیلی ----------------------------------------------------------------------------------------
def published_version(session, budget_id: int) -> BudgetVersion | None:
    return session.scalar(select(BudgetVersion).where(BudgetVersion.budget_id == budget_id, BudgetVersion.status_code == "PUBLISHED"))


def create_revision(company_id: int, user_id: int, budget_id: int, kind_code: str = "AMENDMENT", title: str | None = None,
                    description: str | None = None) -> int:
    """نسخهٔ تازه از روی نسخهٔ منتشرشده؛ مبلغ قبلی هر ردیف نگه داشته می‌شود تا مبلغ اصلاحیه روشن باشد."""
    if kind_code not in ("AMENDMENT", "SUPPLEMENT"):
        raise ValueError("نوع نسخه نامعتبر است.")
    c.require(company_id, user_id, c.FORM_PREPARE)
    with new_session() as session:
        budget = _budget(session, company_id, budget_id, lock=True)
        base = published_version(session, budget_id)
        if base is None:
            raise ValueError("این بودجه هنوز نسخهٔ منتشرشده ندارد؛ همان نسخهٔ اولیه را کامل کنید.")
        if session.scalar(select(BudgetVersion.version_id).where(BudgetVersion.budget_id == budget_id,
                                                                 BudgetVersion.status_code.in_(c.OPEN_VERSION))):
            raise ValueError("برای این بودجه یک نسخهٔ باز (در حال تهیه یا تأیید) هست؛ ابتدا همان را به پایان برسانید.")
        no = (session.scalar(select(func.max(BudgetVersion.version_no)).where(BudgetVersion.budget_id == budget_id)) or 0) + 1
        version = BudgetVersion(budget_id=budget_id, version_no=no, kind_code=kind_code, status_code="DRAFT", based_on_version_id=base.version_id,
                                title=(title or "").strip() or f"{c.KIND_LABELS[kind_code]} {numerals.to_persian_digits(str(no - 1))}",
                                description=description or None, valid_from=base.valid_from, valid_to=base.valid_to,
                                prepared_by_user_id=user_id)
        session.add(version)
        session.flush()
        for ln in session.scalars(select(BudgetLine).where(BudgetLine.version_id == base.version_id).order_by(BudgetLine.line_no)):
            copy = BudgetLine(version_id=version.version_id, key_id=ln.key_id, line_no=ln.line_no, proposed_amount=line_amount(ln),
                              previous_amount=line_amount(ln), policy_code=ln.policy_code, warn_percent=ln.warn_percent,
                              responsible_user_id=ln.responsible_user_id, note=ln.note)
            session.add(copy)
            session.flush()
            _write_periods(session, copy, {p.period_no: p.amount for p in session.scalars(
                select(LinePeriodAmount).where(LinePeriodAmount.line_id == ln.line_id))})
        decide(session, version, "CREATE", None, "DRAFT", user_id, description)
        c.audit(session, company_id, user_id, c.ENTITY_BUDGET, budget.budget_id, "REVISION",
                {"version": no, "kind": kind_code, "based_on": base.version_no})
        session.commit()
        return version.version_id


# --- خواندن --------------------------------------------------------------------------------------------------
def list_budgets(company_id: int, active_only: bool = False) -> list[SimpleNamespace]:
    with new_session() as session:
        budgets = list(session.scalars(select(Budget).where(Budget.company_id == company_id).order_by(Budget.date_from.desc(), Budget.code)))
        fys = {f.fiscal_year_id: f.code for f in session.scalars(select(FiscalYear).where(FiscalYear.company_id == company_id))}
        versions = {}
        for v in session.scalars(select(BudgetVersion).where(BudgetVersion.budget_id.in_([b.budget_id for b in budgets] or [0]))
                                 .order_by(BudgetVersion.version_no)):
            versions.setdefault(v.budget_id, []).append(v)
        out = []
        for b in budgets:
            if active_only and not b.is_active:
                continue
            vs = versions.get(b.budget_id, [])
            pub = next((v for v in vs if v.status_code == "PUBLISHED"), None)
            open_v = next((v for v in vs if v.status_code in c.OPEN_VERSION), None)
            out.append(SimpleNamespace(
                budget_id=b.budget_id, code=b.code, name=b.name, fiscal_year=fys.get(b.fiscal_year_id, ""),
                period_type=b.period_type, period_label=c.PERIOD_TYPE_LABELS[b.period_type], date_from=b.date_from, date_to=b.date_to,
                owner_user_id=b.owner_user_id, is_active=b.is_active, published_version_id=pub.version_id if pub else None,
                published_no=pub.version_no if pub else None, open_version_id=open_v.version_id if open_v else None,
                open_status=open_v.status_code if open_v else None,
                open_status_label=c.VERSION_STATUS_LABELS[open_v.status_code] if open_v else "",
                version_count=len(vs)))
        return out


def get_budget(company_id: int, budget_id: int) -> SimpleNamespace:
    with new_session() as session:
        b = _budget(session, company_id, budget_id)
        periods = _periods(session, budget_id)
        versions = list(session.scalars(select(BudgetVersion).where(BudgetVersion.budget_id == budget_id).order_by(BudgetVersion.version_no)))
        names = c.user_names(session, [b.owner_user_id] + [p.closed_by_user_id for p in periods])
        fy = session.get(FiscalYear, b.fiscal_year_id)
        return SimpleNamespace(
            budget_id=b.budget_id, code=b.code, name=b.name, fiscal_year_id=b.fiscal_year_id, fiscal_year=fy.code if fy else "",
            period_type=b.period_type, period_label=c.PERIOD_TYPE_LABELS[b.period_type], date_from=b.date_from, date_to=b.date_to,
            owner_user_id=b.owner_user_id, owner_name=names.get(b.owner_user_id, ""), description=b.description, is_active=b.is_active,
            periods=[SimpleNamespace(period_no=p.period_no, date_from=p.date_from, date_to=p.date_to, label=p.label, is_closed=p.is_closed,
                                     closed_by=names.get(p.closed_by_user_id, ""), closed_at=p.closed_at, close_note=p.close_note)
                     for p in periods],
            versions=[SimpleNamespace(version_id=v.version_id, version_no=v.version_no, kind_code=v.kind_code,
                                      kind_label=c.KIND_LABELS[v.kind_code], status_code=v.status_code,
                                      status_label=c.VERSION_STATUS_LABELS[v.status_code], title=v.title, created_at=v.created_at,
                                      published_at=v.published_at) for v in versions])


def get_version(company_id: int, version_id: int, lookups: Lookups | None = None) -> SimpleNamespace:
    lookups = lookups or Lookups(company_id)
    with new_session() as session:
        v, b = _version(session, company_id, version_id)
        lines = list(session.scalars(select(BudgetLine).where(BudgetLine.version_id == version_id).order_by(BudgetLine.line_no)))
        keys = {k.key_id: k for k in session.scalars(select(ControlKey).where(ControlKey.key_id.in_([ln.key_id for ln in lines] or [0])))}
        periods = {}
        for p in session.scalars(select(LinePeriodAmount).where(LinePeriodAmount.line_id.in_([ln.line_id for ln in lines] or [0]))):
            periods.setdefault(p.line_id, {})[p.period_no] = p.amount
        decisions = list(session.scalars(select(VersionDecision).where(VersionDecision.version_id == version_id)
                                         .order_by(VersionDecision.decided_at, VersionDecision.decision_id)))
        names = c.user_names(session, [v.prepared_by_user_id, v.submitted_by_user_id, v.reviewed_by_user_id, v.approved_by_user_id,
                                       v.published_by_user_id] + [d.user_id for d in decisions] + [ln.responsible_user_id for ln in lines])
        problems = validate(session, v)
        return SimpleNamespace(
            version_id=v.version_id, budget_id=b.budget_id, budget_code=b.code, budget_name=b.name, version_no=v.version_no,
            kind_code=v.kind_code, kind_label=c.KIND_LABELS[v.kind_code], status_code=v.status_code,
            status_label=c.VERSION_STATUS_LABELS[v.status_code], title=v.title, description=v.description,
            valid_from=v.valid_from, valid_to=v.valid_to, based_on_version_id=v.based_on_version_id,
            prepared_by_user_id=v.prepared_by_user_id, prepared_by=names.get(v.prepared_by_user_id, ""),
            submitted_by=names.get(v.submitted_by_user_id, ""), submitted_at=v.submitted_at,
            reviewed_by_user_id=v.reviewed_by_user_id, reviewed_by=names.get(v.reviewed_by_user_id, ""), reviewed_at=v.reviewed_at,
            approved_by=names.get(v.approved_by_user_id, ""), approved_at=v.approved_at,
            published_by=names.get(v.published_by_user_id, ""), published_at=v.published_at, reject_reason=v.reject_reason,
            problems=problems,
            total_proposed=sum((ln.proposed_amount for ln in lines), c.ZERO),
            total_amount=sum((line_amount(ln) for ln in lines), c.ZERO),
            total_previous=sum((c.dec(ln.previous_amount) for ln in lines), c.ZERO),
            lines=[SimpleNamespace(
                line_id=ln.line_id, line_no=ln.line_no, key_id=ln.key_id, key=keys[ln.key_id], basis_code=keys[ln.key_id].basis_code,
                basis_label=c.BASIS_LABELS[keys[ln.key_id].basis_code], label=lookups.key_label(keys[ln.key_id]),
                proposed_amount=ln.proposed_amount, approved_amount=ln.approved_amount, amount=line_amount(ln),
                previous_amount=ln.previous_amount,
                change=(line_amount(ln) - ln.previous_amount) if ln.previous_amount is not None else None,
                policy_code=ln.policy_code, policy_label=c.POLICY_LABELS.get(ln.policy_code, "طبق سیاست شرکت"),
                warn_percent=ln.warn_percent, responsible_user_id=ln.responsible_user_id,
                responsible=names.get(ln.responsible_user_id, ""), note=ln.note, periods=periods.get(ln.line_id, {}))
                for ln in lines],
            decisions=[SimpleNamespace(action_code=d.action_code, action_label=c.ACTION_LABELS.get(d.action_code, d.action_code),
                                       from_status=d.from_status, to_status=d.to_status,
                                       to_label=c.VERSION_STATUS_LABELS.get(d.to_status, d.to_status), user=names.get(d.user_id, ""),
                                       user_id=d.user_id, at=d.decided_at, comment=d.comment) for d in decisions])


# --- انتقال بودجه‌های سادهٔ خرید (R243) ----------------------------------------------------------------------
def import_simple_budgets(company_id: int, user_id: int, version_id: int) -> int:
    """بودجه‌های سادهٔ خرید هم‌دوره را به‌صورت ردیف «خرید و تعهد» به نسخهٔ پیش‌نویس می‌آورد (بدون تکرار)."""
    from peecha.db.models.commercial import PurchaseBudget

    with new_session() as session:
        version, budget = _version(session, company_id, version_id)
        if version.status_code != "DRAFT":
            raise ValueError("ردیف فقط به نسخهٔ پیش‌نویس اضافه می‌شود.")
        legacy = list(session.scalars(select(PurchaseBudget).where(
            PurchaseBudget.company_id == company_id, PurchaseBudget.is_active.is_(True),
            PurchaseBudget.period_from <= budget.date_to, PurchaseBudget.period_to >= budget.date_from)))
    added = 0
    for pb in legacy:
        dims = Dims("PURCHASE", None, pb.cost_center_detail_account_id, pb.project_detail_account_id, pb.branch_id, pb.org_unit_id,
                    pb.category_id, None)
        try:
            add_line(company_id, user_id, version_id, dims, pb.amount, warn_percent=pb.warn_percent,
                     note=f"از بودجهٔ سادهٔ خرید «{pb.code} — {pb.name}»")
            added += 1
        except ValueError as exc:
            if "همین ابعاد" not in str(exc):
                raise
    return added
