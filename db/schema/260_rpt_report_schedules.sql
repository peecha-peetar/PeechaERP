-- پیچا | R375: گزارش زمان‌بندی‌شده — اجرای خودکار گزارش‌ساز (روزانه، هفتگی، ماهانه) با بازهٔ تاریخ نسبی و فرستادن فایل اکسل
-- به گیرندگان از مرکز اعلان. فایل هر اجرا در خود پایگاه داده نگه داشته می‌شود تا از هر رایانه‌ای باز شود.
CREATE TABLE IF NOT EXISTS rpt.report_schedules (
    schedule_id         INT           GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id          INT           NOT NULL REFERENCES core.companies(company_id),
    report_id           INT           NOT NULL REFERENCES rpt.custom_reports(report_id) ON DELETE CASCADE,
    frequency_code      VARCHAR(10)   NOT NULL CHECK (frequency_code IN ('DAILY', 'WEEKLY', 'MONTHLY')),
    run_hour            SMALLINT      NOT NULL DEFAULT 7 CHECK (run_hour BETWEEN 0 AND 23),
    weekday             SMALLINT      CHECK (weekday BETWEEN 0 AND 6),
    month_day           SMALLINT      CHECK (month_day BETWEEN 1 AND 28),
    period_code         VARCHAR(15)   NOT NULL DEFAULT 'NONE'
        CHECK (period_code IN ('NONE', 'YESTERDAY', 'LAST_7_DAYS', 'THIS_MONTH', 'LAST_MONTH')),
    recipient_user_ids  INT[]         NOT NULL DEFAULT '{}',
    is_active           BOOLEAN       NOT NULL DEFAULT TRUE,
    next_run_at         TIMESTAMPTZ   NOT NULL,
    last_run_at         TIMESTAMPTZ,
    created_by_user_id  INT           REFERENCES sec.users(user_id),
    created_at          TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS rpt.report_runs (
    run_id              INT           GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id          INT           NOT NULL REFERENCES core.companies(company_id),
    schedule_id         INT           REFERENCES rpt.report_schedules(schedule_id) ON DELETE CASCADE,
    report_id           INT           NOT NULL REFERENCES rpt.custom_reports(report_id) ON DELETE CASCADE,
    run_at              TIMESTAMPTZ   NOT NULL DEFAULT now(),
    status_code         VARCHAR(10)   NOT NULL CHECK (status_code IN ('OK', 'ERROR')),
    row_count           INT           NOT NULL DEFAULT 0,
    recipient_user_ids  INT[]         NOT NULL DEFAULT '{}',
    file_name           VARCHAR(200),
    content             BYTEA,
    error_message       VARCHAR(500)
);

CREATE INDEX IF NOT EXISTS ix_rpt_report_schedules_due ON rpt.report_schedules (next_run_at) WHERE is_active;
CREATE INDEX IF NOT EXISTS ix_rpt_report_runs_report ON rpt.report_runs (report_id, run_at DESC);
