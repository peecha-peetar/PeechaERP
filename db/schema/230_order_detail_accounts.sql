-- R340: تفصیلی گروه‌های الزامی دیگر حساب‌های تولید (غیر از مرکز هزینه و پروژه، مثل گروه «هزینه ها») که
-- هنگام ایجاد دستور تولید انتخاب می‌شود و روی سند همان حساب‌ها می‌نشیند.
CREATE TABLE IF NOT EXISTS prd.order_detail_accounts (
    order_id          BIGINT   NOT NULL REFERENCES prd.production_orders(order_id) ON DELETE CASCADE,
    dimension_type_id SMALLINT NOT NULL REFERENCES acc.detail_dimension_types(dimension_type_id),
    detail_account_id INT      NOT NULL REFERENCES acc.detail_accounts(detail_account_id),
    PRIMARY KEY (order_id, dimension_type_id)
);
