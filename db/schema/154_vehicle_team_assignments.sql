-- Field Sales (فازِ ۲ از پخشِ گرم): طبقِ درخواستِ صریحِ کاربر («ممکنه ۳
-- نفر به خودرو وصل بشه: راننده، ویزیتور، موزع -- ممکنه هر ۳ نقش را یک
-- نفر داشته باشه؛ این برایِ آینده است، اگر کسب‌وکاری خواست جدا کند
-- فکرش را کرده باشیم»): هر خودرو (inv.warehouses با
-- warehouse_type_code='VEHICLE') می‌تواند تا سه کاربر داشته باشد -- یکی
-- برایِ هر نقش. اگر یک نفر هر سه نقش را دارد، همان user_id در هر سه
-- ردیف تکرار می‌شود؛ چیزی این را از تفکیکِ آینده منع نمی‌کند.
--
-- نقش‌ها:
-- DRIVER      -- مسئولِ کلی/تحویلِ کلی/برگشتِ کالا (نه ثبتِ سفارش).
-- VISITOR     -- ثبتِ سفارش/فاکتور + تسویه‌حساب (همانی که تا امروز از
--                اپِ موبایل استفاده می‌کرد).
-- DISTRIBUTOR -- بر اساسِ فاکتورِ صادرشده، تحویلِ فیزیکیِ کالا + تسویه‌حساب.

CREATE TABLE inv.vehicle_team_assignments (
    vehicle_warehouse_id INT NOT NULL REFERENCES inv.warehouses(warehouse_id),
    role_code VARCHAR(15) NOT NULL,
    user_id INT NOT NULL REFERENCES sec.users(user_id),
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    PRIMARY KEY (vehicle_warehouse_id, role_code)
);

CREATE INDEX idx_vehicle_team_assignments_user ON inv.vehicle_team_assignments(user_id, company_id);
