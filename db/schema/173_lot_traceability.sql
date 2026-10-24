-- پیچا R227: ردیابیِ بچ/سریال/تاریخِ انقضا و کالایِ امانی بر اساسِ تامین‌کننده.
-- موجودیِ کمّی همچنان فقط در inv.stock_balances (بدونِ تغییر در موتورِ انبار)؛
-- این دو جدول لایهٔ ردیابی‌اند: ورودیِ کاربر پیش از ثبت، و دفترِ حرکتِ بچ/سریال.

-- اطلاعاتِ ورودی (شمارهٔ بچ، تاریخِ تولید/انقضا، سریال) رویِ ردیفِ سندِ انبار
-- یا ردیفِ سندِ بازرگانی (سفارشِ خرید در تاییدِ رسید، فاکتورِ خرید، امانیِ ورودی).
CREATE TABLE IF NOT EXISTS inv.line_tracking_entries (
    entry_id BIGSERIAL PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    commercial_line_id BIGINT REFERENCES comm.commercial_document_lines(line_id) ON DELETE CASCADE,
    stock_line_id BIGINT REFERENCES inv.stock_document_lines(line_id) ON DELETE CASCADE,
    batch_no VARCHAR(50),
    manufacture_date DATE,
    expiry_date DATE,
    serial_no VARCHAR(100),
    quantity NUMERIC(18, 6) NOT NULL CHECK (quantity > 0),
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    CONSTRAINT ck_inv_line_tracking_one_owner CHECK ((commercial_line_id IS NULL) <> (stock_line_id IS NULL))
);
CREATE INDEX IF NOT EXISTS ix_inv_line_tracking_comm ON inv.line_tracking_entries (commercial_line_id);
CREATE INDEX IF NOT EXISTS ix_inv_line_tracking_stock ON inv.line_tracking_entries (stock_line_id);

-- دفترِ حرکتِ ردیابی (به واحدِ پایه، علامت‌دار): ورودی مثبت، خروجی منفی.
-- کلیدِ «استخر»: کالا + انبار + بچ + سریال + تامین‌کننده + امانی‌بودن.
CREATE TABLE IF NOT EXISTS inv.lot_movements (
    movement_id BIGSERIAL PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    item_id INT NOT NULL REFERENCES inv.items(item_id),
    warehouse_id INT NOT NULL REFERENCES inv.warehouses(warehouse_id),
    batch_id INT REFERENCES inv.batches(batch_id),
    serial_id INT REFERENCES inv.serial_numbers(serial_id),
    supplier_detail_account_id INT REFERENCES acc.detail_accounts(detail_account_id),
    is_consignment BOOLEAN NOT NULL DEFAULT FALSE,
    stock_document_line_id BIGINT REFERENCES inv.stock_document_lines(line_id),
    commercial_line_id BIGINT REFERENCES comm.commercial_document_lines(line_id),
    quantity_base NUMERIC(18, 6) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_inv_lot_movements_pool ON inv.lot_movements (company_id, item_id, warehouse_id);
CREATE INDEX IF NOT EXISTS ix_inv_lot_movements_batch ON inv.lot_movements (batch_id);
CREATE INDEX IF NOT EXISTS ix_inv_lot_movements_serial ON inv.lot_movements (serial_id);
CREATE INDEX IF NOT EXISTS ix_inv_lot_movements_stock_line ON inv.lot_movements (stock_document_line_id);
