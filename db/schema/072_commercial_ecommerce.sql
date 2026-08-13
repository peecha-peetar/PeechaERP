-- پیچا | مدیریتِ بازرگانی — مرحلهٔ ۸: اتصال‌گرِ انتزاعی و DOM.
-- پیش‌نیاز: 065_commercial_pricing_channels.sql، 067_commercial_documents.sql

CREATE TABLE comm.marketplace_connections (
    connection_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    platform_code VARCHAR(20) NOT NULL CHECK (platform_code IN ('WOOCOMMERCE', 'PRESTASHOP', 'OTHER')),
    store_url VARCHAR(300) NOT NULL,
    credentials_encrypted BYTEA NULL,
    channel_code VARCHAR(20) NOT NULL,
    warehouse_id INT NULL REFERENCES inv.warehouses(warehouse_id),
    sync_status VARCHAR(15) NOT NULL DEFAULT 'ACTIVE'
        CHECK (sync_status IN ('ACTIVE', 'DISCONNECTED', 'ERROR')),
    last_synced_at TIMESTAMPTZ NULL,
    CONSTRAINT fk_comm_marketplace_connections_channel
        FOREIGN KEY (company_id, channel_code) REFERENCES comm.channels(company_id, channel_code)
);

CREATE TABLE comm.marketplace_order_sync_log (
    log_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    connection_id INT NOT NULL REFERENCES comm.marketplace_connections(connection_id),
    external_order_id VARCHAR(100) NOT NULL,
    document_id BIGINT NULL REFERENCES comm.commercial_documents(document_id),
    sync_status VARCHAR(15) NOT NULL CHECK (sync_status IN ('IMPORTED', 'FAILED', 'DUPLICATE')),
    error_message VARCHAR(500) NULL,
    synced_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_comm_marketplace_order_sync_external UNIQUE (connection_id, external_order_id)
);

CREATE INDEX ix_comm_sync_log_status
    ON comm.marketplace_order_sync_log (connection_id)
    WHERE sync_status = 'FAILED';

CREATE TABLE comm.marketplace_item_mappings (
    mapping_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    connection_id INT NOT NULL REFERENCES comm.marketplace_connections(connection_id),
    external_sku VARCHAR(100) NOT NULL,
    item_id INT NOT NULL REFERENCES inv.items(item_id),
    external_price NUMERIC(18,6) NULL,
    CONSTRAINT uq_comm_marketplace_item_mappings UNIQUE (connection_id, external_sku)
);

CREATE INDEX ix_comm_marketplace_item_mappings_sku ON comm.marketplace_item_mappings (connection_id, external_sku);

CREATE TABLE comm.marketplace_customer_mappings (
    mapping_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    connection_id INT NOT NULL REFERENCES comm.marketplace_connections(connection_id),
    external_customer_id VARCHAR(100) NOT NULL,
    customer_detail_account_id INT NOT NULL REFERENCES acc.detail_accounts(detail_account_id),
    CONSTRAINT uq_comm_marketplace_customer_mappings UNIQUE (connection_id, external_customer_id)
);

CREATE TABLE comm.marketplace_inventory_push_log (
    log_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    connection_id INT NOT NULL REFERENCES comm.marketplace_connections(connection_id),
    item_id INT NOT NULL REFERENCES inv.items(item_id),
    pushed_atp_quantity NUMERIC(18,6) NOT NULL,
    pushed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    push_status VARCHAR(15) NOT NULL DEFAULT 'OK' CHECK (push_status IN ('OK', 'FAILED'))
);

-- مسیریابیِ توزیع‌شدهٔ سفارش (مرحلهٔ ۸، بخشِ ۵).
CREATE TABLE comm.fulfillment_routing_rules (
    rule_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    channel_code VARCHAR(20) NULL,
    strategy_code VARCHAR(20) NOT NULL
        CHECK (strategy_code IN ('MOST_STOCK', 'REGION_MATCH', 'LOWEST_COST', 'FIXED_WAREHOUSE')),
    fallback_warehouse_id INT NOT NULL REFERENCES inv.warehouses(warehouse_id),
    priority SMALLINT NOT NULL DEFAULT 100,
    CONSTRAINT fk_comm_fulfillment_routing_rules_channel
        FOREIGN KEY (company_id, channel_code) REFERENCES comm.channels(company_id, channel_code)
);
