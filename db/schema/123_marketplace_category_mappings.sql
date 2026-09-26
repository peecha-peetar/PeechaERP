-- پیچا | ماژولِ فروشِ اینترنتی — نگاشتِ دسته‌بندیِ داخلیِ کالا به
-- شناسه‌یِ دسته‌بندیِ همان دسته در فروشگاهِ خارجی (ووکامرس/پرستاشاپ) --
-- برایِ اینکه هر بار سینکِ کالا، دسته را دوباره نسازد.

CREATE TABLE comm.marketplace_category_mappings (
    mapping_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    connection_id INT NOT NULL REFERENCES comm.marketplace_connections(connection_id),
    category_id INT NOT NULL REFERENCES inv.item_categories(category_id),
    external_category_id VARCHAR(100) NOT NULL,
    CONSTRAINT uq_comm_marketplace_category_mappings UNIQUE (connection_id, category_id)
);

CREATE INDEX ix_comm_marketplace_category_mappings_conn
    ON comm.marketplace_category_mappings (connection_id);
