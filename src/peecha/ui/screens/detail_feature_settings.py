"""R318: «تنظیمات › کدینگ حسابداری › قابلیت‌های تفصیلی» — کلیدهای روشن/خاموش تعریف دارایی در فرم تفصیلی، انتقال مانده
و ادغام کامل. هر کلید پیش‌فرض خاموش است؛ دسترسی اجرای انتقال/ادغام جداگانه در «نقش‌ها و دسترسی‌ها» داده می‌شود."""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QLabel, QVBoxLayout, QWidget

from peecha import session as app_session
from peecha.services import detail_operations as ops
from peecha.services import inventory_engine as engine
from peecha.services.fixed_assets import detail_form as asset_detail_form
from peecha.ui import theme
from peecha.ui.widgets import FieldHelpMixin

FEATURES = (asset_detail_form.FEATURE, ops.FEATURE_TRANSFER, ops.FEATURE_MERGE)


class DetailFeatureSettingsScreen(FieldHelpMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.toggles: dict[str, QCheckBox] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(8)
        title = QLabel("قابلیت‌های تفصیلی")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        hint = QLabel("اجرای انتقال مانده و ادغام، علاوه بر روشن‌بودن کلید، دسترسی جداگانه در «نقش‌ها و دسترسی‌ها» لازم دارد: "
                      f"«{ops.FORM_LABELS[ops.FORM_TRANSFER]}» و «{ops.FORM_LABELS[ops.FORM_MERGE]}».")
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.toggle_layout = QVBoxLayout()
        layout.addLayout(self.toggle_layout)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        layout.addStretch(1)

    def refresh(self) -> None:
        company = app_session.current_company
        if company is None:
            return
        features = {f.feature_code: f for f in engine.list_features(company.company_id)}
        if not self.toggles:
            descriptions = engine.feature_descriptions()
            helps = []
            for code in FEATURES:
                f = features.get(code)
                if f is None:
                    continue
                box = QCheckBox(f.name)
                box.toggled.connect(lambda checked, k=code: self._toggle(k, checked))
                note = QLabel(descriptions.get(code, ""))
                note.setObjectName("sectionHint")
                note.setWordWrap(True)
                note.setContentsMargins(24, 0, 0, 6)
                self.toggle_layout.addWidget(box)
                self.toggle_layout.addWidget(note)
                self.toggles[code] = box
                helps.append((box, descriptions.get(code, "") or f.name))
            self.set_field_help(helps)
        for code, box in self.toggles.items():
            box.blockSignals(True)
            box.setChecked(features[code].is_enabled)
            box.blockSignals(False)

    def _toggle(self, code: str, checked: bool) -> None:
        company = app_session.current_company
        try:
            engine.set_feature_enabled(company.company_id, code, checked)
        except ValueError as exc:
            box = self.toggles[code]
            box.blockSignals(True)
            box.setChecked(not checked)
            box.blockSignals(False)
            theme.set_status_label(self.status_label, str(exc), ok=False)
            return
        theme.set_status_label(self.status_label, f"«{self.toggles[code].text()}» {'روشن' if checked else 'خاموش'} شد.", ok=True)
