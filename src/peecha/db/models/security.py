"""مدل‌های schema دسترسی: کاربران، نقش‌های درختی، منو/فرم/فیلد.

معادل db/schema/002_security_rbac.sql

جدول‌های *_history به‌صورت SQLAlchemy Core Table (نه کلاس ORM) تعریف شده‌اند
چون هیچ‌وقت مستقیم از طریق ORM درج/به‌روزرسانی نمی‌شوند — پرشدنشان کار تریگر
دیتابیس (audit.track_row_history) است؛ فقط برای گزارش‌گیری/حسابرسی خوانده می‌شوند.
"""

from __future__ import annotations

import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from peecha.db.base import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": "sec"}

    user_id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    password_hash: Mapped[bytes]
    password_salt: Mapped[bytes]
    full_name: Mapped[str] = mapped_column(String(150))
    email: Mapped[str | None] = mapped_column(String(200))
    default_language_id: Mapped[int | None] = mapped_column(ForeignKey("core.languages.language_id"))
    is_super_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime.datetime]


class UserCompany(Base):
    __tablename__ = "user_companies"
    __table_args__ = {"schema": "sec"}

    user_id: Mapped[int] = mapped_column(ForeignKey("sec.users.user_id"), primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"), primary_key=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)


class Module(Base):
    __tablename__ = "modules"
    __table_args__ = {"schema": "sec"}

    module_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    icon_name: Mapped[str | None] = mapped_column(String(50))
    sort_order: Mapped[int] = mapped_column(SmallInteger, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Menu(Base):
    __tablename__ = "menus"
    __table_args__ = {"schema": "sec"}

    menu_id: Mapped[int] = mapped_column(primary_key=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("sec.modules.module_id"))
    parent_menu_id: Mapped[int | None] = mapped_column(ForeignKey("sec.menus.menu_id"))
    code: Mapped[str] = mapped_column(String(50), unique=True)
    icon_name: Mapped[str | None] = mapped_column(String(50))
    target_form_id: Mapped[int | None] = mapped_column(ForeignKey("sec.forms.form_id"))
    sort_order: Mapped[int] = mapped_column(SmallInteger, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    children: Mapped[list[Menu]] = relationship(back_populates="parent")
    parent: Mapped[Menu | None] = relationship(back_populates="children", remote_side="Menu.menu_id")


class Form(Base):
    __tablename__ = "forms"
    __table_args__ = {"schema": "sec"}

    form_id: Mapped[int] = mapped_column(primary_key=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("sec.modules.module_id"))
    code: Mapped[str] = mapped_column(String(50), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class FormField(Base):
    __tablename__ = "form_fields"
    __table_args__ = (UniqueConstraint("form_id", "code"), {"schema": "sec"})

    field_id: Mapped[int] = mapped_column(primary_key=True)
    form_id: Mapped[int] = mapped_column(ForeignKey("sec.forms.form_id"))
    code: Mapped[str] = mapped_column(String(50))
    is_system_field: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(SmallInteger, default=0)


class PermissionAction(Base):
    __tablename__ = "permission_actions"
    __table_args__ = {"schema": "sec"}

    action_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)


class Role(Base):
    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint("company_id", "code"),
        CheckConstraint("parent_role_id IS NULL OR parent_role_id <> role_id", name="ck_roles_not_self_parent"),
        {"schema": "sec"},
    )

    role_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"))
    parent_role_id: Mapped[int | None] = mapped_column(ForeignKey("sec.roles.role_id"))
    code: Mapped[str] = mapped_column(String(50))
    is_system_role: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    parent: Mapped[Role | None] = relationship(remote_side="Role.role_id")


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = {"schema": "sec"}

    user_id: Mapped[int] = mapped_column(ForeignKey("sec.users.user_id"), primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("sec.roles.role_id"), primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"), primary_key=True)
    valid_from: Mapped[datetime.datetime]


class UserModuleRole(Base):
    __tablename__ = "user_module_roles"
    __table_args__ = {"schema": "sec"}

    user_id: Mapped[int] = mapped_column(ForeignKey("sec.users.user_id"), primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("sec.roles.role_id"), primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("core.companies.company_id"), primary_key=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("sec.modules.module_id"), primary_key=True)
    valid_from: Mapped[datetime.datetime]


class RoleMenuPermission(Base):
    __tablename__ = "role_menu_permissions"
    __table_args__ = {"schema": "sec"}

    role_id: Mapped[int] = mapped_column(ForeignKey("sec.roles.role_id"), primary_key=True)
    menu_id: Mapped[int] = mapped_column(ForeignKey("sec.menus.menu_id"), primary_key=True)
    can_view: Mapped[bool] = mapped_column(Boolean, default=True)
    valid_from: Mapped[datetime.datetime]


class RoleFormPermission(Base):
    __tablename__ = "role_form_permissions"
    __table_args__ = {"schema": "sec"}

    role_id: Mapped[int] = mapped_column(ForeignKey("sec.roles.role_id"), primary_key=True)
    form_id: Mapped[int] = mapped_column(ForeignKey("sec.forms.form_id"), primary_key=True)
    action_id: Mapped[int] = mapped_column(ForeignKey("sec.permission_actions.action_id"), primary_key=True)
    is_allowed: Mapped[bool] = mapped_column(Boolean, default=True)
    valid_from: Mapped[datetime.datetime]


class RoleFieldPermission(Base):
    __tablename__ = "role_field_permissions"
    __table_args__ = (
        CheckConstraint("permission_level IN (1, 2)", name="ck_role_field_permissions_level"),
        {"schema": "sec"},
    )

    role_id: Mapped[int] = mapped_column(ForeignKey("sec.roles.role_id"), primary_key=True)
    field_id: Mapped[int] = mapped_column(ForeignKey("sec.form_fields.field_id"), primary_key=True)
    permission_level: Mapped[int] = mapped_column(SmallInteger)
    valid_from: Mapped[datetime.datetime]


# --- جدول‌های تاریخچه (Core Table؛ فقط خواندنی از دید اپلیکیشن) ---------

user_roles_history = Table(
    "user_roles_history", Base.metadata,
    Column("user_id", Integer), Column("role_id", Integer), Column("company_id", Integer),
    Column("valid_from", DateTime(timezone=True)), Column("valid_to", DateTime(timezone=True)),
    schema="sec",
)

user_module_roles_history = Table(
    "user_module_roles_history", Base.metadata,
    Column("user_id", Integer), Column("role_id", Integer), Column("company_id", Integer),
    Column("module_id", SmallInteger),
    Column("valid_from", DateTime(timezone=True)), Column("valid_to", DateTime(timezone=True)),
    schema="sec",
)

role_menu_permissions_history = Table(
    "role_menu_permissions_history", Base.metadata,
    Column("role_id", Integer), Column("menu_id", Integer), Column("can_view", Boolean),
    Column("valid_from", DateTime(timezone=True)), Column("valid_to", DateTime(timezone=True)),
    schema="sec",
)

role_form_permissions_history = Table(
    "role_form_permissions_history", Base.metadata,
    Column("role_id", Integer), Column("form_id", Integer), Column("action_id", SmallInteger),
    Column("is_allowed", Boolean),
    Column("valid_from", DateTime(timezone=True)), Column("valid_to", DateTime(timezone=True)),
    schema="sec",
)

role_field_permissions_history = Table(
    "role_field_permissions_history", Base.metadata,
    Column("role_id", Integer), Column("field_id", Integer), Column("permission_level", SmallInteger),
    Column("valid_from", DateTime(timezone=True)), Column("valid_to", DateTime(timezone=True)),
    schema="sec",
)
