-- طبقِ ادامه‌یِ اولویت‌بندی (بخشِ ۳: «مقایسه‌یِ قیمت با ترب»): تربِ
-- (torob.com) به‌جایِ APIِ Push، فایلِ فیدِ XML می‌خواهد که خودِ سایتِ
-- فروشگاه میزبانی می‌کند و کراولرِ ترب دوره‌ای آن را می‌خواند -- پس
-- زیرساختِ اتصالِ موجود (comm.marketplace_connections) کافی است: فقط
-- کدِ پلتفرمِ تازه‌ای اضافه می‌شود (store_url این‌جا یعنی آدرسِ پایه‌یِ
-- صفحاتِ محصول، channel_code هم مثلِ بقیه فهرستِ قیمت را مشخص می‌کند).
ALTER TABLE comm.marketplace_connections DROP CONSTRAINT marketplace_connections_platform_code_check;
ALTER TABLE comm.marketplace_connections ADD CONSTRAINT marketplace_connections_platform_code_check
    CHECK (platform_code IN ('WOOCOMMERCE', 'PRESTASHOP', 'TOROB', 'OTHER'));
