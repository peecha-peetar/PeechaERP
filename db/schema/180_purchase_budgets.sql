-- پیچا R243: بودجهٔ خرید -- فقط افزایشی. هر بودجه یک مبلغ برایِ یک دوره و ترکیبی اختیاری از
-- مرکزِ هزینه / پروژه / گروهِ کالا است (بُعدِ خالی = همه). مصرف همیشه از اسناد محاسبه می‌شود:
-- واقعی = فاکتورِ خریدِ ثبت‌شده − برگشت؛ تعهد = ماندهٔ فاکتورنشدهٔ سفارش‌هایِ باز. کنترل فقط هشدار است.
--
-- بازگشت (rollback): DROP TABLE IF EXISTS comm.purchase_budgets;

CREATE TABLE IF NOT EXISTS comm.purchase_budgets (
    budget_id SERIAL PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    code VARCHAR(30) NOT NULL,
    name VARCHAR(150) NOT NULL,
    period_from DATE NOT NULL,
    period_to DATE NOT NULL,
    cost_center_detail_account_id INT NULL REFERENCES acc.detail_accounts(detail_account_id),
    project_detail_account_id INT NULL REFERENCES acc.detail_accounts(detail_account_id),
    category_id INT NULL REFERENCES inv.item_categories(category_id),
    amount NUMERIC(18,2) NOT NULL CHECK (amount >= 0),
    warn_percent NUMERIC(5,2) NOT NULL DEFAULT 90,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    note TEXT NULL,
    CHECK (period_to >= period_from),
    UNIQUE (company_id, code)
);
