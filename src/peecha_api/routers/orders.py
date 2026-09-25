"""ثبتِ سفارش/فاکتور از موبایل -- روی همان services/commercial_documents.py
موجود سوار می‌شود، بدونِ بازنویسیِ منطقِ قیمت‌گذاری/تخفیف/مالیات. طبقِ
تفاوتِ دو ماژول: پخشِ سرد (SALES_ORDER) فقط سفارش می‌سازد و همان‌جا
متوقف می‌شود (تبدیل به فاکتور بعداً در خودِ ERP)؛ پخشِ گرم (SALES_INVOICE
با post_immediately=True) بلافاصله تاییدوپست می‌شود چون کالا همان‌لحظه
از خودرو تحویل داده شده."""

from __future__ import annotations

import datetime
import decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.core import Company
from peecha.db.models.security import User
from peecha.db.models.treasury import ReceivedCheck

from peecha.services import commercial_documents as documents_service
from peecha.services import commercial_pos as pos_service
from peecha.services import commercial_pricing as pricing_service
from peecha.services import commercial_settlements as settlements_service
from peecha.services import currencies as currencies_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import inventory_catalog as catalog_service
from peecha.services import inventory_locations as locations_service
from peecha.services import roles as roles_service
from peecha.services import treasury as treasury_service
from peecha_api import audit_log
from peecha_api.deps import AuthContext, get_current_context, get_idempotency_key
from peecha_api.idempotency import IdempotentReplay, run_idempotent
from peecha_api.permissions import FORM_COLD_DISTRIBUTION, FORM_HOT_DISTRIBUTION
from peecha_api.schemas import OrderCreateRequest, OrderSettlementLineRequest

router = APIRouter(prefix="/orders", tags=["orders"])

# طبقِ nav_catalog.py: پخشِ سرد (سفارش‌گیریِ SALES_ORDER) و پخشِ گرم
# (فاکتورِ آنیِ SALES_INVOICE) دو فرمِ RBACِ جداگانه‌یِ از قبل تعریف‌شده
# دارند -- هرکدام طبقِ نوعِ سندِ درخواستی چک می‌شوند.
_FORM_BY_TYPE = {"SALES_ORDER": FORM_COLD_DISTRIBUTION, "SALES_INVOICE": FORM_HOT_DISTRIBUTION}


@router.post("")
def create_order(
    payload: OrderCreateRequest,
    ctx: AuthContext = Depends(get_current_context),
    idempotency_key: str | None = Depends(get_idempotency_key),
) -> dict:
    if payload.document_type_code not in _FORM_BY_TYPE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="نوعِ سند برایِ اپِ موبایل فقط سفارش یا فاکتورِ فروش می‌تواند باشد.")
    if not payload.lines:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="حداقل یک ردیف لازم است.")
    form_code = _FORM_BY_TYPE[payload.document_type_code]
    if not roles_service.user_has_permission(ctx.user_id, ctx.company_id, form_code, "CREATE"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"دسترسیِ ثبتِ {form_code} وجود ندارد.")

    try:
        return run_idempotent(
            idempotency_key, "POST /orders", ctx.user_id, ctx.company_id,
            status.HTTP_200_OK, lambda: _create_order(payload, ctx),
            lambda result: {
                "document_id": result[0], "line_ids": result[1], "document_no": result[2],
                "settlement_warning": result[3],
            },
        )
    except IdempotentReplay as replay:
        return replay.body
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _validate_settlement_lines(company_id: int, lines: list[OrderSettlementLineRequest]) -> None:
    """فقط خطاهایِ «شکلِ داده» (که فرمِ موبایل خودش از آن‌ها جلوگیری
    می‌کند) این‌جا رد می‌شوند. کمبودِ تنظیماتِ خزانه‌داری (نگاشتِ حساب/
    صندوقِ پیش‌فرض) عمداً رد نمی‌شود: فاکتورِ پخشِ گرم از صفِ آفلاین
    می‌آید و ۴۰۰ یعنی حذفِ همیشگیِ آن از صف -- یعنی فروشی که واقعاً
    انجام شده از سیستم گم می‌شود. آن حالت در مرحلهٔ ساختِ سندِ دریافت به
    هشدار (فاکتورِ نسیه) تبدیل می‌شود."""
    enabled_codes = settlements_service.list_enabled_mobile_settlement_method_codes(company_id)
    labels = {m.method_code: m.label for m in settlements_service.list_mobile_settlement_methods(company_id)}
    for line in lines:
        label = labels.get(line.method_code, line.method_code)
        if line.method_code not in enabled_codes:
            raise ValueError(f"روشِ تسویهٔ «{line.method_code}» برایِ موبایل فعال نیست.")
        if line.amount <= 0:
            raise ValueError(f"مبلغِ روشِ «{label}» باید مثبت باشد.")
        if line.detail_account_id is not None:
            _requires, options = settlements_service.mobile_method_detail_options(company_id, line.method_code)
            if line.detail_account_id not in {o.detail_account_id for o in options}:
                raise ValueError(f"صندوق/حسابِ انتخاب‌شده برایِ روشِ «{label}» معتبر نیست.")
        if line.method_code == "CHECK":
            if not line.checks:
                raise ValueError("برایِ روشِ چک، مشخصاتِ حداقل یک چک لازم است.")
            for check in line.checks:
                if not check.check_no.strip():
                    raise ValueError("شماره‌یِ چک الزامی است.")
                if check.amount <= 0:
                    raise ValueError("مبلغِ هر چک باید مثبت باشد.")
            if sum((c.amount for c in line.checks), decimal.Decimal(0)) != line.amount:
                raise ValueError("جمعِ مبلغِ چک‌ها با مبلغِ ردیفِ چک برابر نیست.")
        elif line.checks:
            raise ValueError("مشخصاتِ چک فقط برایِ روشِ چک معنا دارد.")


