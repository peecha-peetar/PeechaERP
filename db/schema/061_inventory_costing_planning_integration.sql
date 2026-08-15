-- پیچا | ماژولِ انبار و لجستیک — قیمت‌گذاری، برنامه‌ریزی و یکپارچگی
-- طبقِ سندِ معماری (مراحلِ ۸، ۱۱، ۱۴).
-- پیش‌نیاز: 060_inventory_tracking_quality.sql

-- ---------------------------------------------------------------------
-- قیمت‌گذاری
-- ---------------------------------------------------------------------
CREATE TABLE inv.company_costing_settings (
    company_id                  INT         NOT NULL PRIMARY KEY REFERENCES core.companies(company_id),
    default_costing_method_id     SMALLINT   NOT NULL REFERENCES inv.costing_methods(costing_method_id),
    allow_item_override             BOOLEAN  NOT NULL DEFAULT TRUE
);

CREATE TABLE inv.cost_layers (
    cost_layer_id           BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    item_id                   INT        NOT NULL REFERENCES inv.items(item_id),
    warehouse_id                INT      NOT NULL REFERENCES inv.warehouses(warehouse_id),
    stock_ledger_id               BIGINT NOT NULL REFERENCES inv.stock_ledger(ledger_id),
    received_at                     TIMESTAMPTZ NOT NULL,
    original_quantity                 NUMERIC(18,6) NOT NULL,
    remaining_quantity                  NUMERIC(18,6) NOT NULL,
    unit_cost                            NUMERIC(18,6) NOT NULL,
    CONSTRAINT ck_inv_cost_layers_remaining CHECK (remaining_quantity BETWEEN 0 AND original_quantity)
);
CREATE INDEX ix_inv_cost_layers_item_wh_received ON inv.cost_layers(item_id, warehouse_id, received_at);

CREATE TABLE inv.standard_costs (
    item_id            INT     NOT NULL REFERENCES inv.items(item_id),
    effective_date       DATE  NOT NULL,
    standard_unit_cost     NUMERIC(18,6) NOT NULL,
    CONSTRAINT pk_inv_standard_costs PRIMARY KEY (item_id, effective_date)
);

-- ---------------------------------------------------------------------
-- برنامه‌ریزیِ موجودی
-- ---------------------------------------------------------------------
CREATE TABLE inv.reorder_policies (
    policy_id           INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id            INT        NOT NULL REFERENCES core.companies(company_id),
    item_id                 INT       NOT NULL REFERENCES inv.items(item_id),
    warehouse_id              INT     NULL REFERENCES inv.warehouses(warehouse_id),
    min_qty                    NUMERIC(18,6) NULL,
    max_qty                     NUMERIC(18,6) NULL,
    reorder_point_qty             NUMERIC(18,6) NULL,
    reorder_qty                    NUMERIC(18,6) NULL,
    lead_time_days                  SMALLINT NULL,
    is_active                        BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT ck_inv_reorder_policies_max_gt_point
        CHECK (max_qty IS NULL OR reorder_point_qty IS NULL OR max_qty > reorder_point_qty)
);
CREATE UNIQUE INDEX ux_inv_reorder_policies_company ON inv.reorder_policies(item_id) WHERE warehouse_id IS NULL;
CREATE UNIQUE INDEX ux_inv_reorder_policies_warehouse ON inv.reorder_policies(item_id, warehouse_id) WHERE warehouse_id IS NOT NULL;

CREATE TABLE inv.reorder_suggestion_acknowledgements (
    ack_id                 INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id               INT        NOT NULL REFERENCES core.companies(company_id),
    item_id                    INT       NOT NULL REFERENCES inv.items(item_id),
    warehouse_id                 INT     NOT NULL REFERENCES inv.warehouses(warehouse_id),
    acknowledged_by_user_id        INT   NOT NULL REFERENCES sec.users(user_id),
    acknowledged_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    snooze_until                      DATE NULL,
    notes                               VARCHAR(500) NULL
);
CREATE INDEX ix_inv_reorder_acks_item_wh ON inv.reorder_suggestion_acknowledgements(item_id, warehouse_id);

