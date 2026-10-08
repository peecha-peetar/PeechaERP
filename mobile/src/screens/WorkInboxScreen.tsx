import React, { useCallback, useEffect, useState } from "react";
import { Pressable, RefreshControl, ScrollView, Text, View } from "react-native";
import { ApiClient, ApiError } from "../api/client";
import { WorkInboxItem, WorkInboxResponse } from "../api/workflowTypes";
import { BottomSheet, Button, EmptyState, ErrorState, Input, SkeletonList, useToast } from "../components";
import { formatJalaliDateTime } from "../jalali";
import { ColorPalette } from "../theme/colors";
import { useTheme } from "../theme/ThemeProvider";
import {
  cardAction, dueLabel, filterInbox, INBOX_FILTERS, InboxFilter, toneColor, ToneColor, URGENCY_COLOR, urgencyOf,
} from "../workflow";

interface Props {
  apiClient: ApiClient;
  onBack: () => void;
  onOpenTask: (taskId: number) => void;
  onOpenCustomer: (detailAccountId: number) => void;
  onOpenCrmTasks: () => void;
}

function paint(colors: ColorPalette, key: ToneColor): { main: string; soft: string } {
  switch (key) {
    case "info":
      return { main: colors.info, soft: colors.infoSoft };
    case "success":
      return { main: colors.success, soft: colors.successSoft };
    case "warning":
      return { main: colors.warning, soft: colors.warningSoft };
    case "danger":
      return { main: colors.danger, soft: colors.dangerSoft };
    default:
      return { main: colors.primary, soft: colors.primarySoft };
  }
}

/** کارتابل یکپارچهٔ موبایل (R300): همهٔ کارها در یک جا، هر کار یک کارت گرافیکی --
 * «چه باید کرد» با رنگ نوع کار، نوار فوریت کنار کارت، نقطه‌های مرحله و دکمهٔ همان کار.
 * تایید/رد کارتابل اسناد همین‌جا انجام می‌شود؛ تایید گردش کار در صفحهٔ کار (با رمز برای موارد حساس). */
