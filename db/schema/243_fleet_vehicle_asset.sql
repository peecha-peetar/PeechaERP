-- پیچا | R357: خودروی پخش (انبار نوع خودرو) ← تجهیز همان خودرو در نگهداری و دارایی ثابت
ALTER TABLE inv.warehouses ADD COLUMN IF NOT EXISTS vehicle_asset_id BIGINT REFERENCES fa.assets(asset_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_warehouses_vehicle_asset ON inv.warehouses(vehicle_asset_id) WHERE vehicle_asset_id IS NOT NULL;
