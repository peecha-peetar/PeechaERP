"""صفحه‌های مدیریت ارتباط با مشتری — R281.

پروندهٔ ۳۶۰ مشتری، مرکز کارها، سرنخ‌ها، قیف فروش (Kanban) و تنظیمات. همهٔ منطق در services/crm است و داده‌های
مالی/فروش از همان سرویس‌های ERP خوانده می‌شود؛ اینجا فقط نمایش و فراخوانی.
"""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QScrollArea, QSplitter, QTableWidget, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from peecha import numerals
from peecha.services.crm import activities as act_service
from peecha.services.crm import analytics
from peecha.services.crm import campaigns as camp_service
from peecha.services.crm import common as cc
from peecha.services.crm import customer360 as c360
from peecha.services.crm import leads as lead_service
from peecha.services.crm import loyalty as loyalty_service
from peecha.services.crm import opportunities as opp_service
from peecha.services.crm import opportunity_sales as opp_sales
from peecha.services.crm import pipelines as pl_service
from peecha.services.crm import segments as seg_service
from peecha.services.crm import tasks as task_service
from peecha.ui.screens import module_style as ms
from peecha.ui.screens.costing import can
from peecha.ui.screens.fixed_assets import (
    FormDialog, P, combo, company_id, date_field, fill, money, num_field, set_combo, table, user_id,
)

ZERO = decimal.Decimal(0)
_RED, _AMBER, _GREEN = QColor("#EF4444"), QColor("#F59E0B"), QColor("#10B981")
_CREDIT_TONE = {"OK": "success", "NEAR_LIMIT": "warning", "OVERDUE": "danger", "OVER_LIMIT": "danger"}


def _date(value) -> str:
    return numerals.format_jalali_date(value) if value else "—"


def _ask(parent, title: str, fields, hint: str = "") -> dict | None:
    dlg = FormDialog(title, fields, hint, parent)
    if getattr(parent, "dialog_runner", None):
        return dlg.values() if parent.dialog_runner(dlg) else None
    return dlg.values() if dlg.exec() == QDialog.Accepted else None


def _run(parent, title: str, fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs), True
    except ValueError as exc:
        QMessageBox.warning(parent, title, str(exc))
        return None, False


def _confirm(parent, title: str, text: str) -> bool:
    runner = getattr(parent, "confirm", None)
    if runner is not None:
        return runner(text)
    return QMessageBox.question(parent, title, text) == QMessageBox.Yes


def _selected(t: QTableWidget):
    items = t.selectedItems()
    return t.item(items[0].row(), 0).data(Qt.UserRole) if items else None


def _quick(label: str, slot) -> QPushButton:
    b = QPushButton(label)
    b.setObjectName("quickAction")
    b.setCursor(Qt.PointingHandCursor)
    b.clicked.connect(lambda _c=False: slot())
    return b


def _text(value) -> QTextEdit:
    w = QTextEdit()
    w.setPlainText(value or "")
    w.setMaximumHeight(90)
    return w


_DOC_NAV = {"SALES_ORDER": "SALES_ORDER", "SALES_PROFORMA": "SALES_PROFORMA", "SALES_INVOICE": "SALES_INVOICE",
            "SALES_RETURN": "SALES_RETURN"}


def open_document(main_window, document_type_code: str, document_id: int) -> None:
    """سند فروش در همان فرم فروش ERP باز می‌شود (تأیید، تبدیل به فاکتور، ثبت و تسویه همان‌جا)."""
    nav = _DOC_NAV.get(document_type_code)
    if main_window is not None and nav:
        main_window.open_screen(nav, then=lambda screen: screen.edit_document(document_id))


class CrmLookups:
    """فهرست‌های مشترک فرم‌های CRM (یک بار در هر refresh)."""

    def __init__(self, cid: int) -> None:
        from peecha.services import detail_dimensions as dims
        from peecha.services import inventory_catalog as catalog

        self.users = [(name, uid) for uid, name in cc.list_company_users(cid)]
        self.sources = [(s.name, s.source_id) for s in pl_service.list_lead_sources(cid)]
        self.customers = [(f"{c['code']} — {c['name']}", c["detail_account_id"]) for c in dims.list_customers(cid)]
        self.items = [(f"{i.code} — {i.name or ''}", i.item_id)
                      for i in catalog.list_items(cid, active_only=True, transactable_only=True) if i.is_sellable]
        self.activity_types = [(label, code) for code, label in cc.ACTIVITY_TYPES.items() if code != "OPPORTUNITY"]
        self.priorities = [(label, code) for code, label in cc.PRIORITIES.items()]


def activity_form(lk: CrmLookups, row: act_service.ActivityRow | None = None, kind: str | None = None,
                  with_party: bool = False) -> list:
    g = (lambda name, default=None: getattr(row, name)) if row else (lambda name, default=None: default)
    fields = [("activity_type_code", "نوع", _with(combo(lk.activity_types), g("activity_type_code", kind or "CALL"))),
              ("subject", "موضوع", QLineEdit(g("subject", "") or ""))]
    if with_party:
        fields.append(("customer_detail_account_id", "مشتری", _with(combo(lk.customers, "—"), g("customer_detail_account_id"))))
    fields += [("due_date", "تاریخ", date_field(g("due_date") or datetime.date.today())),
               ("duration_minutes", "مدت (دقیقه)", num_field(g("duration_minutes"))),
               ("priority_code", "اولویت", _with(combo(lk.priorities), g("priority_code", "NORMAL"))),
               ("assigned_to_user_id", "مسئول", _with(combo(lk.users, "— خودم —"), g("assigned_to_user_id"))),
               ("next_action", "اقدام بعدی", QLineEdit(g("next_action", "") or "")),
               ("description", "توضیحات", _text(g("description")))]
    return fields


def _with(box: QComboBox, value) -> QComboBox:
    set_combo(box, value)
    return box


def activity_fields(values: dict, **party) -> act_service.ActivityFields:
    duration = values.get("duration_minutes")
    return act_service.ActivityFields(
        values["activity_type_code"], values.get("subject") or "", description=values.get("description"),
        due_date=values.get("due_date"), duration_minutes=int(duration) if duration else None,
        priority_code=values.get("priority_code") or "NORMAL", assigned_to_user_id=values.get("assigned_to_user_id"),
        next_action=values.get("next_action"), **party)


def complete_form() -> list:
    return [("result", "نتیجه", _text("")), ("follow", "پیگیری بعدی لازم است", QCheckBox()),
            ("follow_date", "تاریخ پیگیری", date_field(datetime.date.today() + datetime.timedelta(days=3))),
            ("follow_subject", "موضوع پیگیری", QLineEdit())]


def complete_activity(parent, activity_id: int, values: dict | None = None) -> bool:
    values = values if values is not None else _ask(parent, "انجام فعالیت", complete_form())
    if values is None:
        return False
    _r, ok = _run(parent, "فعالیت", act_service.complete_activity, company_id(), user_id(), activity_id, values.get("result"),
                  follow_up_date=values.get("follow_date") if values.get("follow") else None,
                  follow_up_subject=values.get("follow_subject"))
    return ok


