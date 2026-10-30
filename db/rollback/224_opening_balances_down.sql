-- برگشت R314 (افتتاحیه). اگر سند باز افتتاحیه یا تراکنش WIP افتتاحیه ثبت شده باشد، بازسازی CHECKها رد می‌شود؛
-- اول افتتاحیه را با «افتتاحیهٔ اصلاحی» برگشت بزنید و آن اسناد را بردارید.
BEGIN;
DROP SCHEMA opn CASCADE;
ALTER TABLE comm.commercial_documents DROP CONSTRAINT commercial_documents_document_type_code_check;
ALTER TABLE comm.commercial_documents ADD CONSTRAINT commercial_documents_document_type_code_check
    CHECK (document_type_code IN (
        'SALES_ORDER', 'SALES_PROFORMA', 'SALES_INVOICE', 'SALES_RETURN',
        'PURCHASE_ORDER', 'PURCHASE_PROFORMA', 'PURCHASE_INVOICE', 'PURCHASE_RETURN',
        'CONSIGNMENT_OUT', 'CONSIGNMENT_IN'
    ));
ALTER TABLE prd.order_transactions DROP CONSTRAINT order_transactions_txn_type_check;
ALTER TABLE prd.order_transactions ADD CONSTRAINT order_transactions_txn_type_check
    CHECK (txn_type IN ('ISSUE', 'RETURN', 'RECEIPT', 'BY_PRODUCT', 'CO_PRODUCT', 'SCRAP', 'LABOR', 'MACHINE', 'OVERHEAD',
                        'VARIANCE', 'REVERSAL'));
DELETE FROM inv.account_mappings WHERE mapping_key = 'OPENING_CLEARING';
DELETE FROM inv.company_features WHERE feature_code = 'OPN_SELF_APPROVAL';
DELETE FROM inv.feature_definitions WHERE feature_code = 'OPN_SELF_APPROVAL';
DELETE FROM public.peecha_schema_migrations WHERE filename = '224_opening_balances.sql';
COMMIT;
