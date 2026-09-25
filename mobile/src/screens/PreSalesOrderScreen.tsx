import React, { useMemo, useState } from "react";
import { FlatList, Text, View } from "react-native";
import { ApiClient } from "../api/client";
import { CustomerRow, ItemRow, OrderLineInput } from "../api/types";
import { Button, Card, EmptyState, Input, SearchBar } from "../components";
import { useTheme } from "../theme/ThemeProvider";
import { OfflineQueue } from "../sync/offlineQueue";

interface Props {
  customer: CustomerRow;
  items: ItemRow[];
  /** channel_codeِ واقعیِ تعریف‌شده در comm.channelsِ همین شرکت از نوعِ
   * PRE_SALES (مثلِ «PS-1») -- هم‌الگو با باگِ واقعیِ کشف‌شدهٔ R196 برایِ
   * پخشِ گرم. */
  channelCode: string;
  warehouseId: number;
  currencyId: number;
  apiClient: ApiClient;
  offlineQueue: OfflineQueue;
  onSubmitted: () => void;
}

/** طبقِ درخواستِ صریحِ کاربر («رابطِ کاربریِ موبایل برایِ پخشِ گرم و سرد
 * جدا بشه، پروسه‌هاشون جدا باشه»): این صفحه فقط برایِ پخشِ سرد
 * (سفارش‌گیری) است -- عمداً بسیار ساده‌تر از VanSalesOrderScreen: نه
 * امضا/عکس/GPSای لازم است، نه تسویه‌ای -- فقط یک سفارش (SALES_ORDER،
 * بدونِ post_immediately) ثبت می‌شود که بعداً در دسکتاپ طیِ چرخهٔ کاملِ
 * تاییدِ انبار/توزین -> تبدیل به فاکتور می‌رود (commercial_documents.
 * convert_to_invoice) -- ویزیتور این‌جا کاری با آن چرخه ندارد. */
export function PreSalesOrderScreen({ customer, items, channelCode, warehouseId, currencyId, apiClient, offlineQueue, onSubmitted }: Props) {
  const { colors, spacing, typography } = useTheme();
  const [search, setSearch] = useState("");
  const [lines, setLines] = useState<Record<number, { quantity: string; unitPrice: string }>>({});
  const [submitting, setSubmitting] = useState(false);

  const filteredItems = useMemo(() => {
    if (!search.trim()) return items;
    const needle = search.trim().toLowerCase();
    return items.filter((it) => it.name.toLowerCase().includes(needle) || it.code.toLowerCase().includes(needle));
  }, [items, search]);

  const lineCount = Object.values(lines).filter((l) => Number(l.quantity) > 0).length;

  const setLine = (itemId: number, field: "quantity" | "unitPrice", value: string) => {
    setLines((prev) => ({ ...prev, [itemId]: { ...(prev[itemId] ?? { quantity: "", unitPrice: "" }), [field]: value } }));
  };

  const lookupPrice = async (itemId: number, uomId: number, quantity: string) => {
    if (!quantity || Number(quantity) <= 0) return;
    try {
      const resolved = await apiClient.resolvePrice({
        counterpartyDetailAccountId: customer.detail_account_id,
        itemId, uomId, quantity, documentTypeCode: "SALES_ORDER",
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

    setSubmitting(true);
    try {
      await offlineQueue.enqueue({
        type: "CREATE_ORDER",
        payload: {
          document_type_code: "SALES_ORDER",
          counterparty_detail_account_id: customer.detail_account_id,
          warehouse_id: warehouseId,
          channel_code: channelCode,
          currency_id: currencyId,
          lines: orderLines,
          post_immediately: false,
        },
      });
      setLines({});
      onSubmitted();
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <View style={{ flex: 1, backgroundColor: colors.background, padding: spacing.lg, gap: spacing.md }}>
      <Text style={[typography.h2, { color: colors.textPrimary }]}>سفارشِ پخشِ سرد — {customer.name}</Text>
      <SearchBar value={search} onChangeText={setSearch} placeholder="جستجویِ کالا..." />

      <FlatList
        data={filteredItems}
        keyExtractor={(item) => String(item.item_id)}
        contentContainerStyle={{ gap: spacing.sm }}
        renderItem={({ item }) => {
          const line = lines[item.item_id];
          return (
            <Card style={{ padding: spacing.md }}>
              <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}>
                <Text style={[typography.bodyBold, { color: colors.textPrimary, flex: 1 }]} numberOfLines={1}>
                  {item.name}
                </Text>
                <Input
                  value={line?.quantity ?? ""}
                  onChangeText={(v) => setLine(item.item_id, "quantity", v)}
                  onEndEditing={(e) => lookupPrice(item.item_id, item.base_uom_id, e.nativeEvent.text)}
                  keyboardType="numeric"
                  placeholder="تعداد"
                  numeric
                  style={{ width: 70 }}
                />
                <Input
                  value={line?.unitPrice ?? ""}
                  onChangeText={(v) => setLine(item.item_id, "unitPrice", v)}
                  keyboardType="numeric"
                  placeholder="قیمت"
                  numeric
                  style={{ width: 100 }}
                />
              </View>
            </Card>
          );
        }}
        ListEmptyComponent={<EmptyState title="کالایی پیدا نشد" />}
      />

      <Button
        label={submitting ? "در حالِ ثبت..." : `ثبتِ سفارش (${lineCount} قلم)`}
        onPress={submit}
        loading={submitting}
        disabled={submitting || lineCount === 0}
      />
    </View>
  );
}
