-- پیچا | سیستم دسترسی: کاربران، نقش‌های درختی (با ارث‌بری از نقش والد)،
-- تخصیص نقش به‌صورت سراسری یا به‌تفکیک ماژول، و دسترسی منو / فرم / فیلد
-- سازگار با SQL Server 2016 — از System-Versioned Temporal Tables برای
-- تاریخچه‌ی خودکار تغییرات دسترسی استفاده می‌شود (نیاز حسابرسی/کنترل داخلی)
-- پیش‌نیاز: 001_core_i18n_and_tenancy.sql

CREATE SCHEMA sec;
GO

-- ---------------------------------------------------------------------
-- کاربران
-- ---------------------------------------------------------------------
CREATE TABLE sec.Users (
    UserID             INT           NOT NULL IDENTITY(1,1) PRIMARY KEY,
    Username           VARCHAR(50)   NOT NULL,
    PasswordHash       VARBINARY(64) NOT NULL,
    PasswordSalt       VARBINARY(32) NOT NULL,
    FullName           NVARCHAR(150) NOT NULL,
    Email              VARCHAR(200)  NULL,
    DefaultLanguageID  TINYINT       NULL REFERENCES core.Languages(LanguageID),
    IsSuperAdmin       BIT           NOT NULL CONSTRAINT DF_Users_IsSuperAdmin DEFAULT (0), -- دور زدن کامل دسترسی‌ها؛ فقط برای نگهداری سیستم
    IsActive           BIT           NOT NULL CONSTRAINT DF_Users_IsActive DEFAULT (1),
    MustChangePassword BIT           NOT NULL CONSTRAINT DF_Users_MustChangePw DEFAULT (1),
    CreatedAt          DATETIME2(0)  NOT NULL CONSTRAINT DF_Users_CreatedAt DEFAULT (SYSUTCDATETIME()),
    CONSTRAINT UQ_Users_Username UNIQUE (Username)
);
GO

-- کاربر می‌تواند به چند شرکت دسترسی داشته باشد
CREATE TABLE sec.UserCompanies (
    UserID    INT NOT NULL REFERENCES sec.Users(UserID),
    CompanyID INT NOT NULL REFERENCES core.Companies(CompanyID),
    IsDefault BIT NOT NULL CONSTRAINT DF_UserCompanies_IsDefault DEFAULT (0),
    CONSTRAINT PK_UserCompanies PRIMARY KEY (UserID, CompanyID)
);
GO

-- ---------------------------------------------------------------------
-- ماژول‌ها / منوها / فرم‌ها / فیلدها  (کاتالوگ برنامه — پایه‌ی درخت دسترسی)
-- ---------------------------------------------------------------------
CREATE TABLE sec.Modules (
    ModuleID  SMALLINT    NOT NULL IDENTITY(1,1) PRIMARY KEY,
    Code      VARCHAR(20) NOT NULL,   -- GL, INV, SALES, PURCH, TREASURY, COST, MFG, CRM ...
    IconName  VARCHAR(50) NULL,
    SortOrder SMALLINT    NOT NULL CONSTRAINT DF_Modules_SortOrder DEFAULT (0),
    IsActive  BIT         NOT NULL CONSTRAINT DF_Modules_IsActive DEFAULT (1),
    CONSTRAINT UQ_Modules_Code UNIQUE (Code)
);
GO

CREATE TABLE sec.Menus (
    MenuID       INT         NOT NULL IDENTITY(1,1) PRIMARY KEY,
    ModuleID     SMALLINT    NOT NULL REFERENCES sec.Modules(ModuleID),
    ParentMenuID INT         NULL REFERENCES sec.Menus(MenuID),   -- درخت چندسطحی منو
    Code         VARCHAR(50) NOT NULL,
    IconName     VARCHAR(50) NULL,
    TargetFormID INT         NULL,   -- NULL = گره پوشه‌ای بدون فرم مستقیم؛ FK بعد از ساخت Forms اضافه می‌شود
    SortOrder    SMALLINT    NOT NULL CONSTRAINT DF_Menus_SortOrder DEFAULT (0),
    IsActive     BIT         NOT NULL CONSTRAINT DF_Menus_IsActive DEFAULT (1),
    CONSTRAINT UQ_Menus_Code UNIQUE (Code)
);
GO

CREATE TABLE sec.Forms (
    FormID   INT         NOT NULL IDENTITY(1,1) PRIMARY KEY,
    ModuleID SMALLINT    NOT NULL REFERENCES sec.Modules(ModuleID),
    Code     VARCHAR(50) NOT NULL,   -- شناسه‌ی فنی که در کد اپ به صفحه/فرم متصل می‌شود
    IsActive BIT         NOT NULL CONSTRAINT DF_Forms_IsActive DEFAULT (1),
    CONSTRAINT UQ_Forms_Code UNIQUE (Code)
);
GO

