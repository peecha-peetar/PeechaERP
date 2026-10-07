"""موتور اتوماسیون CRM (فاز ۸، R287).

هر قاعده = «رویداد/شرط» (مشتری غیرفعال، فاکتور معوق، سرنخ تماس‌نگرفته، فرصت راکد، ریسک ریزش، نقض SLA، عضویت سگمنت)
+ «اقدام» (ساخت فعالیت، اعلان، ارسال پیام). شرط‌ها فقط دادهٔ موجود ERP/CRM را می‌خوانند و اقدام‌ها از همان سرویس‌های
فعالیت، اعلان و مرکز ارتباطات می‌گذرند. هر موجودیت در بازهٔ «فاصلهٔ تکرار» قاعده فقط یک بار پردازش می‌شود
(crm.automation_log)؛ پس اجرای مکرر (تیک پس‌زمینه یا دکمه) امن است.
"""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.accounting import DetailAccount
from peecha.db.models.commercial import ServiceTicket, VisitPlan
from peecha.db.models.crm import AutomationLog, AutomationRule, CustomerScore, Lead, Opportunity, PipelineStage
from peecha.services import commercial_settlements as settlements_service
from peecha.services.crm import activities as act_service
from peecha.services.crm import common as c
from peecha.services.crm import communication as comm
from peecha.services.crm import segments as seg_service

ZERO = decimal.Decimal(0)


@dataclass(frozen=True)
class Param:
    key: str
    label: str
    kind: str  # int | stage | segment | text
    default: object = None


TRIGGERS: dict[str, tuple[str, str, tuple[Param, ...]]] = {
    "CUSTOMER_INACTIVE": ("مشتری بدون خرید", "CUSTOMER", (Param("days", "روز بدون خرید", "int", 60),)),
    "CHURN_HIGH": ("ریسک ریزش زیاد", "CUSTOMER", ()),
    "INVOICE_OVERDUE": ("فاکتور معوق", "CUSTOMER", (Param("days", "روز گذشته از سررسید", "int", 1),
                                                    Param("min_amount", "حداقل مبلغ معوق", "int", 0))),
    "LEAD_NOT_CONTACTED": ("سرنخ بدون تماس", "LEAD", (Param("hours", "ساعت پس از ثبت", "int", 24),)),
    "OPPORTUNITY_STALE": ("فرصت راکد در مرحله", "OPPORTUNITY", (Param("days", "روز در همان مرحله", "int", 14),
                                                               Param("stage_code", "فقط مرحله (کد، اختیاری)", "text", ""))),
    "TICKET_SLA_BREACHED": ("نقض SLA تیکت", "TICKET", ()),
    "SEGMENT_MEMBER": ("عضو سگمنت", "CUSTOMER", (Param("segment_id", "سگمنت", "segment", None),)),
}
ACTIONS: dict[str, tuple[str, tuple[Param, ...]]] = {
    "CREATE_ACTIVITY": ("ساخت فعالیت/پیگیری", (Param("activity_type", "نوع فعالیت", "text", "FOLLOW_UP"),
                                                Param("subject", "موضوع (با {name} و ...)", "text", "پیگیری {name}"),
                                                Param("due_in_days", "موعد (روز بعد)", "int", 0),
                                                Param("priority", "اولویت", "text", "NORMAL"),
                                                Param("assign_to", "مسئول (OWNER یا شناسهٔ کاربر)", "text", "OWNER"))),
    "NOTIFY": ("اعلان به کاربر", (Param("title", "عنوان", "text", "{name}"), Param("body", "متن", "text", ""),
                                  Param("user_id", "کاربر (OWNER یا شناسه)", "text", "OWNER"))),
    "SEND_MESSAGE": ("ارسال پیام به مشتری", (Param("channel", "کانال", "text", "SMS"), Param("template_id", "الگو", "int", None),
                                              Param("body", "متن (اگر الگو نیست)", "text", ""))),
}
DEFAULT_RULES = (
    ("مشتری ۶۰ روز بدون خرید ← پیگیری فروش", "CUSTOMER_INACTIVE", {"days": 60}, "CREATE_ACTIVITY",
     {"activity_type": "FOLLOW_UP", "subject": "پیگیری فروش: {name} ({days} روز بدون خرید)", "due_in_days": 0}, 30),
    ("فاکتور معوق ← پیگیری وصول", "INVOICE_OVERDUE", {"days": 1, "min_amount": 0}, "CREATE_ACTIVITY",
     {"activity_type": "CALL", "subject": "پیگیری وصول {name} (معوق {overdue})", "due_in_days": 0, "priority": "HIGH"}, 7),
    ("سرنخ ۲۴ ساعت بدون تماس ← اعلان به مسئول", "LEAD_NOT_CONTACTED", {"hours": 24}, "NOTIFY",
     {"title": "سرنخ {name} هنوز تماس نگرفته است", "user_id": "OWNER"}, 3),
    ("فرصت ۱۴ روز راکد ← وظیفه", "OPPORTUNITY_STALE", {"days": 14}, "CREATE_ACTIVITY",
     {"activity_type": "TASK", "subject": "پیگیری فرصت {name} ({days} روز بدون تغییر)", "due_in_days": 1}, 14),
    ("ریسک ریزش زیاد ← جلسه", "CHURN_HIGH", {}, "CREATE_ACTIVITY",
     {"activity_type": "MEETING", "subject": "جلسهٔ حفظ مشتری: {name}", "due_in_days": 3, "priority": "HIGH"}, 30),
)


