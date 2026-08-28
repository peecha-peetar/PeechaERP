"""سرویسِ حضوروغیابِ واقعی (ورود/خروجِ روزانهٔ پرسنل) + خلاصهٔ کارکرد +
الگوهایِ ذخیره‌شدهٔ ایمپورتِ فایلِ اکسل/CSVِ دستگاه‌هایِ حضوروغیاب.

طبقِ گزارشِ صریحِ کاربر: تا این نسخه فقط ثبتِ دستیِ ساعاتِ اضافه‌کاری
(services/payroll_overtime.py) وجود داشت، نه ثبتِ واقعیِ ورود/خروجِ
روزانه یا خلاصهٔ کارکرد؛ این ماژول همان زیرساخت را می‌سازد."""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass

from sqlalchemy import select

from peecha import numerals
from peecha.db.base import new_session
from peecha.db.models.hr import AttendanceImportTemplate, AttendanceRecord, Employee

_VALID_STATUSES = ("PENDING_APPROVAL", "APPROVED", "REJECTED")


def _compute_hours(
    clock_in: datetime.time | None, clock_out: datetime.time | None, worked_hours: decimal.Decimal | None
) -> decimal.Decimal | None:
    if worked_hours is not None:
        return worked_hours
    if clock_in is not None and clock_out is not None:
        delta = datetime.datetime.combine(datetime.date.today(), clock_out) - datetime.datetime.combine(
            datetime.date.today(), clock_in
        )
        return decimal.Decimal(str(round(delta.total_seconds() / 3600, 2)))
    return None


def _validate_attendance_input(
    clock_in: datetime.time | None, clock_out: datetime.time | None, worked_hours: decimal.Decimal | None
) -> None:
    if clock_in is not None and clock_out is not None and clock_out <= clock_in:
        raise ValueError("ساعتِ خروج باید بعد از ساعتِ ورود باشد.")
    if worked_hours is None and (clock_in is None or clock_out is None):
        raise ValueError("یا ساعتِ ورود و خروج، یا مجموعِ ساعاتِ کارکرد را وارد کنید.")


# ---------------------------------------------------------------------
# رکوردهایِ حضوروغیاب (ورود/خروجِ روزانه)
# ---------------------------------------------------------------------
@dataclass
class AttendanceRecordRow:
    attendance_id: int
    employee_id: int
    employee_code: str
    employee_name: str
    work_date: datetime.date
    clock_in: datetime.time | None
    clock_out: datetime.time | None
    worked_hours: decimal.Decimal | None
    status: str
    source: str
    notes: str | None


def create_attendance_record(
    company_id: int,
    employee_id: int,
    work_date: datetime.date,
    clock_in: datetime.time | None = None,
    clock_out: datetime.time | None = None,
    worked_hours: decimal.Decimal | None = None,
    notes: str | None = None,
    *,
    source: str = "MANUAL",
    status: str = "PENDING_APPROVAL",
) -> int:
    _validate_attendance_input(clock_in, clock_out, worked_hours)
    computed_hours = _compute_hours(clock_in, clock_out, worked_hours)
    with new_session() as session:
        exists = session.scalar(
            select(AttendanceRecord).where(
                AttendanceRecord.employee_id == employee_id, AttendanceRecord.work_date == work_date
            )
        )
        if exists is not None:
            raise ValueError("برایِ این کارمند در این تاریخ قبلاً رکوردِ حضوروغیاب ثبت شده است.")
        record = AttendanceRecord(
            company_id=company_id,
            employee_id=employee_id,
            work_date=work_date,
            clock_in=clock_in,
            clock_out=clock_out,
            worked_hours=computed_hours,
            status=status,
            source=source,
            notes=notes,
        )
        session.add(record)
        session.commit()
        return record.attendance_id


def update_attendance_record(
    attendance_id: int,
    clock_in: datetime.time | None,
    clock_out: datetime.time | None,
    worked_hours: decimal.Decimal | None,
    notes: str | None,
) -> None:
    _validate_attendance_input(clock_in, clock_out, worked_hours)
    with new_session() as session:
        record = session.get(AttendanceRecord, attendance_id)
        if record is None:
            raise ValueError("رکورد یافت نشد.")
        record.clock_in = clock_in
        record.clock_out = clock_out
        record.worked_hours = _compute_hours(clock_in, clock_out, worked_hours)
        record.notes = notes
        session.commit()


