"""مدیریتِ رجیستریِ گزارش‌هایِ حرفه‌ایِ قابلِ‌تخصیص برایِ هر فرم -- طبقِ
درخواستِ صریح («برایِ کاردکس/فاکتور بتوان چند گزارشِ نام‌گذاری‌شده
تعریف/ویرایش/اجرا کرد»). خودِ jrxml هرکدام یک کپیِ مستقل (از قالبِ پایه‌یِ
همان فرم) است که زیرِ پوشه‌یِ دادهٔ برنامه (نه گیت) نگه‌داری می‌شود -- طبقِ
تصمیمِ 098_report_template_registry.sql / reporting/registry.py."""

from __future__ import annotations

import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

from peecha.config import SETTINGS_DIR
from peecha.db.base import new_session
from peecha.db.models.reporting import ReportTemplate
from peecha.reporting import jasper_bridge
from peecha.reporting.registry import FORM_DEFINITIONS

_TEMPLATES_ROOT = SETTINGS_DIR / "report_templates"


@dataclass
class ReportTemplateRow:
    report_template_id: int
    form_code: str
    name: str
    file_name: str
    is_default: bool


def _custom_dir(company_id: int) -> Path:
    path = _TEMPLATES_ROOT / str(company_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _to_row(r: ReportTemplate) -> ReportTemplateRow:
    return ReportTemplateRow(r.report_template_id, r.form_code, r.name, r.file_name, r.is_default)


def list_templates(company_id: int, form_code: str) -> list[ReportTemplateRow]:
    with new_session() as session:
        rows = session.scalars(
            select(ReportTemplate)
            .where(ReportTemplate.company_id == company_id, ReportTemplate.form_code == form_code)
            .order_by(ReportTemplate.name)
        ).all()
        return [_to_row(r) for r in rows]


def get_template_path(report_template_id: int, company_id: int) -> Path:
    with new_session() as session:
        row = session.get(ReportTemplate, report_template_id)
        if row is None or row.company_id != company_id:
            raise ValueError("گزارش یافت نشد.")
        return _custom_dir(company_id) / row.file_name


def get_default_template_path(company_id: int, form_code: str) -> Path | None:
    with new_session() as session:
        row = session.scalar(
            select(ReportTemplate).where(
                ReportTemplate.company_id == company_id,
                ReportTemplate.form_code == form_code,
                ReportTemplate.is_default.is_(True),
            )
        )
        if row is None:
            return None
        return _custom_dir(company_id) / row.file_name


def create_template(company_id: int, form_code: str, name: str) -> ReportTemplateRow:
    definition = FORM_DEFINITIONS.get(form_code)
    if definition is None:
        raise ValueError("فرمِ نامعتبر.")
    name = name.strip()
    if not name:
        raise ValueError("نام الزامی است.")

    with new_session() as session:
        existing = session.scalar(
            select(ReportTemplate).where(
                ReportTemplate.company_id == company_id,
                ReportTemplate.form_code == form_code,
                ReportTemplate.name == name,
            )
        )
        if existing is not None:
            raise ValueError("گزارشی با همین نام از قبل برایِ این فرم وجود دارد.")

        # همیشه از رویِ قالبِ پایه‌یِ همان فرم شروع می‌کنیم -- طبقِ
        # تصمیمِ معماریِ Jasper: هیچ‌وقت طراحِ گزارش با فایلِ خالی
        # شروع نمی‌کند، همیشه یک نسخه‌یِ کارکردنیِ اولیه در دست دارد.
        base_path = jasper_bridge.template_path(definition["base_template"])
        file_name = f"{form_code.lower()}_{uuid.uuid4().hex[:10]}.jrxml"
        dest_path = _custom_dir(company_id) / file_name
        shutil.copyfile(base_path, dest_path)

        is_first = session.scalar(
            select(ReportTemplate.report_template_id).where(
                ReportTemplate.company_id == company_id, ReportTemplate.form_code == form_code,
            )
        ) is None
        row = ReportTemplate(
            company_id=company_id, form_code=form_code, name=name, file_name=file_name, is_default=is_first,
        )
        session.add(row)
        session.commit()
        return _to_row(row)


def rename_template(report_template_id: int, company_id: int, new_name: str) -> None:
    new_name = new_name.strip()
    if not new_name:
        raise ValueError("نام الزامی است.")
    with new_session() as session:
        row = session.get(ReportTemplate, report_template_id)
        if row is None or row.company_id != company_id:
            raise ValueError("گزارش یافت نشد.")
        duplicate = session.scalar(
            select(ReportTemplate).where(
                ReportTemplate.company_id == company_id,
                ReportTemplate.form_code == row.form_code,
                ReportTemplate.name == new_name,
                ReportTemplate.report_template_id != report_template_id,
            )
        )
        if duplicate is not None:
            raise ValueError("گزارشی با همین نام از قبل برایِ این فرم وجود دارد.")
        row.name = new_name
        session.commit()


def set_default(report_template_id: int, company_id: int) -> None:
    with new_session() as session:
        row = session.get(ReportTemplate, report_template_id)
        if row is None or row.company_id != company_id:
            raise ValueError("گزارش یافت نشد.")
        siblings = session.scalars(
            select(ReportTemplate).where(
                ReportTemplate.company_id == company_id, ReportTemplate.form_code == row.form_code,
            )
        ).all()
        for sibling in siblings:
            sibling.is_default = sibling.report_template_id == report_template_id
        session.commit()


def delete_template(report_template_id: int, company_id: int) -> None:
    with new_session() as session:
        row = session.get(ReportTemplate, report_template_id)
        if row is None or row.company_id != company_id:
            raise ValueError("گزارش یافت نشد.")
        file_path = _custom_dir(company_id) / row.file_name
        was_default = row.is_default
        form_code = row.form_code
        session.delete(row)
        session.commit()

    file_path.unlink(missing_ok=True)
    if was_default:
        with new_session() as session:
            remaining = session.scalars(
                select(ReportTemplate)
                .where(ReportTemplate.company_id == company_id, ReportTemplate.form_code == form_code)
                .order_by(ReportTemplate.report_template_id)
            ).all()
            if remaining:
                remaining[0].is_default = True
                session.commit()
