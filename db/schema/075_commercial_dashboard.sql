-- پیچا | مدیریتِ بازرگانی — مرحلهٔ ۱۰: اسنپ‌شاتِ روزانهٔ KPIِ اجرایی.
-- هم‌الگو با inv.daily_kpi_snapshots: یک ردیفِ تجمیعیِ سراسری به‌ازایِ
-- هر شرکت/روز؛ شکافتنِ ابعادی (کانال/انبار/...) کارِ گزارشِ زنده است،
-- نه این جدول (مرحلهٔ ۱۰، بخشِ ۲).
-- پیش‌نیاز: 001_core_i18n_and_tenancy.sql

CREATE TABLE comm.daily_kpi_snapshots (
    snapshot_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    snapshot_date DATE NOT NULL,
    total_sales_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    total_purchase_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    total_orders_count INT NOT NULL DEFAULT 0,
    open_credit_holds_count INT NOT NULL DEFAULT 0,
    pos_cash_variance_total NUMERIC(18,2) NOT NULL DEFAULT 0,
    gift_card_liability_outstanding NUMERIC(18,2) NOT NULL DEFAULT 0,
    loyalty_wallet_liability_outstanding NUMERIC(18,2) NOT NULL DEFAULT 0,
    open_service_tickets_count INT NOT NULL DEFAULT 0,
    overdue_installment_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    CONSTRAINT uq_comm_daily_kpi_snapshots UNIQUE (company_id, snapshot_date)
);
