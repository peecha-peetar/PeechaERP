-- پیچا | افزودنِ نوعِ سندِ «پیش‌فاکتور» (خرید و فروش) به اسنادِ بازرگانی —
-- طبقِ درخواستِ صریح: «اصلا پیش‌فاکتوری وجود ندارد». پیش‌فاکتور از نظرِ
-- گردشِ کار دقیقاً هم‌الگو با سفارش است (بدونِ اثرِ مالی/انبار)، فقط
-- برچسبِ متفاوت و قابلِ‌تبدیل‌شدن به فاکتورِ واقعی.
-- پیش‌نیاز: 067_commercial_documents.sql

ALTER TABLE comm.commercial_documents
    DROP CONSTRAINT commercial_documents_document_type_code_check;

ALTER TABLE comm.commercial_documents
    ADD CONSTRAINT commercial_documents_document_type_code_check
    CHECK (document_type_code IN (
        'SALES_ORDER', 'SALES_PROFORMA', 'SALES_INVOICE', 'SALES_RETURN',
        'PURCHASE_ORDER', 'PURCHASE_PROFORMA', 'PURCHASE_INVOICE', 'PURCHASE_RETURN'
    ));
