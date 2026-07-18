-- پیچا | ماژول حسابداری (دفتر کل): سال/دوره‌ی مالی، کدینگ حسابداری درختی،
-- تفصیلی شناور چندبعدی، اسناد حسابداری و آرتیکل‌ها
-- سازگار با SQL Server 2016
-- پیش‌نیاز: 001_core_i18n_and_tenancy.sql

CREATE SCHEMA acc;
GO

-- ---------------------------------------------------------------------
-- سال مالی و دوره‌های مالی (برای قفل‌کردن دوره‌های بسته‌شده)
-- ---------------------------------------------------------------------
CREATE TABLE acc.FiscalYears (
    FiscalYearID INT          NOT NULL IDENTITY(1,1) PRIMARY KEY,
    CompanyID    INT          NOT NULL REFERENCES core.Companies(CompanyID),
    Code         VARCHAR(20)  NOT NULL,   -- مثلاً "1404"
    StartDate    DATE         NOT NULL,
    EndDate      DATE         NOT NULL,
    IsClosed     BIT          NOT NULL CONSTRAINT DF_FiscalYears_IsClosed DEFAULT (0),
    CONSTRAINT UQ_FiscalYears UNIQUE (CompanyID, Code),
    CONSTRAINT CK_FiscalYears_Dates CHECK (EndDate > StartDate)
);
GO

CREATE TABLE acc.FiscalPeriods (
    FiscalPeriodID INT      NOT NULL IDENTITY(1,1) PRIMARY KEY,
    FiscalYearID   INT      NOT NULL REFERENCES acc.FiscalYears(FiscalYearID),
    PeriodNo       TINYINT  NOT NULL,   -- 1..12 (یا بیشتر در صورت نیاز)
    StartDate      DATE     NOT NULL,
    EndDate        DATE     NOT NULL,
    IsClosed       BIT      NOT NULL CONSTRAINT DF_FiscalPeriods_IsClosed DEFAULT (0),
    CONSTRAINT UQ_FiscalPeriods UNIQUE (FiscalYearID, PeriodNo),
    CONSTRAINT CK_FiscalPeriods_Dates CHECK (EndDate > StartDate)
);
GO

-- ---------------------------------------------------------------------
-- کدینگ حسابداری (سرفصل حساب‌ها) — درخت با عمق آزاد؛ AccountLevel صرفاً
-- برچسب گزارشی است (۱=گروه، ۲=کل، ۳=معین، ...) و محدودکننده‌ی عمق واقعی نیست.
-- ---------------------------------------------------------------------
CREATE TABLE acc.AccountNatures (            -- ماهیت حساب: بدهکار/بستانکار/دوطرفه
    NatureID TINYINT     NOT NULL PRIMARY KEY,
    Code     VARCHAR(20) NOT NULL UNIQUE
);
GO
INSERT INTO acc.AccountNatures (NatureID, Code) VALUES
    (1, 'DEBIT'), (2, 'CREDIT'), (3, 'BOTH');
GO

CREATE TABLE acc.AccountCategories (         -- برای طبقه‌بندی در صورت‌های مالی
    CategoryID TINYINT     NOT NULL PRIMARY KEY,
    Code       VARCHAR(20) NOT NULL UNIQUE
);
GO
INSERT INTO acc.AccountCategories (CategoryID, Code) VALUES
    (1, 'ASSET'), (2, 'LIABILITY'), (3, 'EQUITY'), (4, 'REVENUE'), (5, 'EXPENSE');
GO

