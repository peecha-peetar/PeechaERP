"""پلِ فراخوانیِ موتورِ چاپِ حرفه‌ای (JasperReports 6.21.3، از طریقِ
tools/jasper-runner) از پایتون.

طبقِ تصمیمِ معماری (نتیجه‌یِ Spike): این ماژول هیچ محاسبه‌یِ حسابداری/انبار
انجام نمی‌دهد -- فقط دیتایِ از پیش آماده‌شده (توسطِ reports.py/
inventory_engine.py + numerals.py، دقیقاً همان دیتایی که رویِ صفحه هم نشان
داده می‌شود) را به‌صورتِ JSON به jasper-runner.jar می‌دهد و آن، طبقِ فایلِ
jrxmlِ مشخص‌شده، فقط چیدمان/خروجی (PDF یا Excel) را می‌سازد. JasperReports
درونِ پروسه‌یِ Python بالا نمی‌آید -- هر بار با subprocess یک JVMِ جدا صدا
زده می‌شود.

توابعِ *_at_path رویِ هر مسیرِ jrxmlِ دلخواه کار می‌کنند (از جمله فایل‌هایِ
اختصاصیِ هر شرکت که در peecha.services.report_templates مدیریت می‌شوند)؛
توابعِ نام‌دار (render_report/template_path/open_template_for_editing) فقط
برایِ قالب‌هایِ پایه‌ی این ریپازیتوری (templates/) هستند و رویِ همان توابع
سوار شده‌اند."""

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_RUNNER_JAR = _REPO_ROOT / "tools" / "jasper-runner" / "target" / "jasper-runner.jar"
_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

BUILD_INSTRUCTIONS = "طبقِ tools/jasper-runner/README.md آن را build کنید."

JAVA_DOWNLOAD_URL = "https://adoptium.net/temurin/releases/?version=17"
JAVA_MISSING_MESSAGE = (
    "برایِ چاپِ حرفه‌ای، جاوا (JRE ۱۷ یا بالاتر) روی این سیستم نصب نیست.\n\n"
    f"از این آدرس (نسخه‌یِ ۱۷، Windows x64، پکیجِ JRE، فایلِ .msi) دانلود و نصب کنید:\n{JAVA_DOWNLOAD_URL}\n\n"
    "بعد از نصب، برنامه را ببندید و دوباره باز کنید."
)


def _find_java() -> str | None:
    """مسیرِ اجراییِ جاوا را پیدا می‌کند -- اول در PATH، بعد JAVA_HOME، و در
    نبودِ این دو (مثلاً وقتی نصب‌کننده PATH را تازه تنظیم کرده ولی برنامه
    هنوز با محیطِ قدیمی باز است) در پوشه‌هایِ رایجِ نصبِ JRE/JDK جست‌وجو
    می‌کند."""
    found = shutil.which("java")
    if found:
        return found

    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        candidate = Path(java_home) / "bin" / ("java.exe" if sys.platform == "win32" else "java")
        if candidate.exists():
            return str(candidate)

    if sys.platform == "win32":
        patterns = [
            r"C:\Program Files\Eclipse Adoptium\*\bin\java.exe",
            r"C:\Program Files\Java\*\bin\java.exe",
            r"C:\Program Files\Amazon Corretto\*\bin\java.exe",
            r"C:\Program Files\Zulu\*\bin\java.exe",
            r"C:\Program Files (x86)\Eclipse Adoptium\*\bin\java.exe",
            r"C:\Program Files (x86)\Java\*\bin\java.exe",
        ]
    elif sys.platform == "darwin":
        patterns = ["/Library/Java/JavaVirtualMachines/*/Contents/Home/bin/java"]
    else:
        patterns = ["/usr/lib/jvm/*/bin/java"]

    for pattern in patterns:
        matches = sorted(glob.glob(pattern), reverse=True)
        if matches:
            return matches[0]
    return None

_STUDIO_ENV_VAR = "PEECHA_JASPER_STUDIO_PATH"


class JasperNotAvailableError(RuntimeError):
    """موتورِ چاپِ حرفه‌ای هنوز build نشده یا Java نصب نیست -- پیامِ راهنما
    به‌جایِ کرشِ نامفهوم."""


def is_available() -> bool:
    return _RUNNER_JAR.exists()


