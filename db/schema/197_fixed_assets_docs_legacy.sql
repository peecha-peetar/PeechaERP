-- پیچا R265: نوعِ مدرکِ پیوست (فاکتور/گارانتی/قرارداد/...) + انتقالِ دارایی‌هایِ قبلی (inv.asset_details) -- فقط افزودنی.
ALTER TABLE doc.attachments ADD COLUMN IF NOT EXISTS document_type_code VARCHAR(20) NULL;

-- دارایی‌هایِ ثبت‌شده با روشِ قبلی (کالایِ نوعِ ASSET + inv.asset_details) کپی می‌شوند؛ جدول‌هایِ قبلی دست نمی‌خورند.
INSERT INTO fa.asset_books (company_id, code, name, is_primary, posts_to_gl, is_active)
SELECT DISTINCT i.company_id, 'ACC', 'دفترِ حسابداری', TRUE, TRUE, TRUE
FROM inv.asset_details ad JOIN inv.items i ON i.item_id = ad.item_id
WHERE NOT EXISTS (SELECT 1 FROM fa.asset_books b WHERE b.company_id = i.company_id AND b.is_primary);

INSERT INTO fa.asset_categories (company_id, code, name, default_method, default_residual_percent, cost_center_required, is_active)
SELECT DISTINCT i.company_id, 'LEGACY', 'دارایی‌هایِ قبلی', 'STRAIGHT_LINE', 0, FALSE, TRUE
FROM inv.asset_details ad JOIN inv.items i ON i.item_id = ad.item_id
ON CONFLICT (company_id, code) DO NOTHING;

INSERT INTO fa.assets (company_id, asset_code, name, category_id, asset_type_code, barcode, status_code, source_code,
                       acquisition_date, capitalization_date, in_service_date, depreciation_start_date, purchase_price,
                       residual_value, useful_life, useful_life_unit, depreciation_method, gross_cost, accumulated_depreciation,
                       depreciated_months_offset, legacy_item_id, notes)
SELECT i.company_id, LEFT('LEG-' || da.code, 40), COALESCE(da.name, da.code), cat.category_id, 'EQUIPMENT',
       COALESCE(ad.asset_tag_no, da.code),
       CASE WHEN COALESCE(dep.total, 0) >= ad.acquisition_cost - ad.salvage_value THEN 'FULLY_DEPRECIATED' ELSE 'IN_SERVICE' END,
       'LEGACY', ad.acquisition_date, ad.acquisition_date, ad.acquisition_date, ad.acquisition_date, ad.acquisition_cost,
       ad.salvage_value, ad.useful_life_months, 'MONTH',
       CASE WHEN ad.depreciation_method_code = 'DECLINING_BALANCE' THEN 'DECLINING_BALANCE' ELSE 'STRAIGHT_LINE' END,
       ad.acquisition_cost, COALESCE(dep.total, 0), COALESCE(dep.months, 0), ad.item_id,
       'منتقل‌شده از اطلاعاتِ داراییِ کالا (inv.asset_details)'
FROM inv.asset_details ad
JOIN inv.items i ON i.item_id = ad.item_id
JOIN acc.detail_accounts da ON da.detail_account_id = i.item_detail_account_id
JOIN fa.asset_categories cat ON cat.company_id = i.company_id AND cat.code = 'LEGACY'
LEFT JOIN (SELECT item_id, SUM(depreciation_amount) AS total, COUNT(*) AS months
           FROM inv.asset_depreciation_entries GROUP BY item_id) dep ON dep.item_id = ad.item_id
WHERE NOT EXISTS (SELECT 1 FROM fa.assets a WHERE a.legacy_item_id = ad.item_id)
ON CONFLICT (company_id, asset_code) DO NOTHING;

-- دفترِ دارایی: افتتاحیه (بها) + هر استهلاکِ قبلی با همان سندِ حسابداری
INSERT INTO fa.asset_transactions (company_id, asset_id, book_id, txn_type, txn_date, cost_delta, description, source_type, source_id)
SELECT a.company_id, a.asset_id, b.book_id, 'OPENING', COALESCE(a.acquisition_date, CURRENT_DATE), a.gross_cost,
       'افتتاحیهٔ داراییِ منتقل‌شده', 'LEGACY', a.legacy_item_id
FROM fa.assets a JOIN fa.asset_books b ON b.company_id = a.company_id AND b.is_primary
WHERE a.legacy_item_id IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM fa.asset_transactions t WHERE t.asset_id = a.asset_id AND t.txn_type = 'OPENING');

INSERT INTO fa.asset_transactions (company_id, asset_id, book_id, txn_type, txn_date, depreciation_delta, description,
                                   journal_entry_id, source_type, source_id)
SELECT a.company_id, a.asset_id, b.book_id, 'DEPRECIATION', e.period_date, e.depreciation_amount, 'استهلاکِ ثبت‌شده با روشِ قبلی',
       e.journal_entry_id, 'LEGACY_DEPR', e.depreciation_entry_id
FROM inv.asset_depreciation_entries e
JOIN fa.assets a ON a.legacy_item_id = e.item_id
JOIN fa.asset_books b ON b.company_id = a.company_id AND b.is_primary
WHERE NOT EXISTS (SELECT 1 FROM fa.asset_transactions t WHERE t.source_type = 'LEGACY_DEPR' AND t.source_id = e.depreciation_entry_id);