ALTER TABLE sec.Menus
    ADD CONSTRAINT FK_Menus_TargetForm FOREIGN KEY (TargetFormID) REFERENCES sec.Forms(FormID);
GO

CREATE TABLE sec.FormFields (
    FieldID       INT         NOT NULL IDENTITY(1,1) PRIMARY KEY,
    FormID        INT         NOT NULL REFERENCES sec.Forms(FormID),
    Code          VARCHAR(50) NOT NULL,   -- نام فیلد/ویجت داخل فرم
    IsSystemField BIT         NOT NULL CONSTRAINT DF_FormFields_IsSystem DEFAULT (0), -- فیلدهای حیاتی که نباید قابل مخفی‌سازی باشند
    SortOrder     SMALLINT    NOT NULL CONSTRAINT DF_FormFields_SortOrder DEFAULT (0),
    CONSTRAINT UQ_FormFields UNIQUE (FormID, Code)
);
GO

-- ---------------------------------------------------------------------
-- اکشن‌های قابل‌کنترل روی هر فرم
-- ---------------------------------------------------------------------
CREATE TABLE sec.PermissionActions (
    ActionID TINYINT     NOT NULL PRIMARY KEY,
    Code     VARCHAR(20) NOT NULL UNIQUE
);
GO
INSERT INTO sec.PermissionActions (ActionID, Code) VALUES
    (1, 'VIEW'), (2, 'CREATE'), (3, 'EDIT'), (4, 'DELETE'),
    (5, 'PRINT'), (6, 'EXPORT'), (7, 'APPROVE');
GO

-- ---------------------------------------------------------------------
-- نقش‌ها (هر نقش متعلق به یک شرکت مشخص است) — به‌صورت درختی، هر نقش
-- می‌تواند از یک نقش والد ارث‌بری کند و فقط تفاوت‌هایش را تعریف کند.
-- ---------------------------------------------------------------------
CREATE TABLE sec.Roles (
    RoleID       INT         NOT NULL IDENTITY(1,1) PRIMARY KEY,
    CompanyID    INT         NOT NULL REFERENCES core.Companies(CompanyID),
    ParentRoleID INT         NULL REFERENCES sec.Roles(RoleID),   -- درخت نقش‌ها؛ باید هم‌شرکتِ خودِ نقش باشد (بررسی در لایه‌ی اپ/تریگر)
    Code         VARCHAR(50) NOT NULL,
    IsSystemRole BIT         NOT NULL CONSTRAINT DF_Roles_IsSystem DEFAULT (0), -- نقش‌های داخلی (مثلاً «مدیر شرکت»)، غیرقابل‌حذف
    IsActive     BIT         NOT NULL CONSTRAINT DF_Roles_IsActive DEFAULT (1),
    CONSTRAINT UQ_Roles UNIQUE (CompanyID, Code),
    CONSTRAINT CK_Roles_NotSelfParent CHECK (ParentRoleID IS NULL OR ParentRoleID <> RoleID)
);
GO
CREATE INDEX IX_Roles_ParentRoleID ON sec.Roles(ParentRoleID);
GO

-- ---------------------------------------------------------------------
-- جدول‌های تخصیص/دسترسی — با Temporal Table برای تاریخچه‌ی خودکار
-- (چه کسی، چه زمانی، چه دسترسی‌ای را تغییر داده)
-- ---------------------------------------------------------------------

-- نقش عمومی سطح‌شرکت: روی همه‌ی ماژول‌هایی که خودِ نقش دسترسی برایشان تعریف کرده اعمال می‌شود
CREATE TABLE sec.UserRoles (
    UserID       INT      NOT NULL REFERENCES sec.Users(UserID),
    RoleID       INT      NOT NULL REFERENCES sec.Roles(RoleID),
    CompanyID    INT      NOT NULL REFERENCES core.Companies(CompanyID),
    SysStartTime DATETIME2 GENERATED ALWAYS AS ROW START NOT NULL,
    SysEndTime   DATETIME2 GENERATED ALWAYS AS ROW END NOT NULL,
    PERIOD FOR SYSTEM_TIME (SysStartTime, SysEndTime),
    CONSTRAINT PK_UserRoles PRIMARY KEY (UserID, RoleID, CompanyID)
)
WITH (SYSTEM_VERSIONING = ON (HISTORY_TABLE = sec.UserRoles_History));
GO