-- ---------------------------------------------------------------------
-- یکپارچگیِ حسابداری
-- ---------------------------------------------------------------------
CREATE TABLE inv.account_mappings (
    company_id   INT         NOT NULL REFERENCES core.companies(company_id),
    mapping_key   VARCHAR(30) NOT NULL,
    account_id     INT       NOT NULL REFERENCES acc.chart_of_accounts(account_id),
    CONSTRAINT pk_inv_account_mappings PRIMARY KEY (company_id, mapping_key)
);

-- ---------------------------------------------------------------------
-- Feature Toggle
-- ---------------------------------------------------------------------
CREATE TABLE inv.feature_definitions (
    feature_code           VARCHAR(50) NOT NULL PRIMARY KEY,
    name                     VARCHAR(150) NOT NULL,
    category                  VARCHAR(30) NOT NULL,
    requires_feature_code       VARCHAR(50) NULL REFERENCES inv.feature_definitions(feature_code),
    description                  TEXT NULL
);

CREATE TABLE inv.company_features (
    company_id     INT         NOT NULL REFERENCES core.companies(company_id),
    feature_code    VARCHAR(50) NOT NULL REFERENCES inv.feature_definitions(feature_code),
    is_enabled        BOOLEAN  NOT NULL DEFAULT FALSE,
    CONSTRAINT pk_inv_company_features PRIMARY KEY (company_id, feature_code)
);

-- طبقِ مرحلهٔ ۱۴، بخشِ ۲۰۱: کاتالوگِ کاملِ ۱۲ Toggle با زنجیرهٔ وابستگی.
INSERT INTO inv.feature_definitions (feature_code, name, category, requires_feature_code, description) VALUES
    ('QUALITY_CONTROL', 'کنترلِ کیفیت', 'QUALITY', NULL, 'گردشِ کارِ QC را فعال می‌کند؛ بدونِ آن رسیدها مستقیماً APPROVED می‌شوند.'),
    ('BATCH_TRACKING', 'ردیابیِ بچ', 'TRACKING', NULL, 'فیلدِ بچ در فرمِ کالا/رسید/حواله.'),
    ('EXPIRY_TRACKING', 'ردیابیِ انقضا', 'TRACKING', 'BATCH_TRACKING', 'فیلدِ عمرِ قفسه/تاریخِ انقضا.'),
    ('FEFO_ALLOCATION', 'تخصیصِ FEFO', 'TRACKING', 'EXPIRY_TRACKING', 'پیشنهادِ بچ بر اساسِ تاریخِ انقضا.'),
    ('FULL_TRACEABILITY', 'رهگیریِ کاملِ دارویی', 'TRACKING', 'BATCH_TRACKING', 'بازرسیِ QC برایِ هر رسید اجباری می‌شود.'),
    ('SERIAL_TRACKING', 'ردیابیِ سریال', 'TRACKING', NULL, 'فیلدِ سریال/اسکنر در فرمِ کالا/رسید/حواله.'),
    ('WARRANTY_TRACKING', 'گارانتی', 'TRACKING', 'SERIAL_TRACKING', 'فیلدِ تاریخِ انقضایِ گارانتیِ سریال.'),
    ('VARIANTS', 'ویژگی و تنوع', 'CATALOG', NULL, 'Variant Generator در ناوبریِ کاتالوگ.'),
    ('LOGISTICS_DIMENSIONS', 'ابعادِ لجستیکی', 'CATALOG', NULL, 'فیلدِ وزن/حجم در فرمِ کالا.'),
    ('TEMPERATURE_CONTROL', 'کنترلِ دما', 'LOCATION', NULL, 'فیلدهایِ دمایِ مجاز در فرمِ انبار.'),
    ('PROJECT_WAREHOUSES', 'انبارِ پروژه‌ای', 'LOCATION', NULL, 'گزینهٔ انبارِ پروژه در فرمِ انبار.'),
    ('NEW_ITEM_APPROVAL', 'تاییدِ کالایِ تازه', 'WORKFLOW', NULL, 'کالایِ DRAFTِ غیرِمدیرِ کاتالوگ به کارتابل می‌رود.'),
    ('DOCUMENT_APPROVAL_WORKFLOW', 'تاییدِ اسنادِ انبار', 'WORKFLOW', NULL, 'گذارِ CONFIRMED→POSTED نیازمندِ تاییدِ نقشِ دوم.'),
    ('BACKORDER_ALLOWED', 'رزروِ مازادبرموجود', 'PLANNING', NULL, 'رزرو می‌تواند از موجودیِ قابلِ‌دسترس عبور کند.');
