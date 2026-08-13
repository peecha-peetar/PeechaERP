-- پیچا | فازِ ۳ از ماژولِ حقوق و دستمزد: موتورِ عمومیِ آیتمِ حقوقی +
-- بیمه/مالیات/کسورات + موتورِ محاسبه (فصلِ ۶ تا ۱۱ از سندِ طراحی).
--
-- طبقِ سندِ طراحی: بیمه و مالیات هم خودشان نمونه‌هایی از «آیتمِ حقوقی»یِ
-- عمومی‌اند (item_type IN ('INSURANCE','TAX')) — نه موتورهایِ جدا؛ فقط
-- calculation_method='SYSTEM_TAX_ENGINE' یعنی مبلغ‌شان با فرمولِ کاربر
-- محاسبه نمی‌شود، با منطقِ سیستمیِ فصلِ ۹/۱۰ محاسبه می‌شود.

-- ---------------------------------------------------------------------
-- دوره‌هایِ حقوقی (پیش‌نیازِ runs/deduction_entries — بخشی از فصلِ ۳/۱۱)
-- ---------------------------------------------------------------------
CREATE TABLE payroll.periods (
    period_id          INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id         INT          NOT NULL REFERENCES core.companies(company_id),
    jalali_year        SMALLINT     NOT NULL,
    jalali_month       SMALLINT     NOT NULL CHECK (jalali_month BETWEEN 1 AND 12),
    period_start_date  DATE         NOT NULL,
    period_end_date    DATE         NOT NULL,
    status             VARCHAR(20)  NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'CALCULATED', 'APPROVED', 'LOCKED')),
    CONSTRAINT uq_payroll_periods UNIQUE (company_id, jalali_year, jalali_month),
    CONSTRAINT ck_payroll_periods_dates CHECK (period_end_date >= period_start_date)
);

-- ---------------------------------------------------------------------
-- موتورِ عمومیِ آیتمِ حقوقی (فصلِ ۶) + تکمیل‌هایِ مزایا (فصلِ ۷) و
-- کسورات (فصلِ ۸) رویِ همان جدول (نه جدولِ جدا، طبقِ طراحیِ سند)
-- ---------------------------------------------------------------------
CREATE TABLE payroll.pay_item_definitions (
    pay_item_id                          INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id                           INT          NOT NULL REFERENCES core.companies(company_id),
    code                                 VARCHAR(60)  NOT NULL,
    name                                 VARCHAR(200) NOT NULL,
    item_type                            VARCHAR(20)  NOT NULL CHECK (item_type IN ('EARNING', 'BENEFIT', 'DEDUCTION', 'INSURANCE', 'TAX')),
    calculation_method                   VARCHAR(30)  NOT NULL CHECK (calculation_method IN ('BASE_SALARY_FROM_CONTRACT', 'FIXED', 'PERCENTAGE_OF_BASE', 'FORMULA', 'MANUAL', 'SYSTEM_TAX_ENGINE')),
    formula_expression                   VARCHAR(1000),
    fixed_amount                         NUMERIC(18,2),
    percentage                           NUMERIC(9,4),
    is_prorated                          BOOLEAN      NOT NULL DEFAULT FALSE,
    is_taxable                           BOOLEAN      NOT NULL DEFAULT FALSE,
    is_insurable                         BOOLEAN      NOT NULL DEFAULT FALSE,
    is_continuous_benefit                BOOLEAN      NOT NULL DEFAULT FALSE,
    calculation_phase                    VARCHAR(20)  NOT NULL CHECK (calculation_phase IN ('EARNING_PHASE', 'INSURANCE_PHASE', 'DEDUCTION_PHASE', 'TAX_PHASE')),
    gl_account_id                        INT          REFERENCES acc.chart_of_accounts(account_id),
    display_order                        SMALLINT     NOT NULL DEFAULT 0,
    description                          VARCHAR(500),
    is_active                            BOOLEAN      NOT NULL DEFAULT TRUE,
    -- فصلِ ۷ — مزایا
    eligibility_condition                VARCHAR(500),
    is_cash                              BOOLEAN      NOT NULL DEFAULT TRUE,
    tax_exempt_ceiling_policy_code       VARCHAR(60),
    insurance_exempt_ceiling_policy_code VARCHAR(60),
    -- فصلِ ۸ — کسورات
    is_court_order                       BOOLEAN      NOT NULL DEFAULT FALSE,
    deduction_priority                   SMALLINT,
    CONSTRAINT uq_payroll_pay_items UNIQUE (company_id, code)
);
-- طبقِ سند: «فقط یک آیتمِ BASE_SALARY_FROM_CONTRACT در هر شرکت مجاز»
CREATE UNIQUE INDEX ux_payroll_pay_items_base_salary
    ON payroll.pay_item_definitions (company_id)
    WHERE calculation_method = 'BASE_SALARY_FROM_CONTRACT';

