-- طبقِ درخواستِ صریح («ممکنه بخشی از اقساط وصول بشه و مانده‌ی اقساط در
-- جدول نمایش داده بشه و مبلغ وصول‌شده‌ی هر قسط»): تا پیش از این، هر
-- وصول کلِ قسط را یک‌جا PAID می‌کرد -- امکانِ وصولِ بخشی (چند وصولِ
-- جزئی رویِ یک قسط) وجود نداشت. این جدول، هر رویدادِ وصول (کامل یا
-- جزئی، هرکدام با سندِ حسابداریِ خودش) را جداگانه نگه می‌دارد؛ مجموعِ
-- amount این ردیف‌ها برایِ یک line_id همان «مبلغِ وصول‌شده»‌یِ آن قسط
-- است -- دقیقاً هم‌الگو با comm.invoice_settlements برایِ فاکتورها.
CREATE TABLE comm.installment_collections (
    collection_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    line_id BIGINT NOT NULL REFERENCES comm.installment_lines(line_id),
    journal_entry_id BIGINT REFERENCES acc.journal_entries(journal_entry_id),
    collection_date DATE NOT NULL,
    amount NUMERIC(18, 2) NOT NULL,
    description VARCHAR(500),
    created_by_user_id INT NOT NULL REFERENCES sec.users(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_installment_collections_line_id ON comm.installment_collections(line_id);
