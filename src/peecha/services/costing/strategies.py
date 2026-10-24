"""راهبردهای انتخاب لایه (Strategy) — بدون وابستگی به دیتابیس تا مستقیم تست شوند.

هر راهبرد فقط «ترتیب مصرف لایه‌ها» را تعیین می‌کند؛ مصرف/قفل/ثبت در costing.engine است.
"""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass
from typing import Protocol, Sequence

_ZERO = decimal.Decimal(0)

METHOD_LABELS = {
    "FIFO": "اولین صادره از اولین وارده (FIFO)",
    "LIFO": "اولین صادره از آخرین وارده (LIFO)",
    "HIFO": "اول گران‌ترین (HIFO)",
    "LOFO": "اول ارزان‌ترین (LOFO)",
    "WEIGHTED_AVERAGE": "میانگین متحرک (موزون)",
    "SPECIFIC": "شناسایی ویژه (سریال/بچ)",
    "NIFO": "بهای جایگزینی (NIFO)",
    "STANDARD": "بهای استاندارد",
}


class LayerLike(Protocol):
    cost_layer_id: int
    unit_cost: decimal.Decimal
    remaining_quantity: decimal.Decimal
    receipt_date: datetime.date | None


@dataclass(frozen=True)
class Pick:
    layer: object
    quantity: decimal.Decimal


class CostingStrategy:
    code = ""

    def order(self, layers: Sequence[LayerLike]) -> list:
        raise NotImplementedError

    def pick(self, layers: Sequence[LayerLike], quantity: decimal.Decimal) -> tuple[list[Pick], decimal.Decimal]:
        """(لایه‌های انتخاب‌شده، مقدار تامین‌نشده)."""
        picks, remaining = [], quantity
        for layer in self.order([lyr for lyr in layers if lyr.remaining_quantity > 0]):
            if remaining <= 0:
                break
            take = min(layer.remaining_quantity, remaining)
            picks.append(Pick(layer, take))
            remaining -= take
        return picks, remaining


def _date(layer) -> datetime.date:
    return layer.receipt_date or datetime.date.min


class Fifo(CostingStrategy):
    code = "FIFO"

    def order(self, layers):
        return sorted(layers, key=lambda lyr: (_date(lyr), lyr.cost_layer_id))


class Lifo(CostingStrategy):
    code = "LIFO"

    def order(self, layers):
        return sorted(layers, key=lambda lyr: (_date(lyr), lyr.cost_layer_id), reverse=True)


class Hifo(CostingStrategy):
    code = "HIFO"

    def order(self, layers):
        return sorted(layers, key=lambda lyr: (-lyr.unit_cost, _date(lyr), lyr.cost_layer_id))


class Lofo(CostingStrategy):
    code = "LOFO"

    def order(self, layers):
        return sorted(layers, key=lambda lyr: (lyr.unit_cost, _date(lyr), lyr.cost_layer_id))


class Specific(Fifo):
    """شناسایی ویژه: لایهٔ همان سریال/بچ اول (در engine فیلتر می‌شود)، باقی مثل FIFO."""

    code = "SPECIFIC"


_LAYER_STRATEGIES: dict[str, CostingStrategy] = {s.code: s for s in (Fifo(), Lifo(), Hifo(), Lofo(), Specific())}
LAYER_METHODS = frozenset(_LAYER_STRATEGIES)


def is_layer_method(code: str | None) -> bool:
    return code in LAYER_METHODS


def get_strategy(code: str) -> CostingStrategy:
    try:
        return _LAYER_STRATEGIES[code]
    except KeyError as exc:
        raise ValueError(f"روش لایه‌ای «{code}» شناخته‌شده نیست.") from exc


def moving_average(on_hand: decimal.Decimal, average: decimal.Decimal, in_quantity: decimal.Decimal,
                   in_unit_cost: decimal.Decimal) -> decimal.Decimal:
    """میانگین متحرک پس از ورود — همان فرمول apply_in (موجودی منفی: بهای ورودی تازه)."""
    if on_hand < 0:
        return in_unit_cost
    denom = on_hand + in_quantity
    return ((on_hand * average) + (in_quantity * in_unit_cost)) / denom if denom != 0 else in_unit_cost
