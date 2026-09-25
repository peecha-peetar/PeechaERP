import React, { useCallback, useEffect, useState } from "react";
import { FlatList, RefreshControl, Text, View } from "react-native";
import { CustomerRow, VisitPlanRow } from "../api/types";
import { Button, EmptyState } from "../components";
import { useTheme } from "../theme/ThemeProvider";
import { LocalCache } from "../storage/localCache";
import { SyncEngine } from "../sync/syncEngine";

interface Props {
  syncEngine: SyncEngine;
  localCache: LocalCache;
  onOpenVisit: (customer: CustomerRow, visitPlan: VisitPlanRow) => void;
}

/** فهرستِ برنامه‌یِ مراجعه‌یِ امروزِ ویزیتور -- از کشِ محلی خوانده
 * می‌شود (کارِ آفلاین)، و pull-to-refresh آن را از سرور تازه می‌کند
 * (اگر اتصال باشد). فیلترِ روزِ هفته در R133 اضافه می‌شود؛ فعلاً کلِ
 * برنامه‌یِ ویزیتور نمایش داده می‌شود. */
export function VisitListScreen({ syncEngine, localCache, onOpenVisit }: Props) {
  const { colors, spacing, typography } = useTheme();
  const [visitPlans, setVisitPlans] = useState<VisitPlanRow[]>([]);
  const [customersById, setCustomersById] = useState<Map<number, CustomerRow>>(new Map());
  const [refreshing, setRefreshing] = useState(false);
  const [syncError, setSyncError] = useState<string | null>(null);

  const loadFromCache = useCallback(async () => {
    const cached = await localCache.getPullResponse();
    if (cached) {
      setVisitPlans(cached.visit_plans);
      setCustomersById(new Map(cached.customers.map((c) => [c.detail_account_id, c])));
    }
  }, [localCache]);

  useEffect(() => {
    loadFromCache();
  }, [loadFromCache]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    setSyncError(null);
    try {
      await syncEngine.pull();
      await syncEngine.pushQueue();
      await loadFromCache();
    } catch {
      setSyncError("همگام‌سازی ناموفق بود -- برنامه‌یِ ذخیره‌شده‌یِ قبلی نمایش داده می‌شود.");
    } finally {
      setRefreshing(false);
    }
  }, [syncEngine, loadFromCache]);

  return (
    <View style={{ flex: 1, padding: spacing.lg, backgroundColor: colors.background }}>
      <Text style={[typography.h2, { color: colors.textPrimary, marginBottom: spacing.md }]}>برنامه‌یِ مراجعه</Text>
      {syncError !== null ? (
        <Text style={[typography.caption, { color: colors.danger, marginBottom: spacing.sm }]}>{syncError}</Text>
      ) : null}
      <FlatList
        data={visitPlans}
        keyExtractor={(item) => String(item.visit_plan_id)}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
        renderItem={({ item }) => {
          const customer = customersById.get(item.customer_detail_account_id);
          return (
            <View
              style={{
                flexDirection: "row",
                justifyContent: "space-between",
                alignItems: "center",
                paddingVertical: spacing.sm,
                borderBottomWidth: 1,
                borderColor: colors.border,
              }}
            >
              <Text style={[typography.body, { color: colors.textPrimary, flex: 1 }]}>{customer?.name ?? "مشتریِ نامشخص"}</Text>
              <Button
                label="شروعِ ویزیت"
                fullWidth={false}
                onPress={() => {
                  if (customer) onOpenVisit(customer, item);
                }}
                disabled={!customer}
              />
            </View>
          );
        }}
        ListEmptyComponent={<EmptyState title="برنامه‌یِ مراجعه‌ای یافت نشد." />}
      />
    </View>
  );
}
