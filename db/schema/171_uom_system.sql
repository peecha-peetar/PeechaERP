-- پیچا | سیستمِ کاملِ واحدِ اندازه‌گیری، واحدهایِ چندگانهٔ کالا، بسته‌بندی و بارکدِ هر واحد (R225).
-- هیچ داده‌ای حذف یا تغییرِ معنا نمی‌دهد: فقط ستون/جدولِ تازه + انتقالِ اطلاعاتِ فعلی.

-- ۱. Masterِ واحد ---------------------------------------------------------
ALTER TABLE inv.uom DROP CONSTRAINT IF EXISTS uom_uom_type_code_check;
ALTER TABLE inv.uom ADD CONSTRAINT ck_inv_uom_type
    CHECK (uom_type_code IN ('COUNT', 'WEIGHT', 'VOLUME', 'LENGTH', 'AREA', 'TIME', 'PACKAGING', 'OTHER'));
ALTER TABLE inv.uom
    ADD COLUMN symbol            VARCHAR(20)   NULL,
    ADD COLUMN base_uom_id       INT           NULL REFERENCES inv.uom(uom_id),
    ADD COLUMN conversion_factor NUMERIC(18,6) NOT NULL DEFAULT 1 CHECK (conversion_factor > 0),
    ADD COLUMN allow_decimal     BOOLEAN       NOT NULL DEFAULT TRUE,
    ADD COLUMN is_system         BOOLEAN       NOT NULL DEFAULT FALSE,
    ADD COLUMN description       TEXT          NULL,
    ADD COLUMN created_at        TIMESTAMP     NOT NULL DEFAULT now(),
    ADD COLUMN updated_at        TIMESTAMP     NOT NULL DEFAULT now();
UPDATE inv.uom SET allow_decimal = (decimal_places > 0);

-- واحدهایِ سیستمیِ استاندارد -- فقط اگر کدِ هم‌نام در هیچ شرکتی وجود نداشته باشد.
CREATE TEMP TABLE _std_uom (code VARCHAR(20), name VARCHAR(50), symbol VARCHAR(20), uom_type_code VARCHAR(10),
                            base_code VARCHAR(20), factor NUMERIC(18,6), dp SMALLINT, ord INT);
INSERT INTO _std_uom VALUES
    ('PCS',  'عدد',        'عدد', 'COUNT',     NULL,  1,       0, 1),
    ('G',    'گرم',        'g',   'WEIGHT',    NULL,  1,       0, 2),
    ('KG',   'کیلوگرم',    'kg',  'WEIGHT',    'G',   1000,    3, 3),
    ('TON',  'تن',         't',   'WEIGHT',    'G',   1000000, 3, 4),
    ('MM',   'میلی‌متر',   'mm',  'LENGTH',    NULL,  1,       0, 5),
    ('CM',   'سانتی‌متر',  'cm',  'LENGTH',    'MM',  10,      1, 6),
    ('M',    'متر',        'm',   'LENGTH',    'MM',  1000,    2, 7),
    ('M2',   'مترمربع',    'm²',  'AREA',      NULL,  1,       2, 8),
    ('ML',   'میلی‌لیتر',  'ml',  'VOLUME',    NULL,  1,       0, 9),
    ('L',    'لیتر',       'L',   'VOLUME',    'ML',  1000,    3, 10),
    ('M3',   'مترمکعب',    'm³',  'VOLUME',    'ML',  1000000, 3, 11),
    ('HR',   'ساعت',       'h',   'TIME',      NULL,  1,       2, 12),
    ('PACK', 'بسته',       NULL,  'PACKAGING', NULL,  1,       0, 13),
    ('BOX',  'جعبه',       NULL,  'PACKAGING', NULL,  1,       0, 14),
    ('CTN',  'کارتن',      NULL,  'PACKAGING', NULL,  1,       0, 15),
    ('PLT',  'پالت',       NULL,  'PACKAGING', NULL,  1,       0, 16),
    ('ROLL', 'رول',        NULL,  'PACKAGING', NULL,  1,       0, 17),
    ('BTL',  'بطری',       NULL,  'PACKAGING', NULL,  1,       0, 18),
    ('CAN',  'قوطی',       NULL,  'PACKAGING', NULL,  1,       0, 19);
