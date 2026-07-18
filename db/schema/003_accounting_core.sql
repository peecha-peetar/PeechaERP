-- پیچا | ماژول حسابداری (دفتر کل): سال/دوره‌ی مالی، کدینگ حسابداری درختی،
-- تفصیلی شناور چندبعدی، اسناد حسابداری و آرتیکل‌ها
-- PostgreSQL 13+ — شناسه‌ها snake_case هستند (بدون کوتیشن)
-- پیش‌نیاز: 001_core_i18n_and_tenancy.sql، 002_security_rbac.sql (برای sec.users)

CREATE SCHEMA acc;

-- ---------------------------------------------------------------------
-- سال مالی و دوره‌های مالی (برای قفل‌کردن دوره‌های بسته‌شده)
-- ---------------------------------------------------------------------
CREATE TABLE acc.fiscal_years (
    fiscal_year_id INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id     INT          NOT NULL REFERENCES core.companies(company_id),
    code           VARCHAR(20)  NOT NULL,   -- مثلاً "1404"
    start_date     DATE         NOT NULL,
    end_date       DATE         NOT NULL,
    is_closed      BOOLEAN      NOT NULL DEFAULT FALSE,
    CONSTRAINT uq_fiscal_years UNIQUE (company_id, code),
    CONSTRAINT ck_fiscal_years_dates CHECK (end_date > start_date)
);

CREATE TABLE acc.fiscal_periods (
    fiscal_period_id INT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fiscal_year_id   INT      NOT NULL REFERENCES acc.fiscal_years(fiscal_year_id),
    period_no        SMALLINT NOT NULL,   -- 1..12 (یا بیشتر در صورت نیاز)
    start_date       DATE     NOT NULL,
    end_date         DATE     NOT NULL,
    is_closed        BOOLEAN  NOT NULL DEFAULT FALSE,
    CONSTRAINT uq_fiscal_periods UNIQUE (fiscal_year_id, period_no),
    CONSTRAINT ck_fiscal_periods_dates CHECK (end_date > start_date)
);

-- ---------------------------------------------------------------------
-- کدینگ حسابداری (سرفصل حساب‌ها) — ۴ سطح: گروه(۱) / کل(۲) / معین(۳) به‌صورت
-- درخت والد-فرزند، و تفصیلی شناور(۴) که چون چندبعدی و هم‌زمان‌پذیر است
-- (یک معین می‌تواند هم‌زمان چند بعد تفصیلی بخواهد) عمداً به‌صورت یک سیستم
-- جدا (چند جدول پایین‌تر) مدل شده، نه یک والد/فرزند دیگر در همین درخت.
-- ---------------------------------------------------------------------
CREATE TABLE acc.account_natures (            -- ماهیت حساب: بدهکار/بستانکار/دوطرفه
    nature_id SMALLINT    NOT NULL PRIMARY KEY,
    code      VARCHAR(20) NOT NULL UNIQUE
);
INSERT INTO acc.account_natures (nature_id, code) VALUES
    (1, 'DEBIT'), (2, 'CREDIT'), (3, 'BOTH');

CREATE TABLE acc.account_categories (         -- برای طبقه‌بندی در صورت‌های مالی
    category_id SMALLINT    NOT NULL PRIMARY KEY,
    code        VARCHAR(20) NOT NULL UNIQUE
);
INSERT INTO acc.account_categories (category_id, code) VALUES
    (1, 'ASSET'), (2, 'LIABILITY'), (3, 'EQUITY'), (4, 'REVENUE'), (5, 'EXPENSE');

-- نوع حساب: ترازنامه‌ای (دائمی، در پایان سال مالی بسته نمی‌شود) در برابر
-- موقت (نظیر درآمد/هزینه؛ با سند اختتامیه به صفر می‌رسد). معمولاً در سطح
-- گروه تعیین می‌شود و کل/معین زیرمجموعه‌اش همان مقدار را به ارث می‌برند
-- (این هم‌خوانی در لایه‌ی سرویس بررسی می‌شود، نه با CHECK بین‌ردیفی).
CREATE TABLE acc.account_types (
    account_type_id SMALLINT    NOT NULL PRIMARY KEY,
    code            VARCHAR(20) NOT NULL UNIQUE     -- PERMANENT (ترازنامه‌ای), TEMPORARY (موقت)
);
INSERT INTO acc.account_types (account_type_id, code) VALUES
    (1, 'PERMANENT'), (2, 'TEMPORARY');

