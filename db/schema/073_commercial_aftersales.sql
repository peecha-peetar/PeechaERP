-- پیچا | مدیریتِ بازرگانی — مرحلهٔ ۹: گارانتیِ خودکار، تیکت، RMA.
-- پیش‌نیاز: 060_inventory_tracking_quality.sql، 067_commercial_documents.sql

CREATE TABLE comm.warranties (
    warranty_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sales_document_line_id BIGINT NOT NULL REFERENCES comm.commercial_document_lines(line_id),
    serial_id INT NULL REFERENCES inv.serial_numbers(serial_id),
    item_id INT NOT NULL REFERENCES inv.items(item_id),
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    terms VARCHAR(500) NULL,
    status_code VARCHAR(15) NOT NULL DEFAULT 'ACTIVE'
        CHECK (status_code IN ('ACTIVE', 'EXPIRED', 'VOIDED')),
    voided_reason VARCHAR(500) NULL,
    CONSTRAINT ck_comm_warranties_dates CHECK (end_date > start_date)
);

CREATE INDEX ix_comm_warranties_serial ON comm.warranties (serial_id);

CREATE TABLE comm.service_tickets (
    ticket_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_detail_account_id INT NOT NULL REFERENCES acc.detail_accounts(detail_account_id),
    warranty_id BIGINT NULL REFERENCES comm.warranties(warranty_id),
    item_id INT NULL REFERENCES inv.items(item_id),
    subject VARCHAR(200) NOT NULL,
    description TEXT NULL,
    status_code VARCHAR(15) NOT NULL DEFAULT 'OPEN'
        CHECK (status_code IN ('OPEN', 'IN_PROGRESS', 'RESOLVED', 'CLOSED')),
    -- محاسبه‌شده در لحظهٔ بازشدن، بر اساسِ وضعیتِ warranty_id (مرحلهٔ ۹، بخشِ ۷).
    is_billable BOOLEAN NOT NULL DEFAULT FALSE,
    resulting_invoice_document_id BIGINT NULL REFERENCES comm.commercial_documents(document_id),
    assigned_to_user_id INT NULL REFERENCES sec.users(user_id),
    opened_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at TIMESTAMPTZ NULL,
    CONSTRAINT ck_comm_service_tickets_billable_invoice
        CHECK (NOT (is_billable AND status_code = 'CLOSED' AND resulting_invoice_document_id IS NULL))
);

CREATE INDEX ix_comm_service_tickets_status_customer ON comm.service_tickets (customer_detail_account_id, status_code);

CREATE TABLE comm.rma_requests (
    rma_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_detail_account_id INT NOT NULL REFERENCES acc.detail_accounts(detail_account_id),
    original_document_id BIGINT NOT NULL REFERENCES comm.commercial_documents(document_id),
    related_ticket_id BIGINT NULL REFERENCES comm.service_tickets(ticket_id),
    reason_code VARCHAR(20) NOT NULL
        CHECK (reason_code IN ('DEFECTIVE', 'WRONG_ITEM', 'NOT_SATISFIED', 'DAMAGED_IN_TRANSIT')),
    requested_quantity NUMERIC(18,6) NOT NULL CHECK (requested_quantity > 0),
    status_code VARCHAR(15) NOT NULL DEFAULT 'REQUESTED'
        CHECK (status_code IN ('REQUESTED', 'APPROVED', 'REJECTED', 'COMPLETED')),
    resulting_return_document_id BIGINT NULL REFERENCES comm.commercial_documents(document_id)
);

CREATE INDEX ix_comm_rma_requests_status
    ON comm.rma_requests (customer_detail_account_id)
    WHERE status_code = 'REQUESTED';

CREATE TABLE comm.service_ticket_parts_used (
    usage_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ticket_id BIGINT NOT NULL REFERENCES comm.service_tickets(ticket_id),
    item_id INT NOT NULL REFERENCES inv.items(item_id),
    quantity NUMERIC(18,6) NOT NULL CHECK (quantity > 0),
    -- سندِ ISSUEِ استاندارد در انبار که این مصرف را کسر کرده.
    stock_document_id BIGINT NULL REFERENCES inv.stock_documents(stock_document_id)
);
