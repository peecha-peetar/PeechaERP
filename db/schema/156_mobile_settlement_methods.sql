-- Field Sales: طبقِ درخواستِ صریحِ کاربر («نوعِ تسویه در پخشِ گرم باید
-- همانندِ انواعِ تسویه در دسکتاپ باشد و فقط جایی باید باشد که انواعِ
-- تسویهٔ دسکتاپ را برایِ موبایل هم انتخاب کنیم -- ممکنه بعضی نیاز
-- نباشه»): قبلاً فاکتورِ موبایل همیشه خودکار ۱۰۰٪ «نقدی» فرض می‌شد
-- (auto_approve_full_cash_settlement_plan) -- این جدول نشان می‌دهد
-- کدام‌یک از روش‌هایِ واقعیِ تسویهٔ همین شرکت
-- (commercial_settlements.settlement_plan_method_codes) برایِ موبایل
-- هم فعال باشند. پیش‌فرض (بدونِ ردیف): فعال -- تا شرکتِ تازه بدونِ
-- هیچ تنظیمِ اضافه‌ای، همان رفتارِ کاملِ دسکتاپ را رویِ موبایل ببیند؛
-- مدیر فقط روش‌هایِ نامربوط را خاموش می‌کند.

CREATE TABLE comm.mobile_settlement_methods (
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    method_code VARCHAR(30) NOT NULL,
    is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (company_id, method_code)
);
