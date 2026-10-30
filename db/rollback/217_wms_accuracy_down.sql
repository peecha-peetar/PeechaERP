-- برگشت R306: حذف کلیدهای تطبیق شمارش و نگه‌داشت کیفیت (نگه‌داشت‌های فعال کیفیت آزاد می‌شوند).
BEGIN;
UPDATE inv.stock_balance b SET quantity_reserved = GREATEST(0, b.quantity_reserved - r.qty)
  FROM (SELECT item_id, warehouse_id, bin_location_id, SUM(quantity - COALESCE(fulfilled_quantity_base, 0)) AS qty
          FROM inv.stock_reservations WHERE source_type_code = 'QC_HOLD' AND status_code = 'ACTIVE'
         GROUP BY item_id, warehouse_id, bin_location_id) r
 WHERE b.item_id = r.item_id AND b.warehouse_id = r.warehouse_id AND b.bin_location_id = r.bin_location_id AND b.batch_id IS NULL;
UPDATE inv.stock_reservations SET status_code = 'CANCELLED', released_at = now()
 WHERE source_type_code = 'QC_HOLD' AND status_code = 'ACTIVE';
DELETE FROM inv.company_features WHERE feature_code IN ('WMS_COUNT_RECONCILE', 'WMS_QC_HOLD');
DELETE FROM inv.feature_definitions WHERE feature_code IN ('WMS_COUNT_RECONCILE', 'WMS_QC_HOLD');
DELETE FROM public.peecha_schema_migrations WHERE filename = '217_wms_accuracy.sql';
COMMIT;
