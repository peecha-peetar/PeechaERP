"""R348: سامانهٔ مودیان: شناسهٔ کالا و کد واحد، تنظیمات (حافظه، شمارهٔ اقتصادی، کلید و گواهی رمزشده)، ایرادهای مانع
ارسال، ساخت صورتحساب از فاکتور ثبت‌شده (مبالغ، خریدار حقوقی و نوع دوم)، شمارهٔ مالیاتی ۲۲ کاراکتری با رقم کنترل،
ارسال امضاشده و رمزشده به سرور ساختگی، استعلام نتیجه، برگشت از فروش و ابطال با ارجاع، خطای شبکه، و فرم."""
import base64, datetime, json, os, sys, tempfile
from types import SimpleNamespace
os.environ["PEECHA_DB_NAME"] = "peecha_test_r348"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from peecha.db.models.commercial import MoadianInvoice
from peecha.services import commercial_documents as docs, commercial_partners as partners, commercial_settings as csettings, \
    commercial_settlements as settlements, moadian, moadian_protocol as protocol

k13 = A("13", "دریافتنی‌ها", "DEBIT", "ASSET", "PERMANENT", False, g1.account_id)
ar_gl = A("131", "دریافتنی مشتریان", "DEBIT", "ASSET", "PERMANENT", True, k13.account_id)
g_rev = A("4", "درآمدها", "CREDIT", "REVENUE", "TEMPORARY", False)
k41 = A("41", "درآمد عملیاتی", "CREDIT", "REVENUE", "TEMPORARY", False, g_rev.account_id)
rev_gl = A("411", "فروش", "CREDIT", "REVENUE", "TEMPORARY", True, k41.account_id)
disc_gl = A("412", "تخفیف فروش", "DEBIT", "REVENUE", "TEMPORARY", True, k41.account_id)
tax_gl = A("212", "مالیات ارزش‌افزودهٔ فروش", "CREDIT", "LIABILITY", "PERMANENT", True, k7.account_id)
engine_service.set_account_mapping(company_id, "CUSTOMER_RECEIVABLE", ar_gl.account_id)
engine_service.set_account_mapping(company_id, "SALES_TAX_PAYABLE", tax_gl.account_id)
engine_service.set_account_mapping(company_id, "SALES_RETURNS", disc_gl.account_id)
for key, account in (("SALES_REVENUE", rev_gl), ("SALES_DISCOUNT", disc_gl), ("SALES_TAX_PAYABLE", tax_gl)):
    csettings.set_account_mapping(company_id, key, account.account_id)


def keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "peecha-test")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(1)
            .not_valid_before(now).not_valid_after(now + datetime.timedelta(days=2)).sign(key, hashes.SHA256()))
    return key, cert


def pem(key, cert):
    return (key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode(),
            cert.public_bytes(serialization.Encoding.PEM).decode())


# کالا و واحد
check(raises(lambda: item("MD-X", "کالای بدشناسه", "GOOD", moadian_stuff_id="123"), "۱۳"), "the stuff ID must be 13 digits")
goods = item("MD-1", "کالای مودیان", "GOOD", moadian_stuff_id="۲۷۱۰۰۰۰۱۳۸۶۲۴")
plain = item("MD-2", "کالای بی‌شناسه", "GOOD")
check(catalog_service.get_item(goods).moadian_stuff_id == "2710000138624", "the stuff ID is stored with Latin digits")
check(raises(lambda: catalog_service.set_uom_moadian_code(pcs, company_id, "ab"), "عدد"), "the unit code must be numeric")
receive(goods, 100, 400_000)
receive(plain, 10, 400_000)

legal = partners.create_customer(company_id, "C1", "شرکت خریدار", fast_track=True, economic_code="۱۰۱۰۱۲۳۴۵۶۷",
                                 national_id="10101234567", person_type_code="LEGAL")
