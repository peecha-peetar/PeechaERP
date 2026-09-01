-- طبقِ درخواستِ صریح: فرمِ تسهیمِ هزینه‌هایِ جانبیِ خرید (ترخیص/گمرک/
-- هزینه‌هایِ ارزیِ دیگر) رویِ خودِ فاکتورِ خرید. هر ردیفِ هزینه یک مبلغ و
-- یک حسابِ معین+تفصیلیِ مشخص دارد که باید بستانکار شود (مثلاً یک تفصیلیِ
-- گروهِ «سفارشاتِ در راه») -- نه یک دسته‌بندیِ ثابت/روشِ تسهیمِ از پیش
-- تعریف‌شده. جمعِ این هزینه‌ها با تسهیمِ متناسب با ارزشِ ردیف‌ها به بهایِ
-- موجودیِ کالا (و بهایِ تمام‌شدهٔ آیندهٔ همان کالا) اضافه می‌شود -- همراهِ
-- خودِ سندِ حسابداریِ فاکتورِ خرید.
ALTER TABLE comm.landed_cost_allocations
    ALTER COLUMN cost_type_code DROP NOT NULL,
    ALTER COLUMN allocation_method_code DROP NOT NULL,
    ADD COLUMN credit_account_id BIGINT NULL REFERENCES acc.chart_of_accounts(account_id),
    ADD COLUMN credit_detail_account_id BIGINT NULL REFERENCES acc.detail_accounts(detail_account_id);

ALTER TABLE inv.stock_document_lines
    ADD COLUMN landed_cost_amount NUMERIC(18,2) NOT NULL DEFAULT 0;