INSERT INTO inv.uom (company_id, code, name, symbol, uom_type_code, decimal_places, allow_decimal, is_system, conversion_factor)
SELECT NULL, s.code, s.name, s.symbol, s.uom_type_code, s.dp, s.dp > 0, TRUE, s.factor
FROM _std_uom s
WHERE NOT EXISTS (SELECT 1 FROM inv.uom u WHERE u.code = s.code)
ORDER BY s.ord;
UPDATE inv.uom u SET base_uom_id = b.uom_id
FROM _std_uom s JOIN inv.uom b ON b.code = s.base_code AND b.company_id IS NULL
WHERE u.code = s.code AND u.company_id IS NULL AND u.is_system AND s.base_code IS NOT NULL;
DROP TABLE _std_uom;

-- ۲. واحدهایِ مجازِ هر کالا (گسترشِ inv.item_uom_conversions = item_units) -----
ALTER TABLE inv.item_uom_conversions
    ADD COLUMN is_base_unit      BOOLEAN       NOT NULL DEFAULT FALSE,
    ADD COLUMN is_purchase_unit  BOOLEAN       NOT NULL DEFAULT TRUE,
    ADD COLUMN is_sales_unit     BOOLEAN       NOT NULL DEFAULT TRUE,
    ADD COLUMN is_inventory_unit BOOLEAN       NOT NULL DEFAULT FALSE,
    ADD COLUMN decimal_places    SMALLINT      NULL,
    ADD COLUMN min_quantity      NUMERIC(18,6) NULL,
    ADD COLUMN max_quantity      NUMERIC(18,6) NULL,
    ADD COLUMN weight_kg         NUMERIC(12,4) NULL,
    ADD COLUMN volume_m3         NUMERIC(12,6) NULL,
    ADD COLUMN is_active         BOOLEAN       NOT NULL DEFAULT TRUE,
    ADD COLUMN sort_order        INT           NOT NULL DEFAULT 0,
    ADD COLUMN created_at        TIMESTAMP     NOT NULL DEFAULT now(),
    ADD COLUMN updated_at        TIMESTAMP     NOT NULL DEFAULT now();

-- واحدِ پایهٔ هر کالایِ موجود به‌عنوانِ ردیفِ پایه (ضریبِ ۱)؛ اگر برایِ کالا
-- هیچ پیش‌فرضِ خرید/فروشی تعریف نشده بود، همین واحدِ پایه پیش‌فرض می‌شود.
INSERT INTO inv.item_uom_conversions
    (item_id, uom_id, conversion_factor, is_base_unit, is_inventory_unit, is_purchase_default, is_sales_default, sort_order)
SELECT i.item_id, i.base_uom_id, 1, TRUE, TRUE,
       NOT EXISTS (SELECT 1 FROM inv.item_uom_conversions c WHERE c.item_id = i.item_id AND c.is_purchase_default),
       NOT EXISTS (SELECT 1 FROM inv.item_uom_conversions c WHERE c.item_id = i.item_id AND c.is_sales_default),
       0
FROM inv.items i
ON CONFLICT (item_id, uom_id) DO UPDATE SET is_base_unit = TRUE, is_inventory_unit = TRUE, conversion_factor = 1;
UPDATE inv.item_uom_conversions c SET sort_order = 1 WHERE NOT c.is_base_unit;
CREATE UNIQUE INDEX uq_inv_item_units_base ON inv.item_uom_conversions (item_id) WHERE is_base_unit;

