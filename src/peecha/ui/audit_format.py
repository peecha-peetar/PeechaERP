"""R316: نمایش خوانای جزئیات رخدادنگار — به‌جای متن JSON، جدول «موضوع / پیش از تغییر / پس از تغییر» به فارسی."""

from __future__ import annotations

import datetime
import decimal
import re

from peecha import numerals

KEY_LABELS = {
    "operation": "عملیات", "status": "وضعیت", "status_code": "وضعیت", "code": "کد", "name": "نام", "title": "عنوان",
    "version": "نسخه", "version_no": "نسخه", "from": "از نسخهٔ", "item_id": "کالا", "item": "کالا", "quantity": "مقدار",
    "qty": "مقدار", "warehouse_id": "انبار", "warehouse": "انبار", "reason": "علت", "amount": "مبلغ", "description": "شرح",
    "date": "تاریخ", "entry_date": "تاریخ سند", "before": "پیش از تغییر", "after": "پس از تغییر", "lines": "ردیف‌ها",
    "account_id": "حساب", "debit": "بدهکار", "credit": "بستانکار", "unit_cost": "بهای واحد", "parameters": "تعداد شاخص‌ها",
    "stock_documents": "سندهای انبار", "stock_line_id": "ردیف سند انبار", "stage": "مرحله", "order_id": "دستور تولید",
    "default_bin_location_id": "مکان پیش‌فرض", "bin_location_id": "مکان", "location_id": "محل", "type": "نوع",
    "permanent_no": "شمارهٔ دائم", "reversed_by_entry_id": "سند برگشتی", "temporary_no": "شمارهٔ موقت",
    "document_no": "شمارهٔ سند", "document_id": "سند", "purchase_return_id": "سند برگشت به تامین‌کننده",
    "disposition_code": "تصمیم", "date_from": "از تاریخ", "date_to": "تا تاریخ", "fiscal_year_id": "سال مالی",
    "is_active": "فعال", "active": "فعال", "user_id": "کاربر", "role_id": "نقش", "note": "یادداشت", "comment": "یادداشت",
    "customer_id": "مشتری", "supplier_id": "تامین‌کننده", "person_id": "شخص", "price": "قیمت", "total": "جمع",
    "rate": "نرخ", "percent": "درصد", "method": "روش", "policy": "سیاست", "priority": "اولویت", "owner_user_id": "مسئول",
    "assigned_to": "واگذار به", "due_date": "سررسید", "result": "نتیجه", "score": "امتیاز", "value": "مقدار",
    "batch": "بچ", "batch_no": "شمارهٔ بچ", "serial": "سریال", "serial_no": "سریال", "expiry_date": "تاریخ انقضا",
    "run_id": "اجرا", "period": "دوره", "period_no": "دوره", "module": "بخش", "module_code": "بخش", "run": "اجرا",
    "row_id": "ردیف", "key": "کلید", "errors": "خطاها", "warnings": "هشدارها", "count": "تعداد", "rows": "تعداد ردیف",
    "message": "پیام", "label": "عنوان", "level": "سطح", "parent_id": "والد", "category_id": "طبقه", "asset_id": "دارایی",
}
_TOKENS = {
    "id": "", "no": "شمارهٔ", "date": "تاریخ", "item": "کالا", "warehouse": "انبار", "account": "حساب", "status": "وضعیت",
    "amount": "مبلغ", "qty": "مقدار", "quantity": "مقدار", "code": "کد", "name": "نام", "type": "نوع", "line": "ردیف",
    "document": "سند", "stock": "انبار", "bin": "خانه", "location": "مکان", "default": "پیش‌فرض", "user": "کاربر",
    "role": "نقش", "cost": "بها", "unit": "واحد", "price": "قیمت", "rate": "نرخ", "total": "جمع", "from": "از",
    "to": "تا", "order": "سفارش", "run": "اجرا", "period": "دوره", "plan": "برنامه", "version": "نسخه",
    "reason": "علت", "note": "یادداشت", "customer": "مشتری", "supplier": "تامین‌کننده", "person": "شخص",
    "asset": "دارایی", "category": "طبقه", "batch": "بچ", "serial": "سریال", "expiry": "انقضا", "count": "تعداد",
    "budget": "بودجه", "project": "پروژه", "center": "مرکز", "equipment": "تجهیز", "task": "کار", "ticket": "تیکت",
    "lead": "سرنخ", "opportunity": "فرصت", "campaign": "کمپین", "is": "", "active": "فعال", "new": "تازه", "old": "قبلی",
}
VALUE_LABELS = {
    "DRAFT": "پیش‌نویس", "ACTIVE": "فعال", "INACTIVE": "غیرفعال", "APPROVED": "تاییدشده", "REJECTED": "ردشده",
    "CANCELLED": "لغوشده", "CLOSED": "بسته", "OPEN": "باز", "POSTED": "ثبت‌شده", "PERMANENT": "دائم", "REVERSED": "برگشت‌خورده",
    "PENDING": "در انتظار", "COMPLETED": "انجام‌شده", "SUBMITTED": "ارسال‌شده", "CONFIRMED": "تاییدشده", "SENT": "ارسال‌شده",
    "RECEIVED": "دریافت‌شده", "ISSUED": "صادرشده", "SUPERSEDED": "جایگزین‌شده", "IN_PROGRESS": "در جریان", "DONE": "انجام‌شده",
    "TEMPORARY": "موقت", "LOCKED": "قفل", "VALIDATED": "بررسی‌شده", "READY": "آماده", "FAILED": "ناموفق", "SKIPPED": "ردشده از آن",
    "BLOCKED": "مسدود", "RESERVED": "رزرو", "QUARANTINE": "قرنطینه", "RELEASED": "آزادشده", "EXPIRED": "منقضی",
    "CREATE": "ایجاد", "UPDATE": "ویرایش", "DELETE": "حذف", "APPROVE": "تایید", "REJECT": "رد", "REVERSE": "برگشت",
    "POST": "ثبت قطعی", "CANCEL": "لغو", "MERGE": "ادغام", "SUBMIT": "ارسال", "CLOSE": "بستن", "REOPEN": "بازگشایی",
    "QC_RECORD": "ثبت نتیجهٔ بازرسی کیفیت", "QC_CANCEL": "لغو بازرسی کیفیت", "QC_RELEASE": "آزادسازی از قرنطینه",
    "QC_RETURN_TO_SUPPLIER": "برگشت به تامین‌کننده پس از بازرسی", "CROSS_DOCK": "ارسال مستقیم", "STOCK_RESERVE": "رزرو موجودی",
    "STOCK_RELEASE": "آزادسازی رزرو", "REVERSE_CANCEL": "برگشت و لغو", "RETURN_TO_SUPPLIER": "برگشت به تامین‌کننده",
    "USE_AS_IS": "استفاده با همین وضع", "REWORK": "دوباره‌کاری", "SCRAP": "ضایعات", "IN_PROCESS": "حین تولید",
    "INCOMING": "ورودی", "FINAL": "نهایی", "PUTAWAY": "چیدن در قفسه", "PICK": "جمع‌آوری", "REPLENISH": "تامین مجدد",
    "MOVE": "جابه‌جایی", "COUNT": "شمارش", "RECEIVABLES": "دریافتنی‌ها", "PAYABLES": "پرداختنی‌ها", "GL": "تراز حساب‌ها",
    "INVENTORY": "موجودی", "TRUE": "بله", "FALSE": "خیر",
}
ENTITY_LABELS = {
    "ChartOfAccount": "حساب", "JournalEntry": "سند حسابداری", "StockDocument": "سند انبار", "WarehouseTask": "وظیفهٔ انبار",
    "CycleCountSession": "شمارش انبار", "CommercialDocument": "سند فروش/خرید", "BinLocation": "محل انبار",
    "ItemStorageProfile": "شرایط نگهداری کالا", "ProductionOrder": "دستور تولید", "QcInspection": "بازرسی کیفیت",
    "InspectionPlan": "طرح بازرسی", "DepreciationRun": "اجرای استهلاک", "CipProject": "پروژهٔ دارایی در جریان ساخت",
    "AssetPhysicalCount": "شمارش دارایی", "Warehouse": "انبار", "ReplacementCost": "بهای جایگزینی",
    "QmsSettings": "تنظیمات کیفیت", "PayrollRun": "اجرای حقوق", "Nonconformance": "عدم انطباق",
    "CostingSettings": "تنظیمات بهای تمام‌شده", "CostRecalculation": "بازمحاسبهٔ بها", "CartableItem": "درخواست کارتابل",
    "AssetSettings": "تنظیمات دارایی", "AssetCategory": "طبقهٔ دارایی", "CapaAction": "اقدام اصلاحی", "CostClosing": "بستن بها",
    "CostPool": "مخزن هزینه", "BOM": "فهرست مواد", "Routing": "مسیر تولید", "WorkCenter": "مرکز کاری", "LaborRate": "نرخ دستمزد",
    "MrpRun": "محاسبهٔ نیاز مواد", "ProductionPlan": "برنامهٔ تولید", "ProductionSettings": "تنظیمات تولید",
    "StandardCost": "بهای استاندارد", "ItemProductionProfile": "مشخصات تولیدی کالا", "MntEquipment": "تجهیز",
    "MntDowntime": "توقف", "MntPlannedDowntime": "توقف برنامه‌ریزی‌شده", "MntFailureCode": "کد خرابی",
    "MntCapacityRestriction": "محدودیت ظرفیت", "Definition": "تعریف فرایند", "Instance": "اجرای فرایند",
    "Delegation": "تفویض", "Holiday": "تعطیلی", "SlaPolicy": "سیاست تعهد زمانی", "Task": "کار", "Exception": "استثنا",
}
# کلید جمع (فهرست) — «status» جمع نیست
_PLURAL = re.compile(r".*([^us]s|_ids|_list)$")
_CAMEL = re.compile(r"(?<!^)(?=[A-Z])")


