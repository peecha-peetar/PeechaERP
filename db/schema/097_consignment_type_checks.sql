-- طبقِ همان دلیلِ 086_proforma_invoice.sql: افزودنِ نوعِ سندِ تازه به
-- comm.commercial_documents نیازمندِ بازسازیِ CHECKِ document_type_code
-- است. امانیِ ورودی (CONSIGNMENT_IN) به یک نوعِ سندِ انبارِ تازه هم نیاز
-- دارد (services/inventory_engine.py -- بدونِ اثرِ حسابداری، مثلِ نیمه‌یِ
-- ورودیِ TRANSFER)، و بازگردانیِ کالایِ مصرف‌نشده‌یِ آن به یک نوعِ دیگر
-- (CONSIGN_RETURN، بدونِ اثرِ حسابداری، مثلِ نیمه‌یِ خروجیِ
-- TRANSFER) -- پس CHECKِ inv.stock_documents هم باید بازسازی شود.
ALTER TABLE comm.commercial_documents
    DROP CONSTRAINT commercial_documents_document_type_code_check;

ALTER TABLE comm.commercial_documents
    ADD CONSTRAINT commercial_documents_document_type_code_check
    CHECK (document_type_code IN (
        'SALES_ORDER', 'SALES_PROFORMA', 'SALES_INVOICE', 'SALES_RETURN',
        'PURCHASE_ORDER', 'PURCHASE_PROFORMA', 'PURCHASE_INVOICE', 'PURCHASE_RETURN',
        'CONSIGNMENT_OUT', 'CONSIGNMENT_IN'
    ));

ALTER TABLE inv.stock_documents
    DROP CONSTRAINT stock_documents_document_type_code_check;

ALTER TABLE inv.stock_documents
    ADD CONSTRAINT stock_documents_document_type_code_check
    CHECK (document_type_code IN (
        'RECEIPT', 'ISSUE', 'TRANSFER', 'RETURN_IN', 'RETURN_OUT', 'ADJUSTMENT',
        'CONSIGNMENT_IN', 'CONSIGN_RETURN'
    ));
