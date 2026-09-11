import { KeyValueStore } from "../storage/keyValueStore";
import {
  DeliveryConfirmationRequest,
  OrderCreateRequest,
  StartVisitRequest,
} from "../api/types";
import { generateIdempotencyKey } from "./idempotency";

const QUEUE_KEY = "peecha.offline_queue";

/** پیامدِ سفارش+تاییدِ تحویلِ پخشِ گرم (ون‌سیلز) به‌عنوانِ یک اقدامِ
 * ترکیبیِ واحد -- طبقِ نیازِ R133 («Proof of Delivery + آفلاینِ کامل»):
 * تاییدِ تحویل به document_id نیاز دارد که فقط بعدِ موفقیتِ واقعیِ
 * ثبتِ سفارش رویِ سرور مشخص می‌شود؛ پس این دو نمی‌توانند دو اقدامِ
 * مستقلِ صف باشند (تاییدِ تحویل قبل از آماده‌شدنِ document_id بی‌معناست).
 * resolvedDocumentId وقتی که نیمه‌یِ اولِ این اقدام (ثبتِ سفارش) موفق
 * شد پر می‌شود -- اگر بعدِ آن نیمه‌یِ دوم (تاییدِ تحویل) با خطایِ شبکه
 * مواجه شد، این مقدار در صف نگه داشته می‌شود تا تلاشِ بعدی، سفارش را
 * دوباره نسازد و فقط تاییدِ تحویل را دوباره امتحان کند. */
export type VanSaleDeliveryPayload = {
  order: OrderCreateRequest;
  /** lines عمداً حذف شده: document_line_id فقط بعدِ ثبتِ سفارش مشخص
   * می‌شود (resolvedLineIds) -- SyncEngine در لحظه‌یِ ارسال، ردیف‌هایِ
   * تاییدِ تحویل را از رویِ order.lines + resolvedLineIds می‌سازد
   * (تحویلِ کاملِ همان مقدارِ سفارش‌داده‌شده، بدونِ کسری -- ثبتِ کسریِ
   * جزئی‌به‌جزئی در این نسخه‌یِ اسکلتی پیاده نشده، کارِ آینده است). */
  delivery: Omit<DeliveryConfirmationRequest, "document_id" | "lines">;
  resolvedDocumentId?: number;
  resolvedLineIds?: number[];
};

export type PendingAction =
  | { idempotencyKey: string; createdAt: string; type: "START_VISIT"; payload: StartVisitRequest }
  | { idempotencyKey: string; createdAt: string; type: "COMPLETE_VISIT"; payload: { customerVisitId: number; notes?: string } }
  | { idempotencyKey: string; createdAt: string; type: "SKIP_VISIT"; payload: { customerVisitId: number; skipReason: string } }
  | { idempotencyKey: string; createdAt: string; type: "CREATE_ORDER"; payload: OrderCreateRequest }
  | { idempotencyKey: string; createdAt: string; type: "CREATE_DELIVERY_CONFIRMATION"; payload: DeliveryConfirmationRequest }
  | { idempotencyKey: string; createdAt: string; type: "CREATE_VAN_SALE_DELIVERY"; payload: VanSaleDeliveryPayload };

export type PendingActionInput =
  | Omit<Extract<PendingAction, { type: "START_VISIT" }>, "idempotencyKey" | "createdAt">
  | Omit<Extract<PendingAction, { type: "COMPLETE_VISIT" }>, "idempotencyKey" | "createdAt">
  | Omit<Extract<PendingAction, { type: "SKIP_VISIT" }>, "idempotencyKey" | "createdAt">
  | Omit<Extract<PendingAction, { type: "CREATE_ORDER" }>, "idempotencyKey" | "createdAt">
  | Omit<Extract<PendingAction, { type: "CREATE_DELIVERY_CONFIRMATION" }>, "idempotencyKey" | "createdAt">
  | Omit<Extract<PendingAction, { type: "CREATE_VAN_SALE_DELIVERY" }>, "idempotencyKey" | "createdAt">;

/** صفِ اقدام‌هایِ آفلاین -- الگویِ pull-latest + push-queue طبقِ سندِ
 * معماری: هر اقدامِ کاربر (شروع/تکمیل/ردِ ویزیت، ثبتِ سفارش، تاییدِ
 * تحویل) وقتی که اینترنت نیست، این‌جا صف می‌شود؛ به‌محضِ اتصال، از
 * ابتدایِ صف (به‌ترتیبِ ایجاد) یکی‌یکی به سرور فرستاده می‌شود. */
export class OfflineQueue {
  constructor(private readonly kv: KeyValueStore) {}

  private async readAll(): Promise<PendingAction[]> {
    const raw = await this.kv.getItem(QUEUE_KEY);
    if (raw === null) return [];
    return JSON.parse(raw) as PendingAction[];
  }

  private async writeAll(actions: PendingAction[]): Promise<void> {
    await this.kv.setItem(QUEUE_KEY, JSON.stringify(actions));
  }

  async enqueue(input: PendingActionInput): Promise<PendingAction> {
    const action = {
      ...input,
      idempotencyKey: generateIdempotencyKey(),
      createdAt: new Date().toISOString(),
    } as PendingAction;
    const actions = await this.readAll();
    actions.push(action);
    await this.writeAll(actions);
    return action;
  }

  async list(): Promise<PendingAction[]> {
    return this.readAll();
  }

  async remove(idempotencyKey: string): Promise<void> {
    const actions = await this.readAll();
    await this.writeAll(actions.filter((a) => a.idempotencyKey !== idempotencyKey));
  }

  /** جایگزینیِ یک اقدام در همان جایگاهِ صف (ترتیب حفظ می‌شود) -- برایِ
   * ثبتِ پیشرفتِ جزئیِ CREATE_VAN_SALE_DELIVERY (پس از موفقیتِ نیمه‌یِ
   * سفارش) بدونِ از دست‌دادنِ جایگاهِ آن در صف. */
  async update(idempotencyKey: string, updated: PendingAction): Promise<void> {
    const actions = await this.readAll();
    const index = actions.findIndex((a) => a.idempotencyKey === idempotencyKey);
    if (index === -1) return;
    actions[index] = updated;
    await this.writeAll(actions);
  }

  async size(): Promise<number> {
    return (await this.readAll()).length;
  }
}