def key_label(key: str) -> str:
    if key in KEY_LABELS:
        return KEY_LABELS[key]
    words = [_TOKENS.get(t, t) for t in str(key).lower().split("_")]
    words = [w for w in words if w]
    return " ".join(words) if words else str(key)


def entity_label(entity_type: str) -> str:
    if entity_type in ENTITY_LABELS:
        return ENTITY_LABELS[entity_type]
    for prefix, label in (("Crm", "ارتباط با مشتری"), ("Opening", "افتتاحیه"), ("Budget", "بودجه"), ("Mnt", "نگهداری")):
        if entity_type.startswith(prefix) and entity_type != prefix:
            rest = entity_type[len(prefix):]
            return f"{label} — {ENTITY_LABELS.get(rest, ' '.join(_CAMEL.split(rest)))}"
    return " ".join(_CAMEL.split(entity_type))


def value_text(value) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "بله" if value else "خیر"
    if isinstance(value, (int, float, decimal.Decimal)):
        return numerals.to_persian_digits(f"{value:,}" if abs(value) >= 10000 else str(value))
    if isinstance(value, (datetime.datetime, datetime.date)):
        return numerals.format_jalali_date(value)
    if isinstance(value, dict):
        return "، ".join(f"{key_label(k)}: {value_text(v)}" for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return "، ".join(value_text(v) for v in value) or "—"
    text = str(value)
    if text in VALUE_LABELS:
        return VALUE_LABELS[text]
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}([T ][\d:.]+.*)?", text):
        try:
            parsed = datetime.datetime.fromisoformat(text) if len(text) > 10 else datetime.date.fromisoformat(text)
            return numerals.format_jalali_date(parsed)
        except ValueError:
            pass
    if re.fullmatch(r"-?\d+(\.\d+)?", text):
        number = decimal.Decimal(text)
        return value_text(int(number) if number == number.to_integral_value() else number.normalize())
    return numerals.to_persian_digits(text) if not re.search(r"[A-Za-z]", text) else text


