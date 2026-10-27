"""تنظیمات لایهٔ API. کلید امضای JWT از متغیر محیطی PEECHA_API_JWT_SECRET خوانده می‌شود.
R344: اگر ست نشده باشد، یک‌بار ساخته و در پوشهٔ تنظیمات (api_jwt.key، فقط‌خواندنی برای مالک) نگه داشته
می‌شود تا با راه‌اندازی دوباره یا چند worker، ورود گوشی‌ها باطل نشود."""

from __future__ import annotations

import os
import secrets

from peecha.config import SETTINGS_DIR

JWT_ALGORITHM = "HS256"


def _jwt_secret() -> str:
    from_env = os.environ.get("PEECHA_API_JWT_SECRET")
    if from_env:
        return from_env
    path = SETTINGS_DIR / "api_jwt.key"
    try:
        if path.exists() and path.read_text(encoding="ascii").strip():
            return path.read_text(encoding="ascii").strip()
        SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
        key = secrets.token_hex(32)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as handle:
            handle.write(key)
        return key
    except FileExistsError:  # worker دیگری هم‌زمان ساخت
        return path.read_text(encoding="ascii").strip()
    except OSError:
        return secrets.token_hex(32)


JWT_SECRET = _jwt_secret()
ACCESS_TOKEN_MINUTES = int(os.environ.get("PEECHA_API_ACCESS_TOKEN_MINUTES", "20"))
REFRESH_TOKEN_DAYS = int(os.environ.get("PEECHA_API_REFRESH_TOKEN_DAYS", "90"))