def _settlement_extras(company_id: int, line: OrderSettlementLineRequest) -> dict:
    if line.method_code != "CHECK" or not line.checks:
        return {}
    bank_names = {b.bank_id: b.name for b in treasury_service.list_banks(company_id)}
    return {
        "checks": [
            {
                "check_no": c.check_no.strip(), "check_serial": c.check_serial, "bank_id": c.bank_id,
                "check_bank_name": c.check_bank_name or bank_names.get(c.bank_id), "iban": c.iban,
                "bank_account_no": c.bank_account_no, "due_date": c.due_date, "party_name": c.party_name,
                "national_id": c.national_id, "phone": c.phone, "amount": c.amount,
            }
            for c in line.checks
        ],
    }


def _create_order(payload: OrderCreateRequest, ctx: AuthContext) -> tuple[int, list[int], int, str | None]:
    # طبقِ باگِ واقعیِ کشف‌شده رویِ گوشیِ فیزیکیِ کاربر (R196، R198): مقادیرِ
    # warehouse_id/channel_code/currency_id که برایِ این شرکتِ خاص معتبر
    # نباشند، بدونِ این چک مستقیم به یک ForeignKeyViolationِ خامِ
    # SQLAlchemy می‌رسیدند (خطایِ ۵۰۰ِ بی‌پیام) -- که در SyncEngineِ
    # موبایل (فقط ۴xx حذف‌شدنی از صف است) کلِ صفِ آفلاین را برایِ همیشه
    # قفل می‌کرد، چون این اقدام هیچ‌وقت با تلاشِ دوباره موفق نمی‌شود.
    if locations_service.get_warehouse(payload.warehouse_id, ctx.company_id) is None:
        raise ValueError("انبارِ انتخاب‌شده برایِ این شرکت معتبر نیست.")
    if not any(ch.channel_code == payload.channel_code for ch in pricing_service.list_channels(ctx.company_id)):
        raise ValueError("کانالِ فروشِ انتخاب‌شده برایِ این شرکت معتبر نیست.")
    if not any(c.currency_id == payload.currency_id for c in currencies_service.list_all_currencies()):
        raise ValueError("ارزِ انتخاب‌شده معتبر نیست.")
    if payload.document_type_code == "SALES_INVOICE" and payload.post_immediately and payload.settlement_lines:
        _validate_settlement_lines(ctx.company_id, payload.settlement_lines)

    document_id = documents_service.create_document(
        ctx.company_id, ctx.user_id, payload.document_type_code, datetime.date.today(),
        documents_service.DocumentHeaderFields(
            counterparty_detail_account_id=payload.counterparty_detail_account_id,
            currency_id=payload.currency_id, warehouse_id=payload.warehouse_id, channel_code=payload.channel_code,
            cost_center_detail_account_id=payload.cost_center_detail_account_id,
            project_detail_account_id=payload.project_detail_account_id,
        ),
    )
    # line_ids دقیقاً هم‌ترتیب با payload.lines برگردانده می‌شود -- طبقِ
    # نیازِ R133: اپِ موبایل برایِ تاییدِ تحویلِ همین سفارش (پخشِ گرم) به
    # document_line_id هر ردیف نیاز دارد که فقط بعدِ همین ثبت مشخص می‌شود.
    line_ids: list[int] = []
    for line in payload.lines:
        # طبقِ باگِ واقعیِ کشف‌شده (R210): این حلقه قبلاً نه تخفیف و نه
        # مالیات را به add_line می‌داد -- پس فاکتورهایِ پخشِ گرم/سردِ موبایل
        # همیشه با تخفیفِ صفر و مالیاتِ صفر ثبت می‌شدند، صرف‌نظر از قانونِ
        # تخفیفِ فعال یا درصدِ مالیاتِ تعریف‌شده برایِ کالا/انبار/شرکت.
        # تخفیف را خودِ کلاینت (از GET /pricing/resolve) می‌فرستد؛ مالیات
        # را -- دقیقاً هم‌الگو با دسکتاپ -- سرور خودش با همان اولویتِ
        # شرکت→انبار→کالا تعیین می‌کند، نه کلاینت.
        tax_percent = catalog_service.resolve_default_tax_percent(ctx.company_id, line.item_id, payload.warehouse_id)
        line_ids.append(
            documents_service.add_line(
                document_id, ctx.company_id, item_id=line.item_id, uom_id=line.uom_id,
                quantity=line.quantity, quantity_base=line.quantity, unit_price=line.unit_price,
                discount_amount=line.discount_amount, tax_percent=tax_percent,
            )
        )
    documents_service.confirm_document(document_id, ctx.company_id, ctx.user_id)
    settlement_warning: str | None = None
    if payload.document_type_code == "SALES_INVOICE" and payload.post_immediately:
        # طبقِ درخواستِ صریحِ کاربر («نوعِ تسویه در پخشِ گرم باید همانندِ
        # انواعِ تسویه در دسکتاپ باشد»): ویزیتور روشِ واقعیِ دریافت (نقد/
        # بانکی/چک/... -- هرچه مدیر برایِ موبایل فعال کرده باشد) و مبلغِ
        # هر روش را انتخاب می‌کند؛ مانده‌یِ پوشش‌داده‌نشده خودکار نسیه
        # می‌شود (save_settlement_plan). None یعنی موبایلِ آپدیت‌نشده
        # (سازگاریِ عقب‌رو با رفتارِ قبلی: ۱۰۰٪ نقدی).
        if payload.settlement_lines is None:
            settlements_service.auto_approve_full_cash_settlement_plan(document_id, ctx.company_id, ctx.user_id)
        else:
            settlement_lines = [
                (line.method_code, line.amount, line.note, line.detail_account_id, _settlement_extras(ctx.company_id, line))
                for line in payload.settlement_lines
            ]
            settlements_service.auto_approve_settlement_plan(document_id, ctx.company_id, ctx.user_id, settlement_lines)
        documents_service.post_document(document_id, ctx.company_id, ctx.user_id)
        # طبقِ رفعِ کمبودِ واقعی: قبلاً فقط «نقشه‌یِ» تسویه ذخیره می‌شد و هیچ
        # سندِ دریافتِ واقعی/چکی در خزانه ثبت نمی‌شد. حالا دقیقاً هم‌الگو با
        # تاییدِ سرپرستِ POS در دسکتاپ (commercial_pos_approval.py): پس از
        # ثبتِ نهایی، سندِ دریافتِ چندروشی ساخته و به همین فاکتور تخصیص داده
        # می‌شود. اگر این مرحله برخلافِ پیش‌بررسی باز هم خطا دهد، فاکتور
        # (که کالایش تحویل شده) حفظ می‌شود و نسیه می‌ماند -- هشدار برمی‌گردد
        # تا تسویه در دسکتاپ انجام شود، نه اینکه فروشِ واقعی رد شود.
        if payload.settlement_lines:
            try:
                pos_service.record_mixed_payment_and_settle(ctx.company_id, ctx.user_id, document_id, settlement_lines)
            except ValueError as exc:
                settlement_warning = f"فاکتور ثبت شد ولی سندِ دریافت ساخته نشد و فاکتور نسیه ماند: {exc}"
    audit_log.record(
        ctx.company_id, ctx.user_id, "CommercialDocument", document_id, "CREATE",
        {"source": "mobile", "document_type_code": payload.document_type_code, "line_count": len(line_ids)},
    )
    document_no = documents_service.get_document(document_id, ctx.company_id)[0].document_no
    return document_id, line_ids, document_no, settlement_warning


