-- پیچا R244: شعبه، دپارتمان (واحدِ سازمانیِ موجودِ hr) و نماهایِ مشترکِ گزارش -- فقط افزایشی.
-- دپارتمان = hr.organizational_units (از قبل موجود). شعبه جدولِ تازه است و انبار می‌تواند به یک شعبه تعلق داشته باشد
-- (سندِ بدونِ شعبه، شعبهٔ انبارش را می‌گیرد).
--
-- بازگشت (rollback):
--   ALTER TABLE comm.commercial_documents DROP COLUMN IF EXISTS branch_id, DROP COLUMN IF EXISTS org_unit_id;
--   ALTER TABLE comm.purchase_requests DROP COLUMN IF EXISTS branch_id, DROP COLUMN IF EXISTS org_unit_id;
--   ALTER TABLE comm.purchase_budgets DROP COLUMN IF EXISTS branch_id, DROP COLUMN IF EXISTS org_unit_id;
--   ALTER TABLE inv.warehouses DROP COLUMN IF EXISTS branch_id;
--   DROP TABLE IF EXISTS comm.report_views, comm.branches;

CREATE TABLE IF NOT EXISTS comm.branches (
    branch_id SERIAL PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    code VARCHAR(30) NOT NULL,
    name VARCHAR(150) NOT NULL,
    address TEXT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (company_id, code)
);

ALTER TABLE inv.warehouses ADD COLUMN IF NOT EXISTS branch_id INT NULL REFERENCES comm.branches(branch_id);

ALTER TABLE comm.commercial_documents
    ADD COLUMN IF NOT EXISTS branch_id INT NULL REFERENCES comm.branches(branch_id),
    ADD COLUMN IF NOT EXISTS org_unit_id INT NULL REFERENCES hr.organizational_units(org_unit_id);
ALTER TABLE comm.purchase_requests
    ADD COLUMN IF NOT EXISTS branch_id INT NULL REFERENCES comm.branches(branch_id),
    ADD COLUMN IF NOT EXISTS org_unit_id INT NULL REFERENCES hr.organizational_units(org_unit_id);
ALTER TABLE comm.purchase_budgets
    ADD COLUMN IF NOT EXISTS branch_id INT NULL REFERENCES comm.branches(branch_id),
    ADD COLUMN IF NOT EXISTS org_unit_id INT NULL REFERENCES hr.organizational_units(org_unit_id);

-- نماهایِ ذخیره‌شدهٔ گزارش (فیلتر/گزینه/مرتب‌سازی/گروه‌بندی/ستون‌ها) -- شخصی یا اشتراکی
CREATE TABLE IF NOT EXISTS comm.report_views (
    view_id BIGSERIAL PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    report_key VARCHAR(80) NOT NULL,
    name VARCHAR(100) NOT NULL,
    owner_user_id INT NOT NULL REFERENCES sec.users(user_id),
    is_shared BOOLEAN NOT NULL DEFAULT FALSE,
    payload TEXT NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (company_id, report_key, owner_user_id, name)
);
