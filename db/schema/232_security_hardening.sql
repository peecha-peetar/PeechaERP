-- پیچا | R344: قفل موقت حساب پس از چند ورود ناموفق، زمان آخرین تغییر رمز، و اقدام‌های ورود در رد حسابرسی.
-- پیش‌نیاز: 002_security_rbac.sql، 210_wf_engine_core.sql

ALTER TABLE sec.users ADD COLUMN IF NOT EXISTS failed_login_count SMALLINT NOT NULL DEFAULT 0;
ALTER TABLE sec.users ADD COLUMN IF NOT EXISTS locked_until TIMESTAMPTZ NULL;
ALTER TABLE sec.users ADD COLUMN IF NOT EXISTS password_changed_at TIMESTAMPTZ NULL;

ALTER TABLE audit.activity_log DROP CONSTRAINT IF EXISTS ck_activity_log_action;
ALTER TABLE audit.activity_log ADD CONSTRAINT ck_activity_log_action
    CHECK (action IN ('CREATE', 'UPDATE', 'DELETE', 'APPROVE', 'REVERSE', 'MERGE', 'SUBMIT', 'REJECT', 'DELEGATE',
                      'ESCALATE', 'EXECUTE', 'PUBLISH', 'CANCEL', 'RETRY', 'RESOLVE', 'COMMENT', 'START', 'COMPLETE',
                      'LOGIN', 'LOGIN_FAIL', 'LOCK'));
