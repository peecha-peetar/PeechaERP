"""R358: فاصلهٔ جاده‌ای برای مسیر پخش از سرویس «ماتریس فاصله»ی نشان.

درخواست: GET {آدرس سرویس}/v1/distance-matrix?type=car&origins=عرض,طول|...&destinations=عرض,طول|... با سرآیند Api-Key؛
پاسخ: status و rows[i].elements[j].distance.value (متر). هر درخواست حداکثر ۱۰ مبدأ در ۱۰ مقصد است. هر خطا (شبکه، کلید،
سهمیه، پاسخ نامعتبر) RoadDistanceError می‌دهد، در تنظیمات ثبت می‌شود و مسیر پخش با فاصلهٔ خط مستقیم ادامه پیدا می‌کند.
این اتصال با سرور واقعی نشان آزموده نشده است؛ قالب درخواست و پاسخ از کتابخانهٔ عمومی پایتون نشان برداشته شده است.
"""

from __future__ import annotations

import datetime
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from peecha.db.base import new_session
from peecha.db.models.commercial import RoadRoutingSettings
from peecha.services import ecommerce_credentials

DEFAULT_API_URL = "https://api.neshan.org"
PROVIDERS = {"NONE": "خط مستقیم (بدون سرویس نقشه)", "NESHAN": "نشان (فاصلهٔ جاده‌ای)"}
VEHICLE_TYPES = {"car": "خودرو", "motorcycle": "موتورسیکلت"}
_CHUNK = 10
_TIMEOUT = 15
_CACHE_SECONDS, _RETRY_SECONDS = 6 * 3600, 600
_cache: dict[tuple, tuple[float, list]] = {}  # (شرکت، نقاط) ← (زمان، ماتریس)
_failed: dict[int, tuple[float, str]] = {}  # شرکت ← (زمان، خطا): تا چند دقیقه دوباره منتظر شبکهٔ قطع نمی‌مانیم


class RoadDistanceError(ValueError):
    pass


@dataclass
class Settings:
    provider_code: str
    api_url: str
    has_key: bool
    vehicle_type: str
    last_error: str | None
    last_error_at: datetime.datetime | None


def get_settings(company_id: int) -> Settings:
    with new_session() as session:
        r = session.get(RoadRoutingSettings, company_id)
        if r is None:
            return Settings("NONE", DEFAULT_API_URL, False, "car", None, None)
        return Settings(r.provider_code, r.api_url or DEFAULT_API_URL, bool(r.api_key_encrypted), r.vehicle_type, r.last_error,
                        r.last_error_at)


def save_settings(company_id: int, user_id: int | None, provider_code: str, api_key: str | None = None,
                  api_url: str | None = None, vehicle_type: str = "car") -> None:
    """api_key خالی یعنی کلید قبلی می‌ماند."""
    if provider_code not in PROVIDERS:
        raise ValueError("سرویس مسیریابی نامعتبر است.")
    if vehicle_type not in VEHICLE_TYPES:
        raise ValueError("نوع وسیلهٔ نقلیه نامعتبر است.")
    url = (api_url or "").strip().rstrip("/") or DEFAULT_API_URL
    if not url.startswith("https://"):
        raise ValueError("آدرس سرویس باید با https:// شروع شود.")
    key = (api_key or "").strip()
    with new_session() as session:
        row = session.get(RoadRoutingSettings, company_id) or RoadRoutingSettings(company_id=company_id)
        if key:
            row.api_key_encrypted = ecommerce_credentials.encrypt_credentials({"api_key": key})
        if provider_code == "NESHAN" and not row.api_key_encrypted:
            raise ValueError("برای نشان، کلید API (از پنل توسعه‌دهندگان نشان) را وارد کنید.")
        row.provider_code, row.api_url, row.vehicle_type, row.updated_by_user_id = provider_code, url, vehicle_type, user_id
        row.updated_at = datetime.datetime.now(datetime.timezone.utc)
        session.add(row)
        session.commit()
    clear_cache(company_id)


def clear_cache(company_id: int | None = None) -> None:
    for key in [k for k in _cache if company_id is None or k[0] == company_id]:
        del _cache[key]
    for key in [k for k in _failed if company_id is None or k == company_id]:
        del _failed[key]


def _record_error(company_id: int, message: str | None) -> None:
    with new_session() as session:
        row = session.get(RoadRoutingSettings, company_id)
        if row is not None:
            row.last_error = message[:1000] if message else None
            row.last_error_at = datetime.datetime.now(datetime.timezone.utc) if message else None
            session.commit()


def urllib_transport(url: str, headers: dict[str, str]) -> tuple[int, str]:
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:  # noqa: S310 (آدرس https تنظیم‌شده)
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RoadDistanceError(f"اتصال به سرویس نقشه برقرار نشد: {exc}") from exc


