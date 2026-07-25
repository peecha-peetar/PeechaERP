-- پیچا | گزارش‌سازِ پیشرفته: به‌جایِ اینکه هر ردیفِ ACCOUNTس فقط از تک‌تکِ
-- حساب‌هایِ دستی‌چین‌شده ساخته شود، حالا هر جزء می‌تواند «حسابِ مشخص»،
-- «بازه‌یِ کد در یک سطح» یا «کلِ یک طبقه (دارایی/بدهی/سرمایه/درآمد/هزینه)
-- در یک سطح» هم باشد — رفعِ محدودیتِ اصلیِ طراحِ الگویِ گزارشِ قبلی.
-- پیش‌نیاز: 016_statement_templates.sql

ALTER TABLE acc.statement_row_accounts DROP CONSTRAINT statement_row_accounts_pkey;
ALTER TABLE acc.statement_row_accounts ADD COLUMN ref_id SERIAL PRIMARY KEY;

ALTER TABLE acc.statement_row_accounts ALTER COLUMN account_id DROP NOT NULL;
ALTER TABLE acc.statement_row_accounts
    ADD COLUMN selector_type VARCHAR(10) NOT NULL DEFAULT 'ACCOUNT'
        CHECK (selector_type IN ('ACCOUNT', 'RANGE', 'CATEGORY'));
ALTER TABLE acc.statement_row_accounts
    ADD COLUMN account_level SMALLINT CHECK (account_level BETWEEN 1 AND 4);
ALTER TABLE acc.statement_row_accounts ADD COLUMN code_from VARCHAR(50);
ALTER TABLE acc.statement_row_accounts ADD COLUMN code_to VARCHAR(50);
ALTER TABLE acc.statement_row_accounts
    ADD COLUMN category_code VARCHAR(20)
        CHECK (category_code IN ('ASSET', 'LIABILITY', 'EQUITY', 'REVENUE', 'EXPENSE'));

ALTER TABLE acc.statement_row_accounts ADD CONSTRAINT chk_statement_row_accounts_selector CHECK (
    (selector_type = 'ACCOUNT' AND account_id IS NOT NULL AND account_level IS NULL
        AND code_from IS NULL AND code_to IS NULL AND category_code IS NULL)
    OR (selector_type = 'RANGE' AND account_id IS NULL AND account_level IS NOT NULL
        AND code_from IS NOT NULL AND code_to IS NOT NULL AND category_code IS NULL)
    OR (selector_type = 'CATEGORY' AND account_id IS NULL AND account_level IS NOT NULL
        AND category_code IS NOT NULL AND code_from IS NULL AND code_to IS NULL)
);

CREATE INDEX ix_statement_row_accounts_row ON acc.statement_row_accounts(row_id);
