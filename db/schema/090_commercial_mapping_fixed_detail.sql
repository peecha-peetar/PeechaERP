-- پیچا | طبقِ درخواستِ صریح («برایِ فاکتورِ فروش هم برایِ تفصیلیِ
-- مالیات بشه یک تفصیلیِ ثابت تعریف کرد، مثلِ فاکتورِ خرید») -- همان
-- ستونِ inv.account_mappings.detail_account_id (رفعِ راندِ قبل)، این‌بار
-- برایِ comm.account_mappings (SALES_REVENUE/SALES_TAX_PAYABLE/
-- SALES_DISCOUNT/...) که یک جدولِ کاملاً جداست.

ALTER TABLE comm.account_mappings
    ADD COLUMN detail_account_id INT NULL REFERENCES acc.detail_accounts(detail_account_id);
