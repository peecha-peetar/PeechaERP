-- پیچا | ماژولِ انبار و لجستیک — خوشهٔ کاتالوگ (کالا/خدمت، واحد، برند، تولیدکننده، ویژگی/تنوع)
-- طبقِ سندِ معماریِ ۱۵مرحله‌ای (مراحلِ ۱ تا ۳):
--   «کالا» موجودیتِ تازه‌ای نیست — دقیقاً همان تفصیلیِ سطحِ‌آخرِ گروهِ سیستمیِ
--   INVENTORY_ITEM (acc.detail_dimension_types) است؛ inv.items یک جدولِ
--   اقماریِ یک‌به‌یک است (دقیقاً هم‌الگو با hr.employees نسبت به تفصیلیِ
--   گروهِ PERSONNEL) — نه جایگزینِ آن.
-- پیش‌نیاز: 001_core_i18n_and_tenancy.sql، 003_accounting_core.sql،
--           010_detail_group_hierarchy.sql، 005_attachments.sql

CREATE SCHEMA inv;

-- ---------------------------------------------------------------------
-- واحدِ اندازه‌گیری
-- ---------------------------------------------------------------------
CREATE TABLE inv.uom (
    uom_id       INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id   INT          NULL REFERENCES core.companies(company_id),  -- NULL = واحدِ سراسریِ سیستمی
    code         VARCHAR(20)  NOT NULL,
    name         VARCHAR(50)  NOT NULL,
    uom_type_code VARCHAR(10) NOT NULL CHECK (uom_type_code IN ('COUNT', 'WEIGHT', 'VOLUME', 'LENGTH', 'AREA', 'TIME')),
    is_active    BOOLEAN      NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_inv_uom UNIQUE (company_id, code)
);

-- ---------------------------------------------------------------------
-- برند / تولیدکننده — موجودیتِ کاملاً تازه (معادلِ تفصیلیِ ازپیش‌موجود ندارند)
-- ---------------------------------------------------------------------
CREATE TABLE inv.brands (
    brand_id    INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id  INT          NOT NULL REFERENCES core.companies(company_id),
    code        VARCHAR(20)  NOT NULL,
    name        VARCHAR(150) NOT NULL,
    is_active   BOOLEAN      NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_inv_brands UNIQUE (company_id, code)
);

CREATE TABLE inv.manufacturers (
    manufacturer_id INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id      INT          NOT NULL REFERENCES core.companies(company_id),
    code            VARCHAR(20)  NOT NULL,
    name            VARCHAR(150) NOT NULL,
    country_name    VARCHAR(100),
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_inv_manufacturers UNIQUE (company_id, code)
);

-- ---------------------------------------------------------------------
-- روشِ قیمت‌گذاری — Lookup سیستمی، پیش از inv.items چون به آن ارجاع می‌دهد
-- (تعریفِ کاملِ جداولِ قیمت‌گذاری خودش در 061 است)
-- ---------------------------------------------------------------------
CREATE TABLE inv.costing_methods (
    costing_method_id SMALLINT    NOT NULL PRIMARY KEY,
    code               VARCHAR(20) NOT NULL UNIQUE
);
INSERT INTO inv.costing_methods (costing_method_id, code) VALUES
    (1, 'FIFO'), (2, 'WEIGHTED_AVERAGE'), (3, 'STANDARD');

