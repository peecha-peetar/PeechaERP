"""سرویسِ طراحِ بصریِ گزارشِ چاپی (WYSIWYG، مثلِ FastReport) — CRUدِ خالص
(بدونِ Qt/رسم). رندر/پیجینیشن در ui/visual_report_render.py است، چون آن
بخش ذاتاً به QPainter/QPrinter وابسته است."""

from __future__ import annotations

import decimal
from dataclasses import dataclass

from sqlalchemy import delete, select

from peecha.db.base import new_session
from peecha.db.models.accounting import (
    VisualReportBand,
    VisualReportObject,
    VisualReportTemplate,
)

# پیش‌فرضِ ارتفاعِ باندها به میلی‌متر — طبقِ رایج‌ترین اندازه‌هایِ
# گزارش‌هایِ اداری (هدر/فوتر بلندتر برایِ جاگرفتنِ چند خط، جزئیات کوتاه
# برایِ یک خطِ جدول).
_DEFAULT_BAND_HEIGHTS = {
    "REPORT_HEADER": 20,
    "PAGE_HEADER": 10,
    "GROUP_HEADER": 8,
    "DETAIL": 7,
    "GROUP_FOOTER": 8,
    "PAGE_FOOTER": 10,
    "REPORT_FOOTER": 15,
}
_DEFAULT_BAND_TYPES = ["REPORT_HEADER", "PAGE_HEADER", "DETAIL", "PAGE_FOOTER", "REPORT_FOOTER"]
_GROUP_BAND_TYPES = ["GROUP_HEADER", "GROUP_FOOTER"]

BAND_ORDER = [
    "REPORT_HEADER",
    "PAGE_HEADER",
    "GROUP_HEADER",
    "DETAIL",
    "GROUP_FOOTER",
    "PAGE_FOOTER",
    "REPORT_FOOTER",
]


@dataclass
class VisualTemplateRow:
    visual_template_id: int
    name: str
    report_template_id: int
    page_size: str
    orientation: str
    margin_top_mm: decimal.Decimal
    margin_bottom_mm: decimal.Decimal
    margin_left_mm: decimal.Decimal
    margin_right_mm: decimal.Decimal
    use_grouping: bool


@dataclass
class VisualBandRow:
    band_id: int
    band_type: str
    height_mm: decimal.Decimal


@dataclass
class VisualObjectRow:
    object_id: int
    band_id: int
    object_type: str
    x_mm: decimal.Decimal
    y_mm: decimal.Decimal
    width_mm: decimal.Decimal
    height_mm: decimal.Decimal
    text_content: str | None = None
    field_code: str | None = None
    font_family: str = "default"
    font_size: int = 10
    font_bold: bool = False
    text_align: str = "RIGHT"
    border_style: str = "NONE"
    image_data: bytes | None = None


def _to_row(t: VisualReportTemplate) -> VisualTemplateRow:
    return VisualTemplateRow(
        visual_template_id=t.visual_template_id,
        name=t.name,
        report_template_id=t.report_template_id,
        page_size=t.page_size,
        orientation=t.orientation,
        margin_top_mm=t.margin_top_mm,
        margin_bottom_mm=t.margin_bottom_mm,
        margin_left_mm=t.margin_left_mm,
        margin_right_mm=t.margin_right_mm,
        use_grouping=t.use_grouping,
    )


def list_templates(company_id: int) -> list[VisualTemplateRow]:
    with new_session() as session:
        rows = session.scalars(
            select(VisualReportTemplate)
            .where(VisualReportTemplate.company_id == company_id)
            .order_by(VisualReportTemplate.display_order, VisualReportTemplate.visual_template_id)
        ).all()
        return [_to_row(t) for t in rows]


def get_template(visual_template_id: int) -> VisualTemplateRow | None:
    with new_session() as session:
        t = session.get(VisualReportTemplate, visual_template_id)
        return _to_row(t) if t is not None else None


