"""R343: ذخیره و خواندن امن فایل اسناد.

- نوع فایل از روی محتوا (magic bytes) سنجیده می‌شود و باید با پسوند هم‌خوان باشد؛ HTML، SVG، اسکریپت و فایل اجرایی
  پذیرفته نمی‌شوند.
- حالت DB (پیش‌فرض): بایت‌ها در doc.files، در همان تراکنش ثبت سند؛ دسکتاپ، سرور API و موبایل بدون پوشهٔ مشترک به
  یک فایل می‌رسند. حالت FS: کلید نسبی تصادفی زیر پوشهٔ تنظیم‌شده؛ نام فایل کاربر هرگز در مسیر نمی‌آید و مسیر نهایی
  باید داخل همان پوشه بماند.
- عکس: اطلاعات مکانی (GPS) بدون فشرده‌سازی دوباره حذف می‌شود (مگر در تنظیمات نگه داشتن آن روشن باشد)، جهت عکس
  دست نمی‌خورد و فقط بندانگشتی با جهت درست ساخته می‌شود."""

from __future__ import annotations

import datetime
import hashlib
import io
import os
import re
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path

from peecha.config import SETTINGS_DIR
from peecha.db.models.documents import DmsFile, DmsSettings

_IMAGE_TYPES = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp", "gif": "image/gif",
                "tif": "image/tiff", "tiff": "image/tiff", "bmp": "image/bmp"}
_OFFICE_ZIP = {"docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "word/"),
               "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xl/"),
               "pptx": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", "ppt/")}
_ODF = {"odt": "application/vnd.oasis.opendocument.text", "ods": "application/vnd.oasis.opendocument.spreadsheet"}
_OLE = {"doc": "application/msword", "xls": "application/vnd.ms-excel", "ppt": "application/vnd.ms-powerpoint"}
_TEXT = {"txt": "text/plain", "csv": "text/csv"}
ALLOWED_EXTENSIONS = sorted(set(_IMAGE_TYPES) | set(_OFFICE_ZIP) | set(_ODF) | set(_OLE) | set(_TEXT) | {"pdf", "rtf"})
_KEY_PATTERN = re.compile(r"^\d+/\d{4}/\d{2}/[0-9a-f]{32}\.[a-z0-9]{1,5}$")
_MAX_IMAGE_PIXELS = 80_000_000
THUMBNAIL_SIZE = 320


@dataclass
class Checked:
    data: bytes
    extension: str
    mime_type: str
    original_name: str
    width: int | None = None
    height: int | None = None
    thumbnail: bytes | None = None


def _clean_name(name: str) -> str:
    """فقط برای نمایش: بدون مسیر و نویسهٔ کنترلی."""
    base = re.split(r"[\\/]", name or "")[-1]
    base = "".join(ch for ch in base if ch.isprintable() and ch not in '<>:"|?*').strip(" .")
    return (base or "file")[:200]


