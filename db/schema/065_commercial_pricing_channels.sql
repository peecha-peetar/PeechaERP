-- پیچا | مدیریتِ بازرگانی — مراحلِ ۲/۶: کانال‌ها و موتورِ قیمت‌گذاری.
-- طبقِ سندِ معماری: کانال یک بُعدِ رویِ سند است، نه ماژولِ جدا؛ زنجیرهٔ
-- قیمت‌گذاری پنج‌گامی‌ست: قراردادِ فعال → فهرستِ قیمتِ پلکانی →
-- تخفیفِ قاعده‌ای → پروموشن/کوپن → محافظِ حاشیهٔ سود.
-- پیش‌نیاز: 001_core_i18n_and_tenancy.sql، 058_inventory_locations.sql

CREATE SCHEMA IF NOT EXISTS comm;

-- comm.channels و comm.price_lists ارجاعِ دوطرفه دارند (کانال فهرستِ
-- قیمتِ پیش‌فرض خودش را دارد؛ فهرستِ قیمت می‌تواند مختصِ یک کانال باشد) —
-- برایِ رفعِ چرخه، constraintِ channels→price_lists با ALTER اضافه می‌شود.
CREATE TABLE comm.price_lists (
    price_list_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    code VARCHAR(30) NOT NULL,
    name VARCHAR(150) NOT NULL,
    price_list_type_code VARCHAR(10) NOT NULL CHECK (price_list_type_code IN ('SALES', 'PURCHASE')),
    currency_id INT NOT NULL REFERENCES core.currencies(currency_id),
    channel_code VARCHAR(20) NULL,  -- FK به comm.channels در همین فایل، پسِ ساختِ آن جدول
    valid_from DATE NOT NULL,
    valid_to DATE NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_comm_price_lists UNIQUE (company_id, code),
    CONSTRAINT ck_comm_price_lists_dates CHECK (valid_to IS NULL OR valid_to > valid_from)
);

CREATE TABLE comm.channels (
    channel_code VARCHAR(20) NOT NULL,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    name VARCHAR(100) NOT NULL,
    channel_type_code VARCHAR(15) NOT NULL
        CHECK (channel_type_code IN ('POS', 'WHOLESALE', 'ONLINE', 'AGENT', 'MARKETPLACE')),
    default_price_list_id INT NULL REFERENCES comm.price_lists(price_list_id),
    default_warehouse_id INT NULL REFERENCES inv.warehouses(warehouse_id),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT pk_comm_channels PRIMARY KEY (company_id, channel_code)
);

ALTER TABLE comm.price_lists
    ADD CONSTRAINT fk_comm_price_lists_channel
    FOREIGN KEY (company_id, channel_code) REFERENCES comm.channels(company_id, channel_code);

CREATE TABLE comm.price_list_items (
    price_list_item_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    price_list_id INT NOT NULL REFERENCES comm.price_lists(price_list_id),
    item_id INT NOT NULL REFERENCES inv.items(item_id),
    uom_id INT NOT NULL REFERENCES inv.uom(uom_id),
    min_quantity NUMERIC(18,6) NOT NULL DEFAULT 1,
    unit_price NUMERIC(18,6) NOT NULL,
    CONSTRAINT uq_comm_price_list_items UNIQUE (price_list_id, item_id, uom_id, min_quantity)
);

CREATE TABLE comm.discount_rules (
    rule_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    code VARCHAR(30) NOT NULL,
    name VARCHAR(150) NOT NULL,
    discount_type_code VARCHAR(10) NOT NULL
        CHECK (discount_type_code IN ('PERCENT', 'AMOUNT', 'TIERED', 'BUNDLE')),
    scope_type_code VARCHAR(20) NOT NULL
        CHECK (scope_type_code IN ('ITEM', 'CATEGORY', 'CUSTOMER_GROUP', 'ALL')),
    scope_ref_id INT NULL,  -- چندریختی: به‌ازایِ scope_type_code به item_id/customer_groups.group_id اشاره می‌کند؛ بدونِ FKِ واحد
    discount_value NUMERIC(18,6) NULL,  -- برایِ PERCENT/AMOUNT؛ برایِ TIERED خالی، جدولِ زیر منبعِ حقیقت است
    priority SMALLINT NOT NULL DEFAULT 100,
    is_stackable BOOLEAN NOT NULL DEFAULT FALSE,
    valid_from DATE NOT NULL,
    valid_to DATE NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_comm_discount_rules UNIQUE (company_id, code)
);

CREATE TABLE comm.discount_rule_tiers (
    tier_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    rule_id INT NOT NULL REFERENCES comm.discount_rules(rule_id),
    min_quantity NUMERIC(18,6) NULL,
    min_amount NUMERIC(18,2) NULL,
    discount_value NUMERIC(18,6) NOT NULL,
    CONSTRAINT ck_comm_discount_rule_tiers_basis
        CHECK (min_quantity IS NOT NULL OR min_amount IS NOT NULL)
);

CREATE TABLE comm.promotions (
    promotion_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    code VARCHAR(30) NOT NULL,
    name VARCHAR(150) NOT NULL,
    promotion_type_code VARCHAR(15) NOT NULL
        CHECK (promotion_type_code IN ('BUY_X_GET_Y', 'SEASONAL', 'BUNDLE')),
    channel_scope VARCHAR(20) NULL,
    valid_from DATE NOT NULL,
    valid_to DATE NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_comm_promotions UNIQUE (company_id, code)
);

CREATE TABLE comm.coupons (
    coupon_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    code VARCHAR(30) NOT NULL,
    promotion_id INT NULL REFERENCES comm.promotions(promotion_id),
    discount_value NUMERIC(18,6) NOT NULL,
    max_uses INT NOT NULL DEFAULT 1,
    used_count INT NOT NULL DEFAULT 0,
    customer_detail_account_id INT NULL REFERENCES acc.detail_accounts(detail_account_id),
    valid_from DATE NOT NULL,
    valid_to DATE NULL,
    CONSTRAINT uq_comm_coupons UNIQUE (company_id, code),
    CONSTRAINT ck_comm_coupons_used CHECK (used_count <= max_uses)
);

-- محافظِ حاشیهٔ سود (مرحلهٔ ۶، بخشِ ۴).
CREATE TABLE comm.pricing_policies (
    policy_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    min_margin_percent_default NUMERIC(5,2) NULL CHECK (min_margin_percent_default BETWEEN 0 AND 100),
    below_margin_requires_approval BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_comm_pricing_policies_company UNIQUE (company_id)
);

-- فروشِ ترکیبی/CPQِ سبک (مرحلهٔ ۵، بخشِ ۴).
CREATE TABLE comm.bundle_definitions (
    bundle_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    bundle_item_id INT NOT NULL UNIQUE REFERENCES inv.items(item_id),
    name VARCHAR(150) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE comm.bundle_components (
    bundle_component_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    bundle_id INT NOT NULL REFERENCES comm.bundle_definitions(bundle_id),
    component_item_id INT NOT NULL REFERENCES inv.items(item_id),
    quantity_per_bundle NUMERIC(18,6) NOT NULL CHECK (quantity_per_bundle > 0),
    price_allocation_percent NUMERIC(5,2) NOT NULL CHECK (price_allocation_percent > 0),
    CONSTRAINT uq_comm_bundle_components UNIQUE (bundle_id, component_item_id)
);