partners.add_party_address(legal, "OFFICE", "تهران", postal_code="1234567890", is_default=True)
walk_in = partners.create_customer(company_id, "C2", "مشتری گذری", fast_track=True)


def invoice(customer, item_id=goods, qty=10, price=1_000_000, discount=500_000, tax=10, post=True, doc_type="SALES_INVOICE",
            source=None):
    d = docs.create_document(company_id, uid, doc_type, today, docs.DocumentHeaderFields(
        counterparty_detail_account_id=customer, currency_id=company.base_currency_id, warehouse_id=wh_rm,
        source_document_id=source))
    docs.add_line(d, company_id, item_id, pcs, D(qty), D(qty), unit_price=D(price), discount_amount=D(discount),
                  tax_percent=D(tax))
    if post:
        docs.confirm_document(d, company_id, uid)
        if doc_type == "SALES_INVOICE":
            settlements.auto_approve_settlement_plan(d, company_id, uid, [])
        docs.post_document(d, company_id, uid)
    return d


inv1 = invoice(legal)
payload, problems = moadian.build_payload(inv1, company_id)
check(any("حافظه" in p for p in problems) and any("اقتصادی فروشنده" in p for p in problems) and any("واحد" in p for p in problems),
      f"missing settings and unit code are reported ({problems})")

# تنظیمات
key, cert = keypair()
key_pem, cert_pem = pem(key, cert)
other_key, other_cert = keypair()
check(raises(lambda: moadian.save_settings(company_id, "ABC", "10101234567"), "۶"), "the memory ID must be 6 characters")
check(raises(lambda: moadian.save_settings(company_id, "A1B2C3", "10101234567", private_key_pem=key_pem,
                                           certificate_pem=pem(other_key, other_cert)[1]), "جور"),
      "a certificate that does not match the key is refused")
moadian.save_settings(company_id, "a1b2c3", "۱۰۱۰۱۲۳۴۵۶۷", "", "https://moadian.test/api/v2", key_pem, cert_pem)
settings = moadian.get_settings(company_id)
check(settings.memory_id == "A1B2C3" and settings.seller_tin == "10101234567" and settings.has_credentials,
      "settings are saved and the key is kept")
with new_session() as s:
    from peecha.db.models.commercial import MoadianSettings
    blob = bytes(s.get(MoadianSettings, company_id).credentials_encrypted)
check(b"PRIVATE KEY" not in blob, "the private key is stored encrypted")
moadian.save_settings(company_id, "A1B2C3", "10101234567", "", "https://moadian.test/api/v2")
check(moadian.get_settings(company_id).has_credentials, "saving without new files keeps the key")
catalog_service.set_uom_moadian_code(pcs, company_id, "۱۶۱۲")

payload, problems = moadian.build_payload(inv1, company_id)
header, line = payload["header"], payload["body"][0]
check(not problems, f"a complete invoice has no problems ({problems})")
check(line["sstid"] == "2710000138624" and line["mu"] == "1612" and line["am"] == 10 and line["fee"] == 1_000_000
      and line["prdis"] == 10_000_000 and line["dis"] == 500_000 and line["adis"] == 9_500_000 and line["vra"] == 10
      and line["vam"] == 950_000 and line["tsstam"] == 10_450_000, f"line amounts in rials ({line})")
check(header["inty"] == 1 and header["tob"] == 2 and header["tinb"] == "10101234567" and header["bpc"] == "1234567890"
      and header["tins"] == "10101234567" and header["ins"] == 1 and header["inp"] == 1 and header["setm"] == 2
      and header["tbill"] == 10_450_000 and header["tvam"] == 950_000, f"header: legal buyer, totals ({header})")

