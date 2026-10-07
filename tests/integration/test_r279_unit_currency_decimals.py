import os, sys, re, pathlib
os.environ["PEECHA_DB_NAME"] = "peecha_test_r279"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PySide6.QtWidgets import QApplication, QComboBox, QDoubleSpinBox
app = QApplication.instance() or QApplication([])
from prd_fixture import *  # noqa: F401,F403
import prd_fixture as fx
from peecha import decimals, numerals
from peecha.services import companies as companies_service, inventory_catalog as catalog_service
from peecha.ui.widgets import bind_qty_decimals
check = fx.check
P = numerals.to_persian_digits

# ۱) مقدار: واحد «عدد» بدون اعشار، کیلوگرم سه رقم
decimals.invalidate()
check(decimals.qty_decimals(pcs) == 0 and decimals.qty_decimals(kg) == 3, "uom decimals read from settings")
check(decimals.qty_decimals(item_id=fg) == 0 and decimals.qty_decimals(item_id=r1) == 3, "item falls back to its base unit")
check(decimals.format_qty(D("5.000"), uom_id=pcs) == P("5"), f"count unit shows no decimals {decimals.format_qty(D('5.000'), uom_id=pcs)}")
check(decimals.format_qty(D("2.5"), item_id=r1) == P("2.500"), "kg shows three decimals")
check(decimals.format_qty(D("7.50")) == P("7.5"), "unknown unit trims trailing zeros")
check(decimals.plain(D("100.000")) == P("100") and "E" not in decimals.plain(D("1E+2")), "edit text has no exponent")

# ۲) فیلد ورود مقدار از واحد کالای انتخاب‌شده پیروی می‌کند
combo, spin = QComboBox(), QDoubleSpinBox()
combo.addItem("A", fg); combo.addItem("B", r1)
spin.setDecimals(3); spin.setMinimum(0.001)
bind_qty_decimals(spin, combo)
check(spin.decimals() == 0 and spin.minimum() == 1, f"count item → whole numbers ({spin.decimals()}, {spin.minimum()})")
combo.setCurrentIndex(1)
check(spin.decimals() == 3, "kg item → three decimals")

# ۳) تغییر تنظیمات واحد فوراً اعمال می‌شود
catalog_service.update_uom(pcs, company_id, "PCS", "عدد", "COUNT", True, 2)
check(decimals.qty_decimals(pcs) == 2, "uom setting change invalidates cache")
catalog_service.update_uom(pcs, company_id, "PCS", "عدد", "COUNT", True, 0)

# ۴) مبلغ از اعشار ارز پایه
from peecha.ui.screens.journal_entry import _AmountField
base_currency = company.base_currency_id
for dp in (0, 2):
    companies_service.update_currency_decimal_places(base_currency, dp)
    check(decimals.money_decimals() == dp, f"money decimals follow currency ({dp})")
    check(_AmountField()._decimals == dp, f"amount field default follows currency ({dp})")
    expected = P("1,234.50") if dp else P("1,235")
    check(numerals.format_company_amount(D("1234.5")) .startswith(expected), f"company amount {numerals.format_company_amount(D('1234.5'))}")
companies_service.update_currency_decimal_places(base_currency, 0)

# ۵) گزارش‌ها: ستون مقدار صفرهای اضافه ندارد
src = pathlib.Path(__file__).resolve().parents[2] / "src" / "peecha" / "ui" / "screens"
left = [f"{p.name}:{i}" for p in src.glob("*.py") for i, line in enumerate(p.read_text().splitlines(), 1)
        if re.search(r"format_money\([^()]*(quantity|qty)[^()]*,\s*[23]\b", line)]
check(not left, f"no fixed-decimal quantity formatting left {left}")

fx.finish()
