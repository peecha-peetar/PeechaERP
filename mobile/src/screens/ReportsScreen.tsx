import React, { useCallback, useEffect, useState } from "react";
import { RefreshControl, ScrollView, Text, View } from "react-native";
import { ApiClient, ApiError } from "../api/client";
import { TodaySummaryResponse } from "../api/types";
import { Card, ErrorState, SkeletonList } from "../components";
import { formatAmount } from "../format";
import { useTheme } from "../theme/ThemeProvider";

interface Props {
  apiClient: ApiClient;
}

/** طبقِ درخواستِ صریحِ کاربر («در پخشِ گرم... آیتم‌هایِ مشتری و فاکتور و
 * وصول و گزارشات باید باشه»): برایِ پخشِ گرم که ویزیت/برنامهٔ روزانه
 * معنا ندارد، به‌جایِ فرمِ کاملِ صفحه‌یِ خانه، همین سه شمارهٔ کلیدیِ روزِ
 * همین ویزیتور (تعدادِ فاکتور/جمعِ فروش/جمعِ وصول) -- از همان
 * /dashboard/today که هم‌اکنون هست، بدونِ اندپوینتِ تازه. */
export function ReportsScreen({ apiClient }: Props) {
  const { colors, spacing, typography } = useTheme();
  const [summary, setSummary] = useState<TodaySummaryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const data = await apiClient.getTodaySummary();
      setSummary(data);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "دریافتِ گزارشِ امروز ناموفق بود.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [apiClient]);

  useEffect(() => {
    load();
  }, [load]);

  const onRefresh = useCallback(() => {
    setRefreshing(true);
    load();
  }, [load]);

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <ScrollView
        contentContainerStyle={{ padding: spacing.lg, gap: spacing.lg }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
      >
        <Text style={[typography.h2, { color: colors.textPrimary }]}>گزارشِ امروز</Text>

        {loading ? (
          <SkeletonList count={3} />
        ) : error ? (
          <ErrorState description={error} onRetry={load} />
        ) : summary ? (
          <View style={{ gap: spacing.md }}>
            <Card>
              <Text style={[typography.caption, { color: colors.textSecondary }]}>تعدادِ فاکتورِ امروز</Text>
              <Text style={[typography.numeric, { color: colors.textPrimary, fontSize: 24, marginTop: spacing.xxs }]}>
                {summary.order_count}
              </Text>
            </Card>
            <Card style={{ backgroundColor: colors.successSoft, borderColor: colors.successSoft }}>
              <Text style={[typography.caption, { color: colors.success }]}>جمعِ فروشِ امروز</Text>
              <Text style={[typography.numeric, { color: colors.success, fontSize: 24, marginTop: spacing.xxs }]}>
                {formatAmount(summary.sales_amount)}
              </Text>
            </Card>
            <Card style={{ backgroundColor: colors.infoSoft, borderColor: colors.infoSoft }}>
              <Text style={[typography.caption, { color: colors.info }]}>جمعِ وصولِ امروز</Text>
              <Text style={[typography.numeric, { color: colors.info, fontSize: 24, marginTop: spacing.xxs }]}>
                {formatAmount(summary.collection_amount)}
              </Text>
            </Card>
          </View>
        ) : null}
      </ScrollView>
    </View>
  );
}