draft = invoice(legal, post=False)
check(any("ثبت قطعی" in p for p in moadian.build_payload(draft, company_id)[1]), "a draft invoice cannot be sent")
no_id = invoice(legal, item_id=plain, qty=1)
check(any("کالای بی‌شناسه" in p for p in moadian.build_payload(no_id, company_id)[1]), "an item without a stuff ID is named")
check(raises(lambda: moadian.prepare(no_id, company_id, uid), "شناسهٔ کالا"), "prepare refuses with the reasons")

tax1 = moadian.prepare(inv1, company_id, uid)
days = protocol.invoice_timestamp(today) // 86_400_000
numeric = "A1B2C3".replace("A", "65").replace("B", "66").replace("C", "67") + str(days).zfill(6) + "000000000001"
check(len(tax1) == 22 and tax1.startswith("A1B2C3") and tax1[6:11] == f"{days:05X}" and tax1[11:21] == "0000000001"
      and protocol.verhoeff_valid(numeric + tax1[-1]), f"tax ID: memory, day, serial and Verhoeff digit ({tax1})")
check(raises(lambda: moadian.prepare(inv1, company_id, uid), "قبلاً"), "the same invoice is not prepared twice")
inv2 = invoice(walk_in, qty=2, discount=0)
tax2 = moadian.prepare(inv2, company_id, uid)
stored2 = moadian.get_payload(next(r.moadian_invoice_id for r in moadian.list_documents(company_id, today, today)
                                   if r.document_id == inv2), company_id)
check(stored2["header"]["inty"] == 2 and stored2["header"]["tinb"] is None and stored2["header"]["inno"] == "0000000002"
      and tax2[11:21] == "0000000002", "a walk-in customer gets a type-2 invoice and the next serial")


class FakeServer:
    """نقش سامانه: امضای هر درخواست را با گواهی x5c بررسی و صورتحساب را رمزگشایی می‌کند."""

    def __init__(self):
        self.key, _cert = keypair()
        self.public = base64.b64encode(self.key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).decode()
        self.received, self.calls, self.down = [], [], False

    def _verify(self, token):
        header = json.loads(base64.urlsafe_b64decode(token.split(".")[0] + "=="))
        signer = x509.load_der_x509_certificate(base64.b64decode(header["x5c"][0])).public_key()
        return protocol.jws_payload(token, verify_with=signer)

    def request(self, method, url, params=None, json=None, headers=None, timeout=None):
        if self.down:
            raise ConnectionError("network unreachable")
        endpoint = url.rsplit("/", 1)[1]
        self.calls.append(endpoint)
        if endpoint != "nonce":
            assert self._verify(headers["Authorization"].split(" ", 1)[1])["clientId"] == "A1B2C3"
        if endpoint == "nonce":
            body = {"nonce": "n-1"}
        elif endpoint == "server-information":
            body = {"serverTime": 1, "publicKeys": [{"key": self.public, "id": "kid-1"}]}
        elif endpoint == "invoice":
            result = []
            for packet in json:
                invoice_payload = self._verify(protocol.jwe_decrypt(packet["payload"], self.key))
                self.received.append(invoice_payload)
                result.append({"uid": packet["header"]["requestTraceId"], "referenceNumber": "ref-" + invoice_payload["header"]["taxid"]})
            body = {"result": result}
        elif endpoint == "inquiry-by-uid":
            body = [{"uid": uid_, "status": "SUCCESS" if i == 0 else "FAILED",
                     "data": {"error": [] if i == 0 else [{"code": "011204", "message": "شمارهٔ اقتصادی خریدار نادرست است"}]}}
                    for i, uid_ in enumerate(params["uidList"])]
        else:
            return SimpleNamespace(status_code=404, text="not found", json=lambda: {})
        return SimpleNamespace(status_code=200, text="", json=lambda b=body: b)


server = FakeServer()
server.down = True
check(raises(lambda: moadian.send_prepared(company_id, transport=server), "اتصال"), "a network failure is reported in Persian")
check({r.status for r in moadian.list_documents(company_id, today, today) if r.tax_id} == {"PREPARED"},
      "after a network failure the invoices stay ready to send")
