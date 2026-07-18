-- پیچا | هسته: چند‌زبانگی، چند‌شرکتی، چند‌ارزی
-- PostgreSQL 13+  (نیاز به نسخه‌ی ۱۳ برای ستون‌های GENERATED ... STORED در فایل‌های بعدی)
-- نکته: تمام شناسه‌ها snake_case و بدون کوتیشن‌اند (سبک استاندارد خودِ Postgres)
-- تا مدل‌های SQLAlchemy بدون نگاشت دستیِ نام ستون نوشته شوند.
-- ترتیب اجرا: 001 قبل از 002

CREATE SCHEMA core;

-- ---------------------------------------------------------------------
-- زبان‌ها
-- ---------------------------------------------------------------------
CREATE TABLE core.languages (
    language_id  SMALLINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code         VARCHAR(10)   NOT NULL,              -- fa-IR, en-US, ar-AE ...
    native_name  VARCHAR(50)   NOT NULL,               -- فارسی, English ...
    is_rtl       BOOLEAN       NOT NULL DEFAULT FALSE,
    is_default   BOOLEAN       NOT NULL DEFAULT FALSE,
    is_active    BOOLEAN       NOT NULL DEFAULT TRUE,
    sort_order   SMALLINT      NOT NULL DEFAULT 0,
    CONSTRAINT uq_languages_code UNIQUE (code)
);

-- فقط یک زبان پیش‌فرض مجاز است
CREATE UNIQUE INDEX ux_languages_one_default ON core.languages(is_default) WHERE is_default = TRUE;

-- ---------------------------------------------------------------------
-- ترجمه‌های عمومی: هر موجودیت/فیلد قابل‌نمایش در هر زبان یک ردیف دارد.
-- با این روش افزودن زبان جدید نیاز به ALTER TABLE در بقیه‌ی سیستم ندارد.
-- ---------------------------------------------------------------------
CREATE TABLE core.translations (
    translation_id BIGINT        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entity_type    VARCHAR(50)   NOT NULL,   -- 'module' | 'menu' | 'form' | 'form_field' | 'role' | 'currency' | 'company' | ...
    entity_id      INT           NOT NULL,
    property_name  VARCHAR(50)   NOT NULL,   -- 'name' | 'description' | ...
    language_id    SMALLINT      NOT NULL REFERENCES core.languages(language_id),
    value          VARCHAR(400)  NOT NULL,
    CONSTRAINT uq_translations UNIQUE (entity_type, entity_id, property_name, language_id)
);
CREATE INDEX ix_translations_lookup ON core.translations(entity_type, entity_id, language_id);

-- ---------------------------------------------------------------------
-- ارزها (فهرست سراسری؛ نام نمایشی از core.translations می‌آید)
-- ---------------------------------------------------------------------
CREATE TABLE core.currencies (
    currency_id    INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    iso_code       VARCHAR(3)   NOT NULL,   -- IRR, USD, EUR, AED ...
    symbol         VARCHAR(10)  NULL,
    decimal_places SMALLINT     NOT NULL DEFAULT 2,
    is_active      BOOLEAN      NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_currencies_iso_code UNIQUE (iso_code)
);

-- ---------------------------------------------------------------------
-- شرکت‌ها (چند‌شرکتی)
-- ---------------------------------------------------------------------
CREATE TABLE core.companies (
    company_id               INT           GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code                     VARCHAR(20)   NOT NULL,
    legal_name               VARCHAR(200)  NOT NULL,
    display_name             VARCHAR(200)  NOT NULL,
    economic_code            VARCHAR(30)   NULL,
    registration_no          VARCHAR(30)   NULL,
    national_id              VARCHAR(30)   NULL,
    fiscal_year_start_month  SMALLINT      NOT NULL DEFAULT 1,
    fiscal_year_start_day    SMALLINT      NOT NULL DEFAULT 1,
    base_currency_id         INT           NOT NULL REFERENCES core.currencies(currency_id),
    default_language_id      SMALLINT      NOT NULL REFERENCES core.languages(language_id),
    is_active                BOOLEAN       NOT NULL DEFAULT TRUE,
    created_at                TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_companies_code UNIQUE (code)
);

-- ارزهای فعال هر شرکت (یک شرکت می‌تواند چند ارز برای معامله داشته باشد، جدا از ارز پایه)
CREATE TABLE core.company_currencies (
    company_id  INT NOT NULL REFERENCES core.companies(company_id),
    currency_id INT NOT NULL REFERENCES core.currencies(currency_id),
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT pk_company_currencies PRIMARY KEY (company_id, currency_id)
);

-- نرخ تبدیل روزانه‌ی هر ارز به ارز پایه‌ی همان شرکت
CREATE TABLE core.exchange_rates (
    exchange_rate_id BIGINT        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id       INT           NOT NULL REFERENCES core.companies(company_id),
    currency_id      INT           NOT NULL REFERENCES core.currencies(currency_id),
    rate_date        DATE          NOT NULL,
    rate_to_base     NUMERIC(18,6) NOT NULL,   -- ۱ واحد currency_id برابر چند واحد ارز پایه‌ی شرکت است
    CONSTRAINT uq_exchange_rates UNIQUE (company_id, currency_id, rate_date)
);
