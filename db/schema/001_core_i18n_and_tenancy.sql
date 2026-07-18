-- پیچا | هسته: چند‌زبانگی، چند‌شرکتی، چند‌ارزی
-- PostgreSQL 13+  (نیاز به نسخه‌ی ۱۳ برای ستون‌های GENERATED ... STORED در فایل‌های بعدی)
-- نکته: Postgres شناسه‌های بدون کوتیشن را خودکار به حروف کوچک تبدیل می‌کند؛
-- سبک PascalCase در سورس فقط برای خوانایی است و در psql به‌صورت lowercase دیده می‌شود.
-- ترتیب اجرا: 001 قبل از 002

CREATE SCHEMA core;

-- ---------------------------------------------------------------------
-- زبان‌ها
-- ---------------------------------------------------------------------
CREATE TABLE core.Languages (
    LanguageID  SMALLINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    Code        VARCHAR(10)   NOT NULL,              -- fa-IR, en-US, ar-AE ...
    NativeName  VARCHAR(50)   NOT NULL,               -- فارسی, English ...
    IsRTL       BOOLEAN       NOT NULL DEFAULT FALSE,
    IsDefault   BOOLEAN       NOT NULL DEFAULT FALSE,
    IsActive    BOOLEAN       NOT NULL DEFAULT TRUE,
    SortOrder   SMALLINT      NOT NULL DEFAULT 0,
    CONSTRAINT UQ_Languages_Code UNIQUE (Code)
);

-- فقط یک زبان پیش‌فرض مجاز است
CREATE UNIQUE INDEX UX_Languages_OneDefault ON core.Languages(IsDefault) WHERE IsDefault = TRUE;

-- ---------------------------------------------------------------------
-- ترجمه‌های عمومی: هر موجودیت/فیلد قابل‌نمایش در هر زبان یک ردیف دارد.
-- با این روش افزودن زبان جدید نیاز به ALTER TABLE در بقیه‌ی سیستم ندارد.
-- ---------------------------------------------------------------------
CREATE TABLE core.Translations (
    TranslationID BIGINT        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    EntityType    VARCHAR(50)   NOT NULL,   -- 'Module' | 'Menu' | 'Form' | 'FormField' | 'Role' | 'Currency' | 'Company' | ...
    EntityID      INT           NOT NULL,
    PropertyName  VARCHAR(50)   NOT NULL,   -- 'Name' | 'Description' | ...
    LanguageID    SMALLINT      NOT NULL REFERENCES core.Languages(LanguageID),
    Value         VARCHAR(400)  NOT NULL,
    CONSTRAINT UQ_Translations UNIQUE (EntityType, EntityID, PropertyName, LanguageID)
);
CREATE INDEX IX_Translations_Lookup ON core.Translations(EntityType, EntityID, LanguageID);

-- ---------------------------------------------------------------------
-- ارزها (فهرست سراسری؛ نام نمایشی از core.Translations می‌آید)
-- ---------------------------------------------------------------------
CREATE TABLE core.Currencies (
    CurrencyID    INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    IsoCode       VARCHAR(3)   NOT NULL,   -- IRR, USD, EUR, AED ...
    Symbol        VARCHAR(10)  NULL,
    DecimalPlaces SMALLINT     NOT NULL DEFAULT 2,
    IsActive      BOOLEAN      NOT NULL DEFAULT TRUE,
    CONSTRAINT UQ_Currencies_IsoCode UNIQUE (IsoCode)
);

-- ---------------------------------------------------------------------
-- شرکت‌ها (چند‌شرکتی)
-- ---------------------------------------------------------------------
CREATE TABLE core.Companies (
    CompanyID            INT           GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    Code                 VARCHAR(20)   NOT NULL,
    LegalName            VARCHAR(200)  NOT NULL,
    DisplayName          VARCHAR(200)  NOT NULL,
    EconomicCode         VARCHAR(30)   NULL,
    RegistrationNo       VARCHAR(30)   NULL,
    NationalID           VARCHAR(30)   NULL,
    FiscalYearStartMonth SMALLINT      NOT NULL DEFAULT 1,
    FiscalYearStartDay   SMALLINT      NOT NULL DEFAULT 1,
    BaseCurrencyID       INT           NOT NULL REFERENCES core.Currencies(CurrencyID),
    DefaultLanguageID    SMALLINT      NOT NULL REFERENCES core.Languages(LanguageID),
    IsActive              BOOLEAN      NOT NULL DEFAULT TRUE,
    CreatedAt             TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT UQ_Companies_Code UNIQUE (Code)
);

-- ارزهای فعال هر شرکت (یک شرکت می‌تواند چند ارز برای معامله داشته باشد، جدا از ارز پایه)
CREATE TABLE core.CompanyCurrencies (
    CompanyID  INT NOT NULL REFERENCES core.Companies(CompanyID),
    CurrencyID INT NOT NULL REFERENCES core.Currencies(CurrencyID),
    IsActive   BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT PK_CompanyCurrencies PRIMARY KEY (CompanyID, CurrencyID)
);

-- نرخ تبدیل روزانه‌ی هر ارز به ارز پایه‌ی همان شرکت
CREATE TABLE core.ExchangeRates (
    ExchangeRateID BIGINT        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    CompanyID      INT           NOT NULL REFERENCES core.Companies(CompanyID),
    CurrencyID     INT           NOT NULL REFERENCES core.Currencies(CurrencyID),
    RateDate       DATE          NOT NULL,
    RateToBase     NUMERIC(18,6) NOT NULL,   -- ۱ واحد CurrencyID برابر چند واحد ارز پایه‌ی شرکت است
    CONSTRAINT UQ_ExchangeRates UNIQUE (CompanyID, CurrencyID, RateDate)
);
