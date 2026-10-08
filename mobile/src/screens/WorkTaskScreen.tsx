import React, { useCallback, useEffect, useState } from "react";
import { RefreshControl, ScrollView, Text, View } from "react-native";
import { ApiClient, ApiError } from "../api/client";
import { Colleague, WorkTaskDetail } from "../api/workflowTypes";
import { BottomSheet, Button, Card, ErrorState, Input, SkeletonList, useToast } from "../components";
import { formatJalaliDateTime } from "../jalali";
import { OfflineQueue } from "../sync/offlineQueue";
import { SyncEngine } from "../sync/syncEngine";
import { useTheme } from "../theme/ThemeProvider";
import { needsComment, needsStepUp, pathText } from "../workflow";

interface Props {
  apiClient: ApiClient;
  offlineQueue: OfflineQueue;
  syncEngine: SyncEngine;
  taskId: number;
  onBack: () => void;
  onDone: () => void;
}

/** جزئیات کار گردش کار در موبایل (R297): اطلاعات سند، مسیر تایید، سابقه و تصمیم. تصمیم عادی در صف آفلاین ثبت
 * می‌شود؛ تایید مورد حساس فقط آنلاین و با وارد کردن دوبارهٔ رمز انجام می‌شود. */
export function WorkTaskScreen({ apiClient, offlineQueue, syncEngine, taskId, onBack, onDone }: Props) {
  const { colors, spacing, typography } = useTheme();
  const toast = useToast();
  const [detail, setDetail] = useState<WorkTaskDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [stepUpDecision, setStepUpDecision] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const [colleagues, setColleagues] = useState<Colleague[] | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setDetail(await apiClient.getWorkTask(taskId));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "دریافت کار ناموفق بود.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [apiClient, taskId]);

  useEffect(() => {
    load();
  }, [load]);

  /** صف آفلاین ← تلاش برای ارسال فوری؛ نتیجه برای کاربر روشن گفته می‌شود. */
  const queueAndSync = async (input: Parameters<OfflineQueue["enqueue"]>[0], success: string) => {
    setBusy(true);
    try {
      const action = await offlineQueue.enqueue(input);
      try {
        const result = await syncEngine.pushQueue();
        const failed = result.failedButKept.find((f) => f.idempotencyKey === action.idempotencyKey);
        if (failed) {
          toast.show(failed.reason, "danger");
          await load();
          return false;
        }
        if (result.succeeded.includes(action.idempotencyKey)) {
          toast.show(success, "success");
          return true;
        }
      } catch {
        // بدون اینترنت: در صف می‌ماند
      }
      toast.show("ثبت شد؛ پس از اتصال به اینترنت فرستاده می‌شود.", "info");
      return true;
    } finally {
      setBusy(false);
    }
  };

  const decide = async (code: string) => {
    if (!detail) return;
    if (needsComment(code) && !comment.trim()) {
      toast.show("برای این تصمیم، توضیح بنویسید.", "danger");
      return;
    }
    if (needsStepUp(detail, code)) {
      setPassword("");
      setStepUpDecision(code);
      return;
    }
    const ok = await queueAndSync(
      { type: "WF_DECIDE", payload: { taskId, decision: code, comment: comment.trim(), rowVersion: detail.row_version } },
      "تصمیم شما ثبت شد.",
    );
    if (ok) onDone();
  };

  const confirmStepUp = async () => {
    if (!detail || !stepUpDecision) return;
    if (!password) {
      toast.show("رمز خود را وارد کنید.", "danger");
      return;
    }
    setBusy(true);
    try {
      const result = await apiClient.decideWorkTask(taskId, {
        decision: stepUpDecision, comment: comment.trim(), row_version: detail.row_version, password,
      });
      setStepUpDecision(null);
      toast.show(result.message, "success");
      onDone();
    } catch (e) {
      toast.show(e instanceof ApiError ? e.message : "برای تایید این مورد اتصال به اینترنت لازم است.", "danger");
    } finally {
      setPassword("");
      setBusy(false);
    }
  };

  const addComment = async () => {
    if (!comment.trim()) return;
    if (await queueAndSync({ type: "WF_COMMENT", payload: { taskId, text: comment.trim() } }, "یادداشت ثبت شد.")) {
      setComment("");
      await load();
    }
  };

  const openDelegate = async () => {
    try {
      setColleagues(await apiClient.listColleagues());
    } catch (e) {
      toast.show(e instanceof ApiError ? e.message : "دریافت فهرست همکاران ناموفق بود.", "danger");
    }
  };

  const delegateTo = async (c: Colleague) => {
    setColleagues(null);
    const ok = await queueAndSync(
      { type: "WF_DELEGATE", payload: { taskId, toUserId: c.user_id, comment: comment.trim() } },
      `کار به ${c.name} سپرده شد.`,
    );
    if (ok) onDone();
  };

  if (loading) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.background, padding: spacing.lg }}>
        <SkeletonList count={4} />
      </View>
    );
  }
  if (error || detail === null) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.background }}>
        <ErrorState description={error ?? "کار یافت نشد."} onRetry={load} />
      </View>
    );
  }

  const label = (text: string) => (
    <Text style={[typography.captionBold, { color: colors.textSecondary, marginBottom: spacing.xs }]}>{text}</Text>
  );

  return (
    <ScrollView
      style={{ flex: 1, backgroundColor: colors.background }}
      contentContainerStyle={{ padding: spacing.lg, gap: spacing.md }}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
    >
      <Button label="بازگشت" variant="ghost" fullWidth={false} onPress={onBack} />
      <Text style={[typography.h2, { color: colors.textPrimary }]}>{detail.title}</Text>
      <Text style={[typography.caption, { color: colors.textSecondary }]}>
        {detail.definition} · درخواست‌کننده: {detail.requested_by || "سیستم"}
        {detail.created_at ? ` · ${formatJalaliDateTime(detail.created_at)}` : ""}
      </Text>
      {detail.due_at ? (
        <Text style={[typography.captionBold, { color: detail.is_overdue ? colors.danger : colors.textSecondary }]}>
          مهلت: {formatJalaliDateTime(detail.due_at)}
          {detail.sla_label ? ` · ${detail.sla_label}` : ""}
        </Text>
      ) : null}
      {detail.summary ? (
        <Text style={[typography.body, { color: colors.textPrimary }]}>{detail.summary}</Text>
      ) : null}
      {detail.requires_step_up ? (
        <Text style={[typography.captionBold, { color: colors.warning }]}>این مورد حساس است؛ تایید آن به وارد کردن دوبارهٔ رمز نیاز دارد.</Text>
      ) : null}

      {detail.context.length > 0 ? (
        <Card>
          {label(detail.entity_label || "اطلاعات سند")}
          {detail.context.map((row) => (
            <View key={row.label} style={{ flexDirection: "row", justifyContent: "space-between", marginTop: spacing.xxs }}>
              <Text style={[typography.caption, { color: colors.textSecondary }]}>{row.label}</Text>
              <Text style={[typography.bodyBold, { color: colors.textPrimary }]}>{row.value}</Text>
            </View>
          ))}
        </Card>
      ) : null}

      {detail.path.length > 0 ? (
        <Card>
          {label("مسیر تایید")}
          <Text style={[typography.body, { color: colors.textPrimary }]}>{pathText(detail.path)}</Text>
        </Card>
      ) : null}

      {detail.instructions ? (
        <Card>
          {label("توضیح")}
          <Text style={[typography.body, { color: colors.textPrimary }]}>{detail.instructions}</Text>
        </Card>
      ) : null}

      {detail.history.length > 0 ? (
        <Card>
          {label("سابقه")}
          {detail.history.map((h, i) => (
            <Text key={i} style={[typography.caption, { color: colors.textPrimary, marginTop: spacing.xxs }]}>
              {h.at ? `${formatJalaliDateTime(h.at)} · ` : ""}
              {h.user}: {h.decision}
              {h.note ? ` — ${h.note}` : ""}
            </Text>
          ))}
        </Card>
      ) : null}

      {detail.decisions.length > 0 ? (
        <>
          <Input label="توضیح شما" value={comment} onChangeText={setComment} multiline placeholder="برای رد یا برگشت، توضیح لازم است" />
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.sm }}>
            {detail.decisions.map((d) => (
              <Button
                key={d.code}
                label={d.label}
                size="md"
                fullWidth={false}
                variant={d.code === "REJECT" ? "danger" : d.code === "CHANGES" ? "secondary" : "primary"}
                loading={busy}
                onPress={() => decide(d.code)}
              />
            ))}
          </View>
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.sm }}>
            <Button label="ثبت یادداشت" size="md" variant="secondary" fullWidth={false} disabled={busy || !comment.trim()} onPress={addComment} />
            <Button label="سپردن به همکار" size="md" variant="secondary" fullWidth={false} disabled={busy} onPress={openDelegate} />
          </View>
        </>
      ) : (
        <Text style={[typography.caption, { color: colors.textSecondary }]}>این کار منتظر تصمیم شما نیست ({detail.status_label}).</Text>
      )}

      <BottomSheet visible={stepUpDecision !== null} onClose={() => setStepUpDecision(null)} title="تایید با رمز">
        <Text style={[typography.body, { color: colors.textPrimary, marginBottom: spacing.sm }]}>
          برای تایید این مورد حساس، رمز ورود خود را دوباره وارد کنید.
        </Text>
        <Input label="رمز" value={password} onChangeText={setPassword} secureTextEntry autoCapitalize="none" />
        <View style={{ flexDirection: "row", gap: spacing.sm, marginTop: spacing.md }}>
          <Button label="تایید" fullWidth={false} loading={busy} onPress={confirmStepUp} />
          <Button label="انصراف" variant="secondary" fullWidth={false} onPress={() => setStepUpDecision(null)} />
        </View>
      </BottomSheet>

      <BottomSheet visible={colleagues !== null} onClose={() => setColleagues(null)} title="سپردن به همکار">
        <ScrollView style={{ maxHeight: 360 }}>
          {(colleagues ?? []).map((c) => (
            <Card key={c.user_id} onPress={() => delegateTo(c)}>
              <Text style={[typography.body, { color: colors.textPrimary }]}>{c.name}</Text>
            </Card>
          ))}
        </ScrollView>
      </BottomSheet>
    </ScrollView>
  );
}
