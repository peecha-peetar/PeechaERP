import React, { useState } from "react";
import { Button, StyleSheet, Text, TextInput, View } from "react-native";
import { CustomerRow, VisitPlanRow } from "../api/types";
import { LocationProvider } from "../location";
import { OfflineQueue } from "../sync/offlineQueue";

interface Props {
  customer: CustomerRow;
  visitPlan: VisitPlanRow;
  offlineQueue: OfflineQueue;
  locationProvider: LocationProvider;
  onDone: () => void;
}

/** شروع/تکمیل/ردِ ویزیت -- طبقِ الگویِ آفلاین‌اول: خودِ اقدام همیشه به
 * صفِ محلی اضافه می‌شود (حتی اگر آنلاین باشیم)؛ ارسالِ واقعی به سرور
 * وظیفه‌یِ SyncEngine.pushQueue است (که هم از این‌جا و هم از رفرشِ
 * فهرستِ ویزیت‌ها صدا زده می‌شود). این یعنی ویزیتور هیچ‌وقت منتظرِ
 * پاسخِ شبکه نمی‌ماند -- طبقِ الزامِ صریحِ کاربر برایِ کارِ درستِ آفلاین. */
export function VisitDetailScreen({ customer, visitPlan, offlineQueue, locationProvider, onDone }: Props) {
  const [phase, setPhase] = useState<"IN_PROGRESS" | "DONE">("IN_PROGRESS");
  const [notes, setNotes] = useState("");
  const [skipReason, setSkipReason] = useState("");

  const start = async () => {
    const position = await locationProvider.getCurrentPosition();
    await offlineQueue.enqueue({
      type: "START_VISIT",
      payload: {
        customer_detail_account_id: customer.detail_account_id,
        visit_plan_id: visitPlan.visit_plan_id,
        check_in_latitude: position?.latitude ?? null,
        check_in_longitude: position?.longitude ?? null,
      },
    });
  };

  const complete = async () => {
    await offlineQueue.enqueue({
      type: "COMPLETE_VISIT",
      payload: { customerVisitId: visitPlan.visit_plan_id, notes: notes || undefined },
    });
    setPhase("DONE");
    onDone();
  };

  const skip = async () => {
    if (!skipReason.trim()) return;
    await offlineQueue.enqueue({
      type: "SKIP_VISIT",
      payload: { customerVisitId: visitPlan.visit_plan_id, skipReason: skipReason.trim() },
    });
    setPhase("DONE");
    onDone();
  };

  return (
    <View style={styles.container}>
      <Text style={styles.title}>{customer.name}</Text>
      {phase === "IN_PROGRESS" ? (
        <>
          <Button title="ثبتِ ورود (شروعِ ویزیت)" onPress={start} />
          <TextInput style={styles.input} placeholder="یادداشت (اختیاری)" value={notes} onChangeText={setNotes} />
          <Button title="تکمیلِ ویزیت" onPress={complete} />
          <TextInput style={styles.input} placeholder="دلیلِ رد کردن" value={skipReason} onChangeText={setSkipReason} />
          <Button title="ردِ ویزیت" color="#c0392b" onPress={skip} disabled={!skipReason.trim()} />
        </>
      ) : (
        <Text>ثبت شد.</Text>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 16 },
  title: { fontSize: 18, marginBottom: 16, textAlign: "right", writingDirection: "rtl" },
  input: { borderWidth: 1, borderColor: "#ccc", borderRadius: 6, padding: 10, marginVertical: 8, textAlign: "right", writingDirection: "rtl" },
});
