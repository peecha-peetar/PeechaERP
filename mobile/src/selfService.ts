import { SelfLeaveRequest, SelfTimesheetRequest } from "./api/selfTypes";
import { toAsciiDigits } from "./format";
import { parseJalaliDate, todayIsoDate } from "./jalali";

/** R360: منطقِ خالصِ سلف‌سرویس کارمند (بدونِ UI، قابلِ آزمون). */

export const JALALI_MONTHS = [
  "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
];

const PERSIAN_DIGITS = ["۰", "۱", "۲", "۳", "۴", "۵", "۶", "۷", "۸", "۹"];

export function toPersianDigits(text: string | number): string {
  return String(text).replace(/[0-9]/g, (d) => PERSIAN_DIGITS[Number(d)]);
}

/** «فروردین ۱۴۰۵» */
export function payslipTitle(row: { jalali_year: number; jalali_month: number }): string {
  return `${JALALI_MONTHS[row.jalali_month - 1] ?? row.jalali_month} ${toPersianDigits(row.jalali_year)}`;
}

/** «۱ ساعت و ۵ دقیقه» یا «۲۰ دقیقه»؛ صفر = خالی */
export function minutesLabel(minutes: number): string {
  if (!minutes) return "";
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (!h) return `${toPersianDigits(m)} دقیقه`;
  return m ? `${toPersianDigits(h)} ساعت و ${toPersianDigits(m)} دقیقه` : `${toPersianDigits(h)} ساعت`;
}

export interface LeaveForm {
  leaveType: string;
  fromText: string;
  toText: string;
  hoursText: string;
  reason: string;
}

/** فرمِ مرخصی → بدنهٔ درخواست، یا پیامِ خطا برایِ کاربر (تاریخ‌ها شمسی). */
export function buildLeaveRequest(form: LeaveForm): { payload: SelfLeaveRequest } | { error: string } {
  if (!form.leaveType) return { error: "نوع مرخصی را انتخاب کنید." };
  const from = parseJalaliDate(form.fromText);
  if (!from) return { error: "تاریخ شروع نامعتبر است (مثلاً ۱۴۰۵/۰۸/۱۵)." };
  const to = form.toText.trim() ? parseJalaliDate(form.toText) : from;
  if (!to) return { error: "تاریخ پایان نامعتبر است." };
  if (to < from) return { error: "تاریخ پایان نباید پیش از تاریخ شروع باشد." };
  let hours: string | null = null;
  if (form.leaveType === "HOURLY") {
    hours = toAsciiDigits(form.hoursText).replace("٫", ".");
    const n = Number(hours);
    if (!hours || !Number.isFinite(n) || n <= 0 || n > 24) return { error: "تعداد ساعت مرخصی را درست وارد کنید." };
    if (to !== from) return { error: "مرخصی ساعتی فقط برای یک روز است." };
  }
  return { payload: { leave_type: form.leaveType, from_date: from, to_date: to, hours, reason: form.reason.trim() } };
}

export interface TimesheetForm {
  projectId: number | null;
  taskId: number | null;
  dateText: string;
  hoursText: string;
  description: string;
}

/** R364: فرمِ کارکردِ پروژه → بدنهٔ درخواست، یا پیامِ خطا (روزِ خالی = امروز). */
export function buildTimesheetRequest(form: TimesheetForm, today: string = todayIsoDate()): { payload: SelfTimesheetRequest } | { error: string } {
  if (form.projectId === null) return { error: "پروژه را انتخاب کنید." };
  const day = form.dateText.trim() ? parseJalaliDate(form.dateText) : today;
  if (!day) return { error: "روز کارکرد نامعتبر است (مثلاً ۱۴۰۵/۰۸/۱۵)." };
  if (day > today) return { error: "روز کارکرد نمی‌تواند بعد از امروز باشد." };
  const hours = toAsciiDigits(form.hoursText).replace("٫", ".").trim();
  const n = Number(hours);
  if (!hours || !Number.isFinite(n) || n <= 0 || n > 24) return { error: "ساعت کارکرد را بین ۰ و ۲۴ وارد کنید." };
  return { payload: { project_id: form.projectId, task_id: form.taskId, work_date: day, hours, description: form.description.trim() } };
}
