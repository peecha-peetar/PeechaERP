"""سرویسِ تولیدِ فایلِ بانکیِ پرداختِ گروهیِ حقوق (فصلِ ۱۵).

⚠ ساده‌سازیِ آگاهانه (هم‌راستا با یادداشتِ خودِ db/schema/046): چون
مشخصاتِ رسمیِ فایلِ هیچ بانکِ ایرانی‌ای در دسترس نیست، خروجی یک CSV
عمومی است (نه قالبِ اختصاصیِ بانک)؛ افزودنِ قالب‌هایِ رسمی در آینده
بدونِ تغییرِ هستهٔ این سرویس ممکن است.

⚠ ساده‌سازیِ دوم: چون hr.employees (فازِ ۱ از هستهٔ منابعِ انسانی)
فیلدِ bank_id ندارد، اعتبارسنجیِ «متعلق‌بودن به همان بانک» طبقِ سند
انجام نمی‌شود — فقط وجودِ شماره‌حساب/شبا برایِ کارمند بررسی می‌شود."""

from __future__ import annotations

import csv
import decimal
import io
from dataclasses import dataclass, field

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.hr import Employee
from peecha.db.models.payroll import BankPaymentBatch, BankPaymentLine, Payslip, PayrollRun


@dataclass
class BankExceptionRow:
    employee_id: int
    employee_name: str
    net_pay: decimal.Decimal
    reason: str


@dataclass
class BankBatchResult:
    batch_id: int
    total_amount: decimal.Decimal
    included_count: int
    exceptions: list[BankExceptionRow] = field(default_factory=list)


def create_bank_batch(run_id: int, bank_id: int) -> BankBatchResult:
    with new_session() as session:
        run = session.get(PayrollRun, run_id)
        if run is None:
            raise ValueError("این اجرا یافت نشد.")
        if run.status not in ("APPROVED", "POSTED", "LOCKED"):
            raise ValueError("فقط اجرایِ تاییدشده (یا بالاتر) قابلِ تولیدِ فایلِ بانکی است.")

        rows = session.execute(select(Payslip, Employee).join(Employee, Employee.employee_id == Payslip.employee_id).where(Payslip.run_id == run_id)).all()
        already_batched_employee_ids = {
            employee_id
            for (employee_id,) in session.execute(
                select(BankPaymentLine.employee_id)
                .join(BankPaymentBatch, BankPaymentBatch.batch_id == BankPaymentLine.batch_id)
                .where(BankPaymentBatch.run_id == run_id)
            )
        }

        exceptions: list[BankExceptionRow] = []
        included: list[tuple[Payslip, Employee]] = []
        for payslip, employee in rows:
            full_name = f"{employee.first_name} {employee.last_name}"
            if employee.employee_id in already_batched_employee_ids:
                exceptions.append(BankExceptionRow(employee.employee_id, full_name, payslip.net_pay, "قبلاً در batchِ دیگری برایِ همین اجرا گنجانده شده است."))
                continue
            if payslip.net_pay <= 0:
                exceptions.append(BankExceptionRow(employee.employee_id, full_name, payslip.net_pay, "خالصِ پرداختنی صفر یا منفی است."))
                continue
            account_no = (employee.bank_iban or employee.bank_account_no or "").strip()
            if not account_no:
                exceptions.append(BankExceptionRow(employee.employee_id, full_name, payslip.net_pay, "بدونِ شماره‌حساب/شبایِ معتبر."))
                continue
            if employee.bank_iban and not (employee.bank_iban.upper().startswith("IR") and len(employee.bank_iban) == 26):
                exceptions.append(BankExceptionRow(employee.employee_id, full_name, payslip.net_pay, "فرمتِ شبا نامعتبر است."))
                continue
            included.append((payslip, employee))

        total_amount = sum((p.net_pay for p, _ in included), decimal.Decimal(0))
        batch = BankPaymentBatch(run_id=run_id, bank_id=bank_id, total_amount=total_amount, status="DRAFT")
        session.add(batch)
        session.flush()
        for payslip, employee in included:
            account_no = (employee.bank_iban or employee.bank_account_no or "").strip()
            session.add(
                BankPaymentLine(
                    batch_id=batch.batch_id, payslip_id=payslip.payslip_id, employee_id=employee.employee_id,
                    bank_account_no=account_no, amount=payslip.net_pay, line_status="PENDING",
                )
            )
        assert sum((p.net_pay for p, _ in included), decimal.Decimal(0)) == total_amount, "جمعِ مبالغِ batch باید دقیقاً برابرِ جمعِ net_pay فیش‌هایِ شامل‌شده باشد."
        session.commit()
        return BankBatchResult(batch.batch_id, total_amount, len(included), exceptions)


