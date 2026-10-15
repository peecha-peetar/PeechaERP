-- R273: هر دارایی ثابت یک حسابِ تفصیلی از نوعِ «دارایی ثابت» (FIXED_ASSET) دارد -- هم‌الگو با تفصیلیِ کالا.
-- ساختِ تفصیلی برای دارایی‌هایِ موجود در کد (fixed_assets.common.ensure_asset_detail) انجام می‌شود
-- تا قواعدِ طول/بازهٔ کدِ تفصیلی رعایت شود؛ این فایل فقط ستون را اضافه می‌کند.
ALTER TABLE fa.assets ADD COLUMN IF NOT EXISTS detail_account_id INT NULL REFERENCES acc.detail_accounts(detail_account_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_fa_assets_detail_account ON fa.assets (detail_account_id) WHERE detail_account_id IS NOT NULL;
