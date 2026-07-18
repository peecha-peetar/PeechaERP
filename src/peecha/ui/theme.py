"""رنگ‌های semantic پیچا — معادل جدول بخش ۳ در docs/ui-ux-guidelines.md.

این رنگ‌ها معنا حمل می‌کنند (وضعیت سند)، نه صرفاً تزیین؛ برای همین جدا از
پالت عمومی KivyMD در یک‌جا نگه‌داری می‌شوند تا همه‌ی صفحات یکسان استفاده کنند.
"""

from __future__ import annotations

# RGBA در بازه‌ی ۰..۱ (فرمت مورد انتظار KivyMD)
SEMANTIC_COLORS: dict[str, dict[str, tuple[float, float, float, float]]] = {
    "light": {
        "primary": (0.10, 0.35, 0.60, 1),
        "success": (0.16, 0.55, 0.28, 1),   # PERMANENT / APPROVED
        "warning": (0.80, 0.55, 0.10, 1),   # TEMPORARY / PENDING
        "danger":  (0.75, 0.15, 0.15, 1),   # REJECTED / REVERSED / CANCELLED / حذف
        "info":    (0.15, 0.45, 0.70, 1),   # تولید خودکار سیستم، نکته‌ها
        "background": (0.98, 0.98, 0.98, 1),
        "surface": (1, 1, 1, 1),
        "text": (0.10, 0.10, 0.10, 1),
    },
    "dark": {
        "primary": (0.35, 0.60, 0.85, 1),
        "success": (0.35, 0.70, 0.45, 1),
        "warning": (0.90, 0.70, 0.30, 1),
        "danger":  (0.90, 0.40, 0.40, 1),
        "info":    (0.45, 0.65, 0.85, 1),
        "background": (0.09, 0.09, 0.10, 1),
        "surface": (0.14, 0.14, 0.15, 1),
        "text": (0.92, 0.92, 0.92, 1),
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
