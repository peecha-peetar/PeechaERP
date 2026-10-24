-- پیچا R311 — سیستم مدیریت کیفیت: طرح کیفیت نسخه‌دار، نتایج پارامترها، ثبت/تأیید جدا، کیفیت تولید و مرجوعی،
-- عدم‌انطباق و اقدام اصلاحی/پیشگیرانه. همان جدول inv.qc_inspections گسترش می‌یابد (ماژول موازی نیست).
-- کلیدهای تازه پیش‌فرض خاموش‌اند. برگشت: db/rollback/221_qms_down.sql

CREATE SCHEMA IF NOT EXISTS qms;

-- ---------------------------------------------------------------------
-- طرح کیفیت (نسخه‌دار؛ نسخهٔ فعال فقط یکی برای هر کد)
-- ---------------------------------------------------------------------
CREATE TABLE qms.inspection_plans (
    plan_id                     INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id                  INT          NOT NULL REFERENCES core.companies(company_id),
    code                        VARCHAR(30)  NOT NULL,
    version_no                  INT          NOT NULL DEFAULT 1 CHECK (version_no >= 1),
    name                        VARCHAR(150) NOT NULL,
    stage_code                  VARCHAR(20)  NOT NULL CHECK (stage_code IN ('RECEIPT', 'SALES_RETURN', 'IN_PROCESS', 'FINAL')),
    item_id                     INT          NULL REFERENCES inv.items(item_id),
    category_id                 INT          NULL REFERENCES inv.item_categories(category_id),
    supplier_detail_account_id  INT          NULL REFERENCES acc.detail_accounts(detail_account_id),
    work_center_id              INT          NULL REFERENCES prd.work_centers(work_center_id),
    operation_id                INT          NULL REFERENCES prd.operations(operation_id),
    document_type_code          VARCHAR(20)  NULL,
    sampling_method             VARCHAR(10)  NOT NULL DEFAULT 'FULL' CHECK (sampling_method IN ('FULL', 'FIXED', 'PERCENT')),
    sample_size                 NUMERIC(18,6) NULL CHECK (sample_size IS NULL OR sample_size > 0),
    sample_percent              NUMERIC(7,3)  NULL CHECK (sample_percent IS NULL OR (sample_percent > 0 AND sample_percent <= 100)),
    acceptance_number           INT          NOT NULL DEFAULT 0 CHECK (acceptance_number >= 0),
    is_mandatory                BOOLEAN      NOT NULL DEFAULT TRUE,
    valid_from                  DATE         NULL,
    valid_to                    DATE         NULL,
    status_code                 VARCHAR(12)  NOT NULL DEFAULT 'DRAFT' CHECK (status_code IN ('DRAFT', 'ACTIVE', 'SUPERSEDED', 'INACTIVE')),
    previous_plan_id            INT          NULL REFERENCES qms.inspection_plans(plan_id),
    notes                       TEXT         NULL,
    created_by_user_id          INT          NOT NULL REFERENCES sec.users(user_id),
    created_at                  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    activated_by_user_id        INT          NULL REFERENCES sec.users(user_id),
    activated_at                TIMESTAMPTZ  NULL,
    CONSTRAINT uq_qms_inspection_plans_version UNIQUE (company_id, code, version_no),
    CONSTRAINT ck_qms_inspection_plans_validity CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
    CONSTRAINT ck_qms_inspection_plans_sampling CHECK (
        (sampling_method = 'FULL') OR (sampling_method = 'FIXED' AND sample_size IS NOT NULL)
        OR (sampling_method = 'PERCENT' AND sample_percent IS NOT NULL))
);
CREATE UNIQUE INDEX ux_qms_inspection_plans_active ON qms.inspection_plans (company_id, code) WHERE status_code = 'ACTIVE';
CREATE INDEX ix_qms_inspection_plans_lookup ON qms.inspection_plans (company_id, stage_code, status_code);

CREATE TABLE qms.plan_parameters (
    parameter_id    INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    plan_id         INT          NOT NULL REFERENCES qms.inspection_plans(plan_id) ON DELETE CASCADE,
    seq             INT          NOT NULL,
    name            VARCHAR(150) NOT NULL,
    data_type       VARCHAR(10)  NOT NULL CHECK (data_type IN ('NUMERIC', 'PASS_FAIL', 'OPTION', 'TEXT')),
    uom_label       VARCHAR(30)  NULL,
    min_value       NUMERIC(18,6) NULL,
    max_value       NUMERIC(18,6) NULL,
    target_value    NUMERIC(18,6) NULL,
    options         JSONB        NULL,
    test_method     VARCHAR(300) NULL,
    is_mandatory    BOOLEAN      NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_qms_plan_parameters_seq UNIQUE (plan_id, seq),
    CONSTRAINT ck_qms_plan_parameters_range CHECK (min_value IS NULL OR max_value IS NULL OR max_value >= min_value)
);

