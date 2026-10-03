-- طبقِ درخواستِ صریح («مدیر بتواند فاکتورِ ثبت‌شده را اصلاح کند»): فاکتورِ
-- ثبت‌شده هرگز backdate/دست‌کاری نمی‌شود -- به‌جایش سند/موجودی‌اش عیناً
-- برگشت می‌خورد (در تاریخِ امروز) و یک فاکتورِ تازه با اطلاعاتِ اصلاح‌شده
-- جایگزینش می‌شود، با رفرنسِ صریح به همدیگر. status «CORRECTED» یعنی
-- «این فاکتور اصلاح شده، دیگر در آمارِ خرید/فروش شمرده نشود».

ALTER TABLE comm.commercial_documents DROP CONSTRAINT commercial_documents_status_code_check;
ALTER TABLE comm.commercial_documents ADD CONSTRAINT commercial_documents_status_code_check
    CHECK (status_code IN ('DRAFT', 'CONFIRMED', 'APPROVED', 'POSTED', 'CANCELLED', 'CORRECTED'));

ALTER TABLE comm.commercial_documents
    ADD COLUMN corrects_document_id BIGINT NULL REFERENCES comm.commercial_documents(document_id),
    ADD COLUMN corrected_by_document_id BIGINT NULL REFERENCES comm.commercial_documents(document_id);
