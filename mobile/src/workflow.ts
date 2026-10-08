/** کمک‌های خالص کارتابل گردش کار (بدون وابستگی به رابط کاربری، قابل تست). */
import { WorkInboxItem, WorkTaskDetail } from "./api/workflowTypes";

export const PATH_STATE_LABEL: Record<string, string> = {
  done: "انجام‌شده",
  current: "در جریان",
  pending: "در انتظار",
  failed: "ناموفق",
};

export type InboxFilter = "ALL" | "APPROVAL" | "TASK" | "OVERDUE" | "MINE";

export const INBOX_FILTERS: { key: InboxFilter; label: string }[] = [
  { key: "ALL", label: "همه" },
  { key: "APPROVAL", label: "تاییدها" },
  { key: "TASK", label: "کارها" },
  { key: "OVERDUE", label: "گذشته از مهلت" },
  { key: "MINE", label: "درخواست‌های من" },
];

export function filterInbox(items: WorkInboxItem[], filter: InboxFilter, requests: WorkInboxItem[] = []): WorkInboxItem[] {
  switch (filter) {
    case "APPROVAL":
      return items.filter((i) => i.kind === "APPROVAL");
    case "TASK":
      return items.filter((i) => i.kind !== "APPROVAL");
    case "OVERDUE":
      return items.filter((i) => i.is_overdue);
    case "MINE":
      return requests;
    default:
      return items;
  }
}

/** رنگ معنایی هر نوع کار (کلید پالت تم) -- برای نوار و نشان کارت. */
export type ToneColor = "info" | "success" | "warning" | "danger" | "primary";

export function toneColor(tone: string | undefined): ToneColor {
  switch (tone) {
    case "approve":
      return "info";
    case "customer":
      return "success";
    case "followup":
      return "warning";
    case "doc":
    case "task":
    case "mine":
    default:
      return "primary";
  }
}

export type Urgency = "overdue" | "today" | "high" | "normal";

/** فوریت کارت: رنگ نوار کنار کارت و نشان مهلت. */
export function urgencyOf(item: Pick<WorkInboxItem, "is_overdue" | "due_at" | "priority_code">, now: Date = new Date()): Urgency {
  if (item.is_overdue) return "overdue";
  if (item.due_at) {
    const due = new Date(item.due_at);
    if (due.getFullYear() === now.getFullYear() && due.getMonth() === now.getMonth() && due.getDate() === now.getDate()) {
      return "today";
    }
  }
  if (item.priority_code === "HIGH" || item.priority_code === "CRITICAL") return "high";
  return "normal";
}

export const URGENCY_COLOR: Record<Urgency, ToneColor> = { overdue: "danger", today: "warning", high: "warning", normal: "primary" };

/** متن کوتاه مهلت روی کارت (بدون تاریخ کامل؛ تاریخ جلالی جدا نشان داده می‌شود). */
export function dueLabel(item: Pick<WorkInboxItem, "is_overdue" | "due_at">, now: Date = new Date()): string | null {
  if (!item.due_at) return null;
  const due = new Date(item.due_at);
  if (item.is_overdue) {
    const days = Math.floor((now.getTime() - due.getTime()) / 86_400_000);
    return days >= 1 ? `${days} روز گذشته` : "گذشته از مهلت";
  }
  if (urgencyOf({ is_overdue: false, due_at: item.due_at, priority_code: "NORMAL" }, now) === "today") return "موعد امروز";
  return null;
}

/** دکمهٔ اصلی هر کارت: چه کاری با یک لمس ممکن است. */
export type CardAction = "DECIDE_INLINE" | "OPEN_TASK" | "OPEN_CUSTOMER" | "OPEN_FOLLOWUPS" | "DESKTOP_ONLY" | "WAITING";

export function cardAction(item: Pick<WorkInboxItem, "source" | "quick">): CardAction {
  switch (item.source) {
    case "CARTABLE":
      return "DECIDE_INLINE";
    case "WF":
      return "OPEN_TASK";
    case "CUSTOMER":
      return "OPEN_CUSTOMER";
    case "CRM":
      return "OPEN_FOLLOWUPS";
    case "MINE":
      return "WAITING";
    default:
      return "DESKTOP_ONLY";
  }
}

/** تایید کار حساس فقط آنلاین و با رمز انجام می‌شود (رمز هرگز در صف آفلاین ذخیره نمی‌شود). */
export function needsStepUp(detail: Pick<WorkTaskDetail, "requires_step_up">, decision: string): boolean {
  return detail.requires_step_up && (decision === "APPROVE" || decision === "DONE");
}

/** رد و برگشت برای اصلاح بدون توضیح پذیرفته نمی‌شود. */
export function needsComment(decision: string): boolean {
  return decision === "REJECT" || decision === "CHANGES";
}

export function pathText(path: WorkTaskDetail["path"]): string {
  return path.map((p) => `${p.label} (${PATH_STATE_LABEL[p.state] ?? p.state})`).join(" ← ");
}
