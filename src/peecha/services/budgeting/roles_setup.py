"""نقش‌های آمادهٔ بودجه (R313) روی همان RBAC موجود. اجرای دوباره نقش تکراری نمی‌سازد و فقط دسترسی کم‌شده را اضافه می‌کند."""

from __future__ import annotations

from peecha.services import roles as roles_service

_V = ("VIEW",)
_VE = ("VIEW", "EDIT")
_VCE = ("VIEW", "CREATE", "EDIT")
_SCREENS = ("bud_center", "bud_budgets", "bud_exceptions")
TEMPLATES: dict[str, tuple[str, dict[str, tuple[str, ...]]]] = {
    "BUD_PREPARER": ("تهیه‌کنندهٔ بودجه", {"bud_center": _V, "bud_budgets": _VCE, "bud_prepare": _VCE}),
    "BUD_OFFICER": ("مسئول بودجه (بررسی و انتشار)", {
        **{s: _VE for s in _SCREENS}, "bud_review": _VE, "bud_publish": _VE, "bud_period": _VE, "bud_commitments": _V}),
    "BUD_APPROVER": ("تأییدکنندهٔ بودجه (مدیر مجاز)", {
        **{s: _VE for s in _SCREENS}, "bud_approve": _VE, "bud_exception": _VE}),
    "BUD_CONTROLLER": ("کنترل‌کنندهٔ ارشد بودجه", {
        **{s: _VE for s in _SCREENS}, "bud_override": _VE, "bud_exception": _VE, "bud_settings": _VE, "bud_config": _VE}),
    "BUD_BUYER": ("کارشناس خرید (بستن تعهد سفارش)", {"bud_center": _V, "bud_commitments": _VE, "bud_commitment": _VE}),
    "BUD_VIEWER": ("ناظر بودجه", {s: _V for s in _SCREENS}),
}


def ensure_role_templates(company_id: int) -> dict[str, int]:
    """(کد نقش ← شناسه). گزارش‌های بودجه برای همهٔ نقش‌ها قابل مشاهده است."""
    forms = {f.code: f.form_id for f in roles_service.list_forms()}
    report_forms = [code for code in forms if code.startswith("warehouse_report_bud_")]
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
