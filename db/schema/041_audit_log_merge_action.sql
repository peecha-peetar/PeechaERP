-- پیچا | حسابرسی: افزودنِ اکشنِ MERGE به ck_activity_log_action
-- طبقِ آیتمِ ۴ («ادغامِ اسناد در یک سندِ واحدِ جدید»): services/journal_entries.py
-- تابعِ merge_journal_entries هر سندِ اصلی را با action="MERGE" در ردِ
-- حسابرسی ثبت می‌کند — چکِ قبلی (021) این اکشن را نمی‌شناخت.
-- پیش‌نیاز: 021_audit_log_approve_reverse_actions.sql

ALTER TABLE audit.activity_log DROP CONSTRAINT ck_activity_log_action;
ALTER TABLE audit.activity_log ADD CONSTRAINT ck_activity_log_action
    CHECK (action IN ('CREATE', 'UPDATE', 'DELETE', 'APPROVE', 'REVERSE', 'MERGE'));
