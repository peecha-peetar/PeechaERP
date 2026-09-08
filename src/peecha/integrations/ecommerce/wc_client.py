"""لایه‌ی ارتباطِ خامِ HTTP با ووکامرس (WooCommerce REST API v3).

طبقِ بررسیِ برنامه‌یِ PeechaSync (که این ماژول از آن الهام گرفته)، این
لایه عمداً هیچ دسترسیِ مستقیمی به دیتابیسِ ERP ندارد -- فقط sku/نام/قیمت/
موجودی/دسته را به‌عنوانِ پارامترِ ساده می‌گیرد و پاسخِ خامِ سایت را
برمی‌گرداند. تصمیم‌گیری (کدام کالا، کدام دسته، کدام قیمت) در
services/commercial_ecommerce.py انجام می‌شود -- همان‌جا که به
دیتابیسِ Postgresِ خودِ ERP دسترسی دارد.

اعتبارسنجی/تست با کتابخانه‌یِ رسمیِ PyPI به‌نامِ ``woocommerce`` -- که
دقیقاً همان بسته‌ای است که PeechaSync هم استفاده می‌کرد (احرازِ هویتِ
Basic Auth با Consumer Key/Secret روی HTTPS)."""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass

import requests
from woocommerce import API

from peecha.integrations.ecommerce import retry

_DEFAULT_TIMEOUT = 30


class StoreAPIError(RuntimeError):
    """خطایِ ارتباط با فروشگاه -- پیامِ HTTP یا شبکه به فارسی ترجمه می‌شود."""


def normalize_store_url(url: str) -> str:
    cleaned = (url or "").strip().rstrip("/")
    if "/wp-json" in cleaned:
        cleaned = cleaned.split("/wp-json")[0].rstrip("/")
    return cleaned


def build_wcapi(store_url: str, consumer_key: str, consumer_secret: str, timeout: int = _DEFAULT_TIMEOUT) -> API:
    return API(
        url=normalize_store_url(store_url),
        consumer_key=(consumer_key or "").strip(),
        consumer_secret=(consumer_secret or "").strip(),
        version="wc/v3",
        timeout=timeout,
        query_string_auth=False,
    )


def _raise_for_status(resp, label: str) -> dict:
    try:
        data = resp.json()
    except ValueError:
        data = None
    if resp.status_code >= 400:
        message = (data or {}).get("message") if isinstance(data, dict) else None
        raise StoreAPIError(f"{label} -- خطایِ سایت (HTTP {resp.status_code}): {message or resp.text[:300]}")
    return data if isinstance(data, dict) else {}


def check_connection(wcapi: API) -> tuple[bool, str]:
    try:
        resp = retry.call_with_retry(wcapi.get, "system_status")
    except Exception as exc:  # noqa: BLE001 -- خطاهایِ requests/شبکه متنوع‌اند
        return False, f"اتصال به فروشگاه برقرار نشد: {exc}"
    if resp.status_code >= 400:
        return False, f"فروشگاه با خطایِ HTTP {resp.status_code} پاسخ داد -- کلیدِ API را بررسی کنید."
    return True, "اتصال به ووکامرس برقرار است."


def find_product_by_sku(wcapi: API, sku: str) -> dict | None:
    resp = retry.call_with_retry(wcapi.get, "products", params={"sku": sku})
    if resp.status_code >= 400:
        _raise_for_status(resp, f"جست‌وجویِ محصولِ SKU={sku}")
    rows = resp.json()
    if not isinstance(rows, list) or not rows:
        return None
    return rows[0]


def upsert_product(wcapi: API, sku: str, payload: dict) -> dict:
    """محصولِ SKU مشخص را اگر از قبل در فروشگاه هست به‌روزرسانی می‌کند،
    وگرنه می‌سازد. برمی‌گرداند: دیکشنریِ خامِ محصولِ ذخیره‌شده (شاملِ id)."""
    existing = find_product_by_sku(wcapi, sku)
    body = dict(payload)
    body["sku"] = sku
    if existing:
        resp = retry.call_with_retry(wcapi.put, f"products/{existing['id']}", body)
        return _raise_for_status(resp, f"به‌روزرسانیِ محصولِ {sku}")
    resp = retry.call_with_retry(wcapi.post, "products", body)
    return _raise_for_status(resp, f"ایجادِ محصولِ {sku}")


def find_category_by_name(wcapi: API, name: str, parent_external_id: int | None) -> dict | None:
    resp = retry.call_with_retry(wcapi.get, "products/categories", params={"search": name, "per_page": 100})
    if resp.status_code >= 400:
        _raise_for_status(resp, f"جست‌وجویِ دستهٔ «{name}»")
    rows = resp.json()
    if not isinstance(rows, list):
        return None
    parent_id = int(parent_external_id) if parent_external_id else 0
    for row in rows:
        if str(row.get("name") or "").strip() == name.strip() and int(row.get("parent") or 0) == parent_id:
            return row
    return None


def create_category(wcapi: API, name: str, parent_external_id: int | None) -> dict:
    body = {"name": name}
    if parent_external_id:
        body["parent"] = int(parent_external_id)
    resp = retry.call_with_retry(wcapi.post, "products/categories", body)
    return _raise_for_status(resp, f"ایجادِ دستهٔ «{name}»")


@dataclass
class ExternalOrderRow:
    external_order_id: str
    external_customer_id: str
    status: str
    lines: list[dict]  # [{"sku": ..., "quantity": ...}]


