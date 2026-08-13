-- بازطراحیِ فرمِ کالا به فرمِ ماژولار ۱۷بخشی — فازِ ۱ تا ۱۵.
-- «کالا همان تفصیلیِ کالاست»: این مایگریشن هیچ موجودیتِ تازه‌ای برایِ کالا
-- نمی‌سازد؛ فقط inv.items را با فیلدهایِ تازه گسترش می‌دهد و جدول‌هایِ
-- اقماریِ جدید (دسته‌بندی/تامین‌کننده/رسانه/BOM/دارایی/نگاشتِ حسابِ
-- دسته‌بندی) را اضافه می‌کند.

-- ۱) گسترشِ item_kind_code از (GOOD, SERVICE) به ۸ نوع (طولِ ستون هم باید
-- زیاد شود چون مقادیرِ تازه مثلِ RAW_MATERIAL/SEMI_FINISHED از ۱۰ نویسه بلندترند).
ALTER TABLE inv.items ALTER COLUMN item_kind_code TYPE VARCHAR(20);
ALTER TABLE inv.items DROP CONSTRAINT items_item_kind_code_check;
ALTER TABLE inv.items ADD CONSTRAINT items_item_kind_code_check
    CHECK (item_kind_code IN ('GOOD', 'SERVICE', 'RAW_MATERIAL', 'SEMI_FINISHED', 'FINISHED_GOOD', 'ASSET', 'BUNDLE', 'KIT'));

ALTER TABLE inv.items DROP CONSTRAINT ck_inv_items_service_not_tracked;
ALTER TABLE inv.items ADD CONSTRAINT ck_inv_items_service_not_tracked
    CHECK (item_kind_code != 'SERVICE' OR is_stock_tracked = FALSE);

-- ۲) دسته‌بندیِ کالا (سلسله‌مراتبی، مستقل از تفصیلی).
CREATE TABLE inv.item_categories (
    category_id         INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id          INTEGER NOT NULL REFERENCES core.companies(company_id),
    parent_category_id  INTEGER NULL REFERENCES inv.item_categories(category_id),
    code                VARCHAR(20) NOT NULL,
    name                VARCHAR(150) NOT NULL,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (company_id, code)
);

-- ۳) فیلدهایِ تازهٔ inv.items — بخش‌هایِ ۱،۲،۳(بخشی)،۵،۶،۷،۹،۱۰،۱۱،۱۲.
ALTER TABLE inv.items
    ADD COLUMN category_id                    INTEGER NULL REFERENCES inv.item_categories(category_id),
    ADD COLUMN default_warehouse_id            INTEGER NULL REFERENCES inv.warehouses(warehouse_id),
    ADD COLUMN barcode                         VARCHAR(50) NULL,
    ADD COLUMN qr_code_data                    VARCHAR(200) NULL,
    ADD COLUMN sku                             VARCHAR(50) NULL,
    ADD COLUMN latin_name                      VARCHAR(200) NULL,
    ADD COLUMN short_name                      VARCHAR(50) NULL,
    ADD COLUMN country_of_origin               VARCHAR(60) NULL,
    ADD COLUMN length_cm                       NUMERIC(10, 2) NULL,
    ADD COLUMN width_cm                        NUMERIC(10, 2) NULL,
    ADD COLUMN height_cm                       NUMERIC(10, 2) NULL,
    ADD COLUMN package_type_code               VARCHAR(30) NULL,
    ADD COLUMN freight_class_code              VARCHAR(30) NULL,
    ADD COLUMN requires_qc                     BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN qc_standard                     VARCHAR(100) NULL,
    ADD COLUMN qc_test_spec                    TEXT NULL,
    ADD COLUMN qc_inspection_interval_days     INTEGER NULL,
    ADD COLUMN purchase_lead_time_days         INTEGER NULL,
    ADD COLUMN purchase_min_order_qty          NUMERIC(18, 6) NULL,
    ADD COLUMN purchase_package_qty            NUMERIC(18, 6) NULL,
    ADD COLUMN max_discount_percent            NUMERIC(5, 2) NULL,
    ADD COLUMN sales_commission_percent        NUMERIC(5, 2) NULL,
    ADD COLUMN warranty_months                 INTEGER NULL,
    ADD COLUMN seo_title                       VARCHAR(200) NULL,
    ADD COLUMN seo_url_slug                    VARCHAR(200) NULL,
    ADD COLUMN seo_meta_description            VARCHAR(500) NULL,
    ADD COLUMN seo_meta_keywords               VARCHAR(300) NULL,
    ADD COLUMN website_category                VARCHAR(150) NULL,
    ADD COLUMN website_tags                    VARCHAR(300) NULL,
    ADD COLUMN pos_shortcut_key                VARCHAR(10) NULL,
    ADD COLUMN pos_button_color                VARCHAR(20) NULL,
    ADD COLUMN pos_requires_weight             BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN pos_requires_serial             BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN updated_at                      TIMESTAMPTZ NULL;