@dataclass
class Match:
    entity_type: str
    entity_id: int
    customer_id: int | None
    lead_id: int | None
    owner_user_id: int | None
    values: dict


# --- قاعده‌ها -------------------------------------------------------------------------------------------
def ensure_default_rules(company_id: int) -> None:
    """قاعده‌های نمونه (غیرفعال) تا کاربر فقط فعالشان کند."""
    with new_session() as session:
        if session.scalar(select(func.count()).where(AutomationRule.company_id == company_id)):
            return
        for name, trig, cond, action, params, cooldown in DEFAULT_RULES:
            session.add(AutomationRule(company_id=company_id, name=name, trigger_code=trig, conditions=cond, action_code=action,
                                       action_params=params, cooldown_days=cooldown, is_active=False))
        session.commit()


def list_rules(company_id: int) -> list[AutomationRule]:
    ensure_default_rules(company_id)
    with new_session() as session:
        rows = list(session.scalars(select(AutomationRule).where(AutomationRule.company_id == company_id)
                                    .order_by(AutomationRule.is_active.desc(), AutomationRule.rule_id)))
        session.expunge_all()
        return rows


def _validate(company_id: int, trigger_code: str, conditions: dict, action_code: str, params: dict) -> None:
    if trigger_code not in TRIGGERS:
        raise ValueError("رویداد قاعده نامعتبر است.")
    if action_code not in ACTIONS:
        raise ValueError("اقدام قاعده نامعتبر است.")
    for p in TRIGGERS[trigger_code][2]:
        v = conditions.get(p.key)
        if p.kind == "int" and v is not None and int(v) < 0:
            raise ValueError(f"«{p.label}» نمی‌تواند منفی باشد.")
        if p.kind == "segment":
            if not v:
                raise ValueError("سگمنت قاعده انتخاب نشده است.")
            seg_service.get_segment(company_id, int(v))
    if action_code == "CREATE_ACTIVITY":
        if params.get("activity_type", "FOLLOW_UP") not in c.ACTIVITY_TYPES or params.get("activity_type") == "OPPORTUNITY":
            raise ValueError("نوع فعالیت قاعده نامعتبر است.")
        if params.get("priority", "NORMAL") not in c.PRIORITIES:
            raise ValueError("اولویت قاعده نامعتبر است.")
    if action_code == "SEND_MESSAGE":
        if params.get("channel", "SMS") not in comm.CHANNELS or params.get("channel") == "INTERNAL":
            raise ValueError("کانال پیام قاعده نامعتبر است.")
        if not params.get("template_id") and not (params.get("body") or "").strip():
            raise ValueError("برای ارسال پیام، الگو یا متن لازم است.")
    owner = params.get("assign_to", params.get("user_id", "OWNER"))
    if owner not in (None, "", "OWNER") and not str(owner).isdigit():
        raise ValueError("مسئول باید OWNER یا شناسهٔ کاربر باشد.")


