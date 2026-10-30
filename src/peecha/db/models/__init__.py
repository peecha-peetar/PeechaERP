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
    hr_talent,
    inventory,
    maintenance,
    opening,
    payroll,
    production,
    projects,
    quality,
    reporting,
    security,
    treasury,
    workflow,
)
