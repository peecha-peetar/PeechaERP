-- طبقِ درخواستِ صریح («پستِ خودکار در تلگرام و بله» + «تقویمِ محتوایی»):
-- تلگرام و بله (tapi.bale.ai) هردو دقیقاً همان Bot APIِ استاندارد را
-- پیاده می‌کنند -- پس یک جدولِ اتصالِ مشترک با platform_code کافی است.
CREATE TABLE comm.social_connections (
    connection_id BIGSERIAL PRIMARY KEY,
    company_id BIGINT NOT NULL REFERENCES core.companies(company_id),
    platform_code VARCHAR(10) NOT NULL CHECK (platform_code IN ('TELEGRAM', 'BALE')),
    display_name VARCHAR(100) NOT NULL,
    chat_id VARCHAR(100) NOT NULL,
    bot_token_encrypted BYTEA,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

-- هر پست به یک اتصالِ مشخص (یک کانال/گروهِ خاص) زمان‌بندی می‌شود؛
-- run_due_posts (تیکِ هر یک‌دقیقه‌ایِ شل، هم‌الگو با اتوسینکِ فروشِ
-- اینترنتی) پست‌هایِ سررسیده را خودکار ارسال می‌کند.
CREATE TABLE comm.content_calendar_posts (
    post_id BIGSERIAL PRIMARY KEY,
    company_id BIGINT NOT NULL REFERENCES core.companies(company_id),
    connection_id BIGINT NOT NULL REFERENCES comm.social_connections(connection_id),
    title VARCHAR(200),
    body_text TEXT NOT NULL,
    scheduled_at TIMESTAMPTZ NOT NULL,
    status_code VARCHAR(15) NOT NULL DEFAULT 'SCHEDULED' CHECK (status_code IN ('SCHEDULED', 'SENT', 'FAILED', 'CANCELED')),
    sent_at TIMESTAMPTZ,
    error_message VARCHAR(500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
