"""R348: قرارداد فنی سامانهٔ مودیان (نسخهٔ ۲): شمارهٔ مالیاتی ۲۲ کاراکتری، امضای JWS (RS256 با گواهی x5c)، رمزنگاری JWE
(RSA-OAEP-256 + A256GCM) و کلاینت HTTP. بدون پایگاه داده؛ سرویس moadian از آن استفاده می‌کند.

منبع: کیت‌های متن‌باز موجود در PyPI (moadian 1.0.4 و moadian-sdk 0.2.0)؛ سایت سازمان امور مالیاتی از محیط توسعه در
دسترس نبود. پیش از استفادهٔ واقعی باید در محیط آزمایشی سامانه آزموده شود."""

from __future__ import annotations

import base64
import datetime
import json
import os
import uuid
from dataclasses import dataclass

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

DEFAULT_API_URL = "https://tp.tax.gov.ir/requestsmanager/api/v2"

_D = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
    [3, 4, 0, 1, 2, 8, 9, 5, 6, 7], [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3], [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
    [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]
_P = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
    [8, 9, 1, 6, 0, 4, 3, 5, 2, 7], [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]
_INV = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9]
MAX_SERIAL = 0xFFFFFFFFFF


def verhoeff_digit(number: str) -> int:
    c = 0
    for i, digit in enumerate(reversed(number)):
        c = _D[c][_P[(i + 1) % 8][int(digit)]]
    return _INV[c]


def verhoeff_valid(number: str) -> bool:
    c = 0
    for i, digit in enumerate(reversed(number)):
        c = _D[c][_P[i % 8][int(digit)]]
    return c == 0


def invoice_timestamp(day: datetime.date) -> int:
    """زمان صورتحساب (میلی‌ثانیه)؛ ظهر به وقت تهران تا روز آن در هر منطقهٔ زمانی همان بماند."""
    tehran = datetime.timezone(datetime.timedelta(hours=3, minutes=30))
    return int(datetime.datetime.combine(day, datetime.time(12), tehran).timestamp() * 1000)


def tax_id(memory_id: str, timestamp_ms: int, serial: int) -> str:
    """شمارهٔ مالیاتی: شناسهٔ حافظه (۶) + روز از ۱۹۷۰ (۵ هگز) + سریال (۱۰ هگز) + رقم کنترل Verhoeff."""
    memory_id = memory_id.strip().upper()
    if len(memory_id) != 6 or not memory_id.isalnum() or not memory_id.isascii():
        raise ValueError("شناسهٔ یکتای حافظهٔ مالیاتی باید ۶ حرف یا رقم لاتین باشد.")
    if not 0 < serial <= MAX_SERIAL:
        raise ValueError("سریال صورتحساب خارج از بازهٔ مجاز است.")
    days = timestamp_ms // 86_400_000
    numeric = "".join(ch if ch.isdigit() else str(ord(ch)) for ch in memory_id) + str(days).zfill(6) + str(serial).zfill(12)
    return f"{memory_id}{days:05X}{serial:010X}{verhoeff_digit(numeric)}"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


@dataclass
class Credentials:
    private_key_pem: str
    certificate_pem: str

    def load(self):
        try:
            key = serialization.load_pem_private_key(self.private_key_pem.encode("utf-8"), password=None)
        except (ValueError, TypeError) as exc:
            raise ValueError("کلید خصوصی معتبر نیست (قالب PEM بدون رمز لازم است).") from exc
        try:
            cert = x509.load_pem_x509_certificate(self.certificate_pem.encode("utf-8"))
        except ValueError as exc:
            raise ValueError("گواهی امضا معتبر نیست (قالب PEM لازم است).") from exc
        if cert.public_key().public_numbers() != key.public_key().public_numbers():
            raise ValueError("گواهی با کلید خصوصی جور نیست.")
        return key, cert


