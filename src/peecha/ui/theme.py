"""پالت رسمی پیچا — دقیقاً طبق جدول‌های بخش ۳/۴ در docs/ui-ux-guidelines.md.

منبع واحد این مقادیر همین فایل است؛ هم از پایتون و هم مستقیم از KV
(`#:import theme peecha.ui.theme`) استفاده می‌شود تا رنگ‌ها در دو جا به‌صورت
غیرهم‌گام تکرار نشوند.
"""

from __future__ import annotations


def hex_to_rgba(hex_code: str, alpha: float = 1.0) -> tuple[float, float, float, float]:
    hex_code = hex_code.lstrip("#")
    r = int(hex_code[0:2], 16) / 255
    g = int(hex_code[2:4], 16) / 255
    b = int(hex_code[4:6], 16) / 255
    return (r, g, b, alpha)


# رنگ‌های برند/اکشن
PRIMARY = hex_to_rgba("020025")
PRIMARY_HOVER = hex_to_rgba("0B0B55")
PRIMARY_LIGHT = hex_to_rgba("EEF2FF")
ACCENT = hex_to_rgba("2563EB")
SUCCESS = hex_to_rgba("10B981")
WARNING = hex_to_rgba("F59E0B")
DANGER = hex_to_rgba("EF4444")
INFO = hex_to_rgba("0EA5E9")

# اکسنت‌های اضافیِ نمودار (دسته‌ی سوم/چهارم به بعد)
CHART_PURPLE = hex_to_rgba("9333EA")
CHART_ORANGE = hex_to_rgba("F97316")

# سطح/پس‌زمینه (تم روشن)
BACKGROUND = hex_to_rgba("F7F8FC")
SURFACE = hex_to_rgba("FFFFFF")
HOVER = hex_to_rgba("F4F6FA")
SELECTED = hex_to_rgba("EEF2FF")
BORDER = hex_to_rgba("E5E7EB")
DIVIDER = hex_to_rgba("ECECEC")

# متن
TEXT_PRIMARY = hex_to_rgba("111827")
TEXT_SECONDARY = hex_to_rgba("6B7280")
TEXT_DISABLED = hex_to_rgba("9CA3AF")

# RGBA در بازه‌ی ۰..۱ (فرمت مورد انتظار KivyMD) — نگاشت قدیمی برای سازگاری با کدهای موجود
SEMANTIC_COLORS: dict[str, dict[str, tuple[float, float, float, float]]] = {
    "light": {
        "primary": ACCENT,
        "success": SUCCESS,
        "warning": WARNING,
        "danger": DANGER,
        "info": INFO,
        "background": BACKGROUND,
        "surface": SURFACE,
        "text": TEXT_PRIMARY,
    },
    "dark": {
        "primary": hex_to_rgba("5B8DEF"),
        "success": hex_to_rgba("34D399"),
        "warning": hex_to_rgba("FBBF24"),
        "danger": hex_to_rgba("F87171"),
        "info": hex_to_rgba("38BDF8"),
        "background": hex_to_rgba("0F1115"),
        "surface": hex_to_rgba("1A1D23"),
        "text": hex_to_rgba("E5E7EB"),
    },
}

# نگاشت وضعیت سند/کارتابل به نقش رنگ semantic — طبق docs/ui-ux-guidelines.md بخش ۳
STATUS_COLOR_ROLE: dict[str, str] = {
    "TEMPORARY": "warning",
    "PERMANENT": "success",
    "REVERSED": "danger",
    "CANCELLED": "danger",
    "PENDING": "warning",
    "APPROVED": "success",
    "REJECTED": "danger",
}


def status_color(status_code: str, theme_style: str = "light") -> tuple[float, float, float, float]:
    role = STATUS_COLOR_ROLE.get(status_code, "info")
    return SEMANTIC_COLORS[theme_style][role]
