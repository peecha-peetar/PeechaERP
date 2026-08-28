-- پیچا | ماژولِ انبار و لجستیک — موتورِ موجودی و اسنادِ عملیاتی
-- طبقِ سندِ معماری (مراحلِ ۵، ۶، ۱۰): سرِسند+ردیف → (Post) → stock_ledger
-- (Append-Only) → stock_balance. هیچ کدی مستقیماً stock_balance را
-- UPDATE نمی‌کند مگر از طریقِ موتورِ services/inventory_engine.py.
-- پیش‌نیاز: 058_inventory_locations.sql

-- ---------------------------------------------------------------------
-- دلیلِ ساختاریافتهٔ اصلاح/برگشت — Lookup قابلِ‌پیکربندی، هم‌الگو با hr.lookup_*
-- ---------------------------------------------------------------------
CREATE TABLE inv.document_reason_codes (
    reason_code_id INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id      INT         NULL REFERENCES core.companies(company_id),  -- NULL = پیش‌فرضِ سراسری
    applies_to        VARCHAR(20) NOT NULL CHECK (applies_to IN ('ADJUSTMENT', 'RETURN_IN', 'RETURN_OUT')),
    code                VARCHAR(30) NOT NULL,
    name                 VARCHAR(100) NOT NULL,
    is_active             BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_inv_document_reason_codes UNIQUE (company_id, applies_to, code)
);

-- ---------------------------------------------------------------------
-- سرِسند
-- ---------------------------------------------------------------------
CREATE TABLE inv.stock_documents (
    stock_document_id            BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id                    INT        NOT NULL REFERENCES core.companies(company_id),
    fiscal_year_id                  INT      NOT NULL REFERENCES acc.fiscal_years(fiscal_year_id),
    document_type_code                VARCHAR(15) NOT NULL
        CHECK (document_type_code IN ('RECEIPT', 'ISSUE', 'TRANSFER', 'RETURN_IN', 'RETURN_OUT', 'ADJUSTMENT')),
    document_no                        INT     NOT NULL,
    document_date                       DATE   NOT NULL,
    status_code                          VARCHAR(15) NOT NULL DEFAULT 'DRAFT'
        CHECK (status_code IN ('DRAFT', 'CONFIRMED', 'POSTED', 'CANCELLED')),
    source_warehouse_id                   INT   NULL REFERENCES inv.warehouses(warehouse_id),
    destination_warehouse_id               INT  NULL REFERENCES inv.warehouses(warehouse_id),
    counterparty_detail_account_id          INT  NULL REFERENCES acc.detail_accounts(detail_account_id),
    cost_center_detail_account_id            INT NULL REFERENCES acc.detail_accounts(detail_account_id),
    project_detail_account_id                 INT NULL REFERENCES acc.detail_accounts(detail_account_id),
    reference_no                               VARCHAR(50) NULL,
    description                                 TEXT NULL,
    journal_entry_id                             INT NULL REFERENCES acc.journal_entries(journal_entry_id),
    -- طبقِ مرحلهٔ ۹: ردیابیِ جلسهٔ انبارگردانیِ مبدا، اگر این سند نتیجهٔ
    -- تاییدِ یک جلسهٔ شمارشِ فیزیکی باشد. FK واقعی در 062 (پسِ ساختِ
    -- inv.cycle_count_sessions) اضافه می‌شود تا وابستگیِ دوری پیش نیاید.
    cycle_count_session_id                        INT NULL,
    created_by_user_id                             INT NOT NULL REFERENCES sec.users(user_id),
    created_at                                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    posted_by_user_id                                INT NULL REFERENCES sec.users(user_id),
    posted_at                                         TIMESTAMPTZ NULL,
    CONSTRAINT uq_inv_stock_documents UNIQUE (company_id, fiscal_year_id, document_type_code, document_no),
    CONSTRAINT ck_inv_stock_documents_warehouses CHECK (
        CASE document_type_code
            WHEN 'RECEIPT'    THEN destination_warehouse_id IS NOT NULL AND source_warehouse_id IS NULL
            WHEN 'RETURN_IN'  THEN destination_warehouse_id IS NOT NULL AND source_warehouse_id IS NULL
            WHEN 'ISSUE'      THEN source_warehouse_id IS NOT NULL AND destination_warehouse_id IS NULL
            WHEN 'RETURN_OUT' THEN source_warehouse_id IS NOT NULL AND destination_warehouse_id IS NULL
            WHEN 'TRANSFER'   THEN source_warehouse_id IS NOT NULL AND destination_warehouse_id IS NOT NULL
            WHEN 'ADJUSTMENT' THEN source_warehouse_id IS NOT NULL OR destination_warehouse_id IS NOT NULL
            ELSE TRUE
        END
    )
);
CREATE INDEX ix_inv_stock_documents_company_date ON inv.stock_documents(company_id, document_date);

