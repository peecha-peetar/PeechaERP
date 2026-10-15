-- برگشت R312 (نگهداری و تعمیرات). داده‌های دارایی، انبار و حسابداری دست نمی‌خورند؛ اسناد انبار و رویدادهای دارایی
-- که از دستور کار ساخته شده‌اند می‌مانند. پیش از برگشت، محل‌های «کارخانه/ناحیه» باید به نوع دیگری تغییر کنند.
BEGIN;
DROP SCHEMA mnt CASCADE;
UPDATE fa.asset_locations SET location_type = 'SITE' WHERE location_type = 'PLANT';
UPDATE fa.asset_locations SET location_type = 'OTHER' WHERE location_type = 'AREA';
ALTER TABLE fa.asset_locations DROP CONSTRAINT IF EXISTS asset_locations_location_type_check;
ALTER TABLE fa.asset_locations ADD CONSTRAINT asset_locations_location_type_check
    CHECK (location_type IN ('SITE', 'BUILDING', 'FLOOR', 'ROOM', 'LINE', 'OTHER'));
DELETE FROM inv.company_features WHERE feature_code IN ('MNT_CAPACITY_PLANNED', 'MNT_STATUS_LOCK', 'MNT_SEPARATE_VERIFY', 'MNT_ROLE_PERMISSIONS');
DELETE FROM inv.feature_definitions WHERE feature_code IN ('MNT_CAPACITY_PLANNED', 'MNT_STATUS_LOCK', 'MNT_SEPARATE_VERIFY', 'MNT_ROLE_PERMISSIONS');
DELETE FROM inv.account_mappings WHERE mapping_key = 'MAINTENANCE_EXPENSE';
DELETE FROM public.peecha_schema_migrations WHERE filename = '222_maintenance.sql';
COMMIT;
