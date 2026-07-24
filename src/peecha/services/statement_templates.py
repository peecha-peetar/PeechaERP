"""سرویسِ الگوهایِ گزارشِ سفارشی (طراحِ گزارش، فازِ ۲) — CRUدِ ساده‌یِ
الگو/ردیف + جایگزینیِ کاملِ اجزایِ هر ردیف (چه حسابی چه فرمولی).

هیچ محاسبه‌ای این‌جا انجام نمی‌شود — فقط تعریف/نگه‌داریِ ساختار. محاسبه
(`compute_custom_statement`) در reports.py است، چون آن ماژول از قبل
`compute_account_balances` را دارد."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import delete, select

from peecha.db.base import new_session
from peecha.db.models.accounting import (
    StatementRow,
    StatementRowAccount,
    StatementRowRef,
    StatementTemplate,
)


@dataclass
class StatementTemplateRow:
    template_id: int
    name: str
    statement_type: str


@dataclass
class StatementRowInfo:
    row_id: int
    row_order: int
    label: str
    row_type: str
    indent_level: int
    is_bold: bool
    account_refs: list[tuple[int, int]] = field(default_factory=list)  # (account_id, sign)
    formula_refs: list[tuple[int, int]] = field(default_factory=list)  # (ref_row_id, sign)


def list_templates(company_id: int) -> list[StatementTemplateRow]:
    with new_session() as session:
        rows = session.scalars(
            select(StatementTemplate)
            .where(StatementTemplate.company_id == company_id)
            .order_by(StatementTemplate.display_order, StatementTemplate.template_id)
        ).all()
        return [StatementTemplateRow(r.template_id, r.name, r.statement_type) for r in rows]


def create_template(company_id: int, name: str, statement_type: str) -> int:
    with new_session() as session:
        max_order = session.scalar(
            select(StatementTemplate.display_order)
            .where(StatementTemplate.company_id == company_id)
            .order_by(StatementTemplate.display_order.desc())
        )
        template = StatementTemplate(
            company_id=company_id,
            name=name,
            statement_type=statement_type,
            display_order=(max_order or 0) + 1,
        )
        session.add(template)
        session.commit()
        return template.template_id


def rename_template(template_id: int, name: str) -> None:
    with new_session() as session:
        template = session.get(StatementTemplate, template_id)
        if template is None:
            raise ValueError("الگو پیدا نشد.")
        template.name = name
        session.commit()


def delete_template(template_id: int) -> None:
    with new_session() as session:
        row_ids = list(
            session.scalars(select(StatementRow.row_id).where(StatementRow.template_id == template_id)).all()
        )
        if row_ids:
            session.execute(delete(StatementRowRef).where(StatementRowRef.row_id.in_(row_ids)))
            session.execute(delete(StatementRowRef).where(StatementRowRef.ref_row_id.in_(row_ids)))
            session.execute(delete(StatementRowAccount).where(StatementRowAccount.row_id.in_(row_ids)))
            session.execute(delete(StatementRow).where(StatementRow.row_id.in_(row_ids)))
        session.execute(delete(StatementTemplate).where(StatementTemplate.template_id == template_id))
        session.commit()


def list_rows(template_id: int) -> list[StatementRowInfo]:
    with new_session() as session:
        rows = session.scalars(
            select(StatementRow).where(StatementRow.template_id == template_id).order_by(StatementRow.row_order)
        ).all()
        row_ids = [r.row_id for r in rows]

        account_refs_by_row: dict[int, list[tuple[int, int]]] = {}
        formula_refs_by_row: dict[int, list[tuple[int, int]]] = {}
        if row_ids:
            for row_id, account_id, sign in session.execute(
                select(StatementRowAccount.row_id, StatementRowAccount.account_id, StatementRowAccount.sign).where(
                    StatementRowAccount.row_id.in_(row_ids)
                )
            ).all():
                account_refs_by_row.setdefault(row_id, []).append((account_id, sign))
            for row_id, ref_row_id, sign in session.execute(
                select(StatementRowRef.row_id, StatementRowRef.ref_row_id, StatementRowRef.sign).where(
                    StatementRowRef.row_id.in_(row_ids)
                )
            ).all():
                formula_refs_by_row.setdefault(row_id, []).append((ref_row_id, sign))

        return [
            StatementRowInfo(
                row_id=r.row_id,
                row_order=r.row_order,
                label=r.label,
                row_type=r.row_type,
                indent_level=r.indent_level,
                is_bold=r.is_bold,
                account_refs=account_refs_by_row.get(r.row_id, []),
                formula_refs=formula_refs_by_row.get(r.row_id, []),
            )
            for r in rows
        ]


def add_row(
    template_id: int, label: str, row_type: str, *, indent_level: int = 0, is_bold: bool = False
) -> int:
    with new_session() as session:
        max_order = session.scalar(
            select(StatementRow.row_order)
            .where(StatementRow.template_id == template_id)
            .order_by(StatementRow.row_order.desc())
        )
        row = StatementRow(
            template_id=template_id,
            row_order=(max_order or 0) + 1,
            label=label,
            row_type=row_type,
            indent_level=indent_level,
            is_bold=is_bold,
        )
        session.add(row)
        session.commit()
        return row.row_id


def update_row(
    row_id: int,
    *,
    label: str | None = None,
    row_type: str | None = None,
    indent_level: int | None = None,
    is_bold: bool | None = None,
) -> None:
    with new_session() as session:
        row = session.get(StatementRow, row_id)
        if row is None:
            raise ValueError("ردیف پیدا نشد.")
        if label is not None:
            row.label = label
        if row_type is not None:
            row.row_type = row_type
        if indent_level is not None:
            row.indent_level = indent_level
        if is_bold is not None:
            row.is_bold = is_bold
        session.commit()


def delete_row(row_id: int) -> None:
    with new_session() as session:
        session.execute(delete(StatementRowRef).where(StatementRowRef.row_id == row_id))
        session.execute(delete(StatementRowRef).where(StatementRowRef.ref_row_id == row_id))
        session.execute(delete(StatementRowAccount).where(StatementRowAccount.row_id == row_id))
        session.execute(delete(StatementRow).where(StatementRow.row_id == row_id))
        session.commit()


def reorder_rows(template_id: int, ordered_row_ids: list[int]) -> None:
    with new_session() as session:
        rows = {
            r.row_id: r
            for r in session.scalars(select(StatementRow).where(StatementRow.template_id == template_id)).all()
        }
        for order, row_id in enumerate(ordered_row_ids, start=1):
            if row_id in rows:
                rows[row_id].row_order = order
        session.commit()


def set_row_accounts(row_id: int, refs: list[tuple[int, int]]) -> None:
    """جایگزینیِ کاملِ اجزایِ حسابیِ یک ردیف. `refs` = [(account_id, sign), ...]."""
    with new_session() as session:
        session.execute(delete(StatementRowAccount).where(StatementRowAccount.row_id == row_id))
        for account_id, sign in refs:
            session.add(StatementRowAccount(row_id=row_id, account_id=account_id, sign=sign))
        session.commit()


def set_row_formula_refs(row_id: int, refs: list[tuple[int, int]]) -> None:
    """جایگزینیِ کاملِ اجزایِ فرمولیِ یک ردیف. `refs` = [(ref_row_id, sign), ...]."""
    with new_session() as session:
        session.execute(delete(StatementRowRef).where(StatementRowRef.row_id == row_id))
        for ref_row_id, sign in refs:
            if ref_row_id == row_id:
                raise ValueError("یک ردیف نمی‌تواند به خودش ارجاع بدهد.")
            session.add(StatementRowRef(row_id=row_id, ref_row_id=ref_row_id, sign=sign))
        session.commit()
