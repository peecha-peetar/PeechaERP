-- R313: بودجه‌ریزی و کنترل بودجه و تعهدات. بودجهٔ سادهٔ خرید (comm.purchase_budgets، R243) دست‌نخورده می‌ماند.
-- مصرف همیشه از اسناد خرید و دفتر کل می‌آید؛ bud.consumption_entries فقط «تفاوت» وضع سند را با برچسب رویداد
-- نگه می‌دارد (برای قفل هم‌زمانی، مبلغ آزادشده و ردپای اصلاح سند) و با «بازسازی» با اسناد تطبیق داده می‌شود.
-- برگشت: db/rollback/223_budgeting_down.sql

CREATE SCHEMA IF NOT EXISTS bud;

-- سیاست کنترل هر شرکت (هر ردیف بودجه می‌تواند سیاست و درصد هشدار خودش را داشته باشد)
CREATE TABLE bud.settings (
    company_id          INT          PRIMARY KEY REFERENCES core.companies(company_id),
    policy_code         VARCHAR(10)  NOT NULL DEFAULT 'WARN' CHECK (policy_code IN ('WARN', 'APPROVAL', 'BLOCK')),
    warn_percent        NUMERIC(5,2) NOT NULL DEFAULT 90 CHECK (warn_percent > 0 AND warn_percent <= 100),
    control_level       VARCHAR(12)  NOT NULL DEFAULT 'ANNUAL' CHECK (control_level IN ('ANNUAL', 'CUMULATIVE')),
    unbudgeted_policy   VARCHAR(10)  NOT NULL DEFAULT 'ALLOW' CHECK (unbudgeted_policy IN ('ALLOW', 'WARN', 'BLOCK')),
    updated_by_user_id  INT          NULL REFERENCES sec.users(user_id),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- بودجه: یک سال مالی، با نوع دوره
CREATE TABLE bud.budgets (
    budget_id           SERIAL       PRIMARY KEY,
    company_id          INT          NOT NULL REFERENCES core.companies(company_id),
    fiscal_year_id      INT          NOT NULL REFERENCES acc.fiscal_years(fiscal_year_id),
    code                VARCHAR(30)  NOT NULL,
    name                VARCHAR(150) NOT NULL,
    period_type         VARCHAR(10)  NOT NULL CHECK (period_type IN ('YEAR', 'QUARTER', 'MONTH')),
    date_from           DATE         NOT NULL,
    date_to             DATE         NOT NULL,
    owner_user_id       INT          NULL REFERENCES sec.users(user_id),
    description         TEXT         NULL,
    is_active           BOOLEAN      NOT NULL DEFAULT TRUE,
    created_by_user_id  INT          NULL REFERENCES sec.users(user_id),
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CHECK (date_to >= date_from),
    UNIQUE (company_id, code)
);

CREATE TABLE bud.budget_periods (
    period_id           SERIAL       PRIMARY KEY,
    budget_id           INT          NOT NULL REFERENCES bud.budgets(budget_id) ON DELETE CASCADE,
    period_no           SMALLINT     NOT NULL CHECK (period_no >= 1),
    date_from           DATE         NOT NULL,
    date_to             DATE         NOT NULL,
    label               VARCHAR(40)  NOT NULL,
    is_closed           BOOLEAN      NOT NULL DEFAULT FALSE,
    closed_by_user_id   INT          NULL REFERENCES sec.users(user_id),
    closed_at           TIMESTAMPTZ  NULL,
    close_note          TEXT         NULL,
    CHECK (date_to >= date_from),
    UNIQUE (budget_id, period_no)
);

-- کلید کنترل: ترکیب ثابت ابعاد در یک بودجه (میان نسخه‌ها مشترک؛ مصرف به کلید وصل است، نه به ردیف نسخه)
CREATE TABLE bud.control_keys (
    key_id                          SERIAL      PRIMARY KEY,
    budget_id                       INT         NOT NULL REFERENCES bud.budgets(budget_id) ON DELETE CASCADE,
    basis_code                      VARCHAR(10) NOT NULL CHECK (basis_code IN ('PURCHASE', 'ACCOUNT')),
    account_id                      INT         NULL REFERENCES acc.chart_of_accounts(account_id),
    cost_center_detail_account_id   INT         NULL REFERENCES acc.detail_accounts(detail_account_id),
    project_detail_account_id       INT         NULL REFERENCES acc.detail_accounts(detail_account_id),
    branch_id                       INT         NULL REFERENCES comm.branches(branch_id),
    org_unit_id                     INT         NULL REFERENCES hr.organizational_units(org_unit_id),
    category_id                     INT         NULL REFERENCES inv.item_categories(category_id),
    purchase_type_id                INT         NULL REFERENCES comm.purchase_types(purchase_type_id),
    CHECK (basis_code = 'PURCHASE' OR account_id IS NOT NULL),
    CHECK (basis_code = 'ACCOUNT' OR account_id IS NULL)
);
CREATE UNIQUE INDEX ux_bud_control_keys_dims ON bud.control_keys (
    budget_id, basis_code, COALESCE(account_id, 0), COALESCE(cost_center_detail_account_id, 0),
    COALESCE(project_detail_account_id, 0), COALESCE(branch_id, 0), COALESCE(org_unit_id, 0), COALESCE(category_id, 0),
    COALESCE(purchase_type_id, 0));

-- نسخه: اولیه، اصلاحیه یا تکمیلی؛ «نسخهٔ نهایی مصوب» همان نسخهٔ منتشرشده است
CREATE TABLE bud.budget_versions (
    version_id            SERIAL       PRIMARY KEY,
    budget_id             INT          NOT NULL REFERENCES bud.budgets(budget_id) ON DELETE CASCADE,
    version_no            SMALLINT     NOT NULL CHECK (version_no >= 1),
    kind_code             VARCHAR(12)  NOT NULL CHECK (kind_code IN ('ORIGINAL', 'AMENDMENT', 'SUPPLEMENT')),
    status_code           VARCHAR(12)  NOT NULL DEFAULT 'DRAFT'
        CHECK (status_code IN ('DRAFT', 'SUBMITTED', 'REVIEWED', 'APPROVED', 'PUBLISHED', 'SUPERSEDED', 'REJECTED', 'CANCELLED')),
    based_on_version_id   INT          NULL REFERENCES bud.budget_versions(version_id),
    title                 VARCHAR(150) NOT NULL,
    description           TEXT         NULL,
    valid_from            DATE         NOT NULL,
    valid_to              DATE         NOT NULL,
    prepared_by_user_id   INT          NULL REFERENCES sec.users(user_id),
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),
    submitted_by_user_id  INT          NULL REFERENCES sec.users(user_id),
    submitted_at          TIMESTAMPTZ  NULL,
    reviewed_by_user_id   INT          NULL REFERENCES sec.users(user_id),
    reviewed_at           TIMESTAMPTZ  NULL,
    approved_by_user_id   INT          NULL REFERENCES sec.users(user_id),
    approved_at           TIMESTAMPTZ  NULL,
    published_by_user_id  INT          NULL REFERENCES sec.users(user_id),
    published_at          TIMESTAMPTZ  NULL,
    reject_reason         TEXT         NULL,
    CHECK (valid_to >= valid_from),
    UNIQUE (budget_id, version_no)
);
CREATE UNIQUE INDEX ux_bud_versions_published ON bud.budget_versions (budget_id) WHERE status_code = 'PUBLISHED';
CREATE UNIQUE INDEX ux_bud_versions_open ON bud.budget_versions (budget_id)
    WHERE status_code IN ('DRAFT', 'SUBMITTED', 'REVIEWED', 'APPROVED', 'REJECTED');

