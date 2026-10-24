-- طبقِ درخواستِ صریح: (۱) هر کالا علاوه بر «کد»، بتواند «نامِ» تامین‌کننده
-- را هم به‌عنوانِ مرجعِ شناسایی داشته باشد (بعضی تامین‌کننده‌ها فقط نامِ
-- کالا می‌فرستند، نه کد) -- تشخیص باید ترکیبی (کد یا نام) باشد.
-- (۲) لاگِ تاریخچه‌یِ قیمت‌هایِ فهرستِ قیمت تا بشود قیمتِ اشتباه را
-- برگرداند.

ALTER TABLE inv.item_supplier_codes
    ADD COLUMN value_type VARCHAR(10) NOT NULL DEFAULT 'CODE'
        CONSTRAINT ck_inv_item_supplier_codes_value_type CHECK (value_type IN ('CODE', 'NAME'));

ALTER TABLE inv.item_supplier_codes DROP CONSTRAINT uq_inv_item_supplier_codes;
ALTER TABLE inv.item_supplier_codes
    ADD CONSTRAINT uq_inv_item_supplier_codes UNIQUE (item_id, supplier_detail_account_id, value_type, normalized_code);

DROP INDEX IF EXISTS inv.idx_inv_item_supplier_codes_lookup;
CREATE INDEX idx_inv_item_supplier_codes_lookup ON inv.item_supplier_codes(supplier_detail_account_id, value_type, normalized_code);

CREATE TABLE comm.price_list_item_price_history (
    history_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    price_list_id INT NOT NULL REFERENCES comm.price_lists(price_list_id),
    item_id INT NOT NULL REFERENCES inv.items(item_id),
    uom_id INT NOT NULL REFERENCES inv.uom(uom_id),
    min_quantity NUMERIC(18, 6) NOT NULL,
    old_price NUMERIC(18, 6),
    new_price NUMERIC(18, 6) NOT NULL,
    source_code VARCHAR(30) NOT NULL DEFAULT 'MANUAL',
    note VARCHAR(255),
    changed_by_user_id INT REFERENCES sec.users(user_id),
    changed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_price_list_item_price_history_lookup
    ON comm.price_list_item_price_history(price_list_id, item_id, uom_id, min_quantity, changed_at);