-- ---------------------------------------------------------------------
-- کالا/خدمت — جدولِ اقماریِ تفصیلیِ گروهِ INVENTORY_ITEM
-- ---------------------------------------------------------------------
CREATE TABLE inv.items (
    item_id                INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id             INT          NOT NULL REFERENCES core.companies(company_id),
    item_detail_account_id INT          NOT NULL UNIQUE REFERENCES acc.detail_accounts(detail_account_id),
    item_kind_code          VARCHAR(10) NOT NULL CHECK (item_kind_code IN ('GOOD', 'SERVICE')),
    base_uom_id             INT         NOT NULL REFERENCES inv.uom(uom_id),
    brand_id                INT         NULL REFERENCES inv.brands(brand_id),
    manufacturer_id         INT         NULL REFERENCES inv.manufacturers(manufacturer_id),
    variant_parent_item_id  INT         NULL REFERENCES inv.items(item_id),
    costing_method_code     VARCHAR(20) NULL REFERENCES inv.costing_methods(code),
    -- طبقِ مرحلهٔ ۳: چرخهٔ‌عمرِ کالا — بایگانی (خارج از این چرخه) همان
    -- is_active رویِ acc.detail_accounts است، نه ستونی این‌جا.
    lifecycle_status_code   VARCHAR(15) NOT NULL DEFAULT 'ACTIVE'
        CHECK (lifecycle_status_code IN ('DRAFT', 'ACTIVE', 'DISCONTINUED')),
    is_sellable              BOOLEAN    NOT NULL DEFAULT TRUE,
    is_purchasable           BOOLEAN    NOT NULL DEFAULT TRUE,
    is_stock_tracked         BOOLEAN    NOT NULL DEFAULT TRUE,
    track_serial             BOOLEAN    NOT NULL DEFAULT FALSE,
    track_batch              BOOLEAN    NOT NULL DEFAULT FALSE,
    track_expiry             BOOLEAN    NOT NULL DEFAULT FALSE,
    shelf_life_days          INT        NULL,
    weight_kg                NUMERIC(12,4) NULL,
    volume_m3                NUMERIC(12,6) NULL,
    primary_attachment_id    BIGINT     NULL REFERENCES doc.attachments(attachment_id),
    extra_fields              JSONB     NOT NULL DEFAULT '{}'::jsonb,
    notes                     VARCHAR(1000) NULL,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_inv_items_service_not_tracked
        CHECK (item_kind_code = 'GOOD' OR is_stock_tracked = FALSE),
    CONSTRAINT ck_inv_items_expiry_needs_batch
        CHECK (track_expiry = FALSE OR track_batch = TRUE)
);
CREATE INDEX ix_inv_items_company ON inv.items(company_id);
CREATE INDEX ix_inv_items_variant_parent ON inv.items(variant_parent_item_id);

CREATE TABLE inv.item_uom_conversions (
    conversion_id       INT           GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    item_id              INT          NOT NULL REFERENCES inv.items(item_id),
    uom_id                INT         NOT NULL REFERENCES inv.uom(uom_id),
    conversion_factor      NUMERIC(18,6) NOT NULL CHECK (conversion_factor > 0),
    is_purchase_default     BOOLEAN    NOT NULL DEFAULT FALSE,
    is_sales_default         BOOLEAN   NOT NULL DEFAULT FALSE,
    CONSTRAINT uq_inv_item_uom_conversions UNIQUE (item_id, uom_id)
);

-- ---------------------------------------------------------------------
-- ویژگی و تنوعِ کالا
-- ---------------------------------------------------------------------
CREATE TABLE inv.item_attributes (
    attribute_id INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id   INT          NOT NULL REFERENCES core.companies(company_id),
    code         VARCHAR(20)  NOT NULL,
    name         VARCHAR(100) NOT NULL,
    is_active    BOOLEAN      NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_inv_item_attributes UNIQUE (company_id, code)
);

CREATE TABLE inv.item_attribute_values (
    value_id        INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    attribute_id      INT        NOT NULL REFERENCES inv.item_attributes(attribute_id),
    code               VARCHAR(20) NOT NULL,
    value               VARCHAR(100) NOT NULL,
    display_order        SMALLINT NOT NULL DEFAULT 0,
    CONSTRAINT uq_inv_item_attribute_values UNIQUE (attribute_id, code)
);

CREATE TABLE inv.item_variant_values (
    item_id       INT NOT NULL REFERENCES inv.items(item_id),
    attribute_id   INT NOT NULL REFERENCES inv.item_attributes(attribute_id),
    value_id        INT NOT NULL REFERENCES inv.item_attribute_values(value_id),
    CONSTRAINT pk_inv_item_variant_values PRIMARY KEY (item_id, attribute_id)
);

-- ---------------------------------------------------------------------
-- کالاهایِ جایگزین/مکمل
-- ---------------------------------------------------------------------
CREATE TABLE inv.related_items (
    related_item_link_id INT         GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    item_id                INT       NOT NULL REFERENCES inv.items(item_id),
    related_item_id         INT      NOT NULL REFERENCES inv.items(item_id),
    relation_type_code        VARCHAR(15) NOT NULL CHECK (relation_type_code IN ('SUBSTITUTE', 'COMPLEMENTARY')),
    CONSTRAINT uq_inv_related_items UNIQUE (item_id, related_item_id, relation_type_code),
    CONSTRAINT ck_inv_related_items_not_self CHECK (item_id <> related_item_id)
);
