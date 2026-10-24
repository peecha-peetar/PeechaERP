import { ApiError } from "../src/api/client";
import { describeConnectionError, normalizeServerUrl, serverUrlWarning } from "../src/serverUrl";

describe("آدرس سرور", () => {
  it("IP خالی را با http و پورت ۸۰۰۰ کامل می‌کند", () => {
    expect(normalizeServerUrl("192.168.1.10")).toBe("http://192.168.1.10:8000");
    expect(normalizeServerUrl(" ۱۹۲٫۱۶۸٫۱٫۱۰ ")).toBe("http://192.168.1.10:8000");
    expect(normalizeServerUrl("http://192.168.1.10:8000/")).toBe("http://192.168.1.10:8000");
    expect(normalizeServerUrl("192.168.1.10:9000")).toBe("http://192.168.1.10:9000");
  });

  it("آدرس Expo را به پورت سرور برمی‌گرداند", () => {
    expect(normalizeServerUrl("exp://192.168.1.10:8081")).toBe("http://192.168.1.10:8000");
    expect(normalizeServerUrl("http://192.168.1.10:8081")).toBe("http://192.168.1.10:8000");
  });

  it("دامنه و https دست‌نخورده می‌ماند", () => {
    expect(normalizeServerUrl("https://erp.example.com/api/")).toBe("https://erp.example.com/api");
    expect(normalizeServerUrl("erp.example.com")).toBe("http://erp.example.com");
    expect(normalizeServerUrl("")).toBe("");
  });

  it("localhost روی گوشی هشدار دارد", () => {
    expect(serverUrlWarning("http://localhost:8000")).not.toBeNull();
    expect(serverUrlWarning("http://127.0.0.1:8000")).not.toBeNull();
    expect(serverUrlWarning("http://192.168.1.10:8000")).toBeNull();
  });

  it("پیام خطا علت را جدا می‌کند", () => {
    const url = "http://192.168.1.10:8000";
    expect(describeConnectionError(new ApiError(401, "نام کاربری یا رمز نادرست است."), url)).toBe("نام کاربری یا رمز نادرست است.");
    expect(describeConnectionError(new ApiError(500, "Internal Server Error"), url)).toContain("کد 500");
    expect(describeConnectionError(new ApiError(404, "Not Found"), url)).toContain("پیدا نشد");
    const abort = new Error("aborted");
    abort.name = "AbortError";
    expect(describeConnectionError(abort, url)).toContain("پاسخ نداد");
    expect(describeConnectionError(new TypeError("Network request failed"), url)).toContain("--host 0.0.0.0");
  });
});
