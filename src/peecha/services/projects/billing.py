"""R365: فهرست بهای پیمان و صورت‌وضعیت.

- فهرست بها: ردیف‌های پیمان با شرح، واحد، مقدار قرارداد و بهای واحد؛ ردیفی که در صورت‌وضعیت آمده حذف یا تغییر بها نمی‌شود
  (تغییر بعدی با ردیف جدید یا درخواست تغییر).
- صورت‌وضعیت: مقدار «تا این تاریخ» (تجمعی) هر ردیف وارد می‌شود؛ کار این دوره = تجمعی − تجمعی صورت‌وضعیت تاییدشدهٔ قبلی.
  مقدار تجمعی کمتر از قبلی پذیرفته نمی‌شود. بیش از مقدار قرارداد مجاز است ولی هشدار دارد.
- کسور هر دوره: حسن انجام کار و بیمه (درصد از کار دوره) و استرداد پیش‌پرداخت (درصد از کار دوره، حداکثر تا ماندهٔ
  پیش‌پرداخت). این‌ها فقط برای محاسبهٔ خالص قابل پرداخت کارفرما است و سند جداگانه‌ای نمی‌سازد.
- پیش‌نویس ← تاییدشده ← فاکتورشده؛ هر پروژه یک صورت‌وضعیت پیش‌نویس دارد. فاکتور فروش هر صورت‌وضعیت تاییدشده با همان
  اسناد فروش (پیش‌نویس، با تفصیلی پروژه و کالای خدماتی تعیین‌شده) ساخته می‌شود و ثبت و مالیاتش در همان فرم فاکتور است.
"""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass, field

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.commercial import CommercialDocument
from peecha.db.models.inventory import Item
from peecha.db.models.projects import (
    BillingSettings, ContractItem, ProgressStatement, ProgressStatementLine, Project,
)

ZERO = decimal.Decimal(0)
CENT = decimal.Decimal("0.01")
STATUSES = {"DRAFT": "پیش‌نویس", "CONFIRMED": "تاییدشده", "INVOICED": "فاکتورشده", "CANCELLED": "لغوشده"}
_COUNTED = ("CONFIRMED", "INVOICED")


@dataclass
class ContractItemFields:
    code: str
    description: str
    unit: str
    contract_quantity: decimal.Decimal
    unit_price: decimal.Decimal


@dataclass
class SettingsFields:
    service_item_id: int | None = None
    retention_percent: decimal.Decimal = ZERO
    insurance_percent: decimal.Decimal = ZERO
    advance_amount: decimal.Decimal = ZERO
    advance_recovery_percent: decimal.Decimal = ZERO


@dataclass
class StatementLine:
    contract_item_id: int
    code: str
    description: str
    unit: str
    contract_quantity: decimal.Decimal
    unit_price: decimal.Decimal
    previous_quantity: decimal.Decimal
    cumulative_quantity: decimal.Decimal

    @property
    def period_quantity(self) -> decimal.Decimal:
        return self.cumulative_quantity - self.previous_quantity

    @property
    def amount_to_date(self) -> decimal.Decimal:
        return (self.cumulative_quantity * self.unit_price).quantize(CENT)

    @property
    def period_amount(self) -> decimal.Decimal:
        return self.amount_to_date - (self.previous_quantity * self.unit_price).quantize(CENT)

    @property
    def over_contract(self) -> bool:
        return self.cumulative_quantity > self.contract_quantity


@dataclass
class Statement:
    statement_id: int
    project_id: int
    statement_no: int
    period_end: datetime.date
    status_code: str
    gross_to_date: decimal.Decimal
    previous_gross: decimal.Decimal
    retention_amount: decimal.Decimal
    insurance_amount: decimal.Decimal
    advance_recovery: decimal.Decimal
    notes: str
    sales_invoice_id: int | None
    sales_invoice_no: int | None
    lines: list[StatementLine] = field(default_factory=list)

    @property
    def status_label(self) -> str:
        return STATUSES[self.status_code]

    @property
    def period_gross(self) -> decimal.Decimal:
        return self.gross_to_date - self.previous_gross

    @property
    def deductions(self) -> decimal.Decimal:
        return self.retention_amount + self.insurance_amount + self.advance_recovery

    @property
    def net_payable(self) -> decimal.Decimal:
        return self.period_gross - self.deductions