@router.get("/{document_id}/print-data")
def print_data(document_id: int, ctx: AuthContext = Depends(get_current_context)) -> dict:
    """طبقِ درخواستِ صریحِ کاربر («در ادامه پرینتِ فاکتور و فایلِ pdf»):
    دادهٔ کاملِ چاپِ یک فاکتور/سفارش (سرِبرگِ شرکت، مشتری، ردیف‌ها، جمع‌ها،
    تسویهٔ واقعیِ ثبت‌شده و چک‌ها) -- خودِ صفحه‌آرایی/PDF رویِ موبایل
    ساخته می‌شود. ویزیتور فقط سندهایِ خودش را می‌تواند چاپ کند."""
    try:
        doc, lines = documents_service.get_document(document_id, ctx.company_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if doc.document_type_code not in ("SALES_INVOICE", "SALES_ORDER"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="سند یافت نشد.")
    if doc.created_by_user_id != ctx.user_id and not roles_service.user_has_permission(
        ctx.user_id, ctx.company_id, FORM_HOT_DISTRIBUTION, "VIEW",
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="سند یافت نشد.")

    with new_session() as session:
        company = session.get(Company, ctx.company_id)
        seller = session.get(User, doc.created_by_user_id)
        checks = []
        je_ids = [s.journal_entry_id for s in settlements_service.list_settlements_for_invoice(document_id, ctx.company_id) if s.journal_entry_id]
        if je_ids:
            checks = session.scalars(
                select(ReceivedCheck).where(ReceivedCheck.source_journal_entry_id.in_(je_ids)).order_by(ReceivedCheck.received_check_id)
            ).all()
        check_rows = [
            {"check_no": c.check_no, "bank_name": c.drawee_bank_name, "due_date": c.due_date.isoformat(), "amount": str(c.amount)}
            for c in checks
        ]
        company_row = {
            "name": company.display_name, "legal_name": company.legal_name,
            "economic_code": company.economic_code, "national_id": company.national_id,
            "registration_no": company.registration_no,
        }
        seller_name = seller.full_name if seller else None

    customer = next((c for c in dimensions_service.list_customers(ctx.company_id) if c["detail_account_id"] == doc.counterparty_detail_account_id), None)
    items_by_id = {it.item_id: it for it in catalog_service.list_items(ctx.company_id)}
    uom_codes = {u.uom_id: u.code for u in catalog_service.list_uoms(ctx.company_id)}
    plan = settlements_service.get_settlement_plan(document_id, ctx.company_id) if doc.document_type_code == "SALES_INVOICE" else None
    method_labels = dict(settlements_service.SETTLEMENT_PLAN_METHOD_LABELS)
    method_labels.update({m.method_code: m.label for m in settlements_service.list_mobile_settlement_methods(ctx.company_id)})
    settlement_status = (
        settlements_service.get_invoice_settlement_status(document_id, ctx.company_id)
        if doc.document_type_code == "SALES_INVOICE" and doc.status_code == "POSTED" else None
    )
    return {
        "document_id": doc.document_id,
        "document_type_code": doc.document_type_code,
        "document_no": doc.document_no,
        "document_date": doc.document_date.isoformat(),
        "status_code": doc.status_code,
        "company": company_row,
        "seller_name": seller_name,
        "customer": {
            "detail_account_id": doc.counterparty_detail_account_id,
            "code": customer["code"] if customer else None,
            "name": customer["name"] if customer else None,
            "phone": customer.get("phone") if customer else None,
            "address": customer.get("address") if customer else None,
        },
        "lines": [
            {
                "line_no": ln.line_no,
                "item_code": items_by_id[ln.item_id].code if ln.item_id in items_by_id else str(ln.item_id),
                "item_name": items_by_id[ln.item_id].name if ln.item_id in items_by_id else None,
                "uom_code": uom_codes.get(ln.uom_id, ""),
                "quantity": str(ln.quantity), "unit_price": str(ln.unit_price),
                "discount_amount": str(ln.discount_amount), "tax_amount": str(ln.tax_amount),
                "line_total": str(ln.line_total),
            }
            for ln in sorted(lines, key=lambda x: x.line_no)
        ],
        "gross_amount": str(doc.subtotal_amount),
        "discount_amount": str(doc.discount_amount),
        "tax_amount": str(doc.tax_amount),
        "total_amount": str(doc.total_amount),
        "settlement_lines": [
            {"method_code": ln.method_code, "label": method_labels.get(ln.method_code, ln.method_code), "amount": str(ln.amount), "note": ln.note}
            for ln in (plan.lines if plan else [])
        ],
        "checks": check_rows,
        "settled_amount": str(settlement_status.settled_amount) if settlement_status else "0",
        "remaining_amount": str(settlement_status.remaining_amount) if settlement_status else str(doc.total_amount),
    }
