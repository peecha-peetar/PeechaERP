-- پیچا | ردِ حسابرسیِ تغییرناپذیرِ عملیاتِ کسب‌وکاری (نه تاریخچه‌ی جدول‌های
-- دسترسی که در 002_security_rbac.sql با الگوی audit.track_row_history
-- پوشش داده شده — این یک ردِ عمومیِ سطحِ اپلیکیشن است: چه کسی، چه زمانی،
-- روی کدام موجودیت، چه عملیاتی انجام داد، با چه مقادیرِ قبل/بعدی).
-- پیش‌نیاز: 001_core_i18n_and_tenancy.sql، 002_security_rbac.sql (schema audit از آنجا می‌آید)

CREATE TABLE audit.activity_log (
    log_id      BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id  INT          NULL REFERENCES core.companies(company_id),
    user_id     INT          NULL REFERENCES sec.users(user_id),
    entity_type VARCHAR(50)  NOT NULL,
    entity_id   INT          NOT NULL,
    action      VARCHAR(10)  NOT NULL,
    changes     JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_activity_log_action CHECK (action IN ('CREATE', 'UPDATE', 'DELETE'))
);
CREATE INDEX ix_activity_log_entity ON audit.activity_log(entity_type, entity_id);
CREATE INDEX ix_activity_log_company_date ON audit.activity_log(company_id, created_at DESC);

-- تغییرناپذیری: هیچ UPDATE/DELETE‌ای روی این جدول مجاز نیست — حتی برای
-- ادمین یا از طریق دسترسیِ مستقیم به دیتابیس؛ فقط INSERT ممکن است.
CREATE FUNCTION audit.prevent_activity_log_modification() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'ردِ حسابرسی تغییرناپذیر است: عملیاتِ % روی audit.activity_log مجاز نیست', TG_OP;
END;
$$;

CREATE TRIGGER tr_activity_log_immutable
    BEFORE UPDATE OR DELETE ON audit.activity_log
    FOR EACH ROW EXECUTE FUNCTION audit.prevent_activity_log_modification();
