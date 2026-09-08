"""لایه‌ی ارتباطِ خامِ HTTP با پرستاشاپ (PrestaShop Webservice API).

طبقِ درخواستِ صریحِ کاربر («پشتیبانیِ پرستاشاپ») و درسِ گرفته‌شده از فازِ
بررسیِ PeechaSync (که پیاده‌سازیِ پرستاشاپِ خودش را صریحاً «هنوز رویِ
فروشگاهِ واقعی تست‌نشده» علامت زده بود): این لایه با همان انضباطِ
wc_client.py نوشته شده -- هیچ دسترسیِ مستقیمی به دیتابیسِ ERP ندارد،
فقط پارامترهایِ ساده می‌گیرد -- ولی دامنه‌اش عمداً محدودتر از ووکامرس
است: فقط محصولِ ساده (بدون واریانت/کامبینیشن)، دسته، مشتری، و سفارش.
واریانت/تصویر برایِ پرستاشاپ به فازِ بعدی موکول شده -- دقیقاً همان
تدریجی‌بودنی که برایِ ووکامرس هم رعایت شد (S1 قبل از S2).

وبِ‌سرویسِ پرستاشاپ:
- احرازِ هویت: HTTP Basic Auth با کلیدِ API به‌عنوانِ نامِ‌کاربری و
  گذرواژهٔ خالی (نه Consumer Key/Secretِ ووکامرس).
- خواندن (GET): با ``output_format=JSON`` رشته‌یِ JSON برمی‌گرداند --
  این بخش از نسخهٔ ۱.۶ به بعد به‌طورِ رسمی/پایدار پشتیبانی می‌شود.
- نوشتن (POST/PUT): وب‌سرویسِ پرستاشاپ فقط بدنه/پاسخِ XML را به‌طورِ
  رسمی/پایدار در همه‌یِ نسخه‌ها پشتیبانی می‌کند -- پس نوشتن همیشه با
  XML انجام می‌شود، حتی اگر خواندن با JSON باشد.
- موجودی یک resourceِ جداست (``stock_availables``)، نه فیلدی رویِ خودِ
  محصول -- ساختِ محصول خودکار یک stock_availableِ متناظر می‌سازد که
  باید جداگانه به‌روزرسانی شود."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass

import requests

from peecha.integrations.ecommerce import retry

_DEFAULT_TIMEOUT = 30
_DEFAULT_LANGUAGE_ID = 1


class StoreAPIError(RuntimeError):
    """خطایِ ارتباط با فروشگاه -- پیامِ HTTP یا شبکه به فارسی ترجمه می‌شود."""


def normalize_store_url(url: str) -> str:
    cleaned = (url or "").strip().rstrip("/")
    if cleaned.endswith("/api"):
        cleaned = cleaned[: -len("/api")]
    return cleaned


@dataclass
class PrestaAPI:
    """بسته‌بندیِ سبکِ اتصال -- معادلِ نقشِ ``woocommerce.API`` برایِ
    پرستاشاپ. متدهایِ get/post/put دقیقاً یک شیِ‌ء requests.Response
    خام برمی‌گردانند (بدونِ raise_for_status) تا الگویِ فراخوانی با
    wc_client.py یکسان بماند."""

    base_url: str
    api_key: str
    timeout: int = _DEFAULT_TIMEOUT

    def _url(self, resource: str) -> str:
        return f"{self.base_url}/api/{resource}"

    def get(self, resource: str, params: dict | None = None):
        query = dict(params or {})
        query.setdefault("output_format", "JSON")
        return requests.get(self._url(resource), params=query, auth=(self.api_key, ""), timeout=self.timeout)

    def post(self, resource: str, xml_body: str):
        return requests.post(
            self._url(resource), data=xml_body.encode("utf-8"), auth=(self.api_key, ""),
            headers={"Content-Type": "text/xml"}, timeout=self.timeout,
        )

    def put(self, resource: str, xml_body: str):
        return requests.put(
            self._url(resource), data=xml_body.encode("utf-8"), auth=(self.api_key, ""),
            headers={"Content-Type": "text/xml"}, timeout=self.timeout,
        )


def build_prestapi(store_url: str, api_key: str, timeout: int = _DEFAULT_TIMEOUT) -> PrestaAPI:
    return PrestaAPI(base_url=normalize_store_url(store_url), api_key=(api_key or "").strip(), timeout=timeout)


def _raise_for_status(resp, label: str) -> None:
    if resp.status_code >= 400:
        raise StoreAPIError(f"{label} -- خطایِ سایت (HTTP {resp.status_code}): {resp.text[:300]}")


def check_connection(papi: PrestaAPI) -> tuple[bool, str]:
    try:
        resp = retry.call_with_retry(papi.get, "customers", params={"limit": "1"})
    except Exception as exc:  # noqa: BLE001 -- خطاهایِ requests/شبکه متنوع‌اند
        return False, f"اتصال به فروشگاه برقرار نشد: {exc}"
    if resp.status_code >= 400:
        return False, f"فروشگاه با خطایِ HTTP {resp.status_code} پاسخ داد -- کلیدِ API را بررسی کنید."
    return True, "اتصال به پرستاشاپ برقرار است."


def find_product_by_reference(papi: PrestaAPI, reference: str) -> dict | None:
    resp = retry.call_with_retry(
        papi.get, "products", params={"filter[reference]": reference, "display": "full"},
    )
    if resp.status_code >= 400:
        _raise_for_status(resp, f"جست‌وجویِ محصولِ SKU={reference}")
    data = resp.json()
    rows = (data or {}).get("products") or []
    if not isinstance(rows, list) or not rows:
        return None
    return rows[0]


def _multilang_xml(tag: str, value: str, language_id: int = _DEFAULT_LANGUAGE_ID) -> str:
    escaped = (value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f'<{tag}><language id="{language_id}"><![CDATA[{escaped}]]></language></{tag}>'


def _build_product_xml(reference: str, fields: dict, product_id: int | None = None) -> str:
    """``fields`` می‌تواند شامل: name, price (رشته/عدد، بدونِ مالیات),
    active (0/1), id_category_default (اختیاری) باشد. طبقِ مستنداتِ
    وب‌سرویسِ پرستاشاپ، name یک فیلدِ چندزبانه است."""
    parts = ["<prestashop>", "<product>"]
    if product_id is not None:
        parts.append(f"<id>{product_id}</id>")
    parts.append(f"<reference><![CDATA[{reference}]]></reference>")
    if "name" in fields:
        parts.append(_multilang_xml("name", str(fields["name"])))
    if "price" in fields:
        parts.append(f"<price>{fields['price']}</price>")
    if "active" in fields:
        parts.append(f"<active>{1 if fields['active'] else 0}</active>")
    if fields.get("id_category_default"):
        parts.append(f"<id_category_default>{int(fields['id_category_default'])}</id_category_default>")
    parts.append("</product>")
    parts.append("</prestashop>")
    return "".join(parts)


def upsert_product(papi: PrestaAPI, reference: str, fields: dict) -> dict:
    """محصولِ با referenceِ (معادلِ SKU) مشخص را اگر از قبل هست
    به‌روزرسانی می‌کند، وگرنه می‌سازد. برمی‌گرداند: {«id»: ...}."""
    existing = find_product_by_reference(papi, reference)
    if existing:
        product_id = int(existing["id"])
        body = _build_product_xml(reference, fields, product_id=product_id)
        resp = retry.call_with_retry(papi.put, f"products/{product_id}", body)
        _raise_for_status(resp, f"به‌روزرسانیِ محصولِ {reference}")
        return {"id": product_id}
    body = _build_product_xml(reference, fields)
    resp = retry.call_with_retry(papi.post, "products", body)
    _raise_for_status(resp, f"ایجادِ محصولِ {reference}")
    root = ET.fromstring(resp.text)
    id_element = root.find("./product/id")
    if id_element is None or not id_element.text:
        raise StoreAPIError(f"ایجادِ محصولِ {reference} -- پاسخِ فروشگاه فاقدِ id بود.")
    return {"id": int(id_element.text)}


def find_stock_available_id(papi: PrestaAPI, product_id: int) -> int | None:
    resp = retry.call_with_retry(
        papi.get, "stock_availables", params={"filter[id_product]": str(product_id), "filter[id_product_attribute]": "0"},
    )
    if resp.status_code >= 400:
        _raise_for_status(resp, f"جست‌وجویِ موجودیِ محصولِ #{product_id}")
    data = resp.json()
    rows = (data or {}).get("stock_availables") or []
    if not isinstance(rows, list) or not rows:
        return None
    return int(rows[0]["id"])


def update_stock_quantity(papi: PrestaAPI, product_id: int, quantity: int) -> None:
    stock_id = find_stock_available_id(papi, product_id)
    if stock_id is None:
        raise StoreAPIError(f"محصولِ #{product_id} در فروشگاه هیچ رکوردِ موجودیِ متناظری ندارد.")
    body = f"<prestashop><stock_available><id>{stock_id}</id><id_product>{product_id}</id_product><quantity>{quantity}</quantity></stock_available></prestashop>"
    resp = retry.call_with_retry(papi.put, f"stock_availables/{stock_id}", body)
    _raise_for_status(resp, f"به‌روزرسانیِ موجودیِ محصولِ #{product_id}")


def find_category_by_name(papi: PrestaAPI, name: str, parent_external_id: int | None) -> dict | None:
    resp = retry.call_with_retry(papi.get, "categories", params={"filter[name]": f"%[{name}]%", "display": "full"})
    if resp.status_code >= 400:
        _raise_for_status(resp, f"جست‌وجویِ دستهٔ «{name}»")
    data = resp.json()
    rows = (data or {}).get("categories") or []
    if not isinstance(rows, list):
        return None
    parent_id = int(parent_external_id) if parent_external_id else None
    for row in rows:
        row_name = row.get("name")
        if isinstance(row_name, list):
            row_name = next((v.get("value") for v in row_name if isinstance(v, dict)), "")
        if str(row_name or "").strip() != name.strip():
            continue
        if parent_id is not None and int(row.get("id_parent") or 0) != parent_id:
            continue
        return row
    return None


def create_category(papi: PrestaAPI, name: str, parent_external_id: int | None) -> dict:
    parts = ["<prestashop>", "<category>", _multilang_xml("name", name)]
    if parent_external_id:
        parts.append(f"<id_parent>{int(parent_external_id)}</id_parent>")
    parts.append("<active>1</active>")
    parts.append("</category>")
    parts.append("</prestashop>")
    resp = retry.call_with_retry(papi.post, "categories", "".join(parts))
    _raise_for_status(resp, f"ایجادِ دستهٔ «{name}»")
    root = ET.fromstring(resp.text)
    id_element = root.find("./category/id")
    if id_element is None or not id_element.text:
        raise StoreAPIError(f"ایجادِ دستهٔ «{name}» -- پاسخِ فروشگاه فاقدِ id بود.")
    return {"id": int(id_element.text)}


@dataclass
class ExternalOrderRow:
    external_order_id: str
    external_customer_id: str
    status: str
    lines: list[dict]  # [{"sku": ..., "quantity": ...}]


def fetch_new_orders(papi: PrestaAPI, *, state_id: int = 2, limit: int = 50) -> list[ExternalOrderRow]:
    """طبقِ مستنداتِ پرستاشاپ: ``current_state=2`` یعنی «در حالِ پردازش
    (پرداخت‌شده)» در نصبِ پیش‌فرض -- معادلِ همان چیزی که در ووکامرس
    ``status=processing`` بود."""
    resp = retry.call_with_retry(
        papi.get, "orders", params={"filter[current_state]": str(state_id), "display": "full", "limit": str(limit)},
    )
    if resp.status_code >= 400:
        _raise_for_status(resp, "دریافتِ سفارش‌هایِ تازه")
    data = resp.json()
    rows = (data or {}).get("orders") or []
    if not isinstance(rows, list):
        return []
    result = []
    for row in rows:
        associations = row.get("associations") or {}
        order_rows = associations.get("order_rows") or []
        lines = [
            {"sku": str(li.get("product_reference") or "").strip(), "quantity": li.get("product_quantity") or 0}
            for li in order_rows
        ]
        result.append(
            ExternalOrderRow(
                external_order_id=str(row.get("id")),
                external_customer_id=str(row.get("id_customer") or ""),
                status=str(row.get("current_state") or ""),
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


def fetch_customer(papi: PrestaAPI, external_customer_id: str) -> ExternalCustomerRow | None:
    if not external_customer_id or external_customer_id == "0":
        return None
    resp = retry.call_with_retry(papi.get, f"customers/{external_customer_id}")
    if resp.status_code == 404:
        return None
    _raise_for_status(resp, f"دریافتِ مشتریِ #{external_customer_id}")
    data = resp.json()
    row = (data or {}).get("customer") or {}
    return ExternalCustomerRow(
        external_customer_id=str(row.get("id")),
        email=str(row.get("email") or ""),
        first_name=str(row.get("firstname") or ""),
        last_name=str(row.get("lastname") or ""),
        phone=str(row.get("phone") or row.get("phone_mobile") or ""),
    )
