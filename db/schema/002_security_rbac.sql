-- پیچا | سیستم دسترسی: کاربران، نقش‌های درختی (با ارث‌بری از نقش والد)،
-- تخصیص نقش به‌صورت سراسری یا به‌تفکیک ماژول، و دسترسی منو / فرم / فیلد
-- PostgreSQL 13+ — چون Postgres جدول‌های Temporal بومی (مثل SQL Server) ندارد،
-- تاریخچه‌ی خودکار جدول‌های حساس با یک تابع تریگر عمومی (schema پایین) پیاده شده.
-- شناسه‌ها snake_case هستند (بدون کوتیشن، سازگار با نام‌گذاری بومی Postgres).
-- پیش‌نیاز: 001_core_i18n_and_tenancy.sql

CREATE SCHEMA sec;

-- ---------------------------------------------------------------------
-- کاربران
-- ---------------------------------------------------------------------
CREATE TABLE sec.users (
    user_id              INT           GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username             VARCHAR(50)   NOT NULL,
    password_hash        BYTEA         NOT NULL,
    password_salt        BYTEA         NOT NULL,
    full_name            VARCHAR(150)  NOT NULL,
    email                VARCHAR(200)  NULL,
    default_language_id  SMALLINT      NULL REFERENCES core.languages(language_id),
    is_super_admin       BOOLEAN       NOT NULL DEFAULT FALSE, -- دور زدن کامل دسترسی‌ها؛ فقط برای نگهداری سیستم
    is_active             BOOLEAN      NOT NULL DEFAULT TRUE,
    must_change_password BOOLEAN       NOT NULL DEFAULT TRUE,
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_users_username UNIQUE (username)
);

-- کاربر می‌تواند به چند شرکت دسترسی داشته باشد
CREATE TABLE sec.user_companies (
    user_id    INT NOT NULL REFERENCES sec.users(user_id),
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT pk_user_companies PRIMARY KEY (user_id, company_id)
);

-- ---------------------------------------------------------------------
-- ماژول‌ها / منوها / فرم‌ها / فیلدها  (کاتالوگ برنامه — پایه‌ی درخت دسترسی)
-- ---------------------------------------------------------------------
CREATE TABLE sec.modules (
    module_id  SMALLINT    GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code       VARCHAR(20) NOT NULL,   -- GL, INV, SALES, PURCH, TREASURY, COST, MFG, CRM ...
    icon_name  VARCHAR(50) NULL,
    sort_order SMALLINT    NOT NULL DEFAULT 0,
    is_active  BOOLEAN     NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_modules_code UNIQUE (code)
);

CREATE TABLE sec.menus (
    menu_id        INT         GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    module_id      SMALLINT    NOT NULL REFERENCES sec.modules(module_id),
    parent_menu_id INT         NULL REFERENCES sec.menus(menu_id),   -- درخت چندسطحی منو
    code           VARCHAR(50) NOT NULL,
    icon_name      VARCHAR(50) NULL,
    target_form_id INT         NULL,   -- NULL = گره پوشه‌ای بدون فرم مستقیم؛ FK بعد از ساخت forms اضافه می‌شود
    sort_order     SMALLINT    NOT NULL DEFAULT 0,
    is_active      BOOLEAN     NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_menus_code UNIQUE (code)
);

CREATE TABLE sec.forms (
    form_id   INT         GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    module_id SMALLINT    NOT NULL REFERENCES sec.modules(module_id),
    code      VARCHAR(50) NOT NULL,   -- شناسه‌ی فنی که در کد اپ به صفحه/فرم متصل می‌شود
    is_active BOOLEAN     NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_forms_code UNIQUE (code)
);

ALTER TABLE sec.menus
    ADD CONSTRAINT fk_menus_target_form FOREIGN KEY (target_form_id) REFERENCES sec.forms(form_id);

CREATE TABLE sec.form_fields (
    field_id        INT         GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    form_id         INT         NOT NULL REFERENCES sec.forms(form_id),
    code            VARCHAR(50) NOT NULL,   -- نام فیلد/ویجت داخل فرم
    is_system_field BOOLEAN     NOT NULL DEFAULT FALSE, -- فیلدهای حیاتی که نباید قابل مخفی‌سازی باشند
    sort_order      SMALLINT    NOT NULL DEFAULT 0,
    CONSTRAINT uq_form_fields UNIQUE (form_id, code)
);

