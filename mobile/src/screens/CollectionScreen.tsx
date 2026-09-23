import React, { useState } from "react";
import { Text, View } from "react-native";
import { ApiError } from "../api/client";
import { CustomerRow, PaymentMethod } from "../api/types";
import { Button, Card, Input, useToast } from "../components";
import { useTheme } from "../theme/ThemeProvider";
import { OfflineQueue } from "../sync/offlineQueue";

interface Props {
  customer: CustomerRow;
  offlineQueue: OfflineQueue;
  onDone: () => void;
}

const METHODS: { code: PaymentMethod; label: string }[] = [
  { code: "CASH", label: "💵 نقد" },
  { code: "BANK", label: "💳 کارت/انتقال" },
  { code: "CHECK", label: "📄 چک" },
];

/** طبقِ Phase 5 (Collection): ثبتِ وصول همیشه به صفِ آفلاین اضافه
 * می‌شود (هم‌الگو با سفارش/ویزیت) -- هیچ‌وقت منتظرِ پاسخِ شبکه
 * نمی‌مانَد. رویِ همان /payments (R134) که خودش رویِ
 * treasury.create_treasury_voucher موجود سوار است -- بدونِ منطقِ تازه‌یِ
 * حسابداری این‌جا. */
export function CollectionScreen({ customer, offlineQueue, onDone }: Props) {
  const { colors, spacing, typography } = useTheme();
  const toast = useToast();
  const [method, setMethod] = useState<PaymentMethod>("CASH");
  const [amount, setAmount] = useState("");
  const [checkNo, setCheckNo] = useState("");
  const [checkBankName, setCheckBankName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSubmit = amount.trim().length > 0 && Number(amount) > 0 && (method !== "CHECK" || checkNo.trim().length > 0);

  const submit = async () => {
    setError(null);
    setBusy(true);
    try {
      await offlineQueue.enqueue({
        type: "CREATE_PAYMENT",
        payload: {
          customer_detail_account_id: customer.detail_account_id,
          description: description.trim() || undefined,
          method_lines: [
            {
              method,
              amount: amount.trim(),
              check_no: method === "CHECK" ? checkNo.trim() : undefined,
              check_bank_name: method === "CHECK" ? checkBankName.trim() || undefined : undefined,
            },
          ],
        },
      });
      toast.show("وصول ثبت شد و در صفِ همگام‌سازی قرار گرفت.", "success");
      onDone();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "ثبتِ وصول ناموفق بود.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={{ flex: 1, backgroundColor: colors.background, padding: spacing.lg, gap: spacing.lg }}>
      <Text style={[typography.h2, { color: colors.textPrimary }]}>ثبتِ وصول</Text>
      <Text style={[typography.body, { color: colors.textSecondary }]}>{customer.name}</Text>

      <View style={{ flexDirection: "row", gap: spacing.sm }}>
        {METHODS.map((m) => (
          <Button
            key={m.code}
            label={m.label}
            variant={method === m.code ? "primary" : "secondary"}
            fullWidth={false}
            onPress={() => setMethod(m.code)}
          />
        ))}
      </View>

      <Input label="مبلغ" value={amount} onChangeText={setAmount} keyboardType="numeric" placeholder="0" />

      {method === "CHECK" ? (
        <>
          <Input label="شماره‌یِ چک" value={checkNo} onChangeText={setCheckNo} />
          <Input label="نامِ بانک (اختیاری)" value={checkBankName} onChangeText={setCheckBankName} />
        </>
      ) : null}

      <Input label="توضیحات (اختیاری)" value={description} onChangeText={setDescription} />

      {error ? (
        <Card style={{ backgroundColor: colors.dangerSoft, borderColor: colors.dangerSoft }}>
          <Text style={{ color: colors.danger }}>{error}</Text>
        </Card>
      ) : null}

      <Button label="ثبتِ وصول" onPress={submit} loading={busy} disabled={!canSubmit} />
    </View>
  );
}