@dataclass
class BankBatchRow:
    batch_id: int
    run_id: int
    bank_id: int
    total_amount: decimal.Decimal
    status: str


def list_bank_batches(run_id: int) -> list[BankBatchRow]:
    with new_session() as session:
        rows = session.scalars(select(BankPaymentBatch).where(BankPaymentBatch.run_id == run_id)).all()
        return [BankBatchRow(b.batch_id, b.run_id, b.bank_id, b.total_amount, b.status) for b in rows]


@dataclass
class BankPaymentLineRow:
    line_id: int
    employee_id: int
    employee_code: str
    employee_name: str
    bank_account_no: str
    amount: decimal.Decimal
    line_status: str


def list_bank_batch_lines(batch_id: int) -> list[BankPaymentLineRow]:
    with new_session() as session:
        rows = session.execute(
            select(BankPaymentLine, Employee).join(Employee, Employee.employee_id == BankPaymentLine.employee_id).where(BankPaymentLine.batch_id == batch_id)
        ).all()
        return [
            BankPaymentLineRow(l.line_id, e.employee_id, e.employee_code, f"{e.first_name} {e.last_name}", l.bank_account_no, l.amount, l.line_status)
            for l, e in rows
        ]


def mark_batch_sent(batch_id: int) -> None:
    with new_session() as session:
        batch = session.get(BankPaymentBatch, batch_id)
        if batch is None:
            raise ValueError("این batch یافت نشد.")
        if batch.status != "DRAFT":
            raise ValueError("فقط batchِ پیش‌نویس قابلِ ارسال است.")
        batch.status = "SENT"
        for line in session.scalars(select(BankPaymentLine).where(BankPaymentLine.batch_id == batch_id)):
            line.line_status = "SENT"
        session.commit()


def confirm_batch_line(line_id: int) -> None:
    with new_session() as session:
        line = session.get(BankPaymentLine, line_id)
        if line is None:
            raise ValueError("این ردیف یافت نشد.")
        if line.line_status != "SENT":
            raise ValueError("فقط ردیفِ ارسال‌شده قابلِ تاییدِ واریز است.")
        line.line_status = "CONFIRMED"
        session.commit()
        batch = session.get(BankPaymentBatch, line.batch_id)
        other_lines = session.scalars(select(BankPaymentLine).where(BankPaymentLine.batch_id == batch.batch_id)).all()
        if all(l.line_status == "CONFIRMED" for l in other_lines):
            batch.status = "CONFIRMED"
            session.commit()


def fail_batch_line(line_id: int) -> None:
    with new_session() as session:
        line = session.get(BankPaymentLine, line_id)
        if line is None:
            raise ValueError("این ردیف یافت نشد.")
        if line.line_status != "SENT":
            raise ValueError("فقط ردیفِ ارسال‌شده قابلِ ثبتِ برگشت است.")
        line.line_status = "FAILED"
        session.commit()


def create_correction_batch_for_failed(original_batch_id: int, bank_id: int) -> BankBatchResult:
    """فقط ردیف‌هایِ FAILEDِ batchِ اصلی را در یک batchِ اصلاحیِ تازه می‌گذارد."""
    with new_session() as session:
        original = session.get(BankPaymentBatch, original_batch_id)
        if original is None:
            raise ValueError("این batch یافت نشد.")
        failed_lines = session.execute(
            select(BankPaymentLine, Employee)
            .join(Employee, Employee.employee_id == BankPaymentLine.employee_id)
            .where(BankPaymentLine.batch_id == original_batch_id, BankPaymentLine.line_status == "FAILED")
        ).all()
        if not failed_lines:
            raise ValueError("هیچ ردیفِ برگشت‌خورده‌ای برایِ اصلاح وجود ندارد.")
        total_amount = sum((l.amount for l, _ in failed_lines), decimal.Decimal(0))
        batch = BankPaymentBatch(run_id=original.run_id, bank_id=bank_id, total_amount=total_amount, status="DRAFT")
        session.add(batch)
        session.flush()
        for line, employee in failed_lines:
            session.add(
                BankPaymentLine(
                    batch_id=batch.batch_id, payslip_id=line.payslip_id, employee_id=employee.employee_id,
                    bank_account_no=line.bank_account_no, amount=line.amount, line_status="PENDING",
                )
            )
        session.commit()
        return BankBatchResult(batch.batch_id, total_amount, len(failed_lines), [])


def export_bank_batch_csv(batch_id: int) -> str:
    lines = list_bank_batch_lines(batch_id)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["ردیف", "کدِ پرسنلی", "نامِ کارمند", "شمارهحساب/شبا", "مبلغ"])
    for idx, line in enumerate(lines, start=1):
        writer.writerow([idx, line.employee_code, line.employee_name, line.bank_account_no, str(line.amount)])
    return buffer.getvalue()
