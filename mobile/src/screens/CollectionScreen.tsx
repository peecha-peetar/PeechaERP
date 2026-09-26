import React, { useEffect, useState } from "react";
import { Text, TouchableOpacity, View } from "react-native";
import { ApiClient, ApiError } from "../api/client";
import { BankRow, CustomerRow, PaymentMethod, SettlementMethodRow } from "../api/types";
import { Button, Card, Input, useToast } from "../components";
import { parseJalaliDate } from "../jalali";
import { useTheme } from "../theme/ThemeProvider";
import { OfflineQueue } from "../sync/offlineQueue";

interface Props {
  apiClient: ApiClient;
  customer: CustomerRow;
  offlineQueue: OfflineQueue;
  onDone: () => void;
}

const FALLBACK_METHODS: SettlementMethodRow[] = [
  { method_code: "CASH", label: "نقد" },
  { method_code: "BANK", label: "کارت/انتقال" },
  { method_code: "CHECK", label: "چک" },
];

function Chip({ label, selected, onPress }: { label: string; selected: boolean; onPress: () => void }) {
  const { colors, spacing, radius, typography } = useTheme();
  return (
    <TouchableOpacity
      onPress={onPress}
      style={{
        paddingHorizontal: spacing.md,
        paddingVertical: spacing.xs,
        borderRadius: radius.md,
        borderWidth: 1.5,
        borderColor: selected ? colors.primary : colors.border,
        backgroundColor: selected ? colors.primary : "transparent",
        marginEnd: spacing.xs,
        marginBottom: spacing.xs,
      }}
    >
      <Text style={[typography.caption, { color: selected ? colors.textInverse : colors.textPrimary }]}>{label}</Text>
    </TouchableOpacity>
  );
}

/** طبقِ Phase 5 (Collection) + بازبینیِ صریحِ کاربر («فیلدهایِ چک دقیقاً
 * همون فیلدهایِ دسکتاپ»): برخلافِ نسخهٔ قبلی (فقط شماره+نامِ‌آزادِ بانک)،
 * حالا صندوق/حسابِ مقصد (هم‌الگو با GET /pricing/settlement-methods)،
 * بانکِ چک (از فهرستِ واقعیِ بانک‌ها)، سررسید و نامِ صاحبِ چک هم گرفته
 * می‌شود -- دقیقاً همان فیلدهایی که PaymentMethodLineRequestِ سرور از
 * قبل می‌پذیرفت ولی این فرم نمی‌فرستاد. ثبتِ وصول هم‌چنان همیشه به صفِ
 * آفلاین اضافه می‌شود (هیچ‌وقت منتظرِ پاسخِ شبکه نمی‌مانَد). */
export function CollectionScreen({ apiClient, customer, offlineQueue, onDone }: Props) {
  const { colors, spacing, typography } = useTheme();
  const toast = useToast();
  const [methods, setMethods] = useState<SettlementMethodRow[]>(FALLBACK_METHODS);
  const [banks, setBanks] = useState<BankRow[]>([]);
  const [method, setMethod] = useState<PaymentMethod>("CASH");
  const [detailAccountId, setDetailAccountId] = useState<number | null>(null);
  const [amount, setAmount] = useState("");
  const [checkNo, setCheckNo] = useState("");
  const [bankId, setBankId] = useState<number | null>(null);
  const [checkBankName, setCheckBankName] = useState("");
  const [checkDueDate, setCheckDueDate] = useState("");
  const [checkPartyName, setCheckPartyName] = useState(customer.name);
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiClient
      .listSettlementMethods()
      .then((rows) => {
        const allowed = rows.filter((r) => r.method_code === "CASH" || r.method_code === "BANK" || r.method_code === "CHECK");
        if (allowed.length > 0) setMethods(allowed);
      })
      .catch(() => {
        // آفلاین: فهرستِ پیش‌فرضِ سه‌روشیِ بدونِ فیلدِ تفصیلی هم‌چنان قابلِ‌ثبت است.
      });
    apiClient.listBanks().then(setBanks).catch(() => undefined);
  }, [apiClient]);

  useEffect(() => {
    const row = methods.find((m) => m.method_code === method);
    setDetailAccountId(row?.default_detail_account_id ?? null);
  }, [method, methods]);

  const currentMethodRow = methods.find((m) => m.method_code === method);
  const requiresDetail = currentMethodRow?.requires_detail ?? false;
  const detailOptions = currentMethodRow?.detail_options ?? [];

  const canSubmit =
    amount.trim().length > 0 &&
    Number(amount) > 0 &&
    (method !== "CHECK" || checkNo.trim().length > 0) &&
    (!requiresDetail || detailAccountId !== null);

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
              detail_account_id: detailAccountId,
              check_no: method === "CHECK" ? checkNo.trim() : undefined,
              check_bank_name: method === "CHECK" ? (bankId === null ? checkBankName.trim() || undefined : undefined) : undefined,
              check_due_date: method === "CHECK" ? parseJalaliDate(checkDueDate) ?? undefined : undefined,
              check_party_name: method === "CHECK" ? checkPartyName.trim() || undefined : undefined,
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
        {methods.map((m) => (
          <Button
            key={m.method_code}
            label={m.label}
            variant={method === m.method_code ? "primary" : "secondary"}
            fullWidth={false}
            onPress={() => setMethod(m.method_code as PaymentMethod)}
          />
        ))}
      </View>

      <Input label="مبلغ" value={amount} onChangeText={setAmount} keyboardType="numeric" placeholder="0" />

      {requiresDetail && detailOptions.length > 0 ? (
        <View>
          <Text style={[typography.captionBold, { color: colors.textSecondary, marginBottom: spacing.xs }]}>صندوق/حسابِ مقصد</Text>
          <View style={{ flexDirection: "row", flexWrap: "wrap" }}>
            {detailOptions.map((o) => (
              <Chip key={o.detail_account_id} label={o.name} selected={detailAccountId === o.detail_account_id} onPress={() => setDetailAccountId(o.detail_account_id)} />
            ))}
          </View>
        </View>
      ) : null}

      {method === "CHECK" ? (
        <>
          <Input label="شماره‌یِ چک *" value={checkNo} onChangeText={setCheckNo} />
          <View>
            <Text style={[typography.captionBold, { color: colors.textSecondary, marginBottom: spacing.xs }]}>بانک</Text>
            <View style={{ flexDirection: "row", flexWrap: "wrap" }}>
              {banks.map((b) => (
                <Chip key={b.bank_id} label={b.name} selected={bankId === b.bank_id} onPress={() => setBankId(bankId === b.bank_id ? null : b.bank_id)} />
              ))}
            </View>
            {bankId === null ? <Input label="نامِ بانک (اگر در فهرست نیست)" value={checkBankName} onChangeText={setCheckBankName} /> : null}
          </View>
          <Input label="سررسید (۱۴۰۵/۰۸/۱۵)" value={checkDueDate} onChangeText={setCheckDueDate} numeric />
          <Input label="نامِ صاحبِ چک" value={checkPartyName} onChangeText={setCheckPartyName} />
        </>
      ) : null}

      <Input label="توضیحات (اختیاری)" value={description} onChangeText={setDescription} />

      {error ? (
        <Card style={{ backgroundColor: colors.dangerSoft, borderColor: colors.dangerSoft }}>
          <Text style={[typography.caption, { color: colors.danger }]}>{error}</Text>
        </Card>
      ) : null}

      <Button label="ثبتِ وصول" onPress={submit} loading={busy} disabled={!canSubmit} />
    </View>
  );
}
