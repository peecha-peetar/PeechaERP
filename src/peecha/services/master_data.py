"""R276: حذفِ امنِ ردیف‌هایِ اطلاعاتِ پایه -- برایِ همهٔ فرم‌هایِ تعریف.

اگر ردیف در جایِ دیگری استفاده نشده باشد واقعاً حذف می‌شود؛ اگر استفاده شده (کلیدِ خارجی)
و ستونِ is_active دارد غیرفعال می‌شود تا سوابق خراب نشوند؛ وگرنه خطایِ قابلِ‌فهم می‌دهد."""

from __future__ import annotations

from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

from peecha.db.base import new_session

DELETED = "deleted"
DEACTIVATED = "deactivated"
IN_USE = "این ردیف در اسناد یا اطلاعاتِ دیگر استفاده شده و قابلِ حذف نیست."


def delete_or_deactivate(model, pk: int, company_id: int | None = None, children=()) -> str:
    """children: [(مدلِ فرزند، نامِ ستونِ کلیدِ خارجی)] -- ردیف‌هایِ وابستهٔ خودِ این رکورد که همراهش حذف می‌شوند."""
    with new_session() as session:
        row = session.get(model, pk)
        if row is None:
            raise ValueError("ردیف پیدا نشد.")
        if company_id is not None and getattr(row, "company_id", company_id) != company_id:
            raise ValueError("ردیف متعلق به این شرکت نیست.")
        try:
            for child, column in children:
                session.execute(delete(child).where(getattr(child, column) == pk))
            session.delete(row)
            session.flush()
        except IntegrityError:
            session.rollback()
            row = session.get(model, pk)
            if not hasattr(row, "is_active"):
                raise ValueError(IN_USE) from None
            row.is_active = False
            session.commit()
            return DEACTIVATED
        session.commit()
        return DELETED


def result_message(result: str, label: str) -> str:
    if result == DEACTIVATED:
        return f"«{label}» در سوابق استفاده شده؛ به‌جایِ حذف غیرفعال شد."
    return f"«{label}» حذف شد."
