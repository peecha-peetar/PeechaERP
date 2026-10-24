-- برگشت R303: حذف کلیدهای کنترل انبار و ایندکس‌های یکتای وظایف (داده‌ای از اسناد حذف نمی‌شود).
BEGIN;
DROP INDEX IF EXISTS inv.ux_inv_warehouse_tasks_stock_line;
DROP INDEX IF EXISTS inv.ux_inv_warehouse_tasks_comm_line;
DELETE FROM inv.company_features WHERE feature_code IN (
    'WMS_ENFORCE_RESERVATION', 'WMS_SALES_ORDER_RESERVATION', 'WMS_LOCATION_STATUS_CONTROL',
    'WMS_BLOCK_EXPIRED_ISSUE', 'WMS_ENFORCE_WAREHOUSE_ACCESS', 'WMS_DETAILED_MOBILE_PERMISSIONS');
DELETE FROM inv.feature_definitions WHERE feature_code IN (
    'WMS_ENFORCE_RESERVATION', 'WMS_SALES_ORDER_RESERVATION', 'WMS_LOCATION_STATUS_CONTROL',
    'WMS_BLOCK_EXPIRED_ISSUE', 'WMS_ENFORCE_WAREHOUSE_ACCESS', 'WMS_DETAILED_MOBILE_PERMISSIONS');
DELETE FROM public.peecha_schema_migrations WHERE filename = '214_wms_foundation.sql';
COMMIT;