def create_template(
    company_id: int,
    name: str,
    report_template_id: int,
    *,
    page_size: str = "A4",
    orientation: str = "PORTRAIT",
    use_grouping: bool = False,
) -> int:
    with new_session() as session:
        max_order = session.scalar(
            select(VisualReportTemplate.display_order)
            .where(VisualReportTemplate.company_id == company_id)
            .order_by(VisualReportTemplate.display_order.desc())
        )
        template = VisualReportTemplate(
            company_id=company_id,
            name=name,
            report_template_id=report_template_id,
            page_size=page_size,
            orientation=orientation,
            use_grouping=use_grouping,
            display_order=(max_order or 0) + 1,
        )
        session.add(template)
        session.flush()

        band_types = list(_DEFAULT_BAND_TYPES)
        if use_grouping:
            band_types += _GROUP_BAND_TYPES
        for band_type in band_types:
            session.add(
                VisualReportBand(
                    visual_template_id=template.visual_template_id,
                    band_type=band_type,
                    height_mm=_DEFAULT_BAND_HEIGHTS[band_type],
                )
            )
        session.commit()
        return template.visual_template_id


def rename_template(visual_template_id: int, name: str) -> None:
    with new_session() as session:
        template = session.get(VisualReportTemplate, visual_template_id)
        if template is None:
            raise ValueError("گزارش پیدا نشد.")
        template.name = name
        session.commit()


def update_template_settings(
    visual_template_id: int,
    *,
    page_size: str | None = None,
    orientation: str | None = None,
    margin_top_mm: decimal.Decimal | None = None,
    margin_bottom_mm: decimal.Decimal | None = None,
    margin_left_mm: decimal.Decimal | None = None,
    margin_right_mm: decimal.Decimal | None = None,
    use_grouping: bool | None = None,
) -> None:
    with new_session() as session:
        template = session.get(VisualReportTemplate, visual_template_id)
        if template is None:
            raise ValueError("گزارش پیدا نشد.")
        if page_size is not None:
            template.page_size = page_size
        if orientation is not None:
            template.orientation = orientation
        if margin_top_mm is not None:
            template.margin_top_mm = margin_top_mm
        if margin_bottom_mm is not None:
            template.margin_bottom_mm = margin_bottom_mm
        if margin_left_mm is not None:
            template.margin_left_mm = margin_left_mm
        if margin_right_mm is not None:
            template.margin_right_mm = margin_right_mm

        if use_grouping is not None and use_grouping != template.use_grouping:
            template.use_grouping = use_grouping
            existing_types = {
                b.band_type
                for b in session.scalars(
                    select(VisualReportBand).where(VisualReportBand.visual_template_id == visual_template_id)
                ).all()
            }
            if use_grouping:
                for band_type in _GROUP_BAND_TYPES:
                    if band_type not in existing_types:
                        session.add(
                            VisualReportBand(
                                visual_template_id=visual_template_id,
                                band_type=band_type,
                                height_mm=_DEFAULT_BAND_HEIGHTS[band_type],
                            )
                        )
            else:
                group_bands = session.scalars(
                    select(VisualReportBand).where(
                        VisualReportBand.visual_template_id == visual_template_id,
                        VisualReportBand.band_type.in_(_GROUP_BAND_TYPES),
                    )
                ).all()
                for band in group_bands:
                    session.execute(
                        delete(VisualReportObject).where(VisualReportObject.band_id == band.band_id)
                    )
                    session.delete(band)
        session.commit()


def delete_template(visual_template_id: int) -> None:
    with new_session() as session:
        band_ids = list(
            session.scalars(
                select(VisualReportBand.band_id).where(VisualReportBand.visual_template_id == visual_template_id)
            ).all()
        )
        if band_ids:
            session.execute(delete(VisualReportObject).where(VisualReportObject.band_id.in_(band_ids)))
            session.execute(delete(VisualReportBand).where(VisualReportBand.band_id.in_(band_ids)))
        session.execute(
            delete(VisualReportTemplate).where(VisualReportTemplate.visual_template_id == visual_template_id)
        )
        session.commit()


def list_bands(visual_template_id: int) -> list[VisualBandRow]:
    with new_session() as session:
        rows = session.scalars(
            select(VisualReportBand).where(VisualReportBand.visual_template_id == visual_template_id)
        ).all()
        by_type = {b.band_type: b for b in rows}
        # همیشه به ترتیبِ چیدمانِ واقعیِ صفحه برگردانده شود (نه ترتیبِ درج).
        return [
            VisualBandRow(band_id=by_type[t].band_id, band_type=t, height_mm=by_type[t].height_mm)
            for t in BAND_ORDER
            if t in by_type
        ]