export function WorkInboxScreen({ apiClient, onBack, onOpenTask, onOpenCustomer, onOpenCrmTasks }: Props) {
  const { colors, spacing, typography, radius } = useTheme();
  const toast = useToast();
  const [data, setData] = useState<WorkInboxResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<InboxFilter>("ALL");
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [rejecting, setRejecting] = useState<WorkInboxItem | null>(null);
  const [reason, setReason] = useState("");

  const load = useCallback(async () => {
    setError(null);
    try {
      setData(await apiClient.getWorkInbox());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "دریافت کارتابل ناموفق بود.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [apiClient]);

  useEffect(() => {
    load();
  }, [load]);

  const decideLegacy = async (item: WorkInboxItem, approve: boolean, comment = "") => {
    setBusyKey(item.key);
    try {
      if (approve) await apiClient.approveCartableItem(item.ref_id, comment);
      else await apiClient.rejectCartableItem(item.ref_id, comment);
      toast.show(approve ? "تایید شد." : "رد شد.", "success");
      setRejecting(null);
      setReason("");
      await load();
    } catch (e) {
      toast.show(e instanceof ApiError ? e.message : "ثبت تصمیم ناموفق بود.", "danger");
    } finally {
      setBusyKey(null);
    }
  };

  const open = (item: WorkInboxItem) => {
    switch (cardAction(item)) {
      case "OPEN_TASK":
        onOpenTask(item.ref_id);
        return;
      case "OPEN_CUSTOMER":
        if (item.customer_id) onOpenCustomer(item.customer_id);
        return;
      case "OPEN_FOLLOWUPS":
        onOpenCrmTasks();
        return;
      case "DESKTOP_ONLY":
        toast.show("این کار را در برنامهٔ رایانه انجام دهید.", "info");
        return;
      default:
        return;
    }
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

  const requests = data.requests ?? [];
  const items = filterInbox(data.items, filter, requests);
  const approvals = data.approvals ?? data.items.filter((i) => i.kind === "APPROVAL").length;
  const tiles: { key: InboxFilter; label: string; value: number; color: ToneColor }[] = [
    { key: "ALL", label: "همهٔ کارها", value: data.count, color: "primary" },
    { key: "APPROVAL", label: "منتظر تایید من", value: approvals, color: "info" },
    { key: "OVERDUE", label: "عقب‌افتاده", value: data.overdue, color: "danger" },
    { key: "MINE", label: "درخواست‌های من", value: requests.length, color: "success" },
  ];

  const renderCard = (item: WorkInboxItem) => {
    const tone = paint(colors, toneColor(item.tone));
    const urgency = urgencyOf(item);
    const edge = paint(colors, URGENCY_COLOR[urgency]).main;
    const due = dueLabel(item);
    const action = cardAction(item);
    const busy = busyKey === item.key;
    return (
      <Pressable
        key={item.key}
        accessibilityRole="button"
        onPress={() => open(item)}
        style={{
          backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border,
          borderStartWidth: 5, borderStartColor: edge, padding: spacing.md, gap: spacing.xs,
        }}
      >
        <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm, flexWrap: "wrap" }}>
          <View style={{ backgroundColor: tone.soft, borderRadius: radius.lg, paddingHorizontal: spacing.sm, paddingVertical: 2 }}>
            <Text style={[typography.captionBold, { color: tone.main }]}>{item.action || item.kind_label}</Text>
          </View>
          {due ? (
            <View style={{ backgroundColor: paint(colors, URGENCY_COLOR[urgency]).soft, borderRadius: radius.lg, paddingHorizontal: spacing.sm, paddingVertical: 2 }}>
              <Text style={[typography.captionBold, { color: edge }]}>{due}</Text>
            </View>
          ) : null}
          {item.priority_code === "HIGH" || item.priority_code === "CRITICAL" ? (
            <View style={{ backgroundColor: colors.dangerSoft, borderRadius: radius.lg, paddingHorizontal: spacing.sm, paddingVertical: 2 }}>
              <Text style={[typography.captionBold, { color: colors.danger }]}>{item.priority_label}</Text>
            </View>
          ) : null}
        </View>
        <Text style={[typography.bodyBold, { color: colors.textPrimary }]}>{item.title}</Text>
        <Text style={[typography.caption, { color: colors.textSecondary }]}>
          {[item.subtitle, item.definition || item.source_label, item.created_at ? formatJalaliDateTime(item.created_at) : ""]
            .filter(Boolean)
            .join(" · ")}
        </Text>
        {item.path && item.path.length ? (
          <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
            {item.path.map((p, i) => (
              <View
                key={i}
                style={{
                  width: 10, height: 10, borderRadius: 5,
                  backgroundColor: p.state === "done" ? colors.success : p.state === "current" ? colors.info
                    : p.state === "failed" ? colors.danger : "transparent",
                  borderWidth: 1.5,
                  borderColor: p.state === "pending" ? colors.border : "transparent",
                }}
              />
            ))}
            {item.step_no && item.step_total ? (
              <Text style={[typography.caption, { color: colors.textSecondary, marginStart: spacing.xs }]}>
                مرحلهٔ {item.step_no} از {item.step_total}
              </Text>
            ) : null}
          </View>
        ) : null}
        {item.status_note ? <Text style={[typography.caption, { color: colors.warning }]}>{item.status_note}</Text> : null}
        {action === "DECIDE_INLINE" ? (
          <View style={{ flexDirection: "row", gap: spacing.sm, marginTop: spacing.xs }}>
            <Button label="تایید" size="md" fullWidth={false} loading={busy} onPress={() => decideLegacy(item, true)} />
            <Button label="رد" size="md" variant="danger" fullWidth={false} disabled={busy} onPress={() => setRejecting(item)} />
          </View>
        ) : action === "OPEN_TASK" ? (
          <Button label={item.kind === "APPROVAL" ? "بررسی و تصمیم" : "انجام کار"} size="md" fullWidth={false} onPress={() => open(item)} />
        ) : action === "OPEN_CUSTOMER" ? (
          <Button label="بررسی مشتری" size="md" fullWidth={false} onPress={() => open(item)} />
        ) : action === "OPEN_FOLLOWUPS" ? (
          <Button label="انجام پیگیری" size="md" variant="secondary" fullWidth={false} onPress={() => open(item)} />
        ) : action === "DESKTOP_ONLY" ? (
          <Text style={[typography.caption, { color: colors.textSecondary }]}>این کار در برنامهٔ رایانه انجام می‌شود.</Text>
        ) : null}
      </Pressable>
    );
  };

  return (
    <ScrollView
      style={{ flex: 1, backgroundColor: colors.background }}
      contentContainerStyle={{ padding: spacing.lg, gap: spacing.md }}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
    >
      <Button label="بازگشت" variant="ghost" fullWidth={false} onPress={onBack} />
      <Text style={[typography.h2, { color: colors.textPrimary }]}>کارتابل</Text>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.sm }}>
        {tiles.map((t) => {
          const p = paint(colors, t.color);
          const active = filter === t.key;
          return (
            <Pressable
              key={t.key}
              accessibilityRole="button"
              onPress={() => setFilter(t.key)}
              style={{
                flexGrow: 1, flexBasis: "45%", backgroundColor: p.soft, borderRadius: radius.lg, padding: spacing.sm,
                borderWidth: active ? 2 : 1, borderColor: active ? p.main : colors.border,
              }}
            >
              <Text style={[typography.caption, { color: colors.textSecondary }]}>{t.label}</Text>
              <Text style={[typography.h2, { color: p.main }]}>{t.value}</Text>
            </Pressable>
          );
        })}
      </View>
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
      {items.length === 0 ? (
        <EmptyState title={filter === "MINE" ? "درخواست در جریانی ندارید" : "کاری منتظر شما نیست"} />
      ) : null}
      {items.map(renderCard)}

      <BottomSheet visible={rejecting !== null} onClose={() => setRejecting(null)} title="رد درخواست">
        <Input label="دلیل رد" value={reason} onChangeText={setReason} />
        <View style={{ flexDirection: "row", gap: spacing.sm, marginTop: spacing.md }}>
          <Button
            label="ثبت رد"
            variant="danger"
            fullWidth={false}
            disabled={!reason.trim()}
            loading={rejecting !== null && busyKey === rejecting.key}
            onPress={() => rejecting && decideLegacy(rejecting, false, reason.trim())}
          />
          <Button label="انصراف" variant="secondary" fullWidth={false} onPress={() => setRejecting(null)} />
        </View>
      </BottomSheet>
    </ScrollView>
  );
}
