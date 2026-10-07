import React, { useState } from "react";
import { ScrollView, Text, View } from "react-native";
import { CRM_PRIORITIES, CRM_TICKET_TYPES } from "../api/crmTypes";
import { Button, Input, useToast } from "../components";
import { OfflineQueue } from "../sync/offlineQueue";
import { useTheme } from "../theme/ThemeProvider";

interface Props {
  offlineQueue: OfflineQueue;
  customerDetailAccountId: number;
  customerName?: string;
  onDone: () => void;
}

function Chips({ options, value, onChange }: { options: { code: string; label: string }[]; value: string; onChange: (v: string) => void }) {
  const { spacing } = useTheme();
  return (
    <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.xs, marginBottom: spacing.md }}>
      {options.map((o) => (
        <Button key={o.code} label={o.label} size="md" fullWidth={false} variant={value === o.code ? "primary" : "secondary"}
          onPress={() => onChange(o.code)} />
      ))}
    </View>
  );
}

/** ثبتِ شکایت/درخواستِ مشتری از میدان (R286) -- در صفِ آفلاین؛ SLA و ارجاع در سرور اعمال می‌شود. */
export function CrmTicketScreen({ offlineQueue, customerDetailAccountId, customerName, onDone }: Props) {
  const { colors, spacing, typography } = useTheme();
  const toast = useToast();
  const [ticketType, setTicketType] = useState("COMPLAINT");
  const [priority, setPriority] = useState("NORMAL");
  const [subject, setSubject] = useState("");
  const [description, setDescription] = useState("");

  const submit = async () => {
    if (!subject.trim()) {
      toast.show("موضوع را وارد کنید.", "danger");
      return;
    }
    await offlineQueue.enqueue({
      type: "CRM_CREATE_TICKET",
      payload: {
        customer_detail_account_id: customerDetailAccountId, subject: subject.trim(), ticket_type: ticketType,
        priority_code: priority, channel_code: "MOBILE_APP", description: description.trim() || null,
      },
    });
    toast.show("ثبت شد؛ پس از اتصال همگام می‌شود.", "success");
    onDone();
  };

  return (
    <ScrollView style={{ flex: 1, backgroundColor: colors.background }} contentContainerStyle={{ padding: spacing.lg }}>
      <Text style={[typography.h2, { color: colors.textPrimary }]}>شکایت یا درخواست مشتری</Text>
      {customerName ? (
        <Text style={[typography.caption, { color: colors.textSecondary, marginBottom: spacing.md }]}>{customerName}</Text>
      ) : null}
      <Text style={[typography.captionBold, { color: colors.textSecondary, marginBottom: spacing.xs }]}>نوع</Text>
      <Chips options={CRM_TICKET_TYPES} value={ticketType} onChange={setTicketType} />
      <Text style={[typography.captionBold, { color: colors.textSecondary, marginBottom: spacing.xs }]}>اولویت</Text>
      <Chips options={CRM_PRIORITIES} value={priority} onChange={setPriority} />
      <Input label="موضوع *" value={subject} onChangeText={setSubject} />
      <Input label="شرح" value={description} onChangeText={setDescription} multiline />
      <Button label="ثبت" onPress={submit} />
      <View style={{ height: spacing.sm }} />
      <Button label="انصراف" variant="secondary" onPress={onDone} />
    </ScrollView>
  );
}