# =========================================================================================================
# پروندهٔ ۳۶۰ مشتری
# =========================================================================================================
@ms.styled
class Customer360Screen(QWidget):
    """مهم‌ترین صفحهٔ CRM: هویت + سلامت اعتباری + مانده + اقدامات سریع در بالا؛ جزئیات در تب‌ها (تنبل)."""

    scroll_in_mdi = True
    TABS = (("overview", "نمای کلی"), ("timeline", "تایم‌لاین"), ("sales", "فروش"), ("payments", "دریافت‌ها"),
            ("activities", "فعالیت‌ها"), ("visits", "ویزیت‌ها"), ("tickets", "شکایت و پشتیبانی"),
            ("opportunities", "فرصت‌ها"), ("notes", "یادداشت‌ها"), ("documents", "اسناد"))
    PAGE = 50

    def __init__(self, main_window=None) -> None:
        super().__init__()
        self._main_window = main_window
        self.dialog_runner = None
        self.lk: CrmLookups | None = None
        self.customer_id: int | None = None
        self.data: dict | None = None
        self._loaded: set[str] = set()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        title = QLabel("پروندهٔ ۳۶۰ مشتری")
        title.setObjectName("pageTitle")
        self.customer_box = QComboBox()
        self.customer_box.setEditable(True)
        self.customer_box.setMinimumWidth(360)
        self.customer_box.lineEdit().setPlaceholderText("جستجوی مشتری: نام، کد، موبایل")
        self.customer_box.activated.connect(lambda _i: self.load_customer(self.customer_box.currentData()))
        outer.addWidget(ms.header_card(title, self.customer_box))
        # هویت + وضعیت
        self.ident_label = QLabel("مشتری را انتخاب کنید.")
        self.ident_label.setObjectName("sectionTitle")
        self.ident_label.setWordWrap(True)
        self.chips_label = QLabel("")
        self.chips_label.setWordWrap(True)
        self.chips_label.setObjectName("sectionHint")
        ident = QWidget()
        il = QVBoxLayout(ident)
        il.setContentsMargins(0, 0, 0, 0)
        il.addWidget(self.ident_label)
        il.addWidget(self.chips_label)
        outer.addWidget(ident)
        cards, self.cards = ms.summary([
            ("balance", "ماندهٔ حساب", "info", "💳"), ("credit", "وضعیت اعتباری", "success", "🛡️"),
            ("overdue", "بدهی معوق", "danger", "⏰"), ("sales", "مجموع خرید", "success", "🛒"),
            ("year", "خرید امسال", "info", "📅"), ("last", "آخرین خرید", "neutral", "🕒"),
            ("interval", "فاصلهٔ خرید", "neutral", "🔁"), ("pipeline", "فرصت‌های باز", "warning", "🎯")], per_row=8)
        outer.addWidget(cards)
        # اقدامات سریع
        self.quick = {
            "call": _quick("📞 تماس", lambda: self.quick_activity("CALL")),
            "task": _quick("✅ وظیفه", lambda: self.quick_activity("TASK")),
            "visit": _quick("🚚 ویزیت", lambda: self.quick_activity("VISIT")),
            "note": _quick("💬 یادداشت", lambda: self.quick_activity("NOTE")),
            "opportunity": _quick("🎯 فرصت", self.new_opportunity),
            "order": _quick("🛒 سفارش", lambda: self.new_order()),
            "payment": _quick("💰 دریافت", lambda: self.open_erp("TREASURY_RECEIPT")),
            "ticket": _quick("⚠️ شکایت", lambda: self.quick_activity("COMPLAINT")),
        }
        bar = QHBoxLayout()
        for b in self.quick.values():
            bar.addWidget(b)
        bar.addStretch(1)
        outer.addLayout(bar)
        self.tabs = QTabWidget()
        self.tab_widgets: dict[str, QWidget] = {}
        self._build_tabs()
        self.tabs.currentChanged.connect(lambda _i: self._load_current_tab())
        outer.addWidget(self.tabs, stretch=1)
        self._set_enabled(False)

    # --- ساخت تب‌ها ------------------------------------------------------------------------------
    def _build_tabs(self) -> None:
        ov = QWidget()
        ol = QVBoxLayout(ov)
        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        self.summary_label.setObjectName("sectionHint")
        ol.addWidget(self.summary_label)
        self.actions_list = QListWidget()
        self.actions_list.setMaximumHeight(140)
        self.actions_list.itemDoubleClicked.connect(self._smart_action)
        ol.addWidget(QLabel("اقدام‌های پیشنهادی (دوبار کلیک = ثبت اقدام)"))
        ol.addWidget(self.actions_list)
        split = QSplitter(Qt.Horizontal)
        self.t_top = table(["کالاهای پرتکرار", "دفعات خرید", "مقدار", "مبلغ"])
        self.t_not_bought = table(["پرفروش‌های شرکت که این مشتری نخریده"])
        self.t_info = table(["مشخصه", "مقدار"])
        for w in (self.t_info, self.t_top, self.t_not_bought):
            split.addWidget(w)
        ol.addWidget(split, stretch=1)
        self.tabs.addTab(ov, "نمای کلی")
        self.tab_widgets["overview"] = ov
        # تایم‌لاین (با فیلتر نوع، جستجو، بازهٔ تاریخ و صفحه‌بندی)
        tl = QWidget()
        tll = QVBoxLayout(tl)
        filt = QHBoxLayout()
        self.tl_kind = QComboBox()
        self.tl_kind.addItem("همهٔ رویدادها", None)
        for code, (label, icon) in c360.TIMELINE_TYPES.items():
            self.tl_kind.addItem(f"{icon} {label}", code)
        self.tl_search = QLineEdit()
        self.tl_search.setPlaceholderText("جستجو در تایم‌لاین")
        self.tl_from, self.tl_to = date_field(datetime.date.today() - datetime.timedelta(days=365)), date_field()
        self.tl_all_dates = QCheckBox("همهٔ تاریخ‌ها")
        self.tl_all_dates.setChecked(True)
        apply = QPushButton("اعمال فیلتر")
        apply.setObjectName("quickAction")
        apply.clicked.connect(lambda: self.load_timeline(reset=True))
        self.tl_search.returnPressed.connect(lambda: self.load_timeline(reset=True))
        for w in (self.tl_kind, self.tl_search, QLabel("از"), self.tl_from, QLabel("تا"), self.tl_to, self.tl_all_dates, apply):
            filt.addWidget(w)
        tll.addLayout(filt)
        self.t_timeline = table(["", "زمان", "نوع", "عنوان", "شرح", "مبلغ", "وضعیت"])
        tll.addWidget(self.t_timeline, stretch=1)
        self.more_button = QPushButton("نمایش رویدادهای قدیمی‌تر")
        self.more_button.setObjectName("quickAction")
        self.more_button.clicked.connect(lambda: self.load_timeline(reset=False))
        tll.addWidget(self.more_button)
        self.tabs.addTab(tl, "تایم‌لاین")
        self.tab_widgets["timeline"] = tl
        self._timeline_rows: list = []
        # تب‌های فهرستی ساده
        self.t_sales = table(["سند", "شماره", "تاریخ", "مبلغ", "وضعیت"])
        self.t_sales.cellDoubleClicked.connect(lambda r, _c: self._open_doc(self.t_sales, r))
        self.t_payments = table(["", "تاریخ", "شرح", "مبلغ"])
        acts = QWidget()
        al = QVBoxLayout(acts)
        self.t_activities = table(["نوع", "موضوع", "تاریخ", "اولویت", "مسئول", "وضعیت", "نتیجه"])
        self.t_activities.cellDoubleClicked.connect(lambda _r, _c: self.edit_activity())
        al.addWidget(self.t_activities, stretch=1)
        self.act_buttons = {k: QPushButton(t) for k, t in (("new", "فعالیت جدید"), ("done", "انجام شد"), ("edit", "ویرایش فعالیت"),
                                                              ("delete", "حذف فعالیت"))}
        self.act_buttons["new"].clicked.connect(lambda: self.quick_activity(None))
        self.act_buttons["done"].clicked.connect(lambda: self.complete_selected())
        self.act_buttons["edit"].clicked.connect(lambda: self.edit_activity())
        self.act_buttons["delete"].clicked.connect(lambda: self.delete_activity())
        al.addWidget(ms.footer([list(self.act_buttons.values())]))
        self.t_visits = table(["", "زمان", "ویزیتور", "شرح", "وضعیت"])
        self.t_tickets = table(["", "زمان", "نوع", "عنوان", "شرح", "وضعیت"])
        self.t_opps = table(["فرصت", "مرحله", "مبلغ", "احتمال", "تاریخ پیش‌بینی", "مسئول", "وضعیت"])
        self.t_notes = table(["", "زمان", "یادداشت"])
        self.t_documents = table(["نوع", "شماره", "تاریخ", "مبلغ", "وضعیت", "شرح"])
        self.t_documents.cellDoubleClicked.connect(lambda r, _c: self._open_doc(self.t_documents, r))
        for key, w in (("sales", self.t_sales), ("payments", self.t_payments), ("activities", acts), ("visits", self.t_visits),
                       ("tickets", self.t_tickets), ("opportunities", self.t_opps), ("notes", self.t_notes),
                       ("documents", self.t_documents)):
            self.tabs.addTab(w, dict(self.TABS)[key])
            self.tab_widgets[key] = w

    def _set_enabled(self, on: bool) -> None:
        for b in self.quick.values():
            b.setEnabled(on)
        self.quick["opportunity"].setEnabled(on and can("crm_pipeline", "CREATE"))
        for key in ("call", "task", "visit", "note", "ticket"):
            self.quick[key].setEnabled(on and can("crm_activities", "CREATE"))
        for b in self.act_buttons.values():
            b.setEnabled(on and can("crm_activities", "EDIT"))
        self.tabs.setEnabled(on)

    # --- بارگذاری ---------------------------------------------------------------------------------
    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        self.lk = CrmLookups(cid)
        current = self.customer_id
        self.customer_box.blockSignals(True)
        self.customer_box.clear()
        for label, data in self.lk.customers:
            self.customer_box.addItem(P(label), data)
        completer = self.customer_box.completer()
        if completer is not None:
            completer.setFilterMode(Qt.MatchContains)
        self.customer_box.setCurrentIndex(-1)
        self.customer_box.blockSignals(False)
        if current:
            self.load_customer(current)

    def load_customer(self, customer_id: int | None) -> None:
        if not customer_id:
            return
        self.customer_id = customer_id
        set_combo(self.customer_box, customer_id)
        self.data = d = c360.customer_360(company_id(), customer_id)
        ident, fin, sal, cnt = d["identity"], d["financial"], d["sales"], d["counts"]
        self.ident_label.setText(P(f"{ident['name']}  ·  کد {ident['code']}"))
        chips = [ident["customer_type"], ident["person_type"], ident["group"], ident["level"] and f"سطح: {ident['level']}",
                 ident["status"] and f"وضعیت: {ident['status']}", ident["sales_rep"] and f"بازاریاب: {ident['sales_rep']}",
                 ident["visitors"] and f"ویزیتور: {ident['visitors']}", ident["route"] and f"مسیر: {ident['route']}",
                 ident["mobile"] and f"موبایل: {ident['mobile']}"]
        self.chips_label.setText(P("  |  ".join(x for x in chips if x)))
        self.cards["balance"].setText(P(f"{money(fin['balance'])} {fin['balance_nature']}"))
        self.cards["credit"].setText(P(fin["credit_state_label"] + (f" — سقف {money(fin['credit_limit'])}" if fin["credit_limit"] else "")))
        self.cards["overdue"].setText(P(f"{money(fin['overdue_amount'])} ({fin['overdue_count']} فاکتور)" if fin["overdue_count"] else "ندارد"))
        self.cards["sales"].setText(P(f"{money(sal['total_sales'])} ({sal['invoice_count']} فاکتور)"))
        self.cards["year"].setText(money(sal["sales_this_year"]))
        self.cards["last"].setText(P(f"{_date(sal['last_purchase'])} ({sal['days_since_last']} روز پیش)" if sal["last_purchase"] else "خریدی ندارد"))
        self.cards["interval"].setText(P(f"هر {round(sal['avg_days_between'])} روز" if sal["avg_days_between"] else "—"))
        self.cards["pipeline"].setText(P(f"{cnt['open_opportunities']} فرصت — {money(cnt['open_opportunity_value'])}"))
        self._loaded = set()
        self._set_enabled(True)
        self._load_current_tab()

    def _load_current_tab(self) -> None:
        if not self.customer_id:
            return
        key = self.TABS[self.tabs.currentIndex()][0]
        if key in self._loaded:
            return
        self._loaded.add(key)
        getattr(self, f"_load_{key}")()

    def reload(self) -> None:
        if self.customer_id:
            self.load_customer(self.customer_id)

    def _load_overview(self) -> None:
        d = self.data
        ident, fin, sal = d["identity"], d["financial"], d["sales"]
        self.summary_label.setText(P(d["summary"]))
        self.actions_list.clear()
        for a in d["smart_actions"]:
            item = QListWidgetItem(P(f"{a['text']}  ←  {a['suggestion']}"))
            item.setData(Qt.UserRole, a)
            item.setForeground({"danger": _RED, "warning": _AMBER}.get(a["severity"], _GREEN))
            self.actions_list.addItem(item)
        info = [("نوع / شخصیت", f"{ident['customer_type']} {ident['person_type']}".strip()), ("کد اقتصادی", ident["economic_code"]),
                ("شناسهٔ ملی", ident["national_id"]), ("تلفن", ident["phone"]), ("موبایل", ident["mobile"]), ("ایمیل", ident["email"]),
                ("نشانی", ident["address"]), ("شهر / استان", " / ".join(x for x in (ident["city"], ident["province"]) if x)),
                ("منطقه", ident["region"]), ("موقعیت GPS", "، ".join(str(x) for x in ident["gps"]) if ident["gps"] else None),
                ("کانال جذب", ident["onboarding_source"]), ("بازاریاب", ident["sales_rep"]), ("ویزیتور", ident["visitors"]),
                ("مسیر پخش", ident["route"]), ("گروه", ident["group"]), ("سطح", ident["level"]), ("وضعیت", ident["status"]),
                ("بدهکار / بستانکار", f"{money(fin['debit_total'])} / {money(fin['credit_total'])}"),
                ("سقف اعتبار / اعتبار در دسترس", f"{money(fin['credit_limit'])} / {money(fin['available_credit']) if fin['available_credit'] is not None else '—'}"),
                ("مهلت پرداخت", f"{fin['payment_term_days']} روز"), ("سررسید بعدی", f"{_date(fin['next_due_date'])} — {money(fin['next_due_amount'])}" if fin["next_due_date"] else "—"),
                ("آخرین دریافت", f"{_date(fin['last_payment_date'])} — {money(fin['last_payment_amount'])}" if fin["last_payment_date"] else "—"),
                ("اولین خرید", _date(sal["first_purchase"])), ("تعداد سفارش", sal["order_count"]),
                ("میانگین مبلغ فاکتور", money(sal["avg_invoice"])), ("خرید ماه جاری", money(sal["sales_this_month"])),
                ("خرید سال گذشته", money(sal["sales_last_year"])), ("برگشت از فروش", money(sal["returns"]))]
        an = d.get("analytics")
        if an:
            info += [("سلامت مشتری", f"{an['health_score']} — {an['health_label']}"), ("ریسک ریزش", f"{an['churn_risk']}٪ — {an['churn_label']}"),
                     ("RFM", f"{an['rfm']} — {an['rfm_label']}"),
                     ("ارزش طول عمر (تاکنون / پیش‌بینی)", f"{money(an['clv_historical'])} / {money(an['clv_predicted'])}"),
                     ("سگمنت‌ها", "، ".join(an["segments"])), ("اقدام پیشنهادی", an["next_best_action"])]
        lo = d.get("loyalty")
        if lo and (lo["points"] or lo["lifetime_points"]):
            info.append(("باشگاه مشتریان", P(f"{lo['points']} امتیاز — سطح {lo['tier_label']}")))
        fill(self.t_info, [[k, v if v not in (None, "") else "—"] for k, v in info])
        fill(self.t_top, [[x["name"], x["times"], x["quantity"].normalize() if x["quantity"] is not None else "", x["amount"]]
                          for x in sal["top_items"]])
        fill(self.t_not_bought, [[x["name"]] for x in sal["not_bought_items"]])

    def load_timeline(self, reset: bool = True) -> None:
        if reset:
            self._timeline_rows = []
        kind = self.tl_kind.currentData()
        all_dates = self.tl_all_dates.isChecked()
        rows = c360.timeline(company_id(), self.customer_id, kinds=[kind] if kind else None,
                             date_from=None if all_dates else self.tl_from.date(), date_to=None if all_dates else self.tl_to.date(),
                             search=self.tl_search.text().strip() or None, limit=self.PAGE, offset=len(self._timeline_rows))
        self._timeline_rows += rows
        fill(self.t_timeline, [[e.icon, numerals.format_jalali_date(e.at.date()) + " " + P(e.at.strftime("%H:%M")), e.label, e.title,
                                e.detail, e.amount if e.amount is not None else "", e.status] for e in self._timeline_rows],
             [(e.ref_type, e.ref_id) for e in self._timeline_rows])
        self.more_button.setEnabled(len(rows) == self.PAGE)

    def _load_timeline(self) -> None:
        self.load_timeline(reset=True)

    def _events(self, kinds: list[str], limit: int = 300):
        return c360.timeline(company_id(), self.customer_id, kinds=kinds, limit=limit)

    def _load_sales(self) -> None:
        self._load_docs(self.t_sales, ("SALES_PROFORMA", "SALES_ORDER", "SALES_INVOICE"), with_desc=False)

    def _load_documents(self) -> None:
        self._load_docs(self.t_documents, None, with_desc=True)

    def _load_docs(self, t: QTableWidget, types, with_desc: bool) -> None:
        from peecha.services import commercial_documents as documents_service

        docs = [doc for doc in documents_service.list_documents(company_id(), counterparty_detail_account_id=self.customer_id, limit=300)
                if types is None or doc.document_type_code in types]
        rows = []
        for doc in docs:
            row = [documents_service._DOC_TYPE_TITLES.get(doc.document_type_code, doc.document_type_code),
                   doc.document_no, doc.document_date, doc.total_amount, doc.status_code]
            rows.append(row + ([doc.description or ""] if with_desc else []))
        fill(t, rows, [(doc.document_type_code, doc.document_id) for doc in docs])

    def _open_doc(self, t: QTableWidget, row: int) -> None:
        data = t.item(row, 0).data(Qt.UserRole) if t.item(row, 0) else None
        if data:
            open_document(self._main_window, *data)

    def _load_payments(self) -> None:
        ev = self._events(["PAYMENT"])
        fill(self.t_payments, [[e.icon, e.at.date(), e.title + (f" — {e.detail}" if e.detail else ""), e.amount] for e in ev])

    def _load_activities(self) -> None:
        self._acts = act_service.list_activities(company_id(), customer_detail_account_id=self.customer_id, limit=300)
        fill(self.t_activities, [[a.type_label, a.subject, a.due_date, cc.PRIORITIES.get(a.priority_code, ""), a.assigned_name,
                                  ("⚠ معوق — " if a.is_overdue() else "") + a.status_label, a.result_text or ""] for a in self._acts],
             [a.activity_id for a in self._acts])
        for r, a in enumerate(self._acts):
            if a.is_overdue():
                self.t_activities.item(r, 5).setForeground(_RED)

    def _load_visits(self) -> None:
        ev = self._events(["VISIT"])
        fill(self.t_visits, [[e.icon, e.at.date(), e.title, e.detail, e.status] for e in ev])

    def _load_tickets(self) -> None:
        ev = self._events(["TICKET", "COMPLAINT"])
        fill(self.t_tickets, [[e.icon, e.at.date(), e.label, e.title, e.detail, e.status] for e in ev])

    def _load_opportunities(self) -> None:
        rows = opp_service.list_opportunities(company_id(), customer_detail_account_id=self.customer_id)
        fill(self.t_opps, [[o.title, o.stage_name, o.amount, f"{o.probability_percent.normalize()}٪", o.expected_close_date,
                            o.owner_name, o.status_label] for o in rows], [o.opportunity_id for o in rows])

    def _load_notes(self) -> None:
        ev = self._events(["NOTE"])
        fill(self.t_notes, [[e.icon, e.at.date(), e.detail or e.title] for e in ev])

    # --- اقدامات --------------------------------------------------------------------------------
    def quick_activity(self, kind: str | None, values: dict | None = None, subject: str | None = None) -> int | None:
        if not self.customer_id:
            return None
        if values is None:
            fields = activity_form(self.lk, kind=kind)
            if subject:
                fields[1][2].setText(subject)
            values = _ask(self, "فعالیت تازه", fields)
            if values is None:
                return None
        aid, ok = _run(self, "فعالیت", act_service.create_activity, company_id(), user_id(),
                       activity_fields(values, customer_detail_account_id=self.customer_id))
        if ok:
            self.reload()
        return aid

    def _smart_action(self, item: QListWidgetItem) -> None:
        a = item.data(Qt.UserRole)
        self.quick_activity(a["action"], subject=a["suggestion"])

    def _selected_activity(self):
        aid = _selected(self.t_activities)
        if aid is None:
            QMessageBox.warning(self, "فعالیت", "یک فعالیت را انتخاب کنید.")
        return aid

    def complete_selected(self, values: dict | None = None) -> bool:
        aid = self._selected_activity()
        if aid is None:
            return False
        ok = complete_activity(self, aid, values)
        if ok:
            self.reload()
        return ok

    def edit_activity(self, values: dict | None = None) -> bool:
        aid = self._selected_activity()
        if aid is None:
            return False
        row = act_service.get_activity(company_id(), aid)
        values = values or _ask(self, "ویرایش فعالیت", activity_form(self.lk, row))
        if values is None:
            return False
        _r, ok = _run(self, "فعالیت", act_service.update_activity, company_id(), user_id(), aid,
                      activity_fields(values, customer_detail_account_id=self.customer_id, opportunity_id=row.opportunity_id))
        if ok:
            self.reload()
        return ok

    def delete_activity(self) -> bool:
        aid = self._selected_activity()
        if aid is None or not _confirm(self, "فعالیت", "فعالیت انتخاب‌شده حذف شود؟"):
            return False
        _r, ok = _run(self, "فعالیت", act_service.delete_activity, company_id(), user_id(), aid)
        if ok:
            self.reload()
        return ok

    def new_opportunity(self, values: dict | None = None) -> int | None:
        if not self.customer_id:
            return None
        values = values or _ask(self, "فرصت فروش تازه", opportunity_form(self.lk, None))
        if values is None:
            return None
        oid, ok = _run(self, "فرصت فروش", opp_service.create_opportunity, company_id(), user_id(),
                       opportunity_fields(values, customer_detail_account_id=self.customer_id))
        if ok:
            self.reload()
        return oid

    def new_order(self) -> int | None:
        """سفارش پیش‌نویس با همان سرویس فروش برای این مشتری ساخته و در فرم سفارش فروش باز می‌شود."""
        if not self.customer_id:
            return None
        doc_id, ok = _run(self, "سفارش فروش", opp_sales.create_customer_document, company_id(), user_id(), self.customer_id)
        if ok:
            open_document(self._main_window, "SALES_ORDER", doc_id)
            self._loaded.discard("sales")
            self._loaded.discard("documents")
        return doc_id

    def open_erp(self, nav_code: str) -> None:
        """سفارش و دریافت فقط با فرم‌های موجود ERP ثبت می‌شوند؛ مشتری انتخاب‌شده در صورت امکان پر می‌شود."""
        if self._main_window is None or not self.customer_id:
            return
        cid = self.customer_id

        def prefill(screen) -> None:
            setter = getattr(screen, "preselect_counterparty", None)
            if setter is not None:
                setter(cid)

        self._main_window.open_screen(nav_code, then=prefill)


