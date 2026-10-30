-- پیچا | R348: کدهای سامانهٔ مودیان روی کالا و واحد سنجش
-- پیش‌نیاز: inv.items، inv.uom

ALTER TABLE inv.items ADD COLUMN IF NOT EXISTS moadian_stuff_id VARCHAR(13) NULL;  -- شناسهٔ کالا/خدمت
ALTER TABLE inv.uom ADD COLUMN IF NOT EXISTS moadian_unit_code VARCHAR(10) NULL;   -- کد واحد سنجش سامانه
