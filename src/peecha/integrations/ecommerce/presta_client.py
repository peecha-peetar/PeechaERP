"""لایه‌ی ارتباطِ خامِ HTTP با پرستاشاپ (PrestaShop Webservice API).

طبقِ درخواستِ صریحِ کاربر («پشتیبانیِ پرستاشاپ») و درسِ گرفته‌شده از فازِ
بررسیِ PeechaSync (که پیاده‌سازیِ پرستاشاپِ خودش را صریحاً «هنوز رویِ
فروشگاهِ واقعی تست‌نشده» علامت زده بود): این لایه با همان انضباطِ
wc_client.py نوشته شده -- هیچ دسترسیِ مستقیمی به دیتابیسِ ERP ندارد،
فقط پارامترهایِ ساده می‌گیرد. محصولِ ساده، دسته، مشتری، سفارش (S6)، و
حالا واریانت (کامبینیشن) + تصویر (S7) پشتیبانی می‌شوند.

مدلِ واریانتِ پرستاشاپ با ووکامرس فرق دارد: به‌جایِ یک attributeِ محلیِ
سرراست، هر ویژگی باید اول یک «گروهِ ویژگی» (product_options، مثلاً
«سایز») و بعد هر مقدار یک «مقدارِ ویژگی» (product_option_values، مثلاً
«S») در سطحِ کلِ فروشگاه بسازد (نه فقط رویِ یک محصول) -- سپس هر واریانتِ
واقعیِ یک محصول (combinations) به این مقدارها ارجاع می‌دهد. قیمتِ
رویِ combination هم «افزوده» (price impact) نسبت به قیمتِ پایه‌یِ
محصول است، نه قیمتِ مطلق.

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

    def delete(self, resource: str):
        return requests.delete(self._url(resource), auth=(self.api_key, ""), timeout=self.timeout)

    def post_multipart(self, resource: str, file_bytes: bytes, filename: str):
        """آپلودِ تصویر (images/products/{id}) طبقِ مستنداتِ پرستاشاپ
        multipart/form-data است -- نه XML مثلِ بقیه‌یِ نوشتن‌ها."""
        return requests.post(
            self._url(resource), files={"image": (filename, file_bytes)}, auth=(self.api_key, ""), timeout=self.timeout,
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


# ---------------------------------------------------------------------
# واریانت (کامبینیشن) -- طبقِ درخواستِ صریح («واریانت + تصویر برایِ
# پرستاشاپ»). ر.ک. توضیحِ کاملِ مدلِ combinationِ پرستاشاپ در سرِ فایل.
# ---------------------------------------------------------------------
def find_attribute_group_by_name(papi: PrestaAPI, name: str) -> dict | None:
    resp = retry.call_with_retry(papi.get, "product_options", params={"filter[name]": f"%[{name}]%", "display": "full"})
    if resp.status_code >= 400:
        _raise_for_status(resp, f"جست‌وجویِ گروهِ ویژگیِ «{name}»")
    data = resp.json()
    rows = (data or {}).get("product_options") or []
    if not isinstance(rows, list):
        return None
    for row in rows:
        row_name = row.get("name")
        if isinstance(row_name, list):
            row_name = next((v.get("value") for v in row_name if isinstance(v, dict)), "")
        if str(row_name or "").strip() == name.strip():
            return row
    return None


def create_attribute_group(papi: PrestaAPI, name: str) -> dict:
    body = (
        "<prestashop><product_option>"
        + _multilang_xml("name", name)
        + _multilang_xml("public_name", name)
        + "<group_type>select</group_type>"
        + "</product_option></prestashop>"
    )
    resp = retry.call_with_retry(papi.post, "product_options", body)
    _raise_for_status(resp, f"ایجادِ گروهِ ویژگیِ «{name}»")
    root = ET.fromstring(resp.text)
    id_element = root.find("./product_option/id")
    if id_element is None or not id_element.text:
        raise StoreAPIError(f"ایجادِ گروهِ ویژگیِ «{name}» -- پاسخِ فروشگاه فاقدِ id بود.")
    return {"id": int(id_element.text)}


def find_or_create_attribute_group(papi: PrestaAPI, name: str) -> int:
    found = find_attribute_group_by_name(papi, name)
    return int(found["id"]) if found else int(create_attribute_group(papi, name)["id"])


def find_attribute_value_by_name(papi: PrestaAPI, group_id: int, value: str) -> dict | None:
    resp = retry.call_with_retry(
        papi.get, "product_option_values", params={"filter[id_attribute_group]": str(group_id), "filter[name]": f"%[{value}]%", "display": "full"},
    )
    if resp.status_code >= 400:
        _raise_for_status(resp, f"جست‌وجویِ مقدارِ ویژگیِ «{value}»")
    data = resp.json()
    rows = (data or {}).get("product_option_values") or []
    if not isinstance(rows, list):
        return None
    for row in rows:
        if int(row.get("id_attribute_group") or 0) != group_id:
            continue
        row_name = row.get("name")
        if isinstance(row_name, list):
            row_name = next((v.get("value") for v in row_name if isinstance(v, dict)), "")
        if str(row_name or "").strip() == value.strip():
            return row
    return None


def create_attribute_value(papi: PrestaAPI, group_id: int, value: str) -> dict:
    body = (
        "<prestashop><product_option_value>"
        + f"<id_attribute_group>{group_id}</id_attribute_group>"
        + _multilang_xml("name", value)
        + "</product_option_value></prestashop>"
    )
    resp = retry.call_with_retry(papi.post, "product_option_values", body)
    _raise_for_status(resp, f"ایجادِ مقدارِ ویژگیِ «{value}»")
    root = ET.fromstring(resp.text)
    id_element = root.find("./product_option_value/id")
    if id_element is None or not id_element.text:
        raise StoreAPIError(f"ایجادِ مقدارِ ویژگیِ «{value}» -- پاسخِ فروشگاه فاقدِ id بود.")
    return {"id": int(id_element.text)}


def find_or_create_attribute_value(papi: PrestaAPI, group_id: int, value: str) -> int:
    found = find_attribute_value_by_name(papi, group_id, value)
    return int(found["id"]) if found else int(create_attribute_value(papi, group_id, value)["id"])


def list_combinations(papi: PrestaAPI, product_id: int) -> list[dict]:
    resp = retry.call_with_retry(papi.get, "combinations", params={"filter[id_product]": str(product_id), "display": "full"})
    if resp.status_code >= 400:
        _raise_for_status(resp, f"دریافتِ واریانت‌هایِ محصولِ #{product_id}")
    data = resp.json()
    rows = (data or {}).get("combinations") or []
    return rows if isinstance(rows, list) else []


def _build_combination_xml(product_id: int, reference: str, price_impact: str, option_value_ids: list[int], combination_id: int | None = None) -> str:
    parts = ["<prestashop>", "<combination>"]
    if combination_id is not None:
        parts.append(f"<id>{combination_id}</id>")
    parts.append(f"<id_product>{product_id}</id_product>")
    parts.append(f"<reference><![CDATA[{reference}]]></reference>")
    parts.append(f"<price>{price_impact}</price>")
    parts.append("<associations><product_option_values>")
    for value_id in option_value_ids:
        parts.append(f"<product_option_value><id>{value_id}</id></product_option_value>")
    parts.append("</product_option_values></associations>")
    parts.append("</combination>")
    parts.append("</prestashop>")
    return "".join(parts)


def delete_combination(papi: PrestaAPI, combination_id: int) -> None:
    """طبقِ رفعِ باگِ واقعیِ ساختاری («تبدیلِ کالایِ واریانت‌دار به سادهٔ در
    ERP»): بدونِ حذفِ صریحِ combinationِ باقی‌مانده، فروشگاه همچنان
    انتخابگرِ واریانت را نشان می‌دهد در حالی‌که در ERP این کالا دیگر
    واریانت ندارد."""
    resp = retry.call_with_retry(papi.delete, f"combinations/{combination_id}")
    _raise_for_status(resp, f"حذفِ واریانتِ #{combination_id}")


def upsert_combination(papi: PrestaAPI, product_id: int, reference: str, price_impact: str, option_value_ids: list[int], existing_combinations: list[dict]) -> dict:
    existing = next((c for c in existing_combinations if str(c.get("reference") or "") == reference), None)
    if existing:
        combination_id = int(existing["id"])
        body = _build_combination_xml(product_id, reference, price_impact, option_value_ids, combination_id=combination_id)
        resp = retry.call_with_retry(papi.put, f"combinations/{combination_id}", body)
        _raise_for_status(resp, f"به‌روزرسانیِ واریانتِ {reference}")
        return {"id": combination_id}
    body = _build_combination_xml(product_id, reference, price_impact, option_value_ids)
    resp = retry.call_with_retry(papi.post, "combinations", body)
    _raise_for_status(resp, f"ایجادِ واریانتِ {reference}")
    root = ET.fromstring(resp.text)
    id_element = root.find("./combination/id")
    if id_element is None or not id_element.text:
        raise StoreAPIError(f"ایجادِ واریانتِ {reference} -- پاسخِ فروشگاه فاقدِ id بود.")
    return {"id": int(id_element.text)}


def find_combination_stock_available_id(papi: PrestaAPI, product_id: int, combination_id: int) -> int | None:
    resp = retry.call_with_retry(
        papi.get, "stock_availables", params={"filter[id_product]": str(product_id), "filter[id_product_attribute]": str(combination_id)},
    )
    if resp.status_code >= 400:
        _raise_for_status(resp, f"جست‌وجویِ موجودیِ واریانتِ #{combination_id}")
    data = resp.json()
    rows = (data or {}).get("stock_availables") or []
    if not isinstance(rows, list) or not rows:
        return None
    return int(rows[0]["id"])


def update_combination_stock_quantity(papi: PrestaAPI, product_id: int, combination_id: int, quantity: int) -> None:
    stock_id = find_combination_stock_available_id(papi, product_id, combination_id)
    if stock_id is None:
        raise StoreAPIError(f"واریانتِ #{combination_id} در فروشگاه هیچ رکوردِ موجودیِ متناظری ندارد.")
    body = (
        f"<prestashop><stock_available><id>{stock_id}</id><id_product>{product_id}</id_product>"
        f"<id_product_attribute>{combination_id}</id_product_attribute><quantity>{quantity}</quantity></stock_available></prestashop>"
    )
    resp = retry.call_with_retry(papi.put, f"stock_availables/{stock_id}", body)
    _raise_for_status(resp, f"به‌روزرسانیِ موجودیِ واریانتِ #{combination_id}")


def upload_product_image(papi: PrestaAPI, product_id: int, file_bytes: bytes, filename: str) -> dict:
    """طبقِ مستنداتِ پرستاشاپ: برخلافِ ووکامرس (که تصویر را جدا آپلود و
    بعد به محصول متصل می‌کند)، این‌جا خودِ آپلود مستقیماً به محصول متصل
    می‌شود -- یک مرحله‌ای."""
    resp = retry.call_with_retry(papi.post_multipart, f"images/products/{product_id}", file_bytes, filename)
    _raise_for_status(resp, f"آپلودِ تصویرِ محصولِ #{product_id}")
    root = ET.fromstring(resp.text)
    id_element = root.find("./image/id")
    if id_element is None or not id_element.text:
        raise StoreAPIError(f"آپلودِ تصویرِ محصولِ #{product_id} -- پاسخِ فروشگاه فاقدِ id بود.")
    return {"id": int(id_element.text)}


def product_has_images(papi: PrestaAPI, product_id: int) -> bool:
    resp = retry.call_with_retry(papi.get, f"images/products/{product_id}")
    if resp.status_code == 404:
        return False
    if resp.status_code >= 400:
        _raise_for_status(resp, f"بررسیِ تصویرِ محصولِ #{product_id}")
    data = resp.json()
    rows = (data or {}).get("declination") or (data or {}).get("image") or []
    return bool(rows)