# =========================================================================================================
# فرصت فروش — فرم مشترک
# =========================================================================================================
def opportunity_form(lk: CrmLookups, row: opp_service.OpportunityRow | None, with_customer: bool = False) -> list:
    g = (lambda name, default=None: getattr(row, name)) if row else (lambda name, default=None: default)
    fields = [("title", "عنوان", QLineEdit(g("title", "") or ""))]
    if with_customer:
        fields.append(("customer_detail_account_id", "مشتری", _with(combo(lk.customers, "— (برای سرنخ) —"), g("customer_detail_account_id"))))
    fields += [("amount", "مبلغ احتمالی", num_field(g("amount", ZERO))),
               ("expected_close_date", "تاریخ پیش‌بینی فروش", date_field(g("expected_close_date") or datetime.date.today() + datetime.timedelta(days=30))),
               ("owner_user_id", "مسئول فروش", _with(combo(lk.users, "— خودم —"), g("owner_user_id"))),
               ("source_id", "منبع", _with(combo(lk.sources, "—"), g("source_id"))),
               ("description", "توضیحات", _text(g("description")))]
    return fields


def opportunity_fields(values: dict, **party) -> opp_service.OpportunityFields:
    customer = values.get("customer_detail_account_id")
    if customer:
        party["customer_detail_account_id"] = customer
    return opp_service.OpportunityFields(
        title=values.get("title") or "", amount=values.get("amount") or ZERO, expected_close_date=values.get("expected_close_date"),
        owner_user_id=values.get("owner_user_id"), source_id=values.get("source_id"), description=values.get("description"), **party)


# =========================================================================================================
# مرکز کارها
# =========================================================================================================
@ms.styled
class TaskCenterScreen(QWidget):
    """کارهای امروز/فردا/این هفته/معوق + صف‌های واقعی ERP (ویزیت، سفارش، وصول) در یک صفحه."""

    scroll_in_mdi = True

    def __init__(self, main_window=None) -> None:
        super().__init__()
        self._main_window = main_window
        self.dialog_runner = None
        self.lk: CrmLookups | None = None
        self.center: task_service.TaskCenter | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        title = QLabel("مرکز کارها و پیگیری‌ها")
        title.setObjectName("pageTitle")
        self.scope = QComboBox()
        self.scope.addItem("کارهای من", "me")
        self.scope.addItem("همهٔ کاربران", "all")
        self.scope.currentIndexChanged.connect(lambda _i: self.reload())
        outer.addWidget(ms.header_card(title, self.scope))
        cards, self.cards = ms.summary([
            ("overdue", "معوق", "danger", "⏰"), ("today", "امروز", "info", "📌"), ("tomorrow", "فردا", "neutral", "📆"),
            ("week", "این هفته", "neutral", "🗓️"), ("visits", "ویزیت‌های امروز", "success", "🚚"),
            ("orders", "سفارش‌های در انتظار", "warning", "🛒"), ("collections", "وصول سررسیده", "danger", "💰")], per_row=7)
        outer.addWidget(cards)
        self.tabs = QTabWidget()
        self.tables: dict[str, QTableWidget] = {}
        for key, label in task_service.BUCKETS:
            t = table(["نوع", "موضوع", "مشتری / سرنخ", "تاریخ", "اولویت", "مسئول", "اقدام بعدی"])
            t.cellDoubleClicked.connect(lambda _r, _c, tt=t: self.open_customer(tt))
            self.tables[key] = t
            self.tabs.addTab(t, label)
        self.t_visits = table(["ترتیب", "مشتری", "وضعیت"])
        self.t_orders = table(["شماره", "تاریخ", "مشتری", "مبلغ", "وضعیت"])
        self.t_collections = table(["فاکتور", "مشتری", "سررسید", "روز تأخیر", "مانده"])
        for t, label in ((self.t_visits, "ویزیت‌های امروز"), (self.t_orders, "سفارش‌های در انتظار"), (self.t_collections, "وصول‌های سررسیده")):
            self.tabs.addTab(t, label)
        outer.addWidget(self.tabs, stretch=1)
        self.buttons = {k: QPushButton(t) for k, t in (("new", "فعالیت جدید"), ("done", "انجام شد"), ("postpone", "تعویق"),
                                                      ("open", "پروندهٔ مشتری"), ("delete", "حذف فعالیت"))}
        self.buttons["new"].clicked.connect(lambda: self.new_activity())
        self.buttons["done"].clicked.connect(lambda: self.complete())
        self.buttons["postpone"].clicked.connect(lambda: self.postpone())
        self.buttons["open"].clicked.connect(lambda: self.open_customer(self._current_table()))
        self.buttons["delete"].clicked.connect(lambda: self.delete())
        outer.addWidget(ms.footer([list(self.buttons.values())]))

    def refresh(self) -> None:
        if company_id() is None:
            return
        self.lk = CrmLookups(company_id())
        self.scope.setVisible(can("crm_assign", "VIEW"))
        self.reload()

    def reload(self) -> None:
        mine = self.scope.currentData() == "me" or not self.scope.isVisible()
        self.center = tc = task_service.task_center(company_id(), user_id() if mine else None)
        for key, _label in task_service.BUCKETS:
            rows = tc.buckets[key]
            fill(self.tables[key], [[a.type_label, a.subject, a.customer_name or (f"سرنخ: {a.lead_name}" if a.lead_name else ""),
                                     a.due_date, cc.PRIORITIES.get(a.priority_code, ""), a.assigned_name, a.next_action or ""]
                                    for a in rows], [a.activity_id for a in rows])
            if key == "overdue":
                for r in range(len(rows)):
                    for col in range(self.tables[key].columnCount()):
                        self.tables[key].item(r, col).setForeground(_RED)
            self.tabs.setTabText(list(dict(task_service.BUCKETS)).index(key), P(f"{dict(task_service.BUCKETS)[key]} ({len(rows)})"))
        fill(self.t_visits, [[v["sequence"], v["customer_name"], "✓ ویزیت شد" if v["visited"] else "در انتظار"] for v in tc.planned_visits],
             [v["customer_detail_account_id"] for v in tc.planned_visits])
        fill(self.t_orders, [[o["document_no"], o["document_date"], o["customer_name"], o["total_amount"], o["status_code"]]
                             for o in tc.pending_orders], [o["customer_detail_account_id"] for o in tc.pending_orders])
        fill(self.t_collections, [[c["document_id"], c["customer_name"], c["due_date"], c["days_overdue"], c["remaining_amount"]]
                                  for c in tc.due_collections], [c["customer_detail_account_id"] for c in tc.due_collections])
        for key, value in (("overdue", tc.count("overdue")), ("today", tc.count("today")), ("tomorrow", tc.count("tomorrow")),
                           ("week", tc.count("week")), ("visits", len(tc.planned_visits)), ("orders", len(tc.pending_orders)),
                           ("collections", len(tc.due_collections))):
            self.cards[key].setText(P(value))
        if tc.count("overdue"):
            self.tabs.setCurrentIndex(0)

    def _current_table(self) -> QTableWidget:
        return self.tabs.currentWidget()

    def _selected_activity(self):
        t = self._current_table()
        aid = _selected(t) if t in self.tables.values() else None
        if aid is None:
            QMessageBox.warning(self, "مرکز کارها", "یک فعالیت را از یکی از سبدها انتخاب کنید.")
        return aid

    def new_activity(self, values: dict | None = None) -> int | None:
        values = values or _ask(self, "فعالیت تازه", activity_form(self.lk, with_party=True))
        if values is None:
            return None
        aid, ok = _run(self, "فعالیت", act_service.create_activity, company_id(), user_id(),
                       activity_fields(values, customer_detail_account_id=values.get("customer_detail_account_id")))
        if ok:
            self.reload()
        return aid

    def complete(self, values: dict | None = None) -> bool:
        aid = self._selected_activity()
        if aid is None:
            return False
        ok = complete_activity(self, aid, values)
        if ok:
            self.reload()
        return ok

    def postpone(self, new_date: datetime.date | None = None) -> bool:
        aid = self._selected_activity()
        if aid is None:
            return False
        if new_date is None:
            values = _ask(self, "تعویق", [("due_date", "تاریخ تازه", date_field(datetime.date.today() + datetime.timedelta(days=1)))])
            if values is None:
                return False
            new_date = values["due_date"]
        row = act_service.get_activity(company_id(), aid)
        f = act_service.ActivityFields(row.activity_type_code, row.subject, customer_detail_account_id=row.customer_detail_account_id,
                                       lead_id=row.lead_id, opportunity_id=row.opportunity_id, description=row.description,
                                       due_date=new_date, duration_minutes=row.duration_minutes, priority_code=row.priority_code,
                                       assigned_to_user_id=row.assigned_to_user_id, next_action=row.next_action)
        _r, ok = _run(self, "تعویق", act_service.update_activity, company_id(), user_id(), aid, f)
        if ok:
            self.reload()
        return ok

    def delete(self) -> bool:
        aid = self._selected_activity()
        if aid is None or not _confirm(self, "مرکز کارها", "فعالیت انتخاب‌شده حذف شود؟"):
            return False
        _r, ok = _run(self, "مرکز کارها", act_service.delete_activity, company_id(), user_id(), aid)
        if ok:
            self.reload()
        return ok

    def open_customer(self, t: QTableWidget) -> None:
        key = _selected(t)
        if key is None or self._main_window is None:
            return
        customer_id = key
        if t in self.tables.values():
            customer_id = act_service.get_activity(company_id(), key).customer_detail_account_id
        if customer_id:
            self._main_window.open_screen("CRM_CUSTOMER360", then=lambda s: s.load_customer(customer_id))


