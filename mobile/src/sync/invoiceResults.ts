import { KeyValueStore } from "../storage/keyValueStore";

const KEY_PREFIX = "peecha.invoice_result.";

export interface InvoiceResult {
  documentId: number;
  documentNo: number | null;
  settlementWarning: string | null;
}

/** فاکتورِ پخشِ گرم از صفِ آفلاین ثبت می‌شود، پس شماره‌یِ واقعیِ فاکتور
 * فقط بعدِ همگام‌سازی معلوم است. این نگاشتِ ماندگار (idempotencyKeyِ
 * اقدام → نتیجهٔ سرور) به صفحهٔ رسید/چاپ اجازه می‌دهد فاکتورِ واقعی را
 * از سرور چاپ کند -- حتی اگر همگام‌سازی چند دقیقه بعد در پس‌زمینه
 * انجام شده باشد. */
export class InvoiceResultStore {
  constructor(private readonly kv: KeyValueStore) {}

  async record(actionKey: string, result: InvoiceResult): Promise<void> {
    await this.kv.setItem(KEY_PREFIX + actionKey, JSON.stringify(result));
  }

  async get(actionKey: string): Promise<InvoiceResult | null> {
    const raw = await this.kv.getItem(KEY_PREFIX + actionKey);
    return raw === null ? null : (JSON.parse(raw) as InvoiceResult);
  }
}
