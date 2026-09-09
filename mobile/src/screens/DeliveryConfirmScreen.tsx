import React, { useState } from "react";
import { Button, StyleSheet, Text, TextInput, View } from "react-native";
import { DeliveryLineInput } from "../api/types";
import { CaptureProvider } from "../capture";
import { LocationProvider } from "../location";
import { OfflineQueue } from "../sync/offlineQueue";

interface Props {
  documentId: number;
  customerVisitId: number | null;
  lines: DeliveryLineInput[];
  captureProvider: CaptureProvider;
  locationProvider: LocationProvider;
  offlineQueue: OfflineQueue;
  onDone: () => void;
}

/** ثبتِ رسیدِ تحویل -- طبقِ تصمیمِ طراحیِ R131، این رسید (امضا/عکس/GPS)
 * جایگزینِ تاییدِ مدیر برایِ فاکتورهایِ نقدیِ فی‌المجلسِ پخشِ گرم است؛
 * پس این صفحه بخشِ کنترلی/اعتمادِ اصلیِ کلِ گردشِ کار است، نه یک قدمِ
 * جانبی. */
export function DeliveryConfirmScreen({
  documentId,
  customerVisitId,
  lines,
  captureProvider,
  locationProvider,
  offlineQueue,
  onDone,
}: Props) {
  const [receivedByName, setReceivedByName] = useState("");
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const submit = async () => {
    setSubmitting(true);
    try {
      const [signature, photo, position] = await Promise.all([
        captureProvider.captureSignature(),
        captureProvider.capturePhoto(),
        locationProvider.getCurrentPosition(),
      ]);
      await offlineQueue.enqueue({
        type: "CREATE_DELIVERY_CONFIRMATION",
        payload: {
          document_id: documentId,
          customer_visit_id: customerVisitId,
          received_by_name: receivedByName || null,
          signature_base64: signature,
          photo_base64: photo,
          gps_latitude: position?.latitude ?? null,
          gps_longitude: position?.longitude ?? null,
          notes: notes || null,
          lines,
        },
      });
      onDone();
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <View style={styles.container}>
      <Text style={styles.title}>تاییدِ تحویل</Text>
      <TextInput
        style={styles.input}
        placeholder="نامِ تحویل‌گیرنده"
        value={receivedByName}
        onChangeText={setReceivedByName}
      />
      <TextInput style={styles.input} placeholder="یادداشت" value={notes} onChangeText={setNotes} />
      <Button title={submitting ? "در حالِ ثبت..." : "ثبتِ رسیدِ تحویل"} onPress={submit} disabled={submitting} />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 16 },
  title: { fontSize: 18, marginBottom: 16, textAlign: "right", writingDirection: "rtl" },
  input: { borderWidth: 1, borderColor: "#ccc", borderRadius: 6, padding: 10, marginVertical: 8, textAlign: "right", writingDirection: "rtl" },
});
