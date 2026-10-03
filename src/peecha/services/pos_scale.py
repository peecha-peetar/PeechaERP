"""ترازو (وزن‌کِشی) برایِ فروشِ حضوری -- طبقِ درخواستِ صریحِ کاربر:

۱) ترازویِ آفلاین: بارکدِ چاپ‌شده‌یِ ترازو (بدونِ نیاز به هیچ ارتباطِ
   زنده‌یِ سخت‌افزاری) با یک اسکنرِ معمولی خوانده می‌شود -- این ماژول
   همان بارکد را رمزگشایی می‌کند (پیشوند + کدِ کالا + وزن، هرکدام با
   تعدادِ رقمِ قابلِ‌تنظیم). کاملاً پیاده‌سازی‌شده است.

۲) ترازویِ آنلاین: خواندنِ واقعیِ لیستِ اقلامِ ذخیره‌شده در حافظه‌یِ
   ترازو از طریقِ یک بارکد/RFIDِ کلی -- طبقِ توافقِ صریح (چون پروتکلِ
   دقیقِ ارتباطیِ دستگاه هنوز مشخص نیست)، فقط چارچوبِ اولیه/تنظیماتی
   این‌جا آماده است، هم‌الگو با voip_ami.py: خودِ خواندنِ واقعی هنوز
   پیاده نشده و به‌صراحت با ScaleNotConfiguredError اعلام می‌شود، نه
   شکستِ خاموش/گنگ."""

from __future__ import annotations

import decimal
from dataclasses import dataclass

from peecha.db.models.commercial import PosSettings


class ScaleNotConfiguredError(Exception):
    """ترازویِ آنلاین فعال نیست، یا پروتکلِ ارتباطِ واقعی با این دستگاه
    هنوز پیاده‌سازی نشده است."""


@dataclass
class ParsedWeightBarcode:
    item_code: str
    weight: decimal.Decimal


def parse_weight_barcode(settings: PosSettings | None, barcode: str) -> ParsedWeightBarcode | None:
    """اگر بارکدِ اسکن‌شده دقیقاً با فرمتِ پیکربندی‌شده (پیشوند + کدِ
    کالا + وزن) مطابقت داشت، کدِ کالا و وزنِ رمزگشایی‌شده را برمی‌گرداند؛
    وگرنه None -- یعنی این یک بارکدِ وزنی نیست و باید مثلِ همیشه (بارکدِ
    معمولیِ کالا) در نظر گرفته شود."""
    if settings is None or not settings.weight_barcode_enabled:
        return None
    digits = (barcode or "").strip()
    prefix = settings.weight_barcode_prefix or ""
    total_len = len(prefix) + settings.weight_barcode_item_code_digits + settings.weight_barcode_weight_digits
    if len(digits) != total_len or not digits.isdigit() or not prefix:
        return None
    if not digits.startswith(prefix):
        return None
    code_start = len(prefix)
    code_end = code_start + settings.weight_barcode_item_code_digits
    item_code = digits[code_start:code_end]
    weight_end = code_end + settings.weight_barcode_weight_digits
    weight_raw = digits[code_end:weight_end]
    weight = decimal.Decimal(weight_raw) / (decimal.Decimal(10) ** settings.weight_barcode_weight_decimals)
    return ParsedWeightBarcode(item_code=item_code, weight=weight)


def read_online_scale_batch(settings: PosSettings | None, batch_code: str) -> list[dict]:
    """طبقِ توافقِ صریحِ کاربر («فعلاً فقط چارچوبِ اولیه/تنظیماتی»): این
    تابع هنوز به هیچ ترازوی واقعی وصل نمی‌شود -- وقتی پروتکلِ دقیقِ
    ارتباطیِ دستگاه (سریال/RS232، TCP، یا فایلِ مشترکِ روی شبکه) مشخص
    شد، باید هم‌الگو با voip_ami.originate_call واقعاً به دستگاه وصل
    شود و لیستِ اقلامِ همان batch_code را برگرداند (هر آیتم: کدِ کالا +
    وزن)."""
    if settings is None or not settings.scale_online_enabled:
        raise ScaleNotConfiguredError("ترازویِ آنلاین در تنظیماتِ فروشِ حضوری فعال نشده است.")
    raise ScaleNotConfiguredError(
        "پروتکلِ ارتباطِ واقعی با این مدلِ ترازو هنوز پیاده‌سازی نشده — برایِ تکمیلِ این بخش، "
        "مشخصاتِ دقیقِ پروتکلِ ارتباطیِ دستگاه (نوعِ اتصال، آدرس/پورت، و فرمتِ داده) لازم است."
    )
