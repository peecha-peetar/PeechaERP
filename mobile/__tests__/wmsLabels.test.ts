jest.mock("expo-print", () => ({ printAsync: jest.fn(async () => undefined) }));
jest.mock("../src/print/vazirmatnFont", () => ({ VAZIRMATN_BOLD_WOFF2_BASE64: "", VAZIRMATN_REGULAR_WOFF2_BASE64: "" }));
import * as Print from "expo-print";
import { ApiClient, Fetcher } from "../src/api/client";
import { InMemoryKeyValueStore } from "../src/storage/keyValueStore";
import { LocalCache } from "../src/storage/localCache";
import { TokenStore } from "../src/storage/tokenStore";
import { OfflineQueue } from "../src/sync/offlineQueue";
import { SyncEngine } from "../src/sync/syncEngine";
import { submitWmsAction } from "../src/sync/wmsSubmit";
import { buildLocationLabelHtml, printLocationLabels } from "../src/print/locationLabel";

const label = { location_id: 5, code: "WH01-Z01-B07", title: "<قفسه>", qr_payload: "PEECHA-LOC:5:WH01-Z01-B07", qr_svg: "<svg id=\"qr\"></svg>", barcode_svg: "<svg id=\"bars\"></svg>" };

describe("برچسب و شمارشِ بچ (R251)", () => {
  it("HTMLِ برچسب: QR و بارکد و متنِ escape‌شده", () => {
    const html = buildLocationLabelHtml([label, { ...label, location_id: 6, code: "WH01-Z01-B08" }]);
    expect(html).toContain('<svg id="qr"></svg>');
    expect(html).toContain('<svg id="bars"></svg>');
    expect(html).toContain("&lt;قفسه&gt;");
    expect(html.match(/class="label"/g)).toHaveLength(2);
    expect(html).toContain("width: 70mm");
  });

  it("چاپ با expo-print", async () => {
    await printLocationLabels([label]);
    expect(Print.printAsync).toHaveBeenCalledWith({ html: expect.stringContaining("WH01-Z01-B07") });
  });

  it("شمارشِ بچ‌دار شمارهٔ بچ را می‌فرستد", async () => {
    const bodies: unknown[] = [];
    const fetcher = jest.fn(async (_u: string, init: RequestInit) => {
      bodies.push(JSON.parse(String(init.body)));
      return { ok: true, status: 200, statusText: "200", json: async () => ({ line_id: 1 }) } as unknown as Response;
    }) as unknown as Fetcher;
    const kv = new InMemoryKeyValueStore();
    const store = new TokenStore(kv);
    await store.setTokens("a", "r");
    const api = new ApiClient("http://api.local", store, fetcher);
    const queue = new OfflineQueue(kv);
    await submitWmsAction(queue, new SyncEngine(api, queue, new LocalCache(kv)), {
      type: "WMS_COUNT", payload: { sessionId: 1, locationId: 2, itemId: 3, quantity: "4", batchNo: "B-1" },
    });
    expect(bodies).toEqual([{ location_id: 2, item_id: 3, quantity: "4", batch_no: "B-1" }]);
  });
});
