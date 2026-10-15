import React, { useEffect, useState } from "react";
import { ScrollView, Text, View } from "react-native";
import { ApiClient } from "../api/client";
import { CrmLeadSource } from "../api/crmTypes";
import { Button, Input, useToast } from "../components";
import { toAsciiDigits } from "../format";
import { OfflineQueue } from "../sync/offlineQueue";
import { useTheme } from "../theme/ThemeProvider";

interface Props {
  apiClient: ApiClient;
  offlineQueue: OfflineQueue;
  onDone: () => void;
}

/** ثبتِ سرنخِ میدانی (R286) -- آفلاین‌اول: در صف ثبت می‌شود. تکراری‌بودن رد نمی‌شود (allow_duplicate) چون
 * خطایِ ۴xx اقدامِ صف را برای همیشه حذف می‌کند؛ ادغامِ تکراری‌ها در دسکتاپ انجام می‌شود. */
export function CrmLeadScreen({ apiClient, offlineQueue, onDone }: Props) {
  const { colors, spacing, typography } = useTheme();
  const toast = useToast();
  const [sources, setSources] = useState<CrmLeadSource[]>([]);
  const [sourceId, setSourceId] = useState<number | null>(null);
  const [fullName, setFullName] = useState("");
  const [companyName, setCompanyName] = useState("");
  const [mobile, setMobile] = useState("");
  const [interest, setInterest] = useState("");
  const [value, setValue] = useState("");
  const [city, setCity] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    apiClient
      .listCrmLeadSources()
      .then((rows) => {
        setSources(rows);
        setSourceId(rows.find((s) => s.code === "VISITOR")?.source_id ?? null);
      })
      .catch(() => setSources([]));
  }, [apiClient]);

  const submit = async () => {
    const mobileAscii = toAsciiDigits(mobile.trim());
    if (!fullName.trim()) {
      toast.show("نام سرنخ را وارد کنید.", "danger");
      return;
    }
    if (!mobileAscii) {
      toast.show("شمارهٔ موبایل لازم است.", "danger");
      return;
    }
    const amount = toAsciiDigits(value.trim()).replace(/[,٬]/g, "");
    if (amount && !/^\d+(\.\d+)?$/.test(amount)) {
      toast.show("ارزش احتمالی باید عدد باشد.", "danger");
      return;
    }
    setBusy(true);
    try {
      await offlineQueue.enqueue({
        type: "CRM_CREATE_LEAD",
        payload: {
          full_name: fullName.trim(), company_name: companyName.trim() || null, mobile: mobileAscii, source_id: sourceId,
          interested_text: interest.trim() || null, estimated_value: amount || null, city: city.trim() || null,
          notes: notes.trim() || null, allow_duplicate: true,
        },
      });
      toast.show("سرنخ ثبت شد؛ پس از اتصال همگام می‌شود.", "success");
      onDone();
    } finally {
      setBusy(false);
    }
  };

  return (
    <ScrollView style={{ flex: 1, backgroundColor: colors.background }} contentContainerStyle={{ padding: spacing.lg }}>
      <Text style={[typography.h2, { color: colors.textPrimary, marginBottom: spacing.md }]}>ثبت سرنخ تازه</Text>
      <Input label="نام و نام خانوادگی *" value={fullName} onChangeText={setFullName} />
      <Input label="نام فروشگاه/شرکت" value={companyName} onChangeText={setCompanyName} />
      <Input label="موبایل *" value={mobile} onChangeText={setMobile} keyboardType="phone-pad" />
      {sources.length > 0 ? (
        <View style={{ marginBottom: spacing.md }}>
          <Text style={[typography.captionBold, { color: colors.textSecondary, marginBottom: spacing.xs }]}>منبع</Text>
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.xs }}>
            {sources.map((s) => (
              <Button key={s.source_id} label={s.name} size="md" fullWidth={false}
                variant={sourceId === s.source_id ? "primary" : "secondary"} onPress={() => setSourceId(s.source_id)} />
            ))}
          </View>
        </View>
      ) : null}
      <Input label="محصول/نیاز مورد علاقه" value={interest} onChangeText={setInterest} />
      <Input label="ارزش احتمالی خرید" value={value} onChangeText={setValue} keyboardType="number-pad" />
      <Input label="شهر" value={city} onChangeText={setCity} />
      <Input label="یادداشت" value={notes} onChangeText={setNotes} multiline />
      <Button label="ثبت سرنخ" onPress={submit} loading={busy} />
      <View style={{ height: spacing.sm }} />
      <Button label="انصراف" variant="secondary" onPress={onDone} />
    </ScrollView>
  );
}
