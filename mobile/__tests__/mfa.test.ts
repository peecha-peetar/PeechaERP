import { ApiClient, ApiError } from "../src/api/client";
import { isOtpRequired, normalizeOtp, OTP_REQUIRED_STATUS } from "../src/mfa";

describe("R377 ورود دومرحله‌ای", () => {
  it("only HTTP 428 asks for the code", () => {
    expect(isOtpRequired(new ApiError(OTP_REQUIRED_STATUS, "کد"))).toBe(true);
    expect(isOtpRequired(new ApiError(401, "نادرست"))).toBe(false);
    expect(isOtpRequired(new Error("x"))).toBe(false);
  });

  it("normalizes Persian digits, spaces and recovery codes", () => {
    expect(normalizeOtp("۱۲۳ ۴۵۶")).toBe("123456");
    expect(normalizeOtp("abcd-efgh")).toBe("ABCDEFGH");
  });

  it("sends the code with the login request", async () => {
    const calls: { url: string; body: unknown }[] = [];
    const fetcher = jest.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, body: JSON.parse(String(init?.body)) });
      if (calls.length === 1) {
        return new Response(JSON.stringify({ detail: "کد شش‌رقمی ورود دومرحله‌ای را وارد کنید." }), { status: 428 });
      }
      return new Response(JSON.stringify({ access_token: "a", refresh_token: "r", user_id: 1, full_name: "x", company_id: 1, company_name: "c" }),
        { status: 200 });
    });
    const tokens: string[] = [];
    const store = {
      getAccessToken: async () => null, getRefreshToken: async () => null,
      setAccessToken: async (t: string) => { tokens.push(t); }, setTokens: async (a: string) => { tokens.push(a); }, clear: async () => undefined,
    };
    const client = new ApiClient("http://srv", store as never, fetcher as never);
    await expect(client.login("u", "p")).rejects.toMatchObject({ status: 428 });
    const data = await client.login("u", "p", undefined, "123456");
    expect(data.access_token).toBe("a");
    expect((calls[1].body as { otp: string }).otp).toBe("123456");
    expect((calls[0].body as { otp: string | null }).otp).toBeNull();
  });
});
