"""سطح‌بندیِ کاربرانِ تولید -- R270: نقش‌هایِ آمادهٔ «کاربرِ تولید / مدیرِ تولید / حسابدارِ بها» رویِ همان RBACِ موجود.

فقط نقش و دسترسی ساخته می‌شود (sec.roles / role_form_permissions)؛ مدیرِ سیستم همیشه همه‌چیز دارد. اجرایِ دوباره
نقشِ موجود را تکراری نمی‌سازد و فقط دسترسی‌هایِ کم‌شده را اضافه می‌کند.
"""

from __future__ import annotations

from peecha.services import roles as roles_service

_ALL = ("VIEW", "CREATE", "EDIT", "DELETE")
_RW = ("VIEW", "CREATE", "EDIT")
TEMPLATES: dict[str, tuple[str, dict[str, tuple[str, ...]]]] = {
    "PRD_BASIC": ("کاربرِ تولید", {
        "prd_dashboard": ("VIEW",), "prd_orders": _RW, "prd_consume": ("VIEW", "EDIT"), "prd_complete": ("VIEW", "EDIT"),
    }),
    "PRD_MANAGER": ("مدیرِ تولید", {
        "prd_dashboard": ("VIEW",), "prd_orders": _ALL, "prd_release": ("VIEW", "EDIT"), "prd_consume": ("VIEW", "EDIT"),
        "prd_complete": ("VIEW", "EDIT"), "prd_close": ("VIEW", "EDIT"), "prd_planning": _RW, "prd_master": _RW,
        "prd_bom": ("VIEW", "EDIT"), "prd_routing": ("VIEW", "EDIT"), "prd_settings": ("VIEW",),
    }),
    "PRD_COST_ACCOUNTANT": ("حسابدارِ بهایِ تمام‌شده", {
        "prd_dashboard": ("VIEW",), "prd_orders": ("VIEW",), "prd_costing": _RW, "prd_cost_view": ("VIEW", "EDIT"),
        "prd_cost_adjust": ("VIEW", "EDIT"), "prd_allocation": ("VIEW", "EDIT"), "prd_close": ("VIEW", "EDIT"),
        "prd_settings": ("VIEW",),
    }),
}


def ensure_role_templates(company_id: int) -> dict[str, int]:
    """(کدِ نقش ← شناسه). گزارش‌هایِ تولید برایِ همهٔ نقش‌ها قابلِ مشاهده است."""
    forms = {f.code: f.form_id for f in roles_service.list_forms()}
    report_forms = [code for code in forms if code.startswith("warehouse_report_prd_")]
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
