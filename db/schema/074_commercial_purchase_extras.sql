-- پیچا | مدیریتِ بازرگانی — مرحلهٔ ۴: بهایِ تمام‌شدهٔ وارداتی و ریبیت.
-- پیش‌نیاز: 067_commercial_documents.sql، 068_commercial_partners.sql

CREATE TABLE comm.landed_cost_allocations (
    allocation_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    purchase_invoice_document_id BIGINT NOT NULL REFERENCES comm.commercial_documents(document_id),
    cost_type_code VARCHAR(15) NOT NULL
        CHECK (cost_type_code IN ('FREIGHT', 'CUSTOMS', 'INSURANCE', 'HANDLING', 'OTHER')),
    amount NUMERIC(18,2) NOT NULL CHECK (amount > 0),
    allocation_method_code VARCHAR(15) NOT NULL
        CHECK (allocation_method_code IN ('BY_VALUE', 'BY_QUANTITY', 'BY_WEIGHT')),
    notes VARCHAR(500) NULL
);

CREATE INDEX ix_comm_landed_cost_invoice ON comm.landed_cost_allocations (purchase_invoice_document_id);

CREATE TABLE comm.vendor_rebate_agreements (
    agreement_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    supplier_detail_account_id INT NOT NULL REFERENCES acc.detail_accounts(detail_account_id),
    item_id INT NULL REFERENCES inv.items(item_id),
    rebate_basis_code VARCHAR(15) NOT NULL CHECK (rebate_basis_code IN ('FLAT_PERCENT', 'VOLUME_TIER')),
    valid_from DATE NOT NULL,
    valid_to DATE NULL,
    status_code VARCHAR(15) NOT NULL DEFAULT 'ACTIVE'
        CHECK (status_code IN ('ACTIVE', 'EXPIRED', 'CANCELLED'))
);

CREATE TABLE comm.vendor_rebate_tiers (
    tier_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    agreement_id INT NOT NULL REFERENCES comm.vendor_rebate_agreements(agreement_id),
    min_purchase_amount NUMERIC(18,2) NOT NULL,
    rebate_percent NUMERIC(5,2) NOT NULL CHECK (rebate_percent BETWEEN 0 AND 100)
);

CREATE TABLE comm.vendor_rebate_accruals (
    accrual_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    agreement_id INT NOT NULL REFERENCES comm.vendor_rebate_agreements(agreement_id),
    period_from DATE NOT NULL,
    period_to DATE NOT NULL,
    accrued_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    status_code VARCHAR(15) NOT NULL DEFAULT 'ACCRUING' CHECK (status_code IN ('ACCRUING', 'SETTLED')),
    settlement_journal_entry_id INT NULL REFERENCES acc.journal_entries(journal_entry_id),
    CONSTRAINT ck_comm_vendor_rebate_accruals_period CHECK (period_to > period_from)
);

CREATE INDEX ix_comm_vendor_rebate_accruals_agreement_period
    ON comm.vendor_rebate_accruals (agreement_id, period_from);
