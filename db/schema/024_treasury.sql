-- پیچا | ماژولِ خزانه‌داری، فازِ ۲: نگاشتِ حساب‌هایِ خزانه‌داری، دسته‌چک،
-- و چک‌هایِ دریافتی/پرداختی.
-- پیش‌نیاز: 001_core_i18n_and_tenancy.sql, 002_security_rbac.sql,
--           003_accounting_core.sql, 022_treasury_entry_types.sql
--
-- طبقِ طرحِ تاییدشده با کاربر:
--   ۱) treasury.account_mappings: ۶ اسلاتِ قابلِ‌تنظیم (نقد/بانک/چک/تخفیف
--      برایِ دریافت و پرداخت) — هر اسلات یک حسابِ کل از acc.chart_of_accounts.
--      جدولِ کلید-مقدار (نه enum ثابت) تا افزودنِ اسلاتِ تازه در آینده فقط
--      یک ردیفِ تازه باشد، نه migration.
--   ۲) treasury.checkbooks: بازه‌یِ شماره‌سریالِ هر دسته‌چکِ یک حسابِ بانکی
--      (حسابِ بانکی = یک acc.detail_accounts با dimension_type=BANK_ACCOUNT).
--   ۳) treasury.check_statuses: جدولِ lookup (نه CHECK constraint) تا
--      «قابلیتِ اضافه‌کردنِ حالتِ تازه در آینده» (خواسته‌ی صریحِ کاربر) بدونِ
--      migration ممکن باشد.
--   ۴) treasury.received_checks/issued_checks: خودِ چک‌ها، هرکدام به سندِ
--      حسابداری‌ای که ساخته (source_journal_entry_id) وصل‌اند.

CREATE SCHEMA treasury;

CREATE TABLE treasury.account_mappings (
    company_id   INT         NOT NULL REFERENCES core.companies(company_id),
    mapping_key  VARCHAR(30) NOT NULL,  -- RECEIPT_CASH, RECEIPT_BANK, RECEIPT_CHECK, RECEIPT_DISCOUNT, PAYMENT_CASH, PAYMENT_BANK, PAYMENT_CHECK, PAYMENT_DISCOUNT
    account_id   INT         NOT NULL REFERENCES acc.chart_of_accounts(account_id),
    CONSTRAINT pk_treasury_account_mappings PRIMARY KEY (company_id, mapping_key)
);

CREATE TABLE treasury.checkbooks (
    checkbook_id            INT         GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id               INT        NOT NULL REFERENCES core.companies(company_id),
    bank_account_detail_id   INT        NOT NULL REFERENCES acc.detail_accounts(detail_account_id),
    start_no                 BIGINT     NOT NULL,
    end_no                   BIGINT     NOT NULL,
    next_no                  BIGINT     NOT NULL,
    is_active                BOOLEAN    NOT NULL DEFAULT TRUE,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_treasury_checkbooks_range CHECK (start_no <= end_no AND next_no BETWEEN start_no AND end_no + 1)
);
CREATE INDEX ix_treasury_checkbooks_bank_account ON treasury.checkbooks(bank_account_detail_id);

CREATE TABLE treasury.check_statuses (
    status_id    SMALLINT    NOT NULL PRIMARY KEY,
    code         VARCHAR(20) NOT NULL,
    applies_to   VARCHAR(10) NOT NULL CHECK (applies_to IN ('RECEIVED', 'ISSUED')),
    CONSTRAINT uq_treasury_check_statuses UNIQUE (code, applies_to)
);
INSERT INTO treasury.check_statuses (status_id, code, applies_to) VALUES
    (1, 'IN_HAND',   'RECEIVED'),  -- نزدِ صندوق
    (2, 'DEPOSITED', 'RECEIVED'),  -- واگذار به بانک برایِ وصول
    (3, 'CLEARED',   'RECEIVED'),  -- وصول‌شده
    (4, 'BOUNCED',   'RECEIVED'),  -- برگشت‌خورده
    (5, 'ENDORSED',  'RECEIVED'),  -- خرج‌شده نزدِ شخصِ ثالث
    (6, 'ISSUED',    'ISSUED'),    -- صادر/نزدِ گیرنده
    (7, 'CLEARED',   'ISSUED'),    -- وصول‌شده توسطِ بانک
    (8, 'BOUNCED',   'ISSUED'),    -- برگشت‌خورده
    (9, 'VOIDED',    'ISSUED');    -- ابطال‌شده

CREATE TABLE treasury.received_checks (
    received_check_id           INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id                   INT         NOT NULL REFERENCES core.companies(company_id),
    check_no                     VARCHAR(30) NOT NULL,
    drawee_bank_name             VARCHAR(150) NULL,   -- بانکِ صادرکننده‌یِ چک
    drawer_name                  VARCHAR(150) NULL,   -- نامِ صادرکننده‌یِ چک
    amount                       NUMERIC(18,2) NOT NULL,
    due_date                     DATE        NOT NULL,
    received_date                DATE        NOT NULL,
    counterparty_detail_account_id INT       NULL REFERENCES acc.detail_accounts(detail_account_id),
    status_id                    SMALLINT    NOT NULL REFERENCES treasury.check_statuses(status_id),
    source_journal_entry_id      INT         NOT NULL REFERENCES acc.journal_entries(journal_entry_id),
    endorsed_to_issued_check_id  INT         NULL,   -- اگر خرج شد، به چکِ پرداختیِ معادل وصل می‌شود
    created_by_user_id           INT         NOT NULL REFERENCES sec.users(user_id),
    created_at                   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_treasury_received_checks_status ON treasury.received_checks(company_id, status_id);
CREATE INDEX ix_treasury_received_checks_due_date ON treasury.received_checks(company_id, due_date);

CREATE TABLE treasury.issued_checks (
    issued_check_id              INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id                    INT         NOT NULL REFERENCES core.companies(company_id),
    checkbook_id                  INT         NULL REFERENCES treasury.checkbooks(checkbook_id),
    check_no                      VARCHAR(30) NOT NULL,
    bank_account_detail_id        INT         NOT NULL REFERENCES acc.detail_accounts(detail_account_id),
    payee_name                    VARCHAR(150) NULL,
    amount                        NUMERIC(18,2) NOT NULL,
    due_date                      DATE        NOT NULL,
    issue_date                    DATE        NOT NULL,
    counterparty_detail_account_id INT        NULL REFERENCES acc.detail_accounts(detail_account_id),
    status_id                     SMALLINT    NOT NULL REFERENCES treasury.check_statuses(status_id),
    source_journal_entry_id       INT         NOT NULL REFERENCES acc.journal_entries(journal_entry_id),
    created_by_user_id            INT         NOT NULL REFERENCES sec.users(user_id),
    created_at                    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_treasury_issued_checks_status ON treasury.issued_checks(company_id, status_id);
CREATE INDEX ix_treasury_issued_checks_due_date ON treasury.issued_checks(company_id, due_date);

ALTER TABLE treasury.received_checks
    ADD CONSTRAINT fk_treasury_received_checks_endorsed_to
    FOREIGN KEY (endorsed_to_issued_check_id) REFERENCES treasury.issued_checks(issued_check_id);
