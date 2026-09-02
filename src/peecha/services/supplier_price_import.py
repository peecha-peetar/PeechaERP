"""واردکردنِ لیستِ قیمتِ تامین‌کننده از اکسل/PDF -- طبقِ درخواستِ صریح:
هر کالا می‌تواند چند «کدِ تامین‌کننده» داشته باشد (کدِ خودِ کالا نزدِ آن
تامین‌کننده، که با کدِ داخلیِ ما فرق دارد) تا ردیف‌هایِ فایلِ قیمتِ او
خودکار به کالایِ داخلی متصل شوند. سپس رویِ قیمتِ تامین‌کننده چند ستونِ
افزایشیِ درصدی/مبلغی اعمال و نتیجه در یک فهرستِ قیمتِ موجود ثبت می‌شود.

طبقِ محدودیتِ صریحِ توافق‌شده («فازِ اول فقط اکسل و PDFِ متنی، بدونِ
OCR/عکس»): اگر PDF یک اسکنِ عکسی باشد (بدونِ لایه‌یِ متن)، استخراج چیزی
برنمی‌گرداند -- این حالت باید در UI با پیامِ روشن («این PDF یک عکسِ
اسکن‌شده است، نه متنی») به کاربر گفته شود، نه خطایِ فنی."""

from __future__ import annotations

import decimal
import re
from dataclasses import dataclass

import openpyxl
import pdfplumber
from sqlalchemy import select

from peecha import numerals
from peecha.db.base import new_session
from peecha.db.models.commercial import SupplierPriceImportTemplate
from peecha.db.models.inventory import Item, ItemSupplierCode

_ZERO = decimal.Decimal("0")
_Q2 = decimal.Decimal("0.01")


def _normalize_code(code: str) -> str:
    return numerals.to_ascii_digits(code).strip().upper()


# ---------------------------------------------------------------------
# کدهایِ تامین‌کننده برایِ هر کالا
# ---------------------------------------------------------------------
@dataclass
class ItemSupplierCodeRow:
    item_supplier_code_id: int
    item_id: int
    supplier_detail_account_id: int | None
    supplier_code: str


def list_item_supplier_codes(item_id: int) -> list[ItemSupplierCodeRow]:
    with new_session() as session:
        rows = session.scalars(
            select(ItemSupplierCode).where(ItemSupplierCode.item_id == item_id).order_by(ItemSupplierCode.item_supplier_code_id)
        ).all()
        return [
            ItemSupplierCodeRow(r.item_supplier_code_id, r.item_id, r.supplier_detail_account_id, r.supplier_code)
            for r in rows
        ]


def add_item_supplier_code(item_id: int, supplier_code: str, supplier_detail_account_id: int | None = None) -> int:
    supplier_code = supplier_code.strip()
    if not supplier_code:
        raise ValueError("کدِ تامین‌کننده نمی‌تواند خالی باشد.")
    normalized = _normalize_code(supplier_code)
    with new_session() as session:
        existing = session.scalar(
            select(ItemSupplierCode).where(
                ItemSupplierCode.item_id == item_id,
                ItemSupplierCode.supplier_detail_account_id == supplier_detail_account_id,
                ItemSupplierCode.normalized_code == normalized,
            )
        )
        if existing is not None:
            raise ValueError("این کد قبلاً برایِ همین کالا (نزدِ همین تامین‌کننده) ثبت شده است.")
        row = ItemSupplierCode(
            item_id=item_id, supplier_detail_account_id=supplier_detail_account_id,
            supplier_code=supplier_code, normalized_code=normalized,
        )
        session.add(row)
        session.commit()
        return row.item_supplier_code_id


def delete_item_supplier_code(item_supplier_code_id: int) -> None:
    with new_session() as session:
        row = session.get(ItemSupplierCode, item_supplier_code_id)
        if row is None:
            raise ValueError("این کد یافت نشد.")
        session.delete(row)
        session.commit()


