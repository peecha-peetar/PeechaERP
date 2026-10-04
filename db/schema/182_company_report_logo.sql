-- پیچا R245: لوگویِ شرکت برایِ سربرگِ گزارش‌ها و محلِ آن -- فقط افزایشی.
-- بازگشت (rollback):
--   ALTER TABLE core.companies DROP COLUMN IF EXISTS logo_image, DROP COLUMN IF EXISTS logo_mime,
--     DROP COLUMN IF EXISTS report_logo_position;
ALTER TABLE core.companies
    ADD COLUMN IF NOT EXISTS logo_image BYTEA NULL,
    ADD COLUMN IF NOT EXISTS logo_mime VARCHAR(30) NULL,
    ADD COLUMN IF NOT EXISTS report_logo_position VARCHAR(10) NOT NULL DEFAULT 'RIGHT';  -- RIGHT | LEFT | NONE
