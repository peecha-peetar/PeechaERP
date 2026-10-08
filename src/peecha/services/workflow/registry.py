"""قرارداد اتصال ماژول‌ها به موتور (Entity Adapter) + افزونه‌های اقدام/مسیریاب/بررسی دوره‌ای.

موتور هرگز مستقیم به جدول‌های کسب‌وکار دست نمی‌زند: هر ماژول با یک Adapter می‌گوید سندش چه فیلدهایی برای
شرط دارد، اطلاعات تصمیم‌گیری را چطور می‌خواند و کدام تابع سرویس موجود برای هر اقدام صدا زده شود.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from peecha.services.workflow.common import WorkflowError

RISK_LABELS = {"LOW": "کم‌خطر", "HIGH": "حساس (نیازمند تایید انسانی قبلی)"}


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    kind: str = "text"  # number | money | text | date | bool | choice | user
    choices: dict[str, str] | None = None
    sensitive_form: str | None = None  # فقط دارندگان VIEW این فرم مقدار را در کارت تایید می‌بینند


@dataclass(frozen=True)
class ParamSpec:
    key: str
    label: str
    kind: str = "text"  # text | int | money | user | role | choice | template
    default: Any = None
    choices: dict[str, str] | None = None


@dataclass
class ActionContext:
    company_id: int
    user_id: int | None
    entity_type: str | None
    entity_id: int | None
    instance_id: int | None
    context: dict
    params: dict
    idempotency_key: str
    dry_run: bool = False


@dataclass(frozen=True)
class ActionSpec:
    code: str
    label: str
    func: Callable[[ActionContext], dict | None]
    risk: str = "LOW"  # LOW | HIGH
    params: tuple[ParamSpec, ...] = ()
    is_done: Callable[[int, int], bool] | None = None  # حالت سند: آیا این اقدام قبلاً انجام شده؟
    description: str = ""


@dataclass
class EntityAdapter:
    entity_type: str
    label: str
    module_code: str
    load: Callable[[int, int], dict]  # (company_id, entity_id) -> context
    fields: tuple[FieldSpec, ...] = ()
    form_code: str | None = None
    events: dict[str, str] = field(default_factory=dict)  # کد رویداد -> برچسب فارسی
    actions: dict[str, ActionSpec] = field(default_factory=dict)
    title: Callable[[dict], str] | None = None
    owner: Callable[[int, int], int | None] | None = None
    approval_context: Callable[[int, int], list[tuple[str, str]]] | None = None
    open_nav: str | None = None  # کد منو برای بازکردن سند از کارتابل
    submitter_field: str | None = None  # کلید context که صادرکننده را نشان می‌دهد (برای منع خودتاییدی)

    def field_map(self) -> dict[str, FieldSpec]:
        return {f.key: f for f in self.fields}

    def labels(self) -> dict[str, str]:
        return {f.key: f.label for f in self.fields}

    def describe(self, context: dict) -> str:
        if self.title is not None:
            try:
                return self.title(context)
            except Exception:  # noqa: BLE001 -- عنوان نمایشی نباید اجرای فرایند را متوقف کند
                pass
        return self.label


@dataclass(frozen=True)
class ScanSpec:
    """بررسی دوره‌ای (مثلاً فاکتور معوق، موجودی زیر حداقل): برمی‌گرداند شناسهٔ موجودیت‌های منطبق."""
    code: str
    label: str
    entity_type: str
    func: Callable[[int, dict], list[int]]  # (company_id, params) -> entity ids
    params: tuple[ParamSpec, ...] = ()
    period: str = "DAY"  # هر موجودیت در هر دوره یک‌بار


@dataclass(frozen=True)
class ResolverSpec:
    code: str
    label: str
    func: Callable[..., list[int]]
    params: tuple[ParamSpec, ...] = ()


_ADAPTERS: dict[str, EntityAdapter] = {}
_GLOBAL_ACTIONS: dict[str, ActionSpec] = {}
_SCANS: dict[str, ScanSpec] = {}
_RESOLVERS: dict[str, ResolverSpec] = {}
_LOADED = False


def register_adapter(adapter: EntityAdapter) -> EntityAdapter:
    _ADAPTERS[adapter.entity_type] = adapter
    return adapter


def register_action(spec: ActionSpec) -> ActionSpec:
    """اقدام سفارشی توسعه‌دهنده (Developer Extension) -- بدون Hard-code در هستهٔ موتور."""
    _GLOBAL_ACTIONS[spec.code] = spec
    return spec


def register_scan(spec: ScanSpec) -> ScanSpec:
    _SCANS[spec.code] = spec
    return spec


def register_resolver(spec: ResolverSpec) -> ResolverSpec:
    _RESOLVERS[spec.code] = spec
    return spec


def ensure_loaded() -> None:
    """Adapterهای ماژول‌ها یک‌بار و تنبل بارگذاری می‌شوند (بدون وابستگی دوری در import)."""
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    from peecha.services.workflow import actions  # noqa: F401 -- اقدام‌های داخلی
    try:
        from peecha.services.workflow import adapters  # noqa: F401 -- اتصال ماژول‌ها (R295)
    except ImportError:
        pass


def adapters() -> list[EntityAdapter]:
    ensure_loaded()
    return sorted(_ADAPTERS.values(), key=lambda a: (a.module_code, a.label))


def get_adapter(entity_type: str | None) -> EntityAdapter | None:
    ensure_loaded()
    if not entity_type:
        return None
    return _ADAPTERS.get(entity_type)


def require_adapter(entity_type: str) -> EntityAdapter:
    adapter = get_adapter(entity_type)
    if adapter is None:
        raise WorkflowError(f"نوع سند «{entity_type}» برای گردش کار تعریف نشده است.")
    return adapter


def global_actions() -> dict[str, ActionSpec]:
    ensure_loaded()
    return dict(_GLOBAL_ACTIONS)


def scans() -> dict[str, ScanSpec]:
    ensure_loaded()
    return dict(_SCANS)


def resolvers() -> dict[str, ResolverSpec]:
    ensure_loaded()
    return dict(_RESOLVERS)


def find_action(entity_type: str | None, code: str) -> ActionSpec | None:
    """«entity.<code>» اقدام سند؛ بقیه اقدام عمومی/سفارشی."""
    ensure_loaded()
    if code.startswith("entity."):
        adapter = get_adapter(entity_type)
        return adapter.actions.get(code.split(".", 1)[1]) if adapter else None
    return _GLOBAL_ACTIONS.get(code)


def action_choices(entity_type: str | None) -> list[tuple[str, str, str]]:
    """(کد، برچسب، ریسک) برای سازندهٔ فرایند."""
    ensure_loaded()
    out = []
    adapter = get_adapter(entity_type)
    if adapter:
        out += [(f"entity.{k}", a.label, a.risk) for k, a in adapter.actions.items()]
    out += [(k, a.label, a.risk) for k, a in _GLOBAL_ACTIONS.items()]
    return out


def event_choices(entity_type: str | None) -> list[tuple[str, str]]:
    adapter = get_adapter(entity_type)
    out = list(adapter.events.items()) if adapter else []
    for code, scan in scans().items():
        if scan.entity_type == entity_type:
            out.append((f"SCAN:{code}", f"بررسی دوره‌ای: {scan.label}"))
    return out
