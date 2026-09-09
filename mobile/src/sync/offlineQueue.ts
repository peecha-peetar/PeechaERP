import { KeyValueStore } from "../storage/keyValueStore";
import { generateIdempotencyKey } from "./idempotency";
import {
  DeliveryConfirmationRequest,
  OrderCreateRequest,
  StartVisitRequest,
} from "../api/types";

const QUEUE_KEY = "peecha.offline_queue";

export type PendingAction =
  | { idempotencyKey: string; createdAt: string; type: "START_VISIT"; payload: StartVisitRequest }
  | { idempotencyKey: string; createdAt: string; type: "COMPLETE_VISIT"; payload: { customerVisitId: number; notes?: string } }
  | { idempotencyKey: string; createdAt: string; type: "SKIP_VISIT"; payload: { customerVisitId: number; skipReason: string } }
  | { idempotencyKey: string; createdAt: string; type: "CREATE_ORDER"; payload: OrderCreateRequest }
  | { idempotencyKey: string; createdAt: string; type: "CREATE_DELIVERY_CONFIRMATION"; payload: DeliveryConfirmationRequest };

export type PendingActionInput =
  | Omit<Extract<PendingAction, { type: "START_VISIT" }>, "idempotencyKey" | "createdAt">
  | Omit<Extract<PendingAction, { type: "COMPLETE_VISIT" }>, "idempotencyKey" | "createdAt">
  | Omit<Extract<PendingAction, { type: "SKIP_VISIT" }>, "idempotencyKey" | "createdAt">
  | Omit<Extract<PendingAction, { type: "CREATE_ORDER" }>, "idempotencyKey" | "createdAt">
  | Omit<Extract<PendingAction, { type: "CREATE_DELIVERY_CONFIRMATION" }>, "idempotencyKey" | "createdAt">;

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

  async size(): Promise<number> {
    return (await this.readAll()).length;
  }
}