server.down = False
check(moadian.send_prepared(company_id, transport=server) == 2, "both prepared invoices are sent")
check([p["header"]["taxid"] for p in server.received] == [tax1, tax2] and server.received[0]["body"][0]["sstid"] == "2710000138624",
      "the server decrypts and verifies exactly the stored invoices")
check(moadian.send_prepared(company_id, transport=server) == 0, "nothing is sent twice")
check(moadian.check_sent(company_id, transport=server) == 2, "the inquiry settles both invoices")
rows = {r.document_id: r for r in moadian.list_documents(company_id, today, today)}
check(rows[inv1].status == "SUCCESS" and rows[inv2].status == "FAILED" and "011204" in json.dumps(rows[inv2].errors),
      "statuses and the system's error messages are stored")
check(inv1 in rows and draft not in rows, "only posted invoices are listed")

# برگشت از فروش و ابطال
ret1 = invoice(legal, qty=2, discount=0, doc_type="SALES_RETURN", source=inv1)
ret_payload, ret_problems = moadian.build_payload(ret1, company_id)
check(not ret_problems and ret_payload["header"]["ins"] == 4 and ret_payload["header"]["irtaxid"] == tax1,
      f"a return refers to the accepted invoice's tax ID ({ret_problems})")
ret2 = invoice(walk_in, qty=1, discount=0, doc_type="SALES_RETURN", source=inv2)
check(any("پذیرفته" in p for p in moadian.build_payload(ret2, company_id)[1]), "a return of a rejected invoice is blocked")
check(raises(lambda: moadian.prepare_cancel(inv2, company_id, uid), "پذیرفته"), "only an accepted invoice can be cancelled")
cancel = moadian.prepare_cancel(inv1, company_id, uid)
with new_session() as s:
    row = s.scalar(select(MoadianInvoice).where(MoadianInvoice.tax_id == cancel))
check(row.subject_code == 3 and row.related_tax_id == tax1 and row.payload["header"]["ins"] == 3
      and row.payload["header"]["irtaxid"] == tax1 and row.payload["body"] == server.received[0]["body"],
      "the cancellation repeats the invoice with subject 3 and refers to it")
check(raises(lambda: moadian.prepare_cancel(inv1, company_id, uid), "قبلاً"), "a cancellation is not made twice")

# فرم
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QPushButton
qapp = QApplication.instance() or QApplication([])
from peecha.ui.screens.moadian import MoadianScreen

shown = []
QMessageBox.information = staticmethod(lambda *a, **k: shown.append(a[2]) or QMessageBox.Ok)
out = os.path.join(tempfile.mkdtemp(), "invoice.json")
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (out, ""))
screen = MoadianScreen()
screen.refresh()
names = {b.accessibleName() for b in screen.findChildren(QPushButton)}
check({"ارسال همهٔ صورتحساب‌های آماده", "استعلام نتیجه از سامانه"} <= names and screen.table.rowCount() == len(rows) + 2,
      f"the screen lists posted invoices and returns ({screen.table.rowCount()})")
index = next(i for i, r in enumerate(screen.rows) if r.document_id == inv2)
screen.table.selectRow(index)
screen.show_details()
check(shown and "011204" in shown[-1], "the details show the system's error")
index = next(i for i, r in enumerate(screen.rows) if r.document_id == inv1)
screen.table.clearSelection()
screen.table.selectRow(index)
screen.export_selected()
with open(out, encoding="utf-8") as handle:
    exported = json.load(handle)
check(exported["header"]["irtaxid"] == tax1 and exported["header"]["ins"] == 3, "the latest invoice (the cancellation) is exported")
check(screen.memory_field.text() == "A1B2C3" and any(screen.units_table.item(i, 2).text() == "1612"
                                                    for i in range(screen.units_table.rowCount())),
      "the settings tab shows the memory ID and unit codes")

finish()
