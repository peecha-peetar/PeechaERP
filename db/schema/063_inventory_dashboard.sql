-- پیچا | ماژولِ انبار و لجستیک — حافظهٔ‌پنهانِ روزانهٔ داشبورد
-- طبقِ سندِ معماری (مرحلهٔ ۱۲): این جدول فقط یک Cacheِ نمایشی برایِ
-- نمودارهایِ روند است، نه منبعِ حقیقت — همیشه از rویِ stock_ledger/
-- stock_balance و بقیهٔ جداولِ عملیاتی قابلِ‌بازسازی است.
-- پیش‌نیاز: 062_inventory_cycle_count.sql

CREATE TABLE inv.daily_kpi_snapshots (
    snapshot_id                BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id                   INT        NOT NULL REFERENCES core.companies(company_id),
    snapshot_date                  DATE     NOT NULL,
    total_inventory_value            NUMERIC(18,2) NOT NULL,
    total_active_items                 INT NOT NULL,
    total_warehouses                     INT NOT NULL,
    negative_balance_count                 INT NOT NULL,
    near_expiry_value                        NUMERIC(18,2) NOT NULL DEFAULT 0,
    critical_reorder_count                     INT NOT NULL DEFAULT 0,
    open_reservations_value                      NUMERIC(18,2) NOT NULL DEFAULT 0,
    CONSTRAINT uq_inv_daily_kpi_snapshots UNIQUE (company_id, snapshot_date)
);
