-- پیچا | تکمیلِ فیلدهایِ اختصاصیِ گروهِ «بانک» طبقِ گزارشِ صریح: کدِ شعبه،
-- نامِ بانک (از فهرستِ treasury.banks)، نوعِ حساب (کمبویِ جاری/پس‌انداز
-- به‌جایِ متنِ آزاد)، شماره‌کارت، اتصال به کارت‌خوان.

ALTER TABLE acc.detail_group_fields DROP CONSTRAINT chk_detail_group_fields_kind;
ALTER TABLE acc.detail_group_fields
    ADD CONSTRAINT chk_detail_group_fields_kind
    CHECK (kind IN ('text', 'decimal', 'date', 'boolean', 'bank', 'account_type'));

-- کیندِ فیلدِ از-پیش‌موجودِ «نوعِ حساب» را به کمبویِ ثابتِ جاری/پس‌انداز ارتقا می‌دهد.
UPDATE acc.detail_group_fields
SET kind = 'account_type'
WHERE field_key = 'account_type' AND kind = 'text';

-- برایِ هر گروهِ بانکِ از-پیش‌موجود، فیلدهایِ تازه را اضافه می‌کند (idempotent).
-- طبقِ 012_person_group_field_config.sql، کلیدِ یکتا سه‌ستونی است
-- (dimension_type_id, person_group_id, field_key) — BANK_ACCOUNT یکی از
-- ۷ نوعِ بُعدِ سیستمیِ غیرِشخصی است، پس همیشه person_group_id=0.
INSERT INTO acc.detail_group_fields (dimension_type_id, person_group_id, field_key, label, kind, is_required, sort_order)
SELECT t.dimension_type_id, 0, v.field_key, v.label, v.kind, FALSE, v.sort_order
FROM acc.detail_dimension_types t
CROSS JOIN (VALUES
    ('bank_id', 'نامِ بانک', 'bank', 0),
    ('branch_code', 'کدِ شعبه', 'text', 4),
    ('card_number', 'شماره‌کارت', 'text', 6),
    ('is_pos_connected', 'متصل به کارت‌خوان است؟', 'boolean', 7)
) AS v(field_key, label, kind, sort_order)
WHERE t.code = 'BANK_ACCOUNT'
ON CONFLICT (dimension_type_id, person_group_id, field_key) DO NOTHING;
