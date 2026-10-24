-- R336: «جدید» به‌جای «تازه» در متن تنظیمات ثبت‌شده (فقط متن نمایشی؛ کد و رفتار تغییر نمی‌کند).
UPDATE inv.feature_definitions SET name = 'تایید کالای جدید' WHERE feature_code = 'NEW_ITEM_APPROVAL' AND name = 'تایید کالای تازه';
UPDATE inv.feature_definitions SET description = replace(replace(description, 'تازه‌ای', 'جدیدی'), 'تازه', 'جدید')
 WHERE feature_code IN ('NEW_ITEM_APPROVAL', 'REPORT_PRO_TEMPLATES') AND description LIKE '%تازه%';
