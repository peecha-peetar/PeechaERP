-- پیچا | تنظیماتِ کدینگِ حسابداری: تعدادِ رقم + بازه‌یِ از-تا برایِ هر سطحِ
-- کدینگِ حساب‌ها، همان بازه برایِ سطوحِ تفصیلی، تغییرِ کدِ پیش‌فرضِ «بدون
-- تفصیلی» به «۰۰۰۰۰۰»، و ۷ نوعِ‌بُعدِ تفصیلیِ «فرمِ خاص»یِ تازه (کالا/
-- دارایی‌ثابت/بانک/صندوق/تنخواه/مرکزِهزینه/پروژه).
-- پیش‌نیاز: 003_accounting_core.sql, 008_person_dimension.sql, 010_detail_group_hierarchy.sql

-- طبقِ درخواستِ صریح: «تعداد ارقام حساب‌ها از ابتدا ست شود و اگر سندی ثبت
-- شود دیگر قابل تغییر نباشد» + «بتوان از عدد تا عدد خاصی برای کدها در نظر
-- گرفت» — یک ردیفِ اختیاری به‌ازایِ هر سطح (۱=گروه، ۲=کل، ۳=معین)؛ سطحی که
-- ردیفی این‌جا نداشته باشد بدونِ محدودیت می‌ماند (سازگار با شرکت‌هایِ
-- موجود).
CREATE TABLE acc.chart_of_account_level_config (
    company_id   INT NOT NULL REFERENCES core.companies(company_id),
    account_level SMALLINT NOT NULL CHECK (account_level BETWEEN 1 AND 3),
    code_length  SMALLINT NULL CHECK (code_length BETWEEN 1 AND 10),
    range_from   BIGINT NULL,
    range_to     BIGINT NULL,
    CONSTRAINT pk_chart_of_account_level_config PRIMARY KEY (company_id, account_level),
    CONSTRAINT ck_chart_of_account_level_config_range CHECK (range_from IS NULL OR range_to IS NULL OR range_from <= range_to)
);

-- همان «از-تا» برایِ سطوحِ گروه‌هایِ تفصیلی (تا امروز فقط طولِ کد داشت).
ALTER TABLE acc.detail_group_levels
    ADD COLUMN range_from BIGINT NULL,
    ADD COLUMN range_to   BIGINT NULL,
    ADD CONSTRAINT ck_detail_group_levels_range CHECK (range_from IS NULL OR range_to IS NULL OR range_from <= range_to);

-- طبقِ درخواستِ صریح: کدِ تفصیلیِ پیش‌فرض («بدون تفصیلی») باید «۰۰۰۰۰۰»
-- باشد، نه «NONE» — رکوردهایِ already-seeded (برایِ شرکت‌هایِ موجود) هم
-- به‌روز می‌شوند تا با ثابتِ تازه‌یِ NO_DETAIL_CODE در کد هم‌خوان بمانند.
UPDATE acc.detail_accounts SET code = '000000' WHERE code = 'NONE';

-- ۷ نوعِ‌بُعدِ «فرمِ خاص»یِ تازه — دقیقاً مثلِ الگویِ seed شدنِ PERSON در
-- 008_person_dimension.sql: برایِ همه‌ی شرکت‌هایِ موجود همین‌جا، و برایِ
-- شرکت‌هایِ تازه از طریقِ سرویسِ bootstrap/companies (ensure_dimension_type).
INSERT INTO acc.detail_dimension_types (company_id, code, is_active)
SELECT c.company_id, seed_codes.dimension_code, TRUE
FROM core.companies c
CROSS JOIN (VALUES
    ('INVENTORY_ITEM'),
    ('FIXED_ASSET'),
    ('BANK_ACCOUNT'),
    ('CASH_BOX'),
    ('PETTY_CASH'),
    ('COST_CENTER'),
    ('PROJECT')
) AS seed_codes(dimension_code)
ON CONFLICT (company_id, code) DO NOTHING;
