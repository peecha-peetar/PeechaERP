-- R383: پیمانکاری فرعی تولید روی همان دستور تولید: مواد به انبار نزد پیمانکار منتقل و هنگام رسید محصول از همان‌جا
-- مصرف می‌شود؛ دستمزد پیمانکار مثل دستمزد جذب‌شده به کالای در جریان ساخت می‌رود (طرف مقابل: نقش PRODUCTION_SUBCONTRACT_APPLIED).
ALTER TABLE prd.order_transactions DROP CONSTRAINT IF EXISTS order_transactions_txn_type_check;
ALTER TABLE prd.order_transactions ADD CONSTRAINT order_transactions_txn_type_check
    CHECK (txn_type IN ('ISSUE', 'RETURN', 'RECEIPT', 'BY_PRODUCT', 'CO_PRODUCT', 'SCRAP', 'LABOR', 'MACHINE', 'OVERHEAD',
                        'VARIANCE', 'REVERSAL', 'OPENING', 'SUBCONTRACT'));

CREATE TABLE IF NOT EXISTS prd.subcontract_orders (
    order_id                        BIGINT         PRIMARY KEY REFERENCES prd.production_orders(order_id) ON DELETE CASCADE,
    company_id                      INT            NOT NULL REFERENCES core.companies(company_id),
    subcontractor_detail_account_id INT            NOT NULL REFERENCES acc.detail_accounts(detail_account_id),
    warehouse_id                    INT            NOT NULL REFERENCES inv.warehouses(warehouse_id),
    fee_per_unit                    NUMERIC(18,2)  NOT NULL DEFAULT 0 CHECK (fee_per_unit >= 0),
    notes                           VARCHAR(500)   NULL,
    created_by_user_id              INT            NULL REFERENCES sec.users(user_id),
    created_at                      TIMESTAMPTZ    NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_prd_subcontract_orders_party ON prd.subcontract_orders (company_id, subcontractor_detail_account_id);