# =========================================================================================================
# سرنخ‌ها
# =========================================================================================================
@ms.styled
class LeadsScreen(QWidget):
    scroll_in_mdi = True

    def __init__(self, main_window=None) -> None:
        super().__init__()
        self._main_window = main_window
        self.dialog_runner = None
        self.lk: CrmLookups | None = None
        self.rows: list[lead_service.LeadRow] = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        title = QLabel("سرنخ‌ها")
        title.setObjectName("pageTitle")
        self.search = QLineEdit()
        self.search.setPlaceholderText("جستجو: نام، شرکت، موبایل، ایمیل")
        self.search.returnPressed.connect(self.reload)
        self.status = combo([(v, k) for k, v in cc.LEAD_STATUS.items()], "همهٔ وضعیت‌ها")
        self.band = combo([(v, k) for k, v in cc.SCORE_BANDS.items()], "همهٔ امتیازها")
        self.mine = QCheckBox("فقط سرنخ‌های من")
        for w in (self.status, self.band):
            w.currentIndexChanged.connect(lambda _i: self.reload())
        self.mine.toggled.connect(lambda _c: self.reload())
        outer.addWidget(ms.header_card(title, self.search, self.status, self.band, self.mine))
        cards, self.cards = ms.summary([("open", "سرنخ باز", "info", "🧲"), ("hot", "داغ و بسیار داغ", "danger", "🔥"),
                                        ("value", "ارزش احتمالی سرنخ‌های باز", "success", "💎"),
                                        ("converted", "تبدیل‌شده", "success", "✅")], per_row=4)
        outer.addWidget(cards)
        split = QSplitter(Qt.Horizontal)
        self.t = table(["شماره", "نام", "شرکت", "موبایل", "منبع", "وضعیت", "امتیاز", "ارزش احتمالی", "مسئول", "اقدام بعدی", "تاریخ ایجاد"])
        self.t.itemSelectionChanged.connect(self._selected_changed)
        self.t.cellDoubleClicked.connect(lambda _r, _c: self.edit_lead())
        split.addWidget(self.t)
        side = QWidget()
        sl = QVBoxLayout(side)
        self.detail = QLabel("")
        self.detail.setWordWrap(True)
        self.detail.setObjectName("sectionHint")
        sl.addWidget(self.detail)
        self.t_lead_acts = table(["نوع", "موضوع", "تاریخ", "وضعیت"])
        sl.addWidget(self.t_lead_acts, stretch=1)
        split.addWidget(side)
        split.setSizes([900, 380])
        outer.addWidget(split, stretch=1)
        self.buttons = {k: QPushButton(t) for k, t in (
            ("new", "سرنخ جدید"), ("edit", "ویرایش سرنخ"), ("delete", "حذف سرنخ"), ("activity", "ثبت فعالیت"),
            ("assign", "واگذاری"), ("status", "تغییر وضعیت"), ("convert", "تبدیل به مشتری و فرصت"), ("rescore", "محاسبهٔ امتیاز"))}
        for key, b in self.buttons.items():
            b.clicked.connect(lambda _c=False, k=key: getattr(self, {"new": "new_lead", "edit": "edit_lead", "delete": "delete_lead",
                                                                    "activity": "add_activity", "assign": "assign", "status": "change_status",
                                                                    "convert": "convert", "rescore": "rescore"}[k])())
        outer.addWidget(ms.footer([[self.buttons[k] for k in ("new", "edit", "delete")], [self.buttons["activity"], self.buttons["rescore"]],
                                   [self.buttons[k] for k in ("assign", "status", "convert")]]))

    def refresh(self) -> None:
        if company_id() is None:
            return
        self.lk = CrmLookups(company_id())
        self.buttons["new"].setEnabled(can("crm_leads", "CREATE"))
        for k in ("edit", "status", "convert", "rescore"):
            self.buttons[k].setEnabled(can("crm_leads", "EDIT"))
        self.buttons["delete"].setEnabled(can("crm_leads", "DELETE"))
        self.buttons["assign"].setEnabled(can("crm_assign", "EDIT"))
        self.buttons["activity"].setEnabled(can("crm_activities", "CREATE"))
        self.reload()

    def reload(self) -> None:
        cid = company_id()
        self.rows = lead_service.list_leads(cid, status=self.status.currentData(), band=self.band.currentData(),
                                            owner_user_id=user_id() if self.mine.isChecked() else None,
                                            search=self.search.text().strip() or None)
        fill(self.t, [[r.lead_no, r.full_name, r.company_name or "", r.mobile or r.phone or "", r.source_name, r.status_label,
                       f"{r.score} — {r.band_label}", r.estimated_value if r.estimated_value is not None else "", r.owner_name,
                       (r.next_action or "") + (f" ({_date(r.next_action_date)})" if r.next_action_date else ""), r.created_at.date()]
                      for r in self.rows], [r.lead_id for r in self.rows])
        for i, r in enumerate(self.rows):
            if r.score_band in ("HOT", "VERY_HOT"):
                self.t.item(i, 6).setForeground(_RED)
        open_rows = [r for r in self.rows if r.status_code in cc.LEAD_OPEN_STATUSES]
        self.cards["open"].setText(P(len(open_rows)))
        self.cards["hot"].setText(P(sum(1 for r in open_rows if r.score_band in ("HOT", "VERY_HOT"))))
        self.cards["value"].setText(money(sum((r.estimated_value or ZERO for r in open_rows), ZERO)))
        self.cards["converted"].setText(P(sum(1 for r in self.rows if r.status_code == "CONVERTED")))

    def _row(self):
        lid = _selected(self.t)
        return next((r for r in self.rows if r.lead_id == lid), None)

    def _need_row(self):
        row = self._row()
        if row is None:
            QMessageBox.warning(self, "سرنخ", "یک سرنخ را انتخاب کنید.")
        return row

    def _selected_changed(self) -> None:
        row = self._row()
        if row is None:
            self.detail.setText("")
            fill(self.t_lead_acts, [])
            return
        parts = lead_service.score_breakdown(company_id(), row.lead_id)
        names = {"engagement": "تعامل", "responsiveness": "پاسخ‌گویی", "interest": "علاقه به محصول", "value": "ارزش احتمالی",
                 "history": "سابقهٔ خرید", "profile": "صنعت و موقعیت", "source": "منبع", "recency": "فعالیت اخیر"}
        self.detail.setText(P(f"{row.full_name} — امتیاز {row.score} ({row.band_label})\n"
                              + "، ".join(f"{names[k]}: {v}" for k, v in parts.items() if v)
                              + (f"\nعلاقه: {row.interested_text}" if row.interested_text else "")
                              + (f"\nیادداشت: {row.notes}" if row.notes else "")))
        acts = act_service.list_activities(company_id(), lead_id=row.lead_id, limit=50)
        fill(self.t_lead_acts, [[a.type_label, a.subject, a.due_date, a.status_label] for a in acts])

    def _form(self, row: lead_service.LeadRow | None) -> list:
        g = (lambda name, default=None: getattr(row, name)) if row else (lambda name, default=None: default)
        return [("full_name", "نام", QLineEdit(g("full_name", "") or "")), ("company_name", "شرکت", QLineEdit(g("company_name", "") or "")),
                ("mobile", "موبایل", QLineEdit(g("mobile", "") or "")), ("phone", "تلفن", QLineEdit(g("phone", "") or "")),
                ("email", "ایمیل", QLineEdit(g("email", "") or "")),
                ("source_id", "منبع", _with(combo(self.lk.sources, "—"), g("source_id"))),
                ("interested_item_id", "محصول مورد علاقه", _with(combo(self.lk.items, "—"), g("interested_item_id"))),
                ("interested_text", "شرح علاقه", QLineEdit(g("interested_text", "") or "")),
                ("estimated_value", "ارزش احتمالی", num_field(g("estimated_value"))),
                ("owner_user_id", "مسئول", _with(combo(self.lk.users, "— خودم —"), g("owner_user_id"))),
                ("industry", "صنعت", QLineEdit(g("industry", "") or "")), ("city", "شهر", QLineEdit(g("city", "") or "")),
                ("province", "استان", QLineEdit(g("province", "") or "")),
                ("next_action", "اقدام بعدی", QLineEdit(g("next_action", "") or "")),
                ("next_action_date", "تاریخ اقدام بعدی", date_field(g("next_action_date") or datetime.date.today() + datetime.timedelta(days=1))),
                ("notes", "توضیحات", _text(g("notes")))]

    @staticmethod
    def _fields(values: dict) -> lead_service.LeadFields:
        values = dict(values)
        if values.get("estimated_value") == ZERO:
            values["estimated_value"] = None
        return lead_service.LeadFields(**{k: values.get(k) for k in lead_service.LeadFields.__dataclass_fields__})

    def new_lead(self, values: dict | None = None) -> int | None:
        values = values or _ask(self, "سرنخ تازه", self._form(None))
        if values is None:
            return None
        fields = self._fields(values)
        lid, ok = _run(self, "سرنخ", lead_service.create_lead, company_id(), user_id(), fields)
        if not ok and fields.mobile and lead_service.find_duplicates(company_id(), fields.mobile, fields.email) \
                and _confirm(self, "سرنخ", "سرنخ یا مشتری مشابه وجود دارد. با این حال ثبت شود؟"):
            lid, ok = _run(self, "سرنخ", lead_service.create_lead, company_id(), user_id(), fields, allow_duplicate=True)
        if ok:
            self.reload()
        return lid

    def edit_lead(self, values: dict | None = None) -> bool:
        row = self._need_row()
        if row is None:
            return False
        values = values or _ask(self, "ویرایش سرنخ", self._form(row))
        if values is None:
            return False
        _r, ok = _run(self, "سرنخ", lead_service.update_lead, company_id(), user_id(), row.lead_id, self._fields(values))
        if ok:
            self.reload()
        return ok

    def delete_lead(self) -> bool:
        row = self._need_row()
        if row is None or not _confirm(self, "سرنخ", f"سرنخ «{row.full_name}» حذف شود؟"):
            return False
        _r, ok = _run(self, "سرنخ", lead_service.delete_lead, company_id(), user_id(), row.lead_id)
        if ok:
            self.reload()
        return ok

    def add_activity(self, values: dict | None = None) -> int | None:
        row = self._need_row()
        if row is None:
            return None
        values = values or _ask(self, "فعالیت سرنخ", activity_form(self.lk, kind="CALL"))
        if values is None:
            return None
        aid, ok = _run(self, "فعالیت", act_service.create_activity, company_id(), user_id(), activity_fields(values, lead_id=row.lead_id))
        if ok:
            self.reload()
        return aid

    def assign(self, owner_id: int | None = None) -> bool:
        row = self._need_row()
        if row is None:
            return False
        if owner_id is None:
            values = _ask(self, "واگذاری سرنخ", [("owner", "مسئول تازه", _with(combo(self.lk.users), row.owner_user_id))])
            if values is None:
                return False
            owner_id = values["owner"]
        _r, ok = _run(self, "واگذاری", lead_service.assign_lead, company_id(), user_id(), row.lead_id, owner_id)
        if ok:
            self.reload()
        return ok

    def change_status(self, values: dict | None = None) -> bool:
        row = self._need_row()
        if row is None:
            return False
        statuses = [(v, k) for k, v in cc.LEAD_STATUS.items() if k != "CONVERTED"]
        values = values or _ask(self, "وضعیت سرنخ", [("status", "وضعیت", _with(combo(statuses), row.status_code)),
                                                      ("reason", "دلیل (برای از دست رفته / فاقد شرایط)", QLineEdit())])
        if values is None:
            return False
        _r, ok = _run(self, "وضعیت سرنخ", lead_service.set_lead_status, company_id(), user_id(), row.lead_id, values["status"],
                      values.get("reason"))
        if ok:
            self.reload()
        return ok

    def convert(self, values: dict | None = None) -> tuple | None:
        row = self._need_row()
        if row is None:
            return None
        values = values or _ask(self, "تبدیل سرنخ", [
            ("existing", "اتصال به مشتری موجود", _with(combo(self.lk.customers, "— ساخت مشتری تازه —"), None)),
            ("opportunity", "ساخت فرصت فروش", _checked(True)),
            ("title", "عنوان فرصت", QLineEdit(f"فرصت فروش — {row.company_name or row.full_name}")),
            ("amount", "مبلغ فرصت", num_field(row.estimated_value or ZERO))],
            "مشتری تازه با همان فرم و قواعد تعریف مشتری ERP ساخته می‌شود.")
        if values is None:
            return None
        res, ok = _run(self, "تبدیل سرنخ", lead_service.convert_lead, company_id(), user_id(), row.lead_id,
                       existing_customer_id=values.get("existing"), create_opportunity=bool(values.get("opportunity")),
                       opportunity_title=values.get("title"), opportunity_amount=values.get("amount"))
        if ok:
            self.reload()
            if self._main_window is not None:
                customer_id = res[0]
                self._main_window.open_screen("CRM_CUSTOMER360", then=lambda s: s.load_customer(customer_id))
        return res

    def rescore(self) -> bool:
        row = self._need_row()
        if row is None:
            return False
        _r, ok = _run(self, "امتیاز", lead_service.rescore_lead, company_id(), row.lead_id)
        if ok:
            self.reload()
        return ok


def _checked(value: bool) -> QCheckBox:
    box = QCheckBox()
    box.setChecked(value)
    return box


# =========================================================================================================
# قیف فروش (Kanban)
# =========================================================================================================
class _KanbanList(QListWidget):
    """یک ستون قیف؛ کارت کشیده‌شده از ستون دیگر به این مرحله منتقل می‌شود."""

    moved = Signal(int, int)  # opportunity_id, stage_id

    def __init__(self, stage_id: int) -> None:
        super().__init__()
        self.stage_id = stage_id
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setWordWrap(True)
        self.setSpacing(4)
        self.setMinimumWidth(220)

    def dropEvent(self, event) -> None:
        source = event.source()
        if isinstance(source, _KanbanList) and source is not self and source.currentItem() is not None:
            opp_id = source.currentItem().data(Qt.UserRole)
            event.setDropAction(Qt.IgnoreAction)
            event.accept()
            self.moved.emit(opp_id, self.stage_id)
            return
        event.ignore()