CREATE TABLE bud.budget_lines (
    line_id              SERIAL        PRIMARY KEY,
    version_id           INT           NOT NULL REFERENCES bud.budget_versions(version_id) ON DELETE CASCADE,
    key_id               INT           NOT NULL REFERENCES bud.control_keys(key_id),
    line_no              SMALLINT      NOT NULL,
    proposed_amount      NUMERIC(18,2) NOT NULL CHECK (proposed_amount >= 0),
    approved_amount      NUMERIC(18,2) NULL CHECK (approved_amount >= 0),
    previous_amount      NUMERIC(18,2) NULL,
    policy_code          VARCHAR(10)   NULL CHECK (policy_code IN ('WARN', 'APPROVAL', 'BLOCK')),
    warn_percent         NUMERIC(5,2)  NULL CHECK (warn_percent > 0 AND warn_percent <= 100),
    responsible_user_id  INT           NULL REFERENCES sec.users(user_id),
    note                 TEXT          NULL,
    UNIQUE (version_id, key_id)
);

CREATE TABLE bud.line_period_amounts (
    line_id    INT           NOT NULL REFERENCES bud.budget_lines(line_id) ON DELETE CASCADE,
    period_no  SMALLINT      NOT NULL,
    amount     NUMERIC(18,2) NOT NULL CHECK (amount >= 0),
    PRIMARY KEY (line_id, period_no)
);

