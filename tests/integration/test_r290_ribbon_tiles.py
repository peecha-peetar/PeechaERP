import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r290"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crm_fixture import *  # noqa: F401,F403
import crm_fixture as fx
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QLabel
check = fx.check

# همان فونت و تم برنامهٔ واقعی (ایراد فقط با فونت Vazirmatn و برچسب دوسطری دیده می‌شد)
app = QApplication.instance() or QApplication([])
app.setLayoutDirection(Qt.RightToLeft)
app.setStyle("Fusion")
from peecha.ui import main as ui_main, theme
fam = ui_main.get_font_family()
app.setFont(QFont(fam, 11.5))
theme.set_font_family(fam)
theme.set_theme_mode(app, False)
from peecha import nav_catalog
from peecha.ui import shell_window as sw

check(sw._two_lines("داشبورد ارتباط با مشتری", sw._tile_text_metrics(), sw._TILE_WIDTH - 2 * sw._TILE_MARGIN) == "داشبورد ارتباط با مشتری",
      "two-line label kept whole")
long = "گزارش بسیار طولانی برای آزمودن کوتاه‌سازی برچسب در کاشی ریبون صفحهٔ اصلی"
short = sw._two_lines(long, sw._tile_text_metrics(), sw._TILE_WIDTH - 2 * sw._TILE_MARGIN)
check(short.endswith("…") and len(short) < len(long), f"over-long label shortened with ellipsis ({short})")

mw = sw.MainWindow()
mw.resize(1300, 850)
mw.show()
app.processEvents()
scroll = mw._quick_access_scroll
flags = int(Qt.TextWordWrap | Qt.AlignHCenter)
modules = [m for m, items in nav_catalog.DEFAULT_QUICK_ACCESS_BY_MODULE.items() if items]
bad, scrolled = [], 0
for module in modules:
    mw._quick_access_module_code = None
    mw._refresh_quick_access_bar(module)
    app.processEvents()
    viewport = scroll.viewport()
    scrolled += scroll.horizontalScrollBar().isVisible()
    for tile in [t for t in mw.findChildren(sw._QuickAccessTile) if t.isVisible()]:
        icon = tile.findChild(QLabel, "quickTileIcon")
        text = tile.text_label
        needed = text.fontMetrics().boundingRect(0, 0, text.width(), 10_000, flags, text.text()).height()
        top = tile.mapTo(viewport, tile.rect().topLeft()).y()
        problems = []
        if icon.geometry().bottom() >= text.geometry().top():
            problems.append("text overlaps icon")
        if needed > text.height() or text.geometry().bottom() > tile.height():
            problems.append("text clipped")
        if top < 0 or top + tile.height() > viewport.height():
            problems.append("tile cut by ribbon")
        if tile.toolTip() not in text.text() and not text.text().endswith("…"):
            problems.append("label changed")
        if problems:
            bad.append((module, tile.toolTip(), problems))
check(not bad, f"every ribbon tile: icon above, text below in ≤2 lines, nothing clipped {bad[:5]}")
check(scrolled > 0, "checked with horizontal scrollbar visible too")
check(len(modules) >= 10, f"all module ribbons checked ({len(modules)})")

fx.finish()
