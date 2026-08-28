-- طبقِ درخواستِ صریح: در تنظیماتِ روش‌هایِ دریافت، فقط یک معین قابلِ‌انتخاب
-- بود — حالا برایِ هر mapping_key بشود چند معین تنظیم کرد؛ موقعِ ثبتِ سند،
-- تفصیلی‌هایِ همه‌یِ آن معین‌ها با هم (union) در جست‌وجو نمایش داده می‌شود.
-- کلیدِ اصلیِ (company_id, mapping_key) به (company_id, mapping_key, account_id)
-- شل می‌شود تا چند ردیف برایِ یک کلید مجاز باشد؛ detail_account_id (از
-- migration ۰۳۱) همچنان اختیاری و مالِ همان ردیف/همان معین است.
ALTER TABLE treasury.account_mappings
    DROP CONSTRAINT pk_treasury_account_mappings;

ALTER TABLE treasury.account_mappings
    ADD CONSTRAINT pk_treasury_account_mappings PRIMARY KEY (company_id, mapping_key, account_id);
