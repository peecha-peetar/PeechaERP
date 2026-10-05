-- پیچا R252: محلِ فعلیِ سریال و هم‌گام‌سازیِ رزروِ وظایفِ انبار با موجودیِ قابلِ‌فروش -- فقط به‌روزرسانیِ ستون‌هایِ موجود.
-- ۱) inv.serial_numbers.current_bin_location_id (از ابتدا وجود داشت ولی پر نمی‌شد): برایِ سریال‌هایِ موجود از آخرین
--    حرکتِ ورودیِ همان سریال (inv.lot_movements.bin_location_id) پر می‌شود.
-- ۲) inv.stock_balance.quantity_reserved: رزروهایِ فعالِ وظایفِ انبار (WMS_PICK_TASK / WMS_REPLENISH_TASK) از این نسخه
--    در ستونِ رزروِ مانده هم نگه داشته می‌شوند تا «موجودیِ آزاد» (کاتالوگِ موبایل، فروشگاهِ آنلاین، بارگیریِ خودرو)
--    آن را کم کند. رزروهایِ فعالِ نسخه‌هایِ قبل یک‌بار این‌جا اضافه می‌شوند.
-- بازگشت (rollback): ستونِ رزروِ مانده را با کم‌کردنِ همین مقدارها برگردانید؛ ستونِ سریال را می‌توان NULL کرد.
UPDATE inv.serial_numbers s SET current_bin_location_id = (
    SELECT lm.bin_location_id FROM inv.lot_movements lm
    WHERE lm.serial_id = s.serial_id AND lm.quantity_base > 0 AND lm.bin_location_id IS NOT NULL
    ORDER BY lm.movement_id DESC LIMIT 1)
WHERE s.status_code = 'IN_STOCK' AND s.current_bin_location_id IS NULL;

UPDATE inv.stock_balance b SET quantity_reserved = b.quantity_reserved + r.qty
FROM (SELECT item_id, warehouse_id, bin_location_id, SUM(quantity - fulfilled_quantity_base) AS qty
      FROM inv.stock_reservations
      WHERE status_code = 'ACTIVE' AND source_type_code IN ('WMS_PICK_TASK', 'WMS_REPLENISH_TASK') AND bin_location_id IS NOT NULL
      GROUP BY item_id, warehouse_id, bin_location_id) r
WHERE b.item_id = r.item_id AND b.warehouse_id = r.warehouse_id AND b.bin_location_id = r.bin_location_id AND b.batch_id IS NULL;
