-- پیچا | گزارش‌سازِ کامل (ستون+ردیف، هم‌الگو با گزارش‌هایِ استاندارد) — یک
-- ابزارِ واحد که هم گزارشِ تراکنشی (سطحِ سطرِ سند، مثلِ دفترِ روزنامه/کل با
-- ستون‌هایِ دلخواه) و هم گزارشِ خلاصه/تجمیعیِ چندستونی (رویِ ردیف‌هایِ همان
-- الگویِ حسابی که در «طراحیِ الگویِ گزارش» ساخته می‌شود، با چند ستونِ
-- مقدار/دوره) می‌سازد.
-- پیش‌نیاز: 003_accounting_core.sql، 016_statement_templates.sql

CREATE TABLE acc.report_templates (
    report_template_id SERIAL      NOT NULL PRIMARY KEY,
    company_id          INT        NOT NULL REFERENCES core.companies(company_id),
    name                 VARCHAR(200) NOT NULL,
    report_kind          VARCHAR(10) NOT NULL CHECK (report_kind IN ('DETAIL', 'SUMMARY')),
    -- فقط برایِ DETAIL: زیرِ هر حساب یک ردیفِ جمعِ فرعی (مانده‌ی رواگرد) نشان بده.
    group_by_account     BOOLEAN    NOT NULL DEFAULT FALSE,
    -- فقط برایِ SUMMARY: ردیف‌ها از رویِ همین الگویِ حسابیِ موجود خوانده می‌شوند؛
    -- گزارش‌سازِ کامل فقط «ستون»‌هایِ (دوره/نوعِ مقدار) را رویِ همان ردیف‌ها اضافه می‌کند.
    statement_template_id INT      REFERENCES acc.statement_templates(template_id),
    display_order         INT      NOT NULL DEFAULT 0,
    CONSTRAINT chk_report_templates_kind CHECK (
        (report_kind = 'DETAIL' AND statement_template_id IS NULL)
        OR (report_kind = 'SUMMARY' AND statement_template_id IS NOT NULL AND group_by_account = FALSE)
    )
);

CREATE TABLE acc.report_template_columns (
    column_id           SERIAL   NOT NULL PRIMARY KEY,
    report_template_id  INT      NOT NULL REFERENCES acc.report_templates(report_template_id) ON DELETE CASCADE,
    column_order         INT      NOT NULL,
    label                 VARCHAR(200) NOT NULL,
    -- فقط برایِ DETAIL: یکی از فیلدهایِ ثابتِ کاتالوگ (کدِ گزارش‌ساز، نه دیتابیس).
    field_code            VARCHAR(30),
    -- فقط برایِ SUMMARY: OPENING_BALANCE | PERIOD_DEBIT | PERIOD_CREDIT | CLOSING_BALANCE | NATURAL_BALANCE
    measure_code          VARCHAR(20),
    -- فقط برایِ SUMMARY، اختیاری: اگر خالی باشد، بازه‌یِ تاریخِ اجرایِ گزارش استفاده می‌شود.
    date_from_override    DATE,
    date_to_override      DATE
);
CREATE INDEX ix_report_template_columns_template ON acc.report_template_columns(report_template_id);

-- فقط برایِ DETAIL: کدام حساب‌ها در گزارش بیایند — هم‌الگو با انتخاب‌گرِ
-- ACCOUNT/RANGE/CATEGORYِ گزارش‌سازِ الگویِ حسابی (018)؛ چند سطر با هم OR
-- می‌شوند؛ اگر هیچ سطری نباشد یعنی همه‌یِ حساب‌هایِ قابلِ ثبت.
CREATE TABLE acc.report_template_account_filters (
    filter_id           SERIAL   NOT NULL PRIMARY KEY,
    report_template_id  INT      NOT NULL REFERENCES acc.report_templates(report_template_id) ON DELETE CASCADE,
    selector_type        VARCHAR(10) NOT NULL CHECK (selector_type IN ('ACCOUNT', 'RANGE', 'CATEGORY')),
    account_id            INT      REFERENCES acc.chart_of_accounts(account_id),
    account_level         SMALLINT CHECK (account_level BETWEEN 1 AND 4),
    code_from             VARCHAR(50),
    code_to               VARCHAR(50),
    category_code         VARCHAR(20) CHECK (category_code IN ('ASSET', 'LIABILITY', 'EQUITY', 'REVENUE', 'EXPENSE')),
    CONSTRAINT chk_report_template_account_filters_selector CHECK (
        (selector_type = 'ACCOUNT' AND account_id IS NOT NULL AND account_level IS NULL
            AND code_from IS NULL AND code_to IS NULL AND category_code IS NULL)
        OR (selector_type = 'RANGE' AND account_id IS NULL AND account_level IS NOT NULL
            AND code_from IS NOT NULL AND code_to IS NOT NULL AND category_code IS NULL)
        OR (selector_type = 'CATEGORY' AND account_id IS NULL AND account_level IS NOT NULL
            AND category_code IS NOT NULL AND code_from IS NULL AND code_to IS NULL)
    )
);
CREATE INDEX ix_report_template_account_filters_template ON acc.report_template_account_filters(report_template_id);
