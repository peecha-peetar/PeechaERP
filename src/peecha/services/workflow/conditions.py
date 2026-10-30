"""ارزیاب شرط داده‌محور (بدون eval/SQL): هم‌شکل قاعدهٔ بخش مشتری CRM، با ترکیب «و/یا/نه»،
مقایسهٔ فیلد با فیلد («اعتبار آزاد < مبلغ سفارش») و تاریخ نسبی («سررسید < امروز»).

قاعده:
    {"all": [...]} | {"any": [...]} | {"not": قاعده}
    {"field": "amount", "op": ">", "value": 500000000}
    {"field": "credit_available", "op": "<", "value_field": "amount"}
    {"field": "due_date", "op": "<", "value": {"days_from_today": 0}}
"""

from __future__ import annotations

import datetime
import decimal
from typing import Any

from peecha import numerals
from peecha.services.workflow.common import display

OPERATORS = {
    "=": "برابر با", "!=": "مخالف", ">": "بیشتر از", ">=": "بیشتر یا برابر با", "<": "کمتر از", "<=": "کمتر یا برابر با",
    "between": "بین", "in": "یکی از", "not_in": "هیچ‌کدام از", "contains": "شامل", "is_empty": "خالی باشد",
    "not_empty": "خالی نباشد", "is_true": "باشد", "is_false": "نباشد",
}
_UNARY = {"is_empty", "not_empty", "is_true", "is_false"}
_KIND_OPS = {
    "number": ("=", "!=", ">", ">=", "<", "<=", "between", "is_empty", "not_empty"),
    "money": ("=", "!=", ">", ">=", "<", "<=", "between", "is_empty", "not_empty"),
    "date": ("=", "!=", ">", ">=", "<", "<=", "between", "is_empty", "not_empty"),
    "text": ("=", "!=", "contains", "in", "not_in", "is_empty", "not_empty"),
    "choice": ("=", "!=", "in", "not_in", "is_empty", "not_empty"),
    "user": ("=", "!=", "in", "not_in", "is_empty", "not_empty"),
    "bool": ("is_true", "is_false"),
}


def ops_for(kind: str) -> list[tuple[str, str]]:
    return [(op, OPERATORS[op]) for op in _KIND_OPS.get(kind, _KIND_OPS["text"])]


def get_path(context: dict, path: str):
    value: Any = context
    for part in str(path).split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _number(value):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return decimal.Decimal(int(value))
    if isinstance(value, (int, float, decimal.Decimal)):
        return decimal.Decimal(str(value))
    text = numerals.to_ascii_digits(str(value)).replace(",", "").replace("٬", "").strip()
    try:
        return decimal.Decimal(text)
    except decimal.InvalidOperation:
        return None


def _date(value, today: datetime.date):
    if value is None or value == "":
        return None
    if isinstance(value, dict):
        if "days_from_today" in value:
            return today + datetime.timedelta(days=int(value["days_from_today"]))
        if "days_ago" in value:
            return today - datetime.timedelta(days=int(value["days_ago"]))
        if value.get("today"):
            return today
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    try:
        return datetime.date.fromisoformat(numerals.to_ascii_digits(str(value))[:10])
    except ValueError:
        return None


def _coerce(left, right, today):
    """هر دو طرف به یک نوع قابل‌مقایسه: تاریخ، عدد یا متن."""
    if isinstance(left, (datetime.date, datetime.datetime)) or isinstance(right, dict) and (
            {"days_from_today", "days_ago", "today"} & set(right)):
        return _date(left, today), _date(right, today)
    ln, rn = _number(left), _number(right)
    if ln is not None and rn is not None:
        return ln, rn
    return (None if left is None else str(left)), (None if right is None else str(right))


def _compare(op: str, left, right, today: datetime.date) -> bool:
    if op == "is_empty":
        return left is None or left == "" or left == []
    if op == "not_empty":
        return not (left is None or left == "" or left == [])
    if op == "is_true":
        return bool(left)
    if op == "is_false":
        return not bool(left)
    if op in ("in", "not_in"):
        items = right if isinstance(right, (list, tuple)) else [x.strip() for x in str(right or "").split(",") if x.strip()]
        found = str(left) in {str(i) for i in items}
        return found if op == "in" else not found
    if op == "contains":
        return left is not None and str(right or "") in str(left)
    if op == "between":
        lo, hi = (right or [None, None])[:2] if isinstance(right, (list, tuple)) else (None, None)
        a, b = _coerce(left, lo, today)
        _, c = _coerce(left, hi, today)
        return a is not None and b is not None and c is not None and b <= a <= c
    a, b = _coerce(left, right, today)
    if op == "=":
        return a == b
    if op == "!=":
        return a != b
    if a is None or b is None:
        return False
    try:
        return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]
    except TypeError:
        return False


def evaluate(rule: dict | None, context: dict, today: datetime.date | None = None) -> bool:
    """قاعدهٔ خالی یعنی «همیشه درست»."""
    if not rule:
        return True
    today = today or datetime.date.today()
    if "all" in rule:
        return all(evaluate(r, context, today) for r in rule["all"] or [])
    if "any" in rule:
        items = rule["any"] or []
        return any(evaluate(r, context, today) for r in items) if items else True
    if "not" in rule:
        return not evaluate(rule["not"], context, today)
    left = get_path(context, rule.get("field", ""))
    right = get_path(context, rule["value_field"]) if rule.get("value_field") else rule.get("value")
    return _compare(rule.get("op", "="), left, right, today)


