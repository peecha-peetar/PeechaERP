-- پیچا | R380: کانال ایمیل (SMTP) در تنظیمات پیام‌رسان‌ها — همان جدول و رمزنگاری توکن ربات‌ها، با مشخصات سرور ایمیل
ALTER TABLE crm.messenger_settings DROP CONSTRAINT IF EXISTS messenger_settings_channel_check;
ALTER TABLE crm.messenger_settings ADD CONSTRAINT messenger_settings_channel_check
    CHECK (channel IN ('BALE', 'TELEGRAM', 'EITAA', 'RUBIKA', 'WHATSAPP', 'EMAIL'));