@ms.styled
class PipelineScreen(QWidget):
    scroll_in_mdi = True

    def __init__(self, main_window=None) -> None:
        super().__init__()
        self._main_window = main_window
        self.dialog_runner = None
        self.lk: CrmLookups | None = None
        self.columns: dict[int, _KanbanList] = {}
        self.board: list[opp_service.KanbanColumn] = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        title = QLabel("قیف فروش و فرصت‌ها")
        title.setObjectName("pageTitle")
        self.pipeline = QComboBox()
        self.pipeline.currentIndexChanged.connect(lambda _i: self.reload())
        self.mine = QCheckBox("فقط فرصت‌های من")
        self.mine.toggled.connect(lambda _c: self.reload())
        outer.addWidget(ms.header_card(title, self.pipeline, self.mine))
        cards, self.cards = ms.summary([("value", "ارزش قیف", "info", "💼"), ("weighted", "پیش‌بینی وزنی", "success", "📈"),
                                        ("open", "فرصت باز", "neutral", "🎯"), ("won", "برنده", "success", "🏆"),
                                        ("lost", "بازنده", "danger", "✖"), ("rate", "نرخ تبدیل", "info", "📊")], per_row=6)
        outer.addWidget(cards)
        self.board_area = QScrollArea()
        self.board_area.setWidgetResizable(True)
        self.board_host = QWidget()
        self.board_layout = QHBoxLayout(self.board_host)
        self.board_layout.setContentsMargins(0, 0, 0, 0)
        self.board_area.setWidget(self.board_host)
        outer.addWidget(self.board_area, stretch=1)
        self.buttons = {k: QPushButton(t) for k, t in (
            ("new", "فرصت جدید"), ("edit", "ویرایش فرصت"), ("lines", "اقلام پیشنهادی"), ("activity", "ثبت فعالیت"),
            ("won", "برنده شد"), ("lost", "از دست رفت"), ("customer", "پروندهٔ مشتری"), ("delete", "حذف فرصت"),
            ("proforma", "صدور پیش‌فاکتور"), ("order", "صدور سفارش فروش"), ("chain", "اسناد فروش فرصت"))}
        actions = {"new": "new_opportunity", "edit": "edit_opportunity", "lines": "edit_lines", "activity": "add_activity",
                   "won": "mark_won", "lost": "mark_lost", "customer": "open_customer", "delete": "delete_opportunity",
                   "proforma": "issue_proforma", "order": "issue_order", "chain": "show_chain"}
        for key, b in self.buttons.items():
            b.clicked.connect(lambda _c=False, k=key: getattr(self, actions[k])())
        outer.addWidget(ms.footer([[self.buttons[k] for k in ("new", "edit", "lines", "delete")],
                                   [self.buttons["activity"], self.buttons["customer"]],
                                   [self.buttons["proforma"], self.buttons["order"], self.buttons["chain"]],
                                   [self.buttons["won"], self.buttons["lost"]]]))

    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        self.lk = CrmLookups(cid)
        current = self.pipeline.currentData()
        self.pipeline.blockSignals(True)
        self.pipeline.clear()
        for p in pl_service.list_pipelines(cid):
            self.pipeline.addItem(p.name, p.pipeline_id)
        set_combo(self.pipeline, current)
        self.pipeline.blockSignals(False)
        self.buttons["new"].setEnabled(can("crm_pipeline", "CREATE"))
        for k in ("edit", "lines", "won", "lost"):
            self.buttons[k].setEnabled(can("crm_pipeline", "EDIT"))
        for k in ("proforma", "order"):
            self.buttons[k].setEnabled(can("crm_pipeline", "EDIT") and can("commercial_document_sales_order", "CREATE"))
        self.buttons["delete"].setEnabled(can("crm_pipeline", "DELETE"))
        self.reload()

    def reload(self) -> None:
        cid, pid = company_id(), self.pipeline.currentData()
        owner = user_id() if self.mine.isChecked() else None
        opp_sales.sync_won_from_sales(cid)
        self.board = opp_service.kanban(cid, pid, owner)
        while self.board_layout.count():
            w = self.board_layout.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        self.columns = {}
        for col in self.board:
            frame = QFrame()
            frame.setObjectName("card")
            fl = QVBoxLayout(frame)
            fl.setContentsMargins(6, 6, 6, 6)
            head = QLabel(P(f"{col.name}  ({len(col.cards)})\n{money(col.total)} — وزنی {money(col.weighted)}"
                            + (f"\nSLA: {col.sla_hours} ساعت" if col.sla_hours else "")))
            head.setObjectName("sectionTitle")
            head.setWordWrap(True)
            fl.addWidget(head)
            lst = _KanbanList(col.stage_id)
            lst.moved.connect(self.move_card)
            lst.itemDoubleClicked.connect(lambda _it: self.edit_opportunity())
            for o in col.cards:
                text = (f"{o.title}\n{o.customer_name or ('سرنخ: ' + o.lead_name)}\n{money(o.amount)} · {o.probability_percent.normalize()}٪"
                        + (f"\nپیش‌بینی: {_date(o.expected_close_date)}" if o.expected_close_date else "")
                        + f"\n{o.owner_name} · {o.days_in_stage} روز در مرحله" + ("  ⚠ SLA" if o.sla_overdue else ""))
                item = QListWidgetItem(P(text))
                item.setData(Qt.UserRole, o.opportunity_id)
                if o.sla_overdue:
                    item.setForeground(_RED)
                elif o.status_code == "WON":
                    item.setForeground(_GREEN)
                lst.addItem(item)
            fl.addWidget(lst, stretch=1)
            self.columns[col.stage_id] = lst
            self.board_layout.addWidget(frame)
        s = opp_service.pipeline_summary(cid, pid, owner)
        for key, value in (("value", money(s["pipeline_value"])), ("weighted", money(s["weighted_value"])), ("open", P(s["open_count"])),
                           ("won", P(f"{s['won_count']} — {money(s['won_value'])}")), ("lost", P(s["lost_count"])),
                           ("rate", P(f"{s['conversion_rate'].normalize()}٪"))):
            self.cards[key].setText(value)

    def selected_id(self):
        for lst in self.columns.values():
            item = lst.currentItem()
            if item is not None and item.isSelected():
                return item.data(Qt.UserRole)
        return None

    def select(self, opportunity_id: int) -> None:
        for lst in self.columns.values():
            for i in range(lst.count()):
                if lst.item(i).data(Qt.UserRole) == opportunity_id:
                    lst.setCurrentRow(i)
                    return

    def _need(self):
        oid = self.selected_id()
        if oid is None:
            QMessageBox.warning(self, "فرصت فروش", "یک کارت فرصت را انتخاب کنید.")
        return oid

    def move_card(self, opportunity_id: int, stage_id: int, lost_reason: str | None = None) -> bool:
        stage = next((col for col in self.board if col.stage_id == stage_id), None)
        if stage is not None and stage.stage_type == "LOST" and lost_reason is None:
            values = _ask(self, "از دست رفتن فرصت", [("reason", "دلیل", QLineEdit())])
            if values is None:
                self.reload()
                return False
            lost_reason = values.get("reason")
        _r, ok = _run(self, "قیف فروش", opp_service.move_stage, company_id(), user_id(), opportunity_id, stage_id, lost_reason)
        self.reload()
        self.select(opportunity_id)
        return ok

    def new_opportunity(self, values: dict | None = None) -> int | None:
        values = values or _ask(self, "فرصت فروش تازه", opportunity_form(self.lk, None, with_customer=True))
        if values is None:
            return None
        f = opportunity_fields(values)
        f.pipeline_id = self.pipeline.currentData()
        oid, ok = _run(self, "فرصت فروش", opp_service.create_opportunity, company_id(), user_id(), f)
        if ok:
            self.reload()
            self.select(oid)
        return oid

    def edit_opportunity(self, values: dict | None = None) -> bool:
        oid = self._need()
        if oid is None:
            return False
        row = opp_service.get_opportunity(company_id(), oid)
        values = values or _ask(self, "ویرایش فرصت", opportunity_form(self.lk, row, with_customer=True)
                                + [("probability", "احتمال موفقیت٪", num_field(row.probability_percent))])
        if values is None:
            return False
        f = opportunity_fields(values, lead_id=row.lead_id)
        f.probability_percent = values.get("probability")
        _r, ok = _run(self, "فرصت فروش", opp_service.update_opportunity, company_id(), user_id(), oid, f)
        if ok:
            self.reload()
            self.select(oid)
        return ok

    def edit_lines(self, lines: list | None = None) -> bool:
        oid = self._need()
        if oid is None:
            return False
        if lines is None:
            current = opp_service.list_lines(company_id(), oid)
            text = "\n".join(f"{ln.item_id or ''};{ln.quantity.normalize()};{ln.unit_price.normalize()};{ln.discount_amount.normalize()};{ln.description or ''}"
                             for ln in current)
            box = QTextEdit()
            box.setPlainText(text)
            values = _ask(self, "اقلام پیشنهادی", [("item", "افزودن کالا", combo(self.lk.items, "—")), ("lines", "ردیف‌ها", box)],
                          "هر خط: شناسهٔ کالا؛ مقدار؛ قیمت؛ تخفیف؛ شرح — با انتخاب کالا یک خط تازه با مقدار ۱ اضافه می‌شود.")
            if values is None:
                return False
            raw = (values.get("lines") or "").splitlines()
            if values.get("item"):
                raw.append(f"{values['item']};1;0;0;")
            try:
                lines = []
                for ln in raw:
                    if not ln.strip():
                        continue
                    parts = (numerals.to_ascii_digits(ln).split(";") + ["", "", "", "", ""])[:5]
                    lines.append(opp_service.LineFields(int(parts[0]) if parts[0].strip() else None, decimal.Decimal(parts[1] or 1),
                                                        decimal.Decimal(parts[2] or 0), decimal.Decimal(parts[3] or 0), parts[4].strip() or None))
            except (ValueError, decimal.InvalidOperation):
                QMessageBox.warning(self, "اقلام پیشنهادی", "قالب ردیف‌ها نادرست است.")
                return False
        _r, ok = _run(self, "اقلام پیشنهادی", opp_service.set_lines, company_id(), user_id(), oid, lines)
        if ok:
            self.reload()
            self.select(oid)
        return ok

    def add_activity(self, values: dict | None = None) -> int | None:
        oid = self._need()
        if oid is None:
            return None
        values = values or _ask(self, "فعالیت فرصت", activity_form(self.lk, kind="FOLLOW_UP"))
        if values is None:
            return None
        aid, ok = _run(self, "فعالیت", act_service.create_activity, company_id(), user_id(), activity_fields(values, opportunity_id=oid))
        return aid if ok else None

    def mark_won(self) -> bool:
        oid = self._need()
        if oid is None:
            return False
        _r, ok = _run(self, "قیف فروش", opp_service.mark_won, company_id(), user_id(), oid)
        self.reload()
        return ok

    def mark_lost(self, reason: str | None = None) -> bool:
        oid = self._need()
        if oid is None:
            return False
        if reason is None:
            values = _ask(self, "از دست رفتن فرصت", [("reason", "دلیل", QLineEdit())])
            if values is None:
                return False
            reason = values.get("reason") or ""
        _r, ok = _run(self, "قیف فروش", opp_service.mark_lost, company_id(), user_id(), oid, reason)
        self.reload()
        return ok

    def delete_opportunity(self) -> bool:
        oid = self._need()
        if oid is None or not _confirm(self, "قیف فروش", "فرصت انتخاب‌شده حذف شود؟"):
            return False
        _r, ok = _run(self, "قیف فروش", opp_service.delete_opportunity, company_id(), user_id(), oid)
        if ok:
            self.reload()
        return ok

    def _issue(self, document_type_code: str) -> int | None:
        oid = self._need()
        if oid is None:
            return None
        doc_id, ok = _run(self, "سند فروش", opp_sales.create_sales_document, company_id(), user_id(), oid, document_type_code)
        self.reload()
        self.select(oid)
        if ok:
            open_document(self._main_window, document_type_code, doc_id)
        return doc_id

    def issue_proforma(self) -> int | None:
        return self._issue("SALES_PROFORMA")

    def issue_order(self) -> int | None:
        return self._issue("SALES_ORDER")

    def show_chain(self) -> list | None:
        oid = self._need()
        if oid is None:
            return None
        chain = opp_sales.sales_chain(company_id(), oid)
        dlg = QDialog(self)
        dlg.setWindowTitle("اسناد فروش فرصت")
        dlg.setLayoutDirection(Qt.RightToLeft)
        lay = QVBoxLayout(dlg)
        t = table(["سند", "شماره", "تاریخ", "وضعیت", "مبلغ", "ماندهٔ تسویه"])
        fill(t, [[d["type_label"], d["document_no"], d["document_date"], d["status_code"], d["total_amount"],
                  ("تسویه‌شده" if d["paid"] else d["remaining_amount"]) if d["remaining_amount"] is not None else "—"] for d in chain],
             [(d["document_type_code"], d["document_id"]) for d in chain])
        t.cellDoubleClicked.connect(lambda r, _c: (open_document(self._main_window, *t.item(r, 0).data(Qt.UserRole)), dlg.accept()))
        lay.addWidget(QLabel("دوبار کلیک روی هر سند آن را در فرم فروش باز می‌کند (تبدیل، ثبت و تسویه همان‌جا)."))
        lay.addWidget(t)
        dlg.resize(760, 320)
        if getattr(self, "dialog_runner", None) is None:
            dlg.exec()
        return chain

    def open_customer(self) -> None:
        oid = self._need()
        if oid is None or self._main_window is None:
            return
        customer_id = opp_service.get_opportunity(company_id(), oid).customer_detail_account_id
        if customer_id:
            self._main_window.open_screen("CRM_CUSTOMER360", then=lambda s: s.load_customer(customer_id))


# =========================================================================================================
# تنظیمات CRM
# =========================================================================================================
@ms.styled
class CrmSettingsScreen(QWidget):
    scroll_in_mdi = True

    def __init__(self, main_window=None) -> None:
        super().__init__()
        self.dialog_runner = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        title = QLabel("تنظیمات ارتباط با مشتری")
        title.setObjectName("pageTitle")
        self.pipeline = QComboBox()
        self.pipeline.currentIndexChanged.connect(lambda _i: self.load_stages())
        outer.addWidget(ms.header_card(title, QLabel("قیف:"), self.pipeline))
        tabs = QTabWidget()
        st = QWidget()
        sl = QVBoxLayout(st)
        self.t_stages = table(["کد", "مرحله", "احتمال٪", "نوع", "SLA (ساعت)", "فیلدهای الزامی", "اقدام بعدی", "فعالیت خودکار"])
        sl.addWidget(self.t_stages, stretch=1)
        self.stage_buttons = {k: QPushButton(t) for k, t in (("new", "مرحلهٔ جدید"), ("edit", "ویرایش مرحله"), ("delete", "حذف مرحله"),
                                                            ("pipeline", "قیف جدید"), ("roles", "ساخت نقش‌های آمادهٔ CRM"))}
        self.stage_buttons["roles"].clicked.connect(lambda: self.create_roles())
        self.stage_buttons["new"].clicked.connect(lambda: self.edit_stage(new=True))
        self.stage_buttons["edit"].clicked.connect(lambda: self.edit_stage())
        self.stage_buttons["delete"].clicked.connect(lambda: self.delete_stage())
        self.stage_buttons["pipeline"].clicked.connect(lambda: self.new_pipeline())
        sl.addWidget(ms.footer([list(self.stage_buttons.values())]))
        tabs.addTab(st, "مراحل قیف فروش")
        so = QWidget()
        sol = QVBoxLayout(so)
        self.t_sources = table(["کد", "منبع", "ترتیب", "فعال", "سیستمی"])
        sol.addWidget(self.t_sources, stretch=1)
        self.source_buttons = {k: QPushButton(t) for k, t in (("new", "منبع جدید"), ("edit", "ویرایش منبع"))}
        self.source_buttons["new"].clicked.connect(lambda: self.edit_source(new=True))
        self.source_buttons["edit"].clicked.connect(lambda: self.edit_source())
        sol.addWidget(ms.footer([list(self.source_buttons.values())]))
        tabs.addTab(so, "منابع سرنخ")
        outer.addWidget(tabs, stretch=1)

    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        current = self.pipeline.currentData()
        self.pipeline.blockSignals(True)
        self.pipeline.clear()
        for p in pl_service.list_pipelines(cid):
            self.pipeline.addItem(p.name, p.pipeline_id)
        set_combo(self.pipeline, current)
        self.pipeline.blockSignals(False)
        admin = can("crm_settings", "EDIT")
        for b in list(self.stage_buttons.values()) + list(self.source_buttons.values()):
            b.setEnabled(admin)
        self.load_stages()
        self.load_sources()

    def create_roles(self) -> bool:
        from peecha.services.crm import roles_setup

        roles, ok = _run(self, "نقش‌ها", roles_setup.ensure_role_templates, company_id())
        if ok:
            QMessageBox.information(self, "نقش‌ها", "نقش‌ها ساخته یا به‌روز شد: " + "، ".join(roles_setup.TEMPLATES[k][0] for k in roles))
        return ok

    def load_stages(self) -> None:
        pid = self.pipeline.currentData()
        if pid is None:
            return
        self._stages = pl_service.list_stages(company_id(), pid, active_only=False)
        types = {"OPEN": "باز", "WON": "برنده", "LOST": "بازنده"}
        fill(self.t_stages, [[s.code, s.name + ("" if s.is_active else " (غیرفعال)"), s.probability_percent.normalize(), types[s.stage_type],
                              s.sla_hours or "", "، ".join(pl_service.STAGE_FIELDS.get(f, f) for f in s.required_fields or []),
                              s.next_action or "", (s.auto_activity or {}).get("subject", "")] for s in self._stages],
             [s.stage_id for s in self._stages])

    def load_sources(self) -> None:
        self._sources = pl_service.list_lead_sources(company_id(), active_only=False)
        fill(self.t_sources, [[s.code, s.name, s.sort_order, "بله" if s.is_active else "خیر", "بله" if s.company_id is None else ""]
                              for s in self._sources], [s.source_id for s in self._sources])

    def edit_stage(self, new: bool = False, values: dict | None = None) -> bool:
        sid = None if new else _selected(self.t_stages)
        if not new and sid is None:
            QMessageBox.warning(self, "مرحله", "یک مرحله را انتخاب کنید.")
            return False
        st = next((s for s in self._stages if s.stage_id == sid), None)
        g = (lambda name, default=None: getattr(st, name)) if st else (lambda name, default=None: default)
        auto = (st.auto_activity or {}) if st else {}
        if values is None:
            values = _ask(self, "مرحلهٔ قیف", [
                ("code", "کد", QLineEdit(g("code", "") or "")), ("name", "نام", QLineEdit(g("name", "") or "")),
                ("probability", "احتمال موفقیت٪", num_field(g("probability_percent", ZERO))),
                ("stage_type", "نوع", _with(combo([("باز", "OPEN"), ("برنده", "WON"), ("بازنده", "LOST")]), g("stage_type", "OPEN"))),
                ("sla", "SLA (ساعت، خالی = بدون SLA)", num_field(g("sla_hours"))),
                ("required", "فیلدهای الزامی (کدها با ویرگول: " + "، ".join(pl_service.STAGE_FIELDS) + ")",
                 QLineEdit(",".join(g("required_fields", []) or []))),
                ("next_action", "اقدام بعدی", QLineEdit(g("next_action", "") or "")),
                ("auto_type", "فعالیت خودکار", _with(combo([(v, k) for k, v in cc.ACTIVITY_TYPES.items() if k != "OPPORTUNITY"],
                                                          "— ندارد —"), auto.get("type"))),
                ("auto_subject", "موضوع فعالیت خودکار", QLineEdit(auto.get("subject", ""))),
                ("auto_days", "سررسید فعالیت (روز)", num_field(auto.get("due_in_days", 1))),
                ("is_active", "فعال", _checked(g("is_active", True)))])
            if values is None:
                return False
        required = [x.strip() for x in (values.get("required") or "").replace("،", ",").split(",") if x.strip()]
        auto_activity = ({"type": values["auto_type"], "subject": values.get("auto_subject") or "",
                          "due_in_days": int(values.get("auto_days") or 0)} if values.get("auto_type") else None)
        f = pl_service.StageFields(values.get("code") or "", values.get("name") or "", values.get("probability") or ZERO,
                                   values.get("stage_type") or "OPEN", int(values["sla"]) if values.get("sla") else None, required,
                                   values.get("next_action"), auto_activity, None, bool(values.get("is_active", True)))
        _r, ok = _run(self, "مرحلهٔ قیف", pl_service.save_stage, company_id(), user_id(), self.pipeline.currentData(), f, sid)
        if ok:
            self.load_stages()
        return ok

    def delete_stage(self) -> bool:
        sid = _selected(self.t_stages)
        if sid is None or not _confirm(self, "مرحله", "مرحلهٔ انتخاب‌شده حذف شود؟"):
            return False
        _r, ok = _run(self, "مرحله", pl_service.delete_stage, company_id(), user_id(), sid)
        if ok:
            self.load_stages()
        return ok

    def new_pipeline(self, values: dict | None = None) -> int | None:
        values = values or _ask(self, "قیف تازه", [("code", "کد", QLineEdit()), ("name", "نام", QLineEdit())],
                                "مراحل از قیف انتخاب‌شده کپی می‌شوند.")
        if values is None:
            return None
        pid, ok = _run(self, "قیف", pl_service.create_pipeline, company_id(), user_id(), values.get("code") or "",
                       values.get("name") or "", self.pipeline.currentData())
        if ok:
            self.refresh()
            set_combo(self.pipeline, pid)
        return pid

    def edit_source(self, new: bool = False, values: dict | None = None) -> bool:
        sid = None if new else _selected(self.t_sources)
        src = next((s for s in self._sources if s.source_id == sid), None)
        if not new and src is None:
            QMessageBox.warning(self, "منبع سرنخ", "یک منبع را انتخاب کنید.")
            return False
        values = values or _ask(self, "منبع سرنخ", [("code", "کد", QLineEdit(src.code if src else "")),
                                                   ("name", "نام", QLineEdit(src.name if src else "")),
                                                   ("sort", "ترتیب", num_field(src.sort_order if src else 150)),
                                                   ("active", "فعال", _checked(src.is_active if src else True))])
        if values is None:
            return False
        _r, ok = _run(self, "منبع سرنخ", pl_service.save_lead_source, company_id(), values.get("code") or "", values.get("name") or "",
                      sid, int(values.get("sort") or 150), bool(values.get("active")))
        if ok:
            self.load_sources()
        return ok


