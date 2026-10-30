-- پیچا | R379: قفل پرداخت فاکتور خرید با تطبیق سه‌طرفه (سفارش ↔ رسید ↔ فاکتور) — اختیاری، پیش‌فرض خاموش.
-- حد مجاز اختلاف فی و مقدار برای هر شرکت و آزادسازی دستی هر فاکتور با دلیل.
CREATE TABLE IF NOT EXISTS comm.three_way_settings (
    company_id               INT           PRIMARY KEY REFERENCES core.companies(company_id),
    price_tolerance_percent  NUMERIC(5,2)  NOT NULL DEFAULT 0 CHECK (price_tolerance_percent >= 0 AND price_tolerance_percent < 100),
    qty_tolerance_percent    NUMERIC(5,2)  NOT NULL DEFAULT 0 CHECK (qty_tolerance_percent >= 0 AND qty_tolerance_percent < 100),
    updated_by_user_id       INT           REFERENCES sec.users(user_id),
    updated_at               TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS comm.three_way_releases (
    release_id           INT           GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id           INT           NOT NULL REFERENCES core.companies(company_id),
    invoice_document_id  BIGINT        NOT NULL UNIQUE REFERENCES comm.commercial_documents(document_id) ON DELETE CASCADE,
    reason               VARCHAR(500)  NOT NULL,
    released_by_user_id  INT           NOT NULL REFERENCES sec.users(user_id),
    released_at          TIMESTAMPTZ   NOT NULL DEFAULT now()
);

INSERT INTO inv.feature_definitions (feature_code, name, category, requires_feature_code, description) VALUES
    ('PURCHASE_THREE_WAY_LOCK', 'قفل پرداخت فاکتور خرید با تطبیق سه‌طرفه', 'PURCHASE', NULL,
     'فاکتور خریدی که از سفارش ساخته شده و مقدارش بیش از رسید انبار یا سفارش است، یا فی‌اش بیش از حد مجاز با سفارش فرق دارد، '
     || 'تا رفع مغایرت یا آزادسازی مدیر با ذکر دلیل پرداخت و تسویه نمی‌شود. حد مجاز در فرم «قفل پرداخت تطبیق سه‌طرفه» تعیین می‌شود.')
ON CONFLICT (feature_code) DO NOTHING;