def template_path(template_name: str) -> Path:
    path = _TEMPLATES_DIR / template_name
    if not path.exists():
        raise FileNotFoundError(f"قالبِ گزارش یافت نشد: {path}")
    return path


def open_path_for_editing(jrxml_path: Path | str) -> bool:
    """فایلِ jrxml را برایِ ویرایش در Jaspersoft Studio باز می‌کند.

    ReportRunner همیشه از رویِ همینِ فایلِ روی دیسک -- تازه در همان لحظه --
    کامپایل می‌کند (نه از رویِ نسخه‌یِ از پیش‌کامپایل‌شده)، پس ذخیره‌کردن در
    Studio بدونِ هیچ مرحله‌یِ Build جداگانه‌ای بلافاصله در اجرایِ بعدیِ
    گزارش اثر می‌کند.

    اگر مسیرِ اجراییِ Studio با متغیرِ محیطیِ PEECHA_JASPER_STUDIO_PATH
    تنظیم شده باشد از همان استفاده می‌شود؛ وگرنه تلاش می‌شود از طریقِ
    اتصالِ پیش‌فرضِ سیستم‌عامل با پسوندِ jrxml باز شود (نصب‌کننده‌یِ Studio
    این اتصال را معمولاً خودش ثبت می‌کند). خروجی: آیا بازکردن موفق بود یا نه.
    """
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices

    path = Path(jrxml_path)
    if not path.exists():
        raise FileNotFoundError(f"قالبِ گزارش یافت نشد: {path}")
    studio_exe = os.environ.get(_STUDIO_ENV_VAR)
    if studio_exe and Path(studio_exe).exists():
        subprocess.Popen([studio_exe, str(path)])
        return True
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def open_template_for_editing(template_name: str) -> bool:
    return open_path_for_editing(template_path(template_name))


def render_report_at_path(
    jrxml_path: Path | str,
    rows: list[dict],
    params: dict,
    output_path: str,
    output_format: str = "pdf",
) -> None:
    """یک گزارشِ حرفه‌ای می‌سازد و در output_path ذخیره می‌کند.

    rows: لیستی از دیکشنری -- کلیدها باید دقیقاً با نامِ field هایِ همان
    قالب (jrxml) یکی باشند؛ مقادیر باید از قبل با numerals.format_money/
    format_jalali_date/to_persian_digits آماده‌شده باشند (JasperReports این‌جا
    فقط چیدمان می‌کند، نه محاسبه یا فرمت‌دهیِ عدد/تاریخ).
    params: نگاشتِ رشته‌ای برایِ پارامترهایِ گزارش (عنوان، نامِ شرکت، ...).
    output_format: "pdf" یا "xlsx".
    """
    if not _RUNNER_JAR.exists():
        raise JasperNotAvailableError(f"موتورِ چاپِ حرفه‌ای هنوز آماده نیست — {BUILD_INSTRUCTIONS}")

    java_exe = _find_java()
    if java_exe is None:
        raise JasperNotAvailableError(JAVA_MISSING_MESSAGE)

    jrxml_path = Path(jrxml_path)
    if not jrxml_path.exists():
        raise FileNotFoundError(f"قالبِ گزارش یافت نشد: {jrxml_path}")

    with tempfile.TemporaryDirectory(prefix="peecha_jasper_") as tmp_dir:
        rows_path = os.path.join(tmp_dir, "rows.json")
        params_path = os.path.join(tmp_dir, "params.json")
        with open(rows_path, "w", encoding="utf-8") as f:
            json.dump({"rows": rows}, f, ensure_ascii=False)
        with open(params_path, "w", encoding="utf-8") as f:
            json.dump(params, f, ensure_ascii=False)

        try:
            result = subprocess.run(
                [java_exe, "-jar", str(_RUNNER_JAR), str(jrxml_path), rows_path, params_path, str(output_path), output_format],
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as exc:
            raise JasperNotAvailableError(JAVA_MISSING_MESSAGE) from exc

        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(f"تولیدِ گزارشِ حرفه‌ای ناموفق بود:\n{detail}")


def render_report(
    template_name: str,
    rows: list[dict],
    params: dict,
    output_path: str,
    output_format: str = "pdf",
) -> None:
    render_report_at_path(template_path(template_name), rows, params, output_path, output_format)
