import React, { useEffect, useState } from "react";
import { FlatList, Text, View } from "react-native";
import { ApiClient } from "../api/client";
import { VehicleSettlementSummaryLine } from "../api/types";
import { Button, Card, EmptyState, InlineSpinner, Input } from "../components";
import { useTheme } from "../theme/ThemeProvider";

interface Props {
  apiClient: ApiClient;
  onBack: () => void;
}

/** طبقِ درخواستِ صریحِ کاربر («تسویه آخر روز باید بصورت انتخابی به یک
 * نفر از ۳ نقش واگذار بشه و به تاییدِ انبار و حسابداری برسه»): این
 * صفحه فقط برایِ همان یک نفر (طبقِ تنظیمِ دسکتاپ) قابلِ‌دیدن است --
 * App.tsx فقط وقتی دکمه‌اش را نشان می‌دهد که settlementVehicleWarehouseId
 * از /auth/me مقداری داشته باشد. ثبت این‌جا فقط «ارسال» است -- تاییدِ
 * انبار/حسابداری همیشه در دسکتاپ انجام می‌شود. */
export function VehicleSettlementScreen({ apiClient, onBack }: Props) {
  const { colors, spacing, typography } = useTheme();
  const [loading, setLoading] = useState(true);
  const [invoicedAmount, setInvoicedAmount] = useState("0");
  const [lines, setLines] = useState<VehicleSettlementSummaryLine[]>([]);
  const [returnedByItem, setReturnedByItem] = useState<Record<number, string>>({});
  const [declaredCash, setDeclaredCash] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiClient
      .getVehicleSettlementTodaySummary()
      .then((summary) => {
        setInvoicedAmount(summary.invoiced_amount);
        setLines(summary.lines);
      })
      .catch((err) => setError(err.message ?? "خطایی رخ داد."))
      .finally(() => setLoading(false));
  }, [apiClient]);

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      await apiClient.submitVehicleSettlement({
        declared_cash_amount: declaredCash || "0",
        lines: lines.map((l) => ({
          item_id: l.item_id, uom_id: l.uom_id, returned_quantity: returnedByItem[l.item_id] || "0",
        })),
      });
      setSubmitted(true);
    } catch (err: any) {
      setError(err.message ?? "ثبتِ تسویه ناموفق بود.");
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) return <InlineSpinner label="در حالِ بارگذاریِ اطلاعاتِ امروز..." />;

  if (submitted) {
    return (
      <View style={{ flex: 1, padding: spacing.lg, gap: spacing.md }}>
        <EmptyState
          title="تسویه ثبت شد"
          description="این تسویه اکنون منتظرِ تاییدِ انبار و سپس تاییدِ حسابداری است."
        />
        <Button label="بازگشت" onPress={onBack} />
      </View>
    );
  }

  return (
    <View style={{ flex: 1, backgroundColor: colors.background, padding: spacing.lg, gap: spacing.md }}>
      <Text style={[typography.h2, { color: colors.textPrimary }]}>تسویهٔ پایانِ روزِ خودرو</Text>
      <Text style={[typography.caption, { color: colors.textSecondary }]}>
        مبلغِ فاکتورشدهٔ امروز: {Number(invoicedAmount).toLocaleString("fa-IR")}
      </Text>

      <FlatList
        data={lines}
        keyExtractor={(l) => `${l.item_id}-${l.uom_id}`}
        contentContainerStyle={{ gap: spacing.sm }}
        renderItem={({ item }) => {
          const returned = Number(returnedByItem[item.item_id] || "0");
          const shortage = Number(item.loaded_quantity) - Number(item.sold_quantity) - returned;
          return (
            <Card style={{ padding: spacing.md }}>
              <Text style={[typography.bodyBold, { color: colors.textPrimary }]}>{item.item_name ?? `کالایِ #${item.item_id}`}</Text>
              <Text style={[typography.caption, { color: colors.textSecondary }]}>
                بارگیری‌شده: {item.loaded_quantity} — فروخته‌شده: {item.sold_quantity}
              </Text>
              <Input
                label="مقدارِ برگشتی"
                value={returnedByItem[item.item_id] ?? ""}
                onChangeText={(v) => setReturnedByItem((prev) => ({ ...prev, [item.item_id]: v }))}
                keyboardType="numeric"
                numeric
              />
              <Text style={[typography.caption, { color: shortage === 0 ? colors.textSecondary : colors.danger }]}>
                {shortage === 0 ? "بدونِ کسری/اضافی" : shortage > 0 ? `کسری: ${shortage}` : `اضافی: ${-shortage}`}
              </Text>
            </Card>
          );
        }}
        ListEmptyComponent={<EmptyState title="بارگیری/فروشی برایِ امروز ثبت نشده" />}
      />

      <Input label="مبلغِ نقدِ تحویلی" value={declaredCash} onChangeText={setDeclaredCash} keyboardType="numeric" numeric />

      {error ? <Text style={[typography.body, { color: colors.danger }]}>{error}</Text> : null}

      <Button label={submitting ? "در حالِ ثبت..." : "ثبتِ تسویه"} onPress={submit} loading={submitting} disabled={submitting} />
      <Button label="بازگشت" variant="ghost" onPress={onBack} />
    </View>
  );
}