-- ---------------------------------------------------------------------
-- اکشن‌های قابل‌کنترل روی هر فرم
-- ---------------------------------------------------------------------
CREATE TABLE sec.permission_actions (
    action_id SMALLINT    NOT NULL PRIMARY KEY,
    code      VARCHAR(20) NOT NULL UNIQUE
);
INSERT INTO sec.permission_actions (action_id, code) VALUES
    (1, 'VIEW'), (2, 'CREATE'), (3, 'EDIT'), (4, 'DELETE'),
    (5, 'PRINT'), (6, 'EXPORT'), (7, 'APPROVE');

-- ---------------------------------------------------------------------
-- نقش‌ها (هر نقش متعلق به یک شرکت مشخص است) — به‌صورت درختی، هر نقش
-- می‌تواند از یک نقش والد ارث‌بری کند و فقط تفاوت‌هایش را تعریف کند.
-- ---------------------------------------------------------------------
CREATE TABLE sec.roles (
    role_id        INT         GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id     INT         NOT NULL REFERENCES core.companies(company_id),
    parent_role_id INT         NULL REFERENCES sec.roles(role_id),   -- درخت نقش‌ها؛ باید هم‌شرکتِ خودِ نقش باشد (بررسی در لایه‌ی اپ/تریگر)
    code           VARCHAR(50) NOT NULL,
    is_system_role BOOLEAN     NOT NULL DEFAULT FALSE, -- نقش‌های داخلی (مثلاً «مدیر شرکت»)، غیرقابل‌حذف
    is_active      BOOLEAN     NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_roles UNIQUE (company_id, code),
    CONSTRAINT ck_roles_not_self_parent CHECK (parent_role_id IS NULL OR parent_role_id <> role_id)
);
CREATE INDEX ix_roles_parent_role_id ON sec.roles(parent_role_id);

-- ---------------------------------------------------------------------
-- تاریخچه‌ی خودکار (جایگزین Temporal Table): یک تابع تریگر عمومی که پیش از
-- هر UPDATE/DELETE روی جدول‌های "دارای valid_from"، نسخه‌ی قبلی ردیف را در
-- جدول <table>_history (با همان ستون‌ها + valid_to) کپی می‌کند و سپس
-- valid_from ردیف جاری را به‌روز می‌کند. یک‌بار نوشته شده، روی هر جدول قابل
-- استفاده‌ی مجدد است.
-- ---------------------------------------------------------------------
CREATE SCHEMA audit;

CREATE FUNCTION audit.track_row_history() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    history_table text := TG_TABLE_SCHEMA || '.' || TG_TABLE_NAME || '_history';
BEGIN
    IF TG_OP = 'UPDATE' THEN
        EXECUTE format('INSERT INTO %s SELECT ($1).*, now()', history_table) USING OLD;
        NEW.valid_from := now();
        RETURN NEW;
    ELSIF TG_OP = 'DELETE' THEN
        EXECUTE format('INSERT INTO %s SELECT ($1).*, now()', history_table) USING OLD;
        RETURN OLD;
    END IF;
    RETURN NULL;
END;
$$;

-- ---------------------------------------------------------------------
-- جدول‌های تخصیص/دسترسی — هرکدام + جدول *_history + تریگر تاریخچه
-- (چه کسی، چه زمانی، چه دسترسی‌ای را تغییر داده)
-- ---------------------------------------------------------------------

-- نقش عمومی سطح‌شرکت: روی همه‌ی ماژول‌هایی که خودِ نقش دسترسی برایشان تعریف کرده اعمال می‌شود
CREATE TABLE sec.user_roles (
    user_id    INT NOT NULL REFERENCES sec.users(user_id),
    role_id    INT NOT NULL REFERENCES sec.roles(role_id),
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    valid_from TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_user_roles PRIMARY KEY (user_id, role_id, company_id)
);
CREATE TABLE sec.user_roles_history (
    user_id    INT NOT NULL,
    role_id    INT NOT NULL,
    company_id INT NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_to   TIMESTAMPTZ NOT NULL
);
CREATE INDEX ix_user_roles_history ON sec.user_roles_history(user_id, role_id, company_id);
CREATE TRIGGER tr_user_roles_history BEFORE UPDATE OR DELETE ON sec.user_roles
    FOR EACH ROW EXECUTE FUNCTION audit.track_row_history();

