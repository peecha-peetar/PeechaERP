-- پیچا | R347: لیست بیمهٔ تأمین اجتماعی و لیست مالیات حقوق
-- پیش‌نیاز: 043_hr_core.sql، 044_payroll_core.sql
-- مشخصات کارگاه
ALTER TABLE payroll.company_settings
    ADD COLUMN IF NOT EXISTS sso_workshop_code VARCHAR(20) NULL,
    ADD COLUMN IF NOT EXISTS sso_workshop_name VARCHAR(200) NULL,
    ADD COLUMN IF NOT EXISTS sso_employer_name VARCHAR(200) NULL,
    ADD COLUMN IF NOT EXISTS sso_workshop_address VARCHAR(400) NULL,
    ADD COLUMN IF NOT EXISTS sso_contract_row VARCHAR(10) NULL;

-- مشخصات هویتی لازم در لیست بیمه
ALTER TABLE hr.employees
    ADD COLUMN IF NOT EXISTS father_name VARCHAR(100) NULL,
    ADD COLUMN IF NOT EXISTS id_card_no VARCHAR(20) NULL,
    ADD COLUMN IF NOT EXISTS id_issue_place VARCHAR(100) NULL,
    ADD COLUMN IF NOT EXISTS nationality_code VARCHAR(10) NULL,
    ADD COLUMN IF NOT EXISTS insurance_job_code VARCHAR(20) NULL;

-- مزد مشمول بیمه و روزهای کارکرد هر فیش (برای لیست بیمه)
ALTER TABLE payroll.payslips
    ADD COLUMN IF NOT EXISTS insurable_wage NUMERIC(18, 2) NULL,
    ADD COLUMN IF NOT EXISTS worked_days SMALLINT NULL;