def rows(changes: dict | None) -> list[tuple[str, str, str]]:
    """(موضوع، پیش از تغییر، پس از تغییر یا مقدار)."""
    changes = changes or {}
    out: list[tuple[str, str, str]] = []
    before, after = changes.get("before"), changes.get("after")
    if isinstance(before, dict) or isinstance(after, dict):
        before, after = before if isinstance(before, dict) else {}, after if isinstance(after, dict) else {}
        for key in list(before) + [k for k in after if k not in before]:
            out.append((key_label(key), value_text(before.get(key)) if key in before else "—",
                        value_text(after.get(key)) if key in after else "—"))
    for key, value in changes.items():
        if key in ("before", "after") and (isinstance(value, dict)):
            continue
        if isinstance(value, (list, tuple)) and len(value) == 2 and not _PLURAL.match(str(key)):
            out.append((key_label(key), value_text(value[0]), value_text(value[1])))
        else:
            out.append((key_label(key), "", value_text(value)))
    return out


def summary(changes: dict | None, limit: int = 3) -> str:
    """خلاصهٔ یک‌خطی برای ستون «جزئیات»."""
    parts = []
    for subject, before, after in rows(changes)[:limit]:
        parts.append(f"{subject}: {before} ← {after}" if before else f"{subject}: {after}")
    more = len(rows(changes)) - limit
    text = "؛ ".join(parts)
    return text + (numerals.to_persian_digits(f" و {more} مورد دیگر") if more > 0 else "")
