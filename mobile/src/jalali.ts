import { toJalaali } from "jalaali-js";

const PERSIAN_DIGITS = ["۰", "۱", "۲", "۳", "۴", "۵", "۶", "۷", "۸", "۹"];

function toPersianDigits(text: string): string {
  return text.replace(/[0-9]/g, (d) => PERSIAN_DIGITS[Number(d)]);
}

function pad2(n: number): string {
  return n < 10 ? `0${n}` : String(n);
}

/** طبقِ همان قراردادِ نمایشِ تاریخِ نسخه‌یِ دسکتاپ (numerals.py،
 * format_jalali_date): YYYY/MM/DD با ارقامِ فارسی. ورودی همیشه یک
 * تاریخِ خالصِ ISO («YYYY-MM-DD»، بدونِ زمان) از peecha_api است --
 * عمداً با تجزیه‌یِ رشته‌ای (نه new Date(...)) پردازش می‌شود تا از
 * جابه‌جاییِ روز به‌خاطرِ تبدیلِ UTC/منطقه‌یِ‌زمانیِ محلیِ گوشی جلوگیری
 * شود. */
export function formatJalaliDate(isoDate: string): string {
  const [y, m, d] = isoDate.split("T")[0].split("-").map(Number);
  if (!y || !m || !d) return isoDate;
  const { jy, jm, jd } = toJalaali(y, m, d);
  return toPersianDigits(`${jy}/${pad2(jm)}/${pad2(jd)}`);
}

/** معادلِ format_jalali_datetime دسکتاپ -- تاریخِ شمسی + ساعت:دقیقه
 * (بدونِ ثانیه)، با فرضِ این‌که رشته‌یِ ورودی همان زمانِ محلیِ سرور است
 * (بدونِ تبدیلِ منطقه‌یِ‌زمانی -- طبقِ همان رفتارِ numerals.py برایِ
 * datetimeِ بدونِ tzinfo). */
export function formatJalaliDateTime(isoDateTime: string): string {
  const [datePart, timePart] = isoDateTime.split("T");
  const dateLabel = formatJalaliDate(datePart);
  if (!timePart) return dateLabel;
  const [hh, mm] = timePart.split(":");
  return `${dateLabel} ${toPersianDigits(`${hh}:${mm}`)}`;
}
