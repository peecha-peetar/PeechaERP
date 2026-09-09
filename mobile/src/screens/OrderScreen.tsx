import React, { useState } from "react";
import { Button, FlatList, StyleSheet, Text, TextInput, View } from "react-native";
import { CustomerRow, ItemRow, OrderLineInput } from "../api/types";
import { OfflineQueue } from "../sync/offlineQueue";

interface Props {
  customer: CustomerRow;
  items: ItemRow[];
  channelCode: "PRE_SALES" | "VAN_SALES";
  warehouseId: number;
  currencyId: number;
  offlineQueue: OfflineQueue;
  onSubmitted: () => void;
}

/** ثبتِ سفارش (پخشِ سرد) یا فاکتور (پخشِ گرم). طبقِ تصمیمِ طراحیِ
 * R131، پخشِ سرد فقط سفارش می‌سازد (تبدیل به فاکتور بعداً در دسکتاپ)،
 * پخشِ گرم بلافاصله فاکتور می‌سازد و پست می‌شود.
 *
 * محدودیتِ شناخته‌شده: /sync/pull هنوز قیمت را برنمی‌گرداند (چون
 * قیمت‌گذاری بسته به مشتری/کانال است و منطقش در commercial_pricing.py
 * پیچیده‌تر از یک لیستِ ساده است) -- پس فعلاً قیمتِ هر ردیف را خودِ
 * ویزیتور دستی وارد می‌کند. وصل‌کردنِ resolve_price واقعی به /sync/pull
 * یا یک اندپوینتِ جداگانه، کارِ باقی‌مانده‌یِ R133/بعد است. */
export function OrderScreen({ customer, items, channelCode, warehouseId, currencyId, offlineQueue, onSubmitted }: Props) {
  const [lines, setLines] = useState<Record<number, { quantity: string; unitPrice: string }>>({});
  const [documentTypeCode, setDocumentTypeCode] = useState<"SALES_ORDER" | "SALES_INVOICE">(
    channelCode === "VAN_SALES" ? "SALES_INVOICE" : "SALES_ORDER",
  );

  const setLine = (itemId: number, field: "quantity" | "unitPrice", value: string) => {
    setLines((prev) => ({ ...prev, [itemId]: { ...(prev[itemId] ?? { quantity: "", unitPrice: "" }), [field]: value } }));
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

    await offlineQueue.enqueue({
      type: "CREATE_ORDER",
      payload: {
        document_type_code: documentTypeCode,
        counterparty_detail_account_id: customer.detail_account_id,
        warehouse_id: warehouseId,
        channel_code: channelCode,
        currency_id: currencyId,
        lines: orderLines,
        post_immediately: documentTypeCode === "SALES_INVOICE",
      },
    });
    setLines({});
    onSubmitted();
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
      <Button title={documentTypeCode === "SALES_INVOICE" ? "ثبت و پستِ فاکتور" : "ثبتِ سفارش"} onPress={submit} />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 16 },
  title: { fontSize: 18, marginBottom: 12, textAlign: "right", writingDirection: "rtl" },
  row: { flexDirection: "row-reverse", alignItems: "center", paddingVertical: 8, borderBottomWidth: 1, borderColor: "#eee" },
  itemName: { flex: 1, textAlign: "right", writingDirection: "rtl" },
  smallInput: { width: 70, borderWidth: 1, borderColor: "#ccc", borderRadius: 6, padding: 6, marginStart: 6, textAlign: "center" },
});
