-- طبقِ درخواستِ صریحِ کاربر: دو نوعِ ثبتِ حسابداری برایِ فاکتورِ خرید/فروش --
-- «رسمی» (پیش‌فرض، رفتارِ فعلی): مالیات در یک ردیفِ جداگانه (مالياتِ
-- خرید-دریافتنی/فروش-پرداختنی) ثبت می‌شود، بدونِ ورود به ارزشِ موجودی/
-- درآمد. «غیررسمی»: مالیات جداگانه ثبت نمی‌شود -- در فاکتورِ خرید به
-- ارزشِ موجودیِ کالا و در فاکتورِ فروش به مبلغِ درآمد افزوده می‌شود (اگر
-- مالياتی نباشد، دو حالت یکسان‌اند).
--
-- Feature Toggleِ سراسری (پیش‌فرضِ شرکت، طبقِ همان الگویِ PER_LINE_WAREHOUSE)
-- + ستونِ override رویِ خودِ سند (NULL یعنی از پیش‌فرضِ شرکت پیروی کن).
INSERT INTO comm.feature_definitions (feature_code, name, module_scope, requires_feature_code, requires_account_mapping_keys) VALUES
    ('INFORMAL_TAX_POSTING', 'ثبتِ غیررسمی (بدونِ ردیفِ جداگانهٔ مالیات) به‌عنوانِ پیش‌فرضِ فاکتورهایِ خرید/فروش', 'COMMERCIAL', NULL, NULL);

ALTER TABLE comm.commercial_documents
    ADD COLUMN tax_posting_mode VARCHAR(10) NULL
    CHECK (tax_posting_mode IN ('OFFICIAL', 'INFORMAL'));