-- ---------------------------------------------------------------------
-- گسترش رکورد بازرسی موجود
-- ---------------------------------------------------------------------
ALTER TABLE inv.qc_inspections
    ADD COLUMN stage_code                  VARCHAR(20)  NOT NULL DEFAULT 'RECEIPT',
    ADD COLUMN status_code                 VARCHAR(12)  NOT NULL DEFAULT 'APPROVED',
    ADD COLUMN plan_id                     INT          NULL REFERENCES qms.inspection_plans(plan_id),
    ADD COLUMN lot_quantity                NUMERIC(18,6) NULL,
    ADD COLUMN accepted_quantity           NUMERIC(18,6) NULL,
    ADD COLUMN pending_quantity            NUMERIC(18,6) NOT NULL DEFAULT 0,
    ADD COLUMN disposition_code            VARCHAR(20)  NULL,
    ADD COLUMN production_order_id         BIGINT       NULL REFERENCES prd.production_orders(order_id),
    ADD COLUMN order_operation_id          BIGINT       NULL REFERENCES prd.order_operations(order_operation_id),
    ADD COLUMN reinspection_of_id          INT          NULL REFERENCES inv.qc_inspections(qc_inspection_id),
    ADD COLUMN approved_by_user_id         INT          NULL REFERENCES sec.users(user_id),
    ADD COLUMN approved_at                 TIMESTAMPTZ  NULL,
    ADD COLUMN decision_notes              TEXT         NULL,
    ADD COLUMN transfer_stock_document_id  BIGINT       NULL REFERENCES inv.stock_documents(stock_document_id),
    ADD COLUMN idempotency_key             VARCHAR(80)  NULL;

-- بازرسی‌های پیشین (R306): مقدار تحت کنترل = مقدار ردیف رسید، پذیرفته = بقیه
UPDATE inv.qc_inspections q
   SET lot_quantity = l.quantity_base,
       accepted_quantity = GREATEST(0, l.quantity_base - COALESCE(q.rejected_quantity, 0)),
       disposition_code = CASE WHEN COALESCE(q.rejected_quantity, 0) = 0 THEN 'ACCEPT'
                               WHEN COALESCE(q.rejected_quantity, 0) >= l.quantity_base THEN 'REJECT' ELSE 'PARTIAL' END,
       approved_by_user_id = q.inspected_by_user_id, approved_at = q.inspected_at
  FROM inv.stock_document_lines l
 WHERE l.line_id = q.stock_document_line_id AND q.lot_quantity IS NULL;

ALTER TABLE inv.qc_inspections DROP CONSTRAINT ck_inv_qc_inspections_one_target;
ALTER TABLE inv.qc_inspections
    ADD CONSTRAINT ck_inv_qc_inspections_one_target CHECK (
        (stock_document_line_id IS NOT NULL)::int + (batch_id IS NOT NULL)::int <= 1
        AND (stock_document_line_id IS NOT NULL OR batch_id IS NOT NULL OR production_order_id IS NOT NULL)),
    ADD CONSTRAINT ck_inv_qc_inspections_stage CHECK (stage_code IN ('RECEIPT', 'SALES_RETURN', 'IN_PROCESS', 'FINAL')),
    ADD CONSTRAINT ck_inv_qc_inspections_status CHECK (status_code IN ('RECORDED', 'APPROVED', 'CANCELLED')),
    ADD CONSTRAINT ck_inv_qc_inspections_disposition CHECK (disposition_code IS NULL OR disposition_code IN
        ('ACCEPT', 'REJECT', 'PARTIAL', 'PENDING', 'REWORK', 'CONCESSION')),
    ADD CONSTRAINT ck_inv_qc_inspections_quantities CHECK (
        COALESCE(accepted_quantity, 0) >= 0 AND COALESCE(rejected_quantity, 0) >= 0 AND pending_quantity >= 0
        AND (lot_quantity IS NULL
             OR COALESCE(accepted_quantity, 0) + COALESCE(rejected_quantity, 0) + pending_quantity <= lot_quantity));

