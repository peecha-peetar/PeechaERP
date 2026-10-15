-- پیچا R257: هستهٔ ماژولِ بهایِ تمام‌شده و ارزش‌گذاریِ موجودی (فقط افزودنی).
-- لایه‌هایِ موجودِ FIFO (inv.cost_layers) گسترش می‌یابند، نه جایگزین؛ ارتباطِ هر خروج با لایه در
-- inv.cost_allocations ثبت می‌شود؛ روش‌هایِ تازه به همان inv.costing_methods افزوده می‌شوند.

-- ۱) روش‌هایِ تازه (WEIGHTED_AVERAGE همان «میانگینِ متحرک» است و دوباره ساخته نمی‌شود)
INSERT INTO inv.costing_methods (costing_method_id, code) VALUES
    (4, 'LIFO'), (5, 'HIFO'), (6, 'LOFO'), (7, 'SPECIFIC'), (8, 'NIFO')
ON CONFLICT DO NOTHING;

-- ۲) تنظیماتِ شرکت: سیاستِ موجودیِ منفی و ترتیبِ منبعِ بهایِ جایگزینی (NIFO)
ALTER TABLE inv.company_costing_settings
    ADD COLUMN IF NOT EXISTS negative_stock_policy VARCHAR(20) NOT NULL DEFAULT 'WAREHOUSE',
    ADD COLUMN IF NOT EXISTS nifo_price_sources VARCHAR(200) NOT NULL
        DEFAULT 'LAST_RECEIPT,LAST_PURCHASE_PRICE,LAST_PURCHASE_ORDER,SUPPLIER_PRICE,MANUAL';

-- ۳) گسترشِ لایه‌هایِ هزینه
ALTER TABLE inv.cost_layers
    ADD COLUMN IF NOT EXISTS company_id INT NULL REFERENCES core.companies(company_id),
    ADD COLUMN IF NOT EXISTS batch_id INT NULL REFERENCES inv.batches(batch_id),
    ADD COLUMN IF NOT EXISTS serial_id INT NULL REFERENCES inv.serial_numbers(serial_id),
    ADD COLUMN IF NOT EXISTS source_type_code VARCHAR(20) NULL,
    ADD COLUMN IF NOT EXISTS source_line_id BIGINT NULL REFERENCES inv.stock_document_lines(line_id),
    ADD COLUMN IF NOT EXISTS receipt_date DATE NULL,
    ADD COLUMN IF NOT EXISTS status_code VARCHAR(15) NOT NULL DEFAULT 'OPEN',
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL DEFAULT now();

-- پرکردنِ ستون‌هایِ تازه برایِ لایه‌هایِ قدیمی از رویِ همان ردیفِ دفترِ انبار (بدونِ تغییرِ مقدار/بها)
UPDATE inv.cost_layers cl
   SET company_id = sl.company_id,
       source_line_id = sl.stock_document_line_id,
       receipt_date = sl.movement_date,
       source_type_code = COALESCE(cl.source_type_code, 'LEGACY'),
       status_code = CASE WHEN cl.remaining_quantity > 0 THEN 'OPEN' ELSE 'CONSUMED' END
  FROM inv.stock_ledger sl
 WHERE sl.ledger_id = cl.stock_ledger_id AND cl.company_id IS NULL;

CREATE INDEX IF NOT EXISTS ix_inv_cost_layers_open
    ON inv.cost_layers (item_id, warehouse_id) WHERE remaining_quantity > 0;
CREATE INDEX IF NOT EXISTS ix_inv_cost_layers_source_line ON inv.cost_layers (source_line_id);

-- ۴) تخصیصِ بهایِ هر خروج (کدام لایه، چه مقدار، چه بها) -- منبعِ حقیقتِ بهایِ تمام‌شده
CREATE TABLE IF NOT EXISTS inv.cost_allocations (
    allocation_id          BIGSERIAL PRIMARY KEY,
    company_id             INT          NOT NULL REFERENCES core.companies(company_id),
    stock_document_line_id BIGINT       NOT NULL REFERENCES inv.stock_document_lines(line_id),
    item_id                INT          NOT NULL REFERENCES inv.items(item_id),
    warehouse_id           INT          NOT NULL REFERENCES inv.warehouses(warehouse_id),
    cost_layer_id          BIGINT       NULL REFERENCES inv.cost_layers(cost_layer_id),
    costing_method_code    VARCHAR(20)  NOT NULL,
    quantity_base          NUMERIC(18,6) NOT NULL CHECK (quantity_base > 0),
    unit_cost              NUMERIC(18,6) NOT NULL,
    total_cost             NUMERIC(18,2) GENERATED ALWAYS AS (round(quantity_base * unit_cost, 2)) STORED,
    movement_date          DATE         NOT NULL,
    costing_status_code    VARCHAR(25)  NOT NULL DEFAULT 'CALCULATED'
        CHECK (costing_status_code IN ('CALCULATED', 'PENDING', 'RECALCULATION_REQUIRED', 'ERROR')),
    note                   VARCHAR(300) NULL,
    created_at             TIMESTAMP    NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_inv_cost_allocations_line ON inv.cost_allocations (stock_document_line_id);
CREATE INDEX IF NOT EXISTS ix_inv_cost_allocations_item ON inv.cost_allocations (company_id, item_id, movement_date);
CREATE INDEX IF NOT EXISTS ix_inv_cost_allocations_layer ON inv.cost_allocations (cost_layer_id);
CREATE INDEX IF NOT EXISTS ix_inv_cost_allocations_status ON inv.cost_allocations (company_id, costing_status_code)
    WHERE costing_status_code <> 'CALCULATED';