def explain(rule: dict | None, context: dict, labels: dict[str, str] | None = None,
            today: datetime.date | None = None) -> list[tuple[str, bool]]:
    """هر شرط ساده با نتیجه‌اش -- برای لاگ اجرا و شبیه‌سازی."""
    out: list[tuple[str, bool]] = []
    if not rule:
        return out
    today = today or datetime.date.today()
    if "all" in rule or "any" in rule:
        for r in rule.get("all", rule.get("any")) or []:
            out += explain(r, context, labels, today)
        return out
    if "not" in rule:
        return [(f"نه ({describe(rule['not'], labels)})", evaluate(rule, context, today))]
    left = get_path(context, rule.get("field", ""))
    return [(f"{describe(rule, labels)} (مقدار فعلی: {display(left)})", evaluate(rule, context, today))]


def _value_text(rule: dict, labels: dict[str, str]) -> str:
    if rule.get("value_field"):
        return f"«{labels.get(rule['value_field'], rule['value_field'])}»"
    value = rule.get("value")
    if isinstance(value, dict):
        if "days_from_today" in value:
            n = int(value["days_from_today"])
            return "امروز" if n == 0 else numerals.to_persian_digits(f"{abs(n)} روز {'بعد' if n > 0 else 'قبل'}")
        if "days_ago" in value:
            return numerals.to_persian_digits(f"{int(value['days_ago'])} روز قبل")
    if isinstance(value, (list, tuple)):
        return " و ".join(display(_number(v) if _number(v) is not None else v) for v in value)
    number = _number(value)
    return display(number if number is not None else value)


def describe(rule: dict | None, labels: dict[str, str] | None = None) -> str:
    """متن فارسی خوانا: «مبلغ بیشتر از ۵۰۰٬۰۰۰٬۰۰۰ و اعتبار آزاد کمتر از «مبلغ»»."""
    labels = labels or {}
    if not rule:
        return "همیشه"
    if "all" in rule or "any" in rule:
        parts = [describe(r, labels) for r in rule.get("all", rule.get("any")) or []]
        joiner = " و " if "all" in rule else " یا "
        text = joiner.join(p for p in parts if p)
        return f"({text})" if len(parts) > 1 else text
    if "not" in rule:
        return f"نه {describe(rule['not'], labels)}"
    name = labels.get(rule.get("field", ""), rule.get("field", ""))
    op = rule.get("op", "=")
    if op in _UNARY:
        return f"{name} {OPERATORS[op]}"
    return f"{name} {OPERATORS.get(op, op)} {_value_text(rule, labels)}"


def validate(rule: dict | None, fields: dict | None = None) -> list[str]:
    """خطاهای قاعده (فارسی)؛ fields = {کلید: FieldSpec} برای بررسی فیلد و عملگر."""
    errors: list[str] = []
    if not rule:
        return errors
    if not isinstance(rule, dict):
        return ["قالب شرط نامعتبر است."]
    if "all" in rule or "any" in rule:
        items = rule.get("all", rule.get("any"))
        if not isinstance(items, list):
            return ["قالب شرط نامعتبر است."]
        for r in items:
            errors += validate(r, fields)
        return errors
    if "not" in rule:
        return validate(rule["not"], fields)
    key, op = rule.get("field"), rule.get("op", "=")
    if not key:
        return ["فیلد شرط انتخاب نشده است."]
    if op not in OPERATORS:
        errors.append(f"عملگر «{op}» شناخته نشده است.")
    if fields is not None:
        root = str(key).split(".")[0]
        spec = fields.get(key) or fields.get(root)
        if spec is None:
            errors.append(f"فیلد «{key}» در این نوع سند وجود ندارد.")
        elif op in OPERATORS and op not in _KIND_OPS.get(spec.kind, _KIND_OPS["text"]):
            errors.append(f"عملگر «{OPERATORS[op]}» برای «{spec.label}» مناسب نیست.")
        if rule.get("value_field") and rule["value_field"] not in fields:
            errors.append(f"فیلد مقایسه «{rule['value_field']}» در این نوع سند وجود ندارد.")
    if op not in _UNARY and "value" not in rule and not rule.get("value_field"):
        errors.append(f"مقدار شرط «{key}» وارد نشده است.")
    if op == "between" and not (isinstance(rule.get("value"), (list, tuple)) and len(rule["value"]) == 2):
        errors.append("برای «بین» دو مقدار لازم است.")
    return errors


def fields_used(rule: dict | None) -> set[str]:
    if not rule:
        return set()
    if "all" in rule or "any" in rule:
        out: set[str] = set()
        for r in rule.get("all", rule.get("any")) or []:
            out |= fields_used(r)
        return out
    if "not" in rule:
        return fields_used(rule["not"])
    return {k for k in (rule.get("field"), rule.get("value_field")) if k}
