/** کمک‌های خالص کارتابل گردش کار (بدون وابستگی به رابط کاربری، قابل تست). */
import { WorkInboxItem, WorkTaskDetail } from "./api/workflowTypes";

export const PATH_STATE_LABEL: Record<string, string> = {
  done: "انجام‌شده",
  current: "در جریان",
  pending: "در انتظار",
  failed: "ناموفق",
};

export type InboxFilter = "ALL" | "APPROVAL" | "TASK" | "OVERDUE";

export const INBOX_FILTERS: { key: InboxFilter; label: string }[] = [
  { key: "ALL", label: "همه" },
  { key: "APPROVAL", label: "تاییدها" },
  { key: "TASK", label: "کارها" },
  { key: "OVERDUE", label: "گذشته از مهلت" },
];

export function filterInbox(items: WorkInboxItem[], filter: InboxFilter): WorkInboxItem[] {
  switch (filter) {
    case "APPROVAL":
      return items.filter((i) => i.kind === "APPROVAL");
    case "TASK":
      return items.filter((i) => i.kind !== "APPROVAL");
    case "OVERDUE":
      return items.filter((i) => i.is_overdue);
    default:
      return items;
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
