"""R319: «تنظیمات › ارتباط با مشتری» — پیام‌رسان‌ها (ربات رسمی و درگاه عمومی، شناسهٔ گفت‌وگوی طرف حساب) و «پیام پس از
فرایند» (پس از رویداد X، الگوی Y برای Z). همان الگوهای پیام و دفتر پیام‌های مرکز ارتباطات به‌کار می‌رود."""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QLabel, QLineEdit, QPushButton, QVBoxLayout

from peecha.services import detail_dimensions as dims
from peecha.services import inventory_engine as engine
from peecha.services.crm import common as cc
from peecha.services.crm import communication as comm_service
from peecha.services.crm import messengers as msg_service
from peecha.ui import theme
from peecha.ui.screens import module_style as ms
from peecha.ui.screens.costing import can
from peecha.ui.screens.crm import _CrmPanel, _ask, _checked, _confirm, _run, _selected, _text, _with
from peecha.ui.screens.fixed_assets import P, combo, company_id, fill, table, user_id

_FORM = "crm_automation"


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("sectionHint")
    label.setWordWrap(True)
    return label


def _icon(glyph: str, tip: str, kind: str = "") -> QPushButton:
    button = QPushButton(glyph)
    button.setObjectName(ms._OBJECT_NAMES[kind])
    button.setFixedWidth(48 if kind == "primary" else 44)
    button.setToolTip(tip)
    button.setAccessibleName(tip)
    return button


def _feature_box(on_toggle) -> QCheckBox:
    box = QCheckBox("ارسال خودکار پیام پس از فرایندها (پیامک، واتس‌اپ، بله، تلگرام، ایتا، روبیکا)")
    box.toggled.connect(on_toggle)
    return box


