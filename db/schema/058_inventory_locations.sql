-- پیچا | ماژولِ انبار و لجستیک — خوشهٔ مکان (انبارها و مکان‌هایِ انبار)
-- طبقِ سندِ معماری (مرحلهٔ ۴): «شعبه» موجودیتِ جداگانه‌ای نیست — هر شعبه
-- خودش یک core.companies است؛ پس warehouses.company_id خودش بعدِ شعبه
-- را پوشش می‌دهد، بدونِ ستونِ branch_id جداگانه.
-- پیش‌نیاز: 057_inventory_catalog.sql

CREATE TABLE inv.warehouses (
    warehouse_id              INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id                 INT         NOT NULL REFERENCES core.companies(company_id),
    code                        VARCHAR(20) NOT NULL,
    name                         VARCHAR(150) NOT NULL,
    warehouse_type_code           VARCHAR(20) NOT NULL DEFAULT 'GENERAL'
        CHECK (warehouse_type_code IN ('GENERAL', 'PROJECT', 'PRODUCTION_LINE', 'QUARANTINE', 'TRANSIT')),
    project_detail_account_id      INT      NULL REFERENCES acc.detail_accounts(detail_account_id),
    allow_negative_stock             BOOLEAN NOT NULL DEFAULT FALSE,
    is_temperature_controlled         BOOLEAN NOT NULL DEFAULT FALSE,
    min_temp_c                         NUMERIC(5,2) NULL,
    max_temp_c                          NUMERIC(5,2) NULL,
    address                              VARCHAR(400) NULL,
    is_default                            BOOLEAN NOT NULL DEFAULT FALSE,
    is_active                              BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_inv_warehouses UNIQUE (company_id, code),
    CONSTRAINT ck_inv_warehouses_project
        CHECK (warehouse_type_code <> 'PROJECT' OR project_detail_account_id IS NOT NULL)
);

CREATE TABLE inv.bin_locations (
    bin_location_id       INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    warehouse_id            INT         NOT NULL REFERENCES inv.warehouses(warehouse_id),
    parent_bin_location_id   INT        NULL REFERENCES inv.bin_locations(bin_location_id),
    code                       VARCHAR(30) NOT NULL,
    name                        VARCHAR(100) NULL,
    bin_type_code                 VARCHAR(15) NULL CHECK (bin_type_code IN ('AREA', 'AISLE', 'RACK', 'SHELF', 'BIN')),
    barcode                        VARCHAR(100) NULL,
    is_pickable                     BOOLEAN NOT NULL DEFAULT TRUE,
    is_active                        BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_inv_bin_locations UNIQUE (warehouse_id, code)
);
CREATE INDEX ix_inv_bin_locations_barcode ON inv.bin_locations(barcode);
