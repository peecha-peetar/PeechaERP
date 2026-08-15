-- پیچا | مدیریتِ بازرگانی — مرحلهٔ ۷: جلسهٔ صندوق و ابزارهایِ وفاداری.
-- ترمینال/جلسه پیش از اسکلتِ سند ساخته می‌شوند چون هر سندِ POS به یک
-- جلسهٔ باز ارجاع می‌دهد (comm.commercial_documents.pos_session_id).
-- پیش‌نیاز: 058_inventory_locations.sql، 065_commercial_pricing_channels.sql

CREATE TABLE comm.pos_terminals (
    terminal_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    warehouse_id INT NOT NULL REFERENCES inv.warehouses(warehouse_id),
    code VARCHAR(20) NOT NULL,
    name VARCHAR(100) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_comm_pos_terminals UNIQUE (company_id, code)
);

CREATE TABLE comm.pos_sessions (
    session_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    terminal_id INT NOT NULL REFERENCES comm.pos_terminals(terminal_id),
    opened_by_user_id INT NOT NULL REFERENCES sec.users(user_id),
    opened_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    opening_cash_amount NUMERIC(18,2) NOT NULL,
    closed_by_user_id INT NULL REFERENCES sec.users(user_id),
    closed_at TIMESTAMPTZ NULL,
    closing_cash_amount NUMERIC(18,2) NULL,
    expected_cash_amount NUMERIC(18,2) NULL,
    variance_amount NUMERIC(18,2) GENERATED ALWAYS AS (closing_cash_amount - expected_cash_amount) STORED,
    status_code VARCHAR(10) NOT NULL DEFAULT 'OPEN' CHECK (status_code IN ('OPEN', 'CLOSED')),
    -- ترمینال قفل‌شده به‌دلیلِ مغایرتِ بالایِ آستانه (مرحلهٔ ۷، بخشِ ۷)؛
    -- تا آزادسازیِ دستی، جلسهٔ تازه رویِ همان ترمینال قابلِ‌بازکردن نیست.
    variance_override_by_user_id INT NULL REFERENCES sec.users(user_id),
    variance_override_reason VARCHAR(500) NULL
);

-- هر ترمینال هم‌زمان فقط یک جلسهٔ باز.
CREATE UNIQUE INDEX ux_comm_pos_sessions_open
    ON comm.pos_sessions (terminal_id)
    WHERE status_code = 'OPEN';

CREATE TABLE comm.loyalty_accounts (
    loyalty_account_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_detail_account_id INT NOT NULL UNIQUE REFERENCES acc.detail_accounts(detail_account_id),
    points_balance INT NOT NULL DEFAULT 0,
    wallet_balance NUMERIC(18,2) NOT NULL DEFAULT 0,
    tier_code VARCHAR(20) NOT NULL DEFAULT 'STANDARD',
    CONSTRAINT ck_comm_loyalty_accounts_balances CHECK (points_balance >= 0 AND wallet_balance >= 0)
);

CREATE TABLE comm.gift_cards (
    card_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    code VARCHAR(30) NOT NULL,
    initial_balance NUMERIC(18,2) NOT NULL CHECK (initial_balance > 0),
    current_balance NUMERIC(18,2) NOT NULL,
    issued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NULL,
    status_code VARCHAR(10) NOT NULL DEFAULT 'ACTIVE' CHECK (status_code IN ('ACTIVE', 'REDEEMED', 'EXPIRED')),
    CONSTRAINT uq_comm_gift_cards_code UNIQUE (code),
    CONSTRAINT ck_comm_gift_cards_balance CHECK (current_balance BETWEEN 0 AND initial_balance)
);

-- مشتریِ متفرقهٔ پیش‌فرضِ فروشِ سریع (مرحلهٔ ۷، بخشِ ۴).
CREATE TABLE comm.pos_settings (
    company_id INT NOT NULL PRIMARY KEY REFERENCES core.companies(company_id),
    default_guest_customer_detail_account_id INT NULL REFERENCES acc.detail_accounts(detail_account_id),
    cash_variance_threshold_amount NUMERIC(18,2) NOT NULL DEFAULT 0
);
