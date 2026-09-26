-- Field Sales: طبقِ درخواستِ صریحِ کاربر («در تنظیمات باید تعریف بشه
-- کدام قیمت برایِ کالاهایِ پخشِ گرم و سرد و حتی تخفیف‌ها و پروموشن‌ها
-- قابلِ‌انتخاب باشه») -- default_price_list_id از قبل رویِ کانال هست
-- ولی هیچ‌جایِ resolve_price خوانده نمی‌شد؛ اکنون هم آن هم این ستونِ
-- تازه در resolve_price استفاده می‌شوند. مثلِ default_price_list_id،
-- این یک پیش‌فرضِ ثابتِ خودِ کانال است (هر کانال حداکثر یک قاعدهٔ
-- تخفیفِ پیش‌فرض) -- اگر خالی بماند، رفتارِ قبلی (بهترین قاعدهٔ
-- scope=ALLِ فعال) دست‌نخورده می‌ماند.
ALTER TABLE comm.channels
    ADD COLUMN default_discount_rule_id INT REFERENCES comm.discount_rules(rule_id);
