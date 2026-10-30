-- پیچا | R370: اثربخشی کلی تجهیزات (OEE) — گزارش تولید هر شیفت ایستگاه با زمان برنامه‌ای، توقف‌ها، نرخ ایده‌آل، تولید کل و مردود
CREATE TABLE IF NOT EXISTS prd.oee_logs (
    log_id               INT           GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id           INT           NOT NULL REFERENCES core.companies(company_id),
    work_center_id       INT           NOT NULL REFERENCES prd.work_centers(work_center_id),
    log_date             DATE          NOT NULL,
    shift_no             SMALLINT      NOT NULL DEFAULT 1 CHECK (shift_no BETWEEN 1 AND 3),
    planned_minutes      INT           NOT NULL CHECK (planned_minutes > 0),
    ideal_rate_per_hour  NUMERIC(18,4) NOT NULL CHECK (ideal_rate_per_hour > 0),
    total_qty            NUMERIC(18,3) NOT NULL DEFAULT 0 CHECK (total_qty >= 0),
    reject_qty           NUMERIC(18,3) NOT NULL DEFAULT 0 CHECK (reject_qty >= 0),
    order_id             BIGINT        REFERENCES prd.production_orders(order_id),
    notes                VARCHAR(500),
    created_by_user_id   INT           REFERENCES sec.users(user_id),
    created_at           TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CONSTRAINT uq_prd_oee_logs UNIQUE (work_center_id, log_date, shift_no),
    CONSTRAINT ck_prd_oee_logs_reject CHECK (reject_qty <= total_qty)
);

CREATE TABLE IF NOT EXISTS prd.oee_stops (
    stop_id      INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    log_id       INT          NOT NULL REFERENCES prd.oee_logs(log_id) ON DELETE CASCADE,
    reason_code  VARCHAR(20)  NOT NULL
        CHECK (reason_code IN ('BREAKDOWN', 'SETUP', 'MATERIAL', 'QUALITY', 'OPERATOR', 'SMALL_STOP', 'OTHER')),
    minutes      INT          NOT NULL CHECK (minutes > 0),
    note         VARCHAR(300)
);
