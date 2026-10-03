-- طبقِ ادامه‌یِ اولویتِ بخشِ محتوا/بازاریابی («سینکِ CMS» -- شروعِ
-- «استودیویِ محتوا»): اتصال به وردپرس از طریقِ WP REST APIِ استاندارد
-- (Application Password + Basic Auth) -- هم‌الگو با اتصالِ فروشگاهی.
CREATE TABLE comm.cms_connections (
    connection_id BIGSERIAL PRIMARY KEY,
    company_id BIGINT NOT NULL REFERENCES core.companies(company_id),
    platform_code VARCHAR(10) NOT NULL CHECK (platform_code IN ('WORDPRESS')),
    display_name VARCHAR(100) NOT NULL,
    site_url VARCHAR(300) NOT NULL,
    username VARCHAR(100) NOT NULL,
    app_password_encrypted BYTEA,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

-- هر مقاله به یک اتصالِ مشخص سینک می‌شود؛ external_post_id/external_url
-- پس از اولین انتشار پر می‌شود تا سینک‌هایِ بعدی همان پست را به‌روزرسانی
-- کنند (نه اینکه هر بار پستِ تازه بسازند).
CREATE TABLE comm.cms_articles (
    article_id BIGSERIAL PRIMARY KEY,
    company_id BIGINT NOT NULL REFERENCES core.companies(company_id),
    connection_id BIGINT NOT NULL REFERENCES comm.cms_connections(connection_id),
    title VARCHAR(300) NOT NULL,
    body_html TEXT NOT NULL,
    status_code VARCHAR(15) NOT NULL DEFAULT 'DRAFT' CHECK (status_code IN ('DRAFT', 'PUBLISHED', 'FAILED')),
    external_post_id VARCHAR(50),
    external_url VARCHAR(500),
    published_at TIMESTAMPTZ,
    error_message VARCHAR(500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
