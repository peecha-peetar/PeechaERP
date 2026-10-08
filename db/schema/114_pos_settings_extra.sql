ALTER TABLE comm.pos_settings
    ADD COLUMN allow_price_override BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN allow_discount_override BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN quick_access_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN scan_beep_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN receipt_header_text VARCHAR(200),
    ADD COLUMN receipt_footer_text VARCHAR(200);
