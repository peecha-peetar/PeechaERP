-- پیچا | فازِ ۱ از ماژولِ حقوق و دستمزد: هستهٔ منابع انسانی (hr.*)
-- پیش‌نیاز: 001_core_i18n_and_tenancy.sql, 003_accounting_core.sql (acc.detail_accounts
--           برایِ گروهِ شخصیِ PERSONNEL موجود است و به‌عنوانِ تفصیلیِ حسابداری/خزانه‌داریِ
--           هر کارمند استفاده می‌شود؛ خودِ hr.employees رکوردِ اصلیِ منابع انسانی است).
--
-- طبقِ سندِ «مشخصاتِ کارکردیِ ماژولِ حقوق و دستمزد» (فصلِ ۲ و ۳ و ۴):
--   ۱) الگویِ Lookup عمومی (hr.lookup_types/hr.lookup_values) به‌جایِ CHECK ثابت،
--      تا هر بخش از طریقِ تنظیمات قابلِ‌شخصی‌سازی باشد.
--   ۲) ساختارِ سازمانی سلسله‌مراتبی (hr.organizational_units) با ارتباطِ اختیاری
--      به مرکزِ هزینه‌یِ حسابداریِ موجود.
--   ۳) hr.employees رکوردِ اصلیِ کارمند؛ personnel_detail_account_id (اختیاری) به
--      acc.detail_accounts گروهِ PERSONNEL وصل می‌شود تا در اسنادِ حسابداری/خزانه‌داری
--      به‌عنوانِ تفصیلی قابلِ‌انتخاب باشد.
--   ۴) hr.employment_contracts با قاعدهٔ «فقط یک قراردادِ فعال در هر لحظه برایِ هر کارمند»
--      (ایندکسِ یکتایِ جزئی).
--   ۵) hr.terminations برایِ ثبتِ پایانِ همکاری/تسویه.

CREATE SCHEMA hr;

-- ---------------------------------------------------------------------
-- الگویِ Lookup عمومی
-- ---------------------------------------------------------------------
CREATE TABLE hr.lookup_types (
    lookup_type_id  SMALLINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code            VARCHAR(50)   NOT NULL UNIQUE,   -- EMPLOYMENT_TYPE, TERMINATION_REASON, EDUCATION_DEGREE, MARITAL_STATUS, MILITARY_SERVICE_STATUS, GENDER
    is_system       BOOLEAN       NOT NULL DEFAULT FALSE
);

CREATE TABLE hr.lookup_values (
    lookup_value_id INT           GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    lookup_type_id  SMALLINT      NOT NULL REFERENCES hr.lookup_types(lookup_type_id),
    company_id      INT           REFERENCES core.companies(company_id),  -- NULL = سراسری
    code            VARCHAR(50)   NOT NULL,
    name            VARCHAR(200)  NOT NULL,
    display_order   SMALLINT      NOT NULL DEFAULT 0,
    is_active       BOOLEAN       NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_hr_lookup_values UNIQUE (lookup_type_id, company_id, code)
);
CREATE INDEX ix_hr_lookup_values_type ON hr.lookup_values(lookup_type_id, company_id);

INSERT INTO hr.lookup_types (code, is_system) VALUES
    ('EMPLOYMENT_TYPE', TRUE),
    ('TERMINATION_TYPE', TRUE),
    ('EDUCATION_DEGREE', TRUE),
    ('MARITAL_STATUS', TRUE),
    ('MILITARY_SERVICE_STATUS', TRUE),
    ('GENDER', TRUE);

