-- طبقِ درخواستِ صریحِ کاربر («سیاستِ محاسبهٔ مالیات: اگر رویِ تنظیماتِ
-- شرکت بود برایِ همه لحاظ کند؛ اگر شرکت تنظیم نداشت رویِ انبار، و اگر
-- انبار نداشت رویِ کالا نگاه کند؛ + امکانِ کنسل‌کردنِ مالیات رویِ
-- فاکتور»): اولویتِ resolve_default_tax_percent از «کالا -> شرکت» به
-- «شرکت -> انبار -> کالا» تغییر می‌کند -- برایِ همین یک درصدِ مالیاتِ
-- پیش‌فرض در سطحِ انبار هم لازم است؛ و یک پرچمِ معافیتِ مالیاتی در سطحِ
-- خودِ سند.

ALTER TABLE inv.warehouses
    ADD COLUMN default_tax_percent NUMERIC(5, 2);

ALTER TABLE comm.commercial_documents
    ADD COLUMN tax_exempt BOOLEAN NOT NULL DEFAULT FALSE;