def _project(session, company_id: int, project_id: int) -> Project:
    project = session.get(Project, project_id)
    if project is None or project.company_id != company_id:
        raise ValueError("پروژه نامعتبر است.")
    return project


def _used_items(session, project_id: int) -> set[int]:
    return set(session.scalars(select(ProgressStatementLine.contract_item_id).join(
        ProgressStatement, ProgressStatement.statement_id == ProgressStatementLine.statement_id).where(
        ProgressStatement.project_id == project_id, ProgressStatement.status_code != "CANCELLED")))


# --- فهرست بها ---------------------------------------------------------------------------------------------------------
def list_contract_items(company_id: int, project_id: int) -> list[ContractItem]:
    with new_session() as session:
        _project(session, company_id, project_id)
        rows = list(session.scalars(select(ContractItem).where(ContractItem.project_id == project_id)
                                    .order_by(ContractItem.sort_order, ContractItem.contract_item_id)))
        session.expunge_all()
        return rows


def save_contract_item(company_id: int, project_id: int, f: ContractItemFields, contract_item_id: int | None = None) -> int:
    code, description, unit = (f.code or "").strip(), (f.description or "").strip(), (f.unit or "").strip()
    if not code or not description or not unit:
        raise ValueError("کد، شرح و واحد ردیف فهرست بها الزامی است.")
    quantity, price = decimal.Decimal(f.contract_quantity or 0), decimal.Decimal(f.unit_price or 0)
    if quantity <= 0 or price < 0:
        raise ValueError("مقدار قرارداد باید بیشتر از صفر و بهای واحد نامنفی باشد.")
    with new_session() as session:
        _project(session, company_id, project_id)
        if session.scalar(select(ContractItem.contract_item_id).where(
                ContractItem.project_id == project_id, func.upper(ContractItem.code) == code.upper(),
                ContractItem.contract_item_id != (contract_item_id or 0))):
            raise ValueError(f"کد «{code}» در فهرست بهای این پروژه تکراری است.")
        if contract_item_id is None:
            row = ContractItem(project_id=project_id, sort_order=(session.scalar(select(func.max(ContractItem.sort_order)).where(
                ContractItem.project_id == project_id)) or 0) + 1)
            session.add(row)
        else:
            row = session.get(ContractItem, contract_item_id)
            if row is None or row.project_id != project_id:
                raise ValueError("ردیف فهرست بها نامعتبر است.")
            if contract_item_id in _used_items(session, project_id) and price != row.unit_price:
                raise ValueError("بهای واحد ردیفی که در صورت‌وضعیت آمده تغییر نمی‌کند؛ برای بهای جدید ردیف جدید تعریف کنید.")
        row.code, row.description, row.unit, row.contract_quantity, row.unit_price = code, description, unit, quantity, price
        session.commit()
        return row.contract_item_id


def delete_contract_item(company_id: int, project_id: int, contract_item_id: int) -> None:
    with new_session() as session:
        _project(session, company_id, project_id)
        row = session.get(ContractItem, contract_item_id)
        if row is None or row.project_id != project_id:
            raise ValueError("ردیف فهرست بها نامعتبر است.")
        if contract_item_id in _used_items(session, project_id):
            raise ValueError("ردیفی که در صورت‌وضعیت آمده حذف نمی‌شود.")
        session.delete(row)
        session.commit()


def contract_total(company_id: int, project_id: int) -> decimal.Decimal:
    return sum(((r.contract_quantity * r.unit_price).quantize(CENT) for r in list_contract_items(company_id, project_id)), ZERO)


