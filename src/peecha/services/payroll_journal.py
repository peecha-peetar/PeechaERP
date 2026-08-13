"""سرویسِ صدورِ خودکارِ سندِ حسابداریِ حقوق (فصلِ ۱۶) — با استفادهٔ
مستقیم از je_service.create_journal_entry موجود، بدونِ موتورِ تازه.

سطحِ تجمیع: به‌ازایِ هر gl_account_id (نه به‌ازایِ هر کارمند)؛ ریز در
payroll.payslips/payslip_lines قابلِ ردیابی می‌ماند.

⚠ ساده‌سازیِ آگاهانه: تفکیکِ ردیفِ هزینه به‌ازایِ مرکزِهزینه (طبقِ
سناریویِ سند) پیاده نشده، چون هستهٔ منابعِ انسانیِ فعلی (فازِ ۱) هیچ
نگاشتی بینِ hr.org_units و مرکزهزینهٔ حسابداری ندارد — افزودنِ آن یک
فازِ جداگانه است.

سهمِ کارفرمایِ بیمه هرگز به‌صورتِ payslip_line ذخیره نشده (فصلِ ۹/۱۱ فقط
سهمِ کارمند را ذخیره می‌کند)؛ چون نرخ‌ها برایِ کلِ شرکت/دوره یکسان‌اند
(نه به‌ازایِ کارمند)، سهمِ کارفرما دقیقاً از رویِ نسبتِ نرخ‌هایِ همان
InsuranceConfig بازمحاسبه می‌شود: employer_share = employee_share ×
(employer_rate + unemployment_rate) / employee_rate."""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.accounting import DetailAccount
from peecha.db.models.payroll import PayItemDefinition, Payslip, PayslipLine, PayrollJournalEntryLink, PayrollPeriod, PayrollRun
from peecha.services import audit as audit_service
from peecha.services import journal_entries as je_service
from peecha.services import payroll as payroll_service


def get_journal_entry_id_for_run(run_id: int) -> int | None:
    with new_session() as session:
        link = session.get(PayrollJournalEntryLink, run_id)
        return link.journal_entry_id if link is not None else None


@dataclass
class JournalPostingResult:
    run_id: int
    journal_entry_id: int
    total_debit: decimal.Decimal
    total_credit: decimal.Decimal


