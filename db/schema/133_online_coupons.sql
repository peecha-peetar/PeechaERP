-- طبقِ بازخوردِ صریحِ کاربر («امکاناتِ حیاتیِ PeechaSync -- کوپن/کدِ
-- تخفیفِ فروشگاهی»): کوپن در خودِ ERP تعریف می‌شود و به فروشگاهِ
-- ووکامرس (V1، طبقِ محدودیتِ همین دور) پوش می‌شود.
CREATE TABLE comm.online_coupons (
    coupon_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    connection_id INT NOT NULL REFERENCES comm.marketplace_connections(connection_id),
    code VARCHAR(50) NOT NULL,
    discount_type_code VARCHAR(15) NOT NULL
        CHECK (discount_type_code IN ('PERCENT', 'FIXED_CART', 'FIXED_PRODUCT')),
    amount NUMERIC(18,6) NOT NULL,
    valid_from DATE NULL,
    valid_until DATE NULL,
    usage_limit INT NULL,
    external_coupon_id VARCHAR(50) NULL,
    sync_status VARCHAR(15) NOT NULL DEFAULT 'PENDING'
        CHECK (sync_status IN ('PENDING', 'SYNCED', 'FAILED')),
    last_sync_error VARCHAR(500) NULL,
    last_synced_at TIMESTAMPTZ NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_comm_online_coupons_code UNIQUE (connection_id, code)
);
