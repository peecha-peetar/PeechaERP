-- پیچا | مدیریتِ بازرگانی — مرحلهٔ ۲: اسکلتِ یکپارچهٔ سند.
-- طبقِ سندِ معماریِ ۱۱مرحله‌ای: خرید و فروش (سفارش/فاکتور/برگشت، هردو جهت)
-- یک اسکلتِ سرِسند+ردیفِ واحد دارند، متمایزشده با document_type_code —
-- دقیقاً هم‌الگو با inv.stock_documents.
-- پیش‌نیاز: 001_core_i18n_and_tenancy.sql، 003_accounting_core.sql،
-- 057_inventory_catalog.sql، 058_inventory_locations.sql،
-- 059_inventory_engine_documents.sql، 065_commercial_pricing_channels.sql،
-- 066_commercial_pos_sessions.sql

CREATE TABLE comm.commercial_documents (
    document_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    fiscal_year_id INT NOT NULL REFERENCES acc.fiscal_years(fiscal_year_id),
    document_type_code VARCHAR(20) NOT NULL
        CHECK (document_type_code IN (
            'SALES_ORDER', 'SALES_INVOICE', 'SALES_RETURN',
            'PURCHASE_ORDER', 'PURCHASE_INVOICE', 'PURCHASE_RETURN'
        )),
    document_no INT NOT NULL,
    document_date DATE NOT NULL,
    -- برایِ نوعِ ORDER: POSTED یعنی «قفل و ارسال‌شده»، نه ثبتِ مالی —
    -- سفارش هرگز stock_document_id/journal_entry_id پر نمی‌کند (طبقِ
    -- مرحلهٔ ۴، بخشِ ۲). فقط فاکتور/برگشت این دو ستون را پر می‌کنند.
    status_code VARCHAR(15) NOT NULL DEFAULT 'DRAFT'
        CHECK (status_code IN ('DRAFT', 'CONFIRMED', 'APPROVED', 'POSTED', 'CANCELLED')),
    channel_code VARCHAR(20) NULL,
    counterparty_detail_account_id INT NOT NULL REFERENCES acc.detail_accounts(detail_account_id),
    warehouse_id INT NULL REFERENCES inv.warehouses(warehouse_id),
    price_list_id INT NULL REFERENCES comm.price_lists(price_list_id),
    -- خودارجاع: زنجیرهٔ سفارش→فاکتور→برگشت، بدونِ جدولِ واسط.
    source_document_id BIGINT NULL REFERENCES comm.commercial_documents(document_id),
    -- تعویض: SALES_RETURN به فاکتورِ جایگزین اشاره می‌کند (مرحلهٔ ۷، بخشِ ۴).
    linked_exchange_document_id BIGINT NULL REFERENCES comm.commercial_documents(document_id),
    pos_session_id BIGINT NULL REFERENCES comm.pos_sessions(session_id),
    currency_id INT NOT NULL REFERENCES core.currencies(currency_id),
    exchange_rate NUMERIC(18,6) NOT NULL DEFAULT 1,
    -- فقط برایِ PURCHASE_ORDER/SALES_ORDER — ورودیِ گزارشِ تحویلِ به‌موقع.
    requested_delivery_date DATE NULL,
    -- sales_rep_detail_account_id: رویِ اسنادِ فروش «فروشندهٔ ثبت‌کننده»،
    -- رویِ اسنادِ خرید «خریدارِ مسئول» — همان ستون، معنایِ وابسته‌به‌جهت
    -- (مرحلهٔ ۴، بخشِ ۴).
    sales_rep_detail_account_id INT NULL REFERENCES acc.detail_accounts(detail_account_id),
    cost_center_detail_account_id INT NULL REFERENCES acc.detail_accounts(detail_account_id),
    project_detail_account_id INT NULL REFERENCES acc.detail_accounts(detail_account_id),
    reference_no VARCHAR(50) NULL,
    description TEXT NULL,
    subtotal_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    discount_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    tax_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    shipping_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    total_amount NUMERIC(18,2) GENERATED ALWAYS AS
        (subtotal_amount - discount_amount + tax_amount + shipping_amount) STORED,
    -- پرشده فقط پسِ Postِ SALES_INVOICE/SALES_RETURN/PURCHASE_INVOICE/
    -- PURCHASE_RETURN — یک-به-یک با inv.stock_documents/acc.journal_entries.
    stock_document_id BIGINT NULL REFERENCES inv.stock_documents(stock_document_id),
    journal_entry_id INT NULL REFERENCES acc.journal_entries(journal_entry_id),
    created_by_user_id INT NOT NULL REFERENCES sec.users(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    posted_by_user_id INT NULL REFERENCES sec.users(user_id),
    posted_at TIMESTAMPTZ NULL,
    CONSTRAINT uq_comm_documents_number
        UNIQUE (company_id, fiscal_year_id, document_type_code, document_no),
    CONSTRAINT fk_comm_documents_channel
        FOREIGN KEY (company_id, channel_code) REFERENCES comm.channels(company_id, channel_code)
);

CREATE TABLE comm.commercial_document_lines (
    line_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES comm.commercial_documents(document_id),
    line_no SMALLINT NOT NULL,
    item_id INT NOT NULL REFERENCES inv.items(item_id),
    uom_id INT NOT NULL REFERENCES inv.uom(uom_id),
    quantity NUMERIC(18,6) NOT NULL CHECK (quantity > 0),
    quantity_base NUMERIC(18,6) NOT NULL CHECK (quantity_base > 0),
    unit_price NUMERIC(18,6) NOT NULL,
    discount_percent NUMERIC(5,2) NOT NULL DEFAULT 0,
    discount_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    tax_percent NUMERIC(5,2) NOT NULL DEFAULT 0,
    tax_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    line_total NUMERIC(18,2) GENERATED ALWAYS AS
        (ROUND(quantity * unit_price - discount_amount + tax_amount, 2)) STORED,
    batch_id INT NULL REFERENCES inv.batches(batch_id),
    serial_id INT NULL REFERENCES inv.serial_numbers(serial_id),
    -- خودارجاع: ردیفِ برگشت به ردیفِ فاکتورِ اصلی اشاره می‌کند.
    source_line_id BIGINT NULL REFERENCES comm.commercial_document_lines(line_id),
    stock_document_line_id BIGINT NULL REFERENCES inv.stock_document_lines(line_id),
    -- فقط برایِ ردیفِ SALES_ORDERِ تاییدشده (مرحلهٔ ۵، بخشِ ۴).
    reservation_id BIGINT NULL REFERENCES inv.stock_reservations(reservation_id),
    -- فقط برایِ ردیفِ سفارش: با هر فاکتورِ فرزندِ Postشده به‌روزرسانی
    -- می‌شود — هم‌الگو با commercial_contracts.consumed_quantity.
    received_quantity_total NUMERIC(18,6) NOT NULL DEFAULT 0,
    invoiced_quantity_total NUMERIC(18,6) NOT NULL DEFAULT 0,
    -- خودارجاع: ردیفِ جزءِ یک ست به ردیفِ ستِ والد اشاره می‌کند
    -- (مرحلهٔ ۵، بخشِ ۴) — فقط از طریقِ ویرایشِ ردیفِ والد تغییرپذیر.
    bundle_parent_line_id BIGINT NULL REFERENCES comm.commercial_document_lines(line_id),
    promotion_id INT NULL REFERENCES comm.promotions(promotion_id),
    coupon_id INT NULL REFERENCES comm.coupons(coupon_id),
    description VARCHAR(500) NULL,
    CONSTRAINT uq_comm_document_lines UNIQUE (document_id, line_no)
);