CREATE TABLE acc.ChartOfAccounts (
    AccountID        INT          NOT NULL IDENTITY(1,1) PRIMARY KEY,
    CompanyID        INT          NOT NULL REFERENCES core.Companies(CompanyID),
    ParentAccountID  INT          NULL REFERENCES acc.ChartOfAccounts(AccountID),
    SegmentCode      VARCHAR(20)  NOT NULL,   -- کد این گره به‌تنهایی، مثلاً "01"
    FullCode         VARCHAR(100) NOT NULL,   -- کد کامل ترکیبی برای نمایش/مرتب‌سازی سریع، مثلاً "11.01"
    AccountLevel     TINYINT      NOT NULL,   -- ۱=گروه، ۲=کل، ۳=معین (صرفاً برچسب گزارشی)
    NatureID         TINYINT      NOT NULL REFERENCES acc.AccountNatures(NatureID),
    CategoryID       TINYINT      NOT NULL REFERENCES acc.AccountCategories(CategoryID),
    IsPostable       BIT          NOT NULL CONSTRAINT DF_ChartOfAccounts_IsPostable DEFAULT (0), -- فقط حساب‌های Postable می‌توانند طرف سند قرار بگیرند
    CurrencyID       INT          NULL REFERENCES core.Currencies(CurrencyID), -- NULL = هر ارز فعال شرکت؛ مقداردار = این حساب فقط با این ارز
    IsActive         BIT          NOT NULL CONSTRAINT DF_ChartOfAccounts_IsActive DEFAULT (1),
    CONSTRAINT UQ_ChartOfAccounts_FullCode UNIQUE (CompanyID, FullCode)
);
GO
CREATE INDEX IX_ChartOfAccounts_Parent ON acc.ChartOfAccounts(ParentAccountID);
GO

-- ---------------------------------------------------------------------
-- تفصیلی شناور چندبعدی: هر معین می‌تواند صفر یا چند بعد تفصیلی بپذیرد
-- (مثلاً حساب «بدهکاران تجاری» هم بعد «مشتری» و هم بعد «مرکز هزینه» بخواهد)
-- ---------------------------------------------------------------------
CREATE TABLE acc.DetailDimensionTypes (      -- انواع بعد تفصیلی
    DimensionTypeID SMALLINT   NOT NULL IDENTITY(1,1) PRIMARY KEY,
    CompanyID       INT        NOT NULL REFERENCES core.Companies(CompanyID),
    Code            VARCHAR(30) NOT NULL,    -- CUSTOMER, VENDOR, COST_CENTER, PROJECT, EMPLOYEE, CASHBANK ...
    IsActive        BIT        NOT NULL CONSTRAINT DF_DetailDimensionTypes_IsActive DEFAULT (1),
    CONSTRAINT UQ_DetailDimensionTypes UNIQUE (CompanyID, Code)
);
GO

CREATE TABLE acc.DetailAccounts (            -- نمونه‌های واقعی هر بعد (مثلاً یک مشتری خاص)
    DetailAccountID INT          NOT NULL IDENTITY(1,1) PRIMARY KEY,
    CompanyID       INT          NOT NULL REFERENCES core.Companies(CompanyID),
    DimensionTypeID SMALLINT     NOT NULL REFERENCES acc.DetailDimensionTypes(DimensionTypeID),
    Code            VARCHAR(30)  NOT NULL,
    IsActive        BIT          NOT NULL CONSTRAINT DF_DetailAccounts_IsActive DEFAULT (1),
    CONSTRAINT UQ_DetailAccounts UNIQUE (CompanyID, DimensionTypeID, Code)
);
GO

CREATE TABLE acc.AccountDetailDimensions (   -- کدام معین‌ها کدام ابعاد را می‌پذیرند/الزامی است
    AccountID       INT      NOT NULL REFERENCES acc.ChartOfAccounts(AccountID),
    DimensionTypeID SMALLINT NOT NULL REFERENCES acc.DetailDimensionTypes(DimensionTypeID),
    IsRequired      BIT      NOT NULL CONSTRAINT DF_AccountDetailDimensions_Required DEFAULT (1),
    CONSTRAINT PK_AccountDetailDimensions PRIMARY KEY (AccountID, DimensionTypeID)
);
GO

-- ---------------------------------------------------------------------
-- اسناد حسابداری
-- ---------------------------------------------------------------------
CREATE TABLE acc.JournalEntryTypes (
    EntryTypeID TINYINT     NOT NULL PRIMARY KEY,
    Code        VARCHAR(20) NOT NULL UNIQUE   -- NORMAL, OPENING, CLOSING, ADJUSTING
);
GO
INSERT INTO acc.JournalEntryTypes (EntryTypeID, Code) VALUES
    (1, 'NORMAL'), (2, 'OPENING'), (3, 'CLOSING'), (4, 'ADJUSTING');
GO

CREATE TABLE acc.JournalEntryStatuses (
    StatusID TINYINT     NOT NULL PRIMARY KEY,
    Code     VARCHAR(20) NOT NULL UNIQUE      -- TEMPORARY (موقت), PERMANENT (دائم), REVERSED (برگشت‌خورده)
);
GO
INSERT INTO acc.JournalEntryStatuses (StatusID, Code) VALUES
    (1, 'TEMPORARY'), (2, 'PERMANENT'), (3, 'REVERSED');