def find_item_by_supplier_code(company_id: int, code: str, supplier_detail_account_id: int | None) -> int | None:
    """اول با همان تامین‌کننده تلاش می‌کند؛ اگر نبود، با کدِ عمومی
    (بدونِ تامین‌کننده -- مثلاً بارکدِ رایجِ صنعتی) تلاش می‌کند."""
    if not code:
        return None
    normalized = _normalize_code(code)
    with new_session() as session:
        if supplier_detail_account_id is not None:
            row = session.scalar(
                select(ItemSupplierCode)
                .join(Item, Item.item_id == ItemSupplierCode.item_id)
                .where(
                    Item.company_id == company_id,
                    ItemSupplierCode.supplier_detail_account_id == supplier_detail_account_id,
                    ItemSupplierCode.normalized_code == normalized,
                )
            )
            if row is not None:
                return row.item_id
        row = session.scalar(
            select(ItemSupplierCode)
            .join(Item, Item.item_id == ItemSupplierCode.item_id)
            .where(
                Item.company_id == company_id,
                ItemSupplierCode.supplier_detail_account_id.is_(None),
                ItemSupplierCode.normalized_code == normalized,
            )
        )
        return row.item_id if row is not None else None


# ---------------------------------------------------------------------
# قالبِ ذخیره‌شده‌یِ ستون‌بندیِ فایلِ هر تامین‌کننده
# ---------------------------------------------------------------------
@dataclass
class ImportTemplateRow:
    template_id: int
    supplier_detail_account_id: int
    code_column_index: int
    price_column_index: int
    header_row_index: int
    sheet_name: str | None


def get_import_template(company_id: int, supplier_detail_account_id: int) -> ImportTemplateRow | None:
    with new_session() as session:
        row = session.scalar(
            select(SupplierPriceImportTemplate).where(
                SupplierPriceImportTemplate.company_id == company_id,
                SupplierPriceImportTemplate.supplier_detail_account_id == supplier_detail_account_id,
            )
        )
        if row is None:
            return None
        return ImportTemplateRow(
            row.template_id, row.supplier_detail_account_id, row.code_column_index, row.price_column_index,
            row.header_row_index, row.sheet_name,
        )


def save_import_template(
    company_id: int, supplier_detail_account_id: int, code_column_index: int, price_column_index: int,
    header_row_index: int, sheet_name: str | None = None,
) -> None:
    with new_session() as session:
        row = session.scalar(
            select(SupplierPriceImportTemplate).where(
                SupplierPriceImportTemplate.company_id == company_id,
                SupplierPriceImportTemplate.supplier_detail_account_id == supplier_detail_account_id,
            )
        )
        if row is None:
            row = SupplierPriceImportTemplate(company_id=company_id, supplier_detail_account_id=supplier_detail_account_id)
            session.add(row)
        row.code_column_index = code_column_index
        row.price_column_index = price_column_index
        row.header_row_index = header_row_index
        row.sheet_name = sheet_name
        session.commit()


# ---------------------------------------------------------------------
# استخراجِ جدولِ خام از فایل -- طبقِ توافق: فقط اکسل و PDFِ متنی
# ---------------------------------------------------------------------
def list_excel_sheet_names(file_path: str) -> list[str]:
    workbook = openpyxl.load_workbook(file_path, read_only=True)
    try:
        return list(workbook.sheetnames)
    finally:
        workbook.close()


def extract_excel_grid(file_path: str, sheet_name: str | None = None) -> list[list[str]]:
    workbook = openpyxl.load_workbook(file_path, data_only=True, read_only=True)
    try:
        sheet = workbook[sheet_name] if sheet_name else workbook.worksheets[0]
        return [["" if cell is None else str(cell) for cell in row] for row in sheet.iter_rows(values_only=True)]
    finally:
        workbook.close()


def extract_pdf_grid(file_path: str) -> list[list[str]]:
    """اول با تشخیصِ جدولِ بومیِ pdfplumber (بهترین دقت، وقتی PDF واقعاً
    خط‌کشیِ جدول دارد)؛ اگر چیزی پیدا نشد (رایج در فاکتور/لیست‌هایِ
    بدونِ خط‌کشیِ صریح)، به استخراجِ متنِ خام برمی‌گردد و ستون‌ها را از
    رویِ فاصله‌هایِ متوالی (رایج‌ترین الگویِ تراز-چپ/راستِ جدولی) حدس
    می‌زند. اگر PDF یک اسکنِ عکسی باشد (بدونِ لایه‌یِ متن)، هردو راه چیزی
    برنمی‌گردانند -- خروجیِ خالی یعنی همین."""
    grid: list[list[str]] = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                for row in table:
                    grid.append(["" if cell is None else str(cell).strip() for cell in row])
    if grid:
        return grid
    # طبقِ باگِ کشف‌شده حینِ آزمایش: extract_text() فاصله‌هایِ چندتاییِ
    # واقعی را به یک فاصله تبدیل می‌کند (بازسازیِ طبیعیِ متن، نه حفظِ
    # چیدمانِ ستونی) -- پس extract_words() با مختصاتِ x استفاده می‌شود:
    # کلماتی که رویِ همان خط‌اند ولی فاصله‌یِ افقیِ زیاد (فاصله‌یِ ستون،
    # نه فاصله‌یِ بینِ‌کلمه‌ایِ معمولی) دارند، به دو ستونِ جدا تقسیم می‌شوند.
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            grid.extend(_extract_grid_from_words(page))
    return grid


