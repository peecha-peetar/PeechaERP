-- پیچا | R376: دستیار پرسش از داده (فقط‌خواندنی) — ردپای هر پرسش: کاربر، متن، نوع پرسش و داده‌ای که از آن پاسخ داده شد
CREATE TABLE IF NOT EXISTS rpt.assistant_queries (
    query_id      INT           GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id    INT           NOT NULL REFERENCES core.companies(company_id),
    user_id       INT           NOT NULL REFERENCES sec.users(user_id),
    question      VARCHAR(500)  NOT NULL,
    intent_code   VARCHAR(30)   NOT NULL,
    dataset_code  VARCHAR(40),
    used_ai       BOOLEAN       NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_rpt_assistant_queries_user ON rpt.assistant_queries (company_id, user_id, created_at DESC);
