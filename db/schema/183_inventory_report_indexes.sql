-- پیچا R246: ایندکس‌هایِ گزارش‌هایِ انبار -- فقط افزایشی؛ هیچ داده/ستونی تغییر نمی‌کند.
-- دلیل: کوئری‌هایِ گردش/کارتکس/ارزش رویِ این ستون‌ها join یا فیلتر می‌کنند و ایندکس نداشتند
-- (stock_balance فقط ایندکسِ یکتایِ (item_id, ...) داشت و فیلترِ شرکت کلِ جدول را می‌خواند).
-- بازگشت (rollback):
--   DROP INDEX IF EXISTS inv.ix_inv_stock_ledger_doc_line, inv.ix_inv_stock_balance_company_item_wh,
--     comm.ix_comm_documents_stock_document, comm.ix_comm_document_lines_stock_line, inv.ix_inv_serial_movements_serial;
CREATE INDEX IF NOT EXISTS ix_inv_stock_ledger_doc_line ON inv.stock_ledger (stock_document_line_id);
CREATE INDEX IF NOT EXISTS ix_inv_stock_balance_company_item_wh ON inv.stock_balance (company_id, item_id, warehouse_id);
CREATE INDEX IF NOT EXISTS ix_comm_documents_stock_document ON comm.commercial_documents (stock_document_id)
    WHERE stock_document_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_comm_document_lines_stock_line ON comm.commercial_document_lines (stock_document_line_id)
    WHERE stock_document_line_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_inv_serial_movements_serial ON inv.serial_movements (serial_id, moved_at);