CREATE UNIQUE INDEX uq_inv_items_company_barcode ON inv.items (company_id, barcode) WHERE barcode IS NOT NULL;
CREATE UNIQUE INDEX uq_inv_items_company_sku ON inv.items (company_id, sku) WHERE sku IS NOT NULL;

-- ۴) تامین‌کنندگانِ کالا (چندبه‌چند با تفصیلیِ تامین‌کننده) — بخشِ ۶.
CREATE TABLE inv.item_suppliers (
    item_supplier_id        INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    item_id                 INTEGER NOT NULL REFERENCES inv.items(item_id),
    supplier_detail_account_id INTEGER NOT NULL REFERENCES acc.detail_accounts(detail_account_id),
    supplier_sku            VARCHAR(50) NULL,
    lead_time_days          INTEGER NULL,
    min_order_qty           NUMERIC(18, 6) NULL,
    is_preferred            BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (item_id, supplier_detail_account_id)
);

-- ۵) اسناد/رسانهٔ کالا (تصویر/ویدئو/کاتالوگ) — بخشِ ۱۵.
CREATE TABLE inv.item_media (
    item_media_id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    item_id           INTEGER NOT NULL REFERENCES inv.items(item_id),
    attachment_id     BIGINT NOT NULL REFERENCES doc.attachments(attachment_id),
    media_type_code   VARCHAR(15) NOT NULL CHECK (media_type_code IN ('IMAGE', 'VIDEO', 'CATALOG', 'MANUAL', 'DOCUMENT')),
    alt_text          VARCHAR(200) NULL,
    is_primary        BOOLEAN NOT NULL DEFAULT FALSE,
    sort_order        SMALLINT NOT NULL DEFAULT 0
);

-- ۶) فهرستِ موادِ اولیه (BOM) — بخشِ ۸، فقط برایِ نوعِ FINISHED_GOOD معنادار.
CREATE TABLE inv.bom_headers (
    bom_id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    finished_item_id        INTEGER NOT NULL REFERENCES inv.items(item_id),
    version_no              SMALLINT NOT NULL DEFAULT 1,
    batch_size_qty          NUMERIC(18, 6) NOT NULL DEFAULT 1,
    production_time_minutes INTEGER NULL,
    scrap_percent           NUMERIC(5, 2) NOT NULL DEFAULT 0,
    is_active               BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (finished_item_id, version_no)
);

CREATE TABLE inv.bom_lines (
    bom_line_id       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    bom_id            BIGINT NOT NULL REFERENCES inv.bom_headers(bom_id),
    component_item_id INTEGER NOT NULL REFERENCES inv.items(item_id),
    quantity_per      NUMERIC(18, 6) NOT NULL CHECK (quantity_per > 0),
    scrap_percent     NUMERIC(5, 2) NOT NULL DEFAULT 0,
    line_no           SMALLINT NOT NULL,
    UNIQUE (bom_id, line_no)
);

-- ۷) دارایی/استهلاک — بخشِ ۱۳، فقط برایِ نوعِ ASSET معنادار.
CREATE TABLE inv.asset_details (
    item_id                   INTEGER PRIMARY KEY REFERENCES inv.items(item_id),
    asset_tag_no              VARCHAR(50) NULL,
    depreciation_group_code   VARCHAR(30) NULL,
    useful_life_months        INTEGER NOT NULL,
    depreciation_method_code  VARCHAR(20) NOT NULL DEFAULT 'STRAIGHT_LINE'
        CHECK (depreciation_method_code IN ('STRAIGHT_LINE', 'DECLINING_BALANCE')),
    acquisition_date          DATE NOT NULL,
    acquisition_cost          NUMERIC(18, 2) NOT NULL,
    salvage_value             NUMERIC(18, 2) NOT NULL DEFAULT 0
);

CREATE TABLE inv.asset_depreciation_entries (
    depreciation_entry_id  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    item_id                INTEGER NOT NULL REFERENCES inv.asset_details(item_id),
    period_date             DATE NOT NULL,
    depreciation_amount     NUMERIC(18, 2) NOT NULL,
    journal_entry_id        INTEGER NULL REFERENCES acc.journal_entries(journal_entry_id),
    UNIQUE (item_id, period_date)
);

-- ۸) نگاشتِ حسابِ حسابداری در سطحِ دسته‌بندی — بخشِ ۱۴ (override رویِ نگاشتِ
-- سراسریِ inv.account_mappings). خودِ لایهٔ ثبتِ سند (post_stock_document)
-- در این دور همچنان از نگاشتِ سراسری می‌خواند؛ این جدول فقط لایهٔ CRUD/تنظیم
-- را فراهم می‌کند تا در دورِ بعدی به موتورِ ثبت وصل شود.
CREATE TABLE inv.category_account_mappings (
    category_id   INTEGER NOT NULL REFERENCES inv.item_categories(category_id),
    mapping_key   VARCHAR(30) NOT NULL,
    account_id    INTEGER NOT NULL REFERENCES acc.chart_of_accounts(account_id),
    PRIMARY KEY (category_id, mapping_key)
);
