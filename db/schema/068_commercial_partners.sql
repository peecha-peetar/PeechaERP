-- پیچا | مدیریتِ بازرگانی — مراحلِ ۲/۳: لایهٔ تجاری رویِ تفصیلیِ حسابداری.
-- customer_profiles/supplier_profiles اقماریِ یک‌به‌یکِ تفصیلیِ گروهِ
-- CUSTOMER/SUPPLIER هستند — دقیقاً هم‌الگو با inv.items نسبت به گروهِ
-- INVENTORY_ITEM. هرگز طرفِ‌حساب را بازتعریف نمی‌کنند.
-- پیش‌نیاز: 003_accounting_core.sql، 009_person_groups.sql،
-- 065_commercial_pricing_channels.sql

CREATE TABLE comm.commission_rules (
    rule_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    code VARCHAR(30) NOT NULL,
    name VARCHAR(150) NOT NULL,
    basis_code VARCHAR(20) NOT NULL
        CHECK (basis_code IN ('PERCENT_OF_TOTAL', 'PERCENT_OF_MARGIN', 'FLAT_PER_UNIT', 'TIERED')),
    rate_value NUMERIC(18,6) NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_comm_commission_rules UNIQUE (company_id, code)
);

CREATE TABLE comm.customer_groups (
    group_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    code VARCHAR(30) NOT NULL,
    name VARCHAR(150) NOT NULL,
    default_discount_rule_id INT NULL REFERENCES comm.discount_rules(rule_id),
    CONSTRAINT uq_comm_customer_groups UNIQUE (company_id, code)
);

CREATE TABLE comm.supplier_groups (
    group_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    code VARCHAR(30) NOT NULL,
    name VARCHAR(150) NOT NULL,
    default_discount_rule_id INT NULL REFERENCES comm.discount_rules(rule_id),
    CONSTRAINT uq_comm_supplier_groups UNIQUE (company_id, code)
);

CREATE TABLE comm.sales_representatives (
    rep_detail_account_id INT PRIMARY KEY REFERENCES acc.detail_accounts(detail_account_id),
    default_commission_rule_id INT NULL REFERENCES comm.commission_rules(rule_id),
    territory_name VARCHAR(100) NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE comm.customer_profiles (
    customer_detail_account_id INT PRIMARY KEY REFERENCES acc.detail_accounts(detail_account_id),
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    customer_group_id INT NULL REFERENCES comm.customer_groups(group_id),
    default_price_list_id INT NULL REFERENCES comm.price_lists(price_list_id),
    payment_term_days SMALLINT NOT NULL DEFAULT 0,
    credit_limit_amount NUMERIC(18,2) NOT NULL DEFAULT 0 CHECK (credit_limit_amount >= 0),
    default_channel_code VARCHAR(20) NULL,
    default_sales_rep_detail_account_id INT NULL REFERENCES comm.sales_representatives(rep_detail_account_id),
    -- جایگزینِ is_active دوحالته (مرحلهٔ ۳، بخشِ ۴).
    status_code VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'
        CHECK (status_code IN ('DRAFT', 'PENDING_APPROVAL', 'ACTIVE', 'SUSPENDED', 'BLACKLISTED', 'INACTIVE')),
    onboarding_source_code VARCHAR(15) NULL
        CHECK (onboarding_source_code IN ('WALK_IN', 'ONLINE', 'REFERRAL', 'IMPORTED', 'AGENT')),
    is_tax_exempt BOOLEAN NOT NULL DEFAULT FALSE,
    submitted_by_user_id INT NULL REFERENCES sec.users(user_id),
    submitted_at TIMESTAMPTZ NULL,
    approved_by_user_id INT NULL REFERENCES sec.users(user_id),
    approved_at TIMESTAMPTZ NULL,
    hold_reason VARCHAR(500) NULL,
    held_at TIMESTAMPTZ NULL,
    held_by_user_id INT NULL REFERENCES sec.users(user_id)
);

CREATE TABLE comm.supplier_profiles (
    supplier_detail_account_id INT PRIMARY KEY REFERENCES acc.detail_accounts(detail_account_id),
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    supplier_group_id INT NULL REFERENCES comm.supplier_groups(group_id),
    default_price_list_id INT NULL REFERENCES comm.price_lists(price_list_id),
    payment_term_days SMALLINT NOT NULL DEFAULT 0,
    credit_limit_amount NUMERIC(18,2) NOT NULL DEFAULT 0 CHECK (credit_limit_amount >= 0),
    default_lead_time_days SMALLINT NULL,
    incoterm_code VARCHAR(10) NULL,
    preferred_currency_id INT NULL REFERENCES core.currencies(currency_id),
    -- فقط از رخدادهایِ QC انبار محاسبه می‌شود — هرگز دستی (مرحلهٔ ۳، بخشِ ۷).
    quality_rating NUMERIC(3,1) NULL,
    status_code VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'
        CHECK (status_code IN ('DRAFT', 'PENDING_APPROVAL', 'ACTIVE', 'ON_HOLD', 'DISQUALIFIED', 'INACTIVE')),
    submitted_by_user_id INT NULL REFERENCES sec.users(user_id),
    submitted_at TIMESTAMPTZ NULL,
    approved_by_user_id INT NULL REFERENCES sec.users(user_id),
    approved_at TIMESTAMPTZ NULL,
    hold_reason VARCHAR(500) NULL,
    held_at TIMESTAMPTZ NULL,
    held_by_user_id INT NULL REFERENCES sec.users(user_id)
);

ALTER TABLE comm.customer_profiles
    ADD CONSTRAINT fk_comm_customer_profiles_channel
    FOREIGN KEY (company_id, default_channel_code) REFERENCES comm.channels(company_id, channel_code);

CREATE TABLE comm.party_addresses (
    address_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    party_detail_account_id INT NOT NULL REFERENCES acc.detail_accounts(detail_account_id),
    address_type_code VARCHAR(15) NOT NULL
        CHECK (address_type_code IN ('BILLING', 'SHIPPING', 'PICKUP')),
    line1 VARCHAR(300) NOT NULL,
    city VARCHAR(100) NULL,
    province VARCHAR(100) NULL,
    postal_code VARCHAR(20) NULL,
    is_default BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE UNIQUE INDEX ux_comm_party_addresses_default
    ON comm.party_addresses (party_detail_account_id, address_type_code)
    WHERE is_default;

CREATE TABLE comm.party_contacts (
    contact_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    party_detail_account_id INT NOT NULL REFERENCES acc.detail_accounts(detail_account_id),
    full_name VARCHAR(150) NOT NULL,
    role_title VARCHAR(100) NULL,
    phone VARCHAR(30) NULL,
    email VARCHAR(200) NULL,
    is_primary BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX ix_comm_party_addresses_party ON comm.party_addresses (party_detail_account_id);
CREATE INDEX ix_comm_party_contacts_party ON comm.party_contacts (party_detail_account_id);
