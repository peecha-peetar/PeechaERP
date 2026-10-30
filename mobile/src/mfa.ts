import { ApiError } from "./api/client";
import { toAsciiDigits } from "./format";

/** R377: سرور با این کد می‌گوید پس از رمز درست، کد ورود دومرحله‌ای لازم است. */
export const OTP_REQUIRED_STATUS = 428;

export function isOtpRequired(err: unknown): boolean {
  return err instanceof ApiError && err.status === OTP_REQUIRED_STATUS;
}

/** کد شش‌رقمی یا کد بازیابی (مثل ABCD-EFGH) با ارقام فارسی یا فاصله. */
export function normalizeOtp(text: string): string {
  return toAsciiDigits(text ?? "").replace(/[\s-]/g, "").toUpperCase();
}
