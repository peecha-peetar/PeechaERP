"""نقش‌های آمادهٔ افتتاحیه (R314) روی همان RBAC موجود؛ ورود، تأیید و ثبت قطعی در نقش‌های جدا (تفکیک وظایف).
اجرای دوباره نقش تکراری نمی‌سازد و فقط دسترسی کم‌شده را اضافه می‌کند."""

from __future__ import annotations

from peecha.services import roles as roles_service

_V = ("VIEW",)
_VE = ("VIEW", "EDIT")
_SCREENS = ("opn_sheet", "opn_center", "opn_data", "opn_reconcile")
TEMPLATES: dict[str, tuple[str, dict[str, tuple[str, ...]]]] = {
    "OPN_ENTRY": ("کارشناس ورود اطلاعات افتتاحیه", {**{s: _V for s in _SCREENS}, "opn_sheet": _VE, "opn_data": _VE,
                                                    "opn_enter": _VE}),
    "OPN_APPROVER": ("بررسی‌کننده و تأییدکنندهٔ افتتاحیه", {**{s: _V for s in _SCREENS}, "opn_approve": _VE}),
    "OPN_MANAGER": ("مدیر پروژهٔ افتتاحیه", {
        **{s: _VE for s in _SCREENS}, "opn_setup": _VE, "opn_post": _VE, "opn_config": _VE, "opn_settings": _VE}),
    "OPN_CONTROLLER": ("مدیر مالی (مجوز اختلاف و اصلاح)", {
        **{s: _VE for s in _SCREENS}, "opn_difference": _VE, "opn_correct": _VE, "opn_post": _VE}),
    "OPN_VIEWER": ("ناظر افتتاحیه", {s: _V for s in _SCREENS}),
}


def ensure_role_templates(company_id: int) -> dict[str, int]:
    """(کد نقش ← شناسه). گزارش‌های افتتاحیه برای همهٔ نقش‌ها قابل مشاهده است."""
    forms = {f.code: f.form_id for f in roles_service.list_forms()}
    report_forms = [code for code in forms if code.startswith("warehouse_report_opn_")]
    existing = {r.code: r.role_id for r in roles_service.list_roles(company_id)}
    out = {}
    for code, (_label, perms) in TEMPLATES.items():
        role_id = existing.get(code) or roles_service.create_role(company_id, code, None).role_id
        have = roles_service.get_role_permissions(role_id)
        wanted = dict(perms)
        for rf in report_forms:
            wanted.setdefault(rf, ("VIEW",))
        for form_code, actions in wanted.items():
            form_id = forms.get(form_code)
            for action in actions:
                if form_id is not None and (form_id, action) not in have:
                    roles_service.set_role_permission(role_id, form_id, action, True)
        out[code] = role_id
    return out
