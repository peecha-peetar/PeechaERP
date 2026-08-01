-- پیچا | حسابرسی: افزودنِ اکشن‌هایِ APPROVE/REVERSE به ck_activity_log_action
-- طبقِ حسابرسیِ صریح: services/journal_entries.py گردشِ کارِ «تاییدِ
-- کارتابل» (ارتقایِ TEMPORARY به PERMANENT) و «برگشت‌زدنِ سندِ دائم» را
-- پیاده می‌کند، ولی چکِ قبلی (006) فقط CREATE/UPDATE/DELETE را مجاز
-- می‌دانست — این دو اکشنِ تازه هم باید در ردِ حسابرسی ثبت شوند.
-- پیش‌نیاز: 006_audit_log.sql

ALTER TABLE audit.activity_log DROP CONSTRAINT ck_activity_log_action;
ALTER TABLE audit.activity_log ADD CONSTRAINT ck_activity_log_action
    CHECK (action IN ('CREATE', 'UPDATE', 'DELETE', 'APPROVE', 'REVERSE'));
