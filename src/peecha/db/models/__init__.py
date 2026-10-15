"""همهٔ ماژول‌های مدل را import می‌کند تا Base.metadata کامل شود
(لازم برای Alembic و هر جای دیگری که به کل مجموعهٔ جدول‌ها نیاز دارد)."""

from peecha.db.models import (  # noqa: F401
    accounting,
    audit,
    budgeting,
    commercial,
    core,
    crm,
    documents,
    fixed_assets,
    hr,
    inventory,
    maintenance,
    opening,
    payroll,
    production,
    quality,
    reporting,
    security,
    treasury,
    workflow,
)
