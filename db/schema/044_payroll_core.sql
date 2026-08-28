-- پیچا | فازِ ۲ از ماژولِ حقوق و دستمزد: اطلاعاتِ پایه + قوانینِ حقوق (payroll.*)
-- پیش‌نیاز: 043_hr_core.sql (هستهٔ منابعِ انسانی)
--
-- طبقِ سندِ «مشخصاتِ کارکردیِ ماژولِ حقوق و دستمزد» (فصلِ ۴ و ۵):
--   ۱) payroll.minimum_wage_rates — حداقلِ‌دستمزدِ مصوب، نسخه‌بندی‌شده با
--      effective_from/to؛ company_id می‌تواند NULL باشد یعنی «پیش‌فرضِ سراسری».
--   ۲) payroll.company_settings — تنظیماتِ کلیِ حقوق‌ودستمزدِ هر شرکت
--      (تکی، هم‌الگو با acc.company_accounting_settings).
--   ۳) payroll.policies — پارامترسازیِ عمومیِ قوانینِ کار، نسخه‌بندی‌شده،
--      با ۱۵ کدِ پیش‌فرضِ سراسریِ ایران (فصلِ ۵) از قبل seed شده.
--
-- ⚠ همه‌جا بازه‌هایِ effective_from/to در سطحِ سرویس (نه CHECK دیتابیس)
--   اعتبارسنجیِ عدمِ هم‌پوشانی می‌شوند — هم‌الگو با بقیه‌یِ اسکیمای Peecha
--   که چنین قاعده‌هایی را در لایه‌یِ سرویس نگه می‌دارد.

CREATE SCHEMA payroll;

-- ---------------------------------------------------------------------
-- حداقلِ دستمزدِ مصوب
-- ---------------------------------------------------------------------
CREATE TABLE payroll.minimum_wage_rates (
    minimum_wage_rate_id INT           GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id            INT          REFERENCES core.companies(company_id),  -- NULL = سراسری
    effective_from         DATE         NOT NULL,
    effective_to           DATE,
    monthly_amount         NUMERIC(18,2) NOT NULL,
    daily_amount           NUMERIC(18,2),
    hourly_amount          NUMERIC(18,2),
    CONSTRAINT ck_payroll_min_wage_dates CHECK (effective_to IS NULL OR effective_to >= effective_from)
);
CREATE INDEX ix_payroll_min_wage_company ON payroll.minimum_wage_rates(company_id, effective_from);

-- ---------------------------------------------------------------------
-- تنظیماتِ کلیِ حقوق‌ودستمزدِ شرکت — تکی، هم‌الگو با acc.company_accounting_settings
-- ---------------------------------------------------------------------
CREATE TABLE payroll.company_settings (
    company_id           INT          NOT NULL PRIMARY KEY REFERENCES core.companies(company_id),
    standard_month_days  SMALLINT     NOT NULL DEFAULT 30,
    calculation_basis    VARCHAR(10)  NOT NULL DEFAULT 'DAILY' CHECK (calculation_basis IN ('DAILY', 'HOURLY')),
    rounding_rule        VARCHAR(20)  NOT NULL DEFAULT 'NONE' CHECK (rounding_rule IN ('NONE', 'ROUND_1000', 'ROUND_100', 'TRUNCATE')),
    default_pay_day      SMALLINT,
    payslip_currency_id  INT          REFERENCES core.currencies(currency_id)
);

-- ---------------------------------------------------------------------
-- قوانینِ حقوق و دستمزد (Payroll Policies) — الگویِ عمومیِ resolve_policy
-- ---------------------------------------------------------------------
CREATE TABLE payroll.policies (
    policy_id       INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id      INT          REFERENCES core.companies(company_id),  -- NULL = سراسری
    policy_code     VARCHAR(60)  NOT NULL,
    effective_from  DATE         NOT NULL,
    effective_to    DATE,
    value_numeric   NUMERIC(18,4),
    value_text      VARCHAR(500),
    CONSTRAINT ck_payroll_policies_dates CHECK (effective_to IS NULL OR effective_to >= effective_from)
);
CREATE INDEX ix_payroll_policies_lookup ON payroll.policies(policy_code, company_id, effective_from);

-- ۱۵ کدِ پیش‌فرضِ سراسریِ قانونِ کارِ ایران (فصلِ ۵) — سراسری (company_id
-- NULL)، از یک تاریخِ پایه به‌بعد بدونِ effective_to (تا وقتی شرکتی مقدارِ
-- تازه‌ای ثبت کند). شرکت‌هایی که override اختصاصی نیاز دارند، از طریقِ
-- تنظیماتِ همان شرکت یک ردیفِ company_id-دار تازه ثبت می‌کنند.
INSERT INTO payroll.policies (company_id, policy_code, effective_from, value_numeric) VALUES
    (NULL, 'DAILY_WORKING_HOURS_MAX', '2000-01-01', 8),
    (NULL, 'WEEKLY_WORKING_HOURS_MAX', '2000-01-01', 44),
    (NULL, 'PROBATION_PERIOD_MAX_MONTHS_UNSKILLED', '2000-01-01', 1),
    (NULL, 'PROBATION_PERIOD_MAX_MONTHS_SKILLED', '2000-01-01', 3),
    (NULL, 'RESIGNATION_NOTICE_PERIOD_DAYS', '2000-01-01', 30),
    (NULL, 'ANNUAL_LEAVE_ACCRUAL_DAYS_PER_MONTH', '2000-01-01', 2.5),
    (NULL, 'ANNUAL_LEAVE_CARRY_OVER_MAX_DAYS', '2000-01-01', 9),
    (NULL, 'SEVERANCE_MONTHS_SALARY_PER_YEAR', '2000-01-01', 1),
    (NULL, 'YEAR_END_BONUS_MIN_DAYS_OF_MIN_WAGE', '2000-01-01', 60),
    (NULL, 'YEAR_END_BONUS_MAX_DAYS_OF_MIN_WAGE', '2000-01-01', 90),
    (NULL, 'RETIREMENT_AGE_YEARS_MALE', '2000-01-01', 60),
    (NULL, 'RETIREMENT_AGE_YEARS_FEMALE', '2000-01-01', 55),
    (NULL, 'RETIREMENT_MIN_INSURANCE_YEARS', '2000-01-01', 30),
    (NULL, 'SALARY_PAYMENT_DEADLINE_DAYS', '2000-01-01', 30),
    (NULL, 'TERMINATION_NOTICE_PERIOD_DAYS', '2000-01-01', 30);
