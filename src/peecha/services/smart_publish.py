"""Smart Publish -- طبقِ بازخوردِ صریحِ کاربر («امکاناتِ حیاتیِ
PeechaSync -- پردازشِ خودکارِ تصویرِ محصول»): واترمارک + حکِ کدِ/نامِ
کالا + فشرده‌سازیِ WebP، به‌صورتِ یک عملیاتِ دستیِ «پردازشِ هوشمند» رویِ
هر عکسِ مرکزِ رسانه (نه قلاب‌شده به هر مسیرِ آپلودِ دیگر در برنامه، تا
جریان‌هایِ موجود دست‌نخورده بمانند)."""

from __future__ import annotations

import decimal
import io
import shutil
import uuid
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select

from peecha.config import SETTINGS_DIR
from peecha.db.base import new_session
from peecha.db.models.commercial import SmartPublishSettings

_WATERMARK_DIR = SETTINGS_DIR / "smart_publish"
_POSITION_MARGIN = 12


def get_settings(company_id: int) -> SmartPublishSettings:
    with new_session() as session:
        row = session.get(SmartPublishSettings, company_id)
        if row is None:
            row = SmartPublishSettings(company_id=company_id)
            session.add(row)
            session.commit()
        session.refresh(row)
        session.expunge(row)
        return row


def set_settings(
    company_id: int, *, watermark_opacity: decimal.Decimal | None = None, watermark_scale: decimal.Decimal | None = None,
    watermark_position: str | None = None, stamp_text_enabled: bool | None = None,
    stamp_text_source: str | None = None, webp_quality: int | None = None,
) -> None:
    if watermark_position is not None and watermark_position not in ("bottom-right", "bottom-left", "top-right", "top-left", "center"):
        raise ValueError("موقعیتِ واترمارک نامعتبر است.")
    if stamp_text_source is not None and stamp_text_source not in ("item_code", "item_name"):
        raise ValueError("منبعِ متنِ حک‌شده نامعتبر است.")
    with new_session() as session:
        row = session.get(SmartPublishSettings, company_id)
        if row is None:
            row = SmartPublishSettings(company_id=company_id)
            session.add(row)
        if watermark_opacity is not None:
            row.watermark_opacity = watermark_opacity
        if watermark_scale is not None:
            row.watermark_scale = watermark_scale
        if watermark_position is not None:
            row.watermark_position = watermark_position
        if stamp_text_enabled is not None:
            row.stamp_text_enabled = stamp_text_enabled
        if stamp_text_source is not None:
            row.stamp_text_source = stamp_text_source
        if webp_quality is not None:
            row.webp_quality = webp_quality
        session.commit()


def set_watermark_image(company_id: int, file_path: str) -> None:
    source = Path(file_path)
    if not source.is_file():
        raise ValueError("فایلِ واترمارک یافت نشد.")
    try:
        _WATERMARK_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ValueError(f"پوشهٔ Smart Publish («{_WATERMARK_DIR}») در دسترس نیست: {exc}") from exc
    destination = _WATERMARK_DIR / f"watermark_{company_id}_{uuid.uuid4().hex}{source.suffix}"
    shutil.copyfile(source, destination)
    with new_session() as session:
        row = session.get(SmartPublishSettings, company_id)
        if row is None:
            row = SmartPublishSettings(company_id=company_id)
            session.add(row)
        row.watermark_storage_key = str(destination)
        session.commit()


def _apply_watermark(base: Image.Image, settings: SmartPublishSettings) -> Image.Image:
    if not settings.watermark_storage_key or not Path(settings.watermark_storage_key).is_file():
        return base
    watermark = Image.open(settings.watermark_storage_key).convert("RGBA")
    scale = float(settings.watermark_scale)
    target_width = max(1, int(base.width * scale))
    ratio = target_width / watermark.width
    watermark = watermark.resize((target_width, max(1, int(watermark.height * ratio))))

    opacity = max(0.0, min(1.0, float(settings.watermark_opacity)))
    if opacity < 1.0:
        alpha = watermark.split()[3].point(lambda a: int(a * opacity))
        watermark.putalpha(alpha)

    base = base.convert("RGBA")
    positions = {
        "bottom-right": (base.width - watermark.width - _POSITION_MARGIN, base.height - watermark.height - _POSITION_MARGIN),
        "bottom-left": (_POSITION_MARGIN, base.height - watermark.height - _POSITION_MARGIN),
        "top-right": (base.width - watermark.width - _POSITION_MARGIN, _POSITION_MARGIN),
        "top-left": (_POSITION_MARGIN, _POSITION_MARGIN),
        "center": ((base.width - watermark.width) // 2, (base.height - watermark.height) // 2),
    }
    xy = positions.get(settings.watermark_position, positions["bottom-right"])
    base.alpha_composite(watermark, dest=xy)
    return base


def _apply_text_stamp(base: Image.Image, text: str) -> Image.Image:
    base = base.convert("RGBA")
    draw = ImageDraw.Draw(base)
    font_size = max(12, base.width // 25)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", font_size)
    except OSError:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width, text_height = bbox[2] - bbox[0], bbox[3] - bbox[1]
    xy = (base.width - text_width - _POSITION_MARGIN, base.height - text_height - _POSITION_MARGIN)
    draw.rectangle(
        [xy[0] - 6, xy[1] - 4, xy[0] + text_width + 6, xy[1] + text_height + 4],
        fill=(0, 0, 0, 140),
    )
    draw.text(xy, text, font=font, fill=(255, 255, 255, 230))
    return base


def process_image_file(company_id: int, source_path: str, *, item_code: str | None = None, item_name: str | None = None) -> bytes:
    """پردازشِ یک عکس طبقِ تنظیماتِ Smart Publishِ شرکت -- ترتیب: واترمارک
    ← حکِ متن ← فشرده‌سازیِ WebP. برمی‌گرداند: بایت‌هایِ عکسِ نهاییِ WebP."""
    settings = get_settings(company_id)
    image = Image.open(source_path)
    image = _apply_watermark(image, settings)
    if settings.stamp_text_enabled:
        text = item_code if settings.stamp_text_source == "item_code" else item_name
        if text:
            image = _apply_text_stamp(image, text)
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="WEBP", quality=settings.webp_quality)
    return buffer.getvalue()