def _sniff(data: bytes, ext: str) -> str | None:
    """نوع واقعی محتوا (mime) اگر با پسوند هم‌خوان باشد، وگرنه None."""
    head = data[:16]
    if ext == "pdf":
        return "application/pdf" if data.startswith(b"%PDF-") else None
    if ext in ("jpg", "jpeg"):
        return "image/jpeg" if head[:3] == b"\xff\xd8\xff" else None
    if ext == "png":
        return "image/png" if head[:8] == b"\x89PNG\r\n\x1a\n" else None
    if ext == "gif":
        return "image/gif" if head[:6] in (b"GIF87a", b"GIF89a") else None
    if ext == "webp":
        return "image/webp" if head[:4] == b"RIFF" and data[8:12] == b"WEBP" else None
    if ext in ("tif", "tiff"):
        return "image/tiff" if head[:4] in (b"II*\x00", b"MM\x00*") else None
    if ext == "bmp":
        return "image/bmp" if head[:2] == b"BM" else None
    if ext == "rtf":
        return "application/rtf" if data.startswith(b"{\\rtf") else None
    if ext in _OLE:
        return _OLE[ext] if head[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" else None
    if ext in _OFFICE_ZIP or ext in _ODF:
        if head[:4] != b"PK\x03\x04":
            return None
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                names = archive.namelist()
                if ext in _ODF:
                    return _ODF[ext] if "mimetype" in names and archive.read("mimetype").decode("ascii", "replace").strip() == _ODF[ext] else None
                mime, folder = _OFFICE_ZIP[ext]
                if "[Content_Types].xml" not in names or not any(n.startswith(folder) for n in names):
                    return None
                if any(n.lower().endswith("vbaproject.bin") for n in names):
                    return None
                return mime
        except (zipfile.BadZipFile, KeyError, OSError):
            return None
    if ext in _TEXT:
        if b"\x00" in data:
            return None
        try:
            data.decode("utf-8-sig")
        except UnicodeDecodeError:
            return None
        return _TEXT[ext]
    return None


def strip_gps(data: bytes) -> bytes:
    """GPS را از بخش EXIF عکس JPEG حذف می‌کند بدون این‌که خود تصویر دوباره فشرده شود."""
    from PIL import Image

    try:
        exif = Image.open(io.BytesIO(data)).getexif()
    except Exception:  # noqa: BLE001 - عکس خراب پیش‌تر رد شده است
        return data
    if 0x8825 not in exif:
        return data
    del exif[0x8825]
    blob = exif.tobytes()
    blob = blob if blob.startswith(b"Exif\x00\x00") else b"Exif\x00\x00" + blob
    pos = 2
    while pos + 4 <= len(data) and data[pos] == 0xFF:
        marker = data[pos + 1]
        if marker in (0xD9, 0xDA):
            break
        length = int.from_bytes(data[pos + 2:pos + 4], "big")
        if marker == 0xE1 and data[pos + 4:pos + 10] == b"Exif\x00\x00":
            if len(blob) + 2 > 0xFFFF:
                return data
            return data[:pos] + b"\xff\xe1" + (len(blob) + 2).to_bytes(2, "big") + blob + data[pos + 2 + length:]
        pos += 2 + length
    return data


def _image_info(data: bytes) -> tuple[int, int, bytes]:
    from PIL import Image, ImageOps

    Image.MAX_IMAGE_PIXELS = _MAX_IMAGE_PIXELS
    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            if width * height > _MAX_IMAGE_PIXELS:
                raise ValueError("ابعاد عکس بیش از حد بزرگ است.")
            image = ImageOps.exif_transpose(image)
            image.thumbnail((THUMBNAIL_SIZE, THUMBNAIL_SIZE))
            if image.mode not in ("RGB", "L"):
                background = Image.new("RGB", image.size, "white")
                background.paste(image.convert("RGBA"), mask=image.convert("RGBA").split()[-1])
                image = background
            out = io.BytesIO()
            image.save(out, "JPEG", quality=80)
            return width, height, out.getvalue()
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001 - هر خطای خواندن عکس یعنی فایل خراب یا ناسازگار
        raise ValueError("عکس خراب است یا خوانده نمی‌شود.") from exc


def check(name: str, data: bytes, max_file_mb: int, keep_gps: bool = False) -> Checked:
    clean = _clean_name(name)
    ext = clean.rsplit(".", 1)[-1].lower() if "." in clean else ""
    if not data:
        raise ValueError(f"فایل «{clean}» خالی است.")
    if len(data) > max_file_mb * 1024 * 1024:
        raise ValueError(f"حجم فایل «{clean}» بیش از {max_file_mb} مگابایت است.")
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"نوع فایل «{clean}» پذیرفته نمی‌شود. نوع‌های مجاز: {'، '.join(ALLOWED_EXTENSIONS)}")
    mime = _sniff(data, ext)
    if mime is None:
        raise ValueError(f"محتوای فایل «{clean}» با نوع آن ({ext}) هم‌خوان نیست یا مجاز نیست.")
    checked = Checked(data=data, extension=ext, mime_type=mime, original_name=clean)
    if ext in _IMAGE_TYPES:
        if mime == "image/jpeg" and not keep_gps:
            checked.data = strip_gps(data)
        checked.width, checked.height, checked.thumbnail = _image_info(checked.data)
    return checked


def storage_root(cfg: DmsSettings) -> Path:
    return Path(cfg.storage_root) if cfg.storage_root else SETTINGS_DIR / "dms"


