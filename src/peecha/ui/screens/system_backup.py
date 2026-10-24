"""پشتیبان‌گیری/بازیابی کامل دیتابیس — طبق گزارش صریح کاربر: بک‌آپ
قدیمی (قبل از ماژول حقوق‌ودستمزد) جدول‌ها/فیلدهای سفارشی بعداً
اضافه‌شده را نداشت. این صفحه روی services/backup.py سوار است که
ساختار *زنده*ی دیتابیس را می‌خواند (نه فهرست ثابت)، پس هر جدول تازه
خودکار این‌جا هم دیده می‌شود، بدون نیاز به تغییر این فایل.

طبق تایید صریح کاربر: بازیابی فقط روی دیتابیس خالی (تازه‌ساخته/
تازه‌مهاجرت‌شده) مجاز شمرده می‌شود — تداخل‌های ناشی از دیتای ازپیش‌موجود
(مثلاً ردیف‌های seed خود مهاجرت‌ها) به‌طور امن نادیده گرفته می‌شوند
(skipped)، ولی merge کردن عمدی روی یک دیتابیس درحال‌کار پشتیبانی
نمی‌شود."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import numerals, session
from peecha.db import schema_bootstrap
from peecha.db.base import get_engine
from peecha.services import backup as backup_service
from peecha.ui.widgets import FieldHelpMixin, wrap_scrollable_with_footer

_SCHEMA_LABELS = {
    "core": "پایه/تنظیمات عمومی",
    "sec": "کاربران و دسترسی‌ها",
    "acc": "حسابداری (کدینگ/تفصیلی/اسناد)",
    "hr": "منابع انسانی",
    "payroll": "حقوق و دستمزد",
    "treasury": "خزانه‌داری",
    "wf": "گردش کار/کارتابل",
    "doc": "ضمائم",
    "audit": "حسابرسی",
    "public": "سایر",
}


_UPGRADE_SOURCES = {"desktop": "برنامهٔ دسکتاپ", "api": "سرور موبایل", "settings": "تنظیمات اتصال",
                    "restore": "بازیابی پشتیبان"}
_UPGRADE_STATUS = {"DONE": "انجام شد", "FAILED": "ناموفق؛ دیتابیس دست‌نخورده ماند", "RUNNING": "نیمه‌تمام"}


def _ltr(text: str) -> str:
    """نام فایل و مسیر لاتین داخل جملهٔ فارسی به هم نریزد."""
    return f"\u2066{text}\u2069"


class SystemBackupScreen(FieldHelpMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._tables: list[backup_service.BackupTableInfo] = []
        self._table_items: dict[str, QTreeWidgetItem] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(14)

        title = QLabel("پشتیبان‌گیری و بازیابی دیتابیس")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        hint = QLabel(
            "فهرست زیر مستقیماً از ساختار زندهٔ همین دیتابیس خوانده می‌شود — هر جدول یا فیلد سفارشی که "
            "بعداً اضافه شود، خودکار همین‌جا هم دیده می‌شود، بدون نیاز به به‌روزرسانی برنامه. برای بازیابی، "
            "دیتابیس مقصد باید خالی باشد (جدید و ارتقایافته تا آخرین نسخه)."
        )
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        preset_row = QHBoxLayout()
        select_all_button = QPushButton("☑️")
        select_all_button.setObjectName("iconButton")
        select_all_button.setFixedWidth(44)
        select_all_button.setToolTip("انتخاب همه")
        select_all_button.clicked.connect(lambda: self._set_all_checked(True))
        preset_row.addWidget(select_all_button)
        select_none_button = QPushButton("◻️")
        select_none_button.setObjectName("iconButton")
        select_none_button.setFixedWidth(44)
        select_none_button.setToolTip("لغو انتخاب همه")
        select_none_button.clicked.connect(lambda: self._set_all_checked(False))
        preset_row.addWidget(select_none_button)
        setup_only_button = QPushButton("➕")
        setup_only_button.setObjectName("iconButton")
        setup_only_button.setFixedWidth(44)
        setup_only_button.setToolTip("فقط تنظیمات و تعریف اولیه")
        setup_only_button.clicked.connect(self._select_setup_only)
        preset_row.addWidget(setup_only_button)
        preset_row.addStretch(1)
        layout.addLayout(preset_row)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["تعداد ردیف", "جدول"])
        self.tree.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.tree, stretch=1)

        self.status_text = QTextEdit()
        self.status_text.setReadOnly(True)
        self.status_text.setMaximumHeight(140)
        self.status_text.setPlaceholderText("نتیجهٔ آخرین بک‌آپ/بازیابی این‌جا نشان داده می‌شود.")
        layout.addWidget(self.status_text)

        # R335: هر ارتقای دیتابیس با نسخه، سیستم، فایل‌ها و پشتیبان پیش از آن
        upgrades_title = QLabel("ارتقاهای دیتابیس")
        upgrades_title.setObjectName("sectionTitle")
        layout.addWidget(upgrades_title)
        self.upgrade_summary = QLabel("")
        self.upgrade_summary.setObjectName("sectionHint")
        self.upgrade_summary.setWordWrap(True)
        layout.addWidget(self.upgrade_summary)
        self.upgrades_table = QTableWidget(0, 6)
        self.upgrades_table.setHorizontalHeaderLabels(
            ["زمان", "نسخهٔ برنامه", "از کجا", "تعداد فایل", "نتیجه", "پشتیبان پیش از ارتقا"])
        self.upgrades_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.upgrades_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.upgrades_table.verticalHeader().setVisible(False)
        self.upgrades_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.upgrades_table.setMinimumHeight(150)
        layout.addWidget(self.upgrades_table)

        self.export_button = QPushButton("📦 گرفتن بک‌آپ از موارد انتخاب‌شده")
        self.export_button.setObjectName("primaryButton")
        self.export_button.clicked.connect(self._on_export)
        self.import_button = QPushButton("📥 بازیابی بک‌آپ")
        self.import_button.clicked.connect(self._on_import)

        outer.addWidget(wrap_scrollable_with_footer(panel, [self.export_button, self.import_button]))

        self.set_field_help([
            (
                self.export_button,
                "فقط جدول‌هایی که تیک خورده‌اند در فایل بک‌آپ ذخیره می‌شوند. برای بک‌آپ کامل، «انتخاب همه» را بزنید.",
            ),
            (
                self.import_button,
                "بازیابی باید روی یک دیتابیس خالی جدید انجام شود. ردیف‌هایی که ازپیش وجود دارند "
                "(مثلاً دیتای پیش‌فرض خود نصب) بی‌خطر رد می‌شوند؛ خطاهای واقعی (مثلاً ستون الزامی جدید) در گزارش نشان داده می‌شوند.",
            ),
            (self.status_text, "پیام/گزارش آخرین عملیات بک‌آپ/بازیابی این‌جا نشان داده می‌شود."),
        ])

    # --- بارگذاریِ فهرست --------------------------------------------------
    def refresh(self) -> None:
        engine = get_engine()
        self._tables = backup_service.list_backup_tables(engine)
        self._rebuild_tree()
        self._fill_upgrades(engine)

    def _fill_upgrades(self, engine) -> None:
        status = schema_bootstrap.schema_status(engine)
        names = lambda items: "، ".join(_ltr(n) for n in items)  # noqa: E731
        parts = [f"فایل‌های اجراشده: {numerals.to_persian_digits(str(status.applied))}"
                 + (f" (آخرین: {_ltr(status.latest)})" if status.latest else ""),
                 f"پشتیبان خودکار پیش از هر ارتقا در پوشهٔ «{_ltr(str(schema_bootstrap.backup_dir()))}» نگه داشته "
                 f"می‌شود ({numerals.to_persian_digits(str(schema_bootstrap.KEEP_BACKUPS))} پشتیبان آخر)."]
        if status.pending:
            parts.append(f"در انتظار اجرا: {names(status.pending)}")
        if status.newer:
            parts.append(f"⛔ دیتابیس فایل‌هایی دارد که این نسخهٔ برنامه نمی‌شناسد: {names(status.newer)}؛ برنامه را به‌روز کنید.")
        if status.changed:
            parts.append(f"⚠ این فایل‌ها پس از اجرا ویرایش شده‌اند و تغییرشان روی این دیتابیس اعمال نشده است: "
                         f"{names(status.changed)}")
        first_file = next(iter(schema_bootstrap.list_schema_files()), None)
        self.upgrade_summary.setText("\n".join(parts))
        self.upgrades_table.setRowCount(len(status.upgrades))
        for r, u in enumerate(status.upgrades):
            values = [numerals.format_jalali_datetime(u.started_at), u.app_version or "",
                      _UPGRADE_SOURCES.get(u.source or "", u.source or ""), numerals.to_persian_digits(str(len(u.files))),
                      _UPGRADE_STATUS.get(u.status, u.status),
                      u.backup_path.replace("\\", "/").rsplit("/", 1)[-1] if u.backup_path else
                      ("نصب جدید؛ پشتیبان لازم نبود" if first_file and first_file.name in u.files else "بدون پشتیبان")]
            for c, value in enumerate(values):
                item = QTableWidgetItem(value)
                if c == 3:
                    item.setToolTip("\n".join(u.files))
                if c == 4 and u.error:
                    item.setToolTip(u.error)
                if c == 5 and u.backup_path:
                    item.setToolTip(u.backup_path)
                self.upgrades_table.setItem(r, c, item)
        self.upgrades_table.resizeColumnsToContents()
        self.upgrades_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)

    def _rebuild_tree(self) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()
        self._table_items = {}

        by_schema: dict[str, list[backup_service.BackupTableInfo]] = {}
        for t in self._tables:
            by_schema.setdefault(t.schema, []).append(t)

        for schema_name in sorted(by_schema):
            schema_item = QTreeWidgetItem(["", _SCHEMA_LABELS.get(schema_name, schema_name)])
            schema_item.setFlags(schema_item.flags() | Qt.ItemIsAutoTristate | Qt.ItemIsUserCheckable)
            schema_item.setCheckState(0, Qt.Checked)
            self.tree.addTopLevelItem(schema_item)
            for t in sorted(by_schema[schema_name], key=lambda r: r.name):
                child = QTreeWidgetItem([str(t.row_count), t.name])
                child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
                child.setCheckState(0, Qt.Checked)
                child.setData(0, Qt.UserRole, t.full_name)
                schema_item.addChild(child)
                self._table_items[t.full_name] = child

        self.tree.expandAll()
        self.tree.resizeColumnToContents(0)
        self.tree.blockSignals(False)

    def _on_item_changed(self, _item: QTreeWidgetItem, _column: int) -> None:
        pass  # Qt.ItemIsAutoTristate خودش حالتِ والد/فرزند را هماهنگ می‌کند

    def _set_all_checked(self, checked: bool) -> None:
        state = Qt.Checked if checked else Qt.Unchecked
        self.tree.blockSignals(True)
        for item in self._table_items.values():
            item.setCheckState(0, state)
        for i in range(self.tree.topLevelItemCount()):
            self.tree.topLevelItem(i).setCheckState(0, state)
        self.tree.blockSignals(False)

    def _select_setup_only(self) -> None:
        setup_names = {t.full_name for t in self._tables if t.is_setup}
        self.tree.blockSignals(True)
        for full_name, item in self._table_items.items():
            item.setCheckState(0, Qt.Checked if full_name in setup_names else Qt.Unchecked)
        self.tree.blockSignals(False)

    def _selected_full_names(self) -> set[str]:
        return {name for name, item in self._table_items.items() if item.checkState(0) == Qt.Checked}

    # --- عملیات -----------------------------------------------------------
    def _on_export(self) -> None:
        selected = self._selected_full_names()
        if not selected:
            QMessageBox.information(self, "بک‌آپ", "دست‌کم یک جدول را انتخاب کنید.")
            return
        default_name = f"peecha-backup-{session.current_company.company_id if session.current_company else 'db'}.json.gz"
        path, _filter = QFileDialog.getSaveFileName(self, "ذخیرهٔ فایل بک‌آپ", default_name, "Backup (*.json.gz)")
        if not path:
            return
        if not path.lower().endswith(".gz"):
            path += ".json.gz"
        try:
            manifest = backup_service.export_backup(get_engine(), path, selected)
        except Exception as exc:  # noqa: BLE001 - خطایِ غیرمنتظره باید به کاربر نشان داده شود، نه کرش کند
            QMessageBox.critical(self, "خطا در بک‌آپ", str(exc))
            return
        total_rows = sum(t["row_count"] for t in manifest["tables"])
        lines = [f"بک‌آپ با موفقیت ساخته شد: {len(manifest['tables'])} جدول، {total_rows} ردیف.", f"مسیر: {path}"]
        self.status_text.setPlainText("\n".join(lines))
        QMessageBox.information(self, "بک‌آپ", "فایل بک‌آپ با موفقیت ساخته شد.")

    def _on_import(self) -> None:
        confirm = QMessageBox.question(
            self,
            "بازیابی بک‌آپ",
            "بازیابی فقط روی یک دیتابیس خالی جدید مطمئن است. آیا این دیتابیس خالی است و می‌خواهید ادامه دهید؟",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        path, _filter = QFileDialog.getOpenFileName(self, "انتخاب فایل بک‌آپ", "", "Backup (*.json.gz *.json)")
        if not path:
            return
        try:
            report = backup_service.import_backup(get_engine(), path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "خطا در بازیابی", str(exc))
            return

        lines = []
        total_inserted = total_skipped = total_errors = 0
        for r in report.tables:
            total_inserted += r.inserted
            total_skipped += r.skipped_existing
            total_errors += r.errors
            if r.inserted or r.errors:
                lines.append(f"{r.full_name}: {r.inserted} درج شد، {r.skipped_existing} ازپیش‌موجود، {r.errors} خطا")
                for sample in r.error_samples:
                    lines.append(f"    • {sample}")
        if report.skipped_unknown_tables:
            lines.append("جدول‌های زیر در ساختار فعلی وجود ندارند و نادیده گرفته شدند:")
            lines.extend(f"    • {name}" for name in report.skipped_unknown_tables)
        lines.append(f"\nجمع: {total_inserted} ردیف درج شد، {total_skipped} ازپیش‌موجود، {total_errors} خطا.")
        self.status_text.setPlainText("\n".join(lines))
        QMessageBox.information(self, "بازیابی", f"بازیابی انجام شد — {total_inserted} ردیف درج شد.")
        self.refresh()
