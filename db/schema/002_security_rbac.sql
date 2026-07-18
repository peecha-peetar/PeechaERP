-- پیچا | سیستم دسترسی: کاربران، نقش‌های درختی (با ارث‌بری از نقش والد)،
-- تخصیص نقش به‌صورت سراسری یا به‌تفکیک ماژول، و دسترسی منو / فرم / فیلد
-- PostgreSQL 13+ — چون Postgres جدول‌های Temporal بومی (مثل SQL Server) ندارد،
-- تاریخچه‌ی خودکار جدول‌های حساس با یک تابع تریگر عمومی (schema پایین) پیاده شده.
-- پیش‌نیاز: 001_core_i18n_and_tenancy.sql

CREATE SCHEMA sec;

-- ---------------------------------------------------------------------
-- کاربران
-- ---------------------------------------------------------------------
CREATE TABLE sec.Users (
    UserID             INT           GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    Username           VARCHAR(50)   NOT NULL,
    PasswordHash       BYTEA         NOT NULL,
    PasswordSalt       BYTEA         NOT NULL,
    FullName           VARCHAR(150)  NOT NULL,
    Email              VARCHAR(200)  NULL,
    DefaultLanguageID  SMALLINT      NULL REFERENCES core.Languages(LanguageID),
    IsSuperAdmin       BOOLEAN       NOT NULL DEFAULT FALSE, -- دور زدن کامل دسترسی‌ها؛ فقط برای نگهداری سیستم
    IsActive           BOOLEAN       NOT NULL DEFAULT TRUE,
    MustChangePassword BOOLEAN       NOT NULL DEFAULT TRUE,
    CreatedAt          TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CONSTRAINT UQ_Users_Username UNIQUE (Username)
);

-- کاربر می‌تواند به چند شرکت دسترسی داشته باشد
CREATE TABLE sec.UserCompanies (
    UserID    INT NOT NULL REFERENCES sec.Users(UserID),
    CompanyID INT NOT NULL REFERENCES core.Companies(CompanyID),
    IsDefault BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT PK_UserCompanies PRIMARY KEY (UserID, CompanyID)
);

-- ---------------------------------------------------------------------
-- ماژول‌ها / منوها / فرم‌ها / فیلدها  (کاتالوگ برنامه — پایه‌ی درخت دسترسی)
-- ---------------------------------------------------------------------
CREATE TABLE sec.Modules (
    ModuleID  SMALLINT    GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    Code      VARCHAR(20) NOT NULL,   -- GL, INV, SALES, PURCH, TREASURY, COST, MFG, CRM ...
    IconName  VARCHAR(50) NULL,
    SortOrder SMALLINT    NOT NULL DEFAULT 0,
    IsActive  BOOLEAN     NOT NULL DEFAULT TRUE,
    CONSTRAINT UQ_Modules_Code UNIQUE (Code)
);

CREATE TABLE sec.Menus (
    MenuID       INT         GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ModuleID     SMALLINT    NOT NULL REFERENCES sec.Modules(ModuleID),
    ParentMenuID INT         NULL REFERENCES sec.Menus(MenuID),   -- درخت چندسطحی منو
    Code         VARCHAR(50) NOT NULL,
    IconName     VARCHAR(50) NULL,
    TargetFormID INT         NULL,   -- NULL = گره پوشه‌ای بدون فرم مستقیم؛ FK بعد از ساخت Forms اضافه می‌شود
    SortOrder    SMALLINT    NOT NULL DEFAULT 0,
    IsActive     BOOLEAN     NOT NULL DEFAULT TRUE,
    CONSTRAINT UQ_Menus_Code UNIQUE (Code)
);

CREATE TABLE sec.Forms (
    FormID   INT         GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ModuleID SMALLINT    NOT NULL REFERENCES sec.Modules(ModuleID),
    Code     VARCHAR(50) NOT NULL,   -- شناسه‌ی فنی که در کد اپ به صفحه/فرم متصل می‌شود
    IsActive BOOLEAN     NOT NULL DEFAULT TRUE,
    CONSTRAINT UQ_Forms_Code UNIQUE (Code)
);

ALTER TABLE sec.Menus
    ADD CONSTRAINT FK_Menus_TargetForm FOREIGN KEY (TargetFormID) REFERENCES sec.Forms(FormID);

CREATE TABLE sec.FormFields (
    FieldID       INT         GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    FormID        INT         NOT NULL REFERENCES sec.Forms(FormID),
    Code          VARCHAR(50) NOT NULL,   -- نام فیلد/ویجت داخل فرم
    IsSystemField BOOLEAN     NOT NULL DEFAULT FALSE, -- فیلدهای حیاتی که نباید قابل مخفی‌سازی باشند
    SortOrder     SMALLINT    NOT NULL DEFAULT 0,
    CONSTRAINT UQ_FormFields UNIQUE (FormID, Code)
);

