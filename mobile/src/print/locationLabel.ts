import * as Print from "expo-print";
import { LocationLabel } from "../api/types";
import { VAZIRMATN_BOLD_WOFF2_BASE64 } from "./vazirmatnFont";

function escapeHtml(text: string | null | undefined): string {
  return (text ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] as string);
}

/** برچسبِ ۷۰×۳۵ میلی‌متریِ محل (هم‌اندازهٔ برچسبِ دسکتاپ): QR + کدِ محل + بارکدِ Code128. SVGها از سرور می‌آیند. */
export function buildLocationLabelHtml(labels: LocationLabel[]): string {
  const cells = labels
    .map(
      (l) => `<div class="label"><div class="qr">${l.qr_svg}</div><div class="text"><div class="code">${escapeHtml(l.code)}</div>` +
        `<div class="title">${escapeHtml(l.title)}</div><div class="bars">${l.barcode_svg}</div></div></div>`,
    )
    .join("");
  return `<!doctype html><html dir="rtl"><head><meta charset="utf-8"/><style>
@font-face { font-family: Vazirmatn; src: url(data:font/woff2;base64,${VAZIRMATN_BOLD_WOFF2_BASE64}) format("woff2"); font-weight: 700; }
@page { size: A4; margin: 6mm; }
body { font-family: Vazirmatn, sans-serif; margin: 0; }
.label { width: 70mm; height: 35mm; box-sizing: border-box; border: 0.3mm solid #000; display: inline-flex; direction: ltr;
  padding: 2mm; margin: 0 3mm 3mm 0; page-break-inside: avoid; vertical-align: top; }
.qr { width: 31mm; height: 31mm; } .qr svg { width: 100%; height: 100%; }
.text { flex: 1; padding-left: 2mm; display: flex; flex-direction: column; justify-content: space-between; }
.code { font-weight: 700; font-size: 10pt; text-align: center; word-break: break-all; }
.title { font-size: 8pt; text-align: center; direction: rtl; }
.bars svg { width: 100%; height: 14mm; }
</style></head><body>${cells}</body></html>`;
}

export async function printLocationLabels(labels: LocationLabel[]): Promise<void> {
  await Print.printAsync({ html: buildLocationLabelHtml(labels) });
}
