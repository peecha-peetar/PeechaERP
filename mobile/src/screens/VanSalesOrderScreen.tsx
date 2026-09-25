import React, { useMemo, useState } from "react";
import { FlatList, Text, View } from "react-native";
import { ApiClient } from "../api/client";
import { CustomerRow, ItemRow, OrderLineInput, SettlementMethodRow } from "../api/types";
import { CaptureProvider } from "../capture";
import { LocationProvider } from "../location";
import { Button, Card, EmptyState, Input, SearchBar } from "../components";
import { useTheme } from "../theme/ThemeProvider";
import { OfflineQueue } from "../sync/offlineQueue";

interface Props {
  customer: CustomerRow;
  items: ItemRow[];
  /** طبقِ باگِ واقعیِ کشف‌شده (R196): channel_codeِ واقعیِ تعریف‌شده در
   * comm.channelsِ همین شرکت (مثلِ «VAN-1») -- «VAN_SALES» خودش یک
   * channel_codeِ معتبر نیست و اگر مستقیم فرستاده شود، سند به‌خاطرِ
   * شکستِ کلیدِ خارجی اصلاً ساخته نمی‌شود. */
  channelCode: string;
  warehouseId: number;
  currencyId: number;
  costCenterDetailAccountId: number | null;
  projectDetailAccountId: number | null;
  /** طبقِ درخواستِ صریحِ کاربر («نوعِ تسویه در پخشِ گرم باید همانندِ
   * انواعِ تسویه در دسکتاپ باشد -- فقط جایی باشد که برخی را برایِ
   * موبایل خاموش کنیم»): فهرستِ روش‌هایِ فعال‌شده‌یِ همین شرکت. */
  settlementMethods: SettlementMethodRow[];
  customerVisitId: number | null;
  apiClient: ApiClient;
  offlineQueue: OfflineQueue;
  captureProvider: CaptureProvider;
  locationProvider: LocationProvider;
  onSubmitted: () => void;
}

/** طبقِ درخواستِ صریحِ کاربر («رابطِ کاربریِ موبایل برایِ پخشِ گرم و سرد
 * جدا بشه، پروسه‌هاشون جدا باشه»): این صفحه فقط برایِ پخشِ گرم (فروشِ
 * خودرویی) است -- همیشه بلافاصله فاکتور می‌سازد، پست می‌شود، و چون
 * کالا همان‌لحظه از خودرو تحویل داده شده، بلافاصله رسیدِ تحویل هم
 * گرفته می‌شود -- طبقِ R133، این دو یک اقدامِ ترکیبیِ واحد
 * (CREATE_VAN_SALE_DELIVERY) در صفِ آفلاین‌اند چون document_line_id
 * فقط بعدِ ثبتِ سفارش مشخص می‌شود (SyncEngine این را مدیریت می‌کند،
 * نه این صفحه). پخشِ سرد دیگر این‌جا نیست -- PreSalesOrderScreen.tsx
 * جدا و ساده‌تر است (بدونِ امضا/عکس/تسویه). */
