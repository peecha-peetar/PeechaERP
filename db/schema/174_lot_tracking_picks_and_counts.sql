-- پیچا R228: انتخابِ دقیقِ منبع در خروج (تامین‌کننده/امانی) و انبارگردانی با بچ/سریال.
ALTER TABLE inv.line_tracking_entries
    ADD COLUMN IF NOT EXISTS supplier_detail_account_id INT REFERENCES acc.detail_accounts(detail_account_id),
    ADD COLUMN IF NOT EXISTS is_consignment BOOLEAN,
    ADD COLUMN IF NOT EXISTS cycle_count_line_id BIGINT REFERENCES inv.cycle_count_lines(line_id) ON DELETE CASCADE;

ALTER TABLE inv.line_tracking_entries DROP CONSTRAINT IF EXISTS ck_inv_line_tracking_one_owner;
ALTER TABLE inv.line_tracking_entries ADD CONSTRAINT ck_inv_line_tracking_one_owner
    CHECK (num_nonnulls(commercial_line_id, stock_line_id, cycle_count_line_id) = 1);
CREATE INDEX IF NOT EXISTS ix_inv_line_tracking_count ON inv.line_tracking_entries (cycle_count_line_id);
