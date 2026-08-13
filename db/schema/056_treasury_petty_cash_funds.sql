-- پیچا | ساختارِ واقعیِ تنخواه‌گردان: هر تنخواه‌دار (یک تفصیلیِ سطحِ آخرِ
-- گروهِ «تنخواه») می‌تواند هم‌زمان چند تنخواهِ باز داشته باشد؛ هرکدام با
-- شماره‌یِ خودکارِ مستقل (per custodian). افتتاح = یک سندِ پرداختِ واقعیِ
-- اولیه (واریزی به تنخواه‌دار). ردیف‌هایی که در دورانِ بازبودن ثبت
-- می‌شوند هیچ سندِ حسابداری‌ای نمی‌سازند (نه حتی پیش‌نویس). بستنِ تنخواه
-- یک سندِ موقتِ پیش‌نویس می‌سازد که تنخواه‌دار را به‌اندازه‌یِ جمعِ
-- ردیف‌ها بستانکار می‌کند.

CREATE TABLE treasury.petty_cash_funds (
    fund_id                     SERIAL PRIMARY KEY,
    company_id                  INT NOT NULL REFERENCES core.companies(company_id),
    custodian_detail_account_id INT NOT NULL REFERENCES acc.detail_accounts(detail_account_id),
    fund_no                     INT NOT NULL,
    status                      VARCHAR(10) NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'CLOSED')),
    opening_amount              NUMERIC(18, 2) NOT NULL CHECK (opening_amount > 0),
    opening_date                DATE NOT NULL,
    opening_journal_entry_id    INT NOT NULL REFERENCES acc.journal_entries(journal_entry_id),
    closing_date                DATE,
    closing_journal_entry_id    INT REFERENCES acc.journal_entries(journal_entry_id),
    created_by_user_id          INT NOT NULL REFERENCES sec.users(user_id),
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (custodian_detail_account_id, fund_no)
);

CREATE TABLE treasury.petty_cash_fund_lines (
    line_id                     SERIAL PRIMARY KEY,
    fund_id                     INT NOT NULL REFERENCES treasury.petty_cash_funds(fund_id) ON DELETE CASCADE,
    method                      VARCHAR(20) NOT NULL CHECK (method IN ('CASH', 'BANK', 'CHECK')),
    amount                      NUMERIC(18, 2) NOT NULL CHECK (amount > 0),
    description                 VARCHAR(300),
    detail_account_id           INT REFERENCES acc.detail_accounts(detail_account_id),
    check_no                    VARCHAR(50),
    check_due_date              DATE,
    line_date                   DATE NOT NULL,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_petty_cash_fund_lines_fund_id ON treasury.petty_cash_fund_lines(fund_id);
CREATE INDEX idx_petty_cash_funds_custodian ON treasury.petty_cash_funds(custodian_detail_account_id, status);
