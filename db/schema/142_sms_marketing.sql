-- طبقِ درخواستِ صریحِ کاربر («یک تب اضافه کرد برایِ بازاریابی و ارسالِ
-- پیامکِ زمان‌بندی‌شده»): چون ارائه‌دهندهٔ پیامک مشخص نبود («راه آفتاب،
-- تقریباً همه مثل هم‌اند») و APIِ دقیقش پیدا نشد، به‌جایِ سخت‌کدکردنِ
-- یک ارائه‌دهنده، یک الگویِ URLِ عمومی با جایگزینیِ {phone}/{text}
-- ذخیره می‌شود -- هم‌الگو با comm.voip_connections (یک ردیفِ اتصال به
-- ازایِ هر شرکت، رمزنگاری‌شده با همان کلیدِ Fernتِ ecommerce_credentials.py).
CREATE TABLE comm.sms_gateway_settings (
    setting_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id INT NOT NULL UNIQUE REFERENCES core.companies(company_id),
    -- کلِ الگویِ URL (شاملِ هرگونه کلیدِ API/نامِ‌کاربری/رمزِ تعبیه‌شده در
    -- خودِ URL) رمزنگاری‌شده ذخیره می‌شود -- نه فقط بخشی از آن.
    request_template_encrypted BYTEA,
    http_method VARCHAR(10) NOT NULL DEFAULT 'GET' CHECK (http_method IN ('GET', 'POST')),
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE comm.sms_campaigns (
    campaign_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    name VARCHAR(150) NOT NULL,
    message_text VARCHAR(500) NOT NULL,
    scheduled_at TIMESTAMPTZ NOT NULL,
    status_code VARCHAR(15) NOT NULL DEFAULT 'PENDING' CHECK (status_code IN ('PENDING', 'SENT', 'FAILED')),
    created_by_user_id INT NOT NULL REFERENCES sec.users(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    sent_at TIMESTAMPTZ
);

-- طبقِ تصمیمِ طراحیِ MVP: گیرندگان در لحظهٔ ساختِ کمپین، از فهرستِ
-- مشتریانِ اختصاص‌یافته به کاربرِ سازنده (همان telesales.list_assigned_customers،
-- R135) عکس‌برداری می‌شوند -- بدونِ ساختِ یک فرمِ فیلترِ مشتریِ جداگانه.
CREATE TABLE comm.sms_campaign_recipients (
    recipient_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    campaign_id BIGINT NOT NULL REFERENCES comm.sms_campaigns(campaign_id) ON DELETE CASCADE,
    customer_detail_account_id INT NOT NULL REFERENCES acc.detail_accounts(detail_account_id),
    phone_number VARCHAR(30) NOT NULL,
    status_code VARCHAR(15) NOT NULL DEFAULT 'PENDING' CHECK (status_code IN ('PENDING', 'SENT', 'FAILED')),
    sent_at TIMESTAMPTZ,
    error_message VARCHAR(500)
);

CREATE INDEX ix_sms_campaign_recipients_campaign ON comm.sms_campaign_recipients (campaign_id);
