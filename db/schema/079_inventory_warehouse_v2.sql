-- بازطراحیِ فرمِ «تعریفِ انبار» — پوششِ سندِ کاملِ انبارِ ساده تا چندشعبه‌ای.
-- طبقِ سندِ معماری: «شعبه» موجودیتِ جداگانه نیست (هر شعبه یک core.companies
-- است، پس warehouses.company_id از قبل همان نقش را دارد) — این مایگریشن
-- ستونِ branch_id اضافه نمی‌کند. پیش‌نیاز: 058_inventory_locations.sql

-- ۱) عریض‌کردنِ CHECKِ نوعِ انبار — اجتماعِ کدهایِ قدیمی + ۱۰ کدِ تازه
-- (بدونِ حذفِ کدهایِ قدیمی، بدونِ نیاز به backfill).
ALTER TABLE inv.warehouses DROP CONSTRAINT ck_inv_warehouses_project;
ALTER TABLE inv.warehouses DROP CONSTRAINT warehouses_warehouse_type_code_check;
ALTER TABLE inv.warehouses ADD CONSTRAINT warehouses_warehouse_type_code_check
    CHECK (warehouse_type_code IN (
        'GENERAL', 'PROJECT', 'PRODUCTION_LINE', 'QUARANTINE', 'TRANSIT',
        'CENTRAL', 'BRANCH', 'STORE', 'RAW_MATERIAL', 'FINISHED_GOODS',
        'SEMI_FINISHED', 'SCRAP', 'CONSIGNMENT', 'VEHICLE', 'RETURNED'
    ));
ALTER TABLE inv.warehouses ADD CONSTRAINT ck_inv_warehouses_project
    CHECK (warehouse_type_code <> 'PROJECT' OR project_detail_account_id IS NOT NULL);

-- ۲) فیلدهایِ تازهٔ inv.warehouses.
ALTER TABLE inv.warehouses
    -- پایه
    ADD COLUMN english_name                  VARCHAR(150) NULL,
    ADD COLUMN org_unit_id                   INTEGER NULL REFERENCES hr.organizational_units(org_unit_id),
    ADD COLUMN cost_center_detail_account_id INTEGER NULL REFERENCES acc.detail_accounts(detail_account_id),
    -- مکانی
    ADD COLUMN country                       VARCHAR(100) NULL,
    ADD COLUMN province                      VARCHAR(100) NULL,
    ADD COLUMN city                          VARCHAR(100) NULL,
    ADD COLUMN postal_code                   VARCHAR(20) NULL,
    ADD COLUMN phone                         VARCHAR(30) NULL,
    ADD COLUMN gps_coordinates               VARCHAR(50) NULL,
    ADD COLUMN manager_user_id               INTEGER NULL REFERENCES sec.users(user_id),
    -- عملیاتی
    ADD COLUMN allow_purchase                BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN allow_sale                    BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN allow_production              BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN allow_transfer                BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN allow_cycle_count             BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN allow_reservation             BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN allow_direct_sale             BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN requires_receipt_approval     BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN requires_issue_approval       BOOLEAN NOT NULL DEFAULT FALSE,
    -- کنترلِ موجودی (فقط اطلاعاتی این دور — به موتورِ reorder/costing وصل نمی‌شود)
    ADD COLUMN costing_method_id             SMALLINT NULL REFERENCES inv.costing_methods(costing_method_id),
    ADD COLUMN default_min_qty               NUMERIC(18, 6) NULL,
    ADD COLUMN default_max_qty               NUMERIC(18, 6) NULL,
    ADD COLUMN default_reorder_point_qty     NUMERIC(18, 6) NULL,
    ADD COLUMN withdrawal_policy_code        VARCHAR(10) NULL
        CHECK (withdrawal_policy_code IS NULL OR withdrawal_policy_code IN ('FIFO', 'LIFO', 'FEFO', 'MANUAL')),
    -- کیفیت
    ADD COLUMN requires_qc                   BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN requires_quarantine           BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN default_quarantine_warehouse_id INTEGER NULL REFERENCES inv.warehouses(warehouse_id),
    -- امنیت
    ADD COLUMN access_level_code             VARCHAR(15) NOT NULL DEFAULT 'PUBLIC'
        CHECK (access_level_code IN ('PUBLIC', 'RESTRICTED')),
    -- تجهیزات
    ADD COLUMN has_barcode_equipment         BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN has_qr_equipment              BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN has_rfid_equipment            BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN has_pda_equipment             BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN has_scanner_equipment         BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN has_scale_equipment           BOOLEAN NOT NULL DEFAULT FALSE,
    -- فروشگاه/POS (comm.pos_terminals از قبل warehouse_id دارد؛ این‌جا فقط پرچمِ فعال‌سازی/اولویت)
    ADD COLUMN pos_enabled                   BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN pos_pick_priority             SMALLINT NULL,
    -- تولید (خودارجاع — همه اختیاری)
    ADD COLUMN raw_material_warehouse_id     INTEGER NULL REFERENCES inv.warehouses(warehouse_id),
    ADD COLUMN production_line_warehouse_id  INTEGER NULL REFERENCES inv.warehouses(warehouse_id),
    ADD COLUMN finished_goods_warehouse_id   INTEGER NULL REFERENCES inv.warehouses(warehouse_id),
    ADD COLUMN scrap_warehouse_id            INTEGER NULL REFERENCES inv.warehouses(warehouse_id),
    -- مالی
    ADD COLUMN profit_center_detail_account_id INTEGER NULL REFERENCES acc.detail_accounts(detail_account_id),
    -- توضیحات
    ADD COLUMN notes                         TEXT NULL;

