-- پیچا | R352: پشتیبان خودکار زمان‌بندی‌شده و نتیجهٔ آخرین آزمون بازیابی (یک ردیف برای کل دیتابیس)
CREATE TABLE IF NOT EXISTS core.backup_schedule (
    schedule_id       SMALLINT     PRIMARY KEY DEFAULT 1,
    is_enabled        BOOLEAN      NOT NULL DEFAULT FALSE,
    folder            VARCHAR(500) NULL,
    interval_hours    SMALLINT     NOT NULL DEFAULT 24,
    keep_count        SMALLINT     NOT NULL DEFAULT 7,
    last_backup_at    TIMESTAMPTZ  NULL,
    last_backup_path  VARCHAR(600) NULL,
    last_status       VARCHAR(10)  NULL,  -- DONE | FAILED
    last_error        VARCHAR(1000) NULL,
    last_check_at     TIMESTAMPTZ  NULL,
    last_check_ok     BOOLEAN      NULL,
    last_check_note   VARCHAR(2000) NULL,
    CONSTRAINT ck_backup_schedule_single CHECK (schedule_id = 1)
);
