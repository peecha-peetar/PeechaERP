-- پیچا | R378: شمارندهٔ محدودیت نرخ درخواست در پایگاه داده — مشترک بین چند پروسه یا چند سرور API (قبلاً در حافظهٔ هر پروسه)
CREATE TABLE IF NOT EXISTS sec.rate_limit_hits (
    hit_id      BIGINT        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    bucket_key  VARCHAR(250)  NOT NULL,
    hit_at      TIMESTAMPTZ   NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX IF NOT EXISTS ix_sec_rate_limit_hits_key ON sec.rate_limit_hits (bucket_key, hit_at);
