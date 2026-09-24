import { InMemoryKeyValueStore } from "../src/storage/keyValueStore";
import { SyncErrorLog } from "../src/sync/syncErrorLog";

describe("SyncErrorLog", () => {
  it("خطاهایِ تازه را اول لیست نگه می‌دارد و تاریخ ثبت می‌کند", async () => {
    const log = new SyncErrorLog(new InMemoryKeyValueStore());
    await log.record([{ idempotencyKey: "a", reason: "خطایِ اول" }]);
    await log.record([{ idempotencyKey: "b", reason: "خطایِ دوم", documentId: 5 }]);

    const entries = await log.list();
    expect(entries).toHaveLength(2);
    expect(entries[0].reason).toBe("خطایِ دوم");
    expect(entries[0].documentId).toBe(5);
    expect(entries[1].reason).toBe("خطایِ اول");
    expect(typeof entries[0].occurredAt).toBe("string");
  });

  it("لیستِ خالی برایِ record با آرایه‌یِ خالی چیزی ذخیره نمی‌کند", async () => {
    const kv = new InMemoryKeyValueStore();
    const log = new SyncErrorLog(kv);
    await log.record([]);
    expect(await log.list()).toEqual([]);
  });

  it("clear کلیدِ لاگ را کاملاً حذف می‌کند", async () => {
    const log = new SyncErrorLog(new InMemoryKeyValueStore());
    await log.record([{ idempotencyKey: "a", reason: "خطا" }]);
    await log.clear();
    expect(await log.list()).toEqual([]);
  });

  it("بیش از سقفِ ۲۰تایی را کوتاه می‌کند", async () => {
    const log = new SyncErrorLog(new InMemoryKeyValueStore());
    for (let i = 0; i < 25; i += 1) {
      await log.record([{ idempotencyKey: `k${i}`, reason: `خطایِ ${i}` }]);
    }
    const entries = await log.list();
    expect(entries).toHaveLength(20);
    expect(entries[0].reason).toBe("خطایِ 24");
  });
});