def save_rule(company_id: int, user_id: int | None, *, rule_id: int | None = None, name: str, trigger_code: str,
              conditions: dict | None, action_code: str, action_params: dict | None, cooldown_days: int = 7,
              is_active: bool = True) -> int:
    conditions, action_params = dict(conditions or {}), dict(action_params or {})
    if not (name or "").strip():
        raise ValueError("نام قاعده الزامی است.")
    if int(cooldown_days) < 0:
        raise ValueError("فاصلهٔ تکرار نمی‌تواند منفی باشد.")
    _validate(company_id, trigger_code, conditions, action_code, action_params)
    with new_session() as session:
        if rule_id:
            r = session.get(AutomationRule, rule_id)
            if r is None or r.company_id != company_id:
                raise ValueError("قاعده نامعتبر است.")
        else:
            r = AutomationRule(company_id=company_id, created_by_user_id=user_id)
            session.add(r)
        r.name, r.trigger_code, r.conditions, r.action_code = name.strip(), trigger_code, conditions, action_code
        r.action_params, r.cooldown_days, r.is_active = action_params, int(cooldown_days), is_active
        session.flush()
        c.audit(session, company_id, user_id, "AutomationRule", r.rule_id, "UPDATE" if rule_id else "CREATE",
                {"name": r.name, "trigger": trigger_code, "action": action_code, "active": is_active})
        session.commit()
        return r.rule_id


def delete_rule(company_id: int, user_id: int | None, rule_id: int) -> None:
    with new_session() as session:
        r = session.get(AutomationRule, rule_id)
        if r is None or r.company_id != company_id:
            raise ValueError("قاعده نامعتبر است.")
        c.audit(session, company_id, user_id, "AutomationRule", rule_id, "DELETE", {"name": r.name})
        session.delete(r)
        session.commit()


# --- یافتن موجودیت‌ها --------------------------------------------------------------------------------------
def _customer_owners(session, company_id: int, ids: set[int]) -> dict[int, int]:
    rows = session.execute(select(VisitPlan.customer_detail_account_id, VisitPlan.assigned_visitor_user_id).where(
        VisitPlan.company_id == company_id, VisitPlan.is_active.is_(True), VisitPlan.assigned_visitor_user_id.is_not(None),
        VisitPlan.customer_detail_account_id.in_(list(ids) or [-1])).order_by(VisitPlan.visit_plan_id)).all()
    out: dict[int, int] = {}
    for cid, uid in rows:
        out.setdefault(cid, uid)
    return out


