-- طبقِ درخواستِ صریح («سیستمِ فاکتورِ امانی، هردو جهت»): امانیِ خروجی
-- (CONSIGNMENT_OUT) به دو انبار نیاز دارد -- انبارِ مبدا (همان ستونِ
-- warehouse_id ازپیش‌موجود) و انبارِ مقصد/امانتِ نزدِ طرفِ‌حساب (این
-- ستونِ تازه) -- چون کالا در این لحظه هنوز مالِ شرکت است، فقط فیزیکی
-- جابه‌جا می‌شود (TRANSFER، بدونِ اثرِ حسابداری). برایِ امانیِ ورودی
-- (CONSIGNMENT_IN) از همان warehouse_id به‌عنوانِ انبارِ نگه‌داری استفاده
-- می‌شود و این ستون بلااستفاده می‌ماند.
ALTER TABLE comm.commercial_documents ADD COLUMN consignment_warehouse_id BIGINT NULL REFERENCES inv.warehouses(warehouse_id);

-- طبقِ همان نیاز: مانده‌یِ هر ردیفِ امانی (خروجی/ورودی) = quantity منهایِ
-- «تسویه‌شده» (از طریقِ source_line_id، مکانیزمِ ازپیش‌موجودِ
-- سفارش/پیش‌فاکتور) منهایِ «بازگردانده‌شده» -- این دومی جایِ دیگری
-- ردیابی نمی‌شد (بازگشتِ امانی یک TRANSFERِ خامِ بدونِ source_line_id
-- است، نه یک سندِ بازرگانیِ تازه)، پس همین‌جا روی خودِ ردیف نگه‌داری
-- می‌شود.
ALTER TABLE comm.commercial_document_lines ADD COLUMN returned_quantity NUMERIC(18, 6) NOT NULL DEFAULT 0;
