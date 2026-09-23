import React, { useCallback, useEffect, useState } from "react";
import { FlatList, RefreshControl, Text, View } from "react-native";
import { ApiClient, ApiError } from "../api/client";
import { NotificationRow } from "../api/types";
import { Button, Card, EmptyState, ErrorState, SkeletonList } from "../components";
import { useTheme } from "../theme/ThemeProvider";

interface Props {
  apiClient: ApiClient;
  onBack: () => void;
}

const TYPE_ICON: Record<string, string> = {
  CUSTOMER_APPROVAL_NEEDED: "👥",
};

export function NotificationsScreen({ apiClient, onBack }: Props) {
  const { colors, spacing, typography } = useTheme();
  const [items, setItems] = useState<NotificationRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setItems(await apiClient.listNotifications());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "دریافتِ اعلان‌ها ناموفق بود.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [apiClient]);

  useEffect(() => {
    load();
  }, [load]);

  const markRead = async (id: number) => {
    setItems((prev) => prev.map((n) => (n.notification_id === id ? { ...n, is_read: true } : n)));
    try {
      await apiClient.markNotificationRead(id);
    } catch {
      // شکستِ شبکه در علامت‌زدن مهم نیست -- دفعه‌یِ بعدِ بازکردنِ صفحه دوباره تلاش می‌شود
    }
  };

  if (loading) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.background, padding: spacing.lg }}>
        <Button label="← بازگشت" variant="ghost" fullWidth={false} onPress={onBack} />
        <SkeletonList count={4} />
      </View>
    );
  }

  return (
    <View style={{ flex: 1, backgroundColor: colors.background, padding: spacing.lg }}>
      <Button label="← بازگشت" variant="ghost" fullWidth={false} onPress={onBack} />
      <Text style={[typography.h2, { color: colors.textPrimary, marginTop: spacing.sm, marginBottom: spacing.md }]}>اعلان‌ها</Text>
      {error ? (
        <ErrorState description={error} onRetry={load} />
      ) : (
        <FlatList
          data={items}
          keyExtractor={(item) => String(item.notification_id)}
          contentContainerStyle={{ gap: spacing.sm }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
          renderItem={({ item }) => (
            <Card onPress={() => !item.is_read && markRead(item.notification_id)} style={{ opacity: item.is_read ? 0.6 : 1 }}>
              <View style={{ flexDirection: "row", gap: spacing.sm }}>
                <Text style={{ fontSize: 20 }}>{TYPE_ICON[item.type_code] ?? "🔔"}</Text>
                <View style={{ flex: 1 }}>
                  <Text style={[typography.bodyBold, { color: colors.textPrimary }]}>{item.title}</Text>
                  {item.body ? <Text style={[typography.caption, { color: colors.textSecondary, marginTop: 2 }]}>{item.body}</Text> : null}
                </View>
                {!item.is_read ? <View style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: colors.primary }} /> : null}
              </View>
            </Card>
          )}
          ListEmptyComponent={<EmptyState icon="🔔" title="اعلانی وجود ندارد" />}
        />
      )}
    </View>
  );
}