CREATE TABLE acc.chart_of_accounts (
    account_id        INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id        INT          NOT NULL REFERENCES core.companies(company_id),
    parent_account_id INT          NULL REFERENCES acc.chart_of_accounts(account_id),
    segment_code      VARCHAR(20)  NOT NULL,   -- کد این گره به‌تنهایی، مثلاً "01"
    full_code         VARCHAR(100) NOT NULL,   -- کد کامل ترکیبی برای نمایش/مرتب‌سازی سریع، مثلاً "11.01"
    account_level     SMALLINT     NOT NULL,   -- ۱=گروه، ۲=کل، ۳=معین (صرفاً برچسب گزارشی روی همین درخت)
    nature_id         SMALLINT     NOT NULL REFERENCES acc.account_natures(nature_id),
    category_id       SMALLINT     NOT NULL REFERENCES acc.account_categories(category_id),
    account_type_id   SMALLINT     NOT NULL REFERENCES acc.account_types(account_type_id),
    is_postable       BOOLEAN      NOT NULL DEFAULT FALSE, -- فقط حساب‌های postable می‌توانند طرف سند قرار بگیرند
    currency_id       INT          NULL REFERENCES core.currencies(currency_id), -- NULL = هر ارز فعال شرکت؛ مقداردار = این حساب فقط با این ارز
    is_active         BOOLEAN      NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_chart_of_accounts_full_code UNIQUE (company_id, full_code)
);
CREATE INDEX ix_chart_of_accounts_parent ON acc.chart_of_accounts(parent_account_id);

-- حساب‌های واسطی که موتور «سند اختتامیه‌ی خودکار» به آن‌ها نیاز دارد:
-- بستن حساب‌های موقت به حساب واسط سود/زیان، سپس انتقال آن به سود انباشته.
CREATE TABLE acc.company_accounting_settings (
    company_id                    INT NOT NULL PRIMARY KEY REFERENCES core.companies(company_id),
    profit_and_loss_account_id    INT NULL REFERENCES acc.chart_of_accounts(account_id),
    retained_earnings_account_id  INT NULL REFERENCES acc.chart_of_accounts(account_id)
);

-- ---------------------------------------------------------------------
-- تفصیلی شناور چندبعدی: هر معین می‌تواند صفر یا چند بعد تفصیلی بپذیرد
-- (مثلاً حساب «بدهکاران تجاری» هم بعد «مشتری» و هم بعد «مرکز هزینه» بخواهد)
-- ---------------------------------------------------------------------
CREATE TABLE acc.detail_dimension_types (      -- انواع بعد تفصیلی
    dimension_type_id SMALLINT    GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id        INT         NOT NULL REFERENCES core.companies(company_id),
    code               VARCHAR(30) NOT NULL,    -- CUSTOMER, VENDOR, COST_CENTER, PROJECT, EMPLOYEE, CASHBANK ...
    is_active          BOOLEAN     NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_detail_dimension_types UNIQUE (company_id, code)
);

CREATE TABLE acc.detail_accounts (            -- نمونه‌های واقعی هر بعد (مثلاً یک مشتری خاص)
    detail_account_id INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id        INT          NOT NULL REFERENCES core.companies(company_id),
    dimension_type_id SMALLINT     NOT NULL REFERENCES acc.detail_dimension_types(dimension_type_id),
    code               VARCHAR(30)  NOT NULL,
    is_active           BOOLEAN     NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_detail_accounts UNIQUE (company_id, dimension_type_id, code)
);

CREATE TABLE acc.account_detail_dimensions (   -- کدام معین‌ها کدام ابعاد را می‌پذیرند/الزامی است
    account_id         INT      NOT NULL REFERENCES acc.chart_of_accounts(account_id),
    dimension_type_id  SMALLINT NOT NULL REFERENCES acc.detail_dimension_types(dimension_type_id),
    is_required         BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT pk_account_detail_dimensions PRIMARY KEY (account_id, dimension_type_id)
);

-- ---------------------------------------------------------------------
-- اسناد حسابداری
-- ---------------------------------------------------------------------
CREATE TABLE acc.journal_entry_types (
    entry_type_id SMALLINT    NOT NULL PRIMARY KEY,
    code          VARCHAR(20) NOT NULL UNIQUE   -- NORMAL, OPENING, CLOSING, ADJUSTING
);
INSERT INTO acc.journal_entry_types (entry_type_id, code) VALUES
    (1, 'NORMAL'), (2, 'OPENING'), (3, 'CLOSING'), (4, 'ADJUSTING');

CREATE TABLE acc.journal_entry_statuses (
    status_id SMALLINT   NOT NULL PRIMARY KEY,
    code      VARCHAR(20) NOT NULL UNIQUE
);
INSERT INTO acc.journal_entry_statuses (status_id, code) VALUES
    (1, 'TEMPORARY'),   -- موقت: قابل ویرایش/ادغام، شماره‌اش هم قابل تغییر است
    (2, 'PERMANENT'),   -- دائم: پس از تایید در کارتابل؛ شماره‌ی ثابت گرفته و دیگر قابل ویرایش نیست
    (3, 'REVERSED'),    -- برگشت‌خورده: یک سند برگشتی جدید آن را خنثی کرده
    (4, 'CANCELLED');   -- ابطال‌شده/ادغام‌شده در سند موقت دیگر