-- تخصیصِ آیتم به کارمندِ خاص (برایِ آیتم‌هایِ MANUAL/FIXED با مبلغِ
-- شخصی‌سازی‌شده یا مزایایِ مشروط)
CREATE TABLE payroll.employee_pay_components (
    component_id    INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    employee_id     INT          NOT NULL REFERENCES hr.employees(employee_id),
    pay_item_id     INT          NOT NULL REFERENCES payroll.pay_item_definitions(pay_item_id),
    amount          NUMERIC(18,2),
    effective_from  DATE         NOT NULL,
    effective_to    DATE,
    CONSTRAINT ck_payroll_pay_components_dates CHECK (effective_to IS NULL OR effective_to >= effective_from)
);
CREATE INDEX ix_payroll_pay_components_employee ON payroll.employee_pay_components(employee_id);

-- کسرِ موردی (فصلِ ۸ — Ad-hoc Deduction Entry)
CREATE TABLE payroll.deduction_entries (
    deduction_entry_id INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    employee_id        INT          NOT NULL REFERENCES hr.employees(employee_id),
    pay_item_id        INT          NOT NULL REFERENCES payroll.pay_item_definitions(pay_item_id),
    period_id          INT          NOT NULL REFERENCES payroll.periods(period_id),
    amount             NUMERIC(18,2) NOT NULL,
    reason             VARCHAR(500),
    status             VARCHAR(20)  NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'APPROVED', 'APPLIED', 'DEFERRED', 'CANCELLED')),
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX ix_payroll_deduction_entries_employee ON payroll.deduction_entries(employee_id, period_id);

-- ---------------------------------------------------------------------
-- بیمهٔ تأمین اجتماعی (فصلِ ۹)
-- ---------------------------------------------------------------------
CREATE TABLE payroll.insurance_configs (
    insurance_config_id            INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id                     INT          REFERENCES core.companies(company_id),  -- NULL = سراسری
    effective_from                 DATE         NOT NULL,
    effective_to                   DATE,
    employee_rate                  NUMERIC(6,4) NOT NULL,
    employer_rate                  NUMERIC(6,4) NOT NULL,
    unemployment_rate              NUMERIC(6,4) NOT NULL,
    insurable_wage_ceiling_policy_code VARCHAR(60),
    insurable_wage_floor           NUMERIC(18,2),
    CONSTRAINT ck_payroll_insurance_dates CHECK (effective_to IS NULL OR effective_to >= effective_from)
);
CREATE INDEX ix_payroll_insurance_configs_lookup ON payroll.insurance_configs(company_id, effective_from);

-- سقفِ مزدِ مشمولِ بیمه به‌صورتِ «چندبرابرِ حداقل‌دستمزد» یک payroll.policy
-- تازه است (نه عددِ ثابت) تا هر شرکت بتواند override اختصاصی بدهد.
INSERT INTO payroll.policies (company_id, policy_code, effective_from, value_numeric)
VALUES (NULL, 'INSURANCE_WAGE_CEILING_MULTIPLE_OF_MIN_WAGE', '2000-01-01', 7);

INSERT INTO payroll.insurance_configs (company_id, effective_from, employee_rate, employer_rate, unemployment_rate, insurable_wage_ceiling_policy_code)
VALUES (NULL, '2000-01-01', 0.07, 0.20, 0.03, 'INSURANCE_WAGE_CEILING_MULTIPLE_OF_MIN_WAGE');

-- ---------------------------------------------------------------------
-- مالیات بر درآمدِ حقوق (فصلِ ۱۰) — نظامِ تجمعیِ سالانه
-- ---------------------------------------------------------------------
CREATE TABLE payroll.tax_brackets (
    tax_bracket_id    INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id        INT          REFERENCES core.companies(company_id),  -- NULL = سراسری
    effective_from    DATE         NOT NULL,
    effective_to      DATE,
    bracket_order     SMALLINT     NOT NULL,
    from_annual_amount NUMERIC(18,2) NOT NULL,
    to_annual_amount  NUMERIC(18,2),  -- NULL = بدونِ سقف (آخرین پلکان)
    rate              NUMERIC(6,4)  NOT NULL,
    CONSTRAINT ck_payroll_tax_brackets_dates CHECK (effective_to IS NULL OR effective_to >= effective_from)
);
CREATE INDEX ix_payroll_tax_brackets_lookup ON payroll.tax_brackets(company_id, effective_from, bracket_order);

