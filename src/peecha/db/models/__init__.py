"""همه‌ی ماژول‌های مدل را import می‌کند تا Base.metadata کامل شود
(لازم برای Alembic و هر جای دیگری که به کل مجموعه‌ی جدول‌ها نیاز دارد)."""

from peecha.db.models import (  # noqa: F401
    accounting,
    audit,
    commercial,
    core,
    documents,
    hr,
    inventory,
    payroll,
    reporting,
    security,
    treasury,
    workflow,
)
