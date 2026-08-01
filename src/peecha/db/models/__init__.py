"""همه‌ی ماژول‌های مدل را import می‌کند تا Base.metadata کامل شود
(لازم برای Alembic و هر جای دیگری که به کل مجموعه‌ی جدول‌ها نیاز دارد)."""

from peecha.db.models import accounting, audit, core, documents, security, treasury, workflow  # noqa: F401