# --- تنظیمات -----------------------------------------------------------------------------------------------------------
def get_settings(company_id: int, project_id: int) -> SettingsFields:
    with new_session() as session:
        _project(session, company_id, project_id)
        row = session.get(BillingSettings, project_id)
        if row is None:
            return SettingsFields()
        return SettingsFields(row.service_item_id, row.retention_percent, row.insurance_percent, row.advance_amount,
                              row.advance_recovery_percent)


def save_settings(company_id: int, project_id: int, f: SettingsFields) -> None:
    for value in (f.retention_percent, f.insurance_percent, f.advance_recovery_percent):
        if not ZERO <= decimal.Decimal(value or 0) <= 100:
            raise ValueError("درصدها باید بین ۰ و ۱۰۰ باشد.")
    if decimal.Decimal(f.advance_amount or 0) < 0:
        raise ValueError("مبلغ پیش‌پرداخت نمی‌تواند منفی باشد.")
    with new_session() as session:
        _project(session, company_id, project_id)
        if f.service_item_id is not None:
            item = session.get(Item, f.service_item_id)
            if item is None or item.company_id != company_id or item.item_kind_code != "SERVICE":
                raise ValueError("برای فاکتور صورت‌وضعیت یک کالای خدماتی انتخاب کنید.")
        row = session.get(BillingSettings, project_id) or BillingSettings(project_id=project_id)
        session.add(row)
        row.service_item_id = f.service_item_id
        row.retention_percent = decimal.Decimal(f.retention_percent or 0)
        row.insurance_percent = decimal.Decimal(f.insurance_percent or 0)
        row.advance_amount = decimal.Decimal(f.advance_amount or 0)
        row.advance_recovery_percent = decimal.Decimal(f.advance_recovery_percent or 0)
        session.commit()


# --- صورت‌وضعیت -----------------------------------------------------------------------------------------------------------
def _previous(session, project_id: int, before_no: int | None) -> tuple[dict[int, decimal.Decimal], decimal.Decimal, decimal.Decimal]:
    """(مقدار تجمعی هر ردیف، کارکرد ناخالص تجمعی، استرداد پیش‌پرداخت تا کنون) از آخرین صورت‌وضعیت شمرده‌شدهٔ پیش از این شماره."""
    q = select(ProgressStatement).where(ProgressStatement.project_id == project_id, ProgressStatement.status_code.in_(_COUNTED))
    if before_no is not None:
        q = q.where(ProgressStatement.statement_no < before_no)
    counted = list(session.scalars(q.order_by(ProgressStatement.statement_no)))
    if not counted:
        return {}, ZERO, ZERO
    last = counted[-1]
    quantities = {ln.contract_item_id: ln.cumulative_quantity for ln in session.scalars(
        select(ProgressStatementLine).where(ProgressStatementLine.statement_id == last.statement_id))}
    return quantities, last.gross_to_date, sum((s.advance_recovery for s in counted), ZERO)


def _recalculate(session, st: ProgressStatement) -> None:
    previous, previous_gross, recovered = _previous(session, st.project_id, st.statement_no)
    lines = list(session.scalars(select(ProgressStatementLine).where(ProgressStatementLine.statement_id == st.statement_id)))
    gross = sum(((ln.cumulative_quantity * ln.unit_price).quantize(CENT) for ln in lines), ZERO)
    # ردیف‌هایی که در قبلی بوده‌اند ولی در این صورت‌وضعیت نیامده‌اند همان مقدار قبلی را دارند
    present = {ln.contract_item_id for ln in lines}
    items = {i.contract_item_id: i for i in session.scalars(select(ContractItem).where(ContractItem.project_id == st.project_id))}
    gross += sum(((q * items[cid].unit_price).quantize(CENT) for cid, q in previous.items() if cid not in present), ZERO)
    settings = session.get(BillingSettings, st.project_id) or BillingSettings(
        retention_percent=ZERO, insurance_percent=ZERO, advance_amount=ZERO, advance_recovery_percent=ZERO)
    period = gross - previous_gross
    st.gross_to_date, st.previous_gross = gross, previous_gross
    st.retention_amount = (period * settings.retention_percent / 100).quantize(CENT)
    st.insurance_amount = (period * settings.insurance_percent / 100).quantize(CENT)
    st.advance_recovery = max(ZERO, min((period * settings.advance_recovery_percent / 100).quantize(CENT),
                                        settings.advance_amount - recovered))