-- ---------------------------------------------------------------------
-- اکشن‌های قابل‌کنترل روی هر فرم
-- ---------------------------------------------------------------------
CREATE TABLE sec.PermissionActions (
    ActionID SMALLINT    NOT NULL PRIMARY KEY,
    Code     VARCHAR(20) NOT NULL UNIQUE
);
INSERT INTO sec.PermissionActions (ActionID, Code) VALUES
    (1, 'VIEW'), (2, 'CREATE'), (3, 'EDIT'), (4, 'DELETE'),
    (5, 'PRINT'), (6, 'EXPORT'), (7, 'APPROVE');

-- ---------------------------------------------------------------------
-- نقش‌ها (هر نقش متعلق به یک شرکت مشخص است) — به‌صورت درختی، هر نقش
-- می‌تواند از یک نقش والد ارث‌بری کند و فقط تفاوت‌هایش را تعریف کند.
-- ---------------------------------------------------------------------
CREATE TABLE sec.Roles (
    RoleID       INT         GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    CompanyID    INT         NOT NULL REFERENCES core.Companies(CompanyID),
    ParentRoleID INT         NULL REFERENCES sec.Roles(RoleID),   -- درخت نقش‌ها؛ باید هم‌شرکتِ خودِ نقش باشد (بررسی در لایه‌ی اپ/تریگر)
    Code         VARCHAR(50) NOT NULL,
    IsSystemRole BOOLEAN     NOT NULL DEFAULT FALSE, -- نقش‌های داخلی (مثلاً «مدیر شرکت»)، غیرقابل‌حذف
    IsActive     BOOLEAN     NOT NULL DEFAULT TRUE,
    CONSTRAINT UQ_Roles UNIQUE (CompanyID, Code),
    CONSTRAINT CK_Roles_NotSelfParent CHECK (ParentRoleID IS NULL OR ParentRoleID <> RoleID)
);
CREATE INDEX IX_Roles_ParentRoleID ON sec.Roles(ParentRoleID);

-- ---------------------------------------------------------------------
-- تاریخچه‌ی خودکار (جایگزین Temporal Table): یک تابع تریگر عمومی که پیش از
-- هر UPDATE/DELETE روی جدول‌های "دارای ValidFrom"، نسخه‌ی قبلی ردیف را در
-- جدول <table>_history (با همان ستون‌ها + ValidTo) کپی می‌کند و سپس
-- ValidFrom ردیف جاری را به‌روز می‌کند. یک‌بار نوشته شده، روی هر جدول قابل
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
        NEW.ValidFrom := now();
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
CREATE TABLE sec.UserRoles (
    UserID    INT NOT NULL REFERENCES sec.Users(UserID),
    RoleID    INT NOT NULL REFERENCES sec.Roles(RoleID),
    CompanyID INT NOT NULL REFERENCES core.Companies(CompanyID),
    ValidFrom TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT PK_UserRoles PRIMARY KEY (UserID, RoleID, CompanyID)
);
CREATE TABLE sec.UserRoles_History (
    UserID    INT NOT NULL,
    RoleID    INT NOT NULL,
    CompanyID INT NOT NULL,
    ValidFrom TIMESTAMPTZ NOT NULL,
    ValidTo   TIMESTAMPTZ NOT NULL
);
CREATE INDEX IX_UserRoles_History ON sec.UserRoles_History(UserID, RoleID, CompanyID);
CREATE TRIGGER TR_UserRoles_History BEFORE UPDATE OR DELETE ON sec.UserRoles
    FOR EACH ROW EXECUTE FUNCTION audit.track_row_history();

-- نقش اختصاصیِ یک ماژول: همان کاربر می‌تواند در ماژول‌های مختلف نقش‌های متفاوتی
-- داشته باشد (مثلاً «مدیر فروش» در ماژول فروش + «فقط‌مشاهده» در ماژول انبار).
-- در محاسبه‌ی دسترسیِ فرم‌های ماژول M، این جدول با UserRoles (سطح‌شرکت) جمع (اتحاد) می‌شود.
CREATE TABLE sec.UserModuleRoles (
    UserID    INT      NOT NULL REFERENCES sec.Users(UserID),
    RoleID    INT      NOT NULL REFERENCES sec.Roles(RoleID),
    CompanyID INT      NOT NULL REFERENCES core.Companies(CompanyID),
    ModuleID  SMALLINT NOT NULL REFERENCES sec.Modules(ModuleID),
    ValidFrom TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT PK_UserModuleRoles PRIMARY KEY (UserID, RoleID, CompanyID, ModuleID)
);
CREATE TABLE sec.UserModuleRoles_History (
    UserID    INT NOT NULL,
    RoleID    INT NOT NULL,
    CompanyID INT NOT NULL,
    ModuleID  SMALLINT NOT NULL,
    ValidFrom TIMESTAMPTZ NOT NULL,
    ValidTo   TIMESTAMPTZ NOT NULL
);
CREATE INDEX IX_UserModuleRoles_History ON sec.UserModuleRoles_History(UserID, RoleID, CompanyID, ModuleID);
CREATE TRIGGER TR_UserModuleRoles_History BEFORE UPDATE OR DELETE ON sec.UserModuleRoles
    FOR EACH ROW EXECUTE FUNCTION audit.track_row_history();

