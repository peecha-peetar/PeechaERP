-- پیچا R241: درخواستِ خرید (Purchase Request) -- فقط افزایشی.
-- گردش: پیش‌نویس → ارسال‌شده → تصویب‌شده/ردشده → (تبدیل به سفارشِ خرید) ؛ لغو در هر مرحلهٔ پیش از تبدیل.
-- مقدارِ سفارش‌شدهٔ هر ردیف ذخیره نمی‌شود؛ همیشه از ردیف‌هایِ سفارشِ خریدِ لغونشدهٔ مرتبط محاسبه می‌شود.
--
-- بازگشت (rollback):
--   ALTER TABLE comm.commercial_document_lines DROP COLUMN IF EXISTS purchase_request_line_id;
--   DROP TABLE IF EXISTS comm.purchase_request_lines, comm.purchase_requests;

CREATE TABLE IF NOT EXISTS comm.purchase_requests (
    request_id BIGSERIAL PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    request_no INT NOT NULL,
    request_date DATE NOT NULL,
    required_date DATE NULL,
    requester_user_id INT NOT NULL REFERENCES sec.users(user_id),
    priority_code VARCHAR(10) NOT NULL DEFAULT 'NORMAL',      -- NORMAL | URGENT
    purchase_type_id INT NULL REFERENCES comm.purchase_types(purchase_type_id),
    warehouse_id INT NULL REFERENCES inv.warehouses(warehouse_id),
    cost_center_detail_account_id INT NULL REFERENCES acc.detail_accounts(detail_account_id),
    project_detail_account_id INT NULL REFERENCES acc.detail_accounts(detail_account_id),
    status_code VARCHAR(15) NOT NULL DEFAULT 'DRAFT',          -- DRAFT | SUBMITTED | APPROVED | REJECTED | CANCELLED
    description TEXT NULL,
    submitted_at TIMESTAMP NULL,
    approved_by_user_id INT NULL REFERENCES sec.users(user_id),
    approved_at TIMESTAMP NULL,
    rejected_reason TEXT NULL,
    cancellation_reason_id INT NULL REFERENCES comm.cancellation_reasons(reason_id),
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (company_id, request_no)
);

CREATE TABLE IF NOT EXISTS comm.purchase_request_lines (
    line_id BIGSERIAL PRIMARY KEY,
    request_id BIGINT NOT NULL REFERENCES comm.purchase_requests(request_id) ON DELETE CASCADE,
    line_no INT NOT NULL,
    item_id INT NOT NULL REFERENCES inv.items(item_id),
    uom_id INT NOT NULL REFERENCES inv.uom(uom_id),
    quantity NUMERIC(18,6) NOT NULL CHECK (quantity > 0),
    conversion_factor NUMERIC(18,6) NOT NULL DEFAULT 1,
    quantity_base NUMERIC(18,6) NOT NULL CHECK (quantity_base > 0),
    required_date DATE NULL,
    suggested_supplier_detail_account_id INT NULL REFERENCES acc.detail_accounts(detail_account_id),
    estimated_unit_price NUMERIC(18,4) NULL,
    description TEXT NULL
);
CREATE INDEX IF NOT EXISTS ix_purchase_request_lines_request ON comm.purchase_request_lines (request_id);

ALTER TABLE comm.commercial_document_lines
    ADD COLUMN IF NOT EXISTS purchase_request_line_id BIGINT NULL REFERENCES comm.purchase_request_lines(line_id);
CREATE INDEX IF NOT EXISTS ix_commercial_document_lines_pr_line ON comm.commercial_document_lines (purchase_request_line_id);