def new_statement(company_id: int, user_id: int | None, project_id: int, period_end: datetime.date) -> int:
    with new_session() as session:
        _project(session, company_id, project_id)
        if not session.scalar(select(ContractItem.contract_item_id).where(ContractItem.project_id == project_id).limit(1)):
            raise ValueError("ابتدا فهرست بهای پیمان را تعریف کنید.")
        if session.scalar(select(ProgressStatement.statement_id).where(
                ProgressStatement.project_id == project_id, ProgressStatement.status_code == "DRAFT")):
            raise ValueError("این پروژه یک صورت‌وضعیت پیش‌نویس دارد؛ همان را تکمیل یا لغو کنید.")
        last = session.scalar(select(ProgressStatement).where(ProgressStatement.project_id == project_id,
                                                              ProgressStatement.status_code.in_(_COUNTED))
                              .order_by(ProgressStatement.statement_no.desc()).limit(1))
        if last is not None and period_end <= last.period_end:
            raise ValueError("پایان دورهٔ صورت‌وضعیت باید بعد از پایان دورهٔ صورت‌وضعیت قبلی باشد.")
        number = (session.scalar(select(func.max(ProgressStatement.statement_no)).where(ProgressStatement.project_id == project_id)) or 0) + 1
        st = ProgressStatement(company_id=company_id, project_id=project_id, statement_no=number, period_end=period_end,
                               created_by_user_id=user_id)
        session.add(st)
        session.flush()
        previous, _gross, _rec = _previous(session, project_id, number)
        for item in session.scalars(select(ContractItem).where(ContractItem.project_id == project_id)):
            session.add(ProgressStatementLine(statement_id=st.statement_id, contract_item_id=item.contract_item_id,
                                              cumulative_quantity=previous.get(item.contract_item_id, ZERO), unit_price=item.unit_price))
        session.flush()
        _recalculate(session, st)
        session.commit()
        return st.statement_id


def _statement(session, company_id: int, statement_id: int) -> ProgressStatement:
    st = session.get(ProgressStatement, statement_id)
    if st is None or st.company_id != company_id:
        raise ValueError("صورت‌وضعیت نامعتبر است.")
    return st


def save_quantities(company_id: int, statement_id: int, quantities: dict[int, decimal.Decimal], period_end: datetime.date | None = None,
                    notes: str | None = None) -> None:
    """quantities: {ردیف فهرست بها: مقدار تجمعی تا پایان این دوره}"""
    with new_session() as session:
        st = _statement(session, company_id, statement_id)
        if st.status_code != "DRAFT":
            raise ValueError("فقط صورت‌وضعیت پیش‌نویس ویرایش می‌شود.")
        previous, _gross, _rec = _previous(session, st.project_id, st.statement_no)
        items = {i.contract_item_id: i for i in session.scalars(select(ContractItem).where(ContractItem.project_id == st.project_id))}
        lines = {ln.contract_item_id: ln for ln in session.scalars(
            select(ProgressStatementLine).where(ProgressStatementLine.statement_id == statement_id))}
        for cid, value in quantities.items():
            item = items.get(cid)
            if item is None:
                raise ValueError("ردیف فهرست بها در این پروژه نیست.")
            value = decimal.Decimal(value)
            if value < previous.get(cid, ZERO):
                raise ValueError(f"مقدار تجمعی ردیف «{item.code}» از صورت‌وضعیت قبلی کمتر است.")
            line = lines.get(cid)
            if line is None:
                line = ProgressStatementLine(statement_id=statement_id, contract_item_id=cid, unit_price=item.unit_price)
                session.add(line)
            line.cumulative_quantity = value
        if period_end is not None:
            st.period_end = period_end
        if notes is not None:
            st.notes = notes.strip() or None
        session.flush()
        _recalculate(session, st)
        session.commit()


