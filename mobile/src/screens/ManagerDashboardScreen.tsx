import React, { useCallback, useEffect, useState } from "react";
import { ScrollView, Text, View } from "react-native";
import { ApiClient, ApiError } from "../api/client";
import { ManagerDashboardResponse, RouteRow } from "../api/types";
import { Button, Card, ErrorState, SkeletonList } from "../components";
import { formatAmount } from "../format";
import { formatJalaliDate } from "../jalali";
import { useTheme } from "../theme/ThemeProvider";

interface Props {
  apiClient: ApiClient;
  onBack: () => void;
}

type RangePreset = "TODAY" | "WEEK" | "MONTH";

function rangeFor(preset: RangePreset): { dateFrom: string; dateTo: string } {
  const to = new Date();
  const from = new Date();
  if (preset === "WEEK") from.setDate(from.getDate() - 6);
  if (preset === "MONTH") from.setDate(from.getDate() - 29);
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  return { dateFrom: iso(from), dateTo: iso(to) };
}

const PRESETS: { code: RangePreset; label: string }[] = [
  { code: "TODAY", label: "امروز" },
  { code: "WEEK", label: "۷ روزِ اخیر" },
  { code: "MONTH", label: "۳۰ روزِ اخیر" },
];

/** طبقِ Phase 7 (Manager Dashboard + KPI) -- فقط برایِ کاربرِ مدیر
 * (سرور با ۴۰۳ رد می‌کند اگر نباشد؛ این صفحه آن خطا را به‌جایِ Crash
 * با ErrorState نشان می‌دهد). طبقِ R189: فیلترِ منطقه/مسیر اضافه شد و
 * بازهٔ انتخاب‌شده با تاریخِ شمسی نمایش داده می‌شود -- محدودیتِ
 * باقی‌مانده: بازه‌یِ سفارشی (غیر از سه پیش‌فرضِ ثابت) هنوز نیازمندِ
 * یک تقویمِ جلالیِ تعاملی است که هنوز ساخته نشده. */
