"""دستیارِ فروشگاهِ اینترنتی (Peecha Advisor) -- طبقِ بازخوردِ صریحِ کاربر
(«امکاناتِ حیاتیِ PeechaSync -- دستیارِ فروشگاهِ اینترنتی»): برخلافِ
نگهبانِ اتصال/فیلدهایِ سئو/مرکزِ رسانه که هرکدام جداگانه‌اند، این سرویس
سلامتِ اتصال + کاملیِ سئو + آمادگیِ عکسِ کالاهایِ منتشرشده در فروشگاه را
یک‌جا جمع‌بندی و اولویت‌بندی می‌کند."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.commercial import MarketplaceConnection, MarketplaceItemMapping
from peecha.services import connectivity_guard as guard_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import inventory_catalog as catalog_service

_SEO_COMPLETE_THRESHOLD = 4  # چهار فیلدِ سئو: عنوان/اسلاگ/توضیح/کلیدواژه


@dataclass
class AdvisorIssue:
    severity: str  # DANGER|WARNING
    message: str
    fix_hint: str


@dataclass
class AdvisorSummary:
    connectivity_score: int
    seo_score: int
    image_score: int
    online_item_count: int
    issues: list[AdvisorIssue] = field(default_factory=list)


def _online_item_ids(company_id: int) -> set[int]:
    with new_session() as session:
        connection_ids = session.scalars(
            select(MarketplaceConnection.connection_id).where(MarketplaceConnection.company_id == company_id)
        ).all()
        if not connection_ids:
            return set()
        return set(
            session.scalars(
                select(MarketplaceItemMapping.item_id).where(MarketplaceItemMapping.connection_id.in_(connection_ids))
            )
        )


def _seo_fields_filled(item) -> int:
    return sum(1 for value in (item.seo_title, item.seo_url_slug, item.seo_meta_description, item.seo_meta_keywords) if value)


def compute_advisor_summary(company_id: int) -> AdvisorSummary:
    unhealthy_connections = guard_service.list_unhealthy_connections(company_id)
    connectivity_score = 100 if not unhealthy_connections else max(0, 100 - 25 * len(unhealthy_connections))

    online_item_ids = _online_item_ids(company_id)
    online_items = [item for item in catalog_service.list_items(company_id) if item.item_id in online_item_ids]

    issues: list[AdvisorIssue] = []
    for connection in unhealthy_connections:
        issues.append(AdvisorIssue(
            severity="DANGER",
            message=f"اتصالِ «{connection.display_name}» ({connection.platform_label}) ناسالم است -- {connection.consecutive_failure_count} شکستِ پیاپی",
            fix_hint="تبِ «نگهبانِ اتصال» در همینِ هاب",
        ))

    if not online_items:
        return AdvisorSummary(
            connectivity_score=connectivity_score, seo_score=100, image_score=100,
            online_item_count=0, issues=issues,
        )

    seo_incomplete = [item for item in online_items if _seo_fields_filled(item) < _SEO_COMPLETE_THRESHOLD]
    seo_score = round(100 * (len(online_items) - len(seo_incomplete)) / len(online_items))
    if seo_incomplete:
        issues.append(AdvisorIssue(
            severity="WARNING",
            message=f"{len(seo_incomplete)} کالایِ منتشرشده در فروشگاه، اطلاعاتِ سئویِ ناقص دارند (عنوان/اسلاگ/توضیح/کلیدواژه)",
            fix_hint="تبِ «فروشگاهیِ اینترنتی» در فرمِ تعریفِ همان کالا",
        ))

    items_without_image = [
        item for item in online_items
        if not dimensions_service.list_detail_account_files(company_id, item.item_detail_account_id)
    ]
    image_score = round(100 * (len(online_items) - len(items_without_image)) / len(online_items))
    if items_without_image:
        issues.append(AdvisorIssue(
            severity="DANGER" if len(items_without_image) > len(online_items) / 2 else "WARNING",
            message=f"{len(items_without_image)} کالایِ منتشرشده در فروشگاه، هیچ عکسی ندارند",
            fix_hint="تبِ «فایل‌ها/عکس‌ها» در فرمِ تعریفِ همان کالا",
        ))

    issues.sort(key=lambda i: 0 if i.severity == "DANGER" else 1)
    return AdvisorSummary(
        connectivity_score=connectivity_score, seo_score=seo_score, image_score=image_score,
        online_item_count=len(online_items), issues=issues,
    )
