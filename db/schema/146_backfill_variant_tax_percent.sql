-- طبقِ رفعِ باگِ واقعیِ گزارش‌شده («درصدِ مالیاتِ کالایِ مادر که متغیر
-- دارد، برایِ خودِ متغیرها در فاکتور/فروشِ حضوری محاسبه نمی‌شود»): تا پیش
-- از این، هم item_variants.generate_item_variants و هم بخشِ همگام‌سازیِ
-- inventory_catalog.update_item، فیلدِ default_tax_percent را از کالایِ
-- اصلی به متغیرها کپی نمی‌کردند -- پس متغیرها همیشه default_tax_percent
-- خالی داشتند و resolve_default_tax_percent (وقتی شرکت/انبار هم مالیاتِ
-- خاصی تنظیم نکرده باشند) برایِ آن‌ها به صفر سقوط می‌کرد. این تصحیحِ
-- یک‌بارهٔ داده، برایِ متغیرهایی که از قبل ساخته شده‌اند و هنوز خودشان
-- درصدِ مالیاتِ مجزا ندارند (NULL)، همان مقدارِ فعلیِ کالایِ مادرشان را
-- کپی می‌کند.

UPDATE inv.items AS variant
SET default_tax_percent = parent.default_tax_percent
FROM inv.items AS parent
WHERE variant.variant_parent_item_id = parent.item_id
  AND variant.default_tax_percent IS NULL
  AND parent.default_tax_percent IS NOT NULL;
