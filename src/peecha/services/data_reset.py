"""طبقِ درخواستِ صریح: امکانِ «خام‌کردنِ» اطلاعاتِ یک شرکت — بدونِ اثر
رویِ ساختارِ برنامه (schema/تنظیماتِ سراسری) — در سه دسته‌یِ کاملاً جدا:

    ۱) اسناد (وقتی سند حسابداری فروش ثبت میشه) — همه‌یِ اسنادِ فروش/خرید،
       انبار، و مالی/حسابداری با هم (چون به هم وصل‌اند، جداکردنشان
       پرخطر است — طبقِ توافقِ صریح).
    ۲) اطلاعاتِ پایه — حساب‌ها، کالاها، انبارها، مشتریان/تامین‌کنندگان و....
       (فقط وقتی هیچ سندی نمانده باشد).
    ۳) تنظیمات — نگاشتِ حساب‌ها، سطح‌بندیِ حساب/تفصیلی، شماره‌گذاریِ
       اسناد، Toggleهایِ ماژول و....

هرسه به company_id محدودند و هرگز رویِ core.companies/sec.users یا
جدول‌هایِ سراسری (مثلِ inv.feature_definitions/comm.industry_profiles که
تعریف‌هایِ مشترکِ بینِ همه‌یِ شرکت‌ها هستند) دست نمی‌زنند.

محدودیتِ آگاهانه: ماژول‌هایِ کمتر-رایجِ باقی‌مانده (POS/باشگاهِ مشتریان/
بازارهایِ آنلاین/ریبیتِ تامین‌کننده/شمارشِ چرخه‌ای/BOM/صورت‌حسابِ اشتراکی/
بهایِ تمام‌شدهٔ وارداتی/گردشِ کار) این‌جا پوشش داده نمی‌شوند -- گارانتی/
RMA/تیکتِ خدمات طبقِ رفعِ باگِ واقعی (که این محدودیت را عملاً مسدودکننده
می‌کرد) اضافه شدند. اگر داده‌ای در ماژول‌هایِ باقی‌مانده به همین اسناد
وابسته باشد، عملیات با خطایِ صریحِ دیتابیس (نه خرابیِ خاموش) متوقف
می‌شود و هیچ‌چیز حذف نمی‌شود (تراکنشِ واحد، همه‌یا-هیچ)."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from peecha.db.base import new_session

_FK_HINT = (
    "برخی اطلاعاتِ دیگر (احتمالاً از ماژولی مثلِ فروشگاه/باشگاهِ مشتریان/"
    "شمارشِ چرخه‌ای/بازارهایِ آنلاین که این ابزار پوشش نمی‌دهد) هنوز به این رکوردها "
    "وابسته‌اند — هیچ‌چیز حذف نشد. جزئیاتِ فنی: "
)


def _run_delete_sequence(company_id: int, statements: list[str]) -> None:
    with new_session() as session:
        try:
            for sql in statements:
                session.execute(text(sql), {"company_id": company_id})
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise ValueError(f"{_FK_HINT}{exc.orig}") from exc


# ---------------------------------------------------------------------
# ۱) اسناد — فروش/خرید + انبار + مالی/حسابداری، با هم، یک تراکنشِ واحد.
# ---------------------------------------------------------------------
_DOCUMENT_DELETE_STATEMENTS = [
    # طبقِ رفعِ باگِ واقعی («هنوز رکوردهایی به این وابسته‌اند -- invoice_
    # settlements»): تسویه‌یِ فاکتورها (comm.invoice_settlements) و
    # اقساط (comm.installment_plans/installment_lines) بعدِ ساختِ اولیه‌یِ
    # این ابزار اضافه شدند و مستقیم/غیرِمستقیم به commercial_documents و
    # journal_entries اشاره می‌کنند -- باید پیش از حذفِ خودِ آن‌ها (چه در
    # همین لیست، چه در acc.journal_entries که پایینِ همین لیست حذف
    # می‌شود) پاک شوند.
    "DELETE FROM comm.invoice_settlements WHERE company_id = :company_id",
    "DELETE FROM comm.installment_lines WHERE plan_id IN "
    "(SELECT plan_id FROM comm.installment_plans WHERE document_id IN "
    " (SELECT document_id FROM comm.commercial_documents WHERE company_id = :company_id))",
    "DELETE FROM comm.installment_plans WHERE document_id IN "
    "(SELECT document_id FROM comm.commercial_documents WHERE company_id = :company_id)",
    # فروش/خرید
    "DELETE FROM comm.credit_holds WHERE related_document_id IN "
    "(SELECT document_id FROM comm.commercial_documents WHERE company_id = :company_id)",
    # طبقِ رفعِ باگِ واقعی (گارانتی/RMA/تیکتِ خدمات -- «محدودیتِ آگاهانه‌»یِ
    # بالا حالا واقعاً کاربر را مسدود می‌کرد): این چهار جدول قبلاً جزوِ
    # همان ماژول‌هایِ کمتر-رایجِ پوشش‌نداده بودند، ولی چون به‌طورِ مستقیم
    # به commercial_document_lines/commercial_documents وصل‌اند، حالا
    # (به‌ترتیبِ وابستگی: rma_requests/service_ticket_parts_used قبل از
    # service_tickets، و service_tickets قبل از warranties، چون
    # service_tickets.warranty_id به warranties اشاره می‌کند) این‌جا هم
    # پاک می‌شوند.
    "DELETE FROM comm.rma_requests WHERE original_document_id IN "
    "(SELECT document_id FROM comm.commercial_documents WHERE company_id = :company_id) "
    "OR customer_detail_account_id IN (SELECT detail_account_id FROM acc.detail_accounts WHERE company_id = :company_id)",
    "DELETE FROM comm.service_ticket_parts_used WHERE ticket_id IN "
    "(SELECT ticket_id FROM comm.service_tickets WHERE customer_detail_account_id IN "
    " (SELECT detail_account_id FROM acc.detail_accounts WHERE company_id = :company_id))",
    "DELETE FROM comm.service_tickets WHERE customer_detail_account_id IN "
    "(SELECT detail_account_id FROM acc.detail_accounts WHERE company_id = :company_id)",
    "DELETE FROM comm.warranties WHERE sales_document_line_id IN "
    "(SELECT cdl.line_id FROM comm.commercial_document_lines cdl "
    " JOIN comm.commercial_documents cd ON cd.document_id = cdl.document_id WHERE cd.company_id = :company_id)",
    "DELETE FROM comm.commission_entries WHERE document_line_id IN "
    "(SELECT cdl.line_id FROM comm.commercial_document_lines cdl "
    " JOIN comm.commercial_documents cd ON cd.document_id = cdl.document_id WHERE cd.company_id = :company_id)",
    "DELETE FROM comm.commercial_document_lines WHERE document_id IN "
    "(SELECT document_id FROM comm.commercial_documents WHERE company_id = :company_id)",
    "DELETE FROM comm.commercial_documents WHERE company_id = :company_id",
    # خزانه‌داری/تنخواه (این‌ها هم سند‌اند، چون هرکدام یک سندِ حسابداریِ
    # خودشان را دارند و می‌توانند به سندهایِ انبار/فروش اشاره کنند).
    "DELETE FROM treasury.check_stage_events WHERE company_id = :company_id",
    "DELETE FROM treasury.received_checks WHERE company_id = :company_id",
    "DELETE FROM treasury.issued_checks WHERE company_id = :company_id",
    "DELETE FROM treasury.petty_cash_fund_extra_details WHERE fund_id IN "
    "(SELECT fund_id FROM treasury.petty_cash_funds WHERE company_id = :company_id)",
    "DELETE FROM treasury.petty_cash_fund_lines WHERE fund_id IN "
    "(SELECT fund_id FROM treasury.petty_cash_funds WHERE company_id = :company_id)",
    "DELETE FROM treasury.petty_cash_funds WHERE company_id = :company_id",
    # انبار
    "DELETE FROM inv.cost_layers WHERE stock_ledger_id IN "
    "(SELECT ledger_id FROM inv.stock_ledger WHERE company_id = :company_id)",
    # طبقِ تصمیمِ آگاهانه‌یِ همین طراحی، inv.stock_ledger عمداً
    # تغییرناپذیر است (تریگرِ tr_inv_stock_ledger_immutable هر
    # UPDATE/DELETE را رد می‌کند — دقیقاً مثلِ اصلِ «دفترِ روزنامهٔ
    # غیرِقابلِ‌تغییر» در حسابداریِ واقعی). این ابزار — طبقِ درخواستِ
    # صریح، فقط برایِ استفاده‌یِ داخلی/محدود، نه یک ویژگیِ عمومی —
    # همان تریگر را فقط برایِ لحظه‌یِ همینِ عملیات، داخلِ همین تراکنش،
    # غیرِفعال می‌کند؛ اگر جایی از عملیات با خطا مواجه شود، کلِ
    # تراکنش (شاملِ همین غیرِفعال‌سازی) برمی‌گردد و تغییرناپذیریِ
    # دفترِ موجودی خودکار دوباره برقرار می‌ماند.
    "ALTER TABLE inv.stock_ledger DISABLE TRIGGER tr_inv_stock_ledger_immutable",
    "DELETE FROM inv.stock_ledger WHERE company_id = :company_id",
    "ALTER TABLE inv.stock_ledger ENABLE TRIGGER tr_inv_stock_ledger_immutable",
    "DELETE FROM inv.stock_document_lines WHERE stock_document_id IN "
    "(SELECT stock_document_id FROM inv.stock_documents WHERE company_id = :company_id)",
    "DELETE FROM inv.stock_documents WHERE company_id = :company_id",
    "DELETE FROM inv.stock_reservations WHERE company_id = :company_id",
    "DELETE FROM inv.stock_balance WHERE company_id = :company_id",
    # حسابداری
    "DELETE FROM acc.journal_entry_line_details WHERE line_id IN "
    "(SELECT jel.line_id FROM acc.journal_entry_lines jel "
    " JOIN acc.journal_entries je ON je.journal_entry_id = jel.journal_entry_id WHERE je.company_id = :company_id)",
    "DELETE FROM acc.journal_entry_lines WHERE journal_entry_id IN "
    "(SELECT journal_entry_id FROM acc.journal_entries WHERE company_id = :company_id)",
    "DELETE FROM acc.journal_entries WHERE company_id = :company_id",
]


def wipe_documents(company_id: int) -> None:
    """همه‌یِ اسنادِ فروش/خرید، انبار، و مالی/حسابداریِ یک شرکت را حذف
    می‌کند — یک تراکنشِ واحد، همه‌یا-هیچ. اطلاعاتِ پایه و تنظیمات
    دست‌نخورده می‌مانند."""
    _run_delete_sequence(company_id, _DOCUMENT_DELETE_STATEMENTS)


# ---------------------------------------------------------------------
# ۲) اطلاعاتِ پایه — فقط وقتی هیچ سندی نمانده باشد (وگرنه FK رد می‌کند).
# ---------------------------------------------------------------------
_MASTER_DATA_DELETE_STATEMENTS = [
    # اشخاص (تفصیلیِ مشتری/تامین‌کننده/پرسنل + گروه‌ها).
    "DELETE FROM comm.party_contacts WHERE party_detail_account_id IN "
    "(SELECT detail_account_id FROM acc.detail_accounts WHERE company_id = :company_id)",
    "DELETE FROM comm.party_addresses WHERE party_detail_account_id IN "
    "(SELECT detail_account_id FROM acc.detail_accounts WHERE company_id = :company_id)",
    "DELETE FROM comm.sales_representatives WHERE rep_detail_account_id IN "
    "(SELECT detail_account_id FROM acc.detail_accounts WHERE company_id = :company_id)",
    "DELETE FROM comm.customer_profiles WHERE company_id = :company_id",
    "DELETE FROM comm.supplier_profiles WHERE company_id = :company_id",
    "DELETE FROM comm.customer_groups WHERE company_id = :company_id",
    "DELETE FROM comm.supplier_groups WHERE company_id = :company_id",
    "DELETE FROM acc.customer_details WHERE detail_account_id IN "
    "(SELECT detail_account_id FROM acc.detail_accounts WHERE company_id = :company_id)",
    "DELETE FROM acc.supplier_details WHERE detail_account_id IN "
    "(SELECT detail_account_id FROM acc.detail_accounts WHERE company_id = :company_id)",
    "DELETE FROM acc.personnel_details WHERE detail_account_id IN "
    "(SELECT detail_account_id FROM acc.detail_accounts WHERE company_id = :company_id)",
    # قیمت‌گذاری/کانال.
    "DELETE FROM comm.price_list_items WHERE price_list_id IN "
    "(SELECT price_list_id FROM comm.price_lists WHERE company_id = :company_id)",
    "DELETE FROM comm.price_lists WHERE company_id = :company_id",
    "DELETE FROM comm.channels WHERE company_id = :company_id",
    "DELETE FROM comm.discount_rule_tiers WHERE rule_id IN "
    "(SELECT rule_id FROM comm.discount_rules WHERE company_id = :company_id)",
    "DELETE FROM comm.discount_rules WHERE company_id = :company_id",
    "DELETE FROM comm.promotions WHERE company_id = :company_id",
    "DELETE FROM comm.coupons WHERE company_id = :company_id",
    "DELETE FROM comm.commission_rules WHERE company_id = :company_id",
    # خزانه‌داری (بانک/دسته‌چک/روش‌هایِ سفارشی).
    "DELETE FROM treasury.checkbooks WHERE company_id = :company_id",
    "DELETE FROM treasury.banks WHERE company_id = :company_id",
    "DELETE FROM treasury.custom_methods WHERE company_id = :company_id",
    # کالا.
    "DELETE FROM inv.item_suppliers WHERE item_id IN (SELECT item_id FROM inv.items WHERE company_id = :company_id)",
    "DELETE FROM inv.item_media WHERE item_id IN (SELECT item_id FROM inv.items WHERE company_id = :company_id)",
    "DELETE FROM inv.item_variant_values WHERE item_id IN (SELECT item_id FROM inv.items WHERE company_id = :company_id)",
    "DELETE FROM inv.item_attribute_values WHERE attribute_id IN "
    "(SELECT attribute_id FROM inv.item_attributes WHERE company_id = :company_id)",
    "DELETE FROM inv.related_items WHERE item_id IN (SELECT item_id FROM inv.items WHERE company_id = :company_id) "
    "OR related_item_id IN (SELECT item_id FROM inv.items WHERE company_id = :company_id)",
    "DELETE FROM inv.item_uom_conversions WHERE item_id IN (SELECT item_id FROM inv.items WHERE company_id = :company_id)",
    "DELETE FROM inv.bom_lines WHERE bom_id IN "
    "(SELECT bom_id FROM inv.bom_headers WHERE finished_item_id IN (SELECT item_id FROM inv.items WHERE company_id = :company_id)) "
    "OR component_item_id IN (SELECT item_id FROM inv.items WHERE company_id = :company_id)",
    "DELETE FROM inv.bom_headers WHERE finished_item_id IN (SELECT item_id FROM inv.items WHERE company_id = :company_id)",
    "DELETE FROM inv.standard_costs WHERE item_id IN (SELECT item_id FROM inv.items WHERE company_id = :company_id)",
    "DELETE FROM inv.items WHERE company_id = :company_id",
    "DELETE FROM inv.item_attributes WHERE company_id = :company_id",
    "DELETE FROM inv.category_account_mappings WHERE category_id IN "
    "(SELECT category_id FROM inv.item_categories WHERE company_id = :company_id)",
    "DELETE FROM inv.item_categories WHERE company_id = :company_id",
    "DELETE FROM inv.brands WHERE company_id = :company_id",
    "DELETE FROM inv.manufacturers WHERE company_id = :company_id",
    "DELETE FROM inv.uom WHERE company_id = :company_id",
    "DELETE FROM inv.document_reason_codes WHERE company_id = :company_id",
    # انبار.
    "DELETE FROM inv.warehouse_user_access WHERE warehouse_id IN "
    "(SELECT warehouse_id FROM inv.warehouses WHERE company_id = :company_id)",
    "DELETE FROM inv.bin_locations WHERE warehouse_id IN "
    "(SELECT warehouse_id FROM inv.warehouses WHERE company_id = :company_id)",
    "DELETE FROM inv.warehouse_account_mappings WHERE warehouse_id IN "
    "(SELECT warehouse_id FROM inv.warehouses WHERE company_id = :company_id)",
    "DELETE FROM inv.warehouses WHERE company_id = :company_id",
    # حساب‌ها (آخر از همه — چون بالا همه به این‌جا وصل بودند).
    "DELETE FROM acc.account_detail_dimensions WHERE account_id IN "
    "(SELECT account_id FROM acc.chart_of_accounts WHERE company_id = :company_id)",
    "DELETE FROM acc.detail_accounts WHERE company_id = :company_id",
    # گروه‌هایِ اشخاص -- بعد از detail_accounts، چون خودِ detail_accounts
    # به این‌جا اشاره می‌کند (person_group_id)، نه برعکس.
    "DELETE FROM acc.account_person_groups WHERE person_group_id IN "
    "(SELECT person_group_id FROM acc.person_groups WHERE company_id = :company_id)",
    "DELETE FROM acc.person_groups WHERE company_id = :company_id",
    # سطح‌بندیِ نمایشِ گروه‌هایِ تفصیلی -- هرچند «تنظیمات» محسوب می‌شود،
    # چون به‌طورِ مستقیم به detail_dimension_types وصل است، این‌جا هم
    # (بدونِ نیاز به خام‌کردنِ جداگانه‌یِ تنظیمات) پاک می‌شود.
    "DELETE FROM acc.detail_group_fields WHERE dimension_type_id IN "
    "(SELECT dimension_type_id FROM acc.detail_dimension_types WHERE company_id = :company_id)",
    "DELETE FROM acc.detail_group_levels WHERE dimension_type_id IN "
    "(SELECT dimension_type_id FROM acc.detail_dimension_types WHERE company_id = :company_id)",
    "DELETE FROM acc.detail_dimension_types WHERE company_id = :company_id",
    # نگاشتِ حساب‌ها -- هرچند «تنظیمات» محسوب می‌شود، چون به حساب‌ها وصل
    # است، این‌جا هم (بدونِ نیاز به خام‌کردنِ جداگانه‌یِ تنظیمات) پاک می‌شود.
    "DELETE FROM inv.account_mappings WHERE company_id = :company_id",
    "DELETE FROM comm.account_mappings WHERE company_id = :company_id",
    "DELETE FROM treasury.account_mappings WHERE company_id = :company_id",
    "DELETE FROM treasury.counterparty_account_mappings WHERE company_id = :company_id",
    "DELETE FROM acc.chart_of_accounts WHERE company_id = :company_id",
]


def wipe_master_data(company_id: int) -> None:
    """اطلاعاتِ پایه (حساب‌ها، کالاها، انبارها، مشتریان/تامین‌کنندگان و...)
    را حذف می‌کند. طبقِ درخواستِ صریح، این کار فقط وقتی مجاز است که
    هیچ سندی برایِ این شرکت نمانده باشد — وگرنه با پیامِ روشن رد
    می‌شود (نه با خطایِ خامِ دیتابیس)."""
    with new_session() as session:
        remaining = session.execute(
            text(
                "SELECT "
                "(SELECT count(*) FROM comm.commercial_documents WHERE company_id = :company_id) + "
                "(SELECT count(*) FROM inv.stock_documents WHERE company_id = :company_id) + "
                "(SELECT count(*) FROM acc.journal_entries WHERE company_id = :company_id)"
            ),
            {"company_id": company_id},
        ).scalar_one()
    if remaining:
        raise ValueError("ابتدا باید همه‌یِ اسناد (فروش/خرید، انبار، مالی) پاک شوند — اطلاعاتِ پایه هنوز به آن‌ها وصل است.")
    _run_delete_sequence(company_id, _MASTER_DATA_DELETE_STATEMENTS)


# ---------------------------------------------------------------------
# ۳) تنظیمات — نگاشتِ حساب‌ها، سطح‌بندی، شماره‌گذاری، Toggleهایِ ماژول.
# ---------------------------------------------------------------------
_SETTINGS_DELETE_STATEMENTS = [
    "DELETE FROM acc.statement_row_refs WHERE row_id IN "
    "(SELECT sr.row_id FROM acc.statement_rows sr JOIN acc.statement_templates st ON st.template_id = sr.template_id WHERE st.company_id = :company_id)",
    "DELETE FROM acc.statement_row_accounts WHERE row_id IN "
    "(SELECT sr.row_id FROM acc.statement_rows sr JOIN acc.statement_templates st ON st.template_id = sr.template_id WHERE st.company_id = :company_id)",
    "DELETE FROM acc.statement_rows WHERE template_id IN (SELECT template_id FROM acc.statement_templates WHERE company_id = :company_id)",
    "DELETE FROM acc.statement_templates WHERE company_id = :company_id",
    "DELETE FROM acc.detail_group_fields WHERE dimension_type_id IN "
    "(SELECT dimension_type_id FROM acc.detail_dimension_types WHERE company_id = :company_id)",
    "DELETE FROM acc.detail_group_levels WHERE dimension_type_id IN "
    "(SELECT dimension_type_id FROM acc.detail_dimension_types WHERE company_id = :company_id)",
    "DELETE FROM acc.detail_level_digit_config WHERE company_id = :company_id",
    "DELETE FROM acc.chart_of_account_level_config WHERE company_id = :company_id",
    "DELETE FROM acc.company_accounting_settings WHERE company_id = :company_id",
    "DELETE FROM inv.account_mappings WHERE company_id = :company_id",
    "DELETE FROM inv.category_account_mappings WHERE category_id IN "
    "(SELECT category_id FROM inv.item_categories WHERE company_id = :company_id)",
    "DELETE FROM inv.warehouse_account_mappings WHERE warehouse_id IN "
    "(SELECT warehouse_id FROM inv.warehouses WHERE company_id = :company_id)",
    "DELETE FROM inv.company_costing_settings WHERE company_id = :company_id",
    "DELETE FROM inv.company_features WHERE company_id = :company_id",
    "DELETE FROM inv.reorder_policies WHERE company_id = :company_id",
    "DELETE FROM comm.account_mappings WHERE company_id = :company_id",
    "DELETE FROM comm.company_features WHERE company_id = :company_id",
    "DELETE FROM comm.document_numbering_sequences WHERE company_id = :company_id",
    "DELETE FROM treasury.account_mappings WHERE company_id = :company_id",
    "DELETE FROM treasury.counterparty_account_mappings WHERE company_id = :company_id",
    "DELETE FROM treasury.description_templates WHERE company_id = :company_id",
    # طبقِ همان رفعِ باگ: تنظیماتِ آلارمِ موعدِ تسویه هم بعدِ ساختِ اولیه‌یِ
    # این ابزار اضافه شد.
    "DELETE FROM comm.settlement_alarm_settings WHERE company_id = :company_id",
]


def wipe_settings(company_id: int) -> None:
    """تنظیماتِ شرکت (نگاشتِ حساب‌ها، سطح‌بندیِ حساب/تفصیلی، شماره‌گذاریِ
    اسناد، Toggleهایِ ماژول) را حذف می‌کند — به تعریف‌هایِ سراسری/مشترکِ
    بینِ همه‌یِ شرکت‌ها (مثلِ فهرستِ ویژگی‌هایِ قابلِ‌فعال‌سازی) دست
    نمی‌زند، فقط انتخاب/مقدارِ همین شرکت را."""
    _run_delete_sequence(company_id, _SETTINGS_DELETE_STATEMENTS)
