-- طبقِ درخواستِ صریحِ کاربر («ترازوی آفلاین با بارکدِ وزنی برایِ فروشِ
-- حضوری طراحی شود -- بارکد شاملِ چند رقمِ نوع + کدِ کالا + وزن باشد و
-- تعدادِ ارقامِ هر بخش قابلِ‌تنظیم باشد؛ + چارچوبِ اولیه/تنظیماتی برایِ
-- ترازویِ آنلاین که بعداً با پروتکلِ واقعیِ دستگاه تکمیل می‌شود»).

ALTER TABLE comm.pos_settings
    ADD COLUMN weight_barcode_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN weight_barcode_prefix VARCHAR(10) NOT NULL DEFAULT '20',
    ADD COLUMN weight_barcode_item_code_digits SMALLINT NOT NULL DEFAULT 5,
    ADD COLUMN weight_barcode_weight_digits SMALLINT NOT NULL DEFAULT 4,
    ADD COLUMN weight_barcode_weight_decimals SMALLINT NOT NULL DEFAULT 3,
    -- طبقِ توافقِ صریح («فعلاً چارچوبِ اولیه/تنظیماتی»): پروتکلِ واقعیِ
    -- ارتباط با ترازویِ آنلاین (سریال/TCP/...) هنوز پیاده‌سازی نشده --
    -- این ستون‌ها فقط تنظیماتِ لازم برایِ آن را نگه می‌دارند.
    ADD COLUMN scale_online_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN scale_connection_type VARCHAR(20) NOT NULL DEFAULT 'NONE',
    ADD COLUMN scale_address VARCHAR(200),
    ADD COLUMN scale_batch_barcode_prefix VARCHAR(10) NOT NULL DEFAULT '21';