def post_run_to_journal(run_id: int, created_by_user_id: int) -> JournalPostingResult:
    with new_session() as session:
        run = session.get(PayrollRun, run_id)
        if run is None:
            raise ValueError("این اجرا یافت نشد.")
        if run.status != "APPROVED":
            raise ValueError("فقط اجرایِ تاییدشده قابلِ صدورِ سند است.")
        if session.get(PayrollJournalEntryLink, run_id) is not None:
            raise ValueError("برایِ این اجرا قبلاً سندِ حسابداری صادر شده است.")

        period = session.get(PayrollPeriod, run.period_id)
        company_id = period.company_id
        template_context = {
            "دوره": f"{period.jalali_year}/{period.jalali_month:02d}",
            "اجرا": str(run.run_no),
        }
        default_description = payroll_service.render_payroll_description(
            payroll_service.DEFAULT_PAYROLL_DESCRIPTION, template_context
        )

        def resolve_description(item: PayItemDefinition | None) -> str:
            if item is not None and item.description_template:
                item_context = dict(template_context, نام_آیتم=item.name)
                return payroll_service.render_payroll_description(item.description_template, item_context)
            return default_description

        active_items = session.scalars(
            select(PayItemDefinition).where(PayItemDefinition.company_id == company_id, PayItemDefinition.is_active.is_(True))
        ).all()
        missing = [item.code for item in active_items if item.gl_account_id is None]
        if missing:
            raise ValueError("این آیتم‌هایِ حقوقیِ فعال بدونِ حسابِ حسابداری‌اند و مانعِ صدورِ سند می‌شوند: " + "، ".join(missing))
        item_by_id = {item.pay_item_id: item for item in active_items}
        insurance_item = next((item for item in active_items if item.code == "SOCIAL_INSURANCE_EMPLOYEE"), None)

        payslip_ids = [p.payslip_id for p in session.scalars(select(Payslip).where(Payslip.run_id == run_id))]
        payslip_lines = (
            session.scalars(select(PayslipLine).where(PayslipLine.payslip_id.in_(payslip_ids))).all() if payslip_ids else []
        )

        # کلیدِ تجمیع (حساب، تفصیلی، شرح) است نه فقط حساب — طبقِ آیتمِ ۳:
        # اگر تفصیلی یا شرحِ آیتم‌هایِ حقوقیِ هم‌معین با هم فرق کند، باید
        # ردیفِ سندشان هم جدا بماند؛ وگرنه رفتارِ پیش‌فرض (بدونِ تفصیلی/
        # شرحِ سفارشی) دقیقاً همانِ تجمیعِ قبلی می‌ماند.
        debit_lines: dict[tuple[int, int | None, str], decimal.Decimal] = {}
        credit_lines: dict[tuple[int, int | None, str], decimal.Decimal] = {}
        for line in payslip_lines:
            item = item_by_id.get(line.pay_item_id)
            if item is None or item.gl_account_id is None:
                raise ValueError(f"آیتمِ «{line.pay_item_code_snapshot}» حسابِ حسابداریِ فعالی ندارد.")
            key = (item.gl_account_id, item.detail_account_id, resolve_description(item))
            bucket = debit_lines if line.phase == "EARNING_PHASE" else credit_lines
            bucket[key] = bucket.get(key, decimal.Decimal(0)) + line.amount

        employee_insurance_total = sum((l.amount for l in payslip_lines if l.phase == "INSURANCE_PHASE"), decimal.Decimal(0))
        if employee_insurance_total > 0:
            insurance_config = payroll_service.get_insurance_config(company_id, period.period_start_date)
            if insurance_config is None or insurance_config.employee_rate <= 0:
                raise ValueError("تنظیماتِ بیمه برایِ محاسبهٔ سهمِ کارفرما در دسترس نیست.")
            employer_ratio = (insurance_config.employer_rate + insurance_config.unemployment_rate) / insurance_config.employee_rate
            employer_share_total = employee_insurance_total * employer_ratio
            if employer_share_total > 0:
                if insurance_config.employer_expense_gl_account_id is None:
                    raise ValueError("حسابِ هزینهٔ سهمِ کارفرمایِ بیمه در تنظیماتِ بیمه مشخص نشده است.")
                if insurance_item is None or insurance_item.gl_account_id is None:
                    raise ValueError("حسابِ بیمهٔ پرداختنی (آیتمِ سیستمیِ بیمه) مشخص نیست.")
                insurance_description = payroll_service.render_payroll_description(
                    payroll_service.get_payroll_description_template(company_id, "PAYROLL_INSURANCE_EMPLOYER"),
                    template_context,
                )
                debit_key = (
                    insurance_config.employer_expense_gl_account_id,
                    insurance_config.employer_expense_detail_account_id,
                    insurance_description,
                )
                debit_lines[debit_key] = debit_lines.get(debit_key, decimal.Decimal(0)) + employer_share_total
                credit_key = (insurance_item.gl_account_id, insurance_item.detail_account_id, insurance_description)
                credit_lines[credit_key] = credit_lines.get(credit_key, decimal.Decimal(0)) + employer_share_total

        # حقوقِ پرداختنی/بانک — بستانکار، به‌اندازهٔ خالصِ پرداختنیِ کلِ run
        # (فصلِ ۱۴)؛ خودِ net_pay هیچ‌وقت payslip_line نیست، پس این تنها
        # جایی‌ست که مستقیماً از Payslip.net_pay جمع زده می‌شود.
        total_net_pay = sum(
            (p.net_pay for p in session.scalars(select(Payslip).where(Payslip.run_id == run_id))), decimal.Decimal(0)
        )
        if total_net_pay > 0:
            settings = payroll_service.get_company_settings(company_id)
            if settings.salary_payable_gl_account_id is None:
                raise ValueError("حسابِ حقوقِ پرداختنی/بانک در تنظیماتِ حقوق و دستمزد مشخص نشده است.")
            payable_description = payroll_service.render_payroll_description(
                payroll_service.get_payroll_description_template(company_id, "PAYROLL_PAYABLE"), template_context
            )
            payable_key = (
                settings.salary_payable_gl_account_id, settings.salary_payable_detail_account_id, payable_description,
            )
            credit_lines[payable_key] = credit_lines.get(payable_key, decimal.Decimal(0)) + total_net_pay

        total_debit = sum(debit_lines.values(), decimal.Decimal(0))
        total_credit = sum(credit_lines.values(), decimal.Decimal(0))
        if total_debit == 0 and total_credit == 0:
            raise ValueError("این اجرا هیچ مبلغی برایِ صدورِ سند ندارد.")

        def to_details(detail_account_id: int | None) -> dict[int, int]:
            if detail_account_id is None:
                return {}
            detail_account = session.get(DetailAccount, detail_account_id)
            if detail_account is None:
                return {}
            return {detail_account.dimension_type_id: detail_account_id}

        lines_input = [
            je_service.LineInput(
                account_id=account_id, description=description, debit=amount, credit=decimal.Decimal(0),
                details=to_details(detail_account_id),
            )
            for (account_id, detail_account_id, description), amount in debit_lines.items()
        ] + [
            je_service.LineInput(
                account_id=account_id, description=description, debit=decimal.Decimal(0), credit=amount,
                details=to_details(detail_account_id),
            )
            for (account_id, detail_account_id, description), amount in credit_lines.items()
        ]

    je_result = je_service.create_journal_entry(
        company_id, created_by_user_id, period.period_end_date, default_description, lines_input, entry_type_code="PAYROLL",
    )

    with new_session() as session:
        session.add(PayrollJournalEntryLink(run_id=run_id, journal_entry_id=je_result.journal_entry_id))
        run = session.get(PayrollRun, run_id)
        run.status = "POSTED"
        audit_service.log_activity(
            session, company_id=company_id, user_id=created_by_user_id, entity_type="PayrollRun", entity_id=run_id,
            action="UPDATE", changes={"after": {"status": "POSTED", "journal_entry_id": je_result.journal_entry_id}},
        )
        session.commit()

    return JournalPostingResult(run_id, je_result.journal_entry_id, total_debit, total_credit)
