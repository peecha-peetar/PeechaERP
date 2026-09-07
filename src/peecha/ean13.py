"""تولید/رمزگذاریِ بارکدِ EAN-13 — برایِ بارکدِ خودکارِ کالا و «بارکدِ
ترکیبیِ» متغیرها (ویژگی‌ها/متغیرهایِ کالا، طبقِ درخواستِ صریح).

پیشوندِ «۲۰» بازه‌یِ رزروشده‌یِ GS1 برایِ استفاده‌یِ داخلی/فروشگاهی است
(نیازی به ثبتِ رسمی ندارد) — دقیقاً همان قراردادی که اغلبِ سامانه‌هایِ
فروشگاهی برایِ بارکدهایِ خودتولید استفاده می‌کنند.

هیچ کتابخانه‌یِ بیرونی لازم نیست — رمزگذاری/رمزگشاییِ الگویِ نواری هم
همین‌جا (خالص‌پایتون) پیاده شده تا هم برایِ رسم با QPainter استفاده شود،
هم به‌عنوانِ آزمونِ رفت‌وبرگشت (encode→decode) صحتِ جدول‌ها راستی‌آزمایی شود."""

from __future__ import annotations

_L_CODE = {
    "0": "0001101", "1": "0011001", "2": "0010011", "3": "0111101", "4": "0100011",
    "5": "0110001", "6": "0101111", "7": "0111011", "8": "0110111", "9": "0001011",
}
_G_CODE = {
    "0": "0100111", "1": "0110011", "2": "0011011", "3": "0100001", "4": "0011101",
    "5": "0111001", "6": "0000101", "7": "0010001", "8": "0001001", "9": "0010111",
}
_R_CODE = {
    "0": "1110010", "1": "1100110", "2": "1101100", "3": "1000010", "4": "1011100",
    "5": "1001110", "6": "1010000", "7": "1000100", "8": "1001000", "9": "1110100",
}
_PARITY = {
    "0": "LLLLLL", "1": "LLGLGG", "2": "LLGGLG", "3": "LLGGGL", "4": "LGLLGG",
    "5": "LGGLLG", "6": "LGGGLL", "7": "LGLGLG", "8": "LGLGGL", "9": "LGGLGL",
}
_REVERSE_L = {v: k for k, v in _L_CODE.items()}
_REVERSE_G = {v: k for k, v in _G_CODE.items()}
_REVERSE_R = {v: k for k, v in _R_CODE.items()}
_REVERSE_PARITY = {v: k for k, v in _PARITY.items()}

INTERNAL_USE_PREFIX = "20"


def compute_check_digit(payload12: str) -> str:
    if len(payload12) != 12 or not payload12.isdigit():
        raise ValueError("بارِ محموله برایِ محاسبهٔ رقمِ کنترلی باید دقیقاً ۱۲ رقم باشد.")
    total = 0
    for index, ch in enumerate(payload12):
        digit = int(ch)
        total += digit if index % 2 == 0 else digit * 3
    return str((10 - (total % 10)) % 10)


def generate_main_barcode(item_id: int) -> str:
    """بارکدِ اختصاصیِ خودِ کالایِ اصلی (نه متغیر) -- طبقِ درخواستِ صریح
    («برایِ کالایِ اصلی بارکدِ مجزا»)."""
    payload = f"{INTERNAL_USE_PREFIX}{item_id:010d}"
    return payload + compute_check_digit(payload)


def generate_variant_barcode(parent_item_id: int, variant_sequence: int) -> str:
    """«بارکدِ ترکیبی» — طبقِ درخواستِ صریح: رقم‌هایِ خودِ بارکد از ترکیبِ
    شناسهٔ کالایِ اصلی (۷ رقم) با شمارهٔ ترتیبیِ همین متغیر در میانِ
    متغیرهایِ همان کالا (۳ رقم) ساخته می‌شود — یعنی دو بارکدِ متغیرِ یک
    کالا در ۷ رقمِ میانی مشترک‌اند و فقط در ۳ رقمِ آخر فرق دارند."""
    if not (0 <= variant_sequence <= 999):
        raise ValueError("شمارهٔ ترتیبیِ متغیر باید بینِ ۰ تا ۹۹۹ باشد.")
    payload = f"{INTERNAL_USE_PREFIX}{parent_item_id:07d}{variant_sequence:03d}"
    return payload + compute_check_digit(payload)


def encode(digits13: str) -> str:
    """رشتهٔ ۹۵بیتیِ الگویِ میله‌ایِ EAN-13 ('۰'=فاصلهٔ سفید، '۱'=میله)."""
    if len(digits13) != 13 or not digits13.isdigit():
        raise ValueError("بارکد باید دقیقاً ۱۳ رقم باشد.")
    if compute_check_digit(digits13[:12]) != digits13[12]:
        raise ValueError("رقمِ کنترلیِ بارکد نادرست است.")
    first_digit = digits13[0]
    left_digits = digits13[1:7]
    right_digits = digits13[7:13]
    parity = _PARITY[first_digit]
    left_bits = "".join(_L_CODE[d] if p == "L" else _G_CODE[d] for d, p in zip(left_digits, parity))
    right_bits = "".join(_R_CODE[d] for d in right_digits)
    return "101" + left_bits + "01010" + right_bits + "101"


def decode(bits95: str) -> str:
    """رمزگشاییِ الگویِ نواری به ۱۳ رقمِ اصلی -- برایِ آزمونِ رفت‌وبرگشت."""
    if len(bits95) != 95:
        raise ValueError("طولِ الگویِ بارکد باید ۹۵ باشد.")
    if bits95[:3] != "101" or bits95[45:50] != "01010" or bits95[-3:] != "101":
        raise ValueError("نگهبان‌هایِ بارکد نامعتبرند.")
    left_bits = bits95[3:45]
    right_bits = bits95[50:92]
    left_chunks = [left_bits[i:i + 7] for i in range(0, 42, 7)]
    right_chunks = [right_bits[i:i + 7] for i in range(0, 42, 7)]

    parity_pattern = ""
    left_digits = ""
    for chunk in left_chunks:
        if chunk in _REVERSE_L:
            left_digits += _REVERSE_L[chunk]
            parity_pattern += "L"
        elif chunk in _REVERSE_G:
            left_digits += _REVERSE_G[chunk]
            parity_pattern += "G"
        else:
            raise ValueError("الگویِ نیمهٔ چپِ بارکد قابلِ‌رمزگشایی نیست.")
    first_digit = _REVERSE_PARITY.get(parity_pattern)
    if first_digit is None:
        raise ValueError("الگویِ توازنِ بارکد قابلِ‌شناسایی نیست.")
    right_digits = "".join(_REVERSE_R[chunk] for chunk in right_chunks)
    return first_digit + left_digits + right_digits
