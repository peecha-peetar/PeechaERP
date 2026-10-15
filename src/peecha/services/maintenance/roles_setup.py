"""نقش‌های آمادهٔ نگهداری (R312) روی همان RBAC موجود (sec.roles / role_form_permissions).

اجرای دوباره نقش تکراری نمی‌سازد و فقط دسترسی‌های کم‌شده را اضافه می‌کند. مدیر کل سیستم همیشه همه‌چیز دارد.
گام‌ها فقط با کلید «اعمال دسترسی‌های جداگانهٔ نگهداری» در سرویس‌ها اعمال می‌شوند.
"""

from __future__ import annotations

from peecha.services import roles as roles_service

_V = ("VIEW",)
_VE = ("VIEW", "EDIT")
_VCE = ("VIEW", "CREATE", "EDIT")
_SCREENS = ("mnt_dashboard", "mnt_requests", "mnt_work_orders", "mnt_equipment")
TEMPLATES: dict[str, tuple[str, dict[str, tuple[str, ...]]]] = {
    "MNT_REQUESTER": ("درخواست‌کنندهٔ تعمیر", {
        "mnt_requests": _VCE, "mnt_equipment": _V, "mnt_request": ("VIEW", "CREATE", "EDIT"),
    }),
    "MNT_PLANNER": ("برنامه‌ریز نگهداری", {
        **{s: _VCE for s in _SCREENS}, "mnt_pm": _VCE, "mnt_availability": _VCE, "mnt_request": _VCE, "mnt_plan": _VCE,
        "mnt_manage": _VCE,
    }),
    "MNT_TECHNICIAN": ("تکنسین نگهداری", {
        "mnt_requests": _VCE, "mnt_work_orders": _VE, "mnt_equipment": _V, "mnt_request": _VCE, "mnt_execute": _VE,
    }),
    "MNT_SUPERVISOR": ("سرپرست نگهداری", {
        **{s: _VCE for s in _SCREENS}, "mnt_pm": _V, "mnt_availability": _V, "mnt_request": _VCE, "mnt_plan": _VCE,
        "mnt_execute": _VE, "mnt_verify": _VE,
    }),
    "MNT_STOREKEEPER": ("انباردار قطعات نگهداری", {
        "mnt_work_orders": _V, "mnt_equipment": _V, "mnt_parts": _VE,
    }),
    "MNT_APPROVER": ("تأییدکنندهٔ نگهداری و مالی", {
        **{s: _V for s in _SCREENS}, "mnt_pm": _V, "mnt_availability": _VE, "mnt_approve": _VE, "mnt_cost": _VE,
    }),
}


def ensure_role_templates(company_id: int) -> dict[str, int]:
    """(کد نقش ← شناسه). گزارش‌های نگهداری برای همهٔ نقش‌ها قابل مشاهده است."""
    forms = {f.code: f.form_id for f in roles_service.list_forms()}
    report_forms = [code for code in forms if code.startswith("warehouse_report_mnt_")]
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
