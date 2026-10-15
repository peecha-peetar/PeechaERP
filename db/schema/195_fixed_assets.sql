-- پیچا R262: ماژولِ دارایی‌هایِ ثابت (schema fa) -- فقط افزودنی؛ هیچ جدولِ قبلی تغییر/حذف نمی‌شود.
-- ثبت‌هایِ مالی فقط از موتورِ سندِ حسابداریِ موجود (acc.journal_entries)؛ تغییرِ موجودی فقط از موتورِ انبار.
CREATE SCHEMA IF NOT EXISTS fa;

-- تنظیماتِ شرکت
CREATE TABLE IF NOT EXISTS fa.asset_settings (
    company_id                     INT           PRIMARY KEY REFERENCES core.companies(company_id),
    depreciation_start_rule        VARCHAR(20)   NOT NULL DEFAULT 'IN_SERVICE'
        CHECK (depreciation_start_rule IN ('IN_SERVICE', 'ACQUISITION', 'NEXT_MONTH', 'SPECIFIC')),
    depreciation_frequency         VARCHAR(10)   NOT NULL DEFAULT 'MONTHLY'
        CHECK (depreciation_frequency IN ('MONTHLY', 'QUARTERLY', 'YEARLY')),
    improvement_capitalize_min     NUMERIC(18,2) NOT NULL DEFAULT 0 CHECK (improvement_capitalize_min >= 0),
    require_cost_center            BOOLEAN       NOT NULL DEFAULT FALSE,
    large_improvement_approval_min NUMERIC(18,2) NULL,
    updated_at                     TIMESTAMP     NOT NULL DEFAULT now()
);