def find_matches(company_id: int, rule: AutomationRule, now: datetime.datetime | None = None) -> list[Match]:
    now = now or c.now()
    today = now.date()
    cond = {p.key: rule.conditions.get(p.key, p.default) for p in TRIGGERS[rule.trigger_code][2]}
    t = rule.trigger_code
    with new_session() as session:
        names = lambda ids: dict(session.execute(select(DetailAccount.detail_account_id, DetailAccount.name).where(
            DetailAccount.detail_account_id.in_(list(ids) or [-1]))).all())
        if t in ("CUSTOMER_INACTIVE", "CHURN_HIGH", "SEGMENT_MEMBER", "INVOICE_OVERDUE"):
            values: dict[int, dict] = {}
            if t == "CUSTOMER_INACTIVE":
                for cid, days in session.execute(select(CustomerScore.customer_detail_account_id, CustomerScore.recency_days).where(
                        CustomerScore.company_id == company_id, CustomerScore.recency_days >= int(cond["days"]))):
                    values[cid] = {"days": days}
            elif t == "CHURN_HIGH":
                for cid, risk in session.execute(select(CustomerScore.customer_detail_account_id, CustomerScore.churn_risk).where(
                        CustomerScore.company_id == company_id, CustomerScore.churn_band == "HIGH")):
                    values[cid] = {"churn": risk}
            elif t == "SEGMENT_MEMBER":
                values = {cid: {} for cid in seg_service.members(company_id, int(cond["segment_id"]))}
            else:
                due = today - datetime.timedelta(days=int(cond["days"] or 0))
                for u in settlements_service.list_unsettled_invoices_bulk(company_id, due_on_or_before=due):
                    v = values.setdefault(u.counterparty_detail_account_id, {"overdue": ZERO, "invoices": 0})
                    v["overdue"] += u.remaining_amount
                    v["invoices"] += 1
                values = {k: v for k, v in values.items() if v["overdue"] >= decimal.Decimal(cond["min_amount"] or 0)}
                for v in values.values():
                    v["overdue"] = f"{v['overdue']:,.0f}"
            owners, nm = _customer_owners(session, company_id, set(values)), names(values)
            return [Match("CUSTOMER", cid, cid, None, owners.get(cid), {"name": nm.get(cid, ""), **v}) for cid, v in values.items()]
        if t == "LEAD_NOT_CONTACTED":
            limit = now - datetime.timedelta(hours=int(cond["hours"]))
            rows = session.scalars(select(Lead).where(Lead.company_id == company_id, Lead.status_code == "NEW", Lead.created_at <= limit))
            return [Match("LEAD", x.lead_id, None, x.lead_id, x.owner_user_id, {"name": x.full_name}) for x in rows]
        if t == "OPPORTUNITY_STALE":
            limit = now - datetime.timedelta(days=int(cond["days"]))
            q = select(Opportunity, PipelineStage.code).join(PipelineStage, PipelineStage.stage_id == Opportunity.stage_id).where(
                Opportunity.company_id == company_id, Opportunity.status_code == "OPEN", Opportunity.stage_entered_at <= limit)
            if cond.get("stage_code"):
                q = q.where(PipelineStage.code == str(cond["stage_code"]).strip().upper())
            return [Match("OPPORTUNITY", o.opportunity_id, o.customer_detail_account_id, None if o.customer_detail_account_id else o.lead_id,
                          o.owner_user_id, {"name": o.title, "days": (now - o.stage_entered_at).days, "amount": f"{o.amount:,.0f}"})
                    for o, _code in session.execute(q)]
        if t == "TICKET_SLA_BREACHED":
            rows = session.scalars(select(ServiceTicket).where(ServiceTicket.company_id == company_id, ServiceTicket.sla_breached.is_(True),
                                                               ServiceTicket.status_code.in_(("OPEN", "IN_PROGRESS"))))
            rows = list(rows)
            nm = names({x.customer_detail_account_id for x in rows})
            return [Match("TICKET", x.ticket_id, x.customer_detail_account_id, None, x.assigned_to_user_id or x.created_by_user_id,
                          {"name": nm.get(x.customer_detail_account_id, ""), "subject": x.subject}) for x in rows]
    return []


# --- اجرا ----------------------------------------------------------------------------------------------
def _recent(session, rule: AutomationRule, m: Match, now: datetime.datetime) -> bool:
    q = select(AutomationLog.log_id).where(AutomationLog.rule_id == rule.rule_id, AutomationLog.entity_type == m.entity_type,
                                           AutomationLog.entity_id == m.entity_id)
    if rule.cooldown_days:
        q = q.where(AutomationLog.created_at > now - datetime.timedelta(days=rule.cooldown_days))
    return session.scalar(q.limit(1)) is not None


def _owner(rule: AutomationRule, value, m: Match) -> int | None:
    if value in (None, "", "OWNER"):
        return m.owner_user_id or rule.created_by_user_id
    return int(value)


def _act(company_id: int, rule: AutomationRule, m: Match, actor: int) -> dict:
    p = rule.action_params or {}
    if rule.action_code == "CREATE_ACTIVITY":
        aid = act_service.create_activity(company_id, actor, act_service.ActivityFields(
            p.get("activity_type") or "FOLLOW_UP", comm.render(p.get("subject") or "پیگیری {name}", m.values)[:200],
            customer_detail_account_id=m.customer_id, lead_id=m.lead_id,
            opportunity_id=m.entity_id if m.entity_type == "OPPORTUNITY" else None,
            ticket_id=m.entity_id if m.entity_type == "TICKET" else None,
            due_date=datetime.date.today() + datetime.timedelta(days=int(p.get("due_in_days") or 0)),
            priority_code=p.get("priority") or "NORMAL", assigned_to_user_id=_owner(rule, p.get("assign_to"), m),
            description=f"ساخته‌شده با قاعدهٔ «{rule.name}»"))
        return {"activity_id": aid}
    if rule.action_code == "NOTIFY":
        target = _owner(rule, p.get("user_id"), m)
        if target:
            c.notify(company_id, target, "CRM_AUTOMATION", comm.render(p.get("title") or "{name}", m.values)[:200],
                     comm.render(p.get("body") or rule.name, m.values), f"Crm{m.entity_type.title()}", m.entity_id)
        return {"notified": target}
    mid = comm.send_message(company_id, actor, p.get("channel") or "SMS", p.get("body") or "", customer_id=m.customer_id,
                            lead_id=m.lead_id, template_id=int(p["template_id"]) if p.get("template_id") else None,
                            values=m.values, rule_id=rule.rule_id)
    return {"message_id": mid}


