/** فرمتِ سادهٔ مبلغ برایِ نمایش (جداکننده‌یِ هزارگان، LTR) -- طبقِ اصلِ
 * typography.numeric: مبلغ همیشه چپ‌به‌راست نمایش داده می‌شود. ورودی از
 * API رشته است (decimal.Decimal سمتِ سرور) تا خطایِ گردکردنِ اعشاریِ
 * float در جاوااسکریپت پیش نیاید؛ فقط همین‌جا، فقط برایِ نمایش، به عدد
 * تبدیل می‌شود. */
export function formatAmount(value: string): string {
  const n = Number(value);
  if (Number.isNaN(n)) return value;
  return n.toLocaleString("en-US", { maximumFractionDigits: 0 });
}

/** کیبوردِ فارسی ارقامِ ۰-۹ (یا عربیِ ٠-٩) می‌فرستد -- پیش از هر
 * محاسبه/ارسال به سرور، به ارقامِ لاتین و بدونِ جداکنندهٔ هزارگان تبدیل می‌شود. */
export function toAsciiDigits(text: string): string {
  return text
    .replace(/[۰-۹]/g, (d) => String(d.charCodeAt(0) - 0x06f0))
    .replace(/[٠-٩]/g, (d) => String(d.charCodeAt(0) - 0x0660))
    .replace(/[,٬،\s]/g, "");
}

/** مقدارِ عددیِ یک فیلدِ مبلغ/تعداد (با ارقامِ فارسی هم) -- نامعتبر = ۰. */
export function parseAmount(text: string): number {
  const n = Number(toAsciiDigits(text));
  return Number.isFinite(n) ? n : 0;
}
