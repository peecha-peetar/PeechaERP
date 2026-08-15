-- پیچا | ماژولِ انبار و لجستیک — رهگیریِ کالا (بچ/سریال) + کنترلِ کیفیت
-- طبقِ سندِ معماری (مرحلهٔ ۷): این خوشه زیرسیستمِ عرضی است — رویِ عملیاتِ
-- انبار (059) سوار می‌شود. FKهایِ batch_id/serial_id که در 059 عمداً
-- بدونِ REFERENCES رها شدند، اینجا (پسِ ساختِ خودِ جدول‌ها) تکمیل می‌شوند.
-- پیش‌نیاز: 059_inventory_engine_documents.sql

CREATE TABLE inv.batches (
    batch_id                  INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id                 INT         NOT NULL REFERENCES core.companies(company_id),
    item_id                     INT        NOT NULL REFERENCES inv.items(item_id),
    batch_no                     VARCHAR(50) NOT NULL,
    manufacture_date               DATE NULL,
    expiry_date                     DATE NULL,
    supplier_detail_account_id       INT NULL REFERENCES acc.detail_accounts(detail_account_id),
    qc_status_code                    VARCHAR(15) NOT NULL DEFAULT 'PENDING'
        CHECK (qc_status_code IN ('PENDING', 'APPROVED', 'QUARANTINE', 'REJECTED', 'RECALLED')),
    source_line_id                     BIGINT NULL REFERENCES inv.stock_document_lines(line_id),
    notes                                VARCHAR(500) NULL,
    created_at                           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_inv_batches UNIQUE (item_id, batch_no)
);
CREATE INDEX ix_inv_batches_item_expiry ON inv.batches(item_id, expiry_date);

CREATE TABLE inv.serial_numbers (
    serial_id                 INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id                 INT         NOT NULL REFERENCES core.companies(company_id),
    item_id                     INT        NOT NULL REFERENCES inv.items(item_id),
    serial_no                    VARCHAR(100) NOT NULL,
    batch_id                      INT      NULL REFERENCES inv.batches(batch_id),
    current_warehouse_id            INT    NULL REFERENCES inv.warehouses(warehouse_id),
    current_bin_location_id          INT   NULL REFERENCES inv.bin_locations(bin_location_id),
    status_code                       VARCHAR(15) NOT NULL DEFAULT 'IN_STOCK'
        CHECK (status_code IN ('IN_STOCK', 'RESERVED', 'SOLD', 'IN_TRANSIT', 'RETURNED', 'SCRAPPED')),
    warranty_expiry_date                DATE NULL,
    source_line_id                       BIGINT NULL REFERENCES inv.stock_document_lines(line_id),
    created_at                            TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_inv_serial_numbers UNIQUE (company_id, item_id, serial_no)
);

CREATE TABLE inv.serial_movements (
    serial_movement_id    BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    serial_id               INT        NOT NULL REFERENCES inv.serial_numbers(serial_id),
    stock_document_line_id    BIGINT   NOT NULL REFERENCES inv.stock_document_lines(line_id),
    from_status_code            VARCHAR(15) NULL,
    to_status_code                VARCHAR(15) NOT NULL,
    from_warehouse_id                INT NULL REFERENCES inv.warehouses(warehouse_id),
    to_warehouse_id                   INT NULL REFERENCES inv.warehouses(warehouse_id),
    moved_at                           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE inv.qc_inspections (
    qc_inspection_id       INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id               INT        NOT NULL REFERENCES core.companies(company_id),
    stock_document_line_id     BIGINT   NULL REFERENCES inv.stock_document_lines(line_id),
    batch_id                     INT    NULL REFERENCES inv.batches(batch_id),
    inspected_by_user_id           INT  NOT NULL REFERENCES sec.users(user_id),
    inspected_at                     TIMESTAMPTZ NOT NULL DEFAULT now(),
    result_code                       VARCHAR(15) NOT NULL CHECK (result_code IN ('PENDING', 'APPROVED', 'REJECTED', 'PARTIAL')),
    sampled_quantity                    NUMERIC(18,6) NULL,
    rejected_quantity                    NUMERIC(18,6) NULL,
    notes                                 TEXT NULL,
    CONSTRAINT ck_inv_qc_inspections_one_target
        CHECK ((stock_document_line_id IS NOT NULL)::int + (batch_id IS NOT NULL)::int = 1)
);

-- ---------------------------------------------------------------------
-- تکمیلِ FKهایِ Forward-Reference از 059
-- ---------------------------------------------------------------------
ALTER TABLE inv.stock_document_lines
    ADD CONSTRAINT fk_inv_stock_document_lines_batch FOREIGN KEY (batch_id) REFERENCES inv.batches(batch_id);

ALTER TABLE inv.stock_ledger
    ADD CONSTRAINT fk_inv_stock_ledger_batch FOREIGN KEY (batch_id) REFERENCES inv.batches(batch_id),
    ADD CONSTRAINT fk_inv_stock_ledger_serial FOREIGN KEY (serial_id) REFERENCES inv.serial_numbers(serial_id);

ALTER TABLE inv.stock_balance
    ADD CONSTRAINT fk_inv_stock_balance_batch FOREIGN KEY (batch_id) REFERENCES inv.batches(batch_id);

ALTER TABLE inv.stock_reservations
    ADD CONSTRAINT fk_inv_stock_reservations_batch FOREIGN KEY (batch_id) REFERENCES inv.batches(batch_id);
