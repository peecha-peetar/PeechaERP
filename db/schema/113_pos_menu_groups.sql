-- طبقِ بازخوردِ صریح («کالا باید یک فیلدِ دسته‌بندیِ مخصوصِ POS داشته
-- باشه که با دسته‌بندی‌هایِ دیگه فرق بکنه»): برخلافِ دسته‌بندیِ عمومیِ
-- انبار (inv.item_categories که برایِ سلسله‌مراتبِ کاردکس/گزارش است)،
-- این یک گروه‌بندیِ کاملاً مستقل و تخت -- فقط برایِ چیدمانِ تب‌هایِ
-- دسترسیِ‌سریعِ صفحه‌یِ فروشِ حضوری -- است، معادلِ ستونِ «تعیینِ گروهِ
-- کالاهایِ فروشگاه» در نمونه‌یِ ارجاعیِ کاربر.
CREATE TABLE comm.pos_menu_groups (
    group_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id BIGINT NOT NULL REFERENCES core.companies(company_id),
    name VARCHAR(100) NOT NULL,
    display_order INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

ALTER TABLE inv.items
    ADD COLUMN pos_menu_group_id BIGINT REFERENCES comm.pos_menu_groups(group_id);

-- طبقِ درخواستِ صریح («اندازه/جهتِ کلیدهایِ فوری قابلِ‌تنظیم باشد»،
-- هم‌الگو با تبِ «تنظیمِ منو»یِ نمونه‌یِ ارجاعی): این‌ها روی همان
-- comm.pos_settingsِ ازپیش‌موجود (تنظیماتِ سراسریِ POSِ هرشرکت) اضافه
-- می‌شوند -- نه یک جدولِ تازه.
ALTER TABLE comm.pos_settings
    ADD COLUMN quick_button_width INTEGER NOT NULL DEFAULT 110,
    ADD COLUMN quick_button_height INTEGER NOT NULL DEFAULT 64,
    ADD COLUMN quick_button_font_size INTEGER NOT NULL DEFAULT 10,
    ADD COLUMN quick_grid_columns INTEGER NOT NULL DEFAULT 6;
