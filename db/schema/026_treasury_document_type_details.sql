-- پیچا | خزانه‌داری: تفصیلی‌هایِ مجازِ «نوعِ سند» — طبقِ درخواستِ صریح، به‌جایِ
-- یک تفصیلیِ ثابتِ تکی، حالا هر نوعِ سند می‌تواند چند تفصیلیِ «مجاز/پیشنهادی»
-- داشته باشد: صفرتا (فرمِ سند از بینِ همه‌ی تفصیلی‌هایِ معتبرِ معین می‌پرسد)،
-- دقیقاً یکی (خودکار همان استفاده می‌شود، مثلِ رفتارِ قبلی)، یا چندتا (فرمِ
-- سند فقط همان‌ها را به‌صورتِ جستجوپذیر پیشنهاد می‌دهد).
-- پیش‌نیاز: 025_treasury_document_types.sql

CREATE TABLE treasury.document_type_details (
    document_type_id  INT NOT NULL REFERENCES treasury.document_types(document_type_id) ON DELETE CASCADE,
    detail_account_id INT NOT NULL REFERENCES acc.detail_accounts(detail_account_id),
    PRIMARY KEY (document_type_id, detail_account_id)
);

INSERT INTO treasury.document_type_details (document_type_id, detail_account_id)
SELECT document_type_id, detail_account_id FROM treasury.document_types WHERE detail_account_id IS NOT NULL;

ALTER TABLE treasury.document_types DROP COLUMN detail_account_id;
