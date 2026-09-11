import React, { useState } from "react";
import { Button, FlatList, StyleSheet, Text, TextInput, View } from "react-native";
import { ApiClient } from "../api/client";
import { CustomerRow, ItemRow, OrderLineInput } from "../api/types";
import { CaptureProvider } from "../capture";
import { LocationProvider } from "../location";
import { OfflineQueue } from "../sync/offlineQueue";

interface Props {
  customer: CustomerRow;
  items: ItemRow[];
  channelCode: "PRE_SALES" | "VAN_SALES";
  warehouseId: number;
  currencyId: number;
  customerVisitId: number | null;
  apiClient: ApiClient;
  offlineQueue: OfflineQueue;
  captureProvider: CaptureProvider;
  locationProvider: LocationProvider;
  onSubmitted: () => void;
}

/** ثبتِ سفارش (پخشِ سرد) یا فاکتور+تاییدِ تحویل (پخشِ گرم). طبقِ تصمیمِ
 * طراحیِ R131، پخشِ سرد فقط سفارش می‌سازد (تبدیل به فاکتور بعداً در
 * دسکتاپ)؛ پخشِ گرم بلافاصله فاکتور می‌سازد، پست می‌شود، و چون کالا
 * همان‌لحظه از خودرو تحویل داده شده، بلافاصله رسیدِ تحویل هم گرفته
 * می‌شود -- طبقِ R133، این دو یک اقدامِ ترکیبیِ واحد (CREATE_VAN_SALE_DELIVERY)
 * در صفِ آفلاین‌اند چون document_line_id فقط بعدِ ثبتِ سفارش مشخص
 * می‌شود (SyncEngine این را مدیریت می‌کند، نه این صفحه).
 *
 * قیمت وقتی آنلاین هستیم از /pricing/resolve (همان زنجیره‌یِ واقعیِ
 * resolve_price) گرفته می‌شود؛ اگر آفلاین/ناموفق بود، ویزیتور دستی
 * وارد می‌کند (Fallbackِ طراحی‌شده از R132). */
export function OrderScreen({
  customer, items, channelCode, warehouseId, currencyId, customerVisitId,
  apiClient, offlineQueue, captureProvider, locationProvider, onSubmitted,
}: Props) {
  const [lines, setLines] = useState<Record<number, { quantity: string; unitPrice: string }>>({});
  const [documentTypeCode, setDocumentTypeCode] = useState<"SALES_ORDER" | "SALES_INVOICE">(
    channelCode === "VAN_SALES" ? "SALES_INVOICE" : "SALES_ORDER",
  );
  const [receivedByName, setReceivedByName] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const setLine = (itemId: number, field: "quantity" | "unitPrice", value: string) => {
    setLines((prev) => ({ ...prev, [itemId]: { ...(prev[itemId] ?? { quantity: "", unitPrice: "" }), [field]: value } }));
  };

  const lookupPrice = async (itemId: number, uomId: number, quantity: string) => {
    if (!quantity || Number(quantity) <= 0) return;
    try {
      const resolved = await apiClient.resolvePrice({
        counterpartyDetailAccountId: customer.detail_account_id,
        itemId, uomId, quantity, documentTypeCode,
      });
      setLine(itemId, "unitPrice", resolved.unit_price);
    } catch {
      // آفلاین/بدونِ قیمتِ تعریف‌شده -- ویزیتور دستی وارد می‌کند، خطایی نمایش داده نمی‌شود
    }
  };

  const submit = async () => {
    const orderLines: OrderLineInput[] = Object.entries(lines)
      .filter(([, l]) => Number(l.quantity) > 0)
      .map(([itemId, l]) => {
        const item = items.find((i) => i.item_id === Number(itemId));
        return {
          item_id: Number(itemId),
          uom_id: item!.base_uom_id,
          quantity: l.quantity,
          unit_price: l.unitPrice || "0",
        };
      });
    if (orderLines.length === 0) return;

    const order = {
      document_type_code: documentTypeCode,
      counterparty_detail_account_id: customer.detail_account_id,
      warehouse_id: warehouseId,
      channel_code: channelCode,
      currency_id: currencyId,
      lines: orderLines,
      post_immediately: documentTypeCode === "SALES_INVOICE",
    };

    setSubmitting(true);
    try {
      if (documentTypeCode === "SALES_INVOICE") {
        const [signature, photo, position] = await Promise.all([
          captureProvider.captureSignature(),
          captureProvider.capturePhoto(),
          locationProvider.getCurrentPosition(),
        ]);
        await offlineQueue.enqueue({
          type: "CREATE_VAN_SALE_DELIVERY",
          payload: {
            order,
            delivery: {
              customer_visit_id: customerVisitId,
              received_by_name: receivedByName || null,
              signature_base64: signature,
              photo_base64: photo,
              gps_latitude: position?.latitude ?? null,
              gps_longitude: position?.longitude ?? null,
              notes: null,
            },
          },
        });
      } else {
        await offlineQueue.enqueue({ type: "CREATE_ORDER", payload: order });
      }
      setLines({});
      onSubmitted();
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <View style={styles.container}>
      <Text style={styles.title}>سفارشِ {customer.name}</Text>
      <FlatList
        data={items}
        keyExtractor={(item) => String(item.item_id)}
        renderItem={({ item }) => (
          <View style={styles.row}>
            <Text style={styles.itemName}>{item.name}</Text>
            <TextInput
              style={styles.smallInput}
              placeholder="تعداد"
              keyboardType="numeric"
              value={lines[item.item_id]?.quantity ?? ""}
              onChangeText={(v) => setLine(item.item_id, "quantity", v)}
              onEndEditing={(e) => lookupPrice(item.item_id, item.base_uom_id, e.nativeEvent.text)}
            />
            <TextInput
              style={styles.smallInput}
              placeholder="قیمت"
              keyboardType="numeric"
              value={lines[item.item_id]?.unitPrice ?? ""}
              onChangeText={(v) => setLine(item.item_id, "unitPrice", v)}
            />
          </View>
        )}
      />
      {documentTypeCode === "SALES_INVOICE" ? (
        <TextInput
          style={styles.input}
          placeholder="نامِ تحویل‌گیرنده (برایِ رسیدِ تحویل)"
          value={receivedByName}
          onChangeText={setReceivedByName}
        />
      ) : null}
      <Button
        title={submitting ? "در حالِ ثبت..." : documentTypeCode === "SALES_INVOICE" ? "ثبت، پست و تاییدِ تحویل" : "ثبتِ سفارش"}
        onPress={submit}
        disabled={submitting}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 16 },
  title: { fontSize: 18, marginBottom: 12, textAlign: "right", writingDirection: "rtl" },
  row: { flexDirection: "row-reverse", alignItems: "center", paddingVertical: 8, borderBottomWidth: 1, borderColor: "#eee" },
  itemName: { flex: 1, textAlign: "right", writingDirection: "rtl" },
  smallInput: { width: 70, borderWidth: 1, borderColor: "#ccc", borderRadius: 6, padding: 6, marginStart: 6, textAlign: "center" },
  input: { borderWidth: 1, borderColor: "#ccc", borderRadius: 6, padding: 10, marginVertical: 8, textAlign: "right", writingDirection: "rtl" },
});
