-- پیچا | گروه‌های تفصیلیِ اشخاص (مشتری/تامین‌کننده/پرسنل) + محدودیتِ
-- معین به گروه + فرم‌های تکمیلیِ هر گروه.
-- پیش‌نیاز: 008_person_dimension.sql

-- گروهِ تفصیلیِ هر شخص (طبقه‌بندیِ اشخاص، جدا از نوع‌بُعدِ PERSON که خودِ
-- گروه‌بندی نیست، فقط بستری‌ست که همه‌ی اشخاص در آن ثبت می‌شوند)
CREATE TABLE acc.person_groups (
    person_group_id INT           GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id       INT           NOT NULL REFERENCES core.companies(company_id),
    code             VARCHAR(20)   NOT NULL,   -- CUSTOMER | SUPPLIER | PERSONNEL
    name             VARCHAR(100)  NOT NULL,
    is_active        BOOLEAN       NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_person_groups_code UNIQUE (company_id, code)
);

INSERT INTO acc.person_groups (company_id, code, name)
SELECT c.company_id, g.code, g.name
FROM core.companies c
CROSS JOIN (VALUES ('CUSTOMER', 'مشتری'), ('SUPPLIER', 'تامین‌کننده'), ('PERSONNEL', 'پرسنل')) AS g(code, name)
ON CONFLICT (company_id, code) DO NOTHING;

-- هر شخص (جز ردیفِ سیستمیِ «بدون تفصیلی») باید به یکی از این گروه‌ها تعلق داشته باشد
ALTER TABLE acc.detail_accounts ADD COLUMN person_group_id INT NULL REFERENCES acc.person_groups(person_group_id);

-- کدام معین‌ها به کدام گروه(ها)ی تفصیلی محدودند — اگر معینی هیچ ردیفی در
-- این جدول نداشته باشد، انتخابِ تفصیلی برایش آزاد است (پیش‌فرض «بدون تفصیلی»)؛
-- اگر داشته باشد، فقط اشخاصِ همان گروه(ها) مجازند و «بدون تفصیلی» دیگر کافی نیست.
CREATE TABLE acc.account_person_groups (
    account_id       INT NOT NULL REFERENCES acc.chart_of_accounts(account_id),
    person_group_id  INT NOT NULL REFERENCES acc.person_groups(person_group_id),
    CONSTRAINT pk_account_person_groups PRIMARY KEY (account_id, person_group_id)
);

-- جزئیاتِ تکمیلیِ مشتری
CREATE TABLE acc.customer_details (
    detail_account_id INT PRIMARY KEY REFERENCES acc.detail_accounts(detail_account_id),
    economic_code     VARCHAR(30),
    national_id       VARCHAR(20),
    phone             VARCHAR(30),
    mobile            VARCHAR(30),
    address           VARCHAR(400),
    credit_limit      NUMERIC(18,2),
    notes             VARCHAR(500)
);

-- جزئیاتِ تکمیلیِ تامین‌کننده
CREATE TABLE acc.supplier_details (
    detail_account_id INT PRIMARY KEY REFERENCES acc.detail_accounts(detail_account_id),
    economic_code     VARCHAR(30),
    national_id       VARCHAR(20),
    phone             VARCHAR(30),
    mobile            VARCHAR(30),
    address           VARCHAR(400),
    bank_account_no   VARCHAR(40),
    notes             VARCHAR(500)
);

-- جزئیاتِ تکمیلیِ پرسنل
CREATE TABLE acc.personnel_details (
    detail_account_id INT PRIMARY KEY REFERENCES acc.detail_accounts(detail_account_id),
    national_id       VARCHAR(20),
    personnel_no      VARCHAR(30),
    position_title    VARCHAR(100),
    phone             VARCHAR(30),
    mobile            VARCHAR(30),
    hire_date         DATE,
    bank_account_no   VARCHAR(40),
    notes             VARCHAR(500)
);
