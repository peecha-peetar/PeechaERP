import React, { useCallback, useEffect, useState } from "react";
import { RefreshControl, ScrollView, Text, View } from "react-native";
import { ApiClient } from "../api/client";
import { CustomerRow, TodayRouteEntry, VisitPlanRow } from "../api/types";
import { EmptyState, SkeletonList, VisitCard, VisitCardState } from "../components";
import { useTheme } from "../theme/ThemeProvider";
import { LocalCache } from "../storage/localCache";
import { SyncEngine } from "../sync/syncEngine";

interface Props {
  apiClient: ApiClient;
  syncEngine: SyncEngine;
  localCache: LocalCache;
  onOpenVisit: (customer: CustomerRow, visitPlan: VisitPlanRow) => void;
}

/** طبقِ باگِ واقعیِ کشف‌شده (R217): این تب قبلاً فقط فهرستِ خامِ
 * VisitPlanِ کش‌شده را بدونِ ترتیب و بدونِ وضعیتِ واقعی نشان می‌داد
 * (همه همیشه «شروعِ ویزیت»، حتی ویزیت‌هایِ تمام‌شده/ردشده‌یِ امروز) --
 * درحالی‌که HomeScreen از قبل همین داده را درست (مرتب‌شده + با
 * وضعیت‌هایِ DONE/CURRENT/UPCOMING/SKIPPED) از GET /dashboard/today
 * می‌خواند. حالا این تب هم از همان منبع استفاده می‌کند -- اگر آنلاین
 * نباشیم، به همان فهرستِ خامِ کش‌شده (این‌بار حداقل مرتب‌شده بر اساسِ
 * ترتیبِ مسیر) برمی‌گردد، بدونِ اینکه کاربر بدونِ برنامه بماند. */
export function VisitListScreen({ apiClient, syncEngine, localCache, onOpenVisit }: Props) {
  const { colors, spacing, typography } = useTheme();
  const [routeEntries, setRouteEntries] = useState<TodayRouteEntry[] | null>(null);
  const [fallbackPlans, setFallbackPlans] = useState<VisitPlanRow[]>([]);
  const [customersById, setCustomersById] = useState<Map<number, CustomerRow>>(new Map());
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [offline, setOffline] = useState(false);

  const loadFromCache = useCallback(async () => {
    const cached = await localCache.getPullResponse();
    if (cached) {
      setFallbackPlans([...cached.visit_plans].sort((a, b) => a.sequence_order - b.sequence_order));
      setCustomersById(new Map(cached.customers.map((c) => [c.detail_account_id, c])));
    }
  }, [localCache]);

  const load = useCallback(async () => {
    try {
      const summary = await apiClient.getTodaySummary();
      setRouteEntries(summary.today_route);
      setOffline(false);
    } catch {
      setRouteEntries(null);
      setOffline(true);
      await loadFromCache();
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [apiClient, loadFromCache]);

  useEffect(() => {
    load();
  }, [load]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      await syncEngine.pull();
      await syncEngine.pushQueue();
    } catch {
      // ادامه با تلاشِ دوباره‌یِ load زیر -- اگر شبکه واقعاً قطع است،
      // همان مسیرِ fallback زیر اجرا می‌شود.
    }
    await load();
  }, [syncEngine, load]);

  const openByIds = useCallback(
    async (customerDetailAccountId: number, visitPlanId: number) => {
      const cached = await localCache.getPullResponse();
      const customer = cached?.customers.find((c) => c.detail_account_id === customerDetailAccountId);
      const visitPlan = cached?.visit_plans.find((p) => p.visit_plan_id === visitPlanId);
      if (customer && visitPlan) onOpenVisit(customer, visitPlan);
    },
    [localCache, onOpenVisit],
  );

  return (
    <View style={{ flex: 1, padding: spacing.lg, backgroundColor: colors.background }}>
      <Text style={[typography.h2, { color: colors.textPrimary, marginBottom: spacing.md }]}>برنامه‌یِ مراجعه</Text>
      {offline ? (
        <Text style={[typography.caption, { color: colors.textSecondary, marginBottom: spacing.sm }]}>
          آفلاین -- وضعیتِ واقعیِ ویزیت‌ها بعدِ اتصال نمایش داده می‌شود.
        </Text>
      ) : null}
      <ScrollView refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}>
        {loading ? (
          <SkeletonList count={4} />
        ) : routeEntries !== null ? (
          routeEntries.length === 0 ? (
            <EmptyState title="برنامه‌ای برایِ امروز نیست" />
          ) : (
            <View style={{ gap: spacing.sm }}>
              {routeEntries.map((entry) => (
                <VisitCard
                  key={entry.visit_plan_id}
                  customerName={entry.customer_name}
                  state={entry.state as VisitCardState}
                  onPress={
                    entry.state === "UPCOMING" || entry.state === "CURRENT"
                      ? () => openByIds(entry.customer_detail_account_id, entry.visit_plan_id)
                      : undefined
                  }
                />
              ))}
            </View>
          )
        ) : fallbackPlans.length === 0 ? (
          <EmptyState title="برنامه‌یِ مراجعه‌ای یافت نشد." />
        ) : (
          <View style={{ gap: spacing.sm }}>
            {fallbackPlans.map((item) => {
              const customer = customersById.get(item.customer_detail_account_id);
              return (
                <VisitCard
                  key={item.visit_plan_id}
                  customerName={customer?.name ?? "مشتریِ نامشخص"}
                  state="UPCOMING"
                  onPress={customer ? () => onOpenVisit(customer, item) : undefined}
                />
              );
            })}
          </View>
        )}
      </ScrollView>
    </View>
  );
}
