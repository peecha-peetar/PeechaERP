-- R314: افتتاحیه و انتقال اطلاعات از سیستم قبلی.
-- هستهٔ opn فقط فرایند را مدیریت می‌کند (فرایند، ماژول، فایل، ردیف اعتبارسنجی‌شده، زیرعملیات ثبت، رویداد)؛
-- دادهٔ نهایی با سرویس رسمی هر ماژول در جدول‌های همان ماژول ثبت می‌شود.
CREATE SCHEMA IF NOT EXISTS opn;

CREATE TABLE opn.settings (
    company_id             INT           PRIMARY KEY REFERENCES core.companies(company_id),
    difference_policy      VARCHAR(10)   NOT NULL DEFAULT 'BLOCK' CHECK (difference_policy IN ('BLOCK', 'APPROVAL')),
    difference_account_id  INT           NULL REFERENCES acc.chart_of_accounts(account_id),
    updated_by_user_id     INT           NULL REFERENCES sec.users(user_id),
    updated_at             TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE TABLE opn.runs (
    run_id                 SERIAL        PRIMARY KEY,
    company_id             INT           NOT NULL REFERENCES core.companies(company_id),
    fiscal_year_id         INT           NOT NULL REFERENCES acc.fiscal_years(fiscal_year_id),
    code                   VARCHAR(30)   NOT NULL,
    title                  VARCHAR(200)  NOT NULL,
    kind_code              VARCHAR(12)   NOT NULL DEFAULT 'ORIGINAL' CHECK (kind_code IN ('ORIGINAL', 'CORRECTION')),
    corrects_run_id        INT           NULL REFERENCES opn.runs(run_id),
    balance_date           DATE          NOT NULL,
    go_live_date           DATE          NOT NULL,
    currency_id            INT           NOT NULL REFERENCES core.currencies(currency_id),
    status_code            VARCHAR(12)   NOT NULL DEFAULT 'DRAFT'
        CHECK (status_code IN ('DRAFT', 'IN_PROGRESS', 'POSTING', 'POSTED', 'LOCKED', 'CANCELLED')),
    notes                  TEXT          NULL,
    created_by_user_id     INT           NULL REFERENCES sec.users(user_id),
    created_at             TIMESTAMPTZ   NOT NULL DEFAULT now(),
    posted_by_user_id      INT           NULL REFERENCES sec.users(user_id),
    posted_at              TIMESTAMPTZ   NULL,
    locked_by_user_id      INT           NULL REFERENCES sec.users(user_id),
    locked_at              TIMESTAMPTZ   NULL,
    cancel_reason          TEXT          NULL,
    CHECK (go_live_date > balance_date),
    CHECK ((kind_code = 'CORRECTION') = (corrects_run_id IS NOT NULL)),
    UNIQUE (company_id, code)
);
-- یک افتتاحیهٔ اصلی برای هر شرکت و سال مالی؛ تغییر بعدی فقط با فرایند اصلاحی
CREATE UNIQUE INDEX ux_opn_runs_original ON opn.runs (company_id, fiscal_year_id)
    WHERE kind_code = 'ORIGINAL' AND status_code <> 'CANCELLED';

CREATE TABLE opn.run_modules (
    run_id                 INT           NOT NULL REFERENCES opn.runs(run_id) ON DELETE CASCADE,
    module_code            VARCHAR(20)   NOT NULL
        CHECK (module_code IN ('GL', 'INVENTORY', 'RECEIVABLES', 'PAYABLES', 'CHEQUES', 'FIXED_ASSETS', 'WIP')),
    status_code            VARCHAR(12)   NOT NULL DEFAULT 'NOT_STARTED'
        CHECK (status_code IN ('NOT_STARTED', 'ENTERING', 'HAS_ERRORS', 'READY', 'APPROVED', 'POSTING', 'POSTED', 'LOCKED')),
    owner_user_id          INT           NULL REFERENCES sec.users(user_id),
    approver_user_id       INT           NULL REFERENCES sec.users(user_id),
    submitted_by_user_id   INT           NULL REFERENCES sec.users(user_id),
    submitted_at           TIMESTAMPTZ   NULL,
    approved_by_user_id    INT           NULL REFERENCES sec.users(user_id),
    approved_at            TIMESTAMPTZ   NULL,
    posted_at              TIMESTAMPTZ   NULL,
    reject_reason          TEXT          NULL,
    PRIMARY KEY (run_id, module_code)
);

CREATE TABLE opn.import_batches (
    batch_id               SERIAL        PRIMARY KEY,
    run_id                 INT           NOT NULL REFERENCES opn.runs(run_id) ON DELETE CASCADE,
    module_code            VARCHAR(20)   NOT NULL,
    version_no             INT           NOT NULL,
    source_code            VARCHAR(8)    NOT NULL DEFAULT 'FILE' CHECK (source_code IN ('FILE', 'FORM')),
    file_name              VARCHAR(255)  NULL,
    file_hash              CHAR(64)      NULL,
    row_count              INT           NOT NULL DEFAULT 0,
    valid_count            INT           NOT NULL DEFAULT 0,
    invalid_count          INT           NOT NULL DEFAULT 0,
    posted_skipped         INT           NOT NULL DEFAULT 0,
    uploaded_by_user_id    INT           NULL REFERENCES sec.users(user_id),
    uploaded_at            TIMESTAMPTZ   NOT NULL DEFAULT now(),
    UNIQUE (run_id, module_code, version_no)
);
-- همان فایل (همان هش) دو بار وارد نمی‌شود
CREATE UNIQUE INDEX ux_opn_batches_hash ON opn.import_batches (run_id, module_code, file_hash) WHERE file_hash IS NOT NULL;

CREATE TABLE opn.staged_rows (
    row_id                 BIGSERIAL     PRIMARY KEY,
    run_id                 INT           NOT NULL REFERENCES opn.runs(run_id) ON DELETE CASCADE,
    module_code            VARCHAR(20)   NOT NULL,
    row_key                VARCHAR(300)  NOT NULL,
    batch_id               INT           NULL REFERENCES opn.import_batches(batch_id),
    source_row_no          INT           NULL,
    payload                JSONB         NOT NULL,
    resolved               JSONB         NULL,
    status_code            VARCHAR(10)   NOT NULL DEFAULT 'INVALID'
        CHECK (status_code IN ('VALID', 'INVALID', 'POSTED', 'FAILED', 'REVERSED')),
    errors                 JSONB         NULL,
    warnings               JSONB         NULL,
    amount                 NUMERIC(18,2) NOT NULL DEFAULT 0,
    target_type            VARCHAR(30)   NULL,
    target_id              BIGINT        NULL,
    journal_entry_id       INT           NULL REFERENCES acc.journal_entries(journal_entry_id),
    posted_at              TIMESTAMPTZ   NULL,
    updated_by_user_id     INT           NULL REFERENCES sec.users(user_id),
    updated_at             TIMESTAMPTZ   NOT NULL DEFAULT now(),
    UNIQUE (run_id, module_code, row_key)
);
CREATE INDEX ix_opn_rows_status ON opn.staged_rows (run_id, module_code, status_code);

CREATE TABLE opn.postings (
    posting_id             BIGSERIAL     PRIMARY KEY,
    run_id                 INT           NOT NULL REFERENCES opn.runs(run_id) ON DELETE CASCADE,
    module_code            VARCHAR(20)   NOT NULL,
    step_key               VARCHAR(200)  NOT NULL,
    status_code            VARCHAR(10)   NOT NULL DEFAULT 'PENDING' CHECK (status_code IN ('PENDING', 'DONE', 'FAILED', 'REVERSED')),
    target_type            VARCHAR(30)   NULL,
    target_id              BIGINT        NULL,
    journal_entry_id       INT           NULL REFERENCES acc.journal_entries(journal_entry_id),
    reversal_journal_entry_id INT        NULL REFERENCES acc.journal_entries(journal_entry_id),
    row_count              INT           NOT NULL DEFAULT 0,
    amount                 NUMERIC(18,2) NOT NULL DEFAULT 0,
    message                TEXT          NULL,
    attempts               INT           NOT NULL DEFAULT 0,
    user_id                INT           NULL REFERENCES sec.users(user_id),
    started_at             TIMESTAMPTZ   NOT NULL DEFAULT now(),
    finished_at            TIMESTAMPTZ   NULL,
    UNIQUE (run_id, step_key)
);

CREATE TABLE opn.events (
    event_id               BIGSERIAL     PRIMARY KEY,
    run_id                 INT           NOT NULL REFERENCES opn.runs(run_id) ON DELETE CASCADE,
    module_code            VARCHAR(20)   NULL,
    event_code             VARCHAR(20)   NOT NULL,
    user_id                INT           NULL REFERENCES sec.users(user_id),
    created_at             TIMESTAMPTZ   NOT NULL DEFAULT now(),
    comment                TEXT          NULL,
    details                JSONB         NULL
);
CREATE INDEX ix_opn_events_run ON opn.events (run_id, created_at);

-- ردیف ثبت‌شده دست نمی‌خورد؛ فقط با برگشت کنترل‌شده «برگشت‌خورده» می‌شود
CREATE OR REPLACE FUNCTION opn.row_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.status_code = 'POSTED' THEN
            RAISE EXCEPTION 'OPN_LOCKED: ردیف ثبت‌شدهٔ افتتاحیه حذف نمی‌شود؛ افتتاحیهٔ اصلاحی بسازید';
        END IF;
        RETURN OLD;
    END IF;
    IF OLD.status_code = 'POSTED' AND (NEW.status_code NOT IN ('POSTED', 'REVERSED')
            OR NEW.payload IS DISTINCT FROM OLD.payload OR NEW.row_key IS DISTINCT FROM OLD.row_key
            OR NEW.amount IS DISTINCT FROM OLD.amount) THEN
        RAISE EXCEPTION 'OPN_LOCKED: ردیف ثبت‌شدهٔ افتتاحیه قابل تغییر نیست؛ افتتاحیهٔ اصلاحی بسازید';
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;
CREATE TRIGGER tr_opn_rows_guard BEFORE UPDATE OR DELETE ON opn.staged_rows
    FOR EACH ROW EXECUTE FUNCTION opn.row_guard();

-- سند باز افتتاحیهٔ دریافتنی/پرداختنی (فقط سربرگ؛ تسویه و گزارش سنی آن را مثل فاکتور ثبت‌شده می‌شناسند)
ALTER TABLE comm.commercial_documents
    DROP CONSTRAINT commercial_documents_document_type_code_check;
ALTER TABLE comm.commercial_documents
    ADD CONSTRAINT commercial_documents_document_type_code_check
    CHECK (document_type_code IN (
        'SALES_ORDER', 'SALES_PROFORMA', 'SALES_INVOICE', 'SALES_RETURN',
        'PURCHASE_ORDER', 'PURCHASE_PROFORMA', 'PURCHASE_INVOICE', 'PURCHASE_RETURN',
        'CONSIGNMENT_OUT', 'CONSIGNMENT_IN', 'OPENING_RECEIVABLE', 'OPENING_PAYABLE'
    ));

-- کالای در جریان ساخت افتتاحیهٔ هر دستور تولید
DO $$
DECLARE
    c TEXT;
BEGIN
    SELECT conname INTO c FROM pg_constraint
     WHERE conrelid = 'prd.order_transactions'::regclass AND contype = 'c' AND pg_get_constraintdef(oid) LIKE '%txn_type%';
    IF c IS NOT NULL THEN
        EXECUTE format('ALTER TABLE prd.order_transactions DROP CONSTRAINT %I', c);
    END IF;
END $$;
ALTER TABLE prd.order_transactions ADD CONSTRAINT order_transactions_txn_type_check
    CHECK (txn_type IN ('ISSUE', 'RETURN', 'RECEIPT', 'BY_PRODUCT', 'CO_PRODUCT', 'SCRAP', 'LABOR', 'MACHINE', 'OVERHEAD',
                        'VARIANCE', 'REVERSAL', 'OPENING'));

INSERT INTO inv.feature_definitions (feature_code, name, category, requires_feature_code, description) VALUES
    ('OPN_SELF_APPROVAL', 'اجازهٔ تأیید افتتاحیه توسط واردکنندهٔ اطلاعات', 'OPENING', NULL,
     'برای شرکت‌های کوچک: کسی که اطلاعات افتتاحیهٔ یک ماژول را وارد کرده می‌تواند خودش آن را تأیید کند. بدون این کلید واردکننده و تأییدکننده باید دو نفر متفاوت باشند.')
ON CONFLICT (feature_code) DO NOTHING;
