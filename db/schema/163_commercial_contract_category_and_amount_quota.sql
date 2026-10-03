-- پیچا | قراردادِ نمایندگی/سازمانی + سهمیه‌یِ مبلغی + تعهدات (R219،
-- بخشِ ۷) -- رویِ همان comm.commercial_contracts موجود (که از قبل
-- سهمیه‌یِ تعدادی/قیمتِ توافقی/بازه‌یِ اعتبار را داشت، فقط دستِ‌نخورده
-- نگه‌داشته‌شده و بدونِ UI بود).

ALTER TABLE comm.commercial_contracts
    ADD COLUMN contract_category_code VARCHAR(15) NOT NULL DEFAULT 'STANDARD'
        CHECK (contract_category_code IN ('STANDARD', 'AGENCY', 'ORGANIZATIONAL')),
    ADD COLUMN committed_amount NUMERIC(18, 2) NULL CHECK (committed_amount IS NULL OR committed_amount >= 0),
    ADD COLUMN consumed_amount NUMERIC(18, 2) NOT NULL DEFAULT 0,
    ADD COLUMN commitments_text VARCHAR(1000) NULL;