def _resolve(root: Path, key: str) -> Path:
    if not _KEY_PATTERN.match(key or ""):
        raise ValueError("مسیر فایل نامعتبر است.")
    base = root.resolve()
    path = (base / key).resolve()
    if base not in path.parents:
        raise ValueError("مسیر فایل نامعتبر است.")
    return path


def put(session, company_id: int, user_id: int, checked: Checked, cfg: DmsSettings, written: list[Path],
        text_extraction: bool = True) -> DmsFile:
    """فایل بررسی‌شده را ذخیره و ردیف doc.files را در همان جلسه می‌سازد. مسیر فایل‌های نوشته‌شده در written می‌آید تا
    اگر تراکنش شکست خورد، فراخواننده آن‌ها را پاک کند (فایل یتیم نماند)."""
    digest = hashlib.sha256(checked.data).digest()
    row = DmsFile(company_id=company_id, storage_mode=cfg.storage_mode, sha256=digest, size_bytes=len(checked.data),
                  mime_type=checked.mime_type, extension=checked.extension, original_name=checked.original_name,
                  width=checked.width, height=checked.height, thumbnail=checked.thumbnail, created_by_user_id=user_id,
                  text_status="PENDING" if text_extraction and checked.extension in ("pdf", "docx", "txt", "csv")
                  or (text_extraction and checked.extension in _IMAGE_TYPES and cfg.image_ocr) else "NONE")
    if cfg.storage_mode == "FS":
        today = datetime.date.today()
        key = f"{company_id}/{today:%Y}/{today:%m}/{uuid.uuid4().hex}.{checked.extension}"
        path = _resolve(storage_root(cfg), key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix(path.suffix + ".part")
            temp.write_bytes(checked.data)
            os.replace(temp, path)
        except OSError as exc:
            raise ValueError(f"ذخیرهٔ فایل در پوشهٔ اسناد ممکن نشد: {exc.strerror or exc}") from exc
        written.append(path)
        row.storage_key = key
    else:
        row.content = checked.data
    session.add(row)
    session.flush()
    return row


def read(session, row: DmsFile) -> bytes:
    if row.storage_mode == "DB":
        if row.content is None:
            raise FileNotFoundError("محتوای این فایل در دیتابیس نیست.")
        return row.content
    from peecha.services.dms.common import settings

    path = _resolve(storage_root(settings(session, row.company_id)), row.storage_key or "")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise FileNotFoundError("فایل این سند در پوشهٔ اسناد پیدا نشد؛ ممکن است جابه‌جا یا حذف شده باشد.") from exc
    if hashlib.sha256(data).digest() != bytes(row.sha256):
        raise FileNotFoundError("فایل این سند در پوشهٔ اسناد تغییر کرده و با نسخهٔ ثبت‌شده یکی نیست.")
    return data


def discard(paths: list[Path]) -> None:
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def extract_text(data: bytes, extension: str, image_ocr: bool) -> tuple[str, str]:
    """(وضعیت، متن). فقط ابزار محلی؛ هیچ فایلی به سرویس بیرونی فرستاده نمی‌شود."""
    try:
        if extension == "pdf":
            import pypdfium2 as pdfium

            pdf = pdfium.PdfDocument(data)
            try:
                parts = [pdf[index].get_textpage().get_text_range() for index in range(min(len(pdf), 50))]
            finally:
                pdf.close()
            text_value = "\n".join(parts).strip()
        elif extension == "docx":
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                xml = archive.read("word/document.xml").decode("utf-8", "replace")
            text_value = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", xml)).strip()
        elif extension in _TEXT:
            text_value = data.decode("utf-8-sig", "replace").strip()
        elif extension in _IMAGE_TYPES and image_ocr:
            import pytesseract
            from PIL import Image, ImageOps

            pytesseract.get_tesseract_version()
            with Image.open(io.BytesIO(data)) as image:
                image = ImageOps.exif_transpose(image)
                try:
                    text_value = pytesseract.image_to_string(image, lang="fas+eng")
                except pytesseract.TesseractError:
                    text_value = pytesseract.image_to_string(image, lang="eng")
            text_value = text_value.strip()
        else:
            return "SKIPPED", ""
    except Exception:  # noqa: BLE001 - خطای استخراج متن نباید مانع نگهداری سند شود
        return "FAILED", ""
    return ("DONE" if text_value else "EMPTY"), text_value[:200_000]
