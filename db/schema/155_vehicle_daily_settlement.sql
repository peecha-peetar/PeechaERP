-- Field Sales (فازِ ۲، بخشِ ۲ از پخشِ گرم): طبقِ درخواستِ صریحِ کاربر
-- («تسویه آخر روز باید بصورت انتخابی به یک نفر از ۳ نقش واگذار بشه و
-- تسویه را باید به تاییدِ انبار و حسابداری برسونه») -- پایانِ روزِ هر
-- خودرو یک سندِ مستقل است: کسی که نقشِ تعیین‌شده (راننده/ویزیتور/موزع،
-- طبقِ تنظیمِ vehicle_settlement_settings) را دارد، مقدارِ برگشتیِ هر
-- کالا را از موبایل ثبت می‌کند؛ سپس دو گیتِ جداگانه -- هم‌الگو با
-- warehouse_approved_at/weighing_approved_atِ پخشِ سرد (147) -- باید
-- طی شود: تاییدِ انبار (بررسیِ فیزیکیِ برگشتی) و تاییدِ حسابداری
-- (بررسیِ مبلغِ نقدیِ تحویلی). تاییدِ نهاییِ حسابداری سندِ TRANSFERِ
-- واقعی (خودرو -> انبارِ مقصد) می‌سازد تا موجودیِ خودرو/انبارِ مرکزی
-- درست به‌روز شود (TRANSFER، نه RETURN_IN -- این کالاها هیچ‌وقت فروخته
-- نشده‌اند، فقط فیزیکی جابه‌جا می‌شوند).

CREATE TABLE inv.vehicle_settlement_settings (
    company_id INT PRIMARY KEY REFERENCES core.companies(company_id),
    settlement_role_code VARCHAR(15) NOT NULL
);

CREATE TABLE inv.vehicle_settlements (
    vehicle_settlement_id BIGSERIAL PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    vehicle_warehouse_id INT NOT NULL REFERENCES inv.warehouses(warehouse_id),
    return_destination_warehouse_id INT NOT NULL REFERENCES inv.warehouses(warehouse_id),
    settlement_date DATE NOT NULL,
    status_code VARCHAR(20) NOT NULL DEFAULT 'SUBMITTED',  -- SUBMITTED | WAREHOUSE_APPROVED | ACCOUNTING_APPROVED
    invoiced_amount NUMERIC(18, 2) NOT NULL DEFAULT 0,
    declared_cash_amount NUMERIC(18, 2) NOT NULL DEFAULT 0,
    submitted_by_user_id INT NOT NULL REFERENCES sec.users(user_id),
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    warehouse_approved_by_user_id INT REFERENCES sec.users(user_id),
    warehouse_approved_at TIMESTAMPTZ,
    accounting_approved_by_user_id INT REFERENCES sec.users(user_id),
    accounting_approved_at TIMESTAMPTZ,
    return_stock_document_id BIGINT REFERENCES inv.stock_documents(stock_document_id),
    notes TEXT
);

CREATE INDEX idx_vehicle_settlements_vehicle_date ON inv.vehicle_settlements(vehicle_warehouse_id, settlement_date);

CREATE TABLE inv.vehicle_settlement_lines (
    vehicle_settlement_line_id BIGSERIAL PRIMARY KEY,
    vehicle_settlement_id BIGINT NOT NULL REFERENCES inv.vehicle_settlements(vehicle_settlement_id),
    item_id INT NOT NULL REFERENCES inv.items(item_id),
    uom_id INT NOT NULL REFERENCES inv.uom(uom_id),
    loaded_quantity NUMERIC(18, 6) NOT NULL,
    sold_quantity NUMERIC(18, 6) NOT NULL,
    returned_quantity NUMERIC(18, 6) NOT NULL
);