-- هر سند هم شماره‌ی موقت دارد (از لحظه‌ی ایجاد، قابل تغییر/ادغام) و هم
-- شماره‌ی ثابت (فقط پس از تایید نهایی در کارتابل تخصیص می‌یابد؛ پیوسته و
-- پس از تخصیص غیرقابل تغییر — enforce شده با تریگر پایین همین فایل).
CREATE TABLE acc.journal_entries (            -- هدر سند
    journal_entry_id    INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id           INT         NOT NULL REFERENCES core.companies(company_id),
    fiscal_year_id       INT         NOT NULL REFERENCES acc.fiscal_years(fiscal_year_id),
    temporary_no         INT         NOT NULL,   -- شماره موقت؛ تخصیص/تغییر/ادغام آن بر عهده‌ی لایه‌ی سرویس است
    permanent_no         INT         NULL,       -- شماره ثابت؛ فقط هنگام تبدیل به PERMANENT پر می‌شود
    document_date        DATE        NOT NULL,
    entry_type_id        SMALLINT    NOT NULL REFERENCES acc.journal_entry_types(entry_type_id),
    status_id            SMALLINT    NOT NULL REFERENCES acc.journal_entry_statuses(status_id),
    description           TEXT       NULL,
    is_system_generated   BOOLEAN    NOT NULL DEFAULT FALSE, -- مثلاً سند اختتامیه‌ی خودکار
    reversed_entry_id     INT        NULL REFERENCES acc.journal_entries(journal_entry_id), -- اگر این سند، برگشتِ سند دیگری است
    created_by_user_id    INT        NOT NULL REFERENCES sec.users(user_id),
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    posted_by_user_id      INT        NULL REFERENCES sec.users(user_id),   -- کاربری که در کارتابل تاییدِ نهایی را زده
    posted_at               TIMESTAMPTZ NULL,
    CONSTRAINT uq_journal_entries_temporary_no UNIQUE (company_id, fiscal_year_id, temporary_no)
);
-- شماره‌ی ثابت فقط وقتی مقدار دارد یکتاست (بین چند سند TEMPORARY هنوز NULL است)
CREATE UNIQUE INDEX ux_journal_entries_permanent_no
    ON acc.journal_entries(company_id, fiscal_year_id, permanent_no)
    WHERE permanent_no IS NOT NULL;

CREATE FUNCTION acc.prevent_permanent_no_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.permanent_no IS NOT NULL AND (NEW.permanent_no IS NULL OR NEW.permanent_no <> OLD.permanent_no) THEN
        RAISE EXCEPTION 'شماره ثابت سند حسابداری پس از تخصیص غیرقابل تغییر است.';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER tr_journal_entries_prevent_permanent_no_change
    BEFORE UPDATE ON acc.journal_entries
    FOR EACH ROW EXECUTE FUNCTION acc.prevent_permanent_no_change();

CREATE TABLE acc.journal_entry_lines (         -- آرتیکل‌های سند (ردیف‌های بدهکار/بستانکار)
    line_id            BIGINT        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    journal_entry_id   INT           NOT NULL REFERENCES acc.journal_entries(journal_entry_id),
    line_no            SMALLINT      NOT NULL,
    account_id         INT           NOT NULL REFERENCES acc.chart_of_accounts(account_id),
    description        TEXT          NULL,
    currency_id        INT           NOT NULL REFERENCES core.currencies(currency_id),
    exchange_rate      NUMERIC(18,6) NOT NULL DEFAULT 1,
    debit_amount_fc    NUMERIC(18,2) NOT NULL DEFAULT 0,  -- مبلغ به ارز ردیف
    credit_amount_fc   NUMERIC(18,2) NOT NULL DEFAULT 0,
    debit_amount_base  NUMERIC(18,2) GENERATED ALWAYS AS (ROUND(debit_amount_fc  * exchange_rate, 2)) STORED, -- معادل ارز پایه‌ی شرکت
    credit_amount_base NUMERIC(18,2) GENERATED ALWAYS AS (ROUND(credit_amount_fc * exchange_rate, 2)) STORED,
    CONSTRAINT uq_journal_entry_lines UNIQUE (journal_entry_id, line_no),
    CONSTRAINT ck_journal_entry_lines_one_sided CHECK (
        (debit_amount_fc > 0 AND credit_amount_fc = 0) OR
        (credit_amount_fc > 0 AND debit_amount_fc = 0)
    )
);
CREATE INDEX ix_journal_entry_lines_account ON acc.journal_entry_lines(account_id);

CREATE TABLE acc.journal_entry_line_details (   -- تخصیص تفصیلی‌های هر ردیف سند
    line_id            BIGINT   NOT NULL REFERENCES acc.journal_entry_lines(line_id),
    dimension_type_id  SMALLINT NOT NULL REFERENCES acc.detail_dimension_types(dimension_type_id),
    detail_account_id  INT      NOT NULL REFERENCES acc.detail_accounts(detail_account_id),
    CONSTRAINT pk_journal_entry_line_details PRIMARY KEY (line_id, dimension_type_id)
);