# =========================================================================================================
# تحلیل مشتری و سگمنت‌ها (R283)
class SegmentDialog(QDialog):
    """سازندهٔ قاعدهٔ سگمنت: هر ردیف «فیلد / عملگر / مقدار»؛ ترکیب ردیف‌ها با «و» یا «یا»."""

    def __init__(self, seg=None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("سگمنت مشتری")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(760, 460)
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.code, self.name = QLineEdit(seg.code if seg else ""), QLineEdit(seg.name if seg else "")
        self.code.setEnabled(not (seg and seg.is_system))
        self.match = combo([("همهٔ شرط‌ها برقرار باشد (و)", "all"), ("یکی از شرط‌ها کافی است (یا)", "any")])
        rule = seg.rule if seg else {"all": []}
        set_combo(self.match, "any" if "any" in rule else "all")
        self.active = QCheckBox("فعال")
        self.active.setChecked(seg.is_active if seg else True)
        for w in (QLabel("کد:"), self.code, QLabel("نام:"), self.name, self.match, self.active):
            top.addWidget(w)
        lay.addLayout(top)
        self.rows_box = QVBoxLayout()
        lay.addLayout(self.rows_box)
        self.rows: list[tuple[QWidget, QComboBox, QComboBox, QComboBox]] = []
        for cond in rule.get("all", rule.get("any")) or []:
            if "field" in cond:
                self.add_row(cond)
        if not self.rows:
            self.add_row()
        lay.addStretch(1)
        self.hint = QLabel("برای فیلد تاریخ، مقدار = «چند روز پیش». برای «یکی از» و «بین» مقدارها را با ویرگول جدا کنید.")
        self.hint.setObjectName("sectionHint")
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)
        buttons = QHBoxLayout()
        for text, slot in (("افزودن شرط", lambda: self.add_row()), ("پیش‌نمایش تعداد", self.preview), ("ذخیره", self._accept),
                           ("انصراف", self.reject)):
            b = QPushButton(text)
            b.clicked.connect(lambda _c=False, f=slot: f())
            buttons.addWidget(b)
        lay.addLayout(buttons)

    def add_row(self, cond: dict | None = None) -> None:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        field = combo([(f.label, k) for k, f in seg_service.FIELDS.items()])
        op = combo([(v, k) for k, v in seg_service.OPERATORS.items()])
        value = QComboBox()
        value.setEditable(True)
        rm = QPushButton("حذف")
        h.addWidget(field, 3)
        h.addWidget(op, 2)
        h.addWidget(value, 3)
        h.addWidget(rm)
        entry = (w, field, op, value)
        field.currentIndexChanged.connect(lambda _i: self._choices(entry))
        rm.clicked.connect(lambda _c=False: self._remove(entry))
        self.rows.append(entry)
        self.rows_box.addWidget(w)
        if cond:
            set_combo(field, cond["field"])
            set_combo(op, cond.get("op"))
        self._choices(entry)
        if cond:
            v = cond.get("value")
            if isinstance(v, dict) and "days_ago" in v:
                v = v["days_ago"]
            fd = seg_service.FIELDS.get(cond["field"])
            if fd and fd.choices and isinstance(v, str) and v in fd.choices:
                set_combo(value, v)
            else:
                value.setEditText(",".join(str(x) for x in v) if isinstance(v, list) else ("" if v is None else str(v)))

    def _choices(self, entry) -> None:
        _w, field, _op, value = entry
        fd = seg_service.FIELDS[field.currentData()]
        value.clear()
        for k, label in (fd.choices or {}).items():
            value.addItem(label, k)
        value.setEditText("")

    def _remove(self, entry) -> None:
        entry[0].setParent(None)
        self.rows.remove(entry)

    def rule(self) -> dict:
        conds = []
        for _w, field, op, value in self.rows:
            fd, o = seg_service.FIELDS[field.currentData()], op.currentData()
            text = value.currentText().strip()
            label_to_code = {v: k for k, v in (fd.choices or {}).items()}

            def conv(t: str):
                t = numerals.to_ascii_digits(t.strip())
                t = label_to_code.get(t, t)
                if fd.kind == "date":
                    return {"days_ago": int(t)}
                if fd.kind == "number":
                    return float(t) if "." in t else int(t)
                return t

            if o in ("is_null", "not_null"):
                conds.append({"field": field.currentData(), "op": o})
                continue
            if not text:
                continue
            try:
                v = [conv(x) for x in text.replace("،", ",").split(",") if x.strip()] if o in ("in", "not_in", "between") else conv(text)
            except ValueError as exc:
                raise ValueError(f"مقدار «{text}» برای «{fd.label}» معتبر نیست.") from exc
            conds.append({"field": field.currentData(), "op": o, "value": v})
        return {self.match.currentData(): conds}

    def values(self) -> dict:
        return {"code": self.code.text(), "name": self.name.text(), "rule": self.rule(), "is_active": self.active.isChecked()}

    def preview(self) -> None:
        try:
            n = seg_service.count(company_id(), self.rule())
        except ValueError as exc:
            QMessageBox.warning(self, "سگمنت", str(exc))
            return
        QMessageBox.information(self, "سگمنت", P(f"{n} مشتری در این سگمنت قرار می‌گیرند."))

    def _accept(self) -> None:
        try:
            seg_service.validate_rule(self.rule())
        except ValueError as exc:
            QMessageBox.warning(self, "سگمنت", str(exc))
            return
        self.accept()