def confirm(company_id: int, user_id: int | None, statement_id: int) -> None:
    with new_session() as session:
        st = _statement(session, company_id, statement_id)
        if st.status_code != "DRAFT":
            raise ValueError("فقط صورت‌وضعیت پیش‌نویس تایید می‌شود.")
        _recalculate(session, st)
        if st.gross_to_date - st.previous_gross <= 0:
            raise ValueError("در این دوره کاری ثبت نشده است.")
        st.status_code, st.confirmed_by_user_id = "CONFIRMED", user_id
        st.confirmed_at = datetime.datetime.now(datetime.timezone.utc)
        session.commit()


def cancel(company_id: int, statement_id: int) -> None:
    """پیش‌نویس یا تاییدشدهٔ فاکتورنشده؛ فقط آخرین صورت‌وضعیت شمرده‌شده لغو می‌شود تا مقدارهای تجمعی بعدی به‌هم نریزد."""
    with new_session() as session:
        st = _statement(session, company_id, statement_id)
        if st.status_code not in ("DRAFT", "CONFIRMED"):
            raise ValueError("صورت‌وضعیت فاکتورشده یا لغوشده لغو نمی‌شود؛ ابتدا فاکتور آن را باطل کنید.")
        later = session.scalar(select(ProgressStatement.statement_id).where(
            ProgressStatement.project_id == st.project_id, ProgressStatement.statement_no > st.statement_no,
            ProgressStatement.status_code != "CANCELLED").limit(1))
        if later:
            raise ValueError("صورت‌وضعیت بعدی وجود دارد؛ فقط آخرین صورت‌وضعیت لغو می‌شود.")
        st.status_code = "CANCELLED"
        session.commit()


def create_invoice(company_id: int, user_id: int, statement_id: int, invoice_date: datetime.date | None = None) -> int:
    """فاکتور فروش پیش‌نویس به مبلغ کار این دوره (یک ردیف کالای خدماتی پروژه) با تفصیلی پروژه و کارفرما."""
    from peecha.db.models.core import Company
    from peecha.services import commercial_documents as docs

    with new_session() as session:
        st = _statement(session, company_id, statement_id)
        if st.status_code != "CONFIRMED":
            raise ValueError("فاکتور فقط برای صورت‌وضعیت تاییدشده‌ای که هنوز فاکتور نشده ساخته می‌شود.")
        project = session.get(Project, st.project_id)
        settings = session.get(BillingSettings, st.project_id)
        if project.customer_detail_account_id is None:
            raise ValueError("کارفرمای پروژه تعیین نشده است.")
        if settings is None or settings.service_item_id is None:
            raise ValueError("کالای خدماتی فاکتور صورت‌وضعیت در تنظیمات صورت‌وضعیت پروژه تعیین نشده است.")
        item = session.get(Item, settings.service_item_id)
        currency_id = session.get(Company, company_id).base_currency_id
        amount, number = st.gross_to_date - st.previous_gross, st.statement_no
        project_detail, customer = project.project_detail_account_id, project.customer_detail_account_id
        uom_id = item.base_uom_id
    document_id = docs.create_document(company_id, user_id, "SALES_INVOICE", invoice_date or datetime.date.today(), docs.DocumentHeaderFields(
        counterparty_detail_account_id=customer, currency_id=currency_id, project_detail_account_id=project_detail,
        description=f"صورت‌وضعیت شمارهٔ {number}"))
    docs.add_line(document_id, company_id, settings.service_item_id, uom_id, decimal.Decimal(1), decimal.Decimal(1), unit_price=amount,
                  description=f"کار انجام‌شدهٔ صورت‌وضعیت شمارهٔ {number}")
    with new_session() as session:
        st = _statement(session, company_id, statement_id)
        st.status_code, st.sales_invoice_id = "INVOICED", document_id
        session.commit()
    return document_id


