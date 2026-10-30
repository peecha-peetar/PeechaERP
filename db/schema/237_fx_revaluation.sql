-- پیچا | R349: تسعیر ارز — سود و زیان تسعیر روی ماندهٔ ارزی حساب‌ها
-- پیش‌نیاز: 003_accounting_core.sql

ALTER TABLE acc.company_accounting_settings
    ADD COLUMN IF NOT EXISTS fx_gain_account_id INT NULL REFERENCES acc.chart_of_accounts(account_id),
    ADD COLUMN IF NOT EXISTS fx_loss_account_id INT NULL REFERENCES acc.chart_of_accounts(account_id);

-- ردیف ریالیِ اصلاح ماندهٔ یک ارز (تسعیر یا باقی‌ماندهٔ گردکردن در انتقال سال)؛ با حذف ردیف سند پاک می‌شود
CREATE TABLE IF NOT EXISTS acc.fx_position_adjustments (
    line_id      BIGINT PRIMARY KEY REFERENCES acc.journal_entry_lines(line_id) ON DELETE CASCADE,
    currency_id  INT    NOT NULL REFERENCES core.currencies(currency_id)
);

CREATE TABLE IF NOT EXISTS acc.fx_revaluations (
    revaluation_id      SERIAL PRIMARY KEY,
    company_id          INT          NOT NULL REFERENCES core.companies(company_id),
    revaluation_date    DATE         NOT NULL,
    journal_entry_id    INT          NOT NULL REFERENCES acc.journal_entries(journal_entry_id) ON DELETE CASCADE,
    rates               JSONB        NOT NULL,
    created_by_user_id  INT          NULL REFERENCES sec.users(user_id),
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_fx_revaluation_date UNIQUE (company_id, revaluation_date)
);
