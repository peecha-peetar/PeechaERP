-- پیچا | R357: دفتر سوخت و کیلومتر خودروی پخش؛ کیلومتر پیموده به کارکرد تجهیز (fa.asset_usage) می‌رود
CREATE TABLE IF NOT EXISTS inv.vehicle_fuel_logs (
    fuel_log_id              BIGSERIAL      PRIMARY KEY,
    company_id               INT            NOT NULL REFERENCES core.companies(company_id),
    vehicle_warehouse_id     INT            NOT NULL REFERENCES inv.warehouses(warehouse_id),
    log_date                 DATE           NOT NULL,
    odometer_km              NUMERIC(12, 1),
    liters                   NUMERIC(10, 2) NOT NULL CHECK (liters > 0),
    amount                   NUMERIC(18, 2) NOT NULL DEFAULT 0 CHECK (amount >= 0),
    fuel_type_code           VARCHAR(10)    NOT NULL DEFAULT 'GASOLINE',
    driver_detail_account_id INT            REFERENCES acc.detail_accounts(detail_account_id),
    usage_id                 BIGINT         REFERENCES fa.asset_usage(usage_id) ON DELETE SET NULL,
    note                     VARCHAR(300),
    created_by_user_id       INT            REFERENCES sec.users(user_id),
    created_at               TIMESTAMPTZ    NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_vehicle_fuel_logs_vehicle ON inv.vehicle_fuel_logs(company_id, vehicle_warehouse_id, log_date);
