import { ApiClient, ApiError } from "../api/client";
import { LocalCache } from "../storage/localCache";
import { OfflineQueue, PendingAction } from "./offlineQueue";

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
  ) {}

  async pull(): Promise<void> {
    const data = await this.api.pullSync();
    await this.cache.savePullResponse(data);
  }

  async pushQueue(): Promise<PushResult> {
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
      case "START_VISIT":
        await this.api.startVisit(action.payload, action.idempotencyKey);
        return;
      case "COMPLETE_VISIT":
        await this.api.completeVisit(action.payload.customerVisitId, action.payload.notes);
        return;
      case "SKIP_VISIT":
        await this.api.skipVisit(action.payload.customerVisitId, action.payload.skipReason);
        return;
      case "CREATE_ORDER":
        await this.api.createOrder(action.payload, action.idempotencyKey);
        return;
      case "CREATE_DELIVERY_CONFIRMATION":
        await this.api.createDeliveryConfirmation(action.payload, action.idempotencyKey);
        return;
      case "CREATE_VAN_SALE_DELIVERY":
        await this.sendVanSaleDelivery(action);
        return;
    }
  }

  private async sendVanSaleDelivery(action: Extract<PendingAction, { type: "CREATE_VAN_SALE_DELIVERY" }>): Promise<void> {
    let documentId = action.payload.resolvedDocumentId;
    let lineIds = action.payload.resolvedLineIds;
    if (documentId === undefined || lineIds === undefined) {
      const orderResult = await this.api.createOrder(action.payload.order, action.idempotencyKey);
      documentId = orderResult.document_id;
      lineIds = orderResult.line_ids;
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
