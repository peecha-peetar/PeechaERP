"""تنظیماتِ لایهٔ API. کلیدِ امضایِ JWT باید در محیطِ Production حتماً
با متغیرِ محیطیِ PEECHA_API_JWT_SECRET ست شود -- اگر ست نشود، یک کلیدِ
تصادفیِ موقت (فقط برایِ توسعه/تست) در هر بارِ بالاآمدنِ سرویس ساخته
می‌شود، یعنی توکن‌هایِ صادرشده بعدِ ری‌استارتِ سرویس دیگر معتبر نیستند."""

from __future__ import annotations

import os
import secrets

JWT_ALGORITHM = "HS256"
JWT_SECRET = os.environ.get("PEECHA_API_JWT_SECRET") or secrets.token_hex(32)
ACCESS_TOKEN_MINUTES = int(os.environ.get("PEECHA_API_ACCESS_TOKEN_MINUTES", "20"))
REFRESH_TOKEN_DAYS = int(os.environ.get("PEECHA_API_REFRESH_TOKEN_DAYS", "90"))
