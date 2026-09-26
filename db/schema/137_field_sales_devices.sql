-- طبقِ نقشه‌راهِ تاییدشده (R131 -- لایهٔ API برایِ اپِ موبایلِ پخشِ
-- سرد/گرم): همان حسابِ کاربریِ ERP استفاده می‌شود (نه سیستمِ کاربریِ
-- جدا)، فقط یک توکنِ مخصوصِ هر دستگاه اضافه می‌شود تا بازکردنِ روزانهٔ
-- اپ نیازی به لاگینِ دوباره نداشته باشد و مدیر بتواند توکنِ یک دستگاهِ
-- گم‌شده را باطل کند.
CREATE TABLE sec.device_tokens (
    device_token_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id INT NOT NULL REFERENCES sec.users(user_id),
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    device_name VARCHAR(150) NULL,
    refresh_token_hash BYTEA NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at TIMESTAMPTZ NULL,
    revoked_at TIMESTAMPTZ NULL
);
