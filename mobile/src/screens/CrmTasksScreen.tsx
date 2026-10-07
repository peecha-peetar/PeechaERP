import React, { useCallback, useEffect, useState } from "react";
import { RefreshControl, ScrollView, Text, View } from "react-native";
import { ApiClient, ApiError } from "../api/client";
import { CrmActivityRow, CrmTasksResponse } from "../api/crmTypes";
import { Button, Card, EmptyState, ErrorState, Input, SkeletonList, useToast } from "../components";
import { formatJalaliDate, formatJalaliDateTime, parseJalaliDate } from "../jalali";
import { OfflineQueue } from "../sync/offlineQueue";
import { useTheme } from "../theme/ThemeProvider";

interface Props {
  apiClient: ApiClient;
  offlineQueue: OfflineQueue;
  onBack: () => void;
  onOpenCustomer: (detailAccountId: number) => void;
  onNewLead: () => void;
}

const SECTIONS: { key: string; label: string }[] = [
  { key: "overdue", label: "عقب‌افتاده" }, { key: "today", label: "امروز" }, { key: "tomorrow", label: "فردا" },
  { key: "week", label: "این هفته" },
];
const SLA_LABEL: Record<string, string> = { BREACHED: "نقض SLA", AT_RISK: "نزدیک موعد", OK: "در موعد", NONE: "" };

/** کارهای امروزِ CRM (R286): پیگیری‌ها و تماس‌های عقب‌افتاده/امروز، تیکت‌هایِ ارجاع‌شده. انجام‌دادنِ کار در صفِ
 * آفلاین ثبت می‌شود (با پیگیریِ بعدیِ اختیاری) تا بدونِ اینترنت هم از دست نرود. */
export function CrmTasksScreen({ apiClient, offlineQueue, onBack, onOpenCustomer, onNewLead }: Props) {
  const { colors, spacing, typography } = useTheme();
  const toast = useToast();
  const [data, setData] = useState<CrmTasksResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<Set<number>>(new Set());
  const [openId, setOpenId] = useState<number | null>(null);
  const [result, setResult] = useState("");
  const [followUp, setFollowUp] = useState("");

  const load = useCallback(async () => {
    setError(null);
    try {
      setData(await apiClient.getCrmTasks());
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

  const complete = async (a: CrmActivityRow) => {
    const followIso = followUp.trim() ? parseJalaliDate(followUp) : null;
    if (followUp.trim() && !followIso) {
      toast.show("تاریخ پیگیری نامعتبر است (مثلاً ۱۴۰۵/۰۸/۱۵).", "danger");
      return;
    }
    await offlineQueue.enqueue({
      type: "CRM_COMPLETE_ACTIVITY",
      payload: { activityId: a.activity_id, result_text: result.trim() || null, follow_up_date: followIso },
    });
    setDone((prev) => new Set(prev).add(a.activity_id));
    setOpenId(null);
    setResult("");
    setFollowUp("");
    toast.show("انجام شد؛ پس از اتصال همگام می‌شود.", "success");
  };

  if (loading) return <SkeletonList count={4} />;
  if (error) return <ErrorState description={error} onRetry={load} />;

  const tickets = data?.open_tickets ?? [];
  const total = SECTIONS.reduce((n, s) => n + (data?.buckets[s.key]?.length ?? 0), 0);

  return (
    <ScrollView
      style={{ flex: 1, backgroundColor: colors.background }}
      contentContainerStyle={{ padding: spacing.lg, gap: spacing.md }}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
    >
      <View style={{ flexDirection: "row", gap: spacing.sm }}>
        <Button label="بازگشت" variant="secondary" onPress={onBack} fullWidth={false} size="md" />
        <Button label="ثبت سرنخ تازه" onPress={onNewLead} fullWidth={false} size="md" />
      </View>
      <Text style={[typography.h2, { color: colors.textPrimary }]}>کارهای من</Text>
      {total === 0 && tickets.length === 0 ? <EmptyState title="کار بازی ندارید" /> : null}

      {SECTIONS.map((section) => {
        const rows = (data?.buckets[section.key] ?? []).filter((a) => !done.has(a.activity_id));
        if (rows.length === 0) return null;
        return (
          <View key={section.key} style={{ gap: spacing.sm }}>
            <Text style={[typography.captionBold, { color: section.key === "overdue" ? colors.danger : colors.textSecondary }]}>
              {section.label} ({rows.length})
            </Text>
            {rows.map((a) => (
              <Card key={a.activity_id}>
                <Text style={[typography.bodyBold, { color: colors.textPrimary }]}>
                  {a.type_label}: {a.subject}
                </Text>
                <Text style={[typography.caption, { color: colors.textSecondary, marginTop: spacing.xxs }]}>
                  {a.customer_name || a.lead_name}
                  {a.due_date ? ` — ${formatJalaliDate(a.due_date)}` : ""}
                </Text>
                {a.next_action ? (
                  <Text style={[typography.caption, { color: colors.info, marginTop: spacing.xxs }]}>اقدام بعدی: {a.next_action}</Text>
                ) : null}
                {openId === a.activity_id ? (
                  <View style={{ marginTop: spacing.sm }}>
                    <Input label="نتیجه" value={result} onChangeText={setResult} multiline />
                    <Input label="پیگیری بعدی (تاریخ شمسی، اختیاری)" value={followUp} onChangeText={setFollowUp} placeholder="۱۴۰۵/۰۸/۱۵" />
                    <Button label="ثبت انجام" onPress={() => complete(a)} />
                  </View>
                ) : (
                  <View style={{ flexDirection: "row", gap: spacing.sm, marginTop: spacing.sm }}>
                    <Button label="انجام شد" size="md" fullWidth={false} onPress={() => setOpenId(a.activity_id)} />
                    {a.customer_detail_account_id ? (
                      <Button label="پروندهٔ مشتری" variant="secondary" size="md" fullWidth={false}
                        onPress={() => onOpenCustomer(a.customer_detail_account_id!)} />
                    ) : null}
                  </View>
                )}
              </Card>
            ))}
          </View>
        );
      })}

      {tickets.length > 0 ? (
        <View style={{ gap: spacing.sm }}>
          <Text style={[typography.captionBold, { color: colors.textSecondary }]}>تیکت‌های ارجاع‌شده ({tickets.length})</Text>
          {tickets.map((t) => (
            <Card key={t.ticket_id} onPress={() => onOpenCustomer(t.customer_detail_account_id)}>
              <Text style={[typography.bodyBold, { color: colors.textPrimary }]}>
                {t.type_label} {t.ticket_no ?? ""}: {t.subject}
              </Text>
              <Text style={[typography.caption, { color: t.sla_state === "BREACHED" ? colors.danger : colors.textSecondary }]}>
                {t.customer_name}
                {t.resolution_due_at ? ` — موعد: ${formatJalaliDateTime(t.resolution_due_at)}` : ""} {SLA_LABEL[t.sla_state]}
              </Text>
            </Card>
          ))}
        </View>
      ) : null}
    </ScrollView>
  );
}
