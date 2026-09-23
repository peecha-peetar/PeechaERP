import React, { useCallback, useEffect, useState } from "react";
import { RefreshControl, ScrollView, Text, View } from "react-native";
import { ApiClient, ApiError } from "../api/client";
import { CustomerRow, TodaySummaryResponse, VisitPlanRow } from "../api/types";
import { Card, EmptyState, ErrorState, SkeletonList, VisitCard, VisitCardState } from "../components";
import { formatAmount } from "../format";
import { useTheme } from "../theme/ThemeProvider";
import { LocalCache } from "../storage/localCache";

interface Props {
  apiClient: ApiClient;
  localCache: LocalCache;
  userFullName: string;
  onOpenVisit: (customer: CustomerRow, visitPlan: VisitPlanRow) => void;
}

/** صفحه‌یِ خانه -- طبقِ اصلِ صریحِ کاربر («در ۳ ثانیه اطلاعاتِ مهم را
 * نشان دهد»): آماره‌یِ امروز + ویزیتِ بعدی + برنامه‌یِ امروز، همه از یک
 * درخواستِ تکی (/dashboard/today). برایِ بازکردنِ ویزیت، مشتری/برنامه‌یِ
 * کاملشان از کشِ محلیِ pull (که از قبل رویِ دستگاه هست) resolve می‌شود --
 * نه یک درخواستِ شبکه‌یِ دیگر. */
export function HomeScreen({ apiClient, localCache, userFullName, onOpenVisit }: Props) {
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
      setError(e instanceof ApiError ? e.message : "دریافتِ اطلاعاتِ امروز ناموفق بود.");
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

  const openVisitByIds = useCallback(
    async (customerDetailAccountId: number, visitPlanId: number) => {
      const cached = await localCache.getPullResponse();
      const customer = cached?.customers.find((c) => c.detail_account_id === customerDetailAccountId);
      const visitPlan = cached?.visit_plans.find((p) => p.visit_plan_id === visitPlanId);
      if (customer && visitPlan) onOpenVisit(customer, visitPlan);
    },
    [localCache, onOpenVisit],
  );

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <ScrollView
        contentContainerStyle={{ padding: spacing.lg, gap: spacing.lg }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
      >
        <Text style={[typography.h2, { color: colors.textPrimary }]}>
          سلام، {userFullName.split(" ")[0]} 👋
        </Text>

        {loading ? (
          <SkeletonList count={3} />
        ) : error ? (
          <ErrorState description={error} onRetry={load} />
        ) : summary ? (
          <>
            <StatsGrid summary={summary} />
            {summary.next_visit ? (
              <NextVisitCard
                customerName={summary.next_visit.customer_name}
                onPress={() =>
                  openVisitByIds(summary.next_visit!.customer_detail_account_id, summary.next_visit!.visit_plan_id)
                }
              />
            ) : null}

            <Text style={[typography.captionBold, { color: colors.textSecondary }]}>برنامه‌یِ امروز</Text>
            {summary.today_route.length === 0 ? (
              <EmptyState icon="🗓️" title="برنامه‌ای برایِ امروز نیست" />
            ) : (
              <View style={{ gap: spacing.sm }}>
                {summary.today_route.map((entry) => (
                  <VisitCard
                    key={entry.visit_plan_id}
                    customerName={entry.customer_name}
                    state={entry.state as VisitCardState}
                    onPress={
                      entry.state === "UPCOMING" || entry.state === "CURRENT"
                        ? () => openVisitByIds(entry.customer_detail_account_id, entry.visit_plan_id)
                        : undefined
                    }
                  />
                ))}
              </View>
            )}
          </>
        ) : null}
      </ScrollView>
    </View>
  );
}

function StatsGrid({ summary }: { summary: TodaySummaryResponse }) {
  const { colors, spacing, typography, radius } = useTheme();
  const tiles: { icon: string; label: string; value: string; bg: string; fg: string }[] = [
    { icon: "📍", label: "ویزیت", value: `${summary.visit_completed_count}/${summary.visit_count}`, bg: colors.surface, fg: colors.textPrimary },
    { icon: "🛒", label: "سفارش", value: String(summary.order_count), bg: colors.surface, fg: colors.textPrimary },
    { icon: "💰", label: "فروش", value: formatAmount(summary.sales_amount), bg: colors.successSoft, fg: colors.success },
    { icon: "💳", label: "وصول", value: formatAmount(summary.collection_amount), bg: colors.infoSoft, fg: colors.info },
  ];
  return (
    <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.sm }}>
      {tiles.map((tile) => (
        <View
          key={tile.label}
          style={{ flexBasis: "47%", flexGrow: 1, backgroundColor: tile.bg, borderRadius: radius.lg, padding: spacing.md }}
        >
          <Text style={[typography.caption, { color: tile.fg }]}>
            {tile.icon} {tile.label}
          </Text>
          <Text style={[typography.numeric, { color: tile.fg, fontSize: 20, marginTop: spacing.xxs }]}>{tile.value}</Text>
        </View>
      ))}
    </View>
  );
}

function NextVisitCard({ customerName, onPress }: { customerName: string; onPress: () => void }) {
  const { colors, spacing, typography } = useTheme();
  return (
    <View>
      <Text style={[typography.captionBold, { color: colors.textSecondary, marginBottom: spacing.sm }]}>ویزیتِ بعدی</Text>
      <Card onPress={onPress} style={{ backgroundColor: colors.primary, borderColor: colors.primary }}>
        <Text style={[typography.h3, { color: colors.textInverse }]}>{customerName}</Text>
        <Text style={[typography.button, { color: colors.textInverse, textAlign: "left", marginTop: spacing.md, writingDirection: "rtl" }]}>
          شروعِ ویزیت ←
        </Text>
      </Card>
    </View>
  );
}
