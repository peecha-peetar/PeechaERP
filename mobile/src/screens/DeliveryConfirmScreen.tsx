import React, { useState } from "react";
import { Text, TextInput, View } from "react-native";
import { DeliveryLineInput } from "../api/types";
import { Button } from "../components";
import { useTheme } from "../theme/ThemeProvider";
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
  const { colors, spacing, radius, typography } = useTheme();
  const [receivedByName, setReceivedByName] = useState("");
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const submit = async () => {
    setSubmitting(true);
    try {
      // طبقِ باگِ واقعیِ کشف‌شده در R191: امضا یک Modalِ درون‌اپ باز
      // می‌کند و دوربین کلِ اپ را موقتاً به یک اکتیویتیِ نیتیوِ جدا
      // می‌برد -- هم‌زمانی‌شان در Promise.all باعثِ تداخلِ UI می‌شود.
      const signature = await captureProvider.captureSignature();
      const [photo, position] = await Promise.all([
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

  const inputStyle = [
    typography.body,
    {
      color: colors.textPrimary,
      backgroundColor: colors.surface,
      borderWidth: 1,
      borderColor: colors.border,
      borderRadius: radius.md,
      padding: spacing.md,
      marginVertical: spacing.sm,
    },
  ];

  return (
    <View style={{ flex: 1, padding: spacing.lg, backgroundColor: colors.background }}>
      <Text style={[typography.h2, { color: colors.textPrimary, marginBottom: spacing.lg }]}>تاییدِ تحویل</Text>
      <TextInput
        style={inputStyle}
        placeholder="نامِ تحویل‌گیرنده"
        placeholderTextColor={colors.textSecondary}
        value={receivedByName}
        onChangeText={setReceivedByName}
      />
      <TextInput
        style={inputStyle}
        placeholder="یادداشت"
        placeholderTextColor={colors.textSecondary}
        value={notes}
        onChangeText={setNotes}
      />
      <Button label="ثبتِ رسیدِ تحویل" onPress={submit} loading={submitting} disabled={submitting} />
    </View>
  );
}