-- ---------------------------------------------------------------------
-- ردیف
-- ---------------------------------------------------------------------
CREATE TABLE inv.stock_document_lines (
    line_id                    BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    stock_document_id           BIGINT      NOT NULL REFERENCES inv.stock_documents(stock_document_id),
    line_no                      SMALLINT    NOT NULL,
    item_id                       INT        NOT NULL REFERENCES inv.items(item_id),
    uom_id                         INT       NOT NULL REFERENCES inv.uom(uom_id),
    quantity                        NUMERIC(18,6) NOT NULL CHECK (quantity > 0),
    quantity_base                    NUMERIC(18,6) NOT NULL CHECK (quantity_base > 0),
    -- برایِ همه‌جز TRANSFER: تنها مکان (مبدا یا مقصد، بسته به نوعِ سند).
    -- برایِ TRANSFER: مکانِ مبدا؛ destination_bin_location_id مکانِ مقصد است
    -- (طبقِ اصلاحِ صریحِ مرحلهٔ ۶ — یک ستونِ تکی برایِ بیانِ «انتقالِ
    -- فقط‌مکانی» کافی نبود).
    bin_location_id                   INT    NULL REFERENCES inv.bin_locations(bin_location_id),
    destination_bin_location_id        INT   NULL REFERENCES inv.bin_locations(bin_location_id),
    -- FK به inv.batches در 060 اضافه می‌شود (پسِ ساختِ آن جدول؛ همان الگویِ
    -- forward-reference که برایِ cycle_count_session_id بالاتر استفاده شد).
    batch_id                            INT  NULL,
    unit_cost                            NUMERIC(18,6) NULL,
    line_total_cost                       NUMERIC(18,2) GENERATED ALWAYS AS (ROUND(quantity_base * unit_cost, 2)) STORED,
    quality_status_code                    VARCHAR(15) NOT NULL DEFAULT 'APPROVED'
        CHECK (quality_status_code IN ('PENDING', 'APPROVED', 'QUARANTINE', 'REJECTED')),
    -- دلیلِ ساختاریافته — الزامی فقط برایِ ADJUSTMENT/RETURN_IN/RETURN_OUT
    -- (اجباری‌بودن در لایهٔ سرویس بررسی می‌شود، نه CHECK، چون applies_to
    -- در جدولِ دیگری‌ست).
    reason_code_id                          INT NULL REFERENCES inv.document_reason_codes(reason_code_id),
    -- برایِ RETURN: ردیفِ سندِ اصلی که این برگشت به آن ارجاع می‌دهد.
    source_line_id                           BIGINT NULL REFERENCES inv.stock_document_lines(line_id),
    -- برایِ ISSUE/TRANSFER-OUT: رزروی که این ردیف برآورده می‌کند (مرحلهٔ ۱۰).
    -- FK واقعی در 061 (پسِ ساختِ inv.stock_reservations) اضافه می‌شود.
    reservation_id                            INT NULL,
    description                                VARCHAR(500) NULL,
    CONSTRAINT uq_inv_stock_document_lines UNIQUE (stock_document_id, line_no)
);

