import { ApiClient, ApiError } from "../api/client";
import { InMemoryKeyValueStore } from "../storage/keyValueStore";
import { LocalCache } from "../storage/localCache";
import { InvoiceResultStore } from "./invoiceResults";
import { OfflineQueue, PendingAction } from "./offlineQueue";
import { VisitCorrelationStore } from "./visitCorrelation";

export interface PushResult {
  succeeded: string[];
  failedButKept: { idempotencyKey: string; reason: string; documentId?: number }[];
}

/** موتورِ سینک -- طبقِ تصمیمِ طراحی («Pull-latest + Push-queue»، نه
 * CRDTِ کامل): pull همیشه کامل جایگزینِ کشِ محلی می‌شود (سرور-برنده)،
 * push به‌ترتیبِ صف و یکی‌یکی امتحان می‌شود. اگر یک اقدام با خطایِ
 * شبکه (نه خطایِ اعتبارسنجیِ ۴xx) مواجه شود، بقیه‌یِ صف دست‌نخورده
 * می‌ماند تا بارِ بعد (چون معمولاً یعنی اتصال دوباره قطع شده)؛ اگر
 * سرور با خطایِ ۴۰۰/۴۰۴ رد کند (مثلاً ویزیتی که قبلاً تکمیل شده)،
 * آن اقدام به‌عنوانِ «شکست‌خورده ولی حذف‌شده» ثبت می‌شود چون تلاشِ
 * دوباره‌اش هم به همان نتیجه می‌رسد -- کاربر باید در UI مطلع شود.
 *
 * هر درخواستِ ایجادکننده با idempotencyKeyِ خودِ اقدام (یا مشتقی از آن،
 * برایِ نیمه‌یِ دومِ اقدام‌هایِ ترکیبی) به سرور فرستاده می‌شود -- طبقِ
 * R133، سرور با همین کلید تشخیص می‌دهد که آیا این دقیقاً همان درخواستِ
 * قبلی است (پاسخِ گم‌شده در قطعیِ شبکه) یا یک درخواستِ واقعاً جدید. */
export class SyncEngine {
  constructor(
    private readonly api: ApiClient,
    private readonly queue: OfflineQueue,
    private readonly cache: LocalCache,
    // پیش‌فرض فقط برایِ تست‌هایِ موجودی که این وابستگی را نمی‌شناسند
    // (سناریوهایشان customerVisitId مستقیم می‌دهند، نه startActionKey) --
    // در اپِ واقعی، services.ts همیشه نمونه‌یِ مشترکِ رویِ همان kvStore
    // را می‌دهد (وگرنه نگاشت با هر بارِ ساختِ SyncEngine گم می‌شود).
    private readonly visitCorrelation: VisitCorrelationStore = new VisitCorrelationStore(new InMemoryKeyValueStore()),
    private readonly invoiceResults: InvoiceResultStore = new InvoiceResultStore(new InMemoryKeyValueStore()),
  ) {}

  async pull(): Promise<void> {
    const data = await this.api.pullSync();
    await this.cache.savePullResponse(data);
  }

  private inFlightPush: Promise<PushResult> | null = null;

  /** اگر یک ارسالِ صف در جریان است (مثلاً تیکِ خودکارِ پس‌زمینه)، همان
   * را برمی‌گرداند -- دو ارسالِ هم‌زمان ممکن بود یک اقدام را هم‌زمان دوبار
   * بفرستند. */
  pushQueue(): Promise<PushResult> {
    if (this.inFlightPush === null) {
      this.inFlightPush = this.pushQueueOnce().finally(() => {
        this.inFlightPush = null;
      });
    }
    return this.inFlightPush;
  }

  private async pushQueueOnce(): Promise<PushResult> {
    const succeeded: string[] = [];
    const failedButKept: PushResult["failedButKept"] = [];
    const actions = await this.queue.list();

    for (const action of actions) {
      try {
        await this.sendOne(action);
        await this.queue.remove(action.idempotencyKey);
        succeeded.push(action.idempotencyKey);
      } catch (err) {
        if (err instanceof ApiError && err.status >= 400 && err.status < 500) {
          // action ممکن است داخلِ sendOne جهشِ حالت گرفته باشد (مثلاً
          // نیمه‌یِ سفارشِ CREATE_VAN_SALE_DELIVERY موفق شده)؛ نسخه‌یِ
          // فعلی را از خودِ صف می‌خوانیم، نه شیِ آغازینِ حلقه.
          const current = (await this.queue.list()).find((a) => a.idempotencyKey === action.idempotencyKey) ?? action;
          await this.queue.remove(action.idempotencyKey);
          const documentId =
            current.type === "CREATE_VAN_SALE_DELIVERY" ? current.payload.resolvedDocumentId : undefined;
          failedButKept.push({ idempotencyKey: action.idempotencyKey, reason: err.message, documentId });
          continue;
        }
        // خطایِ شبکه/سرور -- توقفِ پردازشِ صف، بقیه برایِ تلاشِ بعدی می‌مانند
        break;
      }
    }
    return { succeeded, failedButKept };
  }

