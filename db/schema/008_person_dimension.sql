-- پیچا | تفصیلیِ اشخاص به‌عنوانِ بُعدِ سیستمی/همیشه‌حاضر (جدا از ابعادِ
-- اختیاری مثلِ مرکزِ هزینه/پروژه که کاربر خودش می‌سازد): هر شرکت یک
-- نوع‌بُعدِ رزروشده با کدِ PERSON دارد + یک حسابِ تفصیلیِ پیش‌فرضِ
-- «بدون تفصیلی» — تا هر ردیفِ سند، چه شخصی روی آن انتخاب شده باشد چه نه،
-- همیشه یک کدِ تفصیلی داشته باشد و ترازِ سطحِ تفصیلی کامل درآید.
-- پیش‌نیاز: 003_accounting_core.sql

-- نام آزادِ حسابِ تفصیلی — برای اشخاص که با نام شناخته می‌شوند نه فقط کد
ALTER TABLE acc.detail_accounts ADD COLUMN name VARCHAR(200) NULL;

-- نوع‌بُعدِ سیستمیِ اشخاص برای هر شرکتِ موجود (شرکت‌های تازه از طریقِ
-- سرویسِ bootstrap/companies همین را در لحظه‌ی ساختِ شرکت می‌سازند)
INSERT INTO acc.detail_dimension_types (company_id, code, is_active)
SELECT company_id, 'PERSON', TRUE FROM core.companies
ON CONFLICT (company_id, code) DO NOTHING;

-- حسابِ تفصیلیِ پیش‌فرضِ «بدون تفصیلی» برای همان نوع‌بُعد
INSERT INTO acc.detail_accounts (company_id, dimension_type_id, code, name, is_active)
SELECT ddt.company_id, ddt.dimension_type_id, 'NONE', 'بدون تفصیلی', TRUE
FROM acc.detail_dimension_types ddt
WHERE ddt.code = 'PERSON'
ON CONFLICT (company_id, dimension_type_id, code) DO NOTHING;
