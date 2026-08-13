-- پیچا | مدیریتِ بازرگانی — مرحلهٔ ۱۱: نگاشتِ حساب، Feature Toggle، شماره‌گذاری.
-- هم‌ساختار با inv.account_mappings/feature_definitions/company_features —
-- CUSTOMER_RECEIVABLE/SUPPLIER_PAYABLE از inv.account_mappings مصرف
-- می‌شوند، این‌جا تکرار نمی‌شوند.
-- پیش‌نیاز: 003_accounting_core.sql

CREATE TABLE comm.account_mappings (
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    mapping_key VARCHAR(30) NOT NULL,
    account_id INT NOT NULL REFERENCES acc.chart_of_accounts(account_id),
    CONSTRAINT pk_comm_account_mappings PRIMARY KEY (company_id, mapping_key)
);

CREATE TABLE comm.feature_definitions (
    feature_code VARCHAR(50) NOT NULL PRIMARY KEY,
    name VARCHAR(150) NOT NULL,
    module_scope VARCHAR(30) NOT NULL,
    requires_feature_code VARCHAR(50) NULL REFERENCES comm.feature_definitions(feature_code),
    requires_account_mapping_keys VARCHAR(300) NULL,  -- فهرستِ کلیدها با کاما جدا؛ بررسیِ واقعی در لایهٔ سرویس
    description TEXT NULL
);

CREATE TABLE comm.company_features (
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    feature_code VARCHAR(50) NOT NULL REFERENCES comm.feature_definitions(feature_code),
    is_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT pk_comm_company_features PRIMARY KEY (company_id, feature_code)
);

CREATE TABLE comm.industry_profiles (
    profile_code VARCHAR(20) NOT NULL PRIMARY KEY,
    name VARCHAR(100) NOT NULL
);

CREATE TABLE comm.industry_profile_feature_defaults (
    profile_code VARCHAR(20) NOT NULL REFERENCES comm.industry_profiles(profile_code),
    feature_code VARCHAR(50) NOT NULL REFERENCES comm.feature_definitions(feature_code),
    default_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT pk_comm_industry_profile_feature_defaults PRIMARY KEY (profile_code, feature_code)
);

CREATE TABLE comm.document_numbering_sequences (
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    document_type_code VARCHAR(20) NOT NULL
        CHECK (document_type_code IN (
            'SALES_ORDER', 'SALES_INVOICE', 'SALES_RETURN',
            'PURCHASE_ORDER', 'PURCHASE_INVOICE', 'PURCHASE_RETURN'
        )),
    prefix VARCHAR(10) NOT NULL DEFAULT '',
    next_number BIGINT NOT NULL DEFAULT 1 CHECK (next_number > 0),
    reset_policy_code VARCHAR(10) NOT NULL DEFAULT 'YEARLY' CHECK (reset_policy_code IN ('YEARLY', 'NEVER')),
    CONSTRAINT pk_comm_document_numbering_sequences PRIMARY KEY (company_id, document_type_code)
);

INSERT INTO comm.feature_definitions (feature_code, name, module_scope, requires_feature_code, requires_account_mapping_keys) VALUES
    ('POS_MODULE', 'فروشگاه و صندوق', 'POS', NULL, NULL),
    ('LOYALTY_PROGRAM', 'باشگاهِ مشتریان و کیف‌پول', 'POS', 'POS_MODULE', 'LOYALTY_LIABILITY'),
    ('GIFT_CARD', 'کارتِ‌هدیه', 'POS', 'POS_MODULE', 'GIFT_CARD_LIABILITY'),
    ('INSTALLMENT_SALES', 'فروشِ اقساطی', 'POS', 'POS_MODULE', NULL),
    ('BUNDLE_SALES', 'فروشِ ترکیبی', 'SALES', NULL, NULL),
    ('DYNAMIC_CREDIT_HOLD', 'قفلِ اعتبارِ پویا', 'SALES', NULL, NULL),
    ('LANDED_COST', 'بهایِ تمام‌شدهٔ وارداتی', 'PURCHASE', NULL, 'LANDED_COST_CLEARING'),
    ('VENDOR_REBATES', 'ریبیتِ تامین‌کننده', 'PURCHASE', NULL, 'VENDOR_REBATE_RECEIVABLE'),
    ('RECURRING_BILLING', 'صورت‌حسابِ اشتراکی', 'PRICING', NULL, NULL),
    ('ONLINE_SALES', 'فروشِ اینترنتی', 'ECOMMERCE', NULL, NULL),
    ('MARKETPLACE_CONNECTORS', 'اتصال به بازارهایِ آنلاین', 'ECOMMERCE', 'ONLINE_SALES', NULL);

INSERT INTO comm.industry_profiles (profile_code, name) VALUES
    ('TRADING', 'بازرگانی'),
    ('MANUFACTURING', 'تولیدی'),
    ('RETAIL_CHAIN', 'فروشگاهِ زنجیره‌ای/آنلاین'),
    ('SERVICE', 'شرکتِ خدماتی');

-- ماتریسِ پیش‌فرض (مرحلهٔ ۱۱، بخشِ ۳) — نقطهٔ شروع، نه قفلِ نهایی؛
-- هر Toggle پسِ اعمال آزادانه قابلِ‌ویرایش می‌ماند.
INSERT INTO comm.industry_profile_feature_defaults (profile_code, feature_code, default_enabled) VALUES
    ('TRADING', 'DYNAMIC_CREDIT_HOLD', TRUE),
    ('TRADING', 'BUNDLE_SALES', FALSE),
    ('TRADING', 'POS_MODULE', FALSE),
    ('MANUFACTURING', 'LANDED_COST', TRUE),
    ('MANUFACTURING', 'VENDOR_REBATES', TRUE),
    ('MANUFACTURING', 'DYNAMIC_CREDIT_HOLD', TRUE),
    ('MANUFACTURING', 'POS_MODULE', FALSE),
    ('RETAIL_CHAIN', 'POS_MODULE', TRUE),
    ('RETAIL_CHAIN', 'LOYALTY_PROGRAM', TRUE),
    ('RETAIL_CHAIN', 'GIFT_CARD', TRUE),
    ('RETAIL_CHAIN', 'INSTALLMENT_SALES', TRUE),
    ('RETAIL_CHAIN', 'ONLINE_SALES', TRUE),
    ('RETAIL_CHAIN', 'MARKETPLACE_CONNECTORS', TRUE),
    ('RETAIL_CHAIN', 'VENDOR_REBATES', FALSE),
    ('SERVICE', 'RECURRING_BILLING', TRUE),
    ('SERVICE', 'POS_MODULE', FALSE),
    ('SERVICE', 'LANDED_COST', FALSE),
    ('SERVICE', 'BUNDLE_SALES', FALSE);