CREATE TABLE payroll.tax_exemptions (
    tax_exemption_id        INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id               INT          REFERENCES core.companies(company_id),  -- NULL = سراسری
    effective_from            DATE         NOT NULL,
    effective_to              DATE,
    annual_exemption_amount  NUMERIC(18,2) NOT NULL,
    CONSTRAINT ck_payroll_tax_exemptions_dates CHECK (effective_to IS NULL OR effective_to >= effective_from)
);
CREATE INDEX ix_payroll_tax_exemptions_lookup ON payroll.tax_exemptions(company_id, effective_from);

CREATE TABLE payroll.employee_annual_tax_ledger (
    ledger_id                   INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    employee_id                 INT          NOT NULL REFERENCES hr.employees(employee_id),
    tax_year                    SMALLINT     NOT NULL,
    cumulative_taxable_income   NUMERIC(18,2) NOT NULL DEFAULT 0,
    cumulative_tax_calculated   NUMERIC(18,2) NOT NULL DEFAULT 0,
    cumulative_tax_paid         NUMERIC(18,2) NOT NULL DEFAULT 0,
    status                      VARCHAR(10)  NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'CLOSED')),
    CONSTRAINT uq_payroll_annual_tax_ledger UNIQUE (employee_id, tax_year)
);

-- ---------------------------------------------------------------------
-- موتورِ محاسبهٔ حقوق (فصلِ ۱۱) + خروجیِ حداقلیِ فیش (پیش‌نیازِ موتور،
-- جزئیاتِ کاملِ فیش در فازِ بعدی طبقِ فصلِ ۱۴ تکمیل می‌شود)
-- ---------------------------------------------------------------------
CREATE TABLE payroll.runs (
    run_id              INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    period_id           INT          NOT NULL REFERENCES payroll.periods(period_id),
    run_no              SMALLINT     NOT NULL,
    run_type            VARCHAR(20)  NOT NULL DEFAULT 'REGULAR' CHECK (run_type IN ('REGULAR', 'CORRECTION', 'OFF_CYCLE')),
    scope_org_unit_id   INT          REFERENCES hr.organizational_units(org_unit_id),  -- NULL = همه‌ی کارمندان
    status              VARCHAR(20)  NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT', 'CALCULATING', 'CALCULATED', 'UNDER_REVIEW', 'APPROVED', 'POSTED', 'LOCKED')),
    started_at          TIMESTAMPTZ,
    finished_at         TIMESTAMPTZ,
    triggered_by_user_id INT         REFERENCES sec.users(user_id),
    error_log           VARCHAR(2000),
    CONSTRAINT uq_payroll_runs UNIQUE (period_id, run_no)
);

CREATE TABLE payroll.payslips (
    payslip_id               INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id                    INT          NOT NULL REFERENCES payroll.runs(run_id),
    employee_id               INT          NOT NULL REFERENCES hr.employees(employee_id),
    contract_id               INT          NOT NULL REFERENCES hr.employment_contracts(contract_id),
    period_id                 INT          NOT NULL REFERENCES payroll.periods(period_id),
    gross_amount               NUMERIC(18,2) NOT NULL,
    total_deductions            NUMERIC(18,2) NOT NULL,
    net_pay                    NUMERIC(18,2) NOT NULL,
    status                     VARCHAR(20)  NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT', 'FINALIZED', 'DELIVERED', 'CORRECTED')),
    correction_of_payslip_id  INT          REFERENCES payroll.payslips(payslip_id),
    CONSTRAINT uq_payroll_payslips_run_employee UNIQUE (run_id, employee_id)
);
CREATE INDEX ix_payroll_payslips_employee ON payroll.payslips(employee_id, period_id);

CREATE TABLE payroll.payslip_lines (
    payslip_line_id    INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    payslip_id          INT          NOT NULL REFERENCES payroll.payslips(payslip_id),
    pay_item_id          INT          NOT NULL REFERENCES payroll.pay_item_definitions(pay_item_id),
    pay_item_code_snapshot VARCHAR(60)  NOT NULL,
    label_snapshot        VARCHAR(200) NOT NULL,
    amount                NUMERIC(18,2) NOT NULL,
    phase                 VARCHAR(20)  NOT NULL CHECK (phase IN ('EARNING_PHASE', 'INSURANCE_PHASE', 'DEDUCTION_PHASE', 'TAX_PHASE'))
);
CREATE INDEX ix_payroll_payslip_lines_payslip ON payroll.payslip_lines(payslip_id);
