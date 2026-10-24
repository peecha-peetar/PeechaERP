import { ApiError } from "./api/client";
import { toAsciiDigits } from "./format";

export const DEFAULT_API_PORT = 8000;
const EXPO_PORT = "8081";

/** آدرس سرور را از شکل‌های رایجِ تایپ کامل می‌کند:
 * «۱۹۲٫۱۶۸٫۱٫۱۰» → «http://192.168.1.10:8000»؛ آدرسِ Expo (exp://…:8081) هم به پورتِ سرور برگردانده می‌شود. */
export function normalizeServerUrl(raw: string): string {
  let url = toAsciiDigits(raw).replace(/[٫۔]/g, ".").trim();
  if (!url) return "";
  url = url.replace(/^exps?:\/\//i, "http://");
  if (!/^https?:\/\//i.test(url)) url = `http://${url}`;
  const match = /^(https?):\/\/([^/:?#]+)(?::(\d+))?(.*)$/i.exec(url);
  if (!match) return url.replace(/\/+$/, "");
  const scheme = match[1].toLowerCase();
  const host = match[2];
  let port = match[3];
  const path = match[4].replace(/\/+$/, "");
  if (port === EXPO_PORT) port = String(DEFAULT_API_PORT);
  if (!port && scheme === "http" && /^\d{1,3}(\.\d{1,3}){3}$/.test(host)) port = String(DEFAULT_API_PORT);
  return `${scheme}://${host}${port ? `:${port}` : ""}${path}`;
}

/** هشدارِ آدرسی که روی گوشی هرگز به کامپیوتر نمی‌رسد. */
export function serverUrlWarning(url: string): string | null {
  return /^https?:\/\/(localhost|127\.\d+\.\d+\.\d+)(:|\/|$)/i.test(url)
    ? "«localhost» روی گوشی یعنی خودِ گوشی؛ IP کامپیوتری را که سرور روی آن اجرا شده وارد کنید."
    : null;
}

/** پیامِ روشن برای هر نوع شکستِ اتصال، تا معلوم شود ایراد از آدرس، شبکه یا خودِ سرور است. */
export function describeConnectionError(err: unknown, baseUrl: string): string {
  if (err instanceof ApiError) {
    if (err.status === 404) return `در آدرسِ ${baseUrl} سرورِ پیچا پیدا نشد. آدرس و پورت را بررسی کنید.`;
    if (err.status >= 500) return `سرور خطا داد (کد ${err.status}). پنجرهٔ اجرای سرور (uvicorn) را بررسی کنید.`;
    return err.message;
  }
  if (err instanceof Error && err.name === "AbortError") {
    return `سرورِ ${baseUrl} در ۱۵ ثانیه پاسخ نداد. اتصالِ شبکه و روشن بودنِ سرور را بررسی کنید.`;
  }
  return (
    `به سرورِ ${baseUrl} وصل نشد. بررسی کنید: سرور با «--host 0.0.0.0» اجرا شده باشد، ` +
    "گوشی و کامپیوتر روی یک شبکه باشند و فایروالِ ویندوز پورتِ سرور را باز گذاشته باشد."
  );
}