-- دسترسی نمایش هر منو به ازای نقش
CREATE TABLE sec.RoleMenuPermissions (
    RoleID    INT NOT NULL REFERENCES sec.Roles(RoleID),
    MenuID    INT NOT NULL REFERENCES sec.Menus(MenuID),
    CanView   BOOLEAN NOT NULL DEFAULT TRUE,
    ValidFrom TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT PK_RoleMenuPermissions PRIMARY KEY (RoleID, MenuID)
);
CREATE TABLE sec.RoleMenuPermissions_History (
    RoleID    INT NOT NULL,
    MenuID    INT NOT NULL,
    CanView   BOOLEAN NOT NULL,
    ValidFrom TIMESTAMPTZ NOT NULL,
    ValidTo   TIMESTAMPTZ NOT NULL
);
CREATE INDEX IX_RoleMenuPermissions_History ON sec.RoleMenuPermissions_History(RoleID, MenuID);
CREATE TRIGGER TR_RoleMenuPermissions_History BEFORE UPDATE OR DELETE ON sec.RoleMenuPermissions
    FOR EACH ROW EXECUTE FUNCTION audit.track_row_history();

-- دسترسی هر اکشن (مشاهده/ایجاد/ویرایش/حذف/چاپ/خروجی/تایید) روی هر فرم به ازای نقش
-- عدم‌وجود ردیف = عدم دسترسی (پیش‌فرض انکار = deny by default)
CREATE TABLE sec.RoleFormPermissions (
    RoleID    INT NOT NULL REFERENCES sec.Roles(RoleID),
    FormID    INT NOT NULL REFERENCES sec.Forms(FormID),
    ActionID  SMALLINT NOT NULL REFERENCES sec.PermissionActions(ActionID),
    IsAllowed BOOLEAN NOT NULL DEFAULT TRUE,
    ValidFrom TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT PK_RoleFormPermissions PRIMARY KEY (RoleID, FormID, ActionID)
);
CREATE TABLE sec.RoleFormPermissions_History (
    RoleID    INT NOT NULL,
    FormID    INT NOT NULL,
    ActionID  SMALLINT NOT NULL,
    IsAllowed BOOLEAN NOT NULL,
    ValidFrom TIMESTAMPTZ NOT NULL,
    ValidTo   TIMESTAMPTZ NOT NULL
);
CREATE INDEX IX_RoleFormPermissions_History ON sec.RoleFormPermissions_History(RoleID, FormID, ActionID);
CREATE TRIGGER TR_RoleFormPermissions_History BEFORE UPDATE OR DELETE ON sec.RoleFormPermissions
    FOR EACH ROW EXECUTE FUNCTION audit.track_row_history();

-- محدودسازی سطح فیلد؛ فقط برای «سخت‌گیرتر کردن» نسبت به سطح فرم استفاده می‌شود
-- (نمی‌تواند دسترسی بیشتر از سطح فرم بدهد). نبود ردیف = فیلد از دسترسی فرم پیروی می‌کند.
-- PermissionLevel: 1 = Hidden , 2 = ReadOnly
CREATE TABLE sec.RoleFieldPermissions (
    RoleID          INT NOT NULL REFERENCES sec.Roles(RoleID),
    FieldID         INT NOT NULL REFERENCES sec.FormFields(FieldID),
    PermissionLevel SMALLINT NOT NULL,
    ValidFrom       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT PK_RoleFieldPermissions PRIMARY KEY (RoleID, FieldID),
    CONSTRAINT CK_RoleFieldPermissions_Level CHECK (PermissionLevel IN (1, 2))
);
CREATE TABLE sec.RoleFieldPermissions_History (
    RoleID          INT NOT NULL,
    FieldID         INT NOT NULL,
    PermissionLevel SMALLINT NOT NULL,
    ValidFrom       TIMESTAMPTZ NOT NULL,
    ValidTo         TIMESTAMPTZ NOT NULL
);
CREATE INDEX IX_RoleFieldPermissions_History ON sec.RoleFieldPermissions_History(RoleID, FieldID);
CREATE TRIGGER TR_RoleFieldPermissions_History BEFORE UPDATE OR DELETE ON sec.RoleFieldPermissions
    FOR EACH ROW EXECUTE FUNCTION audit.track_row_history();