def set_band_height(band_id: int, height_mm: decimal.Decimal) -> None:
    with new_session() as session:
        band = session.get(VisualReportBand, band_id)
        if band is None:
            raise ValueError("باند پیدا نشد.")
        band.height_mm = height_mm
        session.commit()


def _to_object_row(o: VisualReportObject) -> VisualObjectRow:
    return VisualObjectRow(
        object_id=o.object_id,
        band_id=o.band_id,
        object_type=o.object_type,
        x_mm=o.x_mm,
        y_mm=o.y_mm,
        width_mm=o.width_mm,
        height_mm=o.height_mm,
        text_content=o.text_content,
        field_code=o.field_code,
        font_family=o.font_family,
        font_size=o.font_size,
        font_bold=o.font_bold,
        text_align=o.text_align,
        border_style=o.border_style,
        image_data=o.image_data,
    )


def list_objects_by_band(visual_template_id: int) -> dict[int, list[VisualObjectRow]]:
    """همه‌یِ اشیایِ همه‌یِ باندهایِ یک الگو، یک‌جا (برایِ رندر/طراحی) — دیکشنری
    از band_id به لیستِ اشیا."""
    with new_session() as session:
        band_ids = list(
            session.scalars(
                select(VisualReportBand.band_id).where(VisualReportBand.visual_template_id == visual_template_id)
            ).all()
        )
        if not band_ids:
            return {}
        objects = session.scalars(
            select(VisualReportObject).where(VisualReportObject.band_id.in_(band_ids))
        ).all()
        result: dict[int, list[VisualObjectRow]] = {band_id: [] for band_id in band_ids}
        for o in objects:
            result[o.band_id].append(_to_object_row(o))
        return result


def create_object(
    band_id: int,
    object_type: str,
    x_mm: decimal.Decimal,
    y_mm: decimal.Decimal,
    width_mm: decimal.Decimal,
    height_mm: decimal.Decimal,
    *,
    text_content: str | None = None,
    field_code: str | None = None,
    font_size: int = 10,
    font_bold: bool = False,
    text_align: str = "RIGHT",
    border_style: str = "NONE",
    image_data: bytes | None = None,
) -> int:
    with new_session() as session:
        obj = VisualReportObject(
            band_id=band_id,
            object_type=object_type,
            x_mm=x_mm,
            y_mm=y_mm,
            width_mm=width_mm,
            height_mm=height_mm,
            text_content=text_content,
            field_code=field_code,
            font_size=font_size,
            font_bold=font_bold,
            text_align=text_align,
            border_style=border_style,
            image_data=image_data,
        )
        session.add(obj)
        session.commit()
        return obj.object_id


def update_object(
    object_id: int,
    *,
    x_mm: decimal.Decimal | None = None,
    y_mm: decimal.Decimal | None = None,
    width_mm: decimal.Decimal | None = None,
    height_mm: decimal.Decimal | None = None,
    text_content: str | None = ...,
    field_code: str | None = ...,
    font_size: int | None = None,
    font_bold: bool | None = None,
    text_align: str | None = None,
    border_style: str | None = None,
    image_data: bytes | None = ...,
) -> None:
    with new_session() as session:
        obj = session.get(VisualReportObject, object_id)
        if obj is None:
            raise ValueError("شیء پیدا نشد.")
        if x_mm is not None:
            obj.x_mm = x_mm
        if y_mm is not None:
            obj.y_mm = y_mm
        if width_mm is not None:
            obj.width_mm = width_mm
        if height_mm is not None:
            obj.height_mm = height_mm
        if text_content is not ...:
            obj.text_content = text_content
        if field_code is not ...:
            obj.field_code = field_code
        if font_size is not None:
            obj.font_size = font_size
        if font_bold is not None:
            obj.font_bold = font_bold
        if text_align is not None:
            obj.text_align = text_align
        if border_style is not None:
            obj.border_style = border_style
        if image_data is not ...:
            obj.image_data = image_data
        session.commit()


def delete_object(object_id: int) -> None:
    with new_session() as session:
        session.execute(delete(VisualReportObject).where(VisualReportObject.object_id == object_id))
        session.commit()
