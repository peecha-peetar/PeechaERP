"""نقش‌های آمادهٔ CRM روی همان RBAC موجود (sec.roles / role_form_permissions) — هم‌الگوی نقش‌های تولید.

اجرای دوباره نقش موجود را تکراری نمی‌سازد و فقط دسترسی‌های کم‌شده را اضافه می‌کند.
"""

from __future__ import annotations

from peecha.services import roles as roles_service

_ALL = ("VIEW", "CREATE", "EDIT", "DELETE", "EXPORT")
_RW = ("VIEW", "CREATE", "EDIT")
TEMPLATES: dict[str, tuple[str, dict[str, tuple[str, ...]]]] = {
    "CRM_USER": ("کارشناس فروش (CRM)", {
        "crm_customer360": ("VIEW",), "crm_tasks": ("VIEW",), "crm_leads": _RW, "crm_pipeline": _RW, "crm_activities": _ALL[:4],
    }),
    "CRM_MANAGER": ("مدیر فروش (CRM)", {
        "crm_customer360": ("VIEW", "EXPORT"), "crm_tasks": ("VIEW",), "crm_leads": _ALL, "crm_pipeline": _ALL,
        "crm_activities": _ALL, "crm_assign": ("VIEW", "EDIT"), "crm_settings": ("VIEW",),
    }),
    "CRM_ADMIN": ("مدیر سیستم CRM", {
        "crm_customer360": ("VIEW", "EXPORT"), "crm_tasks": ("VIEW",), "crm_leads": _ALL, "crm_pipeline": _ALL,
        "crm_activities": _ALL, "crm_assign": ("VIEW", "EDIT"), "crm_settings": ("VIEW", "EDIT"),
    }),
}


def ensure_role_templates(company_id: int) -> dict[str, int]:
    """(کد نقش ← شناسه)."""
    forms = {f.code: f.form_id for f in roles_service.list_forms()}
    existing = {r.code: r.role_id for r in roles_service.list_roles(company_id)}
    out = {}
    for code, (_label, perms) in TEMPLATES.items():
        role_id = existing.get(code) or roles_service.create_role(company_id, code, None).role_id
        have = roles_service.get_role_permissions(role_id)
        for form_code, actions in perms.items():
            form_id = forms.get(form_code)
            for action in actions:
                if form_id is not None and (form_id, action) not in have:
                    roles_service.set_role_permission(role_id, form_id, action, True)
        out[code] = role_id
    return out