-- ---------------------------------------------------------------------
-- دفترِ حرکاتِ موجودی (Append-Only)
-- ---------------------------------------------------------------------
CREATE TABLE inv.stock_ledger (
    ledger_id                  BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id                  INT         NOT NULL REFERENCES core.companies(company_id),
    stock_document_line_id       BIGINT     NOT NULL REFERENCES inv.stock_document_lines(line_id),
    item_id                       INT        NOT NULL REFERENCES inv.items(item_id),
    warehouse_id                   INT       NOT NULL REFERENCES inv.warehouses(warehouse_id),
    bin_location_id                 INT      NOT NULL REFERENCES inv.bin_locations(bin_location_id),
    batch_id                         INT      NULL,  -- FK به inv.batches در 060
    serial_id                         INT     NULL,  -- FK به inv.serial_numbers در 060
    movement_direction                  VARCHAR(3) NOT NULL CHECK (movement_direction IN ('IN', 'OUT')),
    quantity_base                        NUMERIC(18,6) NOT NULL CHECK (quantity_base > 0),
    unit_cost                             NUMERIC(18,6) NULL,
    total_cost                             NUMERIC(18,2) GENERATED ALWAYS AS (ROUND(quantity_base * unit_cost, 2)) STORED,
    movement_date                           DATE NOT NULL,
    created_at                               TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- توجه: طبقِ مرحلهٔ ۵ بخشِ ۲۱، Partitioningِ این جدول بر اساسِ movement_date
-- برایِ حجمِ بالا توصیه شده — اما چون inv.cost_layers (۰۶۱) با یک FKِ ساده
-- به ledger_id ارجاع می‌دهد، و Postgres رویِ جدولِ Partitionedشده اجازه‌یِ
-- محدودیتِ یکتایِ سراسری رویِ ستونی غیر از کلیدِ Partition را نمی‌دهد،
-- Partitioning عمداً به یک مهاجرتِ اختصاصیِ بعدی (وقتی حجمِ واقعی توجیه‌اش
-- کند) موکول شد — تصمیمی آگاهانه، نه سهو.

CREATE INDEX ix_inv_stock_ledger_item_wh_date ON inv.stock_ledger(item_id, warehouse_id, movement_date);
CREATE INDEX ix_inv_stock_ledger_batch ON inv.stock_ledger(batch_id);
CREATE INDEX ix_inv_stock_ledger_bin ON inv.stock_ledger(bin_location_id);
CREATE INDEX ix_inv_stock_ledger_company_date ON inv.stock_ledger(company_id, movement_date DESC);

CREATE FUNCTION inv.prevent_stock_ledger_modification() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'دفترِ موجودی تغییرناپذیر است: عملیاتِ % روی inv.stock_ledger مجاز نیست', TG_OP;
END;
$$;

CREATE TRIGGER tr_inv_stock_ledger_immutable
    BEFORE UPDATE OR DELETE ON inv.stock_ledger
    FOR EACH ROW EXECUTE FUNCTION inv.prevent_stock_ledger_modification();

-- ---------------------------------------------------------------------
-- مانده
-- ---------------------------------------------------------------------
CREATE TABLE inv.stock_balance (
    stock_balance_id       BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id               INT        NOT NULL REFERENCES core.companies(company_id),
    item_id                   INT        NOT NULL REFERENCES inv.items(item_id),
    warehouse_id               INT       NOT NULL REFERENCES inv.warehouses(warehouse_id),
    bin_location_id             INT      NOT NULL REFERENCES inv.bin_locations(bin_location_id),
    batch_id                     INT     NULL,  -- FK به inv.batches در 060
    quantity_on_hand               NUMERIC(18,6) NOT NULL DEFAULT 0,
    quantity_reserved                NUMERIC(18,6) NOT NULL DEFAULT 0,
    quantity_available                 NUMERIC(18,6) GENERATED ALWAYS AS (quantity_on_hand - quantity_reserved) STORED,
    average_unit_cost                   NUMERIC(18,6) NOT NULL DEFAULT 0,
    total_value                          NUMERIC(18,2) GENERATED ALWAYS AS (ROUND(quantity_on_hand * average_unit_cost, 2)) STORED,
    last_movement_at                      TIMESTAMPTZ NULL
);
CREATE UNIQUE INDEX ux_inv_stock_balance_no_batch
    ON inv.stock_balance(item_id, warehouse_id, bin_location_id) WHERE batch_id IS NULL;
CREATE UNIQUE INDEX ux_inv_stock_balance_batch
    ON inv.stock_balance(item_id, warehouse_id, bin_location_id, batch_id) WHERE batch_id IS NOT NULL;

-- ---------------------------------------------------------------------
-- رزروِ موجودی
-- ---------------------------------------------------------------------
CREATE TABLE inv.stock_reservations (
    reservation_id        BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id              INT        NOT NULL REFERENCES core.companies(company_id),
    item_id                  INT        NOT NULL REFERENCES inv.items(item_id),
    warehouse_id               INT      NOT NULL REFERENCES inv.warehouses(warehouse_id),
    bin_location_id              INT   NULL REFERENCES inv.bin_locations(bin_location_id),
    batch_id                      INT  NULL,  -- FK به inv.batches در 060
    quantity                       NUMERIC(18,6) NOT NULL CHECK (quantity > 0),
    -- طبقِ مرحلهٔ ۱۰: اولویت (کوچک‌تر = بالاتر) و برآوردهٔ جزئی.
    priority_level                  SMALLINT NOT NULL DEFAULT 100,
    fulfilled_quantity_base           NUMERIC(18,6) NOT NULL DEFAULT 0,
    remaining_quantity_base             NUMERIC(18,6) GENERATED ALWAYS AS (quantity - fulfilled_quantity_base) STORED,
    source_type_code                     VARCHAR(30) NOT NULL,
    source_record_id                      BIGINT NOT NULL,
    status_code                            VARCHAR(15) NOT NULL DEFAULT 'ACTIVE'
        CHECK (status_code IN ('ACTIVE', 'FULFILLED', 'CANCELLED', 'EXPIRED')),
    expires_at                              TIMESTAMPTZ NULL,
    created_at                               TIMESTAMPTZ NOT NULL DEFAULT now(),
    released_at                               TIMESTAMPTZ NULL,
    CONSTRAINT ck_inv_stock_reservations_fulfilled CHECK (fulfilled_quantity_base <= quantity)
);
CREATE INDEX ix_inv_stock_reservations_source ON inv.stock_reservations(source_type_code, source_record_id);
CREATE INDEX ix_inv_stock_reservations_active ON inv.stock_reservations(item_id, warehouse_id) WHERE status_code = 'ACTIVE';

ALTER TABLE inv.stock_document_lines
    ADD CONSTRAINT fk_inv_stock_document_lines_reservation
        FOREIGN KEY (reservation_id) REFERENCES inv.stock_reservations(reservation_id);