class NeshanClient:
    def __init__(self, api_key: str, api_url: str = DEFAULT_API_URL, vehicle_type: str = "car", transport=None) -> None:
        self.api_key, self.api_url, self.vehicle_type = api_key, api_url.rstrip("/"), vehicle_type
        self.transport = transport or urllib_transport

    @staticmethod
    def _points(points: list[tuple[float, float]]) -> str:
        return "|".join(f"{lat:.6f},{lon:.6f}" for lat, lon in points)

    def _block(self, origins, destinations) -> list[list[float | None]]:
        query = urllib.parse.urlencode({"type": self.vehicle_type, "origins": self._points(origins),
                                        "destinations": self._points(destinations)}, safe=",|")
        status, body = self.transport(f"{self.api_url}/v1/distance-matrix?{query}", {"Api-Key": self.api_key})
        try:
            data = json.loads(body or "{}")
        except ValueError as exc:
            raise RoadDistanceError(f"پاسخ سرویس نقشه خوانا نیست (کد {status}).") from exc
        if status != 200 or str(data.get("status", "")).lower() != "ok":
            raise RoadDistanceError(f"سرویس نقشه خطا داد (کد {status}): {data.get('message') or data.get('status') or body[:200]}")
        rows = data.get("rows") or []
        if len(rows) != len(origins):
            raise RoadDistanceError("تعداد ردیف‌های پاسخ سرویس نقشه با مبدأها یکی نیست.")
        out = []
        for row in rows:
            elements = row.get("elements") or []
            if len(elements) != len(destinations):
                raise RoadDistanceError("تعداد ستون‌های پاسخ سرویس نقشه با مقصدها یکی نیست.")
            out.append([(e["distance"]["value"] / 1000.0) if str(e.get("status", "ok")).lower() == "ok" and e.get("distance")
                        else None for e in elements])
        return out

    def matrix(self, origins: list[tuple[float, float]], destinations: list[tuple[float, float]]) -> list[list[float | None]]:
        """کیلومتر جاده‌ای هر مبدأ تا هر مقصد؛ None یعنی مسیری پیدا نشد."""
        out = [[None] * len(destinations) for _ in origins]
        for i in range(0, len(origins), _CHUNK):
            for j in range(0, len(destinations), _CHUNK):
                block = self._block(origins[i:i + _CHUNK], destinations[j:j + _CHUNK])
                for di, row in enumerate(block):
                    out[i + di][j:j + len(row)] = row
        return out


def is_on(company_id: int) -> bool:
    return get_settings(company_id).provider_code != "NONE"


def client_for(company_id: int, transport=None) -> NeshanClient | None:
    with new_session() as session:
        r = session.get(RoadRoutingSettings, company_id)
        if r is None or r.provider_code != "NESHAN" or not r.api_key_encrypted:
            return None
        key = ecommerce_credentials.decrypt_credentials(r.api_key_encrypted).get("api_key")
        return NeshanClient(key, r.api_url or DEFAULT_API_URL, r.vehicle_type, transport) if key else None


def road_matrix(company_id: int, points: list[tuple[float, float]], transport=None) -> list[list[float | None]] | None:
    """ماتریس کیلومتر جاده‌ای بین همهٔ نقاط؛ None اگر سرویس خاموش است. خطا ثبت و دوباره پرتاب می‌شود."""
    client = client_for(company_id, transport)
    if client is None:
        return None
    now = time.monotonic()
    key = (company_id, tuple(points))
    if key in _cache and now - _cache[key][0] < _CACHE_SECONDS:
        return _cache[key][1]
    if company_id in _failed and now - _failed[company_id][0] < _RETRY_SECONDS:
        raise RoadDistanceError(_failed[company_id][1])
    try:
        result = client.matrix(points, points)
    except RoadDistanceError as exc:
        _failed[company_id] = (now, str(exc))
        _record_error(company_id, str(exc))
        raise
    except (KeyError, TypeError, ValueError) as exc:
        message = f"پاسخ نامعتبر سرویس نقشه: {exc}"
        _failed[company_id] = (now, message)
        _record_error(company_id, message)
        raise RoadDistanceError(message) from exc
    _cache[key] = (now, result)
    _record_error(company_id, None)
    return result


def test_connection(company_id: int, transport=None) -> float:
    """یک فاصلهٔ نمونه (میدان آزادی تا میدان ونک تهران)؛ کیلومتر برمی‌گرداند یا RoadDistanceError."""
    client = client_for(company_id, transport)
    if client is None:
        raise RoadDistanceError("سرویس نشان روشن نیست یا کلید API ندارد.")
    try:
        km = client.matrix([(35.699739, 51.338097)], [(35.757450, 51.409897)])[0][0]
    except RoadDistanceError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise RoadDistanceError(f"پاسخ نامعتبر سرویس نقشه: {exc}") from exc
    if km is None:
        raise RoadDistanceError("سرویس نقشه برای مسیر نمونه فاصله‌ای برنگرداند.")
    return km
