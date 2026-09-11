import React, { useCallback, useEffect, useState } from "react";
import { Button, FlatList, RefreshControl, StyleSheet, Text, View } from "react-native";
import { CustomerRow, VisitPlanRow } from "../api/types";
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
    <View style={styles.container}>
      <Text style={styles.title}>برنامه‌یِ مراجعه</Text>
      {syncError !== null ? <Text style={styles.error}>{syncError}</Text> : null}
      <FlatList
        data={visitPlans}
        keyExtractor={(item) => String(item.visit_plan_id)}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
        renderItem={({ item }) => {
          const customer = customersById.get(item.customer_detail_account_id);
          return (
            <View style={styles.row}>
              <Text style={styles.customerName}>{customer?.name ?? "مشتریِ نامشخص"}</Text>
              <Button
                title="شروعِ ویزیت"
                onPress={() => {
                  if (customer) onOpenVisit(customer, item);
                }}
                disabled={!customer}
              />
            </View>
          );
        }}
        ListEmptyComponent={<Text style={styles.empty}>برنامه‌یِ مراجعه‌ای یافت نشد.</Text>}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 16 },
  title: { fontSize: 18, marginBottom: 12, textAlign: "right", writingDirection: "rtl" },
  error: { color: "#c0392b", marginBottom: 8, textAlign: "right", writingDirection: "rtl" },
  row: { flexDirection: "row-reverse", justifyContent: "space-between", alignItems: "center", paddingVertical: 10, borderBottomWidth: 1, borderColor: "#eee" },
  customerName: { fontSize: 16, textAlign: "right", writingDirection: "rtl" },
  empty: { textAlign: "center", color: "#888", marginTop: 40 },
});
