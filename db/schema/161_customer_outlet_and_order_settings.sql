-- پیچا | نوعِ کانال (طبقه‌بندیِ فروشگاهی) + تنظیماتِ سفارشِ مشتری (R219،
-- بخشِ ۳) -- رویِ همان comm.customer_profیلِ موجود، بدونِ جدولِ موازی.

ALTER TABLE comm.customer_profiles
    ADD COLUMN outlet_type_code VARCHAR(20) NULL
        CHECK (outlet_type_code IN (
            'SUPERMARKET', 'CHAIN_STORE', 'WHOLESALE', 'RESTAURANT', 'PHARMACY',
            'SPECIALTY_STORE', 'ORGANIZATIONAL', 'OTHER'
        )),
    ADD COLUMN priority_code VARCHAR(10) NULL
        CHECK (priority_code IN ('LOW', 'NORMAL', 'HIGH', 'VIP')),
    ADD COLUMN min_order_amount NUMERIC(18, 2) NULL CHECK (min_order_amount IS NULL OR min_order_amount >= 0),
    ADD COLUMN min_order_quantity NUMERIC(18, 3) NULL CHECK (min_order_quantity IS NULL OR min_order_quantity >= 0),
    -- طبقِ الگویِ acc.detail_group_fields (بیت‌های ۱ تا ۷ = شنبه..جمعه)؛
    -- NULL یعنی «هر روز مجاز است» (بدونِ محدودیت).
    ADD COLUMN allowed_order_days_mask SMALLINT NULL CHECK (allowed_order_days_mask IS NULL OR allowed_order_days_mask BETWEEN 1 AND 127),
    ADD COLUMN allowed_order_hour_from SMALLINT NULL CHECK (allowed_order_hour_from IS NULL OR allowed_order_hour_from BETWEEN 0 AND 23),
    ADD COLUMN allowed_order_hour_to SMALLINT NULL CHECK (allowed_order_hour_to IS NULL OR allowed_order_hour_to BETWEEN 0 AND 23),
    ADD COLUMN expected_delivery_days SMALLINT NULL CHECK (expected_delivery_days IS NULL OR expected_delivery_days >= 0),
    ADD COLUMN shipment_type_code VARCHAR(20) NULL
        CHECK (shipment_type_code IN ('VEHICLE_ROUTE', 'COURIER', 'FREIGHT', 'PICKUP')),
    ADD COLUMN default_warehouse_id INT NULL REFERENCES inv.warehouses(warehouse_id);