-- ۳. بارکدِ هر واحد --------------------------------------------------------
CREATE TABLE inv.item_unit_barcodes (
    barcode_id    INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id    INT          NOT NULL REFERENCES core.companies(company_id),
    item_id       INT          NOT NULL REFERENCES inv.items(item_id),
    item_unit_id  INT          NOT NULL REFERENCES inv.item_uom_conversions(conversion_id),
    barcode       VARCHAR(100) NOT NULL,
    barcode_type  VARCHAR(15)  NOT NULL DEFAULT 'INTERNAL'
        CHECK (barcode_type IN ('EAN13', 'EAN8', 'UPCA', 'CODE128', 'CODE39', 'GS1', 'INTERNAL', 'CUSTOM')),
    is_primary    BOOLEAN      NOT NULL DEFAULT FALSE,
    is_active     BOOLEAN      NOT NULL DEFAULT TRUE,
    description   TEXT         NULL,
    created_at    TIMESTAMP    NOT NULL DEFAULT now(),
    updated_at    TIMESTAMP    NOT NULL DEFAULT now()
);
-- یک بارکد هم‌زمان نمی‌تواند متعلق به دو کالا/واحدِ فعال باشد.
CREATE UNIQUE INDEX uq_inv_item_unit_barcodes_active ON inv.item_unit_barcodes (company_id, barcode) WHERE is_active;
CREATE INDEX ix_inv_item_unit_barcodes_item ON inv.item_unit_barcodes (item_id);

-- انتقالِ بارکدِ فعلیِ کالا (inv.items.barcode) به بارکدِ اصلیِ واحدِ پایه؛
-- بارکدهایِ تکراریِ قدیمی فقط برایِ اولین کالا منتقل می‌شوند (بقیه در
-- inv.items.barcode دست‌نخورده می‌مانند).
INSERT INTO inv.item_unit_barcodes (company_id, item_id, item_unit_id, barcode, barcode_type, is_primary)
SELECT DISTINCT ON (i.company_id, btrim(i.barcode))
       i.company_id, i.item_id, c.conversion_id, btrim(i.barcode),
       CASE WHEN btrim(i.barcode) ~ '^[0-9]{13}$' THEN 'EAN13'
            WHEN btrim(i.barcode) ~ '^[0-9]{8}$' THEN 'EAN8'
            WHEN btrim(i.barcode) ~ '^[0-9]{12}$' THEN 'UPCA'
            ELSE 'INTERNAL' END,
       TRUE
FROM inv.items i
JOIN inv.item_uom_conversions c ON c.item_id = i.item_id AND c.is_base_unit
WHERE i.barcode IS NOT NULL AND btrim(i.barcode) <> ''
ORDER BY i.company_id, btrim(i.barcode), i.item_id;

-- ۴. Snapshotِ ضریبِ تبدیل در ردیفِ اسناد -----------------------------------
ALTER TABLE comm.commercial_document_lines ADD COLUMN conversion_factor NUMERIC(18,6) NOT NULL DEFAULT 1;
UPDATE comm.commercial_document_lines SET conversion_factor = quantity_base / quantity WHERE quantity <> 0 AND quantity_base <> quantity;
ALTER TABLE inv.stock_document_lines ADD COLUMN conversion_factor NUMERIC(18,6) NOT NULL DEFAULT 1;
UPDATE inv.stock_document_lines SET conversion_factor = quantity_base / quantity WHERE quantity <> 0 AND quantity_base <> quantity;

-- ۵. انبارگردانی با واحدِ شمارش ----------------------------------------------
ALTER TABLE inv.cycle_count_lines
    ADD COLUMN counted_uom_id    INT           NULL REFERENCES inv.uom(uom_id),
    ADD COLUMN counted_quantity  NUMERIC(18,6) NULL,
    ADD COLUMN conversion_factor NUMERIC(18,6) NULL;

-- ۶. بارگیریِ خودرو: مقدارِ پایه کنارِ مقدار و واحدِ برنامه‌ریزی‌شده -------------
-- (تسویهٔ خودرو از موجودیِ انبارِ خودرو ساخته می‌شود و همیشه به واحدِ پایه است.)
ALTER TABLE inv.vehicle_loading_lines ADD COLUMN planned_quantity_base NUMERIC(18,6) NULL;
UPDATE inv.vehicle_loading_lines SET planned_quantity_base = planned_quantity;
