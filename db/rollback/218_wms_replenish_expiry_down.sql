-- برگشت R307: حذف کلیدهای تامین مجدد هوشمند و هشدار انقضا و جدول تنظیم آن.
BEGIN;
DROP TABLE IF EXISTS inv.wms_settings;
DELETE FROM inv.company_features WHERE feature_code IN ('WMS_SMART_REPLENISH', 'WMS_EXPIRY_ALERTS');
DELETE FROM inv.feature_definitions WHERE feature_code IN ('WMS_SMART_REPLENISH', 'WMS_EXPIRY_ALERTS');
DELETE FROM public.peecha_schema_migrations WHERE filename = '218_wms_replenish_expiry.sql';
COMMIT;
