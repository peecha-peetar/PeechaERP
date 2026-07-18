"""پایه‌ی مشترک مدل‌های SQLAlchemy + engine/session.

هر ماژول (core, sec, acc, wf, doc) دقیقاً به همان schema متناظرش در
db/schema/*.sql نگاشت می‌شود؛ نام جدول/ستون‌ها هم عیناً همان snake_case
دیتابیس است (بدون نگاشت دستی)، چون خودِ اسکیمای Postgres snake_case نوشته شده.

توجه: db/schema/*.sql مرجعِ ساختار دیتابیس است، نه این مدل‌ها — یعنی هرگز
از Base.metadata.create_all() برای ساخت دیتابیس استفاده نمی‌کنیم (چیزهایی
مثل تریگر تاریخچه و ستون‌های GENERATED در ORM قابل‌بیان نیستند). تغییرات
ساختاری بعدی با Alembic migration نوشته می‌شوند که مستقیماً همان اسکریپت‌های
SQL را اجرا می‌کند.
"""

import datetime

from sqlalchemy import DateTime, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from peecha.config import load_database_config


class Base(DeclarativeBase):
    # همه‌ی ستون‌های زمانی در اسکیما TIMESTAMPTZ هستند؛ با این نگاشت، نوشتن
    # `Mapped[datetime.datetime]` ساده در مدل‌ها کافی است و نیازی به تکرار
    # DateTime(timezone=True) در هر ستون نیست.
    type_annotation_map = {
        datetime.datetime: DateTime(timezone=True),
    }


_engine = None
_SessionFactory: sessionmaker[Session] | None = None


def get_engine():
    global _engine
    if _engine is None:
        config = load_database_config()
        _engine = create_engine(config.sqlalchemy_url, future=True)
    return _engine


def reset_engine() -> None:
    """بعد از ذخیره‌ی تنظیمات اتصال جدید از فرم UI صدا زده می‌شود تا
    engine/session بعدی با مقادیر تازه ساخته شوند، نه نسخه‌ی cache‌شده‌ی قبلی."""
    global _engine, _SessionFactory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionFactory = None


def get_session_factory() -> sessionmaker[Session]:
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=get_engine(), future=True)
    return _SessionFactory


def new_session() -> Session:
    return get_session_factory()()
