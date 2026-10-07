import { KeyValueStore } from "../storage/keyValueStore";
import {
  CustomerCreateRequest,
  DeliveryConfirmationRequest,
  OrderCreateRequest,
  PaymentCreateRequest,
  StartVisitRequest,
  StockTransferRequest,
} from "../api/types";
import { CrmActivityCompleteRequest, CrmActivityRequest, CrmLeadRequest, CrmTicketRequest } from "../api/crmTypes";
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
  | {
      idempotencyKey: string;
      createdAt: string;
      type: "COMPLETE_VISIT";
      // customerVisitId مستقیم: وقتی شناسه از قبل معلوم است (مثلاً فراخوانیِ
      // برنامه‌ای/تست). startActionKey: رفعِ باگِ واقعی -- وقتی صفحه‌یِ
      // ویزیت این را صف می‌کند، شناسهٔ واقعی هنوز معلوم نیست (فقط بعدِ
      // Syncِ موفقِ START_VISIT مشخص می‌شود)؛ SyncEngine از رویِ
      // VisitCorrelationStore آن را resolve می‌کند.
      // طبقِ درخواستِ صریحِ کاربر («برای ویزیت پخش سرد هم ویزیت و عکس و
      // سفارش باشه» + امضا طبقِ گزارشِ کاربر): عکس/امضایِ اختیاریِ
      // ویزیت -- برایِ هر دو نوعِ پخش.
      payload: {
        customerVisitId?: number; startActionKey?: string; notes?: string;
        photoBase64?: string | null; signatureBase64?: string | null;
      };
    }
  | {
      idempotencyKey: string;
      createdAt: string;
      type: "SKIP_VISIT";
      payload: { customerVisitId?: number; startActionKey?: string; skipReason: string };
    }
  | { idempotencyKey: string; createdAt: string; type: "CREATE_ORDER"; payload: OrderCreateRequest }
  | { idempotencyKey: string; createdAt: string; type: "CREATE_DELIVERY_CONFIRMATION"; payload: DeliveryConfirmationRequest }
  | { idempotencyKey: string; createdAt: string; type: "CREATE_VAN_SALE_DELIVERY"; payload: VanSaleDeliveryPayload }
  | { idempotencyKey: string; createdAt: string; type: "CREATE_PAYMENT"; payload: PaymentCreateRequest }
  | { idempotencyKey: string; createdAt: string; type: "CREATE_CUSTOMER"; payload: CustomerCreateRequest }
  // R249: عملیاتِ انبار (اپِ انباردار)
  | { idempotencyKey: string; createdAt: string; type: "WMS_TRANSFER"; payload: StockTransferRequest }
  | { idempotencyKey: string; createdAt: string; type: "WMS_PUTAWAY"; payload: { taskId: number; toLocationId: number } }
  | { idempotencyKey: string; createdAt: string; type: "WMS_PICK"; payload: { taskId: number; quantity: string } }
  | { idempotencyKey: string; createdAt: string; type: "WMS_REPLENISH"; payload: { taskId: number; quantity: string | null } }
  | { idempotencyKey: string; createdAt: string; type: "WMS_COUNT"; payload: { sessionId: number; locationId: number; itemId: number; quantity: string; batchNo?: string | null } }
  | { idempotencyKey: string; createdAt: string; type: "WMS_SERIAL_COUNT"; payload: { sessionId: number; locationId: number; itemId: number; serialNos: string[] } }
  // R286: CRM میدانی
  | { idempotencyKey: string; createdAt: string; type: "CRM_CREATE_LEAD"; payload: CrmLeadRequest }
  | { idempotencyKey: string; createdAt: string; type: "CRM_CREATE_ACTIVITY"; payload: CrmActivityRequest & { visitStartActionKey?: string } }
  | { idempotencyKey: string; createdAt: string; type: "CRM_COMPLETE_ACTIVITY"; payload: { activityId: number } & CrmActivityCompleteRequest }
  | { idempotencyKey: string; createdAt: string; type: "CRM_CREATE_TICKET"; payload: CrmTicketRequest };

export type PendingActionInput =
  | Omit<Extract<PendingAction, { type: "START_VISIT" }>, "idempotencyKey" | "createdAt">
  | Omit<Extract<PendingAction, { type: "COMPLETE_VISIT" }>, "idempotencyKey" | "createdAt">
  | Omit<Extract<PendingAction, { type: "SKIP_VISIT" }>, "idempotencyKey" | "createdAt">
  | Omit<Extract<PendingAction, { type: "CREATE_ORDER" }>, "idempotencyKey" | "createdAt">
  | Omit<Extract<PendingAction, { type: "CREATE_DELIVERY_CONFIRMATION" }>, "idempotencyKey" | "createdAt">
  | Omit<Extract<PendingAction, { type: "CREATE_VAN_SALE_DELIVERY" }>, "idempotencyKey" | "createdAt">
  | Omit<Extract<PendingAction, { type: "CREATE_PAYMENT" }>, "idempotencyKey" | "createdAt">
  | Omit<Extract<PendingAction, { type: "CREATE_CUSTOMER" }>, "idempotencyKey" | "createdAt">
  | Omit<Extract<PendingAction, { type: "WMS_TRANSFER" }>, "idempotencyKey" | "createdAt">
  | Omit<Extract<PendingAction, { type: "WMS_PUTAWAY" }>, "idempotencyKey" | "createdAt">
  | Omit<Extract<PendingAction, { type: "WMS_PICK" }>, "idempotencyKey" | "createdAt">
  | Omit<Extract<PendingAction, { type: "WMS_REPLENISH" }>, "idempotencyKey" | "createdAt">
  | Omit<Extract<PendingAction, { type: "WMS_COUNT" }>, "idempotencyKey" | "createdAt">
  | Omit<Extract<PendingAction, { type: "WMS_SERIAL_COUNT" }>, "idempotencyKey" | "createdAt">
  | Omit<Extract<PendingAction, { type: "CRM_CREATE_LEAD" }>, "idempotencyKey" | "createdAt">
  | Omit<Extract<PendingAction, { type: "CRM_CREATE_ACTIVITY" }>, "idempotencyKey" | "createdAt">
  | Omit<Extract<PendingAction, { type: "CRM_COMPLETE_ACTIVITY" }>, "idempotencyKey" | "createdAt">
  | Omit<Extract<PendingAction, { type: "CRM_CREATE_TICKET" }>, "idempotencyKey" | "createdAt">;

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

  /** طبقِ باگِ واقعیِ کشف‌شده رویِ دستگاهِ فیزیکی: اگر یک آیتمِ صف قبلاً
   * (پیش از رفعِ باگِ اندازهٔ عکس) خیلی بزرگ ذخیره شده باشد، حتی خودِ
   * kv.getItem هم شکست می‌خورد ("Row too big to fit into CursorWindow")
   * -- یعنی readAll غیرِقابل‌استفاده می‌شود و صف برایِ همیشه قفل
   * می‌ماند. این متد بدونِ نیاز به خواندن/parseِ مقدارِ فعلی، مستقیم
   * کلیدِ صف را حذف می‌کند -- تنها راهِ بازیابی از چنین حالتی. */
  async clear(): Promise<void> {
    await this.kv.removeItem(QUEUE_KEY);
  }
}
