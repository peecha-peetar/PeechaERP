-- R312: نگهداری و تعمیرات (CMMS) روی همان دارایی ثابت. تجهیز = fa.assets؛ این‌جا فقط دادهٔ نگهداری.
-- موجودی فقط با موتور انبار، سند مالی فقط با سرویس دارایی/انبار؛ هیچ جدول دیگری مستقیم نوشته نمی‌شود.

-- ساختار مکانی: کارخانه و ناحیه
ALTER TABLE fa.asset_locations DROP CONSTRAINT IF EXISTS asset_locations_location_type_check;
ALTER TABLE fa.asset_locations ADD CONSTRAINT asset_locations_location_type_check
    CHECK (location_type IN ('SITE', 'PLANT', 'BUILDING', 'AREA', 'FLOOR', 'ROOM', 'LINE', 'OTHER'));

CREATE SCHEMA IF NOT EXISTS mnt;

-- مشخصات نگهداری هر تجهیز (یک‌به‌یک با دارایی؛ نام، سریال، سازنده، مدل و محل از خود دارایی خوانده می‌شود)
CREATE TABLE mnt.equipment_profiles (
    profile_id                  BIGSERIAL     PRIMARY KEY,
    company_id                  INT           NOT NULL REFERENCES core.companies(company_id),
    asset_id                    BIGINT        NOT NULL UNIQUE REFERENCES fa.assets(asset_id),
    criticality_code            VARCHAR(10)   NOT NULL DEFAULT 'MEDIUM' CHECK (criticality_code IN ('HIGH', 'MEDIUM', 'LOW')),
    technical_specs             JSONB         NULL,
    meter_unit                  VARCHAR(30)   NULL,
    responsible_user_id         INT           NULL REFERENCES sec.users(user_id),
    default_technician_user_id  INT           NULL REFERENCES sec.users(user_id),
    service_supplier_detail_account_id INT    NULL REFERENCES acc.detail_accounts(detail_account_id),
    safety_notes                VARCHAR(1000) NULL,
    notes                       VARCHAR(1000) NULL,
    updated_by_user_id          INT           NULL REFERENCES sec.users(user_id),
    updated_at                  TIMESTAMPTZ   NOT NULL DEFAULT now()
);

-- کدهای خرابی، علت و رفع (برای تحلیل علل پرتکرار)
CREATE TABLE mnt.failure_codes (
    failure_code_id  SERIAL        PRIMARY KEY,
    company_id       INT           NOT NULL REFERENCES core.companies(company_id),
    kind_code        VARCHAR(10)   NOT NULL CHECK (kind_code IN ('PROBLEM', 'CAUSE', 'REMEDY')),
    code             VARCHAR(30)   NOT NULL,
    name             VARCHAR(150)  NOT NULL,
    is_active        BOOLEAN       NOT NULL DEFAULT TRUE,
    UNIQUE (company_id, kind_code, code)
);