-- ۳) کاربرانِ مجازِ انبار — دقیقاً هم‌الگو با sec.user_companies (junction ساده)
-- به‌اضافهٔ چهار پرچمِ توانایی؛ فقط CRUDِ تعریفی این دور، بدونِ اتصال به
-- موتورِ اسناد (هم‌دامنه با inv.category_account_mappings).
CREATE TABLE inv.warehouse_user_access (
    warehouse_id     INTEGER NOT NULL REFERENCES inv.warehouses(warehouse_id),
    user_id          INTEGER NOT NULL REFERENCES sec.users(user_id),
    can_view_balance BOOLEAN NOT NULL DEFAULT TRUE,
    can_post_receipt BOOLEAN NOT NULL DEFAULT TRUE,
    can_post_issue   BOOLEAN NOT NULL DEFAULT TRUE,
    can_adjust       BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (warehouse_id, user_id)
);

-- ۴) نگاشتِ حسابِ سطحِ‌انبار — عیناً هم‌شکلِ inv.category_account_mappings؛
-- override رویِ نگاشتِ سراسریِ inv.account_mappings. طبقِ همان دامنه‌بندیِ
-- category_account_mappings: این دور فقط CRUD است، اتصال به
-- post_stock_document/_resolve_role_account دورِ بعد.
CREATE TABLE inv.warehouse_account_mappings (
    warehouse_id INTEGER     NOT NULL REFERENCES inv.warehouses(warehouse_id),
    mapping_key  VARCHAR(30) NOT NULL,
    account_id   INTEGER     NOT NULL REFERENCES acc.chart_of_accounts(account_id),
    PRIMARY KEY (warehouse_id, mapping_key)
);

-- ۵) دو Feature Flagِ تازه — هم‌الگو با seedِ 061 (کاتالوگِ toggleها).
INSERT INTO inv.feature_definitions (feature_code, name, category, requires_feature_code, description) VALUES
    ('BIN_LOCATIONS', 'مکان‌هایِ داخلیِ انبار (Bin Location)', 'LOCATION', NULL, 'ساختارِ سالن/راهرو/قفسه/طبقه/باکس در فرمِ انبار.'),
    ('WAREHOUSE_ACCESS_CONTROL', 'کنترلِ دسترسیِ انبار', 'SECURITY', NULL, 'تبِ امنیت (کاربرانِ مجاز/سطحِ دسترسی) در فرمِ انبار.');