-- تاریخچهٔ تصمیم هر نسخه (ارسال، بررسی، تأیید، انتشار، رد، بازگشایی، لغو)
CREATE TABLE bud.version_decisions (
    decision_id   SERIAL       PRIMARY KEY,
    version_id    INT          NOT NULL REFERENCES bud.budget_versions(version_id) ON DELETE CASCADE,
    action_code   VARCHAR(12)  NOT NULL,
    from_status   VARCHAR(12)  NULL,
    to_status     VARCHAR(12)  NOT NULL,
    user_id       INT          NULL REFERENCES sec.users(user_id),
    decided_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    comment       TEXT         NULL
);

-- دفتر مصرف: فقط تفاوت وضع سند (پیش‌تعهد، تعهد، واقعی) با برچسب رویداد؛ هرگز ویرایش یا حذف نمی‌شود
CREATE TABLE bud.consumption_entries (
    entry_id            BIGSERIAL     PRIMARY KEY,
    company_id          INT           NOT NULL REFERENCES core.companies(company_id),
    budget_id           INT           NOT NULL REFERENCES bud.budgets(budget_id),
    key_id              INT           NOT NULL REFERENCES bud.control_keys(key_id),
    kind_code           VARCHAR(8)    NOT NULL CHECK (kind_code IN ('PRE', 'COMMIT', 'ACTUAL')),
    source_type         VARCHAR(20)   NOT NULL,
    source_document_id  BIGINT        NOT NULL,
    source_line_id      BIGINT        NOT NULL,
    source_no           INT           NULL,
    period_date         DATE          NOT NULL,
    amount              NUMERIC(18,2) NOT NULL,
    amount_fc           NUMERIC(18,2) NULL,
    currency_id         INT           NULL REFERENCES core.currencies(currency_id),
    exchange_rate       NUMERIC(18,6) NULL,
    event_code          VARCHAR(16)   NOT NULL,
    note                TEXT          NULL,
    user_id             INT           NULL REFERENCES sec.users(user_id),
    created_at          TIMESTAMPTZ   NOT NULL DEFAULT now()
);
CREATE INDEX ix_bud_consumption_key ON bud.consumption_entries (key_id, kind_code);
CREATE INDEX ix_bud_consumption_source ON bud.consumption_entries (source_type, source_line_id);
CREATE INDEX ix_bud_consumption_doc ON bud.consumption_entries (company_id, source_type, source_document_id);