def set_attendance_status(attendance_id: int, status: str) -> None:
    if status not in _VALID_STATUSES:
        raise ValueError("وضعیتِ نامعتبر.")
    with new_session() as session:
        record = session.get(AttendanceRecord, attendance_id)
        if record is None:
            raise ValueError("رکورد یافت نشد.")
        record.status = status
        session.commit()


def bulk_set_attendance_status(attendance_ids: list[int], status: str) -> None:
    for attendance_id in attendance_ids:
        set_attendance_status(attendance_id, status)


def delete_attendance_record(attendance_id: int) -> None:
    with new_session() as session:
        record = session.get(AttendanceRecord, attendance_id)
        if record is None:
            return
        session.delete(record)
        session.commit()


def list_attendance_records(
    company_id: int,
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
    employee_id: int | None = None,
) -> list[AttendanceRecordRow]:
    with new_session() as session:
        query = select(AttendanceRecord).where(AttendanceRecord.company_id == company_id)
        if start_date is not None:
            query = query.where(AttendanceRecord.work_date >= start_date)
        if end_date is not None:
            query = query.where(AttendanceRecord.work_date <= end_date)
        if employee_id is not None:
            query = query.where(AttendanceRecord.employee_id == employee_id)
        records = session.scalars(query.order_by(AttendanceRecord.work_date.desc())).all()
        employees = {e.employee_id: e for e in session.scalars(select(Employee).where(Employee.company_id == company_id)).all()}
        rows = []
        for r in records:
            emp = employees.get(r.employee_id)
            rows.append(
                AttendanceRecordRow(
                    attendance_id=r.attendance_id,
                    employee_id=r.employee_id,
                    employee_code=emp.employee_code if emp else "—",
                    employee_name=f"{emp.first_name} {emp.last_name}".strip() if emp else "—",
                    work_date=r.work_date,
                    clock_in=r.clock_in,
                    clock_out=r.clock_out,
                    worked_hours=r.worked_hours,
                    status=r.status,
                    source=r.source,
                    notes=r.notes,
                )
            )
        return rows


# ---------------------------------------------------------------------
# خلاصهٔ کارکرد (فرمِ خلاصهٔ کارکرد)
# ---------------------------------------------------------------------
@dataclass
class AttendanceSummaryRow:
    employee_id: int
    employee_code: str
    employee_name: str
    present_days: int
    total_hours: decimal.Decimal


def compute_attendance_summary(
    company_id: int, start_date: datetime.date, end_date: datetime.date, employee_id: int | None = None
) -> list[AttendanceSummaryRow]:
    records = list_attendance_records(company_id, start_date, end_date, employee_id)
    approved = [r for r in records if r.status == "APPROVED"]
    by_employee: dict[int, list[AttendanceRecordRow]] = {}
    for r in approved:
        by_employee.setdefault(r.employee_id, []).append(r)
    result = [
        AttendanceSummaryRow(
            employee_id=emp_id,
            employee_code=rows[0].employee_code,
            employee_name=rows[0].employee_name,
            present_days=len(rows),
            total_hours=sum((r.worked_hours or decimal.Decimal(0) for r in rows), decimal.Decimal(0)),
        )
        for emp_id, rows in by_employee.items()
    ]
    result.sort(key=lambda r: r.employee_code)
    return result


# ---------------------------------------------------------------------
# الگوهایِ ذخیره‌شدهٔ ایمپورتِ دستگاه‌هایِ حضوروغیاب
# ---------------------------------------------------------------------
@dataclass
class AttendanceImportTemplateRow:
    template_id: int
    name: str
    has_header_row: bool
    date_format: str
    time_format: str
    column_mapping: dict
    is_active: bool


def list_attendance_import_templates(company_id: int) -> list[AttendanceImportTemplateRow]:
    with new_session() as session:
        templates = session.scalars(
            select(AttendanceImportTemplate)
            .where(AttendanceImportTemplate.company_id == company_id, AttendanceImportTemplate.is_active)
            .order_by(AttendanceImportTemplate.name)
        ).all()
        return [
            AttendanceImportTemplateRow(
                t.template_id, t.name, t.has_header_row, t.date_format, t.time_format, dict(t.column_mapping), t.is_active
            )
            for t in templates
        ]


