import React, { useState } from "react";
import { ScrollView, Text, View } from "react-native";
import { CustomerRow, VisitPlanRow } from "../api/types";
import { Button, Card, Input, StatusBadge } from "../components";
import { LocationProvider } from "../location";
import { OfflineQueue } from "../sync/offlineQueue";
import { useTheme } from "../theme/ThemeProvider";

interface Props {
  customer: CustomerRow;
  visitPlan: VisitPlanRow;
  offlineQueue: OfflineQueue;
  locationProvider: LocationProvider;
  onDone: () => void;
}

/** شروع/تکمیل/ردِ ویزیت -- طبقِ الگویِ آفلاین‌اول: خودِ اقدام همیشه به
 * صفِ محلی اضافه می‌شود (حتی اگر آنلاین باشیم)؛ ارسالِ واقعی به سرور
 * وظیفه‌یِ SyncEngine.pushQueue است. طبقِ رفعِ باگِ واقعیِ کشف‌شده:
 * COMPLETE_VISIT/SKIP_VISIT دیگر customer_visit_id را حدس نمی‌زنند --
 * startActionKey (idempotencyKeyِ خودِ اقدامِ START_VISIT) را حمل
 * می‌کنند تا SyncEngine از رویِ VisitCorrelationStore شناسهٔ واقعی را
 * resolve کند؛ برایِ همین دکمه‌هایِ تکمیل/رد تا وقتی «شروعِ ویزیت» زده
 * نشده غیرِفعال‌اند. */
export function VisitDetailScreen({ customer, visitPlan, offlineQueue, locationProvider, onDone }: Props) {
  const { colors, spacing, typography } = useTheme();
  const [phase, setPhase] = useState<"NOT_STARTED" | "IN_PROGRESS" | "DONE">("NOT_STARTED");
  const [startActionKey, setStartActionKey] = useState<string | undefined>();
  const [gpsCaptured, setGpsCaptured] = useState(false);
  const [notes, setNotes] = useState("");
  const [skipReason, setSkipReason] = useState("");
  const [busy, setBusy] = useState(false);

  const start = async () => {
    setBusy(true);
    try {
      const position = await locationProvider.getCurrentPosition();
      const action = await offlineQueue.enqueue({
        type: "START_VISIT",
        payload: {
          customer_detail_account_id: customer.detail_account_id,
          visit_plan_id: visitPlan.visit_plan_id,
          check_in_latitude: position?.latitude ?? null,
          check_in_longitude: position?.longitude ?? null,
        },
      });
      setStartActionKey(action.idempotencyKey);
      setGpsCaptured(position !== null);
      setPhase("IN_PROGRESS");
    } finally {
      setBusy(false);
    }
  };

  const complete = async () => {
    if (!startActionKey) return;
    await offlineQueue.enqueue({
      type: "COMPLETE_VISIT",
      payload: { startActionKey, notes: notes.trim() || undefined },
    });
    setPhase("DONE");
    onDone();
  };

  const skip = async () => {
    if (!startActionKey || !skipReason.trim()) return;
    await offlineQueue.enqueue({
      type: "SKIP_VISIT",
      payload: { startActionKey, skipReason: skipReason.trim() },
    });
    setPhase("DONE");
    onDone();
  };

  return (
    <ScrollView contentContainerStyle={{ padding: spacing.lg, gap: spacing.lg, backgroundColor: colors.background }}>
      <View>
        <Text style={[typography.h2, { color: colors.textPrimary }]}>{customer.name}</Text>
        <View style={{ marginTop: spacing.sm }}>
          <StatusBadge
            statusCode={phase}
            label={{ NOT_STARTED: "شروع‌نشده", IN_PROGRESS: "درحالِ‌انجام", DONE: "ثبت‌شد" }[phase]}
          />
        </View>
      </View>

      {phase === "NOT_STARTED" ? (
        <Button label="📍 ثبتِ ورود (شروعِ ویزیت)" onPress={start} loading={busy} />
      ) : (
        <>
          <Card>
            <Text style={[typography.body, { color: gpsCaptured ? colors.success : colors.textSecondary }]}>
              {gpsCaptured ? "📍 موقعیتِ مکانی ثبت شد" : "📍 موقعیتِ مکانی در دسترس نبود"}
            </Text>
          </Card>

          {phase === "IN_PROGRESS" ? (
            <>
              <Input label="یادداشت (اختیاری)" value={notes} onChangeText={setNotes} placeholder="مثلاً: قفسه‌چینیِ محصولات انجام شد" />
              <Button label="✓ تکمیلِ ویزیت" onPress={complete} />

              <Input
                label="دلیلِ ردِ ویزیت (فقط اگر ویزیت انجام نشد)"
                value={skipReason}
                onChangeText={setSkipReason}
                placeholder="مثلاً: فروشگاه بسته بود"
              />
              <Button label="✕ ردِ ویزیت" variant="danger" onPress={skip} disabled={!skipReason.trim()} />
            </>
          ) : (
            <Text style={[typography.body, { color: colors.textSecondary }]}>ویزیت ثبت شد.</Text>
          )}
        </>
      )}
    </ScrollView>
  );
}
