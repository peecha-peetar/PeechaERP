-- پیچا | R358: فاصلهٔ جاده‌ای مسیر پخش از سرویس نقشهٔ نشان؛ کلید API رمزشده نگه‌داری می‌شود
CREATE TABLE IF NOT EXISTS comm.road_routing_settings (
    company_id          INT           PRIMARY KEY REFERENCES core.companies(company_id),
    provider_code       VARCHAR(10)   NOT NULL DEFAULT 'NONE',
    api_url             VARCHAR(300),
    api_key_encrypted   BYTEA,
    vehicle_type        VARCHAR(12)   NOT NULL DEFAULT 'car',
    last_error          VARCHAR(1000),
    last_error_at       TIMESTAMPTZ,
    updated_by_user_id  INT           REFERENCES sec.users(user_id),
    updated_at          TIMESTAMPTZ   NOT NULL DEFAULT now()
);