INSERT INTO hr.lookup_values (lookup_type_id, company_id, code, name, display_order)
SELECT lt.lookup_type_id, NULL, v.code, v.name, v.display_order
FROM hr.lookup_types lt
JOIN (VALUES
    ('EMPLOYMENT_TYPE', 'FULL_TIME', 'تمام‌وقت', 1),
    ('EMPLOYMENT_TYPE', 'PART_TIME', 'پاره‌وقت', 2),
    ('EMPLOYMENT_TYPE', 'PROJECT_BASED', 'پروژه‌ای', 3),
    ('EMPLOYMENT_TYPE', 'CONTRACTOR', 'پیمانکار', 4),
    ('TERMINATION_TYPE', 'RESIGNATION', 'استعفا', 1),
    ('TERMINATION_TYPE', 'TERMINATION_BY_EMPLOYER', 'اخراج/خاتمهٔ همکاری', 2),
    ('TERMINATION_TYPE', 'RETIREMENT', 'بازنشستگی', 3),
    ('TERMINATION_TYPE', 'CONTRACT_END', 'پایانِ قرارداد', 4),
    ('TERMINATION_TYPE', 'MUTUAL_AGREEMENT', 'توافقی', 5),
    ('EDUCATION_DEGREE', 'DIPLOMA', 'دیپلم', 1),
    ('EDUCATION_DEGREE', 'ASSOCIATE', 'کاردانی', 2),
    ('EDUCATION_DEGREE', 'BACHELOR', 'کارشناسی', 3),
    ('EDUCATION_DEGREE', 'MASTER', 'کارشناسی ارشد', 4),
    ('EDUCATION_DEGREE', 'DOCTORATE', 'دکتری', 5),
    ('MARITAL_STATUS', 'SINGLE', 'مجرد', 1),
    ('MARITAL_STATUS', 'MARRIED', 'متأهل', 2),
    ('MILITARY_SERVICE_STATUS', 'EXEMPT', 'معاف', 1),
    ('MILITARY_SERVICE_STATUS', 'COMPLETED', 'پایان‌خدمت', 2),
    ('MILITARY_SERVICE_STATUS', 'DEFERRED', 'معافیتِ تحصیلی', 3),
    ('MILITARY_SERVICE_STATUS', 'NOT_APPLICABLE', 'مشمول‌نیست', 4),
    ('GENDER', 'MALE', 'مرد', 1),
    ('GENDER', 'FEMALE', 'زن', 2)
) AS v(type_code, code, name, display_order) ON v.type_code = lt.code;

-- ---------------------------------------------------------------------
-- ساختارِ سازمانی
-- ---------------------------------------------------------------------
CREATE TABLE hr.organizational_units (
    org_unit_id                 INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id                  INT          NOT NULL REFERENCES core.companies(company_id),
    code                        VARCHAR(30)  NOT NULL,
    name                        VARCHAR(200) NOT NULL,
    parent_org_unit_id          INT          REFERENCES hr.organizational_units(org_unit_id),
    cost_center_detail_account_id INT        REFERENCES acc.detail_accounts(detail_account_id),
    manager_employee_id         INT,  -- FK به hr.employees بعد از تعریفِ آن جدول اضافه می‌شود (رفعِ وابستگیِ دوری)
    is_active                   BOOLEAN      NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_hr_org_units UNIQUE (company_id, code)
);
CREATE INDEX ix_hr_org_units_parent ON hr.organizational_units(parent_org_unit_id);

-- ---------------------------------------------------------------------
-- رده‌هایِ شغلی
-- ---------------------------------------------------------------------
CREATE TABLE hr.job_grades (
    job_grade_id     INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id       INT          NOT NULL REFERENCES core.companies(company_id),
    code             VARCHAR(30)  NOT NULL,
    title            VARCHAR(200) NOT NULL,
    grade_level      SMALLINT     NOT NULL DEFAULT 0,
    min_base_salary  NUMERIC(18,2),
    max_base_salary  NUMERIC(18,2),
    is_active        BOOLEAN      NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_hr_job_grades UNIQUE (company_id, code),
    CONSTRAINT ck_hr_job_grades_range CHECK (min_base_salary IS NULL OR max_base_salary IS NULL OR min_base_salary <= max_base_salary)
);

-- ---------------------------------------------------------------------
-- پست‌های سازمانی
-- ---------------------------------------------------------------------
CREATE TABLE hr.positions (
    position_id      INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id       INT          NOT NULL REFERENCES core.companies(company_id),
    code             VARCHAR(30)  NOT NULL,
    title            VARCHAR(200) NOT NULL,
    org_unit_id      INT          NOT NULL REFERENCES hr.organizational_units(org_unit_id),
    job_grade_id     INT          REFERENCES hr.job_grades(job_grade_id),
    capacity         SMALLINT     NOT NULL DEFAULT 1,
    is_active        BOOLEAN      NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_hr_positions UNIQUE (company_id, code)
);
CREATE INDEX ix_hr_positions_org_unit ON hr.positions(org_unit_id);

