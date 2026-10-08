-- طبقِ درخواستِ صریحِ کاربر («متغیرها دیگر بعنوانِ تفصیلی معرفی نشوند،
-- در یک جدولِ مستقل با کدبندیِ متفاوت ذخیره شوند»): تا این‌جا هر متغیرِ
-- کالا صرفاً یک ردیفِ کاملاً مستقلِ acc.detail_accounts بود (هم‌سطح و
-- هم‌گروهِ کالایِ اصلی) که خودش باعثِ چند دور باگِ تکراری شد (یتیم‌شدنِ
-- متغیر از کالای اصلی، امکانِ انتخاب/ویرایشِ مستقیمِ آن در درختِ
-- تفصیلی‌ها). بررسیِ دقیق نشان داد تنها زیرسیستمی که واقعاً به وجودِ
-- یک ردیفِ acc.detail_accounts برایِ هر کالا وابسته است، threadingِ
-- بُعدِ حسابداری در سندهای حسابداری است (acc.journal_entry_line_
-- details.detail_account_id) -- موجودی/کاردکس/قیمت‌گذاری/فروشگاهِ
-- اینترنتی/POS/تلیفروشی همه فقط با item_id کار می‌کنند. پس این جدول
-- هویتِ واقعی/قابلِ‌مدیریتِ متغیر را نگه می‌دارد (کدِ مستقل، ارتباط با
-- کالای اصلی)، بدونِ نیاز به لمسِ FKِ inv.items.item_detail_account_id
-- یا هیچ‌یک از زیرسیستم‌هایِ بالا -- ردیفِ acc.detail_accounts هر
-- متغیر همچنان در پس‌زمینه وجود دارد (برایِ همان threadingِ حسابداری)
-- ولی دیگر هرگز مستقیماً در UIِ تفصیلی‌ها (detail_dimensions.py)
-- نمایش داده نمی‌شود.
CREATE TABLE inv.item_variants (
    item_id       INT NOT NULL PRIMARY KEY REFERENCES inv.items(item_id) ON DELETE CASCADE,
    variant_code  VARCHAR(40) NOT NULL,
    display_order SMALLINT NOT NULL DEFAULT 0
);

-- طبقِ الگویِ suggest_next_code فعلی (که بر اساسِ parent_item_id +
-- شمارهٔ ترتیبی کدِ تازه می‌سازد): یکتاییِ کد فقط در میانِ متغیرهایِ
-- همان کالای اصلی معنا دارد، نه سراسری -- پس یکتایی رویِ
-- (parent_item_id, variant_code) تعریف می‌شود، نه فقط variant_code.
ALTER TABLE inv.item_variants ADD COLUMN parent_item_id INT NOT NULL REFERENCES inv.items(item_id);
CREATE UNIQUE INDEX uq_inv_item_variants_parent_code ON inv.item_variants(parent_item_id, variant_code);

-- بک‌فیلِ متغیرهایِ ازپیش‌موجود (از دورهایِ قبلِ این تغییر): variant_code
-- از رویِ همان کدِ فعلیِ acc.detail_accounts کپی می‌شود -- تا کدهایی که
-- ممکن است از قبل در سندهایِ ثبت‌شده/گزارش‌ها دیده شده باشند، تغییر نکنند.
INSERT INTO inv.item_variants (item_id, parent_item_id, variant_code, display_order)
SELECT it.item_id, it.variant_parent_item_id, da.code, 0
FROM inv.items it
JOIN acc.detail_accounts da ON da.detail_account_id = it.item_detail_account_id
WHERE it.variant_parent_item_id IS NOT NULL
ON CONFLICT DO NOTHING;
