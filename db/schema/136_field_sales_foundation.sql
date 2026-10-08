-- طبقِ طرحِ تاییدشده (R129 -- فازِ اولِ ماژولِ پخشِ سرد/گرم): زیرساختِ
-- میدانی -- برنامهٔ مراجعه، ویزیتِ واقعی، بارگیریِ خودرو، تاییدِ تحویل،
-- و موتورِ پروموشن. این فاز فقط دیتامدل+سرویس است؛ UI دسکتاپی (R130)،
-- لایهٔ API (R131) و اپِ موبایل (R132) در فازهایِ بعدی اضافه می‌شوند.

-- طبقِ درخواستِ صریح («فاصله از موقعیتِ مشتری» در چک‌این): بدونِ مختصاتِ
-- ثبت‌شدهٔ خودِ مشتری، محاسبهٔ فاصله در customer_visits بی‌معنی است.
ALTER TABLE comm.customer_profiles ADD COLUMN gps_latitude NUMERIC(9,6) NULL;
ALTER TABLE comm.customer_profiles ADD COLUMN gps_longitude NUMERIC(9,6) NULL;

-- ---------------------------------------------------------------------
-- برنامهٔ مراجعه -- هر ردیف یعنی «این مشتری این روزِ هفته باید دیده شود»
-- ---------------------------------------------------------------------
CREATE TABLE comm.visit_plans (
    visit_plan_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    customer_detail_account_id INT NOT NULL REFERENCES acc.detail_accounts(detail_account_id),
    -- طبقِ date.weekday()ِ پایتون: ۰=دوشنبه ... ۶=یکشنبه.
    visit_day_of_week SMALLINT NOT NULL CHECK (visit_day_of_week BETWEEN 0 AND 6),
    sequence_order SMALLINT NOT NULL DEFAULT 0,
    assigned_visitor_user_id INT NULL REFERENCES sec.users(user_id),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_visit_plans_customer_day UNIQUE (customer_detail_account_id, visit_day_of_week)
);

-- ---------------------------------------------------------------------
-- ویزیتِ واقعی -- هر بار حضور (طبق‌برنامه یا بی‌برنامه)
-- ---------------------------------------------------------------------
CREATE TABLE comm.customer_visits (
    customer_visit_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    visit_plan_id INT NULL REFERENCES comm.visit_plans(visit_plan_id),
    customer_detail_account_id INT NOT NULL REFERENCES acc.detail_accounts(detail_account_id),
    visitor_user_id INT NOT NULL REFERENCES sec.users(user_id),
    status_code VARCHAR(15) NOT NULL DEFAULT 'IN_PROGRESS'
        CHECK (status_code IN ('IN_PROGRESS', 'COMPLETED', 'SKIPPED')),
    skip_reason VARCHAR(200) NULL,
    checked_in_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    checked_out_at TIMESTAMPTZ NULL,
    check_in_latitude NUMERIC(9,6) NULL,
    check_in_longitude NUMERIC(9,6) NULL,
    distance_from_customer_m NUMERIC(10,1) NULL,
    notes VARCHAR(500) NULL
);