def fetch_new_orders(wcapi: API, *, status: str = "processing", per_page: int = 50) -> list[ExternalOrderRow]:
    """سفارش‌هایِ فروشگاه با وضعیتِ مشخص (پیش‌فرض «در حالِ پردازش» --
    یعنی پرداخت‌شده) -- فیلترِ «قبلاً واردنشده» بر اساسِ لاگِ سینک در
    خودِ ERP انجام می‌شود، نه این‌جا."""
    resp = retry.call_with_retry(wcapi.get, "orders", params={"status": status, "per_page": per_page})
    if resp.status_code >= 400:
        _raise_for_status(resp, "دریافتِ سفارش‌هایِ تازه")
    rows = resp.json()
    if not isinstance(rows, list):
        return []
    result = []
    for row in rows:
        lines = [
            {"sku": str(li.get("sku") or "").strip(), "quantity": li.get("quantity") or 0}
            for li in (row.get("line_items") or [])
        ]
        result.append(
            ExternalOrderRow(
                external_order_id=str(row.get("id")),
                external_customer_id=str(row.get("customer_id") or ""),
                status=str(row.get("status") or ""),
                lines=lines,
            )
        )
    return result


@dataclass
class ExternalCustomerRow:
    external_customer_id: str
    email: str
    first_name: str
    last_name: str
    phone: str


def list_variations(wcapi: API, parent_id: int, per_page: int = 100, max_pages: int = 20) -> list[dict]:
    """طبقِ رفعِ ابهامِ واقعی: مستنداتِ ووکامرس تضمین نمی‌کنند که فیلترِ
    sku رویِ endpointِ واریانت‌ها پشتیبانی شود -- پس همه‌یِ واریانت‌هایِ
    یک محصولِ متغیر یک‌جا خوانده می‌شوند و تطبیقِ SKU در پایتون انجام
    می‌شود (برایِ تعدادِ معمولِ واریانت -- چند ده‌تا -- کاملاً کافی است)."""
    result: list[dict] = []
    page = 1
    while page <= max_pages:
        resp = retry.call_with_retry(wcapi.get, f"products/{parent_id}/variations", params={"per_page": per_page, "page": page})
        if resp.status_code >= 400:
            _raise_for_status(resp, f"دریافتِ واریانت‌هایِ محصولِ #{parent_id}")
        rows = resp.json()
        if not isinstance(rows, list) or not rows:
            break
        result.extend(rows)
        if len(rows) < per_page:
            break
        page += 1
    return result


def upsert_variation(wcapi: API, parent_id: int, sku: str, payload: dict, existing_variations: list[dict]) -> dict:
    existing = next((v for v in existing_variations if str(v.get("sku") or "") == sku), None)
    body = dict(payload)
    body["sku"] = sku
    if existing:
        resp = retry.call_with_retry(wcapi.put, f"products/{parent_id}/variations/{existing['id']}", body)
        return _raise_for_status(resp, f"به‌روزرسانیِ واریانتِ {sku}")
    resp = retry.call_with_retry(wcapi.post, f"products/{parent_id}/variations", body)
    return _raise_for_status(resp, f"ایجادِ واریانتِ {sku}")


def upload_media(store_url: str, wp_username: str, wp_app_password: str, file_bytes: bytes, filename: str) -> dict:
    """آپلودِ تصویر به کتابخانه‌یِ رسانه‌یِ وردپرس (wp/v2/media) --
    طبقِ کشفِ صریح حینِ بررسیِ PeechaSync: این endpoint هیچ ربطی به
    کلیدِ APIِ ووکامرس ندارد و نیازمندِ نامِ‌کاربری + گذرواژهٔ‌برنامه‌ایِ
    (Application Password) خودِ وردپرس است -- یک اعتبارِ کاملاً جدا."""
    base = normalize_store_url(store_url)
    url = f"{base}/wp-json/wp/v2/media"
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"', "Content-Type": content_type}
    try:
        resp = retry.call_with_retry(requests.post, url, headers=headers, data=file_bytes, auth=(wp_username, wp_app_password), timeout=60)
    except requests.RequestException as exc:
        raise StoreAPIError(f"آپلودِ تصویر -- خطایِ شبکه: {exc}") from exc
    if resp.status_code >= 400:
        raise StoreAPIError(f"آپلودِ تصویر -- خطایِ سایت (HTTP {resp.status_code}): {resp.text[:300]}")
    return resp.json()


def attach_product_image(wcapi: API, product_id: int, media_id: int) -> dict:
    resp = retry.call_with_retry(wcapi.put, f"products/{product_id}", {"images": [{"id": media_id}]})
    return _raise_for_status(resp, f"اتصالِ تصویر به محصولِ #{product_id}")


def fetch_customer(wcapi: API, external_customer_id: str) -> ExternalCustomerRow | None:
    if not external_customer_id or external_customer_id == "0":
        return None
    resp = retry.call_with_retry(wcapi.get, f"customers/{external_customer_id}")
    if resp.status_code == 404:
        return None
    data = _raise_for_status(resp, f"دریافتِ مشتریِ #{external_customer_id}")
    billing = data.get("billing") or {}
    return ExternalCustomerRow(
        external_customer_id=str(data.get("id")),
        email=str(data.get("email") or ""),
        first_name=str(data.get("first_name") or ""),
        last_name=str(data.get("last_name") or ""),
        phone=str(billing.get("phone") or ""),
    )