def jws_sign(payload: dict, credentials: Credentials, now: datetime.datetime | None = None) -> str:
    key, cert = credentials.load()
    sig_time = (now or datetime.datetime.now(datetime.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    header = {"alg": "RS256", "x5c": [base64.b64encode(cert.public_bytes(serialization.Encoding.DER)).decode("ascii")],
              "sigT": sig_time, "crit": ["sigT"]}
    signing_input = (_b64url(json.dumps(header, separators=(",", ":")).encode("utf-8")) + "."
                     + _b64url(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")))
    signature = key.sign(signing_input.encode("ascii"), padding.PKCS1v15(), hashes.SHA256())
    return f"{signing_input}.{_b64url(signature)}"


def jwe_encrypt(plaintext: str, server_public_key_b64: str, key_id: str) -> str:
    public_key = serialization.load_der_public_key(base64.b64decode(server_public_key_b64))
    header = _b64url(json.dumps({"alg": "RSA-OAEP-256", "enc": "A256GCM", "kid": key_id}, separators=(",", ":")).encode("utf-8"))
    cek, iv = os.urandom(32), os.urandom(12)
    encrypted_key = public_key.encrypt(cek, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
    sealed = AESGCM(cek).encrypt(iv, plaintext.encode("utf-8"), header.encode("ascii"))
    return ".".join([header, _b64url(encrypted_key), _b64url(iv), _b64url(sealed[:-16]), _b64url(sealed[-16:])])


def jwe_decrypt(token: str, private_key) -> str:
    """فقط برای آزمون (نقش سرور)."""
    header, encrypted_key, iv, ciphertext, tag = token.split(".")
    cek = private_key.decrypt(_b64url_decode(encrypted_key),
                              padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
    return AESGCM(cek).decrypt(_b64url_decode(iv), _b64url_decode(ciphertext) + _b64url_decode(tag),
                               header.encode("ascii")).decode("utf-8")


def jws_payload(token: str, verify_with=None) -> dict:
    header, payload, signature = token.split(".")
    if verify_with is not None:
        verify_with.verify(_b64url_decode(signature), f"{header}.{payload}".encode("ascii"), padding.PKCS1v15(), hashes.SHA256())
    return json.loads(_b64url_decode(payload))


class MoadianError(Exception):
    pass


class Client:
    """کلاینت سامانه؛ transport شیئی با متد request مانند requests.Session است (در آزمون جایگزین می‌شود)."""

    def __init__(self, api_url: str, fiscal_id: str, credentials: Credentials, transport=None, timeout: int = 30):
        if not api_url.startswith("https://"):
            raise ValueError("آدرس سامانهٔ مودیان باید با https:// شروع شود.")
        self.base_url, self.fiscal_id, self.credentials, self.timeout = api_url.rstrip("/"), fiscal_id, credentials, timeout
        if transport is None:
            import requests

            transport = requests.Session()
        self.transport = transport

    def _call(self, method: str, endpoint: str, *, params=None, body=None, auth: bool = True):
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if auth:
            nonce = self._call("GET", "nonce", params={"timeToLive": 30}, auth=False)["nonce"]
            headers["Authorization"] = "Bearer " + jws_sign({"nonce": nonce, "clientId": self.fiscal_id}, self.credentials)
        try:
            response = self.transport.request(method, f"{self.base_url}/{endpoint}", params=params, json=body,
                                              headers=headers, timeout=self.timeout)
        except Exception as exc:  # noqa: BLE001 (خطای شبکه با پیام فارسی برمی‌گردد)
            raise MoadianError(f"اتصال به سامانهٔ مودیان برقرار نشد: {exc}") from exc
        if response.status_code == 401:
            raise MoadianError("سامانهٔ مودیان احراز هویت را نپذیرفت؛ شناسهٔ حافظه، کلید و گواهی را بررسی کنید.")
        if response.status_code >= 400:
            raise MoadianError(f"پاسخ خطای سامانهٔ مودیان ({response.status_code}): {response.text[:300]}")
        return response.json()

    def server_information(self) -> dict:
        return self._call("GET", "server-information")

    def taxpayer(self, economic_code: str) -> dict:
        return self._call("GET", "taxpayer", params={"economicCode": economic_code})

    def fiscal_information(self) -> dict:
        return self._call("GET", "fiscal-information", params={"memoryId": self.fiscal_id})

    def send(self, invoices: list[dict]) -> list[dict]:
        """invoices: صورتحساب‌های ساخته‌شده؛ خروجی: [{"uid", "referenceNumber", ...}] به همان ترتیب."""
        keys = self.server_information().get("publicKeys") or []
        if not keys:
            raise MoadianError("سامانه کلید عمومی رمزنگاری برنگرداند.")
        packets = [{"header": {"requestTraceId": str(uuid.uuid4()), "fiscalId": self.fiscal_id},
                    "payload": jwe_encrypt(jws_sign(invoice, self.credentials), keys[0]["key"], keys[0]["id"])}
                   for invoice in invoices]
        result = _items(self._call("POST", "invoice", body=packets))
        by_uid = {r.get("uid"): r for r in result}
        return [dict(by_uid.get(p["header"]["requestTraceId"]) or {}, uid=p["header"]["requestTraceId"]) for p in packets]

    def inquiry_by_uid(self, uids: list[str]) -> list[dict]:
        return _items(self._call("GET", "inquiry-by-uid", params={"uidList": uids, "fiscalId": self.fiscal_id}))


def _items(response) -> list[dict]:
    """پاسخ فهرستی سامانه، چه خود فهرست باشد چه زیر کلید result."""
    if isinstance(response, dict):
        response = response.get("result") or response.get("data") or []
    return [r for r in response if isinstance(r, dict)] if isinstance(response, list) else []
