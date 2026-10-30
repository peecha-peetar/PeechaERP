-- پیچا | R377: ورود دومرحله‌ای با کد یک‌بارمصرف زمان‌دار (TOTP) — راز هر کاربر، کدهای بازیابی (فقط درهم‌سازی‌شده) و آخرین گام
-- زمانی استفاده‌شده (تا یک کد دو بار پذیرفته نشود). کلید شرکتی «الزام ورود دومرحله‌ای» در قابلیت‌های امنیت.
CREATE TABLE IF NOT EXISTS sec.user_mfa (
    user_id          INT           PRIMARY KEY REFERENCES sec.users(user_id) ON DELETE CASCADE,
    secret           VARCHAR(64)   NOT NULL,
    is_enabled       BOOLEAN       NOT NULL DEFAULT FALSE,
    enabled_at       TIMESTAMPTZ,
    recovery_hashes  JSONB         NOT NULL DEFAULT '[]'::jsonb,
    last_step        BIGINT,
    created_at       TIMESTAMPTZ   NOT NULL DEFAULT now()
);

INSERT INTO inv.feature_definitions (feature_code, name, category, requires_feature_code, description) VALUES
    ('SECURITY_MFA_REQUIRED', 'ورود دومرحله‌ای برای همهٔ کاربران الزامی', 'SECURITY', NULL,
     'هر کاربر این شرکت پس از رمز عبور، کد شش‌رقمی برنامهٔ احراز هویت گوشی (مثل Google Authenticator) را هم وارد می‌کند. '
     || 'کاربری که هنوز فعالش نکرده، در اولین ورود دسکتاپ آن را راه می‌اندازد؛ تا آن زمان از برنامهٔ موبایل وارد نمی‌شود.')
ON CONFLICT (feature_code) DO NOTHING;

-- رخدادهای ورود دومرحله‌ای در ردپای حسابرسی
ALTER TABLE audit.activity_log DROP CONSTRAINT IF EXISTS ck_activity_log_action;
ALTER TABLE audit.activity_log ADD CONSTRAINT ck_activity_log_action
    CHECK (action IN ('CREATE', 'UPDATE', 'DELETE', 'APPROVE', 'REVERSE', 'MERGE', 'SUBMIT', 'REJECT', 'DELEGATE',
                      'ESCALATE', 'EXECUTE', 'PUBLISH', 'CANCEL', 'RETRY', 'RESOLVE', 'COMMENT', 'START', 'COMPLETE',
                      'LOGIN', 'LOGIN_FAIL', 'LOCK', 'MFA_ON', 'MFA_OFF', 'MFA_RESET', 'MFA_FAIL', 'MFA_BACKUP',
                      'MFA_CODES'));