def run_rule(company_id: int, rule_id: int, user_id: int | None = None, now: datetime.datetime | None = None) -> int:
    """یک قاعده را اجرا می‌کند؛ برمی‌گرداند: تعداد موجودیت‌هایی که اقدام رویشان انجام شد."""
    now = now or c.now()
    with new_session() as session:
        rule = session.get(AutomationRule, rule_id)
        if rule is None or rule.company_id != company_id:
            raise ValueError("قاعده نامعتبر است.")
        session.expunge(rule)
    matches = find_matches(company_id, rule, now)
    actor = user_id or rule.created_by_user_id or comm._company_admin(company_id)
    done = 0
    for m in matches:
        with new_session() as session:
            if _recent(session, rule, m, now):
                continue
        try:
            result = _act(company_id, rule, m, actor)
        except ValueError as exc:
            result = {"error": str(exc)}
        with new_session() as session:
            session.add(AutomationLog(rule_id=rule.rule_id, company_id=company_id, entity_type=m.entity_type, entity_id=m.entity_id,
                                      customer_detail_account_id=m.customer_id, result=c._plain(result)))
            session.commit()
        done += 1 if "error" not in result else 0
    with new_session() as session:
        r = session.get(AutomationRule, rule_id)
        r.last_run_at, r.run_count = now, r.run_count + done
        session.commit()
    return done


def run_all(company_id: int, user_id: int | None = None) -> dict[int, int]:
    """همهٔ قاعده‌های فعال (تیک پس‌زمینهٔ برنامه یا دکمهٔ «اجرای اکنون»). خطای یک قاعده بقیه را متوقف نمی‌کند."""
    from peecha.services.crm import analytics, tickets

    tickets.check_sla(company_id)
    rules = [r for r in list_rules(company_id) if r.is_active]
    if any(r.trigger_code in ("CUSTOMER_INACTIVE", "CHURN_HIGH", "SEGMENT_MEMBER") for r in rules):
        analytics.ensure_fresh(company_id)
    out = {}
    for r in rules:
        try:
            out[r.rule_id] = run_rule(company_id, r.rule_id, user_id)
        except ValueError:
            out[r.rule_id] = -1
    return out


def preview(company_id: int, trigger_code: str, conditions: dict) -> int:
    """تعداد موجودیت‌هایی که اکنون با این شرط جور درمی‌آیند (بدون اقدام)."""
    _validate(company_id, trigger_code, conditions or {}, "NOTIFY", {})
    fake = AutomationRule(company_id=company_id, trigger_code=trigger_code, conditions=conditions or {}, action_code="NOTIFY",
                          action_params={}, cooldown_days=0)
    return len(find_matches(company_id, fake))


def list_log(company_id: int, rule_id: int | None = None, limit: int = 300) -> list[dict]:
    with new_session() as session:
        q = select(AutomationLog, AutomationRule.name, DetailAccount.name).join(
            AutomationRule, AutomationRule.rule_id == AutomationLog.rule_id).outerjoin(
            DetailAccount, DetailAccount.detail_account_id == AutomationLog.customer_detail_account_id).where(
            AutomationLog.company_id == company_id)
        if rule_id:
            q = q.where(AutomationLog.rule_id == rule_id)
        return [{"log_id": x.log_id, "rule_id": x.rule_id, "rule_name": rname, "entity_type": x.entity_type, "entity_id": x.entity_id,
                 "customer_name": cname or "", "result": x.result, "created_at": x.created_at}
                for x, rname, cname in session.execute(q.order_by(AutomationLog.log_id.desc()).limit(limit))]