-- درخواست تعمیر
CREATE TABLE mnt.work_requests (
    request_id           BIGSERIAL     PRIMARY KEY,
    company_id           INT           NOT NULL REFERENCES core.companies(company_id),
    request_no           INT           NOT NULL,
    asset_id             BIGINT        NOT NULL REFERENCES fa.assets(asset_id),
    title                VARCHAR(200)  NOT NULL,
    description          VARCHAR(2000) NULL,
    failure_at           TIMESTAMPTZ   NULL,
    reported_at          TIMESTAMPTZ   NOT NULL DEFAULT now(),
    reported_by_user_id  INT           NOT NULL REFERENCES sec.users(user_id),
    machine_stopped      BOOLEAN       NOT NULL DEFAULT FALSE,
    severity_code        VARCHAR(10)   NOT NULL DEFAULT 'MEDIUM' CHECK (severity_code IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    probable_cause       VARCHAR(500)  NULL,
    suggested_work_type  VARCHAR(15)   NULL,
    priority_code        VARCHAR(10)   NULL CHECK (priority_code IN ('LOW', 'NORMAL', 'HIGH', 'URGENT')),
    status_code          VARCHAR(15)   NOT NULL DEFAULT 'NEW'
        CHECK (status_code IN ('NEW', 'UNDER_REVIEW', 'APPROVED', 'REJECTED', 'CONVERTED', 'CANCELLED')),
    evaluated_by_user_id INT           NULL REFERENCES sec.users(user_id),
    evaluated_at         TIMESTAMPTZ   NULL,
    approved_by_user_id  INT           NULL REFERENCES sec.users(user_id),
    approved_at          TIMESTAMPTZ   NULL,
    decision_note        VARCHAR(500)  NULL,
    assigned_to_user_id  INT           NULL REFERENCES sec.users(user_id),
    source_code          VARCHAR(10)   NOT NULL DEFAULT 'DESKTOP' CHECK (source_code IN ('DESKTOP', 'MOBILE', 'QR', 'PM')),
    idempotency_key      VARCHAR(80)   NULL,
    UNIQUE (company_id, request_no)
);
CREATE UNIQUE INDEX ux_mnt_work_requests_idempotency ON mnt.work_requests (company_id, idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE INDEX ix_mnt_work_requests_status ON mnt.work_requests (company_id, status_code);

-- برنامهٔ نگهداری پیشگیرانه
CREATE TABLE mnt.pm_plans (
    plan_id               BIGSERIAL     PRIMARY KEY,
    company_id            INT           NOT NULL REFERENCES core.companies(company_id),
    code                  VARCHAR(30)   NOT NULL,
    asset_id              BIGINT        NOT NULL REFERENCES fa.assets(asset_id),
    title                 VARCHAR(200)  NOT NULL,
    work_type_code        VARCHAR(15)   NOT NULL DEFAULT 'PREVENTIVE'
        CHECK (work_type_code IN ('PREVENTIVE', 'INSPECTION', 'OVERHAUL', 'PREDICTIVE')),
    trigger_code          VARCHAR(10)   NOT NULL DEFAULT 'CALENDAR' CHECK (trigger_code IN ('CALENDAR', 'METER', 'BOTH')),
    interval_days         INT           NULL CHECK (interval_days IS NULL OR interval_days > 0),
    meter_interval        NUMERIC(18,4) NULL CHECK (meter_interval IS NULL OR meter_interval > 0),
    lead_days             INT           NOT NULL DEFAULT 0 CHECK (lead_days >= 0),
    start_date            DATE          NOT NULL,
    next_due_date         DATE          NULL,
    last_completed_date   DATE          NULL,
    meter_at_last         NUMERIC(18,4) NOT NULL DEFAULT 0,
    estimated_hours       NUMERIC(10,2) NULL,
    safety_instructions   VARCHAR(2000) NULL,
    required_skills       VARCHAR(500)  NULL,
    requires_shutdown     BOOLEAN       NOT NULL DEFAULT FALSE,
    responsible_user_id   INT           NULL REFERENCES sec.users(user_id),
    is_active             BOOLEAN       NOT NULL DEFAULT TRUE,
    created_by_user_id    INT           NULL REFERENCES sec.users(user_id),
    created_at            TIMESTAMPTZ   NOT NULL DEFAULT now(),
    UNIQUE (company_id, code),
    CHECK ((trigger_code = 'CALENDAR' AND interval_days IS NOT NULL) OR (trigger_code = 'METER' AND meter_interval IS NOT NULL)
           OR (trigger_code = 'BOTH' AND interval_days IS NOT NULL AND meter_interval IS NOT NULL))
);

CREATE TABLE mnt.pm_plan_tasks (
    plan_task_id   BIGSERIAL     PRIMARY KEY,
    plan_id        BIGINT        NOT NULL REFERENCES mnt.pm_plans(plan_id) ON DELETE CASCADE,
    seq            INT           NOT NULL,
    description    VARCHAR(500)  NOT NULL,
    result_type    VARCHAR(10)   NOT NULL DEFAULT 'CHECK' CHECK (result_type IN ('CHECK', 'NUMERIC', 'TEXT')),
    min_value      NUMERIC(18,4) NULL,
    max_value      NUMERIC(18,4) NULL,
    uom_label      VARCHAR(30)   NULL,
    is_mandatory   BOOLEAN       NOT NULL DEFAULT TRUE,
    is_safety      BOOLEAN       NOT NULL DEFAULT FALSE
);

CREATE TABLE mnt.pm_plan_parts (
    plan_part_id   BIGSERIAL     PRIMARY KEY,
    plan_id        BIGINT        NOT NULL REFERENCES mnt.pm_plans(plan_id) ON DELETE CASCADE,
    item_id        INT           NOT NULL REFERENCES inv.items(item_id),
    warehouse_id   INT           NULL REFERENCES inv.warehouses(warehouse_id),
    quantity       NUMERIC(18,6) NOT NULL CHECK (quantity > 0)
);

-- دستور کار
CREATE TABLE mnt.work_orders (
    work_order_id         BIGSERIAL     PRIMARY KEY,
    company_id            INT           NOT NULL REFERENCES core.companies(company_id),
    wo_no                 INT           NOT NULL,
    asset_id              BIGINT        NOT NULL REFERENCES fa.assets(asset_id),
    request_id            BIGINT        NULL REFERENCES mnt.work_requests(request_id),
    pm_plan_id            BIGINT        NULL REFERENCES mnt.pm_plans(plan_id),
    pm_due_date           DATE          NULL,
    work_type_code        VARCHAR(15)   NOT NULL
        CHECK (work_type_code IN ('EMERGENCY', 'CORRECTIVE', 'PREVENTIVE', 'PREDICTIVE', 'INSPECTION', 'OVERHAUL')),
    priority_code         VARCHAR(10)   NOT NULL DEFAULT 'NORMAL' CHECK (priority_code IN ('LOW', 'NORMAL', 'HIGH', 'URGENT')),
    title                 VARCHAR(200)  NOT NULL,
    description           VARCHAR(2000) NULL,
    status_code           VARCHAR(15)   NOT NULL DEFAULT 'OPEN'
        CHECK (status_code IN ('OPEN', 'PLANNED', 'ASSIGNED', 'IN_PROGRESS', 'ON_HOLD', 'COMPLETED', 'VERIFIED', 'CLOSED', 'CANCELLED')),
    hold_reason           VARCHAR(500)  NULL,
    responsible_user_id   INT           NULL REFERENCES sec.users(user_id),
    planned_start         TIMESTAMPTZ   NULL,
    planned_end           TIMESTAMPTZ   NULL,
    estimated_hours       NUMERIC(10,2) NULL,
    actual_start          TIMESTAMPTZ   NULL,
    actual_end            TIMESTAMPTZ   NULL,
    requires_shutdown     BOOLEAN       NOT NULL DEFAULT FALSE,
    safety_instructions   VARCHAR(2000) NULL,
    required_skills       VARCHAR(500)  NULL,
    problem_code_id       INT           NULL REFERENCES mnt.failure_codes(failure_code_id),
    cause_code_id         INT           NULL REFERENCES mnt.failure_codes(failure_code_id),
    remedy_code_id        INT           NULL REFERENCES mnt.failure_codes(failure_code_id),
    root_cause_note       VARCHAR(1000) NULL,
    completion_note       VARCHAR(1000) NULL,
    completed_by_user_id  INT           NULL REFERENCES sec.users(user_id),
    completed_at          TIMESTAMPTZ   NULL,
    verification_result   VARCHAR(5)    NULL CHECK (verification_result IN ('PASS', 'FAIL')),
    verification_note     VARCHAR(1000) NULL,
    verified_by_user_id   INT           NULL REFERENCES sec.users(user_id),
    verified_at           TIMESTAMPTZ   NULL,
    closed_by_user_id     INT           NULL REFERENCES sec.users(user_id),
    closed_at             TIMESTAMPTZ   NULL,
    reopened_count        INT           NOT NULL DEFAULT 0,
    capital_candidate     BOOLEAN       NOT NULL DEFAULT FALSE,
    idempotency_key       VARCHAR(80)   NULL,
    created_by_user_id    INT           NULL REFERENCES sec.users(user_id),
    created_at            TIMESTAMPTZ   NOT NULL DEFAULT now(),
    UNIQUE (company_id, wo_no),
    CHECK (planned_end IS NULL OR planned_start IS NULL OR planned_end >= planned_start),
    CHECK (actual_end IS NULL OR actual_start IS NULL OR actual_end >= actual_start)
);
-- یک دستور کار برای هر سررسید هر برنامهٔ پیشگیرانه (اجرای دوبارهٔ تولید، تکراری نمی‌سازد)
CREATE UNIQUE INDEX ux_mnt_work_orders_pm_due ON mnt.work_orders (pm_plan_id, pm_due_date) WHERE pm_plan_id IS NOT NULL;
CREATE UNIQUE INDEX ux_mnt_work_orders_request ON mnt.work_orders (request_id) WHERE request_id IS NOT NULL;
CREATE UNIQUE INDEX ux_mnt_work_orders_idempotency ON mnt.work_orders (company_id, idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE INDEX ix_mnt_work_orders_status ON mnt.work_orders (company_id, status_code);
CREATE INDEX ix_mnt_work_orders_asset ON mnt.work_orders (asset_id);

CREATE TABLE mnt.work_order_technicians (
    work_order_id   BIGINT       NOT NULL REFERENCES mnt.work_orders(work_order_id) ON DELETE CASCADE,
    user_id         INT          NOT NULL REFERENCES sec.users(user_id),
    is_lead         BOOLEAN      NOT NULL DEFAULT FALSE,
    assigned_by_user_id INT      NULL REFERENCES sec.users(user_id),
    assigned_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (work_order_id, user_id)
);

-- چک‌لیست و نتیجهٔ بازرسی
CREATE TABLE mnt.work_order_tasks (
    task_id         BIGSERIAL     PRIMARY KEY,
    work_order_id   BIGINT        NOT NULL REFERENCES mnt.work_orders(work_order_id) ON DELETE CASCADE,
    seq             INT           NOT NULL,
    description     VARCHAR(500)  NOT NULL,
    result_type     VARCHAR(10)   NOT NULL DEFAULT 'CHECK' CHECK (result_type IN ('CHECK', 'NUMERIC', 'TEXT')),
    min_value       NUMERIC(18,4) NULL,
    max_value       NUMERIC(18,4) NULL,
    uom_label       VARCHAR(30)   NULL,
    is_mandatory    BOOLEAN       NOT NULL DEFAULT TRUE,
    is_safety       BOOLEAN       NOT NULL DEFAULT FALSE,
    is_done         BOOLEAN       NOT NULL DEFAULT FALSE,
    value_numeric   NUMERIC(18,4) NULL,
    value_text      VARCHAR(500)  NULL,
    is_ok           BOOLEAN       NULL,
    done_by_user_id INT           NULL REFERENCES sec.users(user_id),
    done_at         TIMESTAMPTZ   NULL
);

-- نیروی کار (اطلاعاتی؛ حقوق در ماژول حقوق ثبت می‌شود)
CREATE TABLE mnt.work_order_labor (
    labor_id        BIGSERIAL     PRIMARY KEY,
    work_order_id   BIGINT        NOT NULL REFERENCES mnt.work_orders(work_order_id),
    user_id         INT           NOT NULL REFERENCES sec.users(user_id),
    employee_id     INT           NULL REFERENCES hr.employees(employee_id),
    work_date       DATE          NOT NULL,
    hours           NUMERIC(10,2) NOT NULL CHECK (hours > 0),
    hourly_rate     NUMERIC(18,2) NOT NULL DEFAULT 0 CHECK (hourly_rate >= 0),
    amount          NUMERIC(18,2) NOT NULL DEFAULT 0,
    note            VARCHAR(300)  NULL,
    idempotency_key VARCHAR(80)   NULL,
    created_by_user_id INT        NULL REFERENCES sec.users(user_id),
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX ux_mnt_labor_idempotency ON mnt.work_order_labor (work_order_id, idempotency_key) WHERE idempotency_key IS NOT NULL;

-- قطعات (رزرو با inv.stock_reservations، صدور و برگشت با موتور انبار)
CREATE TABLE mnt.work_order_parts (
    part_id          BIGSERIAL     PRIMARY KEY,
    work_order_id    BIGINT        NOT NULL REFERENCES mnt.work_orders(work_order_id),
    item_id          INT           NOT NULL REFERENCES inv.items(item_id),
    warehouse_id     INT           NOT NULL REFERENCES inv.warehouses(warehouse_id),
    planned_qty      NUMERIC(18,6) NOT NULL CHECK (planned_qty > 0),
    issued_qty       NUMERIC(18,6) NOT NULL DEFAULT 0 CHECK (issued_qty >= 0),
    returned_qty     NUMERIC(18,6) NOT NULL DEFAULT 0 CHECK (returned_qty >= 0),
    issued_amount    NUMERIC(18,2) NOT NULL DEFAULT 0,
    returned_amount  NUMERIC(18,2) NOT NULL DEFAULT 0,
    purchase_request_id   BIGINT   NULL,
    purchase_request_line_id BIGINT NULL,
    created_by_user_id INT         NULL REFERENCES sec.users(user_id),
    CHECK (returned_qty <= issued_qty)
);

CREATE TABLE mnt.work_order_part_moves (
    move_id            BIGSERIAL     PRIMARY KEY,
    part_id            BIGINT        NOT NULL REFERENCES mnt.work_order_parts(part_id),
    direction_code     VARCHAR(6)    NOT NULL CHECK (direction_code IN ('ISSUE', 'RETURN')),
    quantity           NUMERIC(18,6) NOT NULL CHECK (quantity > 0),
    amount             NUMERIC(18,2) NOT NULL DEFAULT 0,
    stock_document_id  BIGINT        NOT NULL REFERENCES inv.stock_documents(stock_document_id),
    idempotency_key    VARCHAR(80)   NULL,
    created_by_user_id INT           NULL REFERENCES sec.users(user_id),
    created_at         TIMESTAMPTZ   NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX ux_mnt_part_moves_idempotency ON mnt.work_order_part_moves (part_id, idempotency_key) WHERE idempotency_key IS NOT NULL;

-- خدمات پیمانکار و سایر هزینه‌ها (ثبت مالی فقط با سرویس دارایی، یا ارجاع به فاکتور خرید موجود)
CREATE TABLE mnt.work_order_costs (
    cost_id                 BIGSERIAL     PRIMARY KEY,
    work_order_id           BIGINT        NOT NULL REFERENCES mnt.work_orders(work_order_id),
    cost_type_code          VARCHAR(10)   NOT NULL CHECK (cost_type_code IN ('SERVICE', 'OTHER')),
    description             VARCHAR(300)  NOT NULL,
    supplier_detail_account_id INT        NULL REFERENCES acc.detail_accounts(detail_account_id),
    amount                  NUMERIC(18,2) NOT NULL CHECK (amount > 0),
    accounting_code         VARCHAR(12)   NOT NULL DEFAULT 'PENDING'
        CHECK (accounting_code IN ('PENDING', 'INVOICE', 'EXPENSE', 'CAPITALIZE', 'NONE')),
    commercial_document_id  BIGINT        NULL REFERENCES comm.commercial_documents(document_id),
    asset_event_id          BIGINT        NULL REFERENCES fa.asset_events(event_id),
    status_code             VARCHAR(12)   NOT NULL DEFAULT 'DRAFT'
        CHECK (status_code IN ('DRAFT', 'PENDING_APPROVAL', 'POSTED', 'LINKED', 'CANCELLED')),
    created_by_user_id      INT           NULL REFERENCES sec.users(user_id),
    created_at              TIMESTAMPTZ   NOT NULL DEFAULT now(),
    posted_by_user_id       INT           NULL REFERENCES sec.users(user_id),
    posted_at               TIMESTAMPTZ   NULL
);
CREATE UNIQUE INDEX ux_mnt_costs_event ON mnt.work_order_costs (asset_event_id) WHERE asset_event_id IS NOT NULL;

-- توقف واقعی: زمان خرابی (عدم دسترس) و زمان آماده‌به‌کاری مستقل از زمان تعمیر
CREATE TABLE mnt.downtime_events (
    downtime_id          BIGSERIAL     PRIMARY KEY,
    company_id           INT           NOT NULL REFERENCES core.companies(company_id),
    asset_id             BIGINT        NOT NULL REFERENCES fa.assets(asset_id),
    downtime_type_code   VARCHAR(10)   NOT NULL DEFAULT 'BREAKDOWN' CHECK (downtime_type_code IN ('BREAKDOWN', 'PLANNED', 'OTHER')),
    down_from            TIMESTAMPTZ   NOT NULL,
    reported_at          TIMESTAMPTZ   NULL,
    available_at         TIMESTAMPTZ   NULL,
    request_id           BIGINT        NULL REFERENCES mnt.work_requests(request_id),
    work_order_id        BIGINT        NULL REFERENCES mnt.work_orders(work_order_id),
    previous_asset_status VARCHAR(20)  NULL,
    note                 VARCHAR(500)  NULL,
    created_by_user_id   INT           NULL REFERENCES sec.users(user_id),
    released_by_user_id  INT           NULL REFERENCES sec.users(user_id),
    CHECK (available_at IS NULL OR available_at >= down_from)
);
CREATE UNIQUE INDEX ux_mnt_downtime_open ON mnt.downtime_events (asset_id) WHERE available_at IS NULL;
CREATE INDEX ix_mnt_downtime_asset ON mnt.downtime_events (asset_id, down_from);

-- پنجرهٔ توقف برنامه‌ریزی‌شده (آینده) و ظرفیت محدود مصوب
CREATE TABLE mnt.planned_downtime (
    window_id           BIGSERIAL     PRIMARY KEY,
    company_id          INT           NOT NULL REFERENCES core.companies(company_id),
    asset_id            BIGINT        NOT NULL REFERENCES fa.assets(asset_id),
    work_order_id       BIGINT        NULL REFERENCES mnt.work_orders(work_order_id),
    start_at            TIMESTAMPTZ   NOT NULL,
    end_at              TIMESTAMPTZ   NOT NULL,
    status_code         VARCHAR(10)   NOT NULL DEFAULT 'PROPOSED' CHECK (status_code IN ('PROPOSED', 'APPROVED', 'CANCELLED')),
    reason              VARCHAR(300)  NULL,
    requested_by_user_id INT          NULL REFERENCES sec.users(user_id),
    approved_by_user_id INT           NULL REFERENCES sec.users(user_id),
    approved_at         TIMESTAMPTZ   NULL,
    CHECK (end_at > start_at)
);
CREATE INDEX ix_mnt_planned_downtime_asset ON mnt.planned_downtime (asset_id, start_at);

CREATE TABLE mnt.capacity_restrictions (
    restriction_id      BIGSERIAL     PRIMARY KEY,
    company_id          INT           NOT NULL REFERENCES core.companies(company_id),
    asset_id            BIGINT        NOT NULL REFERENCES fa.assets(asset_id),
    capacity_percent    NUMERIC(5,2)  NOT NULL CHECK (capacity_percent > 0 AND capacity_percent < 100),
    start_date          DATE          NOT NULL,
    end_date            DATE          NULL,
    status_code         VARCHAR(10)   NOT NULL DEFAULT 'PROPOSED' CHECK (status_code IN ('PROPOSED', 'APPROVED', 'CANCELLED')),
    reason              VARCHAR(300)  NOT NULL,
    work_order_id       BIGINT        NULL REFERENCES mnt.work_orders(work_order_id),
    requested_by_user_id INT          NULL REFERENCES sec.users(user_id),
    approved_by_user_id INT           NULL REFERENCES sec.users(user_id),
    approved_at         TIMESTAMPTZ   NULL,
    CHECK (end_date IS NULL OR end_date >= start_date)
);

-- تعویق سررسید پیشگیرانه با تأیید
CREATE TABLE mnt.pm_postponements (
    postponement_id     BIGSERIAL     PRIMARY KEY,
    plan_id             BIGINT        NOT NULL REFERENCES mnt.pm_plans(plan_id),
    work_order_id       BIGINT        NULL REFERENCES mnt.work_orders(work_order_id),
    old_due_date        DATE          NOT NULL,
    new_due_date        DATE          NOT NULL,
    reason              VARCHAR(300)  NOT NULL,
    status_code         VARCHAR(10)   NOT NULL DEFAULT 'PENDING' CHECK (status_code IN ('PENDING', 'APPROVED', 'REJECTED')),
    requested_by_user_id INT          NULL REFERENCES sec.users(user_id),
    decided_by_user_id  INT           NULL REFERENCES sec.users(user_id),
    decided_at          TIMESTAMPTZ   NULL,
    CHECK (new_due_date > old_due_date)
);
CREATE UNIQUE INDEX ux_mnt_postponement_pending ON mnt.pm_postponements (plan_id) WHERE status_code = 'PENDING';

-- دستور کار بسته یا لغوشده بدون بازگشایی ثبت‌شده تغییر نمی‌کند
CREATE OR REPLACE FUNCTION mnt.work_order_lock() RETURNS trigger AS $$
BEGIN
    IF OLD.status_code IN ('CLOSED', 'CANCELLED')
       AND NOT (OLD.status_code = 'CLOSED' AND NEW.status_code = 'IN_PROGRESS' AND NEW.reopened_count = OLD.reopened_count + 1) THEN
        RAISE EXCEPTION 'MNT_LOCKED: دستور کار بسته یا لغوشده قابل تغییر نیست';
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;
CREATE TRIGGER tr_mnt_work_orders_lock BEFORE UPDATE ON mnt.work_orders FOR EACH ROW EXECUTE FUNCTION mnt.work_order_lock();

-- هزینهٔ ثبت‌شده یا لینک‌شده به سند مالی ویرایش نمی‌شود
CREATE OR REPLACE FUNCTION mnt.cost_lock() RETURNS trigger AS $$
BEGIN
    IF OLD.status_code IN ('POSTED', 'LINKED', 'CANCELLED') THEN
        RAISE EXCEPTION 'MNT_LOCKED: هزینهٔ ثبت‌شده قابل تغییر نیست';
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;
CREATE TRIGGER tr_mnt_costs_lock BEFORE UPDATE ON mnt.work_order_costs FOR EACH ROW EXECUTE FUNCTION mnt.cost_lock();

INSERT INTO inv.feature_definitions (feature_code, name, category, requires_feature_code, description) VALUES
    ('MNT_CAPACITY_PLANNED', 'کسر توقف برنامه‌ریزی‌شده و ظرفیت محدود از ظرفیت تولید', 'MAINTENANCE', NULL,
     'پنجرهٔ توقف برنامه‌ریزی‌شدهٔ تأییدشده و ظرفیت محدود مصوب ماشین از ظرفیت در دسترس مرکز کاری کم می‌شود. بدون این کلید هم هشدار آن‌ها در بار ظرفیت نمایش داده می‌شود.'),
    ('MNT_STATUS_LOCK', 'وضعیت ماشین فقط از نگهداری', 'MAINTENANCE', NULL,
     'وقتی برای ماشین توقف باز ثبت شده، وضعیت آن از صفحهٔ دارایی دستی به «بهره‌برداری» برنمی‌گردد؛ آماده‌به‌کاری فقط از دستور کار ثبت می‌شود.'),
    ('MNT_SEPARATE_VERIFY', 'آزمون و تأیید دستور کار توسط فردی غیر از تکنسین', 'MAINTENANCE', NULL,
     'کسی که کار را انجام‌شده ثبت کرده نمی‌تواند آزمون و تأیید ایمنی همان دستور کار را ثبت کند.'),
    ('MNT_ROLE_PERMISSIONS', 'اعمال دسترسی‌های جداگانهٔ نگهداری', 'MAINTENANCE', NULL,
     'هر گام (ثبت درخواست، بررسی، اجرا، آزمون، قطعه، هزینه، تأیید) فقط برای نقشی که دسترسی همان گام را دارد. بدون این کلید هر کاربری که صفحه را می‌بیند همهٔ گام‌ها را انجام می‌دهد.')
ON CONFLICT (feature_code) DO NOTHING;
