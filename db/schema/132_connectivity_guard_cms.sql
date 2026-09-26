-- طبقِ ادامه‌یِ اولویت‌بندی («بررسیِ سلامتِ سایت»): نگهبانِ اتصال (131)
-- فقط فروشِ اینترنتی و تلگرام/بله را پوشش می‌داد -- این‌جا همان سه
-- ستون برایِ اتصال‌هایِ CMS (وردپرس) هم اضافه می‌شود تا بررسیِ سلامتِ
-- «الان» بتواند همه‌یِ اتصال‌ها را یک‌جا آزمایش کند.
ALTER TABLE comm.cms_connections ADD COLUMN consecutive_failure_count INT NOT NULL DEFAULT 0;
ALTER TABLE comm.cms_connections ADD COLUMN last_error_message VARCHAR(500);
ALTER TABLE comm.cms_connections ADD COLUMN last_checked_at TIMESTAMPTZ;
