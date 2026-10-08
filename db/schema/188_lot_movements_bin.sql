-- پیچا R251: بچ/سریال به تفکیکِ محل -- فقط افزایشی.
-- inv.lot_movements تا امروز فقط انبار داشت؛ ستونِ bin_location_id اضافه می‌شود و از دفترِ انبار (stock_ledger،
-- همان ردیفِ سند و همان جهت) پر می‌شود. موتورِ انبار و ماندهٔ ریالی تغییری نمی‌کنند.
-- پرکردنِ سوابق: فقط ستونِ تازه مقدار می‌گیرد؛ داده‌ای حذف یا جابه‌جا نمی‌شود. ردیفی که در دفترِ انبار چند محل
-- برایِ همان جهت دارد (نادر) کوچک‌ترین شناسه را می‌گیرد.
-- بازگشت (rollback): ALTER TABLE inv.lot_movements DROP COLUMN IF EXISTS bin_location_id;
ALTER TABLE inv.lot_movements ADD COLUMN IF NOT EXISTS bin_location_id INT NULL REFERENCES inv.bin_locations(bin_location_id);
UPDATE inv.lot_movements lm SET bin_location_id = (
    SELECT MIN(sl.bin_location_id) FROM inv.stock_ledger sl
    WHERE sl.stock_document_line_id = lm.stock_document_line_id AND sl.warehouse_id = lm.warehouse_id
      AND sl.movement_direction = CASE WHEN lm.quantity_base > 0 THEN 'IN' ELSE 'OUT' END)
WHERE lm.bin_location_id IS NULL AND lm.stock_document_line_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_inv_lot_movements_bin ON inv.lot_movements (bin_location_id, item_id);