-- ---------------------------------------------------------------------
-- کارمندان
-- ---------------------------------------------------------------------
CREATE TABLE hr.employees (
    employee_id                  INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id                   INT          NOT NULL REFERENCES core.companies(company_id),
    personnel_detail_account_id  INT          REFERENCES acc.detail_accounts(detail_account_id),
    employee_code                VARCHAR(30)  NOT NULL,
    first_name                   VARCHAR(100) NOT NULL,
    last_name                    VARCHAR(100) NOT NULL,
    national_id                  VARCHAR(20),
    date_of_birth                DATE,
    gender_lookup_id             INT          REFERENCES hr.lookup_values(lookup_value_id),
    marital_status_lookup_id     INT          REFERENCES hr.lookup_values(lookup_value_id),
    education_degree_lookup_id   INT          REFERENCES hr.lookup_values(lookup_value_id),
    military_service_lookup_id   INT          REFERENCES hr.lookup_values(lookup_value_id),
    social_security_no           VARCHAR(30),
    bank_account_no              VARCHAR(40),
    bank_iban                    VARCHAR(34),
    phone                        VARCHAR(30),
    mobile                       VARCHAR(30),
    address                      VARCHAR(400),
    hire_date                    DATE         NOT NULL,
    status                       VARCHAR(20)  NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'ON_LEAVE', 'TERMINATED')),
    notes                        VARCHAR(1000),
    CONSTRAINT uq_hr_employees_code UNIQUE (company_id, employee_code)
);
CREATE INDEX ix_hr_employees_company ON hr.employees(company_id);
CREATE INDEX ix_hr_employees_national_id ON hr.employees(national_id);

ALTER TABLE hr.organizational_units
    ADD CONSTRAINT fk_hr_org_units_manager FOREIGN KEY (manager_employee_id) REFERENCES hr.employees(employee_id);

-- ---------------------------------------------------------------------
-- قراردادهایِ کاری — فقط یک قراردادِ فعال برایِ هر کارمند در هر لحظه
-- ---------------------------------------------------------------------
CREATE TABLE hr.employment_contracts (
    contract_id            INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    employee_id            INT          NOT NULL REFERENCES hr.employees(employee_id),
    employment_type_lookup_id INT       REFERENCES hr.lookup_values(lookup_value_id),
    org_unit_id            INT          NOT NULL REFERENCES hr.organizational_units(org_unit_id),
    position_id            INT          NOT NULL REFERENCES hr.positions(position_id),
    start_date             DATE         NOT NULL,
    end_date               DATE,
    base_salary            NUMERIC(18,2) NOT NULL,
    status                 VARCHAR(20)  NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'ENDED', 'CANCELLED')),
    end_reason_lookup_id   INT          REFERENCES hr.lookup_values(lookup_value_id),
    CONSTRAINT ck_hr_contracts_dates CHECK (end_date IS NULL OR end_date >= start_date)
);
CREATE INDEX ix_hr_contracts_employee ON hr.employment_contracts(employee_id);
-- طبقِ یافتهٔ اکتشاف در سندِ طراحی: «فقط یک قراردادِ فعال» با ایندکسِ یکتایِ جزئی
CREATE UNIQUE INDEX ux_hr_contracts_one_active ON hr.employment_contracts(employee_id) WHERE status = 'ACTIVE';

-- ---------------------------------------------------------------------
-- پایانِ همکاری
-- ---------------------------------------------------------------------
CREATE TABLE hr.terminations (
    termination_id          INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    employee_id             INT          NOT NULL REFERENCES hr.employees(employee_id),
    contract_id             INT          NOT NULL REFERENCES hr.employment_contracts(contract_id),
    termination_date        DATE         NOT NULL,
    termination_type_lookup_id INT       REFERENCES hr.lookup_values(lookup_value_id),
    reason                  VARCHAR(1000),
    settlement_status       VARCHAR(20)  NOT NULL DEFAULT 'PENDING' CHECK (settlement_status IN ('PENDING', 'SETTLED')),
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_hr_terminations_employee ON hr.terminations(employee_id);
