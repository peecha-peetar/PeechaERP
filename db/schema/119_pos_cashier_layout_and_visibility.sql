-- طبقِ درخواستِ صریح: چیدمانِ دکمه‌هایِ دسترسیِ‌سریع (ترتیب + اندازه)
-- به‌ازایِ هر صندوق‌دار (نه سراسریِ شرکت) ذخیره شود.
ALTER TABLE comm.pos_cashier_settings
    ADD COLUMN quick_button_order TEXT,
    ADD COLUMN quick_button_width_override INT,
    ADD COLUMN quick_button_height_override INT;

-- طبقِ درخواستِ صریح: نمایش/عدمِ‌نمایشِ بخش‌هایِ فاکتورِ تک‌فروشی +
-- تعدادِ فاکتورهایِ اخیر که در پنلِ کنارِ کلیدهایِ فوری نشان داده شود.
ALTER TABLE comm.pos_settings
    ADD COLUMN show_price_list_field BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN show_tax_discount_breakdown BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN show_customer_credit_warning BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN recent_invoices_count INT NOT NULL DEFAULT 10;

-- طبقِ درخواستِ صریح («ارسالِ هم‌زمانِ چند فاکتور به چند پرینترِ
-- مختلف»): هر گروه‌کالایِ POS می‌تواند پرینترِ مقصدِ خودش را داشته
-- باشد -- فاکتوری که اقلامش از چند گروه با پرینترهایِ متفاوت باشند، به
-- هر پرینترِ متمایز فرستاده می‌شود.
ALTER TABLE comm.pos_menu_groups
    ADD COLUMN target_printer_name VARCHAR(200);
