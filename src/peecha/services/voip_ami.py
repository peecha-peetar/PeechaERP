"""کلاینتِ سبکِ AMI (Asterisk Manager Interface) برایِ Click-to-Call --
طبقِ درخواستِ صریحِ کاربر («وصل بشه به سیستمِ سانترال یا وویپ ... با
کلیک کردن روی اون تماس گرفت»). ایزابل بر پایه‌یِ آستریسک است و AMI
یک پروتکلِ متنیِ ساده رویِ TCP است -- نیازی به هیچ کتابخانه‌یِ بیرونی
نیست (برخلافِ REST APIِ خودِ ایزابل که JWT/نسخه‌بندیِ متغیر دارد و کمتر
پایدار است بینِ نسخه‌ها).

الگو: Login -> Originate (داخلیِ خودِ کاربر را زنگ می‌زند؛ با جواب‌دادنِ
اپراتور، سانترال خودش شمارهٔ مشتری را هم می‌گیرد و دو طرف را پل
می‌کند) -> Logoff. طبقِ اصلِ «تیکِ پس‌زمینه‌ای/عملیاتِ بیرونی هیچ‌وقت
نباید برنامه را متوقف کند»، این تابع هیچ‌وقت raise نمی‌کند -- همیشه
یک OriginateResult برمی‌گرداند، حتی در بدترین خطایِ شبکه."""

from __future__ import annotations

import socket
from dataclasses import dataclass

_DEFAULT_TIMEOUT_SECONDS = 8.0


@dataclass
class OriginateResult:
    success: bool
    message: str


def _send_action(sock: socket.socket, fields: dict[str, str]) -> None:
    lines = [f"{key}: {value}" for key, value in fields.items()]
    sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("utf-8"))


def _read_response(sock: socket.socket, timeout: float) -> str:
    sock.settimeout(timeout)
    data = b""
    try:
        while b"\r\n\r\n" not in data:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
    except (TimeoutError, socket.timeout):
        pass
    return data.decode("utf-8", errors="replace")


def originate_call(
    host: str, port: int, ami_username: str, ami_secret: str, dial_context: str, channel_tech_prefix: str,
    agent_extension: str, customer_phone_number: str, timeout: float = _DEFAULT_TIMEOUT_SECONDS,
) -> OriginateResult:
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            try:
                sock.recv(1024)  # بنرِ اتصالِ آستریسک -- محتوایش لازم نیست
            except (TimeoutError, socket.timeout):
                pass

            _send_action(sock, {"Action": "Login", "Username": ami_username, "Secret": ami_secret})
            login_response = _read_response(sock, timeout)
            if "Response: Success" not in login_response:
                return OriginateResult(False, "ورود به سانترال ناموفق بود -- نامِ‌کاربری/رمزِ AMI را در تنظیمات بررسی کنید.")

            channel = f"{channel_tech_prefix}/{agent_extension}"
            _send_action(
                sock,
                {
                    "Action": "Originate",
                    "Channel": channel,
                    "Context": dial_context,
                    "Exten": customer_phone_number,
                    "Priority": "1",
                    "CallerID": agent_extension,
                    "Timeout": "30000",
                    "Async": "true",
                },
            )
            originate_response = _read_response(sock, timeout)

            _send_action(sock, {"Action": "Logoff"})

            if "Response: Success" in originate_response:
                return OriginateResult(True, "درخواستِ تماس برایِ سانترال ارسال شد -- گوشیِ داخلیِ شما زنگ می‌خورد.")
            return OriginateResult(False, f"سانترال درخواستِ تماس را رد کرد: {originate_response.strip()[:200] or 'بدونِ پاسخ'}")
    except (OSError, socket.timeout, TimeoutError) as exc:
        return OriginateResult(False, f"اتصال به سانترال برقرار نشد: {exc}")
