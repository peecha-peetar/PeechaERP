-- طبقِ درخواستِ صریح (پورتِ «استودیویِ قیمت»ِ PeechaSync): هر اتصال
-- می‌تواند برایِ یک دسته یا برندِ خاص، یک درصد/مبلغِ افزوده (نسبت به
-- قیمتِ فهرستِ قیمتِ کانال) تعریف کند -- بدونِ نیاز به دستکاریِ تک‌تکِ
-- ردیف‌هایِ فهرستِ قیمت. اولویت: برند > دسته (اگر کالایی هم برند و هم
-- دسته‌یِ دارایِ قاعده داشته باشد، قاعده‌یِ برند اعمال می‌شود).
CREATE TABLE comm.ecommerce_pricing_rules (
    rule_id BIGSERIAL PRIMARY KEY,
    connection_id BIGINT NOT NULL REFERENCES comm.marketplace_connections(connection_id),
    scope_type_code VARCHAR(10) NOT NULL CHECK (scope_type_code IN ('CATEGORY', 'BRAND')),
    scope_id BIGINT NOT NULL,
    markup_type_code VARCHAR(10) NOT NULL CHECK (markup_type_code IN ('PERCENT', 'AMOUNT')),
    markup_value NUMERIC(18, 6) NOT NULL,
    UNIQUE (connection_id, scope_type_code, scope_id)
);