GO

CREATE TABLE acc.JournalEntries (            -- هدر سند
    JournalEntryID   INT           NOT NULL IDENTITY(1,1) PRIMARY KEY,
    CompanyID        INT           NOT NULL REFERENCES core.Companies(CompanyID),
    FiscalYearID     INT           NOT NULL REFERENCES acc.FiscalYears(FiscalYearID),
    DocumentNo       INT           NOT NULL,   -- شماره سند در سال مالی؛ تخصیص آن بر عهده‌ی لایه‌ی سرویس است
    DocumentDate     DATE          NOT NULL,
    EntryTypeID      TINYINT       NOT NULL REFERENCES acc.JournalEntryTypes(EntryTypeID),
    StatusID         TINYINT       NOT NULL REFERENCES acc.JournalEntryStatuses(StatusID),
    Description      NVARCHAR(500) NULL,
    ReversedEntryID  INT           NULL REFERENCES acc.JournalEntries(JournalEntryID), -- اگر این سند، برگشتِ سند دیگری است
    CreatedByUserID  INT           NOT NULL REFERENCES sec.Users(UserID),
    CreatedAt        DATETIME2(0)  NOT NULL CONSTRAINT DF_JournalEntries_CreatedAt DEFAULT (SYSUTCDATETIME()),
    PostedByUserID   INT           NULL REFERENCES sec.Users(UserID),
    PostedAt         DATETIME2(0)  NULL,
    CONSTRAINT UQ_JournalEntries_DocNo UNIQUE (CompanyID, FiscalYearID, DocumentNo)
);
GO

CREATE TABLE acc.JournalEntryLines (         -- آرتیکل‌های سند (ردیف‌های بدهکار/بستانکار)
    LineID           BIGINT        NOT NULL IDENTITY(1,1) PRIMARY KEY,
    JournalEntryID   INT           NOT NULL REFERENCES acc.JournalEntries(JournalEntryID),
    LineNo           SMALLINT      NOT NULL,
    AccountID        INT           NOT NULL REFERENCES acc.ChartOfAccounts(AccountID),
    Description      NVARCHAR(500) NULL,
    CurrencyID       INT           NOT NULL REFERENCES core.Currencies(CurrencyID),
    ExchangeRate     DECIMAL(18,6) NOT NULL CONSTRAINT DF_JournalEntryLines_Rate DEFAULT (1),
    DebitAmountFC    DECIMAL(18,2) NOT NULL CONSTRAINT DF_JournalEntryLines_DrFC DEFAULT (0),  -- مبلغ به ارز ردیف
    CreditAmountFC   DECIMAL(18,2) NOT NULL CONSTRAINT DF_JournalEntryLines_CrFC DEFAULT (0),
    DebitAmountBase  AS (CAST(DebitAmountFC  * ExchangeRate AS DECIMAL(18,2))) PERSISTED,        -- معادل ارز پایه‌ی شرکت
    CreditAmountBase AS (CAST(CreditAmountFC * ExchangeRate AS DECIMAL(18,2))) PERSISTED,
    CONSTRAINT UQ_JournalEntryLines UNIQUE (JournalEntryID, LineNo),
    CONSTRAINT CK_JournalEntryLines_OneSided CHECK (
        (DebitAmountFC > 0 AND CreditAmountFC = 0) OR
        (CreditAmountFC > 0 AND DebitAmountFC = 0)
    )
);
GO
CREATE INDEX IX_JournalEntryLines_Account ON acc.JournalEntryLines(AccountID);
GO

CREATE TABLE acc.JournalEntryLineDetails (   -- تخصیص تفصیلی‌های هر ردیف سند
    LineID          BIGINT   NOT NULL REFERENCES acc.JournalEntryLines(LineID),
    DimensionTypeID SMALLINT NOT NULL REFERENCES acc.DetailDimensionTypes(DimensionTypeID),
    DetailAccountID INT      NOT NULL REFERENCES acc.DetailAccounts(DetailAccountID),
    CONSTRAINT PK_JournalEntryLineDetails PRIMARY KEY (LineID, DimensionTypeID)
);
GO
