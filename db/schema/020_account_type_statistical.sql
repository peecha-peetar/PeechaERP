-- پیچا | افزودنِ سومین نوعِ حساب: «انتظامی» (آماری/خارج از ترازنامه) —
-- طبقِ توضیحِ صریحِ کاربر: «سه نوع حساب داریم: ترازنامه‌ای، موقت،
-- انتظامی». دو نوعِ اول (PERMANENT/TEMPORARY) از ۰۰۳ موجود بودند.
-- پیش‌نیاز: 003_accounting_core.sql

INSERT INTO acc.account_types (account_type_id, code) VALUES
    (3, 'STATISTICAL')
ON CONFLICT (account_type_id) DO NOTHING;
