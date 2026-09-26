-- طبقِ درخواستِ صریح: در فرمِ «نحوهٔ تسویه»یِ تک‌فروشی، جلویِ هر روش یک
-- فیلدِ انتخابِ تفصیلی (همیشه یک ستونِ ثابت در جدول) اضافه شود؛ اگر
-- تفصیلیِ پیش‌فرضِ همان روش در تنظیمات از قبل مشخص شده باشد از همان‌جا
-- خوانده شود، وگرنه صندوق‌دار همان لحظه انتخاب می‌کند.

ALTER TABLE comm.commercial_document_settlement_plan_lines
    ADD COLUMN detail_account_id INT REFERENCES acc.detail_accounts(detail_account_id);

-- پیش‌فرضِ تفصیلی (+ مرکزِ هزینه/پروژه، اگر معینِ همان روش این ابعاد را
-- الزامی کرده باشد) به‌ازایِ هر روشِ دریافت/پرداختِ تک‌فروشی -- تا هربار
-- در لحظهٔ ثبتِ فروش پرسیده نشود.
CREATE TABLE comm.pos_settlement_method_defaults (
    default_id BIGSERIAL PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    method_code VARCHAR(30) NOT NULL,
    detail_account_id INT REFERENCES acc.detail_accounts(detail_account_id),
    cost_center_detail_account_id INT REFERENCES acc.detail_accounts(detail_account_id),
    project_detail_account_id INT REFERENCES acc.detail_accounts(detail_account_id),
    UNIQUE (company_id, method_code)
);
