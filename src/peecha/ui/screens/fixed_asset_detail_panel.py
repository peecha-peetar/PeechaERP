"""R318: پنل شناسنامهٔ دارایی ثابت داخل فرم «تعریف تفصیلی» (هم‌الگو با پنل کالا).

همهٔ فیلدهای ثبت دارایی (همان ویزارد «ثبت دارایی» به‌علاوهٔ شمارهٔ قطعه، بارکد، دارایی اصلی، ارز، خط تولید، نرخ ماشین،
ظرفیت و یادداشت) در کارت‌های برچسب‌دار؛ بهای تحصیل فقط هنگام تعریف. عملیات مالی بعدی در «دارایی‌ها» است."""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from peecha import decimals
from peecha.services.fixed_assets import assets as fa
from peecha.services.fixed_assets import common as fac
from peecha.ui.screens import module_style as ms
from peecha.ui.screens.fixed_assets import Lookups, P, combo, date_field, dec, money, num_field, set_combo
from peecha.ui.screens.costing import can

# فیلدهایی که بعد از پیش‌نویس فقط با «انتقال/تغییر طبقه» عوض می‌شوند (قاعدهٔ update_asset)
_LOCKED_AFTER_DRAFT = ("category_id", "location_id", "custodian_employee_id", "cost_center_detail_account_id", "branch_id",
                       "department_id")


def _section(title: str) -> QLabel:
    label = QLabel(title)
    label.setObjectName("sectionTitle")
    return label


class AssetDetailPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.asset = None
        self.lk: Lookups | None = None
        self._company_id: int | None = None
        self.w: dict[str, QWidget] = {}
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)
        self.status_label = QLabel("")
        self.status_label.setObjectName("sectionHint")
        self.status_label.setWordWrap(True)
        self.open_button = QPushButton("🏭")
        self.open_button.setObjectName("iconButton")
        self.open_button.setFixedWidth(44)
        self.open_button.setToolTip("بازکردن در «دارایی‌ها» برای عملیات مالی (سرمایه‌ای‌کردن، انتقال، استهلاک، فروش)")
        self.open_button.clicked.connect(self.open_in_assets)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.addWidget(self.status_label, stretch=1)
        head.addWidget(self.open_button)
        self._layout.addLayout(head)
        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(6)
        self._layout.addWidget(self._body)

    # --- ساخت ---------------------------------------------------------------------------------
    def _build(self) -> None:
        w = self.w
        w["asset_code"] = QLineEdit()
        w["asset_code"].setPlaceholderText("خالی = همان کد تفصیلی")
        for key in ("category_id", "group_id", "asset_type_code", "parent_asset_id", "source_code", "depreciation_method",
                    "useful_life_unit", "location_id", "cost_center_detail_account_id", "project_detail_account_id",
                    "custodian_employee_id", "branch_id", "department_id", "supplier_detail_account_id", "currency_id",
                    "offset_account"):
            w[key] = combo([])
        for key in ("brand", "model", "serial_no", "part_no", "barcode", "description", "invoice_reference",
                    "work_center_code", "production_line", "notes"):
            w[key] = QLineEdit()
        for key in ("useful_life", "residual_value", "declining_rate", "exchange_rate", "purchase_price_fc", "machine_rate",
                    "capacity_per_hour", "standard_hours", "purchase", "transport", "installation", "other_cost"):
            w[key] = num_field()
        w["acquisition_date"], w["in_service_date"] = date_field(), date_field()
        w["is_production_machine"] = QCheckBox("ماشین تولیدی")
        # بهای تحصیل (فقط هنگام تعریف؛ همان مسیر ویزارد: تحصیل و درخواست سرمایه‌ای‌شدن)
        w["capitalize"] = QCheckBox("همین حالا سرمایه‌ای و در بهره‌برداری شود")

        add = self._body_layout.addWidget
        add(_section("شناسنامه"))
        add(ms.field_grid([("کد دارایی", w["asset_code"]), ("طبقهٔ دارایی", w["category_id"]), ("گروه", w["group_id"]),
                           ("نوع", w["asset_type_code"]), ("برند", w["brand"]), ("مدل", w["model"]),
                           ("شمارهٔ سریال", w["serial_no"]), ("شمارهٔ قطعه", w["part_no"]), ("بارکد", w["barcode"]),
                           ("دارایی اصلی (برای جزء)", w["parent_asset_id"]), ("شرح", w["description"])], columns=4))
        add(_section("روش استهلاک"))
        add(ms.field_grid([("روش استهلاک", w["depreciation_method"]), ("عمر مفید (خالی = پیش‌فرض)", w["useful_life"]),
                           ("واحد عمر", w["useful_life_unit"]), ("ارزش اسقاط", w["residual_value"]),
                           ("نرخ نزولی سالانه", w["declining_rate"])], columns=5))
        add(_section("محل و مرکز هزینه"))
        add(ms.field_grid([("محل", w["location_id"]), ("مرکز هزینه", w["cost_center_detail_account_id"]),
                           ("پروژه", w["project_detail_account_id"]), ("تحویل‌گیرنده", w["custodian_employee_id"]),
                           ("شعبه", w["branch_id"]), ("دپارتمان", w["department_id"])], columns=3))
        add(_section("خرید"))
        add(ms.field_grid([("منبع", w["source_code"]), ("تامین‌کننده", w["supplier_detail_account_id"]),
                           ("تاریخ تحصیل", w["acquisition_date"]), ("شمارهٔ فاکتور", w["invoice_reference"]),
                           ("ارز خرید", w["currency_id"]), ("نرخ ارز", w["exchange_rate"]),
                           ("قیمت ارزی", w["purchase_price_fc"])], columns=4))
        add(_section("تولید"))
        add(ms.field_grid([("", w["is_production_machine"]), ("مرکز کار", w["work_center_code"]),
                           ("خط تولید", w["production_line"]), ("نرخ ماشین (هر ساعت)", w["machine_rate"]),
                           ("ظرفیت در ساعت", w["capacity_per_hour"]), ("ساعت استاندارد سالانه", w["standard_hours"])],
                          columns=3))
        add(ms.field_grid([("یادداشت", w["notes"])], columns=1))
        self.cost_title = _section("بهای تحصیل (فقط هنگام تعریف)")
        add(self.cost_title)
        self.cost_box = ms.field_grid([("قیمت خرید", w["purchase"]), ("حمل", w["transport"]),
                                       ("نصب/راه‌اندازی", w["installation"]), ("سایر هزینه‌های سرمایه‌ای", w["other_cost"]),
                                       ("حساب طرف مقابل", w["offset_account"]), ("", w["capitalize"]),
                                       ("تاریخ بهره‌برداری", w["in_service_date"])], columns=4)
        add(self.cost_box)

    def refresh(self, company_id: int) -> None:
        """فهرست‌ها با دادهٔ تازه پر می‌شوند (طبقه، محل، مرکز هزینه، ...)؛ خود فیلدها یک بار ساخته می‌شوند."""
        from peecha.services import currencies as currencies_service

        if not self.w:
            self._build()
        self._company_id = company_id
        fac.ensure_default_categories(company_id)
        self.lk = lk = Lookups(company_id)
        currencies = [(c.iso_code, c.currency_id) for c in currencies_service.list_company_currencies(company_id)
                      if getattr(c, "is_enabled", False) and not getattr(c, "is_base", False)]
        lists = {
            "category_id": (lk.categories, None), "group_id": (lk.groups, "— بدون گروه —"),
            "asset_type_code": ([(v, k) for k, v in fac.TYPE_LABELS.items()], None),
            "parent_asset_id": ([(f"{r.asset_code} — {r.name}", r.asset_id) for r in fa.list_assets(company_id)],
                                "— دارایی مستقل —"),
            "source_code": ([(v, k) for k, v in fa.SOURCE_LABELS.items()], None),
            "depreciation_method": ([(v, k) for k, v in fac.METHOD_LABELS.items()], "— پیش‌فرض طبقه —"),
            "useful_life_unit": ([("ماه", "MONTH"), ("سال", "YEAR"), ("ساعت کار", "HOUR"), ("واحد تولید", "UNIT")], None),
            "location_id": (lk.locations, "— محل —"),
            "cost_center_detail_account_id": (lk.cost_centers, "— مرکز هزینه (پیش‌فرض طبقه) —"),
            "project_detail_account_id": (lk.projects, "— پروژه —"),
            "custodian_employee_id": (lk.employees, "— تحویل‌گیرنده —"), "branch_id": (lk.branches, "— شعبه —"),
            "department_id": (lk.departments, "— دپارتمان —"),
            "supplier_detail_account_id": (lk.suppliers, "— تامین‌کننده —"), "currency_id": (currencies, "— ارز پایه —"),
            "offset_account": (lk.accounts, "— حساب طرف مقابل (پرداختنی/بانک) —"),
        }
        for key, (items, none_label) in lists.items():
            box = self.w[key]
            box.blockSignals(True)
            box.clear()
            box._legacy_labels = getattr(items, "legacy", None)
            if none_label is not None:
                box.addItem(none_label, None)
            for label, data in items:
                box.addItem(P(label), data)
            box.blockSignals(False)
        self.load(None)

    # --- بارگذاری/خواندن ---------------------------------------------------------------------------
    def load(self, asset) -> None:
        """None = دارایی تازه."""
        self.asset = asset
        if not self.w:
            return
        w = self.w
        f = fa.fields_of(asset) if asset is not None else fa.AssetFields(asset_code="", name="", category_id=0)
        w["asset_code"].setText(f.asset_code or "")
        for key in ("category_id", "group_id", "parent_asset_id", "depreciation_method", "location_id",
                    "cost_center_detail_account_id", "project_detail_account_id", "custodian_employee_id", "branch_id",
                    "department_id", "supplier_detail_account_id", "currency_id"):
            set_combo(w[key], getattr(f, key))
        set_combo(w["asset_type_code"], f.asset_type_code)
        set_combo(w["source_code"], f.source_code if asset is not None else "PURCHASE")
        set_combo(w["useful_life_unit"], f.useful_life_unit)
        for key in ("brand", "model", "serial_no", "part_no", "barcode", "description", "invoice_reference",
                    "work_center_code", "production_line", "notes"):
            w[key].setText(getattr(f, key) or "")
        for key in ("useful_life", "residual_value", "declining_rate", "exchange_rate", "purchase_price_fc", "machine_rate",
                    "capacity_per_hour", "standard_hours"):
            value = getattr(f, key)
            w[key].setText("" if value is None else decimals.plain(value))
        w["is_production_machine"].setChecked(bool(f.is_production_machine))
        if f.acquisition_date:
            w["acquisition_date"].setDate(f.acquisition_date)
        for key in ("purchase", "transport", "installation", "other_cost"):
            w[key].clear()
        w["capitalize"].setChecked(False)
        is_new = asset is None
        self.cost_title.setVisible(is_new)
        self.cost_box.setVisible(is_new)
        locked = asset is not None and asset.status_code != "DRAFT"
        for key in _LOCKED_AFTER_DRAFT:
            w[key].setEnabled(not locked)
            w[key].setToolTip("بعد از پیش‌نویس فقط از «انتقال» یا «تغییر طبقه» در دارایی‌ها عوض می‌شود." if locked else "")
        self.open_button.setVisible(asset is not None)
        if asset is None:
            self.status_label.setText("دارایی جدید: با ذخیره، حساب تفصیلی و شناسنامهٔ دارایی با هم ساخته می‌شوند.")
        else:
            cost = (f" — بهای تمام‌شده {money(asset.gross_cost)} — ارزش دفتری {money(asset.book_value)}"
                    if can("fa_cost_view", "VIEW") else "")
            self.status_label.setText(P(f"وضعیت: {fac.STATUS_LABELS.get(asset.status_code, asset.status_code)}{cost}"))

    def fields(self, code: str = "", name: str = "") -> fa.AssetFields:
        w = self.w
        num = {k: dec(w[k].text()) for k in ("useful_life", "residual_value", "declining_rate", "exchange_rate",
                                              "purchase_price_fc", "machine_rate", "capacity_per_hour", "standard_hours")}
        text = {k: w[k].text().strip() or None for k in ("brand", "model", "serial_no", "part_no", "barcode", "description",
                                                          "invoice_reference", "work_center_code", "production_line", "notes")}
        return fa.AssetFields(
            asset_code=w["asset_code"].text().strip() or code, name=name, category_id=w["category_id"].currentData(),
            asset_type_code=w["asset_type_code"].currentData(), group_id=w["group_id"].currentData(),
            parent_asset_id=w["parent_asset_id"].currentData(), source_code=w["source_code"].currentData() or "MANUAL",
            acquisition_date=w["acquisition_date"].date(), residual_value=num["residual_value"] or None,
            useful_life=num["useful_life"] or None,
            useful_life_unit=w["useful_life_unit"].currentData() if num["useful_life"] else "MONTH",
            depreciation_method=w["depreciation_method"].currentData(), declining_rate=num["declining_rate"] or None,
            location_id=w["location_id"].currentData(),
            cost_center_detail_account_id=w["cost_center_detail_account_id"].currentData(),
            project_detail_account_id=w["project_detail_account_id"].currentData(),
            custodian_employee_id=w["custodian_employee_id"].currentData(), branch_id=w["branch_id"].currentData(),
            department_id=w["department_id"].currentData(), supplier_detail_account_id=w["supplier_detail_account_id"].currentData(),
            currency_id=w["currency_id"].currentData(), exchange_rate=num["exchange_rate"] or None,
            purchase_price_fc=num["purchase_price_fc"] or None, is_production_machine=w["is_production_machine"].isChecked(),
            machine_rate=num["machine_rate"] or None, capacity_per_hour=num["capacity_per_hour"] or None,
            standard_hours=num["standard_hours"] or None, **text)

    def costs(self) -> list[fa.CostItem]:
        w = self.w
        account, supplier = w["offset_account"].currentData(), w["supplier_detail_account_id"].currentData()
        out = []
        for key, cost_type in (("purchase", "PURCHASE"), ("transport", "TRANSPORT"), ("installation", "INSTALLATION"),
                               ("other_cost", "OTHER")):
            amount = dec(w[key].text())
            if amount > 0:
                out.append(fa.CostItem(cost_type, amount, account, supplier if cost_type == "PURCHASE" else None,
                                       w["invoice_reference"].text().strip() or None))
        return out

    def post_acquisition(self, company_id: int, user_id: int, asset_id: int) -> str | None:
        """بعد از ساخت دارایی تازه: همان مسیر ویزارد (تحصیل و درخواست سرمایه‌ای‌شدن). خروجی: پیام خطا یا None."""
        from peecha.services.fixed_assets import approval

        items = self.costs()
        if not items:
            return None
        date = self.w["acquisition_date"].date()
        try:
            fa.acquire(company_id, user_id, asset_id, date, items, source_code="PURCHASE")
            if self.w["capitalize"].isChecked():
                approval.request(company_id, user_id, "CAPITALIZE", asset_id, date=date,
                                 in_service_date=self.w["in_service_date"].date())
        except ValueError as exc:
            return f"دارایی ثبت شد ولی بهای تحصیل ثبت نشد: {exc}"
        return None

    def open_in_assets(self) -> None:
        window = self.window()
        if self.asset is not None and hasattr(window, "open_screen"):
            asset_id = self.asset.asset_id
            window.open_screen("FA_ASSETS", then=lambda s: s.open_asset(asset_id))