-- یک بازرسی باز (ثبت‌شده و تأییدنشده) برای هر ردیف یا عملیات؛ کلید یکتایی برای اجرای دوباره
CREATE UNIQUE INDEX ux_inv_qc_inspections_open_line ON inv.qc_inspections (stock_document_line_id)
    WHERE status_code = 'RECORDED' AND stock_document_line_id IS NOT NULL;
CREATE UNIQUE INDEX ux_inv_qc_inspections_open_operation ON inv.qc_inspections (order_operation_id)
    WHERE status_code = 'RECORDED' AND order_operation_id IS NOT NULL;
CREATE UNIQUE INDEX ux_inv_qc_inspections_idempotency ON inv.qc_inspections (company_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;
CREATE INDEX ix_inv_qc_inspections_line ON inv.qc_inspections (stock_document_line_id);
CREATE INDEX ix_inv_qc_inspections_order ON inv.qc_inspections (production_order_id) WHERE production_order_id IS NOT NULL;
CREATE INDEX ix_inv_qc_inspections_status ON inv.qc_inspections (company_id, status_code, stage_code);

-- بازرسی تأییدشده یا لغوشده تغییرناپذیر است (اصلاح فقط با بازرسی مجدد)
CREATE FUNCTION inv.qc_inspections_lock() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status_code IN ('APPROVED', 'CANCELLED') THEN
        RAISE EXCEPTION 'QC_LOCKED: بازرسی شمارهٔ % تأیید یا لغو شده و قابل تغییر نیست', OLD.qc_inspection_id;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER tr_inv_qc_inspections_lock BEFORE UPDATE ON inv.qc_inspections
    FOR EACH ROW EXECUTE FUNCTION inv.qc_inspections_lock();

-- ---------------------------------------------------------------------
-- نتایج پارامترها (مشخصات پارامتر هنگام ثبت ثابت می‌شود)
-- ---------------------------------------------------------------------
CREATE TABLE qms.inspection_results (
    result_id            BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id           INT          NOT NULL REFERENCES core.companies(company_id),
    qc_inspection_id     INT          NOT NULL REFERENCES inv.qc_inspections(qc_inspection_id) ON DELETE CASCADE,
    parameter_id         INT          NULL REFERENCES qms.plan_parameters(parameter_id),
    sample_no            INT          NOT NULL DEFAULT 1 CHECK (sample_no >= 1),
    parameter_name       VARCHAR(150) NOT NULL,
    data_type            VARCHAR(10)  NOT NULL CHECK (data_type IN ('NUMERIC', 'PASS_FAIL', 'OPTION', 'TEXT')),
    uom_label            VARCHAR(30)  NULL,
    min_value            NUMERIC(18,6) NULL,
    max_value            NUMERIC(18,6) NULL,
    target_value         NUMERIC(18,6) NULL,
    options              JSONB        NULL,
    is_mandatory         BOOLEAN      NOT NULL DEFAULT TRUE,
    value_numeric        NUMERIC(18,6) NULL,
    value_text           VARCHAR(500) NULL,
    value_bool           BOOLEAN      NULL,
    is_conforming        BOOLEAN      NULL,
    recorded_by_user_id  INT          NOT NULL REFERENCES sec.users(user_id),
    recorded_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_qms_inspection_results_sample UNIQUE (qc_inspection_id, parameter_id, sample_no)
);
CREATE INDEX ix_qms_inspection_results_inspection ON qms.inspection_results (qc_inspection_id);

CREATE FUNCTION qms.inspection_results_lock() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'QC_LOCKED: نتیجهٔ ثبت‌شدهٔ بازرسی قابل تغییر نیست؛ بازرسی مجدد ثبت کنید';
END;
$$;
CREATE TRIGGER tr_qms_inspection_results_lock BEFORE UPDATE ON qms.inspection_results
    FOR EACH ROW EXECUTE FUNCTION qms.inspection_results_lock();

-- ---------------------------------------------------------------------
-- عدم‌انطباق و اقدام اصلاحی/پیشگیرانه
-- ---------------------------------------------------------------------
CREATE TABLE qms.nonconformances (
    ncr_id                      INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id                  INT          NOT NULL REFERENCES core.companies(company_id),
    ncr_no                      INT          NOT NULL,
    source_code                 VARCHAR(20)  NOT NULL CHECK (source_code IN
                                    ('RECEIPT', 'SALES_RETURN', 'IN_PROCESS', 'FINAL', 'INTERNAL', 'SUPPLIER', 'CUSTOMER')),
    qc_inspection_id            INT          NULL REFERENCES inv.qc_inspections(qc_inspection_id),
    item_id                     INT          NULL REFERENCES inv.items(item_id),
    supplier_detail_account_id  INT          NULL REFERENCES acc.detail_accounts(detail_account_id),
    customer_detail_account_id  INT          NULL REFERENCES acc.detail_accounts(detail_account_id),
    production_order_id         BIGINT       NULL REFERENCES prd.production_orders(order_id),
    stock_document_id           BIGINT       NULL REFERENCES inv.stock_documents(stock_document_id),
    quantity                    NUMERIC(18,6) NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    severity_code               VARCHAR(10)  NOT NULL DEFAULT 'MINOR' CHECK (severity_code IN ('MINOR', 'MAJOR', 'CRITICAL')),
    title                       VARCHAR(200) NOT NULL,
    description                 TEXT         NULL,
    cause_code                  VARCHAR(20)  NULL,
    root_cause_method           VARCHAR(12)  NULL CHECK (root_cause_method IS NULL OR root_cause_method IN ('FIVE_WHY', 'FISHBONE', 'OTHER')),
    root_cause_details          JSONB        NULL,
    root_cause                  TEXT         NULL,
    responsible_user_id         INT          NULL REFERENCES sec.users(user_id),
    cost_amount                 NUMERIC(18,2) NOT NULL DEFAULT 0 CHECK (cost_amount >= 0),
    disposition_code            VARCHAR(20)  NULL CHECK (disposition_code IS NULL OR disposition_code IN
                                    ('USE_AS_IS', 'REWORK', 'SCRAP', 'RETURN_TO_SUPPLIER', 'REPLACE', 'NONE')),
    status_code                 VARCHAR(15)  NOT NULL DEFAULT 'OPEN' CHECK (status_code IN
                                    ('OPEN', 'INVESTIGATING', 'ACTION', 'CLOSED', 'CANCELLED')),
    detected_at                 TIMESTAMPTZ  NOT NULL DEFAULT now(),
    due_date                    DATE         NULL,
    closed_at                   TIMESTAMPTZ  NULL,
    closed_by_user_id           INT          NULL REFERENCES sec.users(user_id),
    created_by_user_id          INT          NOT NULL REFERENCES sec.users(user_id),
    created_at                  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_qms_nonconformances_no UNIQUE (company_id, ncr_no)
);
CREATE INDEX ix_qms_nonconformances_status ON qms.nonconformances (company_id, status_code);
CREATE INDEX ix_qms_nonconformances_inspection ON qms.nonconformances (qc_inspection_id) WHERE qc_inspection_id IS NOT NULL;

CREATE TABLE qms.capa_actions (
    action_id              INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id             INT          NOT NULL REFERENCES core.companies(company_id),
    ncr_id                 INT          NOT NULL REFERENCES qms.nonconformances(ncr_id),
    action_type            VARCHAR(12)  NOT NULL CHECK (action_type IN ('CORRECTIVE', 'PREVENTIVE')),
    description            TEXT         NOT NULL,
    owner_user_id          INT          NULL REFERENCES sec.users(user_id),
    due_date               DATE         NULL,
    status_code            VARCHAR(12)  NOT NULL DEFAULT 'OPEN' CHECK (status_code IN
                               ('OPEN', 'DONE', 'VERIFIED', 'INEFFECTIVE', 'CANCELLED')),
    evidence               TEXT         NULL,
    completed_at           TIMESTAMPTZ  NULL,
    completed_by_user_id   INT          NULL REFERENCES sec.users(user_id),
    verified_at            TIMESTAMPTZ  NULL,
    verified_by_user_id    INT          NULL REFERENCES sec.users(user_id),
    effectiveness_note     TEXT         NULL,
    created_by_user_id     INT          NOT NULL REFERENCES sec.users(user_id),
    created_at             TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX ix_qms_capa_actions_ncr ON qms.capa_actions (ncr_id);
CREATE INDEX ix_qms_capa_actions_open ON qms.capa_actions (company_id, status_code, due_date);

-- پرونده و اقدام بسته‌شده دیگر تغییر نمی‌کند
CREATE FUNCTION qms.closed_record_lock() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status_code IN ('CLOSED', 'CANCELLED', 'VERIFIED', 'INEFFECTIVE') THEN
        RAISE EXCEPTION 'QC_LOCKED: رکورد بسته‌شدهٔ کیفیت قابل تغییر نیست';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER tr_qms_nonconformances_lock BEFORE UPDATE ON qms.nonconformances
    FOR EACH ROW EXECUTE FUNCTION qms.closed_record_lock();
CREATE TRIGGER tr_qms_capa_actions_lock BEFORE UPDATE ON qms.capa_actions
    FOR EACH ROW EXECUTE FUNCTION qms.closed_record_lock();

-- ---------------------------------------------------------------------
-- تنظیمات کیفیت (امتیاز تامین‌کننده و عدم‌انطباق خودکار)
-- ---------------------------------------------------------------------
CREATE TABLE qms.settings (
    company_id            INT          PRIMARY KEY REFERENCES core.companies(company_id),
    score_window_days     INT          NOT NULL DEFAULT 365 CHECK (score_window_days > 0),
    score_min_samples     INT          NOT NULL DEFAULT 3 CHECK (score_min_samples >= 1),
    weight_reject         NUMERIC(6,2) NOT NULL DEFAULT 40 CHECK (weight_reject >= 0),
    weight_return         NUMERIC(6,2) NOT NULL DEFAULT 25 CHECK (weight_return >= 0),
    weight_ncr            NUMERIC(6,2) NOT NULL DEFAULT 20 CHECK (weight_ncr >= 0),
    weight_delay          NUMERIC(6,2) NOT NULL DEFAULT 15 CHECK (weight_delay >= 0),
    weight_trend          NUMERIC(6,2) NOT NULL DEFAULT 0 CHECK (weight_trend >= 0),
    target_handling_days  NUMERIC(6,2) NOT NULL DEFAULT 2 CHECK (target_handling_days > 0),
    auto_ncr_on_reject    BOOLEAN      NOT NULL DEFAULT TRUE,
    updated_by_user_id    INT          NULL REFERENCES sec.users(user_id),
    updated_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_qms_settings_weights CHECK (weight_reject + weight_return + weight_ncr + weight_delay + weight_trend > 0)
);

-- ---------------------------------------------------------------------
-- کلیدهای روشن/خاموش (پیش‌فرض خاموش)
-- ---------------------------------------------------------------------
INSERT INTO inv.feature_definitions (feature_code, name, category, requires_feature_code, description) VALUES
    ('QC_SEPARATE_APPROVAL', 'جداسازی ثبت نتیجه و تأیید نهایی کیفیت', 'QUALITY', NULL,
     'بازرس فقط نتیجه را ثبت می‌کند و تعیین تکلیف موجودی (آزادسازی، انتقال به قرنطینه یا ضایعات) بعد از تأیید نهایی کس دیگری انجام می‌شود. ثبت‌کننده نمی‌تواند نتیجهٔ خودش را تأیید کند.'),
    ('QC_QUARANTINE_LOCK', 'قفل انبار قرنطینه', 'QUALITY', 'WMS_QC_HOLD',
     'کالای انبار قرنطینه با حواله، فروش یا انتقال عادی خارج نمی‌شود؛ فقط از صفحهٔ کنترل کیفیت (آزادسازی با مجوز، انتقال به ضایعات یا برگشت به تامین‌کننده).'),
    ('QC_PRODUCTION', 'کنترل کیفیت تولید', 'QUALITY', 'WMS_QC_HOLD',
     'رسید محصول تولیدی که کالایش نیازمند کنترل کیفیت است یا طرح بازرسی نهایی دارد، تا بازرسی نهایی نگه داشته می‌شود. عملیاتی که کنترل کیفیت اجباری دارد بدون بازرسی تأییدشده تمام نمی‌شود و دستور تولید با بازرسی باز بسته نمی‌شود.'),
    ('QC_SALES_RETURN', 'بازرسی کالای مرجوعی فروش', 'QUALITY', 'WMS_QC_HOLD',
     'کالای برگشتی مشتری وارد انبار می‌شود ولی تا بازرسی و تصمیم کیفیت قابل فروش نیست؛ مقدار مردود به قرنطینه یا ضایعات می‌رود و پروندهٔ عدم‌انطباق مشتری ساخته می‌شود.'),
    ('QC_ROLE_PERMISSIONS', 'اعمال دسترسی‌های جداگانهٔ کیفیت', 'QUALITY', NULL,
     'ثبت نتیجه، تأیید نهایی، آزادسازی موجودی، مدیریت طرح‌ها و رسیدگی به عدم‌انطباق فقط برای نقش‌هایی که در «نقش‌ها و دسترسی‌ها» مجوز همان بخش را دارند ممکن است.')
ON CONFLICT (feature_code) DO NOTHING;
