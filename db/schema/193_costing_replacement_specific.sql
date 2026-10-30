-- پیچا R258: بهایِ جایگزینی (NIFO) و شناساییِ ویژه -- فقط افزودنی.
CREATE TABLE IF NOT EXISTS inv.replacement_costs (
    replacement_cost_id  BIGSERIAL PRIMARY KEY,
    company_id           INT           NOT NULL REFERENCES core.companies(company_id),
    item_id              INT           NOT NULL REFERENCES inv.items(item_id),
    warehouse_id         INT           NULL REFERENCES inv.warehouses(warehouse_id),
    unit_cost            NUMERIC(18,6) NOT NULL CHECK (unit_cost > 0),   -- به ازایِ واحدِ پایه
    effective_date       DATE          NOT NULL,
    source_code          VARCHAR(25)   NOT NULL DEFAULT 'MANUAL',
    note                 VARCHAR(300)  NULL,
    created_by_user_id   INT           NULL REFERENCES sec.users(user_id),
    created_at           TIMESTAMP     NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_inv_replacement_costs_item ON inv.replacement_costs (item_id, effective_date DESC);

-- بهایِ جایگزینیِ ثبت‌شدهٔ دستی، معتبرترین منبع است (اول در ترتیبِ پیش‌فرض)؛ فقط اگر تنظیمات هنوز دست‌نخورده است.
ALTER TABLE inv.company_costing_settings
    ALTER COLUMN nifo_price_sources SET DEFAULT 'MANUAL,LAST_RECEIPT,LAST_PURCHASE_PRICE,LAST_PURCHASE_ORDER,SUPPLIER_PRICE';
UPDATE inv.company_costing_settings
   SET nifo_price_sources = 'MANUAL,LAST_RECEIPT,LAST_PURCHASE_PRICE,LAST_PURCHASE_ORDER,SUPPLIER_PRICE'
 WHERE nifo_price_sources = 'LAST_RECEIPT,LAST_PURCHASE_PRICE,LAST_PURCHASE_ORDER,SUPPLIER_PRICE,MANUAL';