@ms.styled
class AnalyticsScreen(QWidget):
    scroll_in_mdi = True

    def __init__(self, main_window=None) -> None:
        super().__init__()
        self._main_window = main_window
        self.dialog_runner = None
        self.rows: list[dict] = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        title = QLabel("تحلیل مشتری و سگمنت‌ها")
        title.setObjectName("pageTitle")
        self.segment = QComboBox()
        self.rfm = combo([(v, k) for k, v in analytics.RFM_SEGMENTS.items()], "همهٔ بخش‌های RFM")
        self.health = combo([(v[0], k) for k, v in analytics.insights.HEALTH_BANDS.items()], "همهٔ وضعیت‌های سلامت")
        self.churn = combo([(v, k) for k, v in analytics.insights.CHURN_BANDS.items()], "همهٔ سطوح ریسک ریزش")
        self.order = combo([("بیشترین ریسک ریزش", "churn"), ("کمترین سلامت", "health"), ("بیشترین ارزش طول عمر", "clv"),
                            ("بیشترین خرید ۱۲ ماه", "monetary")])
        for w in (self.segment, self.rfm, self.health, self.churn, self.order):
            w.currentIndexChanged.connect(lambda _i: self.reload())
        self.recalc = _quick("محاسبهٔ دوباره", self.recompute)
        outer.addWidget(ms.header_card(title, self.segment, self.rfm, self.health, self.churn, self.order, self.recalc))
        cards, self.cards = ms.summary([("healthy", "مشتری سالم", "success", "🟢"), ("attention", "نیازمند توجه", "warning", "🟡"),
                                        ("risk", "در معرض خطر", "danger", "🔴"), ("churn", "ریسک ریزش زیاد", "danger", "📉"),
                                        ("clv", "ارزش طول عمر کل (تاکنون)", "success", "💎"), ("clv_pred", "ارزش پیش‌بینی‌شده", "info", "🔮"),
                                        ("overdue", "بدهی معوق", "warning", "⏰"), ("computed", "آخرین محاسبه", "info", "🕒")], per_row=4)
        outer.addWidget(cards)
        self.tabs = QTabWidget()
        self.t = table(["کد", "مشتری", "RFM", "بخش RFM", "سلامت", "ریسک ریزش", "روز از آخرین خرید", "دفعات ۱۲ ماه",
                        "خرید ۱۲ ماه", "ارزش طول عمر", "پیش‌بینی ارزش", "بدهی معوق", "اقدام پیشنهادی"])
        self.t.cellDoubleClicked.connect(lambda _r, _c: self.open_customer())
        self.tabs.addTab(self.t, "مشتریان")
        self.t_rfm = table(["بخش RFM", "تعداد مشتری", "خرید ۱۲ ماه"])
        self.t_rfm.cellDoubleClicked.connect(lambda r, _c: set_combo(self.rfm, self.t_rfm.item(r, 0).data(Qt.UserRole)))
        self.tabs.addTab(self.t_rfm, "ماتریس RFM")
        sw = QWidget()
        sl = QVBoxLayout(sw)
        self.t_seg = table(["کد", "نام", "تعداد اعضا", "سیستمی", "فعال", "قاعده"])
        self.t_seg.cellDoubleClicked.connect(lambda _r, _c: self.edit_segment())
        sl.addWidget(self.t_seg, stretch=1)
        self.seg_buttons = {k: QPushButton(t) for k, t in (("new", "سگمنت جدید"), ("edit", "ویرایش سگمنت"),
                                                           ("delete", "حذف سگمنت"), ("members", "نمایش اعضا"))}
        self.seg_buttons["new"].clicked.connect(lambda: self.edit_segment(new=True))
        self.seg_buttons["edit"].clicked.connect(lambda: self.edit_segment())
        self.seg_buttons["delete"].clicked.connect(lambda: self.delete_segment())
        self.seg_buttons["members"].clicked.connect(lambda: self.show_members())
        sl.addWidget(ms.footer([list(self.seg_buttons.values())]))
        self.tabs.addTab(sw, "سگمنت‌ها")
        outer.addWidget(self.tabs, stretch=1)
        self.buttons = {"open": QPushButton("پروندهٔ ۳۶۰"), "activity": QPushButton("ثبت پیگیری پیشنهادی")}
        self.buttons["open"].clicked.connect(lambda: self.open_customer())
        self.buttons["activity"].clicked.connect(lambda: self.follow_up())
        outer.addWidget(ms.footer([list(self.buttons.values())]))

    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        analytics.ensure_fresh(cid)
        self.recalc.setEnabled(can("crm_analytics", "EDIT"))
        self.seg_buttons["new"].setEnabled(can("crm_analytics", "CREATE"))
        self.seg_buttons["edit"].setEnabled(can("crm_analytics", "EDIT"))
        self.seg_buttons["delete"].setEnabled(can("crm_analytics", "DELETE"))
        self.buttons["activity"].setEnabled(can("crm_activities", "CREATE"))
        self.load_segments()
        self.reload()

    def recompute(self) -> None:
        cid = company_id()
        n = analytics.refresh_scores(cid)
        seg_service.refresh_counts(cid)
        self.load_segments()
        self.reload()
        if not self.dialog_runner:
            QMessageBox.information(self, "تحلیل مشتری", P(f"امتیاز {n} مشتری دوباره محاسبه شد."))

    def load_segments(self) -> None:
        cid = company_id()
        if any(s.member_count is None for s in seg_service.list_segments(cid, active_only=True)):
            seg_service.refresh_counts(cid)
        self._segs = seg_service.list_segments(cid)
        current = self.segment.currentData()
        self.segment.blockSignals(True)
        self.segment.clear()
        self.segment.addItem("همهٔ مشتریان", None)
        for s in self._segs:
            if s.is_active:
                self.segment.addItem(f"{s.name} ({P(s.member_count or 0)})", s.segment_id)
        set_combo(self.segment, current)
        self.segment.blockSignals(False)
        fill(self.t_seg, [[s.code, s.name, s.member_count if s.member_count is not None else "", "بله" if s.is_system else "",
                           "بله" if s.is_active else "خیر", self._rule_text(s.rule)] for s in self._segs],
             [s.segment_id for s in self._segs])

    @staticmethod
    def _rule_text(rule: dict) -> str:
        joiner = " و " if "all" in rule else " یا "
        parts = []
        for cnd in rule.get("all", rule.get("any")) or []:
            if "field" not in cnd:
                parts.append("(گروه شرط)")
                continue
            fd = seg_service.FIELDS.get(cnd["field"])
            v = cnd.get("value")
            if isinstance(v, dict) and "days_ago" in v:
                v = f"{v['days_ago']} روز پیش"
            elif fd and fd.choices:
                v = "، ".join(fd.choices.get(x, str(x)) for x in v) if isinstance(v, list) else fd.choices.get(v, v)
            parts.append(f"{fd.label if fd else cnd['field']} {seg_service.OPERATORS.get(cnd['op'], cnd['op'])} {'' if v is None else v}".strip())
        return P(joiner.join(parts))

    def reload(self) -> None:
        cid = company_id()
        sid = self.segment.currentData()
        ids = seg_service.members(cid, sid) if sid else None
        self.rows = analytics.list_scores(cid, rfm_segment_code=self.rfm.currentData(), health_band=self.health.currentData(),
                                          churn_band=self.churn.currentData(), customer_ids=ids, order=self.order.currentData())
        fill(self.t, [[r["code"], r["name"], f"{r['r_score'] or '-'}{r['f_score'] or '-'}{r['m_score'] or '-'}", r["rfm_label"],
                       f"{r['health_score']} {r['health_label']}", f"{r['churn_risk']}٪ {r['churn_label']}",
                       r["recency_days"] if r["recency_days"] is not None else "—", r["frequency_365"], r["monetary_365"],
                       r["clv_historical"], r["clv_predicted"], r["overdue_amount"], r["next_best_action"] or ""] for r in self.rows],
             [r["customer_detail_account_id"] for r in self.rows])
        tone = {"AT_RISK": _RED, "ATTENTION": _AMBER, "HEALTHY": _GREEN}
        for i, r in enumerate(self.rows):
            self.t.item(i, 4).setForeground(tone[r["health_band"]])
            if r["churn_band"] == "HIGH":
                self.t.item(i, 5).setForeground(_RED)
        counts = {"HEALTHY": 0, "ATTENTION": 0, "AT_RISK": 0}
        for r in self.rows:
            counts[r["health_band"]] += 1
        self.cards["healthy"].setText(P(counts["HEALTHY"]))
        self.cards["attention"].setText(P(counts["ATTENTION"]))
        self.cards["risk"].setText(P(counts["AT_RISK"]))
        self.cards["churn"].setText(P(sum(1 for r in self.rows if r["churn_band"] == "HIGH")))
        self.cards["clv"].setText(money(sum((r["clv_historical"] for r in self.rows), ZERO)))
        self.cards["clv_pred"].setText(money(sum((r["clv_predicted"] for r in self.rows), ZERO)))
        self.cards["overdue"].setText(money(sum((r["overdue_amount"] for r in self.rows), ZERO)))
        newest = max((r["computed_at"] for r in self.rows), default=None)
        self.cards["computed"].setText(_date(newest.date()) if newest else "—")
        matrix = analytics.rfm_matrix(cid)
        fill(self.t_rfm, [[m["label"], m["count"], m["monetary"]] for m in matrix], [m["code"] for m in matrix])

    def _selected_seg(self):
        sid = _selected(self.t_seg)
        return next((s for s in self._segs if s.segment_id == sid), None)

    def edit_segment(self, new: bool = False, values: dict | None = None) -> int | None:
        seg = None if new else self._selected_seg()
        if not new and seg is None:
            QMessageBox.warning(self, "سگمنت", "یک سگمنت را انتخاب کنید.")
            return None
        if values is None:
            dlg = SegmentDialog(seg, self)
            ok = self.dialog_runner(dlg) if self.dialog_runner else dlg.exec() == QDialog.Accepted
            if not ok:
                return None
            values = dlg.values()
        sid, ok = _run(self, "سگمنت", seg_service.save_segment, company_id(), user_id(),
                       segment_id=seg.segment_id if seg else None, **values)
        if ok:
            seg_service.refresh_counts(company_id())
            self.load_segments()
        return sid if ok else None

    def delete_segment(self) -> bool:
        seg = self._selected_seg()
        if seg is None or not _confirm(self, "سگمنت", f"سگمنت «{seg.name}» حذف شود؟"):
            return False
        _r, ok = _run(self, "سگمنت", seg_service.delete_segment, company_id(), user_id(), seg.segment_id)
        if ok:
            self.load_segments()
        return ok

    def show_members(self) -> None:
        seg = self._selected_seg()
        if seg is None:
            return
        set_combo(self.segment, seg.segment_id)
        self.tabs.setCurrentIndex(0)

    def _row(self):
        cid = _selected(self.t)
        return next((r for r in self.rows if r["customer_detail_account_id"] == cid), None)

    def open_customer(self) -> None:
        r = self._row()
        if r is not None and self._main_window is not None:
            self._main_window.open_screen("CRM_CUSTOMER360", then=lambda s: s.load_customer(r["customer_detail_account_id"]))

    def follow_up(self, values: dict | None = None) -> int | None:
        """فعالیت پیگیری با موضوع «اقدام پیشنهادی» مشتری انتخاب‌شده."""
        r = self._row()
        if r is None:
            QMessageBox.warning(self, "پیگیری", "یک مشتری را انتخاب کنید.")
            return None
        lk = CrmLookups(company_id())
        if values is None:
            values = _ask(self, "ثبت پیگیری", activity_form(lk, kind="FOLLOW_UP"))
            if values is None:
                return None
        if not values.get("subject"):
            values["subject"] = r["next_best_action"] or "پیگیری مشتری"
        aid, ok = _run(self, "پیگیری", act_service.create_activity, company_id(), user_id(),
                       activity_fields(values, customer_detail_account_id=r["customer_detail_account_id"]))
        return aid if ok else None