-- نقش اختصاصیِ یک ماژول: همان کاربر می‌تواند در ماژول‌های مختلف نقش‌های متفاوتی
-- داشته باشد (مثلاً «مدیر فروش» در ماژول فروش + «فقط‌مشاهده» در ماژول انبار).
-- در محاسبه‌ی دسترسیِ فرم‌های ماژول M، این جدول با UserRoles (سطح‌شرکت) جمع (اتحاد) می‌شود.
CREATE TABLE sec.UserModuleRoles (
    UserID       INT      NOT NULL REFERENCES sec.Users(UserID),
    RoleID       INT      NOT NULL REFERENCES sec.Roles(RoleID),
    CompanyID    INT      NOT NULL REFERENCES core.Companies(CompanyID),
    ModuleID     SMALLINT NOT NULL REFERENCES sec.Modules(ModuleID),
    SysStartTime DATETIME2 GENERATED ALWAYS AS ROW START NOT NULL,
    SysEndTime   DATETIME2 GENERATED ALWAYS AS ROW END NOT NULL,
    PERIOD FOR SYSTEM_TIME (SysStartTime, SysEndTime),
    CONSTRAINT PK_UserModuleRoles PRIMARY KEY (UserID, RoleID, CompanyID, ModuleID)
)
WITH (SYSTEM_VERSIONING = ON (HISTORY_TABLE = sec.UserModuleRoles_History));
GO

-- دسترسی نمایش هر منو به ازای نقش
CREATE TABLE sec.RoleMenuPermissions (
    RoleID       INT      NOT NULL REFERENCES sec.Roles(RoleID),
    MenuID       INT      NOT NULL REFERENCES sec.Menus(MenuID),
    CanView      BIT      NOT NULL CONSTRAINT DF_RoleMenuPermissions_CanView DEFAULT (1),
    SysStartTime DATETIME2 GENERATED ALWAYS AS ROW START NOT NULL,
    SysEndTime   DATETIME2 GENERATED ALWAYS AS ROW END NOT NULL,
    PERIOD FOR SYSTEM_TIME (SysStartTime, SysEndTime),
    CONSTRAINT PK_RoleMenuPermissions PRIMARY KEY (RoleID, MenuID)
)
WITH (SYSTEM_VERSIONING = ON (HISTORY_TABLE = sec.RoleMenuPermissions_History));
GO

-- دسترسی هر اکشن (مشاهده/ایجاد/ویرایش/حذف/چاپ/خروجی/تایید) روی هر فرم به ازای نقش
-- عدم‌وجود ردیف = عدم دسترسی (پیش‌فرض انکار = deny by default)
CREATE TABLE sec.RoleFormPermissions (
    RoleID       INT      NOT NULL REFERENCES sec.Roles(RoleID),
    FormID       INT      NOT NULL REFERENCES sec.Forms(FormID),
    ActionID     TINYINT  NOT NULL REFERENCES sec.PermissionActions(ActionID),
    IsAllowed    BIT      NOT NULL CONSTRAINT DF_RoleFormPermissions_Allowed DEFAULT (1),
    SysStartTime DATETIME2 GENERATED ALWAYS AS ROW START NOT NULL,
    SysEndTime   DATETIME2 GENERATED ALWAYS AS ROW END NOT NULL,
    PERIOD FOR SYSTEM_TIME (SysStartTime, SysEndTime),
    CONSTRAINT PK_RoleFormPermissions PRIMARY KEY (RoleID, FormID, ActionID)
)
WITH (SYSTEM_VERSIONING = ON (HISTORY_TABLE = sec.RoleFormPermissions_History));
GO

-- محدودسازی سطح فیلد؛ فقط برای «سخت‌گیرتر کردن» نسبت به سطح فرم استفاده می‌شود
-- (نمی‌تواند دسترسی بیشتر از سطح فرم بدهد). نبود ردیف = فیلد از دسترسی فرم پیروی می‌کند.
-- PermissionLevel: 1 = Hidden , 2 = ReadOnly
CREATE TABLE sec.RoleFieldPermissions (
    RoleID          INT      NOT NULL REFERENCES sec.Roles(RoleID),
    FieldID         INT      NOT NULL REFERENCES sec.FormFields(FieldID),
    PermissionLevel TINYINT  NOT NULL,
    SysStartTime DATETIME2 GENERATED ALWAYS AS ROW START NOT NULL,
    SysEndTime   DATETIME2 GENERATED ALWAYS AS ROW END NOT NULL,
    PERIOD FOR SYSTEM_TIME (SysStartTime, SysEndTime),
    CONSTRAINT PK_RoleFieldPermissions PRIMARY KEY (RoleID, FieldID),
    CONSTRAINT CK_RoleFieldPermissions_Level CHECK (PermissionLevel IN (1, 2))
)
WITH (SYSTEM_VERSIONING = ON (HISTORY_TABLE = sec.RoleFieldPermissions_History));
GO