def get_statement(company_id: int, statement_id: int) -> Statement:
    with new_session() as session:
        st = _statement(session, company_id, statement_id)
        previous, _gross, _rec = _previous(session, st.project_id, st.statement_no)
        items = {i.contract_item_id: i for i in session.scalars(select(ContractItem).where(ContractItem.project_id == st.project_id))}
        lines = {ln.contract_item_id: ln for ln in session.scalars(
            select(ProgressStatementLine).where(ProgressStatementLine.statement_id == statement_id))}
        invoice_no = session.scalar(select(CommercialDocument.document_no).where(
            CommercialDocument.document_id == st.sales_invoice_id)) if st.sales_invoice_id else None
        out = Statement(st.statement_id, st.project_id, st.statement_no, st.period_end, st.status_code, st.gross_to_date,
                        st.previous_gross, st.retention_amount, st.insurance_amount, st.advance_recovery, st.notes or "",
                        st.sales_invoice_id, invoice_no)
        for cid, item in sorted(items.items(), key=lambda kv: (kv[1].sort_order, kv[0])):
            ln = lines.get(cid)
            prev = previous.get(cid, ZERO)
            out.lines.append(StatementLine(cid, item.code, item.description, item.unit, item.contract_quantity,
                                           ln.unit_price if ln else item.unit_price, prev, ln.cumulative_quantity if ln else prev))
        return out


def list_statements(company_id: int, project_id: int) -> list[Statement]:
    with new_session() as session:
        _project(session, company_id, project_id)
        ids = list(session.scalars(select(ProgressStatement.statement_id).where(ProgressStatement.project_id == project_id)
                                   .order_by(ProgressStatement.statement_no.desc())))
    return [get_statement(company_id, i) for i in ids]


def billing_summary(company_id: int, project_id: int) -> dict[str, decimal.Decimal]:
    """جمع کارکرد تاییدشده، فاکتورشده، کسور حسن انجام کار و بیمه و استرداد پیش‌پرداخت تا کنون."""
    with new_session() as session:
        rows = list(session.scalars(select(ProgressStatement).where(ProgressStatement.project_id == project_id,
                                                                    ProgressStatement.status_code.in_(_COUNTED))
                                    .order_by(ProgressStatement.statement_no)))
    gross = rows[-1].gross_to_date if rows else ZERO
    invoiced = sum((r.gross_to_date - r.previous_gross for r in rows if r.status_code == "INVOICED"), ZERO)
    return {"gross": gross, "invoiced": invoiced, "retention": sum((r.retention_amount for r in rows), ZERO),
            "insurance": sum((r.insurance_amount for r in rows), ZERO), "advance_recovered": sum((r.advance_recovery for r in rows), ZERO)}


def statement_print_table(company_id: int, statement_id: int, project_label: str):
    s = get_statement(company_id, statement_id)
    headers = ["کد", "شرح", "واحد", "مقدار قرارداد", "بهای واحد", "مقدار تا قبل", "مقدار این دوره", "مقدار تا کنون",
               "مبلغ تا کنون", "مبلغ این دوره"]
    rows = [[ln.code, ln.description + (" (بیش از قرارداد)" if ln.over_contract else ""), ln.unit, ln.contract_quantity, ln.unit_price,
             ln.previous_quantity, ln.period_quantity, ln.cumulative_quantity, ln.amount_to_date, ln.period_amount] for ln in s.lines]
    from peecha import decimals, numerals

    money = decimals.format_amount
    head = [("پروژه", project_label), ("پایان دوره", numerals.format_jalali_date(s.period_end)), ("وضعیت", s.status_label),
            ("کارکرد تا کنون", money(s.gross_to_date)), ("کارکرد تا قبل", money(s.previous_gross)),
            ("کارکرد این دوره", money(s.period_gross)), ("کسر حسن انجام کار", money(s.retention_amount)),
            ("کسر بیمه", money(s.insurance_amount)), ("استرداد پیش‌پرداخت", money(s.advance_recovery)),
            ("خالص قابل پرداخت این دوره", money(s.net_payable))]
    return f"صورت‌وضعیت شمارهٔ {numerals.to_persian_digits(str(s.statement_no))}", headers, rows, head