-- دفترهایِ استهلاک (فعلاً یک دفترِ اصلی؛ ساختار برایِ دفترِ مالیاتی/مدیریتی باز است)
CREATE TABLE IF NOT EXISTS fa.asset_books (
    book_id      SERIAL        PRIMARY KEY,
    company_id   INT           NOT NULL REFERENCES core.companies(company_id),
    code         VARCHAR(20)   NOT NULL,
    name         VARCHAR(100)  NOT NULL,
    is_primary   BOOLEAN       NOT NULL DEFAULT FALSE,
    posts_to_gl  BOOLEAN       NOT NULL DEFAULT TRUE,
    is_active    BOOLEAN       NOT NULL DEFAULT TRUE,
    UNIQUE (company_id, code)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_fa_asset_books_primary ON fa.asset_books (company_id) WHERE is_primary;

-- گروهِ حسابداریِ دارایی (زمین، ساختمان، ماشین‌آلات، ...) با پیش‌فرض‌ها و حساب‌ها
CREATE TABLE IF NOT EXISTS fa.asset_categories (
    category_id                     SERIAL        PRIMARY KEY,
    company_id                      INT           NOT NULL REFERENCES core.companies(company_id),
    code                            VARCHAR(30)   NOT NULL,
    name                            VARCHAR(150)  NOT NULL,
    default_method                  VARCHAR(25)   NOT NULL DEFAULT 'STRAIGHT_LINE'
        CHECK (default_method IN ('STRAIGHT_LINE', 'DECLINING_BALANCE', 'UNITS_OF_PRODUCTION', 'NONE')),
    default_life_months             INT           NULL CHECK (default_life_months IS NULL OR default_life_months > 0),
    default_residual_percent        NUMERIC(7,4)  NOT NULL DEFAULT 0 CHECK (default_residual_percent BETWEEN 0 AND 100),
    default_declining_rate          NUMERIC(9,6)  NULL CHECK (default_declining_rate IS NULL OR default_declining_rate > 0),
    cost_center_required            BOOLEAN       NOT NULL DEFAULT FALSE,
    default_cost_center_detail_account_id INT     NULL REFERENCES acc.detail_accounts(detail_account_id),
    asset_account_id                INT           NULL REFERENCES acc.chart_of_accounts(account_id),
    accumulated_depreciation_account_id INT       NULL REFERENCES acc.chart_of_accounts(account_id),
    depreciation_expense_account_id INT           NULL REFERENCES acc.chart_of_accounts(account_id),
    disposal_gain_account_id        INT           NULL REFERENCES acc.chart_of_accounts(account_id),
    disposal_loss_account_id        INT           NULL REFERENCES acc.chart_of_accounts(account_id),
    impairment_account_id           INT           NULL REFERENCES acc.chart_of_accounts(account_id),
    revaluation_account_id          INT           NULL REFERENCES acc.chart_of_accounts(account_id),
    cip_account_id                  INT           NULL REFERENCES acc.chart_of_accounts(account_id),
    maintenance_expense_account_id  INT           NULL REFERENCES acc.chart_of_accounts(account_id),
    is_active                       BOOLEAN       NOT NULL DEFAULT TRUE,
    UNIQUE (company_id, code)
);

-- گروه‌بندیِ مدیریتی/آزاد (مثلاً «خطِ تولیدِ A»)
CREATE TABLE IF NOT EXISTS fa.asset_groups (
    group_id     SERIAL        PRIMARY KEY,
    company_id   INT           NOT NULL REFERENCES core.companies(company_id),
    code         VARCHAR(30)   NOT NULL,
    name         VARCHAR(150)  NOT NULL,
    is_active    BOOLEAN       NOT NULL DEFAULT TRUE,
    UNIQUE (company_id, code)
);

-- محلِ دارایی: سایت/کارخانه ← ساختمان ← طبقه/اتاق ← خطِ تولید (جدا از مکان‌هایِ انبار)
CREATE TABLE IF NOT EXISTS fa.asset_locations (
    location_id     SERIAL        PRIMARY KEY,
    company_id      INT           NOT NULL REFERENCES core.companies(company_id),
    parent_location_id INT        NULL REFERENCES fa.asset_locations(location_id),
    code            VARCHAR(40)   NOT NULL,
    name            VARCHAR(150)  NOT NULL,
    location_type   VARCHAR(15)   NOT NULL DEFAULT 'ROOM'
        CHECK (location_type IN ('SITE', 'BUILDING', 'FLOOR', 'ROOM', 'LINE', 'OTHER')),
    branch_id       INT           NULL REFERENCES comm.branches(branch_id),
    is_active       BOOLEAN       NOT NULL DEFAULT TRUE,
    UNIQUE (company_id, code)
);

-- شناسنامهٔ دارایی (ارقامِ کش‌شده از دفترِ دارایی، برایِ دفترِ اصلی)
CREATE TABLE IF NOT EXISTS fa.assets (
    asset_id                    BIGSERIAL     PRIMARY KEY,
    company_id                  INT           NOT NULL REFERENCES core.companies(company_id),
    asset_code                  VARCHAR(40)   NOT NULL,
    name                        VARCHAR(200)  NOT NULL,
    category_id                 INT           NOT NULL REFERENCES fa.asset_categories(category_id),
    group_id                    INT           NULL REFERENCES fa.asset_groups(group_id),
    asset_type_code             VARCHAR(20)   NOT NULL DEFAULT 'EQUIPMENT'
        CHECK (asset_type_code IN ('LAND', 'BUILDING', 'MACHINE', 'EQUIPMENT', 'VEHICLE', 'IT', 'FURNITURE', 'TOOL',
                                   'INSTALLATION', 'INTANGIBLE', 'OTHER')),
    description                 TEXT          NULL,
    brand                       VARCHAR(100)  NULL,
    model                       VARCHAR(100)  NULL,
    serial_no                   VARCHAR(100)  NULL,
    part_no                     VARCHAR(100)  NULL,
    barcode                     VARCHAR(100)  NULL,
    parent_asset_id             BIGINT        NULL REFERENCES fa.assets(asset_id),
    status_code                 VARCHAR(20)   NOT NULL DEFAULT 'DRAFT'
        CHECK (status_code IN ('DRAFT', 'UNDER_CONSTRUCTION', 'ACQUIRED', 'CAPITALIZED', 'IN_SERVICE', 'UNDER_MAINTENANCE',
                               'TRANSFERRED', 'SUSPENDED', 'IMPAIRED', 'FULLY_DEPRECIATED', 'DISPOSED', 'SOLD', 'SCRAPPED',
                               'MERGED', 'SPLIT')),
    source_code                 VARCHAR(20)   NOT NULL DEFAULT 'MANUAL'
        CHECK (source_code IN ('PURCHASE', 'IMPORT', 'PRODUCTION', 'CAPITALIZATION', 'TRANSFER', 'CONSTRUCTION', 'OPENING',
                               'MANUAL', 'SPLIT', 'LEGACY')),
    acquisition_date            DATE          NULL,
    capitalization_date         DATE          NULL,
    in_service_date             DATE          NULL,
    depreciation_start_date     DATE          NULL,
    purchase_price              NUMERIC(18,2) NOT NULL DEFAULT 0 CHECK (purchase_price >= 0),
    residual_value              NUMERIC(18,2) NOT NULL DEFAULT 0 CHECK (residual_value >= 0),
    useful_life                 NUMERIC(14,2) NULL CHECK (useful_life IS NULL OR useful_life > 0),
    useful_life_unit            VARCHAR(10)   NOT NULL DEFAULT 'MONTH' CHECK (useful_life_unit IN ('MONTH', 'YEAR', 'HOUR', 'UNIT')),
    depreciation_method         VARCHAR(25)   NOT NULL DEFAULT 'STRAIGHT_LINE'
        CHECK (depreciation_method IN ('STRAIGHT_LINE', 'DECLINING_BALANCE', 'UNITS_OF_PRODUCTION', 'NONE')),
    declining_rate              NUMERIC(9,6)  NULL CHECK (declining_rate IS NULL OR declining_rate > 0),
    -- ارقامِ جاریِ دفترِ اصلی (جمعِ fa.asset_transactions؛ در همان تراکنش به‌روز می‌شوند)
    gross_cost                  NUMERIC(18,2) NOT NULL DEFAULT 0,
    accumulated_depreciation    NUMERIC(18,2) NOT NULL DEFAULT 0,
    accumulated_impairment      NUMERIC(18,2) NOT NULL DEFAULT 0,
    revaluation_surplus         NUMERIC(18,2) NOT NULL DEFAULT 0,
    units_consumed              NUMERIC(18,4) NOT NULL DEFAULT 0,
    branch_id                   INT           NULL REFERENCES comm.branches(branch_id),
    department_id               INT           NULL REFERENCES hr.organizational_units(org_unit_id),
    cost_center_detail_account_id INT         NULL REFERENCES acc.detail_accounts(detail_account_id),
    project_detail_account_id   INT           NULL REFERENCES acc.detail_accounts(detail_account_id),
    location_id                 INT           NULL REFERENCES fa.asset_locations(location_id),
    custodian_employee_id       INT           NULL REFERENCES hr.employees(employee_id),
    supplier_detail_account_id  INT           NULL REFERENCES acc.detail_accounts(detail_account_id),
    invoice_document_id         BIGINT        NULL REFERENCES comm.commercial_documents(document_id),
    invoice_reference           VARCHAR(100)  NULL,
    source_stock_line_id        BIGINT        NULL REFERENCES inv.stock_document_lines(line_id),
    capitalization_stock_document_id BIGINT   NULL REFERENCES inv.stock_documents(stock_document_id),
    legacy_item_id              INT           NULL REFERENCES inv.items(item_id),
    -- چندارزی: نقطهٔ توسعه (فعلاً فقط ثبت؛ ارقامِ دفتر به ارزِ پایه)
    currency_id                 INT           NULL REFERENCES core.currencies(currency_id),
    exchange_rate               NUMERIC(18,6) NULL,
    purchase_price_fc           NUMERIC(18,2) NULL,
    -- تولید
    is_production_machine       BOOLEAN       NOT NULL DEFAULT FALSE,
    work_center_code            VARCHAR(40)   NULL,
    production_line             VARCHAR(100)  NULL,
    machine_rate                NUMERIC(18,2) NULL,
    capacity_per_hour           NUMERIC(18,4) NULL,
    standard_hours              NUMERIC(14,2) NULL,
    notes                       TEXT          NULL,
    created_by_user_id          INT           NULL REFERENCES sec.users(user_id),
    created_at                  TIMESTAMP     NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMP     NOT NULL DEFAULT now(),
    UNIQUE (company_id, asset_code)
);
CREATE INDEX IF NOT EXISTS ix_fa_assets_category ON fa.assets (company_id, category_id);
CREATE INDEX IF NOT EXISTS ix_fa_assets_status ON fa.assets (company_id, status_code);
CREATE INDEX IF NOT EXISTS ix_fa_assets_location ON fa.assets (location_id);
CREATE INDEX IF NOT EXISTS ix_fa_assets_cost_center ON fa.assets (cost_center_detail_account_id);
CREATE INDEX IF NOT EXISTS ix_fa_assets_parent ON fa.assets (parent_asset_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_fa_assets_source_stock_line ON fa.assets (source_stock_line_id) WHERE source_stock_line_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_fa_assets_legacy_item ON fa.assets (legacy_item_id) WHERE legacy_item_id IS NOT NULL;

-- تنظیمِ استهلاکِ هر دارایی در دفترهایِ غیرِاصلی (چنددفتری؛ خالی = همان تنظیمِ خودِ دارایی)
CREATE TABLE IF NOT EXISTS fa.asset_book_settings (
    asset_id             BIGINT        NOT NULL REFERENCES fa.assets(asset_id),
    book_id              INT           NOT NULL REFERENCES fa.asset_books(book_id),
    depreciation_method  VARCHAR(25)   NOT NULL,
    useful_life          NUMERIC(14,2) NULL,
    residual_value       NUMERIC(18,2) NOT NULL DEFAULT 0,
    declining_rate       NUMERIC(9,6)  NULL,
    PRIMARY KEY (asset_id, book_id)
);

-- اجزایِ بهایِ تحصیل (قیمتِ خرید، حمل، نصب، گمرک، ...)
CREATE TABLE IF NOT EXISTS fa.asset_cost_items (
    cost_item_id          BIGSERIAL     PRIMARY KEY,
    asset_id              BIGINT        NOT NULL REFERENCES fa.assets(asset_id),
    cost_type             VARCHAR(20)   NOT NULL
        CHECK (cost_type IN ('PURCHASE', 'TRANSPORT', 'INSTALLATION', 'CUSTOMS', 'INSURANCE', 'COMMISSION', 'TESTING',
                             'SETUP', 'PROFESSIONAL', 'OTHER')),
    amount                NUMERIC(18,2) NOT NULL CHECK (amount > 0),
    offset_account_id     INT           NULL REFERENCES acc.chart_of_accounts(account_id),
    offset_detail_account_id INT        NULL REFERENCES acc.detail_accounts(detail_account_id),
    reference             VARCHAR(100)  NULL,
    journal_entry_id      INT           NULL REFERENCES acc.journal_entries(journal_entry_id),
    created_at            TIMESTAMP     NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_fa_asset_cost_items_asset ON fa.asset_cost_items (asset_id);

-- دفترِ دارایی: هر تغییرِ ارزش یک ردیف (فقط افزودنی)
CREATE TABLE IF NOT EXISTS fa.asset_transactions (
    txn_id                BIGSERIAL     PRIMARY KEY,
    company_id            INT           NOT NULL REFERENCES core.companies(company_id),
    asset_id              BIGINT        NOT NULL REFERENCES fa.assets(asset_id),
    book_id               INT           NOT NULL REFERENCES fa.asset_books(book_id),
    txn_type              VARCHAR(20)   NOT NULL
        CHECK (txn_type IN ('ACQUISITION', 'CAPITALIZATION', 'DEPRECIATION', 'IMPROVEMENT', 'IMPAIRMENT', 'REVALUATION',
                            'TRANSFER', 'RECLASS', 'SPLIT_OUT', 'SPLIT_IN', 'MERGE_OUT', 'MERGE_IN', 'DISPOSAL', 'SALE',
                            'SCRAP', 'REVERSAL', 'ADJUSTMENT', 'OPENING')),
    txn_date              DATE          NOT NULL,
    cost_delta            NUMERIC(18,2) NOT NULL DEFAULT 0,
    depreciation_delta    NUMERIC(18,2) NOT NULL DEFAULT 0,
    impairment_delta      NUMERIC(18,2) NOT NULL DEFAULT 0,
    revaluation_delta     NUMERIC(18,2) NOT NULL DEFAULT 0,
    units                 NUMERIC(18,4) NULL,
    description           VARCHAR(300)  NULL,
    reference             VARCHAR(100)  NULL,
    journal_entry_id      INT           NULL REFERENCES acc.journal_entries(journal_entry_id),
    source_type           VARCHAR(20)   NULL,
    source_id             BIGINT        NULL,
    reversed_txn_id       BIGINT        NULL REFERENCES fa.asset_transactions(txn_id),
    created_by_user_id    INT           NULL REFERENCES sec.users(user_id),
    created_at            TIMESTAMP     NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_fa_asset_txn_asset ON fa.asset_transactions (asset_id, txn_date, txn_id);
CREATE INDEX IF NOT EXISTS ix_fa_asset_txn_company ON fa.asset_transactions (company_id, txn_date);
CREATE INDEX IF NOT EXISTS ix_fa_asset_txn_source ON fa.asset_transactions (source_type, source_id);

CREATE OR REPLACE FUNCTION fa.prevent_asset_txn_modification() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'دفترِ دارایی تغییرناپذیر است: عملیاتِ % روی fa.asset_transactions مجاز نیست (اصلاح با ردیفِ برگشتی)', TG_OP;
END;
$$;
DROP TRIGGER IF EXISTS tr_fa_asset_txn_immutable ON fa.asset_transactions;
CREATE TRIGGER tr_fa_asset_txn_immutable
    BEFORE UPDATE OR DELETE ON fa.asset_transactions
    FOR EACH ROW EXECUTE FUNCTION fa.prevent_asset_txn_modification();

-- اجرایِ استهلاک: محاسبه ← بررسی ← تأیید ← ثبت؛ هر دوره/دفتر فقط یک اجرایِ فعال (ضدِ ثبتِ تکراری)
CREATE TABLE IF NOT EXISTS fa.depreciation_runs (
    run_id                BIGSERIAL     PRIMARY KEY,
    company_id            INT           NOT NULL REFERENCES core.companies(company_id),
    book_id               INT           NOT NULL REFERENCES fa.asset_books(book_id),
    period_code           VARCHAR(10)   NOT NULL,
    period_start          DATE          NOT NULL,
    period_end            DATE          NOT NULL,
    posting_date          DATE          NOT NULL,
    status_code           VARCHAR(12)   NOT NULL DEFAULT 'CALCULATED'
        CHECK (status_code IN ('CALCULATED', 'REVIEWED', 'APPROVED', 'POSTED', 'REVERSED')),
    asset_count           INT           NOT NULL DEFAULT 0,
    total_amount          NUMERIC(18,2) NOT NULL DEFAULT 0,
    journal_entry_id      INT           NULL REFERENCES acc.journal_entries(journal_entry_id),
    reversal_journal_entry_id INT       NULL REFERENCES acc.journal_entries(journal_entry_id),
    created_by_user_id    INT           NULL REFERENCES sec.users(user_id),
    reviewed_by_user_id   INT           NULL REFERENCES sec.users(user_id),
    approved_by_user_id   INT           NULL REFERENCES sec.users(user_id),
    posted_by_user_id     INT           NULL REFERENCES sec.users(user_id),
    created_at            TIMESTAMP     NOT NULL DEFAULT now(),
    posted_at             TIMESTAMP     NULL,
    CHECK (period_end >= period_start)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_fa_depr_runs_active_period ON fa.depreciation_runs (company_id, book_id, period_code)
    WHERE status_code <> 'REVERSED';

CREATE TABLE IF NOT EXISTS fa.depreciation_lines (
    depreciation_line_id  BIGSERIAL     PRIMARY KEY,
    run_id                BIGINT        NOT NULL REFERENCES fa.depreciation_runs(run_id),
    asset_id              BIGINT        NOT NULL REFERENCES fa.assets(asset_id),
    method                VARCHAR(25)   NOT NULL,
    opening_book_value    NUMERIC(18,2) NOT NULL,
    amount                NUMERIC(18,2) NOT NULL CHECK (amount >= 0),
    closing_book_value    NUMERIC(18,2) NOT NULL,
    units                 NUMERIC(18,4) NULL,
    cost_center_detail_account_id INT   NULL REFERENCES acc.detail_accounts(detail_account_id),
    expense_account_id    INT           NULL REFERENCES acc.chart_of_accounts(account_id),
    accumulated_account_id INT          NULL REFERENCES acc.chart_of_accounts(account_id),
    txn_id                BIGINT        NULL REFERENCES fa.asset_transactions(txn_id),
    UNIQUE (run_id, asset_id)
);
CREATE INDEX IF NOT EXISTS ix_fa_depr_lines_asset ON fa.depreciation_lines (asset_id);

-- کارکرد (ساعتِ ماشین/واحدِ تولید): مبنایِ استهلاکِ بر اساسِ تولید و بهایِ ماشین در تولید
CREATE TABLE IF NOT EXISTS fa.asset_usage (
    usage_id              BIGSERIAL     PRIMARY KEY,
    company_id            INT           NOT NULL REFERENCES core.companies(company_id),
    asset_id              BIGINT        NOT NULL REFERENCES fa.assets(asset_id),
    usage_date            DATE          NOT NULL,
    units                 NUMERIC(18,4) NOT NULL CHECK (units > 0),
    source_code           VARCHAR(15)   NOT NULL DEFAULT 'MANUAL' CHECK (source_code IN ('MANUAL', 'PRODUCTION', 'METER')),
    production_order_ref  VARCHAR(60)   NULL,
    note                  VARCHAR(300)  NULL,
    created_by_user_id    INT           NULL REFERENCES sec.users(user_id),
    created_at            TIMESTAMP     NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_fa_asset_usage_asset_date ON fa.asset_usage (asset_id, usage_date);

-- تخصیصِ بهایِ ماشین به سفارشِ تولید (برایِ موتورِ بهایِ تولیدِ آینده)
CREATE TABLE IF NOT EXISTS fa.machine_cost_allocations (
    allocation_id         BIGSERIAL     PRIMARY KEY,
    company_id            INT           NOT NULL REFERENCES core.companies(company_id),
    asset_id              BIGINT        NOT NULL REFERENCES fa.assets(asset_id),
    period_code           VARCHAR(10)   NOT NULL,
    production_order_ref  VARCHAR(60)   NOT NULL,
    hours                 NUMERIC(18,4) NOT NULL CHECK (hours > 0),
    rate_per_hour         NUMERIC(18,6) NOT NULL,
    amount                NUMERIC(18,2) NOT NULL,
    cost_center_detail_account_id INT   NULL REFERENCES acc.detail_accounts(detail_account_id),
    created_at            TIMESTAMP     NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_fa_machine_alloc_asset ON fa.machine_cost_allocations (asset_id, period_code);

-- رویدادها: انتقال، تغییرِ طبقه، بهسازی، تعمیر، کاهشِ ارزش، تجدیدِ ارزیابی، فروش، اسقاط، تقسیم، ادغام
CREATE TABLE IF NOT EXISTS fa.asset_events (
    event_id              BIGSERIAL     PRIMARY KEY,
    company_id            INT           NOT NULL REFERENCES core.companies(company_id),
    asset_id              BIGINT        NOT NULL REFERENCES fa.assets(asset_id),
    event_type            VARCHAR(20)   NOT NULL
        CHECK (event_type IN ('CAPITALIZATION', 'TRANSFER', 'RECLASS', 'IMPROVEMENT', 'MAINTENANCE', 'IMPAIRMENT', 'REVALUATION',
                              'SALE', 'SCRAP', 'DONATION', 'WRITE_OFF', 'SPLIT', 'MERGE', 'STATUS')),
    event_date            DATE          NOT NULL,
    status_code           VARCHAR(20)   NOT NULL DEFAULT 'POSTED'
        CHECK (status_code IN ('DRAFT', 'PENDING_APPROVAL', 'APPROVED', 'POSTED', 'REJECTED', 'CANCELLED')),
    amount                NUMERIC(18,2) NULL,
    proceeds              NUMERIC(18,2) NULL,
    previous_book_value   NUMERIC(18,2) NULL,
    new_value             NUMERIC(18,2) NULL,
    gain_loss             NUMERIC(18,2) NULL,
    reason                VARCHAR(300)  NULL,
    condition_note        VARCHAR(300)  NULL,
    details               JSONB         NULL,
    offset_account_id     INT           NULL REFERENCES acc.chart_of_accounts(account_id),
    counterparty_detail_account_id INT  NULL REFERENCES acc.detail_accounts(detail_account_id),
    journal_entry_id      INT           NULL REFERENCES acc.journal_entries(journal_entry_id),
    idempotency_key       VARCHAR(80)   NULL,
    created_by_user_id    INT           NULL REFERENCES sec.users(user_id),
    approved_by_user_id   INT           NULL REFERENCES sec.users(user_id),
    created_at            TIMESTAMP     NOT NULL DEFAULT now(),
    posted_at             TIMESTAMP     NULL
);
CREATE INDEX IF NOT EXISTS ix_fa_asset_events_asset ON fa.asset_events (asset_id, event_date);
CREATE UNIQUE INDEX IF NOT EXISTS ux_fa_asset_events_idem ON fa.asset_events (company_id, idempotency_key) WHERE idempotency_key IS NOT NULL;

-- دارایی در جریانِ تکمیل
CREATE TABLE IF NOT EXISTS fa.cip_projects (
    cip_id                BIGSERIAL     PRIMARY KEY,
    company_id            INT           NOT NULL REFERENCES core.companies(company_id),
    code                  VARCHAR(40)   NOT NULL,
    name                  VARCHAR(200)  NOT NULL,
    category_id           INT           NOT NULL REFERENCES fa.asset_categories(category_id),
    start_date            DATE          NOT NULL,
    status_code           VARCHAR(12)   NOT NULL DEFAULT 'OPEN' CHECK (status_code IN ('OPEN', 'CAPITALIZED', 'CANCELLED')),
    cost_center_detail_account_id INT   NULL REFERENCES acc.detail_accounts(detail_account_id),
    project_detail_account_id INT       NULL REFERENCES acc.detail_accounts(detail_account_id),
    capitalized_asset_id  BIGINT        NULL REFERENCES fa.assets(asset_id),
    capitalized_at        DATE          NULL,
    journal_entry_id      INT           NULL REFERENCES acc.journal_entries(journal_entry_id),
    notes                 TEXT          NULL,
    created_by_user_id    INT           NULL REFERENCES sec.users(user_id),
    created_at            TIMESTAMP     NOT NULL DEFAULT now(),
    UNIQUE (company_id, code)
);

CREATE TABLE IF NOT EXISTS fa.cip_costs (
    cip_cost_id           BIGSERIAL     PRIMARY KEY,
    cip_id                BIGINT        NOT NULL REFERENCES fa.cip_projects(cip_id),
    cost_date             DATE          NOT NULL,
    cost_type             VARCHAR(20)   NOT NULL
        CHECK (cost_type IN ('MATERIAL', 'LABOR', 'INSTALLATION', 'TRANSPORT', 'ENGINEERING', 'OTHER')),
    amount                NUMERIC(18,2) NOT NULL CHECK (amount > 0),
    description           VARCHAR(300)  NULL,
    offset_account_id     INT           NULL REFERENCES acc.chart_of_accounts(account_id),
    offset_detail_account_id INT        NULL REFERENCES acc.detail_accounts(detail_account_id),
    stock_document_id     BIGINT        NULL REFERENCES inv.stock_documents(stock_document_id),
    journal_entry_id      INT           NULL REFERENCES acc.journal_entries(journal_entry_id),
    created_by_user_id    INT           NULL REFERENCES sec.users(user_id),
    created_at            TIMESTAMP     NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_fa_cip_costs_cip ON fa.cip_costs (cip_id);

-- شمارشِ فیزیکی
CREATE TABLE IF NOT EXISTS fa.physical_counts (
    count_id              BIGSERIAL     PRIMARY KEY,
    company_id            INT           NOT NULL REFERENCES core.companies(company_id),
    code                  VARCHAR(40)   NOT NULL,
    count_date            DATE          NOT NULL,
    location_id           INT           NULL REFERENCES fa.asset_locations(location_id),
    status_code           VARCHAR(10)   NOT NULL DEFAULT 'OPEN' CHECK (status_code IN ('OPEN', 'CLOSED', 'CANCELLED')),
    notes                 VARCHAR(300)  NULL,
    created_by_user_id    INT           NULL REFERENCES sec.users(user_id),
    created_at            TIMESTAMP     NOT NULL DEFAULT now(),
    closed_at             TIMESTAMP     NULL,
    UNIQUE (company_id, code)
);

CREATE TABLE IF NOT EXISTS fa.physical_count_items (
    count_item_id         BIGSERIAL     PRIMARY KEY,
    count_id              BIGINT        NOT NULL REFERENCES fa.physical_counts(count_id),
    asset_id              BIGINT        NOT NULL REFERENCES fa.assets(asset_id),
    expected_location_id  INT           NULL REFERENCES fa.asset_locations(location_id),
    expected_custodian_employee_id INT  NULL REFERENCES hr.employees(employee_id),
    found_location_id     INT           NULL REFERENCES fa.asset_locations(location_id),
    found_custodian_employee_id INT     NULL REFERENCES hr.employees(employee_id),
    result_code           VARCHAR(20)   NOT NULL DEFAULT 'PENDING'
        CHECK (result_code IN ('PENDING', 'FOUND', 'MISSING', 'MOVED', 'DAMAGED', 'WRONG_LOCATION', 'WRONG_CUSTODIAN', 'UNEXPECTED')),
    scan_method           VARCHAR(10)   NULL CHECK (scan_method IS NULL OR scan_method IN ('MANUAL', 'BARCODE', 'QR', 'MOBILE')),
    is_damaged            BOOLEAN       NOT NULL DEFAULT FALSE,
    scanned_at            TIMESTAMP     NULL,
    note                  VARCHAR(300)  NULL,
    UNIQUE (count_id, asset_id)
);

-- گارانتی و بیمه
CREATE TABLE IF NOT EXISTS fa.asset_warranties (
    warranty_id           BIGSERIAL     PRIMARY KEY,
    asset_id              BIGINT        NOT NULL REFERENCES fa.assets(asset_id),
    warranty_type         VARCHAR(60)   NULL,
    supplier_detail_account_id INT      NULL REFERENCES acc.detail_accounts(detail_account_id),
    contract_no           VARCHAR(60)   NULL,
    start_date            DATE          NOT NULL,
    end_date              DATE          NOT NULL,
    note                  VARCHAR(300)  NULL,
    CHECK (end_date >= start_date)
);
CREATE INDEX IF NOT EXISTS ix_fa_warranties_end ON fa.asset_warranties (end_date);

CREATE TABLE IF NOT EXISTS fa.asset_insurances (
    insurance_id          BIGSERIAL     PRIMARY KEY,
    asset_id              BIGINT        NOT NULL REFERENCES fa.assets(asset_id),
    insurer_name          VARCHAR(150)  NOT NULL,
    policy_no             VARCHAR(60)   NULL,
    start_date            DATE          NOT NULL,
    end_date              DATE          NOT NULL,
    premium               NUMERIC(18,2) NULL,
    coverage              VARCHAR(300)  NULL,
    insured_value         NUMERIC(18,2) NULL,
    CHECK (end_date >= start_date)
);
CREATE INDEX IF NOT EXISTS ix_fa_insurances_end ON fa.asset_insurances (end_date);

-- نوعِ سندِ حسابداریِ «دارایی ثابت» (هم‌الگو با INVENTORY/COMMERCIAL) برایِ تفکیک در فهرست/گزارش
INSERT INTO acc.journal_entry_types (entry_type_id, code) VALUES
    (11, 'FIXED_ASSET')
ON CONFLICT (entry_type_id) DO NOTHING;
