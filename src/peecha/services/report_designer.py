"""سرویسِ گزارش‌سازِ کامل — CRUدِ ساده‌یِ الگو/ستون/فیلترِ حساب. محاسبه
(`compute_detail_report`/`compute_summary_report`) در reports.py است، چون
آن ماژول از قبل موتورهایِ گردش/مانده و منطقِ حل‌کردنِ ردیف‌هایِ الگویِ
حسابی (statement_templates) را دارد."""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field

from sqlalchemy import delete, select

from peecha.db.base import new_session
from peecha.db.models.accounting import (
    ReportTemplate,
    ReportTemplateAccountFilter,
    ReportTemplateColumn,
)


@dataclass
class ReportTemplateRow:
    report_template_id: int
    name: str
    report_kind: str  # DETAIL | SUMMARY
    group_by_account: bool
    statement_template_id: int | None


@dataclass
class ReportColumnInfo:
    column_id: int
    column_order: int
    label: str
    field_code: str | None = None  # DETAIL kind
    measure_code: str | None = None  # SUMMARY kind
    date_from_override: datetime.date | None = None
    date_to_override: datetime.date | None = None


@dataclass
class AccountFilterInfo:
    """یک جزءِ فیلترِ حسابیِ گزارشِ تراکنشی — دقیقاً هم‌الگو با
    AccountRefInfoِ statement_templates.py، بدونِ فیلدِ sign (این‌جا فقط
    فیلترِ عضویت است، نه جمع/تفریق)."""

    selector_type: str  # ACCOUNT | RANGE | CATEGORY
    account_id: int | None = None
    account_level: int | None = None
    code_from: str | None = None
    code_to: str | None = None
    category_code: str | None = None


def list_templates(company_id: int) -> list[ReportTemplateRow]:
    with new_session() as session:
        rows = session.scalars(
            select(ReportTemplate)
            .where(ReportTemplate.company_id == company_id)
            .order_by(ReportTemplate.display_order, ReportTemplate.report_template_id)
        ).all()
        return [
            ReportTemplateRow(r.report_template_id, r.name, r.report_kind, r.group_by_account, r.statement_template_id)
            for r in rows
        ]


def create_template(
    company_id: int,
    name: str,
    report_kind: str,
    *,
    group_by_account: bool = False,
    statement_template_id: int | None = None,
) -> int:
    if report_kind == "SUMMARY" and statement_template_id is None:
        raise ValueError("برایِ گزارشِ خلاصه باید یک الگویِ حسابی انتخاب شود.")
    with new_session() as session:
        max_order = session.scalar(
            select(ReportTemplate.display_order)
            .where(ReportTemplate.company_id == company_id)
            .order_by(ReportTemplate.display_order.desc())
        )
        template = ReportTemplate(
            company_id=company_id,
            name=name,
            report_kind=report_kind,
            group_by_account=group_by_account if report_kind == "DETAIL" else False,
            statement_template_id=statement_template_id if report_kind == "SUMMARY" else None,
            display_order=(max_order or 0) + 1,
        )
        session.add(template)
        session.commit()
        return template.report_template_id


def rename_template(report_template_id: int, name: str) -> None:
    with new_session() as session:
        template = session.get(ReportTemplate, report_template_id)
        if template is None:
            raise ValueError("الگو پیدا نشد.")
        template.name = name
        session.commit()


def set_group_by_account(report_template_id: int, group_by_account: bool) -> None:
    with new_session() as session:
        template = session.get(ReportTemplate, report_template_id)
        if template is None:
            raise ValueError("الگو پیدا نشد.")
        if template.report_kind != "DETAIL":
            raise ValueError("جمعِ فرعیِ حساب فقط برایِ گزارشِ تراکنشی معنا دارد.")
        template.group_by_account = group_by_account
        session.commit()


def delete_template(report_template_id: int) -> None:
    with new_session() as session:
        session.execute(
            delete(ReportTemplateColumn).where(ReportTemplateColumn.report_template_id == report_template_id)
        )
        session.execute(
            delete(ReportTemplateAccountFilter).where(
                ReportTemplateAccountFilter.report_template_id == report_template_id
            )
        )
        session.execute(delete(ReportTemplate).where(ReportTemplate.report_template_id == report_template_id))
        session.commit()


def list_columns(report_template_id: int) -> list[ReportColumnInfo]:
    with new_session() as session:
        rows = session.scalars(
            select(ReportTemplateColumn)
            .where(ReportTemplateColumn.report_template_id == report_template_id)
            .order_by(ReportTemplateColumn.column_order)
        ).all()
        return [
            ReportColumnInfo(
                column_id=r.column_id,
                column_order=r.column_order,
                label=r.label,
                field_code=r.field_code,
                measure_code=r.measure_code,
                date_from_override=r.date_from_override,
                date_to_override=r.date_to_override,
            )
            for r in rows
        ]


def set_columns(report_template_id: int, columns: list[ReportColumnInfo]) -> None:
    """جایگزینیِ کاملِ ستون‌هایِ یک الگو."""
    with new_session() as session:
        session.execute(delete(ReportTemplateColumn).where(ReportTemplateColumn.report_template_id == report_template_id))
        for order, col in enumerate(columns, start=1):
            session.add(
                ReportTemplateColumn(
                    report_template_id=report_template_id,
                    column_order=order,
                    label=col.label,
                    field_code=col.field_code,
                    measure_code=col.measure_code,
                    date_from_override=col.date_from_override,
                    date_to_override=col.date_to_override,
                )
            )
        session.commit()


def list_account_filters(report_template_id: int) -> list[AccountFilterInfo]:
    with new_session() as session:
        rows = session.scalars(
            select(ReportTemplateAccountFilter).where(
                ReportTemplateAccountFilter.report_template_id == report_template_id
            )
        ).all()
        return [
            AccountFilterInfo(
                selector_type=r.selector_type,
                account_id=r.account_id,
                account_level=r.account_level,
                code_from=r.code_from,
                code_to=r.code_to,
                category_code=r.category_code,
            )
            for r in rows
        ]


def set_account_filters(report_template_id: int, filters: list[AccountFilterInfo]) -> None:
    """جایگزینیِ کاملِ فیلترهایِ حسابیِ یک الگو. لیستِ خالی یعنی همه‌یِ
    حساب‌هایِ قابلِ ثبت (بدونِ محدودیت)."""
    with new_session() as session:
        session.execute(
            delete(ReportTemplateAccountFilter).where(
                ReportTemplateAccountFilter.report_template_id == report_template_id
            )
        )
        for f in filters:
            session.add(
                ReportTemplateAccountFilter(
                    report_template_id=report_template_id,
                    selector_type=f.selector_type,
                    account_id=f.account_id,
                    account_level=f.account_level,
                    code_from=f.code_from,
                    code_to=f.code_to,
                    category_code=f.category_code,
                )
            )
        session.commit()
