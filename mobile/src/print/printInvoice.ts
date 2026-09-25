import * as Print from "expo-print";
import * as Sharing from "expo-sharing";
import { InvoicePrintData } from "../api/types";
import { buildInvoiceHtml } from "./invoiceHtml";

/** پنجره‌یِ چاپِ اندروید -- هر چاپگری که سرویسِ چاپِ اندروید برایش نصب
 * است (وای‌فای/بلوتوث/USB) و گزینهٔ «ذخیره به‌صورتِ PDF» خودِ اندروید. */
export async function printInvoice(data: InvoicePrintData): Promise<void> {
  await Print.printAsync({ html: buildInvoiceHtml(data) });
}

/** ساختِ فایلِ PDF و بازکردنِ منویِ اشتراک‌گذاری (واتس‌اپ/تلگرام/ایمیل/ذخیره). */
export async function shareInvoicePdf(data: InvoicePrintData): Promise<void> {
  const { uri } = await Print.printToFileAsync({ html: buildInvoiceHtml(data) });
  if (await Sharing.isAvailableAsync()) {
    await Sharing.shareAsync(uri, {
      mimeType: "application/pdf",
      UTI: "com.adobe.pdf",
      dialogTitle: data.document_no !== null ? `فاکتورِ شمارهٔ ${data.document_no}` : "فاکتور",
    });
  }
}
