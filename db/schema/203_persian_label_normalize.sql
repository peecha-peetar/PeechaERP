-- R277: برچسب‌هایِ سیستمیِ فارسی بدونِ کسرهٔ اضافه (ه‌یِ → هٔ). فقط جدول‌هایِ تعریفِ سیستم؛ داده‌یِ کاربر دست نمی‌خورد.
UPDATE inv.feature_definitions SET name = replace(replace(name, 'ه‌یِ', 'هٔ'), 'ِ', '') WHERE name LIKE '%ِ%';
UPDATE inv.feature_definitions SET description = replace(replace(description, 'ه‌یِ', 'هٔ'), 'ِ', '') WHERE description LIKE '%ِ%';
UPDATE comm.feature_definitions SET name = replace(replace(name, 'ه‌یِ', 'هٔ'), 'ِ', '') WHERE name LIKE '%ِ%';
UPDATE comm.industry_profiles SET name = replace(replace(name, 'ه‌یِ', 'هٔ'), 'ِ', '') WHERE name LIKE '%ِ%';
UPDATE hr.lookup_values SET name = replace(replace(name, 'ه‌یِ', 'هٔ'), 'ِ', '') WHERE company_id IS NULL AND name LIKE '%ِ%';
UPDATE acc.detail_group_fields SET label = replace(replace(label, 'ه‌یِ', 'هٔ'), 'ِ', '') WHERE label LIKE '%ِ%';
UPDATE comm.feature_definitions SET description = replace(replace(description, 'ه‌یِ', 'هٔ'), 'ِ', '') WHERE description LIKE '%ِ%';
UPDATE comm.feature_definitions SET name = replace(name, 'ریبیت', 'تخفیف حجمی') WHERE name LIKE '%ریبیت%';
UPDATE inv.feature_definitions SET name = replace(name, 'تأیید', 'تایید') WHERE name LIKE '%تأیید%';