# =========================================================================================================
# کمپین‌ها، باشگاه مشتریان و امتیاز سرنخ (R284)
@ms.styled
class CampaignsScreen(QWidget):
    scroll_in_mdi = True

    def __init__(self, main_window=None) -> None:
        super().__init__()
        self._main_window = main_window
        self.dialog_runner = None
        self.rows: list = []
        self.members: list[dict] = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        title = QLabel("کمپین‌ها و باشگاه مشتریان")
        title.setObjectName("pageTitle")
        self.search = QLineEdit()
        self.search.setPlaceholderText("جستجوی نام کمپین")
        self.search.returnPressed.connect(self.reload)
        self.status = combo([(v, k) for k, v in camp_service.STATUS.items()], "همهٔ وضعیت‌ها")
        self.status.currentIndexChanged.connect(lambda _i: self.reload())
        outer.addWidget(ms.header_card(title, self.search, self.status))
        cards, self.cards = ms.summary([("active", "کمپین فعال", "info", "📣"), ("members", "مخاطبان کمپین انتخابی", "info", "👥"),
                                        ("response", "نرخ پاسخ", "success", "💬"), ("leads", "سرنخ‌ها / تبدیل‌شده", "warning", "🧲"),
                                        ("revenue", "فروش نسبت‌داده‌شده", "success", "💰"), ("roi", "بازگشت سرمایه (ROI)", "success", "📈"),
                                        ("cpl", "هزینه به ازای سرنخ", "warning", "🎯"), ("won", "فرصت برنده / مبلغ", "success", "🏆")],
                                       per_row=4)
        outer.addWidget(cards)
        self.tabs = QTabWidget()
        cw = QWidget()
        cl = QVBoxLayout(cw)
        split = QSplitter(Qt.Horizontal)
        self.t = table(["شماره", "نام", "نوع", "وضعیت", "سگمنت", "شروع", "پایان", "مخاطبان", "بودجه", "هزینه", "مسئول"])
        self.t.itemSelectionChanged.connect(self._selected_changed)
        self.t.cellDoubleClicked.connect(lambda _r, _c: self.edit_campaign())
        split.addWidget(self.t)
        self.t_members = table(["مخاطب", "تماس", "وضعیت", "پاسخ", "یادداشت"])
        split.addWidget(self.t_members)
        split.setSizes([800, 480])
        cl.addWidget(split, stretch=1)
        self.buttons = {k: QPushButton(t) for k, t in (
            ("new", "کمپین جدید"), ("edit", "ویرایش"), ("delete", "حذف"), ("build", "ساخت مخاطبان از سگمنت"),
            ("add_customer", "افزودن مشتری"), ("add_lead", "افزودن سرنخ"), ("launch", "اجرای کمپین"), ("complete", "پایان"),
            ("cancel", "لغو"), ("responded", "پاسخ داد"), ("converted", "تبدیل شد"), ("opted_out", "انصراف"),
            ("new_lead", "ثبت سرنخ از کمپین"))}
        actions = {"new": lambda: self.new_campaign(), "edit": lambda: self.edit_campaign(), "delete": lambda: self.delete_campaign(),
                   "build": lambda: self.build_members(), "add_customer": lambda: self.add_customer(), "add_lead": lambda: self.add_lead(),
                   "launch": lambda: self.launch(), "complete": lambda: self.close_campaign("COMPLETED"),
                   "cancel": lambda: self.close_campaign("CANCELLED"), "responded": lambda: self.member_status("RESPONDED"),
                   "converted": lambda: self.member_status("CONVERTED"), "opted_out": lambda: self.member_status("OPTED_OUT"),
                   "new_lead": lambda: self.new_lead()}
        for k, b in self.buttons.items():
            b.clicked.connect(lambda _c=False, f=actions[k]: f())
        B = self.buttons
        cl.addWidget(ms.footer([[B["new"], B["edit"], B["delete"]], [B["build"], B["add_customer"], B["add_lead"]],
                                [B["launch"], B["complete"], B["cancel"]], [B["responded"], B["converted"], B["opted_out"], B["new_lead"]]]))
        self.tabs.addTab(cw, "کمپین‌ها")
        self.tabs.addTab(self._loyalty_tab(), "باشگاه مشتریان")
        self.tabs.addTab(self._scoring_tab(), "امتیاز سرنخ")
        outer.addWidget(self.tabs, stretch=1)

    # --- باشگاه مشتریان ---
    def _loyalty_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.l_enabled = QCheckBox("باشگاه مشتریان فعال است (امتیاز خرید از فاکتورهای ثبت‌شده)")
        self.l_fields = {k: num_field() for k in ("amount_per_point", "first_purchase_bonus", "repeat_every", "repeat_bonus",
                                                   "referral_points", "SILVER", "GOLD", "PLATINUM")}
        labels = {"amount_per_point": "مبلغ هر امتیاز", "first_purchase_bonus": "جایزهٔ اولین خرید", "repeat_every": "هر چندمین خرید",
                  "repeat_bonus": "جایزهٔ خرید تکراری", "referral_points": "امتیاز معرفی", "SILVER": "مرز نقره‌ای", "GOLD": "مرز طلایی",
                  "PLATINUM": "مرز پلاتینی"}
        lay.addWidget(self.l_enabled)
        grid = QHBoxLayout()
        for k, f in self.l_fields.items():
            box = QVBoxLayout()
            box.addWidget(QLabel(labels[k]))
            box.addWidget(f)
            grid.addLayout(box)
        lay.addLayout(grid)
        self.l_customer = QComboBox()
        self.l_customer.currentIndexChanged.connect(lambda _i: self.load_loyalty_customer())
        self.l_summary = QLabel("")
        self.l_summary.setObjectName("sectionHint")
        row = QHBoxLayout()
        row.addWidget(QLabel("مشتری:"))
        row.addWidget(self.l_customer, 1)
        row.addWidget(self.l_summary, 2)
        lay.addLayout(row)
        self.t_loyalty = table(["تاریخ", "نوع", "امتیاز", "کیف پول", "سند"])
        lay.addWidget(self.t_loyalty, stretch=1)
        self.l_buttons = {"save": QPushButton("ذخیرهٔ قواعد"), "award": QPushButton("اعمال امتیاز فاکتورها"),
                          "adjust": QPushButton("اصلاح امتیاز"), "referral": QPushButton("ثبت معرفی")}
        self.l_buttons["save"].clicked.connect(lambda: self.save_loyalty())
        self.l_buttons["award"].clicked.connect(lambda: self.award())
        self.l_buttons["adjust"].clicked.connect(lambda: self.adjust_points())
        self.l_buttons["referral"].clicked.connect(lambda: self.referral())
        lay.addWidget(ms.footer([list(self.l_buttons.values())]))
        return w

    def _scoring_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        hint = QLabel("سقف امتیاز هر عامل (۰ تا ۵۰) و مرز سطح‌ها؛ پس از ذخیره، سرنخ‌های باز دوباره امتیازدهی می‌شوند.")
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.s_factors = {k: num_field() for k in lead_service.FACTOR_MAX}
        self.s_bands = {k: num_field() for k in ("VERY_HOT", "HOT", "WARM")}
        for group, labels in ((self.s_factors, lead_service.FACTOR_LABELS), (self.s_bands, cc.SCORE_BANDS)):
            row = QHBoxLayout()
            for k, f in group.items():
                box = QVBoxLayout()
                box.addWidget(QLabel(labels[k]))
                box.addWidget(f)
                row.addLayout(box)
            lay.addLayout(row)
        self.t_sources = table(["منبع", "امتیاز"])
        self.t_sources.setEditTriggers(QAbstractItemView.AllEditTriggers)
        lay.addWidget(self.t_sources, stretch=1)
        self.s_save = QPushButton("ذخیرهٔ امتیازدهی سرنخ")
        self.s_save.clicked.connect(lambda: self.save_scoring())
        lay.addWidget(ms.footer([[self.s_save]]))
        return w

    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        self.lk = CrmLookups(cid)
        for k in ("new",):
            self.buttons[k].setEnabled(can("crm_campaigns", "CREATE"))
        for k in ("edit", "build", "add_customer", "add_lead", "launch", "complete", "cancel", "responded", "converted", "opted_out"):
            self.buttons[k].setEnabled(can("crm_campaigns", "EDIT"))
        self.buttons["delete"].setEnabled(can("crm_campaigns", "DELETE"))
        self.buttons["new_lead"].setEnabled(can("crm_leads", "CREATE"))
        admin = can("crm_settings", "EDIT")
        self.l_buttons["save"].setEnabled(admin)
        self.s_save.setEnabled(admin)
        for k in ("award", "adjust", "referral"):
            self.l_buttons[k].setEnabled(can("crm_campaigns", "EDIT"))
        current = self.l_customer.currentData()
        self.l_customer.blockSignals(True)
        self.l_customer.clear()
        for label, value in self.lk.customers:
            self.l_customer.addItem(label, value)
        set_combo(self.l_customer, current)
        self.l_customer.blockSignals(False)
        self.load_settings()
        camp_service.sync_delivery(cid)
        self.reload()
        self.load_loyalty_customer()

    def load_settings(self) -> None:
        cid = company_id()
        rules = loyalty_service.get_rules(cid)
        self.l_enabled.setChecked(bool(rules["enabled"]))
        for k, f in self.l_fields.items():
            f.setText(str(rules["tiers"][k] if k in rules["tiers"] else rules[k]))
        from peecha.db.base import new_session

        with new_session() as session:
            cfg = lead_service.scoring_config(session, cid)
        for k, f in self.s_factors.items():
            f.setText(str(cfg["factor_max"][k]))
        bands = dict(cfg["bands"])
        for k, f in self.s_bands.items():
            f.setText(str(bands[k]))
        sources = pl_service.list_lead_sources(cid)
        fill(self.t_sources, [[s.name, cfg["source_points"].get(s.code, 5)] for s in sources], [s.code for s in sources])
        self.t_sources.setEditTriggers(QAbstractItemView.AllEditTriggers)

    def reload(self) -> None:
        cid = company_id()
        self.rows = camp_service.list_campaigns(cid, self.status.currentData(), self.search.text().strip() or None)
        fill(self.t, [[r.campaign_no, r.name, r.type_label, r.status_label, r.segment_name, r.start_date or "", r.end_date or "",
                       r.member_count, r.budget_amount if r.budget_amount is not None else "", r.actual_cost, r.owner_name]
                      for r in self.rows], [r.campaign_id for r in self.rows])
        self.cards["active"].setText(P(sum(1 for r in self.rows if r.status_code in ("ACTIVE", "SCHEDULED"))))
        self._selected_changed()

    def _row(self):
        cid = _selected(self.t)
        return next((r for r in self.rows if r.campaign_id == cid), None)

    def _need(self):
        r = self._row()
        if r is None:
            QMessageBox.warning(self, "کمپین", "یک کمپین را انتخاب کنید.")
        return r

    def _selected_changed(self) -> None:
        r = self._row()
        if r is None:
            fill(self.t_members, [])
            for k in ("members", "response", "leads", "revenue", "roi", "cpl", "won"):
                self.cards[k].setText("—")
            return
        cid = company_id()
        self.members = camp_service.list_members(cid, r.campaign_id)
        fill(self.t_members, [[m["name"], m["contact"] or "", m["status_label"], m["responded_at"].date() if m["responded_at"] else "",
                               m["note"] or ""] for m in self.members], [m["member_id"] for m in self.members])
        a = camp_service.campaign_analytics(cid, r.campaign_id)
        self.cards["members"].setText(P(a["members"]))
        self.cards["response"].setText(P(f"{a['response_rate']}٪") if a["response_rate"] is not None else "—")
        self.cards["leads"].setText(P(f"{a['leads']} / {a['leads_converted']}"))
        self.cards["revenue"].setText(money(a["revenue"]))
        self.cards["roi"].setText(P(f"{a['roi_percent']}٪") if a["roi_percent"] is not None else "—")
        self.cards["cpl"].setText(money(a["cost_per_lead"]) if a["cost_per_lead"] is not None else "—")
        self.cards["won"].setText(P(f"{a['opportunities_won']} / ") + money(a["won_amount"]))

    def _form(self, r=None) -> list:
        segs = [(s.name, s.segment_id) for s in seg_service.list_segments(company_id(), active_only=True)]
        g = (lambda name, default=None: getattr(r, name)) if r else (lambda name, default=None: default)
        today = datetime.date.today()
        return [("name", "نام کمپین", QLineEdit(g("name", "") or "")),
                ("campaign_type", "نوع", _with(combo([(v, k) for k, v in camp_service.TYPES.items()]), g("campaign_type", "SMS"))),
                ("segment_id", "سگمنت مخاطبان", _with(combo(segs, "— بدون سگمنت —"), g("segment_id"))),
                ("lead_source_id", "منبع سرنخ‌های کمپین", _with(combo(self.lk.sources, "—"), g("lead_source_id"))),
                ("start_date", "شروع", date_field(g("start_date") or today)),
                ("end_date", "پایان", date_field(g("end_date") or today + datetime.timedelta(days=30))),
                ("attribution_days", "بازهٔ نسبت‌دهی فروش (روز پس از پایان)", num_field(g("attribution_days", 30))),
                ("budget_amount", "بودجه", num_field(g("budget_amount"))), ("actual_cost", "هزینهٔ واقعی", num_field(g("actual_cost", 0))),
                ("expected_revenue", "درآمد مورد انتظار", num_field(g("expected_revenue"))),
                ("owner_user_id", "مسئول", _with(combo(self.lk.users, "— خودم —"), g("owner_user_id"))),
                ("message_text", "متن پیام (کمپین پیامکی)", _text(g("message_text"))),
                ("description", "توضیحات", _text(g("description")))]

    @staticmethod
    def _fields(v: dict) -> camp_service.CampaignFields:
        return camp_service.CampaignFields(
            v["name"] or "", v.get("campaign_type") or "SMS", segment_id=v.get("segment_id"), lead_source_id=v.get("lead_source_id"),
            start_date=v.get("start_date"), end_date=v.get("end_date"), attribution_days=int(v.get("attribution_days") or 0),
            budget_amount=v.get("budget_amount"), actual_cost=v.get("actual_cost") or ZERO, expected_revenue=v.get("expected_revenue"),
            message_text=v.get("message_text"), owner_user_id=v.get("owner_user_id"), description=v.get("description"))

    def new_campaign(self, values: dict | None = None) -> int | None:
        values = values or _ask(self, "کمپین جدید", self._form())
        if values is None:
            return None
        cid, ok = _run(self, "کمپین", camp_service.create_campaign, company_id(), user_id(), self._fields(values))
        if ok:
            self.reload()
        return cid if ok else None

    def edit_campaign(self, values: dict | None = None) -> bool:
        r = self._need()
        if r is None:
            return False
        values = values or _ask(self, "ویرایش کمپین", self._form(r))
        if values is None:
            return False
        _x, ok = _run(self, "کمپین", camp_service.update_campaign, company_id(), user_id(), r.campaign_id, self._fields(values))
        if ok:
            self.reload()
        return ok

    def delete_campaign(self) -> bool:
        r = self._need()
        if r is None or not _confirm(self, "کمپین", f"کمپین «{r.name}» حذف شود؟"):
            return False
        _x, ok = _run(self, "کمپین", camp_service.delete_campaign, company_id(), user_id(), r.campaign_id)
        if ok:
            self.reload()
        return ok

    def _after(self, campaign_id: int) -> None:
        self.reload()
        for i in range(self.t.rowCount()):
            if self.t.item(i, 0).data(Qt.UserRole) == campaign_id:
                self.t.selectRow(i)

    def build_members(self) -> int | None:
        r = self._need()
        if r is None:
            return None
        n, ok = _run(self, "مخاطبان", camp_service.build_members, company_id(), user_id(), r.campaign_id)
        if ok:
            self._after(r.campaign_id)
        return n if ok else None

    def add_customer(self, values: dict | None = None) -> int | None:
        r = self._need()
        if r is None:
            return None
        values = values or _ask(self, "افزودن مشتری", [("customer", "مشتری", combo(self.lk.customers))])
        if not values or not values.get("customer"):
            return None
        n, ok = _run(self, "مخاطبان", camp_service.add_customers, company_id(), user_id(), r.campaign_id, [values["customer"]])
        if ok:
            self._after(r.campaign_id)
        return n if ok else None

    def add_lead(self, values: dict | None = None) -> int | None:
        r = self._need()
        if r is None:
            return None
        leads = [(f"{x.lead_no} — {x.full_name}", x.lead_id) for x in lead_service.list_leads(company_id(), open_only=True)]
        values = values or _ask(self, "افزودن سرنخ", [("lead", "سرنخ", combo(leads))])
        if not values or not values.get("lead"):
            return None
        n, ok = _run(self, "مخاطبان", camp_service.add_leads, company_id(), user_id(), r.campaign_id, [values["lead"]])
        if ok:
            self._after(r.campaign_id)
        return n if ok else None

    def launch(self, confirm: bool = True) -> dict | None:
        r = self._need()
        if r is None:
            return None
        if confirm and not _confirm(self, "اجرای کمپین", f"کمپین «{r.name}» برای {P(r.member_count)} مخاطب اجرا شود؟"):
            return None
        res, ok = _run(self, "اجرای کمپین", camp_service.launch, company_id(), user_id(), r.campaign_id)
        if ok:
            self._after(r.campaign_id)
        return res if ok else None

    def close_campaign(self, status_code: str) -> bool:
        r = self._need()
        if r is None:
            return False
        _x, ok = _run(self, "کمپین", camp_service.set_status, company_id(), user_id(), r.campaign_id, status_code)
        if ok:
            self._after(r.campaign_id)
        return ok

    def member_status(self, status_code: str) -> bool:
        r, mid = self._row(), _selected(self.t_members)
        if r is None or mid is None:
            QMessageBox.warning(self, "مخاطب", "یک مخاطب را انتخاب کنید.")
            return False
        _x, ok = _run(self, "مخاطب", camp_service.set_member_status, company_id(), user_id(), mid, status_code)
        if ok:
            self._after(r.campaign_id)
        return ok

    def new_lead(self, values: dict | None = None) -> int | None:
        """سرنخ پاسخ‌دهنده به کمپین (نسبت‌دادن خودکار به کمپین)."""
        r = self._need()
        if r is None:
            return None
        values = values or _ask(self, "سرنخ از کمپین", [("full_name", "نام", QLineEdit()), ("mobile", "موبایل", QLineEdit()),
                                                        ("interested_text", "علاقه/نیاز", QLineEdit())])
        if values is None:
            return None
        lid, ok = _run(self, "سرنخ", lead_service.create_lead, company_id(), user_id(), lead_service.LeadFields(
            values.get("full_name") or "", mobile=values.get("mobile"), interested_text=values.get("interested_text")),
            campaign_id=r.campaign_id)
        if ok:
            self._after(r.campaign_id)
        return lid if ok else None

    # --- باشگاه و امتیاز ---
    def save_loyalty(self) -> bool:
        def num(k):
            return int(numerals.to_ascii_digits(self.l_fields[k].text().strip() or "0").replace(",", "").split(".")[0])

        _x, ok = _run(self, "باشگاه مشتریان", loyalty_service.save_rules, company_id(), user_id(), enabled=self.l_enabled.isChecked(),
                      amount_per_point=num("amount_per_point"), first_purchase_bonus=num("first_purchase_bonus"),
                      repeat_every=num("repeat_every"), repeat_bonus=num("repeat_bonus"), referral_points=num("referral_points"),
                      tiers={k: num(k) for k in ("SILVER", "GOLD", "PLATINUM")})
        return ok

    def award(self) -> dict | None:
        res, ok = _run(self, "باشگاه مشتریان", loyalty_service.award_for_invoices, company_id())
        if ok:
            self.load_loyalty_customer()
            if not self.dialog_runner:
                QMessageBox.information(self, "باشگاه مشتریان", P(f"{res['points']} امتیاز برای {res['invoices']} فاکتور ثبت شد."))
        return res if ok else None

    def load_loyalty_customer(self) -> None:
        cust = self.l_customer.currentData()
        if cust is None:
            self.l_summary.setText("")
            fill(self.t_loyalty, [])
            return
        s = loyalty_service.summary(company_id(), cust)
        self.l_summary.setText(P(f"امتیاز: {s['points']} — سطح: {s['tier_label']} — کل امتیاز کسب‌شده: {s['lifetime_points']} — "
                                 f"کیف پول: ") + money(s["wallet"]))
        types = {"EARN": "کسب", "REDEEM": "مصرف", "ADJUST": "اصلاح"}
        fill(self.t_loyalty, [[t["at"].date(), types.get(t["type"], t["type"]), t["points"], t["wallet"], t["document_no"] or ""]
                              for t in s["transactions"]])

    def adjust_points(self, values: dict | None = None) -> int | None:
        cust = self.l_customer.currentData()
        if cust is None:
            return None
        values = values or _ask(self, "اصلاح امتیاز", [("points", "امتیاز (منفی برای کسر)", num_field()), ("reason", "علت", QLineEdit())])
        if values is None:
            return None
        bal, ok = _run(self, "اصلاح امتیاز", loyalty_service.adjust_points, company_id(), user_id(), cust, int(values.get("points") or 0),
                       values.get("reason") or "")
        if ok:
            self.load_loyalty_customer()
        return bal if ok else None

    def referral(self, values: dict | None = None) -> int | None:
        cust = self.l_customer.currentData()
        if cust is None:
            return None
        values = values or _ask(self, "ثبت معرفی", [("referred", "مشتری معرفی‌شده", combo(self.lk.customers))])
        if not values or not values.get("referred"):
            return None
        pts, ok = _run(self, "معرفی", loyalty_service.award_referral, company_id(), user_id(), cust, values["referred"])
        if ok:
            self.load_loyalty_customer()
        return pts if ok else None

    def save_scoring(self) -> bool:
        def num(f):
            return int(numerals.to_ascii_digits(f.text().strip() or "0").split(".")[0])

        sources = {}
        for i in range(self.t_sources.rowCount()):
            code = self.t_sources.item(i, 0).data(Qt.UserRole)
            sources[code] = int(numerals.to_ascii_digits(self.t_sources.item(i, 1).text().strip() or "0").split(".")[0])
        _x, ok = _run(self, "امتیاز سرنخ", lead_service.save_scoring_config, company_id(), user_id(),
                      factor_max={k: num(f) for k, f in self.s_factors.items()}, source_points=sources,
                      bands={k: num(f) for k, f in self.s_bands.items()})
        return ok