-- مجوز تجاوز از بودجه (یا افزایش مصرف در دورهٔ بسته / خرید خارج از بودجه)
CREATE TABLE bud.exceptions (
    exception_id          SERIAL        PRIMARY KEY,
    company_id            INT           NOT NULL REFERENCES core.companies(company_id),
    budget_id             INT           NULL REFERENCES bud.budgets(budget_id),
    key_id                INT           NULL REFERENCES bud.control_keys(key_id),
    source_type           VARCHAR(20)   NOT NULL,
    source_document_id    BIGINT        NOT NULL,
    source_no             INT           NULL,
    level_code            VARCHAR(10)   NOT NULL CHECK (level_code IN ('APPROVAL', 'BLOCK', 'CLOSED', 'UNBUDGETED')),
    excess_amount         NUMERIC(18,2) NOT NULL CHECK (excess_amount >= 0),
    reason                TEXT          NULL,
    status_code           VARCHAR(10)   NOT NULL DEFAULT 'PENDING'
        CHECK (status_code IN ('PENDING', 'APPROVED', 'REJECTED', 'USED', 'CANCELLED')),
    requested_by_user_id  INT           NULL REFERENCES sec.users(user_id),
    requested_at          TIMESTAMPTZ   NOT NULL DEFAULT now(),
    decided_by_user_id    INT           NULL REFERENCES sec.users(user_id),
    decided_at            TIMESTAMPTZ   NULL,
    decision_note         TEXT          NULL,
    used_at               TIMESTAMPTZ   NULL
);
CREATE UNIQUE INDEX ux_bud_exceptions_open ON bud.exceptions (source_type, source_document_id, COALESCE(key_id, 0), level_code)
    WHERE status_code IN ('PENDING', 'APPROVED');

-- ردپای هر بار اجرای کنترل روی سند
CREATE TABLE bud.control_events (
    event_id            BIGSERIAL     PRIMARY KEY,
    company_id          INT           NOT NULL REFERENCES core.companies(company_id),
    budget_id           INT           NULL REFERENCES bud.budgets(budget_id),
    key_id              INT           NULL REFERENCES bud.control_keys(key_id),
    source_type         VARCHAR(20)   NOT NULL,
    source_document_id  BIGINT        NOT NULL,
    source_no           INT           NULL,
    stage_code          VARCHAR(16)   NOT NULL,
    outcome_code        VARCHAR(16)   NOT NULL,
    policy_code         VARCHAR(10)   NULL,
    budget_amount       NUMERIC(18,2) NULL,
    consumed_before     NUMERIC(18,2) NULL,
    delta               NUMERIC(18,2) NULL,
    available_after     NUMERIC(18,2) NULL,
    exception_id        INT           NULL REFERENCES bud.exceptions(exception_id),
    message             TEXT          NULL,
    user_id             INT           NULL REFERENCES sec.users(user_id),
    created_at          TIMESTAMPTZ   NOT NULL DEFAULT now()
);
CREATE INDEX ix_bud_control_events_doc ON bud.control_events (company_id, source_type, source_document_id);

-- بستن ماندهٔ تعهد یک ردیف سفارش (وضعیت سفارش خرید عوض نمی‌شود)
CREATE TABLE bud.commitment_closures (
    closure_id           SERIAL        PRIMARY KEY,
    company_id           INT           NOT NULL REFERENCES core.companies(company_id),
    document_id          BIGINT        NOT NULL REFERENCES comm.commercial_documents(document_id),
    line_id              BIGINT        NOT NULL REFERENCES comm.commercial_document_lines(line_id),
    closed_qty_base      NUMERIC(18,6) NOT NULL CHECK (closed_qty_base > 0),
    reason               TEXT          NOT NULL,
    closed_by_user_id    INT           NULL REFERENCES sec.users(user_id),
    closed_at            TIMESTAMPTZ   NOT NULL DEFAULT now(),
    reopened_by_user_id  INT           NULL REFERENCES sec.users(user_id),
    reopened_at          TIMESTAMPTZ   NULL,
    reopen_note          TEXT          NULL
);
CREATE UNIQUE INDEX ux_bud_closures_active ON bud.commitment_closures (line_id) WHERE reopened_at IS NULL;

