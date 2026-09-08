-- طبقِ درخواستِ صریح («زمان‌بندیِ خودکارِ سینک»): هر اتصالِ فروشگاهی
-- می‌تواند مستقل از بقیه، سینکِ خودکار را روشن/خاموش کند و فاصله‌یِ
-- زمانیِ دلخواهِ خودش را داشته باشد -- فازِ ۱ عمداً فقط دستی بود.
ALTER TABLE comm.marketplace_connections
    ADD COLUMN auto_sync_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN auto_sync_interval_minutes INTEGER NOT NULL DEFAULT 60;
