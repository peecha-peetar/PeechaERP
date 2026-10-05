-- پیچا R263: ماه‌هایِ استهلاکِ ازپیش‌گذشته برایِ دارایی‌هایِ حاصل از تقسیم/جزء (عمرِ باقی‌مانده از صفر شروع نشود) -- افزودنی.
ALTER TABLE fa.assets ADD COLUMN IF NOT EXISTS depreciated_months_offset INT NOT NULL DEFAULT 0
    CHECK (depreciated_months_offset >= 0);
