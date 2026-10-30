"""R362: گواهی آنالیز — صدور از بازرسی تأییدشده، پیوند به مشتری و سند فروش، چاپ و Excel، لغو با دلیل."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QInputDialog, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from peecha import numerals
from peecha.db.base import new_session
from peecha.services.qms import certificates as coa
from peecha.ui import report_export, theme
from peecha.ui.screens.fixed_assets import P, combo, company_id, fill, selected_data, table, user_id
from peecha.ui.widgets import FieldGrid, FieldSpec, JalaliDateEdit, build_page_header


def _btn(label: str, glyph: str, kind: str = "") -> QPushButton:
    button = QPushButton(glyph)
    button.setToolTip(label)
    button.setAccessibleName(label)
    button.setObjectName({"primary": "primaryIconButton", "danger": "dangerIconButton"}.get(kind, "iconButton"))
    button.setFixedWidth(48 if kind == "primary" else 44)
    button.setCursor(Qt.PointingHandCursor)
    return button


def _sales_documents(cid: int) -> list[tuple[str, int]]:
    from sqlalchemy import select

    from peecha.db.models.accounting import DetailAccount
    from peecha.db.models.commercial import CommercialDocument

    labels = {"SALES_ORDER": "سفارش فروش", "SALES_INVOICE": "فاکتور فروش"}
    with new_session() as session:
        rows = session.execute(select(CommercialDocument.document_id, CommercialDocument.document_type_code,
                                      CommercialDocument.document_no, DetailAccount.name)
                               .join(DetailAccount, DetailAccount.detail_account_id == CommercialDocument.counterparty_detail_account_id)
                               .where(CommercialDocument.company_id == cid, CommercialDocument.document_type_code.in_(list(labels)),
                                      CommercialDocument.status_code != "CANCELLED")
                               .order_by(CommercialDocument.document_id.desc()).limit(300)).all()
    return [(f"{labels[t]} {no} — {name}", did) for did, t, no, name in rows]


class QcCertificatesScreen(QWidget):
    def __init__(self, main_window=None) -> None:
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self.eligible: list = []
        self.certificates: list = []
        layout = QVBoxLayout(self)
        layout.addWidget(build_page_header(
            "گواهی آنالیز", "برای بازرسی تأییدشده‌ای که همهٔ پارامترهای الزامی‌اش در حد مجاز است گواهی صادر کنید؛ نتایج هنگام "
            "صدور ثابت می‌ماند و گواهی فقط با ذکر دلیل لغو می‌شود."))
        layout.addWidget(QLabel("بازرسی‌های قابل صدور گواهی"))
        self.eligible_table = table(["بازرسی", "کالا", "بچ", "مرحله", "نتیجه", "تاریخ تأیید", "گواهی صادرشده"])
        layout.addWidget(self.eligible_table, 1)
        self.customer_combo, self.document_combo = combo([], "—"), combo([], "—")
        self.date_field = JalaliDateEdit()
        self.notes_field = QLineEdit()
        row = QHBoxLayout()
        row.addWidget(FieldGrid([FieldSpec("coa_document", "سند فروش (اختیاری)", self.document_combo, span=2),
                                 FieldSpec("coa_customer", "مشتری (اختیاری)", self.customer_combo, span=2),
                                 FieldSpec("coa_date", "تاریخ صدور", self.date_field, span=1),
                                 FieldSpec("coa_notes", "توضیح", self.notes_field, span=2)]), 1)
        issue = _btn("صدور گواهی برای بازرسی انتخاب‌شده", "📜", "primary")
        issue.clicked.connect(self.issue)
        row.addWidget(issue)
        layout.addLayout(row)
        layout.addWidget(QLabel("گواهی‌های صادرشده"))
        self.cert_table = table(["شماره", "کالا", "بچ", "مشتری", "سند فروش", "تاریخ صدور", "وضعیت"])
        layout.addWidget(self.cert_table, 1)
        bar = QHBoxLayout()
        for label, glyph, kind, slot in (("چاپ گواهی انتخاب‌شده", "🖨️", "", self.print_certificate),
                                         ("خروجی Excel گواهی انتخاب‌شده", "📊", "", self.export_certificate),
                                         ("لغو گواهی انتخاب‌شده", "🚫", "danger", self.revoke),
                                         ("به‌روزرسانی", "🔄", "", self.refresh)):
            button = _btn(label, glyph, kind)
            button.clicked.connect(slot)
            bar.addWidget(button)
        bar.addStretch(1)
        layout.addLayout(bar)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.ask_reason = None  # برای آزمون: تابعی که دلیل لغو را برمی‌گرداند

    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        from peecha.services import detail_dimensions as dims

        for box, items in ((self.customer_combo, [(f"{c['code']} — {c['name'] or ''}", c["detail_account_id"]) for c in dims.list_customers(cid)]),
                           (self.document_combo, _sales_documents(cid))):
            current = box.currentData()
            box.clear()
            box.addItem("—", None)
            for label, data in items:
                box.addItem(P(label), data)
            index = box.findData(current)
            box.setCurrentIndex(index if index >= 0 else 0)
        self.eligible = coa.eligible_inspections(cid)
        fill(self.eligible_table, [[P(e.inspection_id), e.item_label, e.batch_no or "—", e.stage_label, e.result_label,
                                    numerals.format_jalali_date(e.approved_at.date()) if e.approved_at else "",
                                    P(e.certificates)] for e in self.eligible], [e.inspection_id for e in self.eligible])
        self.certificates = coa.list_certificates(cid)
        fill(self.cert_table, [[P(c.certificate_no), c.item_label, c.batch_no or "—", c.customer or "—",
                                P(c.sales_document_no) if c.sales_document_no else "—", c.issue_date, c.status_label]
                               for c in self.certificates], [c.certificate_id for c in self.certificates])

    def issue(self) -> int | None:
        inspection_id = selected_data(self.eligible_table)
        if inspection_id is None:
            theme.set_status_label(self.status_label, "یک بازرسی را از فهرست انتخاب کنید.", ok=False)
            return None
        try:
            cert_id = coa.issue(company_id(), user_id(), inspection_id, customer_id=self.customer_combo.currentData(),
                                sales_document_id=self.document_combo.currentData(), issue_date=self.date_field.date(),
                                notes=self.notes_field.text())
        except ValueError as exc:
            theme.set_status_label(self.status_label, str(exc), ok=False)
            return None
        self.notes_field.clear()
        self.refresh()
        theme.set_status_label(self.status_label, "گواهی صادر شد.", ok=True)
        return cert_id

    def _selected(self):
        cert_id = selected_data(self.cert_table)
        if cert_id is None:
            theme.set_status_label(self.status_label, "یک گواهی را از فهرست انتخاب کنید.", ok=False)
            return None
        return coa.get_certificate(company_id(), cert_id)

    def print_certificate(self) -> bool:
        cert = self._selected()
        if cert is None:
            return False
        title, headers, rows, head = coa.print_table(cert)
        report_export.print_report(self, title, headers, rows, filters=head)
        return True

    def export_certificate(self) -> bool:
        cert = self._selected()
        if cert is None:
            return False
        title, headers, rows, head = coa.print_table(cert)
        report_export.export_report_excel(self, title, headers, rows, filters=head)
        return True

    def revoke(self) -> bool:
        cert = self._selected()
        if cert is None:
            return False
        if self.ask_reason is not None:
            reason, ok = self.ask_reason(), True
        else:
            reason, ok = QInputDialog.getText(self, "لغو گواهی", "دلیل لغو گواهی:")
        if not ok:
            return False
        try:
            coa.revoke(company_id(), user_id(), cert.certificate_id, reason)
        except ValueError as exc:
            theme.set_status_label(self.status_label, str(exc), ok=False)
            return False
        self.refresh()
        theme.set_status_label(self.status_label, "گواهی لغو شد.", ok=True)
        return True