-- نقش اختصاصیِ یک ماژول: همان کاربر می‌تواند در ماژول‌های مختلف نقش‌های متفاوتی
-- داشته باشد (مثلاً «مدیر فروش» در ماژول فروش + «فقط‌مشاهده» در ماژول انبار).
-- در محاسبه‌ی دسترسیِ فرم‌های ماژول M، این جدول با user_roles (سطح‌شرکت) جمع (اتحاد) می‌شود.
CREATE TABLE sec.user_module_roles (
    user_id    INT      NOT NULL REFERENCES sec.users(user_id),
    role_id    INT      NOT NULL REFERENCES sec.roles(role_id),
    company_id INT      NOT NULL REFERENCES core.companies(company_id),
    module_id  SMALLINT NOT NULL REFERENCES sec.modules(module_id),
    valid_from TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_user_module_roles PRIMARY KEY (user_id, role_id, company_id, module_id)
);
CREATE TABLE sec.user_module_roles_history (
    user_id    INT NOT NULL,
    role_id    INT NOT NULL,
    company_id INT NOT NULL,
    module_id  SMALLINT NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_to   TIMESTAMPTZ NOT NULL
);
CREATE INDEX ix_user_module_roles_history ON sec.user_module_roles_history(user_id, role_id, company_id, module_id);
CREATE TRIGGER tr_user_module_roles_history BEFORE UPDATE OR DELETE ON sec.user_module_roles
    FOR EACH ROW EXECUTE FUNCTION audit.track_row_history();

-- دسترسی نمایش هر منو به ازای نقش
CREATE TABLE sec.role_menu_permissions (
    role_id    INT NOT NULL REFERENCES sec.roles(role_id),
    menu_id    INT NOT NULL REFERENCES sec.menus(menu_id),
    can_view   BOOLEAN NOT NULL DEFAULT TRUE,
    valid_from TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_role_menu_permissions PRIMARY KEY (role_id, menu_id)
);
CREATE TABLE sec.role_menu_permissions_history (
    role_id    INT NOT NULL,
    menu_id    INT NOT NULL,
    can_view   BOOLEAN NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_to   TIMESTAMPTZ NOT NULL
);
CREATE INDEX ix_role_menu_permissions_history ON sec.role_menu_permissions_history(role_id, menu_id);
CREATE TRIGGER tr_role_menu_permissions_history BEFORE UPDATE OR DELETE ON sec.role_menu_permissions
    FOR EACH ROW EXECUTE FUNCTION audit.track_row_history();

-- دسترسی هر اکشن (مشاهده/ایجاد/ویرایش/حذف/چاپ/خروجی/تایید) روی هر فرم به ازای نقش
-- عدم‌وجود ردیف = عدم دسترسی (پیش‌فرض انکار = deny by default)
CREATE TABLE sec.role_form_permissions (
    role_id    INT NOT NULL REFERENCES sec.roles(role_id),
    form_id    INT NOT NULL REFERENCES sec.forms(form_id),
    action_id  SMALLINT NOT NULL REFERENCES sec.permission_actions(action_id),
    is_allowed BOOLEAN NOT NULL DEFAULT TRUE,
    valid_from TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_role_form_permissions PRIMARY KEY (role_id, form_id, action_id)
);
CREATE TABLE sec.role_form_permissions_history (
    role_id    INT NOT NULL,
    form_id    INT NOT NULL,
    action_id  SMALLINT NOT NULL,
    is_allowed BOOLEAN NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_to   TIMESTAMPTZ NOT NULL
);
CREATE INDEX ix_role_form_permissions_history ON sec.role_form_permissions_history(role_id, form_id, action_id);
CREATE TRIGGER tr_role_form_permissions_history BEFORE UPDATE OR DELETE ON sec.role_form_permissions
    FOR EACH ROW EXECUTE FUNCTION audit.track_row_history();

-- محدودسازی سطح فیلد؛ فقط برای «سخت‌گیرتر کردن» نسبت به سطح فرم استفاده می‌شود
-- (نمی‌تواند دسترسی بیشتر از سطح فرم بدهد). نبود ردیف = فیلد از دسترسی فرم پیروی می‌کند.
-- permission_level: 1 = Hidden , 2 = ReadOnly
CREATE TABLE sec.role_field_permissions (
    role_id          INT NOT NULL REFERENCES sec.roles(role_id),
    field_id         INT NOT NULL REFERENCES sec.form_fields(field_id),
    permission_level SMALLINT NOT NULL,
    valid_from       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_role_field_permissions PRIMARY KEY (role_id, field_id),
    CONSTRAINT ck_role_field_permissions_level CHECK (permission_level IN (1, 2))
);
CREATE TABLE sec.role_field_permissions_history (
    role_id          INT NOT NULL,
    field_id         INT NOT NULL,
    permission_level SMALLINT NOT NULL,
    valid_from       TIMESTAMPTZ NOT NULL,
    valid_to         TIMESTAMPTZ NOT NULL
);
CREATE INDEX ix_role_field_permissions_history ON sec.role_field_permissions_history(role_id, field_id);
CREATE TRIGGER tr_role_field_permissions_history BEFORE UPDATE OR DELETE ON sec.role_field_permissions
    FOR EACH ROW EXECUTE FUNCTION audit.track_row_history();
