-- پیچا | آیتمِ ۳ (دورِ جدید): امکانِ تعیینِ تفصیلی (علاوه بر معین) برایِ
-- آیتم‌هایِ حقوقی (مزایا/کسورات)، حسابِ حقوقِ پرداختنی/بانک، و حسابِ
-- هزینهٔ سهمِ کارفرمایِ بیمه — به‌علاوهٔ شرحِ سندِ قابلِ‌ویرایش، هم‌الگو با
-- description_templates خزانه‌داری.

ALTER TABLE payroll.pay_item_definitions
    ADD COLUMN detail_account_id INT REFERENCES acc.detail_accounts(detail_account_id),
    ADD COLUMN description_template VARCHAR(300);

ALTER TABLE payroll.company_settings
    ADD COLUMN salary_payable_detail_account_id INT REFERENCES acc.detail_accounts(detail_account_id);

ALTER TABLE payroll.insurance_configs
    ADD COLUMN employer_expense_detail_account_id INT REFERENCES acc.detail_accounts(detail_account_id);

CREATE TABLE IF NOT EXISTS payroll.description_templates (
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    template_key VARCHAR(30) NOT NULL,
    template_text TEXT NOT NULL,
    PRIMARY KEY (company_id, template_key)
);