def create_attendance_import_template(
    company_id: int, name: str, has_header_row: bool, date_format: str, time_format: str, column_mapping: dict
) -> int:
    name = name.strip()
    if not name:
        raise ValueError("نامِ الگو الزامی است.")
    with new_session() as session:
        exists = session.scalar(
            select(AttendanceImportTemplate).where(
                AttendanceImportTemplate.company_id == company_id, AttendanceImportTemplate.name == name
            )
        )
        if exists is not None:
            raise ValueError("الگویی با این نام قبلاً ثبت شده است.")
        template = AttendanceImportTemplate(
            company_id=company_id,
            name=name,
            has_header_row=has_header_row,
            date_format=date_format,
            time_format=time_format,
            column_mapping=dict(column_mapping),
        )
        session.add(template)
        session.commit()
        return template.template_id


def update_attendance_import_template(
    template_id: int, name: str, has_header_row: bool, date_format: str, time_format: str, column_mapping: dict
) -> None:
    name = name.strip()
    if not name:
        raise ValueError("نامِ الگو الزامی است.")
    with new_session() as session:
        template = session.get(AttendanceImportTemplate, template_id)
        if template is None:
            raise ValueError("الگو یافت نشد.")
        template.name = name
        template.has_header_row = has_header_row
        template.date_format = date_format
        template.time_format = time_format
        template.column_mapping = dict(column_mapping)
        session.commit()


def delete_attendance_import_template(template_id: int) -> None:
    with new_session() as session:
        template = session.get(AttendanceImportTemplate, template_id)
        if template is None:
            return
        session.delete(template)
        session.commit()


# ---------------------------------------------------------------------
# ایمپورتِ دسته‌ای از فایلِ اکسل/CSVِ دستگاهِ حضوروغیاب — چه با الگویِ
# ذخیره‌شده (auto_approve=True، طبقِ خواستهٔ صریح «لود و تایید کنیم»)،
# چه با تناظرِ دستیِ یک‌بارهٔ ستون‌ها (auto_approve=False، درانتظارِ تایید)
# ---------------------------------------------------------------------
def _parse_date_cell(value, date_format: str) -> datetime.date:
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    text = numerals.to_ascii_digits(str(value).strip()).replace("-", "/")
    return datetime.datetime.strptime(text, date_format.replace("-", "/")).date()


def _parse_time_cell(value, time_format: str) -> datetime.time:
    if isinstance(value, datetime.datetime):
        return value.time()
    if isinstance(value, datetime.time):
        return value
    text = numerals.to_ascii_digits(str(value).strip())
    return datetime.datetime.strptime(text, time_format).time()


def import_attendance_rows(
    company_id: int,
    data_rows: list[tuple],
    mapping: dict[str, int | None],
    date_format: str,
    time_format: str,
    *,
    auto_approve: bool = False,
) -> tuple[int, list[str]]:
    with new_session() as session:
        employees = session.scalars(select(Employee).where(Employee.company_id == company_id)).all()
    employees_by_code = {e.employee_code: e.employee_id for e in employees}

    status = "APPROVED" if auto_approve else "PENDING_APPROVAL"
    created = 0
    errors: list[str] = []
    for row_no, row in enumerate(data_rows, start=1):
        try:
            employee_code = str(row[mapping["employee_code"]]).strip()
            employee_id = employees_by_code.get(employee_code)
            if employee_id is None:
                raise ValueError(f"کارمندی با کدِ «{employee_code}» یافت نشد.")

            work_date = _parse_date_cell(row[mapping["work_date"]], date_format)

            worked_hours = None
            clock_in = None
            clock_out = None
            hours_col = mapping.get("worked_hours")
            if hours_col is not None and row[hours_col] not in (None, ""):
                worked_hours = decimal.Decimal(numerals.to_ascii_digits(str(row[hours_col]).strip()))
            else:
                in_col = mapping.get("clock_in")
                out_col = mapping.get("clock_out")
                if in_col is not None and row[in_col] not in (None, ""):
                    clock_in = _parse_time_cell(row[in_col], time_format)
                if out_col is not None and row[out_col] not in (None, ""):
                    clock_out = _parse_time_cell(row[out_col], time_format)

            create_attendance_record(
                company_id,
                employee_id,
                work_date,
                clock_in=clock_in,
                clock_out=clock_out,
                worked_hours=worked_hours,
                source="IMPORT",
                status=status,
            )
            created += 1
        except (ValueError, IndexError, KeyError, decimal.InvalidOperation) as exc:
            errors.append(f"ردیفِ {row_no}: {exc}")
    return created, errors
