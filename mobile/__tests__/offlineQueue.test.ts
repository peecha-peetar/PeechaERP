import { InMemoryKeyValueStore } from "../src/storage/keyValueStore";
import { OfflineQueue } from "../src/sync/offlineQueue";

describe("OfflineQueue", () => {
  it("enqueue کلیدِ یکتا می‌سازد و ترتیبِ ورود را حفظ می‌کند", async () => {
    const queue = new OfflineQueue(new InMemoryKeyValueStore());
    const a = await queue.enqueue({
      type: "START_VISIT",
      payload: { customer_detail_account_id: 5 },
    });
    const b = await queue.enqueue({
      type: "COMPLETE_VISIT",
      payload: { customerVisitId: 1 },
    });

    expect(a.idempotencyKey).not.toEqual(b.idempotencyKey);
    const all = await queue.list();
    expect(all.map((x) => x.idempotencyKey)).toEqual([a.idempotencyKey, b.idempotencyKey]);
    expect(await queue.size()).toBe(2);
  });

  it("remove فقط همان اقدام را از صف پاک می‌کند", async () => {
    const queue = new OfflineQueue(new InMemoryKeyValueStore());
    const a = await queue.enqueue({ type: "SKIP_VISIT", payload: { customerVisitId: 1, skipReason: "بسته بود" } });
    const b = await queue.enqueue({ type: "SKIP_VISIT", payload: { customerVisitId: 2, skipReason: "بسته بود" } });

    await queue.remove(a.idempotencyKey);

    const remaining = await queue.list();
    expect(remaining).toHaveLength(1);
    expect(remaining[0].idempotencyKey).toBe(b.idempotencyKey);
  });

  it("صفِ خالی برایِ استورِ تازه برمی‌گرداند", async () => {
    const queue = new OfflineQueue(new InMemoryKeyValueStore());
    expect(await queue.list()).toEqual([]);
    expect(await queue.size()).toBe(0);
  });

  it("clear کلیدِ صف را کاملاً حذف می‌کند -- حتی وقتی مقدارِ فعلی خرابه", async () => {
    const kv = new InMemoryKeyValueStore();
    const queue = new OfflineQueue(kv);
    await queue.enqueue({ type: "START_VISIT", payload: { customer_detail_account_id: 5 } });
    expect(await queue.size()).toBe(1);

    // طبقِ باگِ واقعیِ اندروید («Row too big to fit into CursorWindow»):
    // clear باید بدونِ خواندن/parseِ مقدارِ فعلی کار کند، چون در آن باگ
    // خودِ خواندن هم شکست می‌خورد.
    await kv.setItem("peecha.offline_queue", "این یک JSONِ نامعتبر است");
    await queue.clear();
    expect(await kv.getItem("peecha.offline_queue")).toBeNull();
    expect(await queue.size()).toBe(0);
  });
});
