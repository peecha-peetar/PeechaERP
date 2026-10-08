-- طبقِ درخواستِ صریحِ کاربر («وصل بشه به سیستمِ سانترال یا وویپ»):
-- تنظیماتِ اتصال به سرورِ AMIِ آستریسک/ایزابل -- هم‌الگو با
-- comm.social_connections (اعتبارنامه رمزنگاری‌شده با همان کلیدِ
-- Fernetِ موجود در ecommerce_credentials.py، شمارشِ خطایِ متوالی برایِ
-- نگهبانِ اتصال). برخلافِ social_connections که چند اتصالِ هم‌زمان
-- معنا دارد (چند بات)، این‌جا هر شرکت معمولاً فقط یک سانترال دارد --
-- پس هم‌الگو با comm.pricing_policies یک ردیفِ یکتا به‌ازایِ هر شرکت.
CREATE TABLE comm.voip_connections (
    connection_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id INT NOT NULL UNIQUE REFERENCES core.companies(company_id),
    host VARCHAR(200) NOT NULL,
    -- INT، نه SMALLINT: هرچند AMI معمولاً رویِ ۵۰۳۸ گوش می‌دهد، شماره‌یِ
    -- پورتِ TCP می‌تواند تا ۶۵۵۳۵ باشد -- بیشتر از سقفِ SMALLINTِ علامت‌دار (۳۲۷۶۷).
    port INT NOT NULL DEFAULT 5038,
    -- کانتکستِ دایل‌پلنِ آستریسک که Originate از رویِ آن اجرا می‌شود
    -- (پیش‌فرضِ رایجِ ایزابل: from-internal).
    dial_context VARCHAR(50) NOT NULL DEFAULT 'from-internal',
    -- پیشوندِ کانالِ تکنولوژیِ داخلی‌هایِ سانترال -- مثلاً PJSIP یا SIP،
    -- بسته به این‌که ایزابل با کدام درایور پیکربندی شده است.
    channel_tech_prefix VARCHAR(20) NOT NULL DEFAULT 'PJSIP',
    credentials_encrypted BYTEA,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    consecutive_failure_count INT NOT NULL DEFAULT 0,
    last_error_message VARCHAR(500),
    last_checked_at TIMESTAMPTZ
);

-- طبقِ همان درخواست: هر ویزیتور/کاربرِ فروشِ تلفنی یک داخلیِ مشخص در
-- سانترال دارد که تماس ابتدا به آن Originate و سپس به شمارهٔ مشتری پل
-- می‌شود. چون داخلی‌ها می‌توانند بینِ شرکت‌هایِ مختلف (اگر هرکدام
-- سانترالِ جدا دارند) متفاوت باشند، رویِ همان جدولِ تخصیصِ
-- کاربر-به-شرکتِ موجود اضافه شد، نه یک جدولِ تازه.
ALTER TABLE sec.user_companies ADD COLUMN voip_extension VARCHAR(20);