def _extract_grid_from_words(page, column_gap_threshold: float = 10.0) -> list[list[str]]:
    words = page.extract_words()
    if not words:
        return []
    rows: dict[int, list[dict]] = {}
    for w in words:
        key = round(w["top"] / 3)
        rows.setdefault(key, []).append(w)
    grid: list[list[str]] = []
    for key in sorted(rows.keys()):
        row_words = sorted(rows[key], key=lambda w: w["x0"])
        cells: list[str] = []
        current_cell = [row_words[0]["text"]]
        prev_x1 = row_words[0]["x1"]
        for w in row_words[1:]:
            if w["x0"] - prev_x1 > column_gap_threshold:
                cells.append(" ".join(current_cell))
                current_cell = [w["text"]]
            else:
                current_cell.append(w["text"])
            prev_x1 = w["x1"]
        cells.append(" ".join(current_cell))
        grid.append(cells)
    return grid


def parse_price(text: str) -> decimal.Decimal | None:
    if not text:
        return None
    cleaned = numerals.to_ascii_digits(str(text)).replace(",", "").replace("٬", "").strip()
    cleaned = re.sub(r"[^\d.\-]", "", cleaned)
    if not cleaned or cleaned in ("-", "."):
        return None
    try:
        return decimal.Decimal(cleaned)
    except decimal.InvalidOperation:
        return None


# ---------------------------------------------------------------------
# تطبیقِ ردیف‌ها با کالاهایِ داخلی
# ---------------------------------------------------------------------
@dataclass
class MatchedPriceRow:
    row_no: int
    raw_code: str
    supplier_price: decimal.Decimal | None
    item_id: int | None
    item_label: str


def match_grid_rows(
    company_id: int, grid: list[list[str]], code_column: int, price_column: int, header_row_index: int,
    supplier_detail_account_id: int | None,
) -> list[MatchedPriceRow]:
    from peecha.services import inventory_catalog as catalog_service

    items_by_id = {i.item_id: i for i in catalog_service.list_items(company_id)}
    results: list[MatchedPriceRow] = []
    for row_no, row in enumerate(grid):
        if row_no <= header_row_index:
            continue
        if code_column >= len(row) or price_column >= len(row):
            continue
        raw_code = (row[code_column] or "").strip()
        raw_price_text = (row[price_column] or "").strip()
        if not raw_code and not raw_price_text:
            continue
        price = parse_price(raw_price_text)
        item_id = find_item_by_supplier_code(company_id, raw_code, supplier_detail_account_id) if raw_code else None
        item = items_by_id.get(item_id) if item_id is not None else None
        item_label = f"{item.code} — {item.name or ''}" if item else ""
        results.append(MatchedPriceRow(row_no=row_no, raw_code=raw_code, supplier_price=price, item_id=item_id, item_label=item_label))
    return results


# ---------------------------------------------------------------------
# اعمالِ ستون‌هایِ افزایشیِ درصدی/مبلغی
# ---------------------------------------------------------------------
@dataclass
class PriceAdjustmentStep:
    kind: str  # PERCENT | AMOUNT
    value: decimal.Decimal
    label: str = ""


def apply_adjustments(base_price: decimal.Decimal, steps: list[PriceAdjustmentStep]) -> decimal.Decimal:
    price = base_price
    for step in steps:
        if step.kind == "PERCENT":
            price = price + (price * step.value / decimal.Decimal(100))
        elif step.kind == "AMOUNT":
            price = price + step.value
        else:
            raise ValueError(f"نوعِ ستونِ افزایشی نامعتبر است: {step.kind}")
    return price.quantize(_Q2, rounding=decimal.ROUND_HALF_UP)
