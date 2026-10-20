-- R319: پیام‌رسان‌ها (ربات رسمی بله/تلگرام/ایتا/روبیکا و درگاه عمومی واتس‌اپ) در مرکز ارتباطات و «پیام پس از فرایند».
-- قاعده‌ها خودشان فرایند گردش کار (wf.definitions با دستهٔ MESSAGE) هستند؛ این‌جا فقط تنظیمات و شناسهٔ گفت‌وگو.

CREATE TABLE crm.messenger_settings (
    setting_id          SERIAL        PRIMARY KEY,
    company_id          INT           NOT NULL REFERENCES core.companies(company_id),
    channel             VARCHAR(12)   NOT NULL CHECK (channel IN ('BALE', 'TELEGRAM', 'EITAA', 'RUBIKA', 'WHATSAPP')),
    secret_encrypted    BYTEA         NULL,
    base_url            VARCHAR(300)  NULL,
    http_method         VARCHAR(6)    NOT NULL DEFAULT 'GET' CHECK (http_method IN ('GET', 'POST')),
    is_active           BOOLEAN       NOT NULL DEFAULT FALSE,
    last_error          VARCHAR(500)  NULL,
    last_checked_at     TIMESTAMPTZ   NULL,
    updated_by_user_id  INT           NULL REFERENCES sec.users(user_id),
    updated_at          TIMESTAMPTZ   NOT NULL DEFAULT now(),
    UNIQUE (company_id, channel)
);

-- شناسهٔ گفت‌وگوی هر طرف حساب در هر پیام‌رسان (کاربر باید یک بار به ربات پیام داده باشد)
CREATE TABLE crm.party_messenger_ids (
    party_detail_account_id  INT           NOT NULL REFERENCES acc.detail_accounts(detail_account_id),
    channel                  VARCHAR(12)   NOT NULL CHECK (channel IN ('BALE', 'TELEGRAM', 'EITAA', 'RUBIKA')),
    company_id               INT           NOT NULL REFERENCES core.companies(company_id),
    chat_id                  VARCHAR(100)  NOT NULL,
    created_at               TIMESTAMPTZ   NOT NULL DEFAULT now(),
    PRIMARY KEY (party_detail_account_id, channel)
);
CREATE INDEX ix_crm_party_messenger_ids_company ON crm.party_messenger_ids (company_id);

ALTER TABLE crm.message_templates DROP CONSTRAINT IF EXISTS message_templates_channel_check;
ALTER TABLE crm.message_templates ADD CONSTRAINT message_templates_channel_check
    CHECK (channel IN ('SMS', 'EMAIL', 'WHATSAPP', 'TELEGRAM', 'BALE', 'EITAA', 'RUBIKA', 'INTERNAL'));

INSERT INTO inv.feature_definitions (feature_code, name, category, requires_feature_code, description) VALUES
    ('MSG_AFTER_PROCESS', 'ارسال خودکار پیام پس از فرایندها', 'MESSAGING', NULL,
     'پس از رویدادهای اسناد (مثلاً تصویب فاکتور، ثبت سند دریافت، ارسال سفارش)، الگوی پیام انتخابی با پیامک، واتس‌اپ (درگاه عمومی) یا ربات رسمی بله، تلگرام، ایتا و روبیکا برای طرف حساب، گیرندهٔ ثابت یا کاربر فرستاده می‌شود. قاعده‌ها در «تنظیمات › ارتباط با مشتری › پیام پس از فرایند» تعریف می‌شوند.')
ON CONFLICT (feature_code) DO NOTHING;