-- نسخهٔ تأییدشده بی‌ردپا تغییر نمی‌کند: فقط تأییدشده ← منتشرشده و منتشرشده ← جایگزین‌شده
CREATE OR REPLACE FUNCTION bud.version_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.status_code NOT IN ('DRAFT', 'CANCELLED') THEN
            RAISE EXCEPTION 'BUD_LOCKED: نسخهٔ ارسال‌شده یا مصوب بودجه حذف نمی‌شود';
        END IF;
        RETURN OLD;
    END IF;
    IF OLD.status_code IN ('APPROVED', 'PUBLISHED', 'SUPERSEDED', 'CANCELLED') THEN
        IF NOT ((OLD.status_code = 'APPROVED' AND NEW.status_code IN ('PUBLISHED', 'APPROVED'))
                OR (OLD.status_code = 'PUBLISHED' AND NEW.status_code = 'SUPERSEDED'))
           OR NEW.valid_from IS DISTINCT FROM OLD.valid_from OR NEW.valid_to IS DISTINCT FROM OLD.valid_to
           OR NEW.kind_code IS DISTINCT FROM OLD.kind_code OR NEW.budget_id IS DISTINCT FROM OLD.budget_id THEN
            RAISE EXCEPTION 'BUD_LOCKED: نسخهٔ مصوب بودجه قابل تغییر نیست؛ اصلاحیه بسازید';
        END IF;
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;
CREATE TRIGGER tr_bud_versions_guard BEFORE UPDATE OR DELETE ON bud.budget_versions
    FOR EACH ROW EXECUTE FUNCTION bud.version_guard();

CREATE OR REPLACE FUNCTION bud.line_guard() RETURNS trigger AS $$
DECLARE
    v_status VARCHAR(12);
BEGIN
    IF TG_TABLE_NAME = 'budget_lines' THEN
        SELECT status_code INTO v_status FROM bud.budget_versions WHERE version_id = COALESCE(NEW.version_id, OLD.version_id);
    ELSE
        SELECT v.status_code INTO v_status FROM bud.budget_lines l JOIN bud.budget_versions v ON v.version_id = l.version_id
         WHERE l.line_id = COALESCE(NEW.line_id, OLD.line_id);
    END IF;
    IF v_status IS NOT NULL AND v_status NOT IN ('DRAFT', 'SUBMITTED', 'REVIEWED') THEN
        RAISE EXCEPTION 'BUD_LOCKED: ردیف نسخهٔ مصوب بودجه قابل تغییر نیست؛ اصلاحیه بسازید';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;
CREATE TRIGGER tr_bud_lines_guard BEFORE INSERT OR UPDATE OR DELETE ON bud.budget_lines
    FOR EACH ROW EXECUTE FUNCTION bud.line_guard();
CREATE TRIGGER tr_bud_period_amounts_guard BEFORE INSERT OR UPDATE OR DELETE ON bud.line_period_amounts
    FOR EACH ROW EXECUTE FUNCTION bud.line_guard();

CREATE OR REPLACE FUNCTION bud.consumption_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'BUD_LOCKED: دفتر مصرف بودجه فقط افزودنی است';
END $$ LANGUAGE plpgsql;
CREATE TRIGGER tr_bud_consumption_immutable BEFORE UPDATE OR DELETE ON bud.consumption_entries
    FOR EACH ROW EXECUTE FUNCTION bud.consumption_immutable();

INSERT INTO inv.feature_definitions (feature_code, name, category, requires_feature_code, description) VALUES
    ('BUD_ENFORCE', 'کنترل بودجه در تایید اسناد خرید', 'BUDGET', NULL,
     'سفارش خرید، فاکتور خرید و (با کلید بعدی) درخواست خرید هنگام تایید با بودجهٔ منتشرشده سنجیده می‌شوند و سیاست هشدار، تأیید سطح بالاتر یا مسدودسازی در خود سرویس اجرا می‌شود. بدون این کلید فقط مصرف ثبت و گزارش می‌شود.'),
    ('BUD_PR_COMMIT', 'کسر درخواست خرید تصویب‌شده از ماندهٔ بودجه', 'BUDGET', NULL,
     'ماندهٔ سفارش‌نشدهٔ درخواست‌های خرید تصویب‌شده به‌عنوان پیش‌تعهد از ماندهٔ قابل تعهد کم می‌شود و تصویب درخواست هم با بودجه سنجیده می‌شود.'),
    ('BUD_SELF_APPROVAL', 'اجازهٔ بررسی و تأیید بودجه توسط تهیه‌کننده', 'BUDGET', NULL,
     'برای شرکت‌های کوچک: تهیه‌کنندهٔ نسخه می‌تواند خودش آن را بررسی و تأیید کند. بدون این کلید تهیه‌کننده، بررسی‌کننده و تأییدکننده باید سه نفر متفاوت باشند.')
ON CONFLICT (feature_code) DO NOTHING;