-- ---------------------------------------------------------------------
-- بارگیریِ خودرو -- Pick Listِ صبح، پیش از پخشِ گرم
-- ---------------------------------------------------------------------
CREATE TABLE inv.vehicle_loadings (
    vehicle_loading_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    vehicle_warehouse_id INT NOT NULL REFERENCES inv.warehouses(warehouse_id),
    source_warehouse_id INT NOT NULL REFERENCES inv.warehouses(warehouse_id),
    loading_date DATE NOT NULL,
    status_code VARCHAR(15) NOT NULL DEFAULT 'DRAFT'
        CHECK (status_code IN ('DRAFT', 'CONFIRMED')),
    -- پرشده فقط پسِ تاییدِ بارگیری -- سندِ TRANSFERِ واقعی که موجودی را
    -- جابه‌جا می‌کند؛ منطقِ انبار در inventory_documents.py دوباره
    -- نوشته نمی‌شود، همان سرویسِ موجود صدا زده می‌شود.
    stock_document_id BIGINT NULL REFERENCES inv.stock_documents(stock_document_id),
    driver_confirmed_by_user_id INT NULL REFERENCES sec.users(user_id),
    driver_confirmed_at TIMESTAMPTZ NULL,
    notes VARCHAR(500) NULL,
    created_by_user_id INT NOT NULL REFERENCES sec.users(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE inv.vehicle_loading_lines (
    vehicle_loading_line_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    vehicle_loading_id INT NOT NULL REFERENCES inv.vehicle_loadings(vehicle_loading_id),
    item_id INT NOT NULL REFERENCES inv.items(item_id),
    uom_id INT NOT NULL REFERENCES inv.uom(uom_id),
    planned_quantity NUMERIC(18,6) NOT NULL CHECK (planned_quantity > 0),
    available_quantity_at_planning NUMERIC(18,6) NULL
);

-- ---------------------------------------------------------------------
-- تاییدِ تحویل (Proof of Delivery) -- امضا/عکس/GPS رویِ فاکتور
-- ---------------------------------------------------------------------
CREATE TABLE comm.delivery_confirmations (
    delivery_confirmation_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    document_id BIGINT NOT NULL REFERENCES comm.commercial_documents(document_id),
    customer_visit_id BIGINT NULL REFERENCES comm.customer_visits(customer_visit_id),
    confirmed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    confirmed_by_user_id INT NOT NULL REFERENCES sec.users(user_id),
    received_by_name VARCHAR(150) NULL,
    signature_storage_key VARCHAR(300) NULL,
    photo_storage_key VARCHAR(300) NULL,
    gps_latitude NUMERIC(9,6) NULL,
    gps_longitude NUMERIC(9,6) NULL,
    notes VARCHAR(500) NULL,
    CONSTRAINT uq_delivery_confirmations_document UNIQUE (document_id)
);

CREATE TABLE comm.delivery_confirmation_lines (
    delivery_confirmation_line_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    delivery_confirmation_id BIGINT NOT NULL REFERENCES comm.delivery_confirmations(delivery_confirmation_id),
    document_line_id BIGINT NOT NULL REFERENCES comm.commercial_document_lines(line_id),
    delivered_quantity NUMERIC(18,6) NOT NULL,
    shortage_reason VARCHAR(200) NULL
);

-- ---------------------------------------------------------------------
-- موتورِ پروموشن -- BUY_X_GET_Y / THRESHOLD_DISCOUNT. طبقِ طرحِ تاییدشده،
-- در همین فاز فقط دیتامدل+محاسبهٔ مستقل ساخته می‌شود؛ اتصالِ آن به
-- محاسبهٔ زندهٔ قیمتِ فاکتور (commercial_documents.py) یک گامِ جداگانه
-- و حساس است که در فازِ بعدی به‌طورِ مستقل بررسی/تست می‌شود.
-- ---------------------------------------------------------------------
CREATE TABLE comm.promotion_rules (
    promotion_rule_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    code VARCHAR(30) NOT NULL,
    name VARCHAR(150) NOT NULL,
    promotion_type_code VARCHAR(20) NOT NULL
        CHECK (promotion_type_code IN ('BUY_X_GET_Y', 'THRESHOLD_DISCOUNT')),
    channel_type_code VARCHAR(15) NULL
        CHECK (channel_type_code IN ('POS', 'WHOLESALE', 'ONLINE', 'AGENT', 'MARKETPLACE', 'VAN_SALES', 'PRE_SALES')),
    -- فقط برایِ BUY_X_GET_Y
    applies_to_item_id INT NULL REFERENCES inv.items(item_id),
    buy_quantity NUMERIC(18,6) NULL,
    get_quantity NUMERIC(18,6) NULL,
    get_item_id INT NULL REFERENCES inv.items(item_id),
    -- فقط برایِ THRESHOLD_DISCOUNT
    threshold_amount NUMERIC(18,2) NULL,
    discount_percent NUMERIC(5,2) NULL,
    valid_from DATE NULL,
    valid_to DATE NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_promotion_rules_code UNIQUE (company_id, code)
);