  private async sendOne(action: PendingAction): Promise<void> {
    switch (action.type) {
      case "START_VISIT": {
        const result = await this.api.startVisit(action.payload, action.idempotencyKey);
        // طبقِ رفعِ باگِ واقعی: COMPLETE_VISIT/SKIP_VISIT بعدیِ همین
        // ویزیت (که با startActionKey صف شده باشند) این‌جا resolve
        // می‌شوند -- نگاشت ماندگار است، حتی بعدِ حذفِ این اقدام از صف.
        await this.visitCorrelation.resolve(action.idempotencyKey, result.customer_visit_id);
        return;
      }
      case "COMPLETE_VISIT": {
        const customerVisitId = await this.resolveCustomerVisitId(action.payload);
        await this.api.completeVisit(customerVisitId, action.payload.notes, action.payload.photoBase64);
        return;
      }
      case "SKIP_VISIT": {
        const customerVisitId = await this.resolveCustomerVisitId(action.payload);
        await this.api.skipVisit(customerVisitId, action.payload.skipReason);
        return;
      }
      case "CREATE_ORDER":
        await this.api.createOrder(action.payload, action.idempotencyKey);
        return;
      case "CREATE_DELIVERY_CONFIRMATION":
        await this.api.createDeliveryConfirmation(action.payload, action.idempotencyKey);
        return;
      case "CREATE_PAYMENT":
        await this.api.createPayment(action.payload, action.idempotencyKey);
        return;
      case "CREATE_VAN_SALE_DELIVERY":
        await this.sendVanSaleDelivery(action);
        return;
    }
  }

  private async resolveCustomerVisitId(payload: { customerVisitId?: number; startActionKey?: string }): Promise<number> {
    if (payload.customerVisitId !== undefined) return payload.customerVisitId;
    if (payload.startActionKey) {
      const resolved = await this.visitCorrelation.get(payload.startActionKey);
      if (resolved !== null) return resolved;
    }
    // طبقِ الگویِ خطایِ ۴xx در pushQueue: این اقدام دیگر هیچ‌وقت با
    // تلاشِ دوباره حل نمی‌شود (شروعِ ویزیتِ مرتبط یا هنوز Sync نشده یا
    // خودش قطعاً شکست خورده) -- پس به‌جایِ توقفِ کلِ صف، به‌عنوانِ
    // failedButKept ثبت و از صف حذف می‌شود.
    throw new ApiError(400, "شروعِ ویزیتِ مرتبط هنوز همگام‌سازی نشده است.");
  }

  private async sendVanSaleDelivery(action: Extract<PendingAction, { type: "CREATE_VAN_SALE_DELIVERY" }>): Promise<void> {
    let documentId = action.payload.resolvedDocumentId;
    let lineIds = action.payload.resolvedLineIds;
    if (documentId === undefined || lineIds === undefined) {
      const orderResult = await this.api.createOrder(action.payload.order, action.idempotencyKey);
      documentId = orderResult.document_id;
      lineIds = orderResult.line_ids;
      await this.invoiceResults.record(action.idempotencyKey, {
        documentId,
        documentNo: orderResult.document_no ?? null,
        settlementWarning: orderResult.settlement_warning ?? null,
      });
      // نیمه‌یِ اول موفق شد -- این را همین‌جا در صف ثبت می‌کنیم تا اگر
      // نیمه‌یِ دوم (تاییدِ تحویل) با قطعیِ شبکه مواجه شد، تلاشِ بعدی
      // سفارش را دوباره نسازد.
      await this.queue.update(action.idempotencyKey, {
        ...action,
        payload: { ...action.payload, resolvedDocumentId: documentId, resolvedLineIds: lineIds },
      });
    }
    const lines = action.payload.order.lines.map((line, index) => ({
      document_line_id: lineIds![index],
      delivered_quantity: line.quantity,
    }));
    await this.api.createDeliveryConfirmation(
      { ...action.payload.delivery, document_id: documentId, lines },
      `${action.idempotencyKey}:delivery`,
    );
  }
}