class MessengersPanel(_CrmPanel):
    """ربات‌ها و درگاه‌ها + شناسهٔ گفت‌وگوی هر طرف حساب."""

    def __init__(self, host=None) -> None:
        super().__init__(host)
        self.settings: list = []
        self.chats: list = []
        lay = QVBoxLayout(self)
        lay.addWidget(_hint("بله، تلگرام، ایتا و روبیکا با ربات رسمی همان پیام‌رسان کار می‌کنند: ربات را در خود پیام‌رسان بسازید و "
                            "توکنش را این‌جا وارد کنید. گیرنده باید یک بار به ربات پیام داده باشد تا شناسهٔ گفت‌وگویش معلوم شود؛ "
                            "برای گروه یا کانال هم ربات را عضو کنید. واتس‌اپ از درگاه عمومی (مثل درگاه پیامک) با نشانی دارای "
                            "{phone} و {text} فرستاده می‌شود."))
        self.feature = _feature_box(self._toggle_feature)
        lay.addWidget(self.feature)
        self.t_channels = table(["پیام‌رسان", "روش", "وضعیت", "آخرین خطا"])
        self.t_channels.cellDoubleClicked.connect(lambda _r, _c: self.edit_channel())
        lay.addWidget(self.t_channels, stretch=1)
        self.channel_buttons = {k: _icon(g, t, kind) for k, g, t, kind in (
            ("edit", "✏️", "تنظیم پیام‌رسان", ""), ("test", "🔌", "بررسی اتصال ربات", ""))}
        self.channel_buttons["edit"].clicked.connect(lambda: self.edit_channel())
        self.channel_buttons["test"].clicked.connect(lambda: self.test_channel())
        lay.addWidget(ms.footer([list(self.channel_buttons.values())]))
        title = QLabel("شناسهٔ گفت‌وگوی طرف حساب‌ها")
        title.setObjectName("sectionTitle")
        lay.addWidget(title)
        self.t_chats = table(["طرف حساب", "پیام‌رسان", "شناسهٔ گفت‌وگو"])
        self.t_chats.cellDoubleClicked.connect(lambda _r, _c: self.edit_chat())
        lay.addWidget(self.t_chats, stretch=1)
        self.chat_buttons = {k: _icon(g, t, kind) for k, g, t, kind in (
            ("new", "➕", "افزودن شناسه", "primary"), ("edit", "✏️", "ویرایش شناسه", ""), ("delete", "🗑️", "حذف شناسه", "danger"))}
        self.chat_buttons["new"].clicked.connect(lambda: self.edit_chat(new=True))
        self.chat_buttons["edit"].clicked.connect(lambda: self.edit_chat())
        self.chat_buttons["delete"].clicked.connect(lambda: self.delete_chat())
        lay.addWidget(ms.footer([list(self.chat_buttons.values())]))
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        lay.addWidget(self.status_label)

    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        allowed = can(_FORM, "EDIT")
        self.feature.blockSignals(True)
        self.feature.setChecked(msg_service.is_on(cid))
        self.feature.blockSignals(False)
        self.feature.setEnabled(allowed)
        for b in list(self.channel_buttons.values()) + list(self.chat_buttons.values()):
            b.setEnabled(allowed)
        self.load()

    def load(self) -> None:
        cid = company_id()
        self.settings = msg_service.list_settings(cid)
        fill(self.t_channels, [[s.label, "ربات رسمی" if s.kind == "BOT" else "درگاه عمومی",
                                ("روشن" if s.is_active else "خاموش") + ("" if s.has_secret else " (تنظیم‌نشده)"),
                                s.last_error or "—"] for s in self.settings], [s.channel for s in self.settings])
        self.t_channels.resizeColumnsToContents()
        self.chats = msg_service.chat_ids(cid)
        names = {p["detail_account_id"]: f"{p['code']} — {p['name']}" for p in self._parties()} if self.chats else {}
        fill(self.t_chats, [[names.get(r.party_detail_account_id, str(r.party_detail_account_id)),
                             comm_service.CHANNELS.get(r.channel, r.channel), r.chat_id] for r in self.chats],
             [(r.party_detail_account_id, r.channel) for r in self.chats])
        self.t_chats.resizeColumnsToContents()

    @staticmethod
    def _parties() -> list[dict]:
        cid = company_id()
        seen, out = set(), []
        for p in dims.list_customers(cid) + dims.list_suppliers(cid):
            if p["detail_account_id"] not in seen:
                seen.add(p["detail_account_id"])
                out.append(p)
        return out

    def _toggle_feature(self, checked: bool) -> None:
        _x, ok = _run(self.ctx, "پیام‌رسان‌ها", engine.set_feature_enabled, company_id(), msg_service.FEATURE, checked)
        if ok:
            theme.set_status_label(self.status_label, "ارسال خودکار پیام " + ("روشن" if checked else "خاموش") + " شد.", ok=True)

    def edit_channel(self, values: dict | None = None, channel: str | None = None) -> bool:
        channel = channel or _selected(self.t_channels)
        s = next((x for x in self.settings if x.channel == channel), None)
        if s is None:
            _run(self.ctx, "پیام‌رسان", _raise, "یک پیام‌رسان را انتخاب کنید.")
            return False
        if values is None:
            secret = QLineEdit()
            secret.setEchoMode(QLineEdit.Password)
            secret.setPlaceholderText("خالی = همان قبلی" if s.has_secret else "")
            base = QLineEdit(s.base_url)
            base.setPlaceholderText("خالی = نشانی رسمی")
            fields = [("secret", "توکن ربات" if s.kind == "BOT" else "نشانی درگاه با {phone} و {text}", secret)]
            if s.kind == "BOT":
                fields.append(("base_url", "نشانی پایهٔ سرویس (اختیاری)", base))
            else:
                fields.append(("http_method", "روش ارسال", _with(combo([("GET", "GET"), ("POST", "POST")]), s.http_method)))
            fields.append(("is_active", "روشن", _checked(s.is_active)))
            values = _ask(self.ctx, s.label, fields)
            if values is None:
                return False
        _x, ok = _run(self.ctx, s.label, msg_service.save_setting, company_id(), user_id(), channel,
                      secret=values.get("secret"), is_active=bool(values.get("is_active")), base_url=values.get("base_url"),
                      http_method=values.get("http_method") or "GET")
        if ok:
            self.load()
        return ok

    def test_channel(self, channel: str | None = None) -> tuple[bool, str] | None:
        channel = channel or _selected(self.t_channels)
        if channel is None:
            return None
        ok, message = msg_service.test_setting(company_id(), channel)
        theme.set_status_label(self.status_label, message, ok=ok)
        self.load()
        return ok, message

    def edit_chat(self, new: bool = False, values: dict | None = None) -> bool:
        cid = company_id()
        key = None if new else _selected(self.t_chats)
        if not new and key is None:
            return False
        if values is None:
            parties = [(f"{p['code']} — {p['name']}", p["detail_account_id"]) for p in self._parties()]
            row = next((r for r in self.chats if (r.party_detail_account_id, r.channel) == key), None)
            party_box = _with(combo(parties), row.party_detail_account_id if row else None)
            channel_box = _with(combo([(comm_service.CHANNELS[c], c) for c in msg_service.BOT_CHANNELS]),
                                row.channel if row else "BALE")
            party_box.setEnabled(row is None)
            channel_box.setEnabled(row is None)
            values = _ask(self.ctx, "شناسهٔ گفت‌وگو", [("party", "طرف حساب", party_box), ("channel", "پیام‌رسان", channel_box),
                                                       ("chat_id", "شناسهٔ گفت‌وگو", QLineEdit(row.chat_id if row else ""))])
            if values is None:
                return False
        _x, ok = _run(self.ctx, "شناسهٔ گفت‌وگو", msg_service.set_chat_id, cid, values["party"], values["channel"],
                      values.get("chat_id"))
        if ok:
            self.load()
        return ok

    def delete_chat(self) -> bool:
        key = _selected(self.t_chats)
        if key is None or not _confirm(self.ctx, "شناسهٔ گفت‌وگو", "این شناسه حذف شود؟"):
            return False
        _x, ok = _run(self.ctx, "شناسهٔ گفت‌وگو", msg_service.set_chat_id, company_id(), key[0], key[1], None)
        if ok:
            self.load()
        return ok