export function ManagerDashboardScreen({ apiClient, onBack }: Props) {
  const { colors, spacing, typography } = useTheme();
  const [preset, setPreset] = useState<RangePreset>("TODAY");
  const [routes, setRoutes] = useState<RouteRow[]>([]);
  const [routeId, setRouteId] = useState<number | null>(null);
  const [data, setData] = useState<ManagerDashboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [forbidden, setForbidden] = useState(false);

  useEffect(() => {
    apiClient.listRoutes().then(setRoutes).catch(() => setRoutes([]));
  }, [apiClient]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setForbidden(false);
    try {
      const { dateFrom, dateTo } = rangeFor(preset);
      const result = await apiClient.getManagerDashboard({
        dateFrom, dateTo, routeDetailAccountId: routeId ?? undefined,
      });
      setData(result);
    } catch (e) {
      if (e instanceof ApiError && e.status === 403) {
        setForbidden(true);
      } else {
        setError(e instanceof ApiError ? e.message : "دریافتِ داشبوردِ مدیریتی ناموفق بود.");
      }
    } finally {
      setLoading(false);
    }
  }, [apiClient, preset, routeId]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <ScrollView contentContainerStyle={{ padding: spacing.lg, gap: spacing.lg, backgroundColor: colors.background }}>
      <Button label="بازگشت" variant="ghost" fullWidth={false} onPress={onBack} />
      <Text style={[typography.h2, { color: colors.textPrimary }]}>داشبوردِ مدیریت</Text>

      <View style={{ flexDirection: "row", gap: spacing.sm, flexWrap: "wrap" }}>
        {PRESETS.map((p) => (
          <Button key={p.code} label={p.label} variant={preset === p.code ? "primary" : "secondary"} fullWidth={false} onPress={() => setPreset(p.code)} />
        ))}
      </View>
      {data ? (
        <Text style={[typography.caption, { color: colors.textSecondary }]}>
          بازه: {formatJalaliDate(data.date_from)} تا {formatJalaliDate(data.date_to)}
        </Text>
      ) : null}

      {routes.length > 0 ? (
        <View style={{ flexDirection: "row", gap: spacing.sm, flexWrap: "wrap" }}>
          <Button label="همه‌یِ مسیرها" variant={routeId === null ? "primary" : "secondary"} fullWidth={false} onPress={() => setRouteId(null)} />
          {routes.map((r) => (
            <Button
              key={r.detail_account_id}
              label={r.name ?? r.code}
              variant={routeId === r.detail_account_id ? "primary" : "secondary"}
              fullWidth={false}
              onPress={() => setRouteId(r.detail_account_id)}
            />
          ))}
        </View>
      ) : null}

      {forbidden ? (
        <ErrorState title="دسترسی ندارید" description="این گزارش فقط برایِ مدیر در دسترس است." />
      ) : loading ? (
        <SkeletonList count={4} />
      ) : error ? (
        <ErrorState description={error} onRetry={load} />
      ) : data ? (
        <>
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.sm }}>
            <Kpi label="فروش" value={formatAmount(data.sales_amount)} tone="success" />
            <Kpi label="سفارش" value={String(data.order_count)} />
            <Kpi label="میانگینِ سفارش" value={formatAmount(data.average_order_value)} />
            <Kpi label="وصول" value={formatAmount(data.collection_amount)} tone="info" />
            <Kpi label="نرخِ وصول" value={`${(Number(data.collection_rate) * 100).toFixed(0)}%`} />
            <Kpi label="ویزیت" value={`${data.visit_completed_count}/${data.visit_count}`} />
            <Kpi label="تبدیلِ ویزیت به سفارش" value={`${(Number(data.visit_to_order_conversion) * 100).toFixed(0)}%`} />
            <Kpi label="مشتریِ جدید" value={String(data.new_customer_count)} />
            <Kpi label="مشتریِ بدونِ‌خرید" value={String(data.customers_without_purchase_count)} tone="danger" />
          </View>

          {data.by_visitor.length > 0 ? (
            <View>
              <Text style={[typography.captionBold, { color: colors.textSecondary, marginBottom: spacing.sm }]}>عملکردِ ویزیتورها</Text>
              <Card>
                {data.by_visitor.map((v, index) => (
                  <View
                    key={v.user_id}
                    style={{
                      flexDirection: "row",
                      justifyContent: "space-between",
                      paddingVertical: spacing.sm,
                      borderTopWidth: index === 0 ? 0 : 1,
                      borderTopColor: colors.border,
                    }}
                  >
                    <View>
                      <Text style={[typography.bodyBold, { color: colors.textPrimary }]}>{v.full_name}</Text>
                      <Text style={[typography.caption, { color: colors.textSecondary, marginTop: 2 }]}>
                        {v.visit_completed_count}/{v.visit_count} ویزیت · {v.order_count} سفارش
                      </Text>
                    </View>
                    <Text style={[typography.numeric, { color: colors.textPrimary }]}>{formatAmount(v.sales_amount)}</Text>
                  </View>
                ))}
              </Card>
            </View>
          ) : null}
        </>
      ) : null}
    </ScrollView>
  );
}

function Kpi({ label, value, tone = "neutral" }: { label: string; value: string; tone?: "neutral" | "success" | "info" | "danger" }) {
  const { colors, spacing, typography, radius } = useTheme();
  const fg = { neutral: colors.textPrimary, success: colors.success, info: colors.info, danger: colors.danger }[tone];
  const bg = { neutral: colors.surface, success: colors.successSoft, info: colors.infoSoft, danger: colors.dangerSoft }[tone];
  return (
    <View style={{ flexBasis: "47%", flexGrow: 1, backgroundColor: bg, borderRadius: radius.lg, padding: spacing.md }}>
      <Text style={[typography.caption, { color: fg }]}>{label}</Text>
      <Text style={[typography.numeric, { color: fg, fontSize: 18, marginTop: spacing.xxs }]}>{value}</Text>
    </View>
  );
}
