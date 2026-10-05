import { WarehouseMapNode } from "../api/types";

export interface MapRect {
  locationId: number;
  code: string;
  level: string | null;
  left: number;
  top: number;
  width: number;
  height: number;
  occupancy: number | null;
  status: string;
}

const DRAWN_LEVELS = new Set(["AREA", "AISLE", "RACK", "BIN"]);

/** مستطیل‌هایِ نقشهٔ انبار در مقیاسِ صفحهٔ گوشی: کوچک‌ترین x/y به صفر می‌رسد و عرضِ کل = width.
 * چرخشِ ۹۰ درجه ابعاد را جابه‌جا می‌کند (هم‌الگو با نمایِ سه‌بعدیِ دسکتاپ). */
export function layoutWarehouseMap(nodes: WarehouseMapNode[], width: number): { rects: MapRect[]; height: number } {
  const drawn = nodes
    .filter((n) => n.map !== null && DRAWN_LEVELS.has(n.level ?? ""))
    .map((n) => {
      const m = n.map!;
      const quarter = Math.round(m.rotation) % 180 === 90;
      const w = quarter ? m.height : m.width;
      const h = quarter ? m.width : m.height;
      return { n, x: m.x + m.width / 2 - w / 2, y: m.y + m.height / 2 - h / 2, w, h };
    });
  if (drawn.length === 0) return { rects: [], height: 0 };
  const minX = Math.min(...drawn.map((d) => d.x));
  const minY = Math.min(...drawn.map((d) => d.y));
  const maxX = Math.max(...drawn.map((d) => d.x + d.w));
  const maxY = Math.max(...drawn.map((d) => d.y + d.h));
  const scale = width / Math.max(1, maxX - minX);
  const order: Record<string, number> = { AREA: 0, AISLE: 1, RACK: 2, BIN: 3 };
  const rects = drawn
    .sort((a, b) => (order[a.n.level ?? ""] ?? 4) - (order[b.n.level ?? ""] ?? 4))
    .map((d) => ({
      locationId: d.n.location_id,
      code: d.n.code,
      level: d.n.level,
      left: (d.x - minX) * scale,
      top: (d.y - minY) * scale,
      width: Math.max(2, d.w * scale),
      height: Math.max(2, d.h * scale),
      occupancy: d.n.occupancy_percent !== null ? Number(d.n.occupancy_percent) : null,
      status: d.n.status,
    }));
  return { rects, height: (maxY - minY) * scale };
}

/** رنگِ اشغال (هم‌خوان با دسکتاپ): سبز < ۵۰، زرد < ۷۵، نارنجی < ۹۰، قرمز. */
export function occupancyTone(percent: number | null): "empty" | "low" | "mid" | "high" | "full" {
  if (percent === null || percent <= 0) return "empty";
  if (percent < 50) return "low";
  if (percent < 75) return "mid";
  if (percent < 90) return "high";
  return "full";
}
