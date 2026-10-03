-- طبقِ درخواستِ صریح («کدهایِ ردیفِ تامین‌کننده با کدهایِ من فرق دارد --
-- باید کد یا کدهایی تعریف کنم که بشه از فایلِ تامین‌کننده کد را
-- شناسایی کرد»): هر کالا می‌تواند چند کدِ تامین‌کننده داشته باشد --
-- معمولاً یکی به‌ازایِ هر تامین‌کننده (یک کالا ممکن است نزدِ چند
-- تامین‌کنندهٔ مختلف کدهایِ متفاوت داشته باشد)، ولی supplier_detail_
-- account_id می‌تواند NULL هم باشد (یک کدِ عمومی/بدونِ‌وابستگی‌به‌
-- تامین‌کنندهٔ خاص -- مثلاً بارکدِ رایجِ صنعتی).
CREATE TABLE inv.item_supplier_codes (
    item_supplier_code_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    item_id INT NOT NULL REFERENCES inv.items(item_id),
    supplier_detail_account_id INT NULL REFERENCES acc.detail_accounts(detail_account_id),
    supplier_code VARCHAR(60) NOT NULL,
    -- طبقِ نیازِ تطبیقِ خودکار (بدونِ حساسیت به حروفِ بزرگ/کوچک، فاصله‌یِ
    -- ابتدا/انتها): مقدارِ نرمال‌شده برایِ جست‌وجو -- خودِ supplier_code
    -- برایِ نمایش دست‌نخورده می‌ماند.
    normalized_code VARCHAR(60) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_inv_item_supplier_codes UNIQUE (item_id, supplier_detail_account_id, normalized_code)
);

CREATE INDEX idx_inv_item_supplier_codes_lookup ON inv.item_supplier_codes(supplier_detail_account_id, normalized_code);

-- طبقِ درخواستِ صریح («این تطبیق را برایِ دفعاتِ بعد ذخیره کن»): تنظیماتِ
-- ستون‌بندیِ فایلِ هر تامین‌کننده (اکسل/PDF) -- تا کاربر هر بار مجبور
-- به تطبیقِ دستیِ ستون‌ها نباشد.
CREATE TABLE comm.supplier_price_import_templates (
    template_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    supplier_detail_account_id INT NOT NULL REFERENCES acc.detail_accounts(detail_account_id),
    code_column_index SMALLINT NOT NULL,
    price_column_index SMALLINT NOT NULL,
    header_row_index SMALLINT NOT NULL DEFAULT 0,
    sheet_name VARCHAR(100) NULL,
    CONSTRAINT uq_comm_supplier_price_import_templates UNIQUE (company_id, supplier_detail_account_id)
);
