"""نقش‌های آمادهٔ CRM روی همان RBAC موجود (sec.roles / role_form_permissions) — هم‌الگوی نقش‌های تولید.

اجرای دوباره نقش موجود را تکراری نمی‌سازد و فقط دسترسی‌های کم‌شده را اضافه می‌کند.
"""

from __future__ import annotations

from peecha.services import roles as roles_service

_ALL = ("VIEW", "CREATE", "EDIT", "DELETE", "EXPORT")
_RW = ("VIEW", "CREATE", "EDIT")
_REPORTS = ("CRM_LEAD_SOURCES", "CRM_LEAD_FUNNEL", "CRM_PIPELINE", "CRM_WON_LOST", "CRM_PERFORMANCE", "CRM_FORECAST", "CRM_RFM",
            "CRM_CHURN", "CRM_CLV", "CRM_INACTIVE", "CRM_TICKETS_SLA", "CRM_COMPLAINTS", "CRM_SATISFACTION", "CRM_CAMPAIGNS",
            "CRM_ACTIVITIES", "CRM_OVERDUE")
_REPORT_PERMS = {f"warehouse_report_{c.lower()}": ("VIEW", "PRINT", "EXPORT") for c in _REPORTS}
TEMPLATES: dict[str, tuple[str, dict[str, tuple[str, ...]]]] = {
    "CRM_USER": ("کارشناس فروش (CRM)", {
        "crm_customer360": ("VIEW",), "crm_tasks": ("VIEW",), "crm_leads": _RW, "crm_pipeline": _RW, "crm_activities": _ALL[:4],
        "crm_analytics": ("VIEW",), "crm_campaigns": ("VIEW",), "crm_tickets": _RW, "crm_automation": ("VIEW",), "crm_dashboard": ("VIEW",),
        "warehouse_report_crm_overdue": ("VIEW", "PRINT"),
    }),
    "CRM_MANAGER": ("مدیر فروش (CRM)", {
        "crm_customer360": ("VIEW", "EXPORT"), "crm_tasks": ("VIEW",), "crm_leads": _ALL, "crm_pipeline": _ALL,
        "crm_activities": _ALL, "crm_assign": ("VIEW", "EDIT"), "crm_settings": ("VIEW",),
        "crm_analytics": _ALL, "crm_campaigns": _ALL, "crm_tickets": _ALL, "crm_automation": _ALL, "crm_dashboard": ("VIEW", "EXPORT"), **_REPORT_PERMS,
    }),
    "CRM_ADMIN": ("مدیر سیستم CRM", {
        "crm_customer360": ("VIEW", "EXPORT"), "crm_tasks": ("VIEW",), "crm_leads": _ALL, "crm_pipeline": _ALL,
        "crm_activities": _ALL, "crm_assign": ("VIEW", "EDIT"), "crm_settings": ("VIEW", "EDIT"),
        "crm_analytics": _ALL, "crm_campaigns": _ALL, "crm_tickets": _ALL, "crm_automation": _ALL, "crm_dashboard": ("VIEW", "EXPORT"), **_REPORT_PERMS,
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
