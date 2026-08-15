-- طبقِ آیتمِ ۷ (درخواستِ صریح: «بتونیم روش پرداخت و دریافت خودمون درست
-- کنیم غیر از موارد پیش‌فرض»): روش‌هایِ سفارشیِ هر شرکت — طبقِ توافقِ
-- تاییدشده با کاربر، «ساده» (مثلِ نقد/تخفیف/بن): فقط مبلغ + تفصیلیِ
-- اختیاری، که به یک حسابِ کلِ ثابت (از طریقِ treasury.account_mappings،
-- با mapping_key = '{RECEIPT|PAYMENT}_CUSTOM_{custom_method_id}') می‌رود.
-- custom_method_id به‌عنوانِ بخشی از خودِ mapping_key استفاده می‌شود، پس
-- منحصربه‌فرد بودنِ آن در کلِ جدول (نه فقط هر شرکت) تضمین‌شده است —
-- هیچ برخوردی بینِ شرکت‌هایِ مختلف پیش نمی‌آید.
CREATE TABLE treasury.custom_methods (
    custom_method_id INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id       INT          NOT NULL REFERENCES core.companies(company_id),
    direction        VARCHAR(10)  NOT NULL CHECK (direction IN ('RECEIPT', 'PAYMENT')),
    code             VARCHAR(30)  NOT NULL,
    label            VARCHAR(100) NOT NULL,
    is_active        BOOLEAN      NOT NULL DEFAULT TRUE,
    sort_order       INT          NOT NULL DEFAULT 0,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_treasury_custom_methods UNIQUE (company_id, direction, code)
);