export function VanSalesOrderScreen({
  customer, items, channelCode, warehouseId, currencyId,
  costCenterDetailAccountId, projectDetailAccountId, settlementMethods, customerVisitId,
  apiClient, offlineQueue, captureProvider, locationProvider, onSubmitted,
}: Props) {
  const { colors, spacing, typography } = useTheme();
  const [search, setSearch] = useState("");
  const [lines, setLines] = useState<Record<number, { quantity: string; unitPrice: string }>>({});
  const [receivedByName, setReceivedByName] = useState("");
  // طبقِ درخواستِ صریحِ کاربر («نوعِ تسویه در پخشِ گرم باید همانندِ
  // انواعِ تسویه در دسکتاپ باشد»): مبلغِ واردشده برایِ هر روشِ فعال --
  // خالی/صفر یعنی این روش استفاده نشده.
  const [settlementAmounts, setSettlementAmounts] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);

  const filteredItems = useMemo(() => {
    if (!search.trim()) return items;
    const needle = search.trim().toLowerCase();
    return items.filter((it) => it.name.toLowerCase().includes(needle) || it.code.toLowerCase().includes(needle));
  }, [items, search]);

  const lineCount = Object.values(lines).filter((l) => Number(l.quantity) > 0).length;
  const orderTotal = Object.values(lines).reduce((sum, l) => sum + Number(l.quantity || 0) * Number(l.unitPrice || 0), 0);
  const settledTotal = Object.values(settlementAmounts).reduce((sum, v) => sum + Number(v || 0), 0);

  const setLine = (itemId: number, field: "quantity" | "unitPrice", value: string) => {
    setLines((prev) => ({ ...prev, [itemId]: { ...(prev[itemId] ?? { quantity: "", unitPrice: "" }), [field]: value } }));
  };

  const lookupPrice = async (itemId: number, uomId: number, quantity: string) => {
    if (!quantity || Number(quantity) <= 0) return;
    try {
      const resolved = await apiClient.resolvePrice({
        counterpartyDetailAccountId: customer.detail_account_id,
        itemId, uomId, quantity, documentTypeCode: "SALES_INVOICE",
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
      document_type_code: "SALES_INVOICE" as const,
      counterparty_detail_account_id: customer.detail_account_id,
      warehouse_id: warehouseId,
      channel_code: channelCode,
      currency_id: currencyId,
      lines: orderLines,
      post_immediately: true,
      cost_center_detail_account_id: costCenterDetailAccountId,
      project_detail_account_id: projectDetailAccountId,
      // طبقِ درخواستِ صریحِ کاربر («نوعِ تسویه در پخشِ گرم باید همانندِ
      // انواعِ تسویه در دسکتاپ باشد»): فهرستِ خالی (اگر ویزیتور چیزی
      // وارد نکند) یعنی صراحتاً «همه‌اش نسیه»، نه سقوطِ خاموش به «همه‌اش نقد».
      settlement_lines: Object.entries(settlementAmounts)
        .filter(([, amount]) => Number(amount) > 0)
        .map(([method_code, amount]) => ({ method_code, amount })),
    };

    setSubmitting(true);
    try {
      // طبقِ باگِ واقعیِ کشف‌شده در R191: امضا حالا (بر خلافِ قبل) یک
      // Modalِ واقعیِ درون‌اپ باز می‌کند -- اگر هم‌زمان با دوربین (که کلِ
      // اپ را موقتاً به یک اکتیویتیِ نیتیوِ جدا می‌برد) در یک Promise.all
      // اجرا شود، هردو رابطِ کاربری روی هم می‌آیند. پس امضا باید اول و
      // تنها اجرا شود؛ عکس/GPS بعد از بستنِ آن Modal با هم اجرا می‌شوند.
      const signature = await captureProvider.captureSignature();
      const [photo, position] = await Promise.all([
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
      setLines({});
      setSettlementAmounts({});
      onSubmitted();
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <View style={{ flex: 1, backgroundColor: colors.background, padding: spacing.lg, gap: spacing.md }}>
      <Text style={[typography.h2, { color: colors.textPrimary }]}>فاکتورِ پخشِ گرم — {customer.name}</Text>
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
        ListEmptyComponent={<EmptyState icon="🔍" title="کالایی پیدا نشد" />}
      />

      <Input label="نامِ تحویل‌گیرنده (برایِ رسیدِ تحویل)" value={receivedByName} onChangeText={setReceivedByName} />

      {/* طبقِ درخواستِ صریحِ کاربر («نوعِ تسویه در پخشِ گرم باید همانندِ
          انواعِ تسویه در دسکتاپ باشد»): هر روشِ فعال‌شده یک فیلدِ مبلغ
          دارد؛ خالی‌گذاشتنِ همه یعنی این فاکتور صراحتاً نسیه است. */}
      <Text style={[typography.bodyBold, { color: colors.textPrimary }]}>نحوه‌یِ تسویه</Text>
      {settlementMethods.map((method) => (
        <Input
          key={method.method_code}
          label={method.label}
          value={settlementAmounts[method.method_code] ?? ""}
          onChangeText={(v) => setSettlementAmounts((prev) => ({ ...prev, [method.method_code]: v }))}
          keyboardType="numeric"
          numeric
        />
      ))}
      <Text style={[typography.caption, { color: colors.textSecondary }]}>
        جمعِ سفارش: {orderTotal.toLocaleString("fa-IR")} — تسویه‌شده: {settledTotal.toLocaleString("fa-IR")}
        {settledTotal < orderTotal ? ` — نسیه: ${(orderTotal - settledTotal).toLocaleString("fa-IR")}` : ""}
      </Text>

      <Button
        label={submitting ? "در حالِ ثبت..." : `ثبت، پست و تاییدِ تحویل (${lineCount} قلم)`}
        onPress={submit}
        loading={submitting}
        disabled={submitting || lineCount === 0}
      />
    </View>
  );
}
