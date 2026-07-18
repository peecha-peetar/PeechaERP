-- پیچا | هسته: چند‌زبانگی، چند‌شرکتی، چند‌ارزی
-- سازگار با SQL Server 2016
-- ترتیب اجرا: 001 قبل از 002

CREATE SCHEMA core;
GO

-- ---------------------------------------------------------------------
-- زبان‌ها
-- ---------------------------------------------------------------------
CREATE TABLE core.Languages (
    LanguageID  TINYINT       NOT NULL IDENTITY(1,1) PRIMARY KEY,
    Code        VARCHAR(10)   NOT NULL,              -- fa-IR, en-US, ar-AE ...
    NativeName  NVARCHAR(50)  NOT NULL,               -- فارسی, English ...
    IsRTL       BIT           NOT NULL CONSTRAINT DF_Languages_IsRTL DEFAULT (0),
    IsDefault   BIT           NOT NULL CONSTRAINT DF_Languages_IsDefault DEFAULT (0),
    IsActive    BIT           NOT NULL CONSTRAINT DF_Languages_IsActive DEFAULT (1),
    SortOrder   SMALLINT      NOT NULL CONSTRAINT DF_Languages_SortOrder DEFAULT (0),
    CONSTRAINT UQ_Languages_Code UNIQUE (Code)
);
GO

-- فقط یک زبان پیش‌فرض مجاز است
CREATE UNIQUE INDEX UX_Languages_OneDefault ON core.Languages(IsDefault) WHERE IsDefault = 1;
GO

-- ---------------------------------------------------------------------
-- ترجمه‌های عمومی: هر موجودیت/فیلد قابل‌نمایش در هر زبان یک ردیف دارد.
-- با این روش افزودن زبان جدید نیاز به ALTER TABLE در بقیه‌ی سیستم ندارد.
-- ---------------------------------------------------------------------
CREATE TABLE core.Translations (
    TranslationID BIGINT        NOT NULL IDENTITY(1,1) PRIMARY KEY,
    EntityType    VARCHAR(50)   NOT NULL,   -- 'Module' | 'Menu' | 'Form' | 'FormField' | 'Role' | 'Currency' | 'Company' | ...
    EntityID      INT           NOT NULL,
    PropertyName  VARCHAR(50)   NOT NULL,   -- 'Name' | 'Description' | ...
    LanguageID    TINYINT       NOT NULL,
    Value         NVARCHAR(400) NOT NULL,
    CONSTRAINT UQ_Translations UNIQUE (EntityType, EntityID, PropertyName, LanguageID),
    CONSTRAINT FK_Translations_Language FOREIGN KEY (LanguageID) REFERENCES core.Languages(LanguageID)
);
GO
CREATE INDEX IX_Translations_Lookup ON core.Translations(EntityType, EntityID, LanguageID);
GO

-- ---------------------------------------------------------------------
-- ارزها (فهرست سراسری؛ نام نمایشی از core.Translations می‌آید)
-- ---------------------------------------------------------------------
CREATE TABLE core.Currencies (
    CurrencyID    INT          NOT NULL IDENTITY(1,1) PRIMARY KEY,
    IsoCode       VARCHAR(3)   NOT NULL,   -- IRR, USD, EUR, AED ...
    Symbol        NVARCHAR(10) NULL,
    DecimalPlaces TINYINT      NOT NULL CONSTRAINT DF_Currencies_Decimals DEFAULT (2),
    IsActive      BIT          NOT NULL CONSTRAINT DF_Currencies_IsActive DEFAULT (1),
    CONSTRAINT UQ_Currencies_IsoCode UNIQUE (IsoCode)
);
GO

-- ---------------------------------------------------------------------
-- شرکت‌ها (چند‌شرکتی)
-- ---------------------------------------------------------------------
CREATE TABLE core.Companies (
    CompanyID            INT           NOT NULL IDENTITY(1,1) PRIMARY KEY,
    Code                 VARCHAR(20)   NOT NULL,
    LegalName            NVARCHAR(200) NOT NULL,
    DisplayName          NVARCHAR(200) NOT NULL,
    EconomicCode         VARCHAR(30)   NULL,
    RegistrationNo       VARCHAR(30)   NULL,
    NationalID           VARCHAR(30)   NULL,
    FiscalYearStartMonth TINYINT       NOT NULL CONSTRAINT DF_Companies_FYStartMonth DEFAULT (1),
    FiscalYearStartDay   TINYINT       NOT NULL CONSTRAINT DF_Companies_FYStartDay DEFAULT (1),
    BaseCurrencyID       INT           NOT NULL,
    DefaultLanguageID    TINYINT       NOT NULL,
    IsActive              BIT          NOT NULL CONSTRAINT DF_Companies_IsActive DEFAULT (1),
    CreatedAt             DATETIME2(0) NOT NULL CONSTRAINT DF_Companies_CreatedAt DEFAULT (SYSUTCDATETIME()),
    CONSTRAINT UQ_Companies_Code UNIQUE (Code),
    CONSTRAINT FK_Companies_BaseCurrency FOREIGN KEY (BaseCurrencyID) REFERENCES core.Currencies(CurrencyID),
    CONSTRAINT FK_Companies_DefaultLanguage FOREIGN KEY (DefaultLanguageID) REFERENCES core.Languages(LanguageID)
);
GO

-- ارزهای فعال هر شرکت (یک شرکت می‌تواند چند ارز برای معامله داشته باشد، جدا از ارز پایه)
CREATE TABLE core.CompanyCurrencies (
    CompanyID  INT NOT NULL REFERENCES core.Companies(CompanyID),
    CurrencyID INT NOT NULL REFERENCES core.Currencies(CurrencyID),
    IsActive   BIT NOT NULL CONSTRAINT DF_CompanyCurrencies_IsActive DEFAULT (1),
    CONSTRAINT PK_CompanyCurrencies PRIMARY KEY (CompanyID, CurrencyID)
);
GO

-- نرخ تبدیل روزانه‌ی هر ارز به ارز پایه‌ی همان شرکت
CREATE TABLE core.ExchangeRates (
    ExchangeRateID BIGINT        NOT NULL IDENTITY(1,1) PRIMARY KEY,
    CompanyID      INT           NOT NULL REFERENCES core.Companies(CompanyID),
    CurrencyID     INT           NOT NULL REFERENCES core.Currencies(CurrencyID),
    RateDate       DATE          NOT NULL,
    RateToBase     DECIMAL(18,6) NOT NULL,   -- ۱ واحد CurrencyID برابر چند واحد ارز پایه‌ی شرکت است
    CONSTRAINT UQ_ExchangeRates UNIQUE (CompanyID, CurrencyID, RateDate)
);
GO
