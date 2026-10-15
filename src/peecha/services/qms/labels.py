"""نام‌های نمایشی کالا، طرف‌حساب، کاربر و انبار با حافظهٔ کوتاه‌مدت در یک نشست."""

from __future__ import annotations

from peecha.db.models.accounting import DetailAccount
from peecha.db.models.inventory import Item, Warehouse


class Names:
    def __init__(self, session) -> None:
        self.session = session
        self._items: dict[int, str] = {}
        self._parties: dict[int, str] = {}
        self._users: dict[int, str] = {}
        self._warehouses: dict[int, str] = {}

    def item(self, item_id: int | None) -> str:
        if not item_id:
            return ""
        if item_id not in self._items:
            item = self.session.get(Item, item_id)
            acc = self.session.get(DetailAccount, item.item_detail_account_id) if item else None
            self._items[item_id] = f"{acc.code} — {acc.name or ''}" if acc else ""
        return self._items[item_id]

    def party(self, detail_account_id: int | None) -> str:
        if not detail_account_id:
            return ""
        if detail_account_id not in self._parties:
            acc = self.session.get(DetailAccount, detail_account_id)
            self._parties[detail_account_id] = f"{acc.code} — {acc.name or ''}" if acc else ""
        return self._parties[detail_account_id]

    def user(self, user_id: int | None) -> str:
        from peecha.db.models.security import User

        if not user_id:
            return ""
        if user_id not in self._users:
            u = self.session.get(User, user_id)
            self._users[user_id] = (u.full_name or u.username) if u else ""
        return self._users[user_id]

    def warehouse(self, warehouse_id: int | None) -> str:
        if not warehouse_id:
            return ""
        if warehouse_id not in self._warehouses:
            w = self.session.get(Warehouse, warehouse_id)
            self._warehouses[warehouse_id] = w.name if w else ""
        return self._warehouses[warehouse_id]
