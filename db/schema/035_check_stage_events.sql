-- تاریخچه‌یِ کاملِ چرخه‌یِ عمرِ چک (دریافتی/پرداختی): یک ردیف به‌ازایِ هر
-- رویدادی که رویِ یک چک اتفاق می‌افتد (ثبت، انتقال بینِ صندوق‌ها، واگذاری
-- به بانک، اعلامِ وصول، برگشت، برگشت‌خوردن، خرج‌شدن، …) — پیش از این
-- migration هیچ ردی از این‌که «کدام سندِ حسابداری در کدام مرحله برایِ این
-- چکِ خاص ساخته شد» نگه‌داری نمی‌شد.

CREATE TABLE treasury.check_stage_events (
    event_id            SERIAL PRIMARY KEY,
    company_id          INT NOT NULL REFERENCES core.companies(company_id),
    check_kind           VARCHAR(10) NOT NULL,  -- RECEIVED | ISSUED
    check_id             INT NOT NULL,          -- received_check_id یا issued_check_id، بسته به check_kind
    event_code           VARCHAR(30) NOT NULL,
    event_date            DATE NOT NULL,
    from_status_code      VARCHAR(20) NULL,
    to_status_code        VARCHAR(20) NOT NULL,
    journal_entry_id      INT NULL REFERENCES acc.journal_entries(journal_entry_id),
    created_by_user_id    INT NOT NULL REFERENCES sec.users(user_id),
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_check_stage_events_lookup
    ON treasury.check_stage_events (company_id, check_kind, check_id, event_id);