class ProcessMessagesPanel(_CrmPanel):
    """قاعده‌های «پس از رویداد X، الگوی Y برای Z» (هر قاعده یک فرایند یک‌اقدامی گردش کار)."""

    def __init__(self, host=None) -> None:
        super().__init__(host)
        self.rules: list = []
        lay = QVBoxLayout(self)
        lay.addWidget(_hint("پس از هر رویداد (مثلاً تصویب فاکتور فروش، ثبت سند دریافت یا ارسال سفارش)، الگوی انتخابی برای طرف حساب "
                            "همان سند، یک گیرندهٔ ثابت یا یک کاربر فرستاده می‌شود. در متن: " + msg_service.RULE_FIELDS_HINT
                            + ". نتیجهٔ هر ارسال در دفتر پیام‌ها ثبت می‌شود."))
        self.off_note = _hint("ارسال خودکار پیام خاموش است؛ از زبانهٔ «پیام‌رسان‌ها» روشنش کنید. قاعده‌ها نگه داشته می‌شوند.")
        lay.addWidget(self.off_note)
        self.t_rules = table(["نام", "پس از رویداد", "کانال", "گیرنده", "وضعیت"])
        self.t_rules.cellDoubleClicked.connect(lambda _r, _c: self.edit_rule())
        lay.addWidget(self.t_rules, stretch=1)
        self.buttons = {k: _icon(g, t, kind) for k, g, t, kind in (
            ("new", "➕", "قاعدهٔ جدید", "primary"), ("edit", "✏️", "ویرایش قاعده", ""), ("toggle", "⏯️", "روشن/خاموش قاعده", ""),
            ("delete", "🗑️", "حذف قاعده", "danger"))}
        self.buttons["new"].clicked.connect(lambda: self.edit_rule(new=True))
        self.buttons["edit"].clicked.connect(lambda: self.edit_rule())
        self.buttons["toggle"].clicked.connect(lambda: self.toggle_rule())
        self.buttons["delete"].clicked.connect(lambda: self.delete_rule())
        lay.addWidget(ms.footer([list(self.buttons.values())]))

    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        self.off_note.setVisible(not msg_service.is_on(cid))
        for key, action in (("new", "CREATE"), ("edit", "EDIT"), ("toggle", "EDIT"), ("delete", "DELETE")):
            self.buttons[key].setEnabled(can(_FORM, action))
        self.load()

    def load(self) -> None:
        self.rules = msg_service.list_rules(company_id())
        fill(self.t_rules, [[r.name, r.event_label, comm_service.CHANNELS.get(r.channel, r.channel),
                             msg_service.RECIPIENTS.get(r.recipient, r.recipient) + (f": {r.target}" if r.target else ""),
                             "فعال" if r.is_active else r.status_label] for r in self.rules],
             [r.definition_id for r in self.rules])
        self.t_rules.resizeColumnsToContents()

    def edit_rule(self, new: bool = False, values: dict | None = None) -> int | None:
        cid = company_id()
        rid = None if new else _selected(self.t_rules)
        if not new and rid is None:
            return None
        r = next((x for x in self.rules if x.definition_id == rid), None)
        if values is None:
            events = [(e.label, e.event_type) for e in msg_service.event_choices()]
            channels = [(v, k) for k, v in comm_service.CHANNELS.items() if k != "INTERNAL"]
            templates = [(f"{t.name} ({comm_service.CHANNELS.get(t.channel, t.channel)})", t.template_id)
                         for t in comm_service.list_templates(cid, active_only=True)]
            users = [(name, uid) for uid, name in cc.list_company_users(cid)]
            values = _ask(self.ctx, "پیام پس از فرایند", [
                ("name", "نام قاعده", QLineEdit(r.name if r else "")),
                ("event_type", "پس از رویداد", _with(combo(events), r.event_type if r else None)),
                ("channel", "کانال", _with(combo(channels), r.channel if r else "SMS")),
                ("template_id", "الگو", _with(combo(templates, "— بدون الگو (متن زیر) —"), r.template_id if r else None)),
                ("body", "متن (اگر الگو انتخاب نشده)", _text(r.body if r else "")),
                ("recipient", "گیرنده", _with(combo([(v, k) for k, v in msg_service.RECIPIENTS.items()]),
                                              r.recipient if r else "COUNTERPARTY")),
                ("target", "شماره یا شناسهٔ گیرندهٔ ثابت", QLineEdit(r.target if r else "")),
                ("notify_user_id", "کاربر گیرنده (اعلان داخلی)", _with(combo(users, "—"), r.notify_user_id if r else None))],
                "در متن: " + msg_service.RULE_FIELDS_HINT)
            if values is None:
                return None
        new_id, ok = _run(self.ctx, "پیام پس از فرایند", msg_service.save_rule, cid, user_id(), definition_id=rid,
                          name=values.get("name") or "", event_type=values.get("event_type"), channel=values.get("channel"),
                          template_id=values.get("template_id"), body=values.get("body") or "",
                          recipient=values.get("recipient") or "COUNTERPARTY", target=values.get("target") or "",
                          notify_user_id=values.get("notify_user_id"))
        if ok:
            self.load()
        return new_id if ok else None

    def toggle_rule(self) -> bool:
        rid = _selected(self.t_rules)
        r = next((x for x in self.rules if x.definition_id == rid), None)
        if r is None:
            return False
        _x, ok = _run(self.ctx, "پیام پس از فرایند", msg_service.set_rule_active, company_id(), user_id(), rid, not r.is_active)
        if ok:
            self.load()
        return ok

    def delete_rule(self) -> bool:
        rid = _selected(self.t_rules)
        if rid is None or not _confirm(self.ctx, "پیام پس از فرایند", "این قاعده حذف شود؟"):
            return False
        _x, ok = _run(self.ctx, "پیام پس از فرایند", msg_service.delete_rule, company_id(), user_id(), rid)
        if ok:
            self.load()
        return ok


def _raise(message: str) -> None:
    raise ValueError(message)
