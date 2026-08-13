"""زیرساختِ مشترکِ ایمپورتِ اکسل — طبقِ درخواستِ صریح («در فرم‌هایِ موجود و
فرم‌هایِ ورودِ اطلاعات بتوان از فایلِ اکسل اطلاعات را ایمپورت کرد، مثلِ فرمِ
تعریفِ حساب‌ها»): دیالوگِ تناظرِ ستون‌ها که برایِ ایمپورتِ ردیف‌هایِ سند
(journal_entry.py) ساخته شده بود، این‌جا عمومی شده — هر فرمی فقط فهرستِ
فیلدهایِ مقصدِ خودش را می‌دهد (به‌جایِ کپی‌کردنِ کلِ دیالوگ)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)


def excel_column_letter(index: int) -> str:
    letters = ""
    n = index + 1
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


class ExcelColumnMappingDialog(QDialog):
    """دیالوگِ عمومیِ تناظرِ ستون‌هایِ اکسل با فیلدهایِ مقصد — هر فرم فهرستِ
    (کلید، برچسب، الزامی؟) و کلیدواژه‌هایِ حدسِ خودکار را می‌دهد؛ خودِ
    دیالوگ فقط UI و اعتبارسنجیِ «فیلدهایِ الزامی مشخص شده‌اند» را انجام
    می‌دهد."""

    def __init__(
        self,
        target_fields: list[tuple[str, str, bool]],
        guess_keywords: dict[str, list[str]],
        header_row: tuple,
        parent: QWidget | None = None,
        *,
        title: str = "ایمپورتِ اطلاعات از اکسل — تناظرِ ستون‌ها",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(480)
        self._target_fields = target_fields

        self._column_labels: list[str] = []
        for i, value in enumerate(header_row):
            letter = excel_column_letter(i)
            text = str(value).strip() if value is not None else ""
            self._column_labels.append(f"{letter}: {text}" if text else f"ستونِ {letter}")

        layout = QVBoxLayout(self)

        self.header_checkbox = QCheckBox("ردیفِ اولِ فایل، عنوانِ ستون‌هاست (وارد نشود)")
        self.header_checkbox.setChecked(True)
        layout.addWidget(self.header_checkbox)

        hint = QLabel("هر فیلدِ مقصد را به یکی از ستون‌هایِ فایلِ اکسل نسبت دهید:")
        hint.setObjectName("sectionHint")
        layout.addWidget(hint)

        form = QFormLayout()
        self.field_combos: dict[str, QComboBox] = {}
        for key, label, required in target_fields:
            combo = QComboBox()
            combo.addItem("— هیچ‌کدام —", None)
            for i, col_label in enumerate(self._column_labels):
                combo.addItem(col_label, i)
            guessed = self._guess_column(key, guess_keywords, header_row)
            if guessed is not None:
                combo.setCurrentIndex(guessed + 1)
            form.addRow(("* " if required else "") + label + ":", combo)
            self.field_combos[key] = combo
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _guess_column(self, field_key: str, guess_keywords: dict[str, list[str]], header_row: tuple) -> int | None:
        keywords = guess_keywords.get(field_key, [])
        for i, value in enumerate(header_row):
            text = str(value).strip() if value is not None else ""
            if any(kw in text for kw in keywords):
                return i
        return None

    def _on_accept(self) -> None:
        for key, _label, required in self._target_fields:
            if required and self.field_combos[key].currentData() is None:
                QMessageBox.warning(self, "ناقص", "همه‌یِ فیلدهایِ الزامی (*) باید مشخص شوند.")
                return
        self.accept()

    def mapping(self) -> dict[str, int | None]:
        return {key: combo.currentData() for key, combo in self.field_combos.items()}

    def skip_header_row(self) -> bool:
        return self.header_checkbox.isChecked()


def read_excel_rows(parent_widget: QWidget, path: str) -> list[tuple] | None:
    """بازکردنِ فایلِ اکسل یا CSV و برگرداندنِ ردیف‌هایِ غیرِخالی؛ در صورتِ
    خطا، پیغام به کاربر نمایش داده و None برمی‌گردد. طبقِ خواستهٔ صریح
    («دستگاه‌هایِ حضوروغیاب معمولاً CSV خروجی می‌دهند»)، پسوندِ .csv هم
    کنارِ .xlsx/.xls پشتیبانی می‌شود."""
    if path.lower().endswith(".csv"):
        return _read_csv_rows(parent_widget, path)

    import openpyxl

    try:
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
        worksheet = workbook.active
        rows = [row for row in worksheet.iter_rows(values_only=True) if any(c is not None for c in row)]
    except Exception as exc:
        QMessageBox.critical(parent_widget, "خطا در خواندنِ فایل", f"فایلِ اکسل قابلِ‌خواندن نبود:\n{exc}")
        return None
    if not rows:
        QMessageBox.warning(parent_widget, "فایلِ خالی", "فایلِ انتخاب‌شده هیچ ردیفی ندارد.")
        return None
    return rows


def _read_csv_rows(parent_widget: QWidget, path: str) -> list[tuple] | None:
    import csv

    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            sample = f.read(4096)
            f.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
            except csv.Error:
                dialect = csv.excel
            rows = [tuple(row) for row in csv.reader(f, dialect) if any(c.strip() for c in row)]
    except Exception as exc:
        QMessageBox.critical(parent_widget, "خطا در خواندنِ فایل", f"فایلِ CSV قابلِ‌خواندن نبود:\n{exc}")
        return None
    if not rows:
        QMessageBox.warning(parent_widget, "فایلِ خالی", "فایلِ انتخاب‌شده هیچ ردیفی ندارد.")
        return None
    return rows
