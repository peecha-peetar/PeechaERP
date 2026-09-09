import { ApiClient, ApiError } from "../api/client";
import { LocalCache } from "../storage/localCache";
import { OfflineQueue, PendingAction } from "./offlineQueue";

export interface PushResult {
  succeeded: string[];
  failedButKept: { idempotencyKey: string; reason: string }[];
}

/** موتورِ سینک -- طبقِ تصمیمِ طراحی («Pull-latest + Push-queue»، نه
 * CRDTِ کامل): pull همیشه کامل جایگزینِ کشِ محلی می‌شود (سرور-برنده)،
 * push به‌ترتیبِ صف و یکی‌یکی امتحان می‌شود. اگر یک اقدام با خطایِ
 * شبکه (نه خطایِ اعتبارسنجیِ ۴xx) مواجه شود، بقیه‌یِ صف دست‌نخورده
 * می‌ماند تا بارِ بعد (چون معمولاً یعنی اتصال دوباره قطع شده)؛ اگر
 * سرور با خطایِ ۴۰۰/۴۰۴ رد کند (مثلاً ویزیتی که قبلاً تکمیل شده)،
 * آن اقدام به‌عنوانِ «شکست‌خورده ولی حذف‌شده» ثبت می‌شود چون تلاشِ
 * دوباره‌اش هم به همان نتیجه می‌رسد -- کاربر باید در UI مطلع شود. */
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
    const failedButKept: { idempotencyKey: string; reason: string }[] = [];
    const actions = await this.queue.list();

    for (const action of actions) {
      try {
        await this.sendOne(action);
        await this.queue.remove(action.idempotencyKey);
        succeeded.push(action.idempotencyKey);
      } catch (err) {
        if (err instanceof ApiError && err.status >= 400 && err.status < 500) {
          await this.queue.remove(action.idempotencyKey);
          failedButKept.push({ idempotencyKey: action.idempotencyKey, reason: err.message });
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
        await this.api.startVisit(action.payload);
        return;
      case "COMPLETE_VISIT":
        await this.api.completeVisit(action.payload.customerVisitId, action.payload.notes);
        return;
      case "SKIP_VISIT":
        await this.api.skipVisit(action.payload.customerVisitId, action.payload.skipReason);
        return;
      case "CREATE_ORDER":
        await this.api.createOrder(action.payload);
        return;
      case "CREATE_DELIVERY_CONFIRMATION":
        await this.api.createDeliveryConfirmation(action.payload);
        return;
    }
  }
}
