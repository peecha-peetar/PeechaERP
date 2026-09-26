import { ColorPalette } from "./colors";

/** نگاشتِ وضعیت -> رنگِ معنایی -- تکِ منبعِ حقیقت برایِ StatusBadge،
 * تا هر صفحه (سفارش/وصول/Sync/ویزیت) به‌جایِ رنگِ دستی از همین نگاشت
 * استفاده کند و رنگ‌ها بینِ صفحه‌ها ناهماهنگ نشوند. کدهایِ وضعیت دقیقاً
 * هم‌نامِ enum های سمتِ سرور/صف‌آفلاین (Pending/Syncing/Synced/Failed/
 * Conflict) + وضعیت‌هایِ دامنه‌ایِ رایج (Active/PendingApproval/...) هستند
 * تا نگاشت مستقیم و بدونِ ترجمه‌یِ اضافه باشد. */
export type StatusTone = "neutral" | "info" | "success" | "warning" | "danger";

const STATUS_TONE_MAP: Record<string, StatusTone> = {
  PENDING: "neutral",
  NOT_STARTED: "neutral",
  IN_PROGRESS: "info",
  SYNCING: "info",
  SYNCED: "success",
  FAILED: "danger",
  CONFLICT: "warning",
  ACTIVE: "success",
  PENDING_APPROVAL: "warning",
  SUSPENDED: "danger",
  BLACKLISTED: "danger",
  INACTIVE: "neutral",
  OVERDUE: "danger",
  DRAFT: "neutral",
  CONFIRMED: "info",
  APPROVED: "success",
  POSTED: "success",
  CANCELLED: "danger",
  DONE: "success",
  // طبقِ بازطراحیِ Customer360Screen (بازخوردِ کاربر رویِ R220): وضعیت‌هایِ
  // ضمانت/فعالیتِ CRM هم از همین نگاشتِ مشترکِ رنگ استفاده کنند.
  OPEN: "warning",
  RESOLVED: "success",
  WON: "success",
  LOST: "danger",
  RELEASED: "success",
  CALLED: "danger",
  EXPIRED: "neutral",
  // سگمنتِ مشتری (commercial_documents.compute_customer_segment).
  NEW: "info",
  LOYAL: "success",
  LOW_PURCHASE: "warning",
  AT_RISK: "warning",
  DEBTOR: "danger",
  VIP: "success",
};

export function statusTone(statusCode: string): StatusTone {
  return STATUS_TONE_MAP[statusCode] ?? "neutral";
}

export function toneColor(tone: StatusTone, colors: ColorPalette): { bg: string; fg: string } {
  switch (tone) {
    case "success":
      return { bg: colors.successSoft, fg: colors.success };
    case "warning":
      return { bg: colors.warningSoft, fg: colors.warning };
    case "danger":
      return { bg: colors.dangerSoft, fg: colors.danger };
    case "info":
      return { bg: colors.infoSoft, fg: colors.info };
    default:
      return { bg: colors.surfaceAlt, fg: colors.textSecondary };
  }
}
