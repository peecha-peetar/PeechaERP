-- پیچا R242: استعلامِ قیمت (RFQ) -- فقط افزایشی.
-- گردش: پیش‌نویس → ارسال‌شده (دعوت از تامین‌کنندگان) → ثبتِ پیشنهادها → انتخاب (Award) → سفارشِ خرید ؛ لغو پیش از سفارش.
--
-- بازگشت (rollback):
--   ALTER TABLE comm.commercial_document_lines DROP COLUMN IF EXISTS rfq_quote_id;
--   DROP TABLE IF EXISTS comm.rfq_quotes, comm.rfq_suppliers, comm.rfq_lines, comm.rfqs;

CREATE TABLE IF NOT EXISTS comm.rfqs (
    rfq_id BIGSERIAL PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    rfq_no INT NOT NULL,
    rfq_date DATE NOT NULL,
    response_due_date DATE NULL,
    request_id BIGINT NULL REFERENCES comm.purchase_requests(request_id),
    status_code VARCHAR(15) NOT NULL DEFAULT 'DRAFT',   -- DRAFT | SENT | AWARDED | ORDERED | CANCELLED
    description TEXT NULL,
    created_by_user_id INT NOT NULL REFERENCES sec.users(user_id),
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    sent_at TIMESTAMP NULL,
    awarded_at TIMESTAMP NULL,
    awarded_by_user_id INT NULL REFERENCES sec.users(user_id),
    UNIQUE (company_id, rfq_no)
);

CREATE TABLE IF NOT EXISTS comm.rfq_lines (
    line_id BIGSERIAL PRIMARY KEY,
    rfq_id BIGINT NOT NULL REFERENCES comm.rfqs(rfq_id) ON DELETE CASCADE,
    line_no INT NOT NULL,
    item_id INT NOT NULL REFERENCES inv.items(item_id),
    uom_id INT NOT NULL REFERENCES inv.uom(uom_id),
    quantity NUMERIC(18,6) NOT NULL CHECK (quantity > 0),
    conversion_factor NUMERIC(18,6) NOT NULL DEFAULT 1,
    quantity_base NUMERIC(18,6) NOT NULL CHECK (quantity_base > 0),
    required_date DATE NULL,
    purchase_request_line_id BIGINT NULL REFERENCES comm.purchase_request_lines(line_id),
    description TEXT NULL
);

CREATE TABLE IF NOT EXISTS comm.rfq_suppliers (
    rfq_supplier_id BIGSERIAL PRIMARY KEY,
    rfq_id BIGINT NOT NULL REFERENCES comm.rfqs(rfq_id) ON DELETE CASCADE,
    supplier_detail_account_id INT NOT NULL REFERENCES acc.detail_accounts(detail_account_id),
    status_code VARCHAR(15) NOT NULL DEFAULT 'INVITED',  -- INVITED | RESPONDED | DECLINED
    responded_at TIMESTAMP NULL,
    note TEXT NULL,
    UNIQUE (rfq_id, supplier_detail_account_id)
);

CREATE TABLE IF NOT EXISTS comm.rfq_quotes (
    quote_id BIGSERIAL PRIMARY KEY,
    rfq_supplier_id BIGINT NOT NULL REFERENCES comm.rfq_suppliers(rfq_supplier_id) ON DELETE CASCADE,
    rfq_line_id BIGINT NOT NULL REFERENCES comm.rfq_lines(line_id) ON DELETE CASCADE,
    unit_price NUMERIC(18,4) NOT NULL CHECK (unit_price >= 0),     -- به واحدِ ردیفِ استعلام
    discount_percent NUMERIC(7,4) NOT NULL DEFAULT 0,
    lead_time_days INT NULL,
    valid_until DATE NULL,
    is_awarded BOOLEAN NOT NULL DEFAULT FALSE,
    note TEXT NULL,
    UNIQUE (rfq_supplier_id, rfq_line_id)
);

ALTER TABLE comm.commercial_document_lines
    ADD COLUMN IF NOT EXISTS rfq_quote_id BIGINT NULL REFERENCES comm.rfq_quotes(quote_id);
