-- طبقِ گزارشِ صریح: «اگر یک چکِ دریافتی را حذف کنم، کلِ سندِ مربوطه حذف
-- می‌شود، در صورتی که ممکن است در همان سند روش‌هایِ دیگری هم (نقد،
-- چکِ دیگر و ...) بوده باشند — باید فقط سطرِ همان چک از سند و مبلغِ
-- کلِ سند اصلاح شود، نه کلِ سند حذف شود». برایِ این‌که services/treasury.py
-- بتواند دقیقاً بفهمد کدام ردیفِ سند (line_no) متعلق به کدام چک بوده،
-- همان شماره‌ی ردیف در لحظه‌ی ساختِ سند (create_treasury_voucher) این‌جا
-- ذخیره می‌شود.

ALTER TABLE treasury.received_checks
    ADD COLUMN source_journal_entry_line_no SMALLINT NULL;

ALTER TABLE treasury.issued_checks
    ADD COLUMN source_journal_entry_line_no SMALLINT NULL;
