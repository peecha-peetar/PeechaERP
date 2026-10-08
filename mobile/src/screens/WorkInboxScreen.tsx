import React, { useCallback, useEffect, useState } from "react";
import { Pressable, RefreshControl, ScrollView, Text, View } from "react-native";
import { ApiClient, ApiError } from "../api/client";
import { WorkInboxItem, WorkInboxResponse } from "../api/workflowTypes";
import { Button, Card, EmptyState, ErrorState, SkeletonList, useToast } from "../components";
import { formatJalaliDateTime } from "../jalali";
import { useTheme } from "../theme/ThemeProvider";
import { filterInbox, INBOX_FILTERS, InboxFilter } from "../workflow";

interface Props {
  apiClient: ApiClient;
  onBack: () => void;
  onOpenTask: (taskId: number) => void;
  onOpenApprovals: () => void;
  onOpenCrmTasks: () => void;
}

/** کارتابل یکپارچهٔ موبایل (R297): تاییدها و کارهای گردش کار، کارتابل قبلی و پیگیری‌ها در یک فهرست. */
export function WorkInboxScreen({ apiClient, onBack, onOpenTask, onOpenApprovals, onOpenCrmTasks }: Props) {
  const { colors, spacing, typography, radius } = useTheme();
  const toast = useToast();
  const [data, setData] = useState<WorkInboxResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<InboxFilter>("ALL");

  const load = useCallback(async () => {
    setError(null);
    try {
      setData(await apiClient.getWorkInbox());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "دریافت کارها ناموفق بود.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [apiClient]);

  useEffect(() => {
    load();
  }, [load]);

  const open = (item: WorkInboxItem) => {
    if (item.source === "WF") onOpenTask(item.ref_id);
    else if (item.source === "CARTABLE") onOpenApprovals();
    else if (item.source === "CRM") onOpenCrmTasks();
    else toast.show("این کار را در برنامهٔ رایانه انجام دهید.", "info");
  };

  if (loading) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.background, padding: spacing.lg }}>
        <SkeletonList count={4} />
      </View>
    );
  }
  if (error || data === null) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.background }}>
        <ErrorState description={error ?? "اطلاعات یافت نشد."} onRetry={load} />
      </View>
    );
  }

  const items = filterInbox(data.items, filter);
  return (
    <ScrollView
      style={{ flex: 1, backgroundColor: colors.background }}
      contentContainerStyle={{ padding: spacing.lg, gap: spacing.md }}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
    >
      <Button label="بازگشت" variant="ghost" fullWidth={false} onPress={onBack} />
      <Text style={[typography.h2, { color: colors.textPrimary }]}>کارهای من</Text>
      <Text style={[typography.caption, { color: colors.textSecondary }]}>
        {data.count} کار باز{data.overdue ? ` · ${data.overdue} کار گذشته از مهلت` : ""}
      </Text>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.sm }}>
        {INBOX_FILTERS.map((f) => (
          <Pressable
            key={f.key}
            accessibilityRole="button"
            onPress={() => setFilter(f.key)}
            style={{
              paddingVertical: spacing.xs, paddingHorizontal: spacing.md, borderRadius: radius.lg,
              backgroundColor: filter === f.key ? colors.primary : colors.surface,
              borderWidth: 1, borderColor: filter === f.key ? colors.primary : colors.border,
            }}
          >
            <Text style={[typography.captionBold, { color: filter === f.key ? colors.textInverse : colors.textPrimary }]}>{f.label}</Text>
          </Pressable>
        ))}
      </View>
      {items.length === 0 ? <EmptyState title="کاری در این بخش ندارید" /> : null}
      {items.map((item) => (
        <Card key={item.key} onPress={() => open(item)}>
          <Text style={[typography.bodyBold, { color: colors.textPrimary }]}>{item.title}</Text>
          <Text style={[typography.caption, { color: colors.textSecondary, marginTop: spacing.xxs }]}>
            {item.kind_label} · {item.source_label}
            {item.subtitle ? ` · ${item.subtitle}` : ""}
          </Text>
          {item.due_at ? (
            <Text style={[typography.caption, { color: item.is_overdue ? colors.danger : colors.textSecondary, marginTop: spacing.xxs }]}>
              مهلت: {formatJalaliDateTime(item.due_at)}
              {item.is_overdue ? " (گذشته)" : ""}
            </Text>
          ) : null}
          {item.status_note ? (
            <Text style={[typography.caption, { color: colors.warning, marginTop: spacing.xxs }]}>{item.status_note}</Text>
          ) : null}
        </Card>
      ))}
    </ScrollView>
  );
}
