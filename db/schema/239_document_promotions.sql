-- پیچا | R351: اثر پروموشن روی سند فروش (ردیف هدیه یا تخفیف افزوده به یک ردیف)، تا اعمال دوباره تکراری نشود
-- پیش‌نیاز: comm.commercial_documents، comm.promotion_rules

CREATE TABLE IF NOT EXISTS comm.document_promotions (
    document_promotion_id  BIGSERIAL PRIMARY KEY,
    document_id            BIGINT        NOT NULL REFERENCES comm.commercial_documents(document_id) ON DELETE CASCADE,
    promotion_rule_id      INT           NOT NULL REFERENCES comm.promotion_rules(promotion_rule_id),
    line_id                BIGINT        NOT NULL REFERENCES comm.commercial_document_lines(line_id) ON DELETE CASCADE,
    kind                   VARCHAR(10)   NOT NULL,  -- GIFT | DISCOUNT
    discount_added         NUMERIC(18, 2) NOT NULL DEFAULT 0,
    CONSTRAINT ck_document_promotion_kind CHECK (kind IN ('GIFT', 'DISCOUNT'))
);
CREATE INDEX IF NOT EXISTS ix_document_promotions_document ON comm.document_promotions(document_id);
