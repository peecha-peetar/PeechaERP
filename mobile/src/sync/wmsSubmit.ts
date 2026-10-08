import { OfflineQueue, PendingActionInput } from "./offlineQueue";
import { SyncEngine } from "./syncEngine";

export type WmsSubmitOutcome =
  | { status: "DONE" }
  | { status: "QUEUED" }
  | { status: "REJECTED"; reason: string };

/** عملیاتِ انبار هم مثلِ بقیهٔ نوشتن‌ها از صفِ آفلاین می‌رود، ولی انباردار باید فوراً بداند
 * ثبت شد، در صف ماند (بی‌اینترنت) یا سرور رد کرد (مثلاً محلِ مسدود یا ظرفیتِ ناکافی). */
export async function submitWmsAction(
  queue: OfflineQueue,
  engine: SyncEngine,
  input: PendingActionInput,
): Promise<WmsSubmitOutcome> {
  const action = await queue.enqueue(input);
  let result;
  try {
    result = await engine.pushQueue();
  } catch {
    return { status: "QUEUED" };
  }
  if (result.succeeded.includes(action.idempotencyKey)) return { status: "DONE" };
  const failed = result.failedButKept.find((f) => f.idempotencyKey === action.idempotencyKey);
  if (failed) return { status: "REJECTED", reason: failed.reason };
  return { status: "QUEUED" };
}
