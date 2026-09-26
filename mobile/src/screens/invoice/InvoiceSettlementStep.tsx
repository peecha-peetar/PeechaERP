import React, { useMemo, useState } from "react";
import { ScrollView, Text, TouchableOpacity, View } from "react-native";
import { BankRow, CustomerRow, OrderSettlementLineInput, SettlementMethodRow } from "../../api/types";
import { Button, Card, Input } from "../../components";
import { formatAmount, parseAmount, toAsciiDigits } from "../../format";
import { parseJalaliDate } from "../../jalali";
import { useTheme } from "../../theme/ThemeProvider";
import { Cart, cartDiscountTotal, cartGrossTotal, cartLines, cartTaxTotal, cartTotal, lineTotalAmount } from "./cart";

interface CheckDraft {
  key: number;
  check_no: string;
  check_serial: string;
  bank_id: number | null;
  bank_name: string;
  iban: string;
  bank_account_no: string;
  due_date: string;
  amount: string;
  party_name: string;
  national_id: string;
  phone: string;
}

interface MethodDraft {
  amount: string;
  detailAccountId: number | null;
  note: string;
  checks: CheckDraft[];
}

interface Props {
  customer: CustomerRow;
  cart: Cart;
  methods: SettlementMethodRow[];
  banks: BankRow[];
  submitting: boolean;
  onChangePrice: (itemId: number, price: number | null) => void;
  onBack: () => void;
  onSubmit: (settlementLines: OrderSettlementLineInput[], receivedByName: string) => void;
}

let nextCheckKey = 1;

function emptyCheck(partyName: string): CheckDraft {
  return {
    key: nextCheckKey++, check_no: "", check_serial: "", bank_id: null, bank_name: "", iban: "",
    bank_account_no: "", due_date: "", amount: "", party_name: partyName, national_id: "", phone: "",
  };
}

function Chip({ label, selected, onPress }: { label: string; selected: boolean; onPress: () => void }) {
  const { colors, spacing, radius, typography } = useTheme();
  return (
    <TouchableOpacity
      onPress={onPress}
      accessibilityRole="button"
      accessibilityState={{ selected }}
      style={{ paddingHorizontal: spacing.md, paddingVertical: spacing.xs, borderRadius: radius.pill, backgroundColor: selected ? colors.primary : colors.surfaceAlt }}
    >
      <Text style={[typography.captionBold, { color: selected ? colors.textInverse : colors.textPrimary }]}>{label}</Text>
    </TouchableOpacity>
  );
}

/** طبقِ درخواستِ صریحِ کاربر («با انتخاب کردنِ کالاها و تایید، قسمتِ
 * تسویه بیاد و انتخاب کنیم نوعِ تسویه و ثبتِ تسویه -- دقیقاً همون
 * فیلدهایی که دسکتاپ داره، مثلاً فیلدهایِ چک»): هر روش همان ستون‌هایِ
 * دیالوگِ نحوه‌یِ تسویهٔ دسکتاپ را دارد (مبلغ، تفصیلی، یادداشت)؛ چک همان
 * فیلدهایِ چکِ دریافتیِ فرمِ دریافتِ خزانه‌داری را (چند چک در یک ردیف).
 * هرچه پوشش داده نشود، خودکار نسیه می‌ماند -- دقیقاً مثلِ دسکتاپ. */
export function InvoiceSettlementStep({ customer, cart, methods, banks, submitting, onChangePrice, onBack, onSubmit }: Props) {
  const { colors, spacing, typography } = useTheme();
  const [drafts, setDrafts] = useState<Record<string, MethodDraft>>(() =>
    Object.fromEntries(
      methods.map((m) => [
        m.method_code,
        {
          amount: "",
          detailAccountId:
            m.default_detail_account_id ?? (m.detail_options && m.detail_options.length === 1 ? m.detail_options[0].detail_account_id : null),
          note: "",
          checks: [],
        },
      ]),
    ),
  );
  const [receivedByName, setReceivedByName] = useState("");
  const [errors, setErrors] = useState<string[]>([]);

  const lines = cartLines(cart);
  const total = cartTotal(cart);

  const methodAmount = (code: string): number => {
    const draft = drafts[code];
    if (!draft) return 0;
    if (code === "CHECK") return draft.checks.reduce((sum, c) => sum + parseAmount(c.amount), 0);
    return parseAmount(draft.amount);
  };
  const paid = useMemo(() => methods.reduce((sum, m) => sum + methodAmount(m.method_code), 0), [drafts, methods]);
  const remaining = total - paid;

  const update = (code: string, patch: Partial<MethodDraft>) =>
    setDrafts((prev) => ({ ...prev, [code]: { ...prev[code], ...patch } }));
  const updateCheck = (key: number, patch: Partial<CheckDraft>) =>
    setDrafts((prev) => ({
      ...prev,
      CHECK: { ...prev.CHECK, checks: prev.CHECK.checks.map((c) => (c.key === key ? { ...c, ...patch } : c)) },
    }));

  const submit = () => {
    const found: string[] = [];
    if (lines.some((l) => l.unitPrice === null || l.unitPrice <= 0)) found.push("قیمتِ همهٔ کالاهایِ سبد باید وارد شود.");
    const result: OrderSettlementLineInput[] = [];
    for (const method of methods) {
      const draft = drafts[method.method_code];
      const amount = methodAmount(method.method_code);
      if (amount <= 0) continue;
      if (method.requires_detail && (method.detail_options?.length ?? 0) > 0 && draft.detailAccountId === null) {
        found.push(`برایِ «${method.label}» صندوق/حساب را انتخاب کنید.`);
      }
      const line: OrderSettlementLineInput = {
        method_code: method.method_code,
        amount: String(amount),
        detail_account_id: draft.detailAccountId,
        note: draft.note.trim() || null,
      };
      if (method.method_code === "CHECK") {
        line.checks = [];
        draft.checks.forEach((c, index) => {
          const label = `چکِ ${index + 1}`;
          const dueIso = parseJalaliDate(c.due_date);
          if (!toAsciiDigits(c.check_no)) found.push(`${label}: شمارهٔ چک الزامی است.`);
          if (!dueIso) found.push(`${label}: تاریخِ سررسید را به‌صورتِ ۱۴۰۵/۰۸/۱۵ وارد کنید.`);
          if (parseAmount(c.amount) <= 0) found.push(`${label}: مبلغ الزامی است.`);
          line.checks!.push({
            check_no: toAsciiDigits(c.check_no),
            due_date: dueIso ?? "",
            amount: String(parseAmount(c.amount)),
            check_serial: c.check_serial.trim() || null,
            bank_id: c.bank_id,
            check_bank_name: c.bank_id === null ? c.bank_name.trim() || null : null,
            iban: toAsciiDigits(c.iban) || null,
            bank_account_no: toAsciiDigits(c.bank_account_no) || null,
            party_name: c.party_name.trim() || null,
            national_id: toAsciiDigits(c.national_id) || null,
            phone: toAsciiDigits(c.phone) || null,
          });
        });
      }
      result.push(line);
    }
    if (paid > total) found.push("جمعِ تسویه از مبلغِ فاکتور بیشتر است.");
    setErrors(found);
    if (found.length === 0) onSubmit(result, receivedByName.trim());
  };

  return (
    <ScrollView contentContainerStyle={{ padding: spacing.lg, gap: spacing.md, backgroundColor: colors.background }} keyboardShouldPersistTaps="handled">
      <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
        <Text style={[typography.h3, { color: colors.textPrimary, flex: 1 }]} numberOfLines={1}>
          تسویه -- {customer.name}
        </Text>
        <Button label="بازگشت به کالاها" variant="ghost" fullWidth={false} onPress={onBack} />
      </View>

      <Card>
        <Text style={[typography.captionBold, { color: colors.textSecondary, marginBottom: spacing.sm }]}>اقلامِ فاکتور</Text>
        {lines.map((l) => (
          <View key={l.item.item_id} style={{ paddingVertical: spacing.xs, gap: spacing.xxs }}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}>
              <Text style={[typography.body, { color: colors.textPrimary, flex: 1 }]} numberOfLines={1}>
                {l.item.name} × {formatAmount(String(l.quantity))}
              </Text>
              <Input
                value={l.unitPrice !== null ? String(l.unitPrice) : ""}
                onChangeText={(v) => onChangePrice(l.item.item_id, v.trim() ? parseAmount(v) : null)}
                keyboardType="numeric"
                numeric
                placeholder="قیمت"
                error={l.unitPrice === null ? "بدونِ قیمت" : undefined}
                style={{ width: 120, marginBottom: 0 }}
              />
            </View>
            {l.discountAmount > 0 || l.taxPercent > 0 ? (
              <Text style={[typography.caption, { color: colors.textSecondary }]}>
                {l.discountAmount > 0 ? `تخفیف: ${formatAmount(String(l.discountAmount))}` : ""}
                {l.discountAmount > 0 && l.taxPercent > 0 ? " -- " : ""}
                {l.taxPercent > 0 ? `مالیات ${formatAmount(String(l.taxPercent))}٪` : ""}
                {" -- "}جمعِ این ردیف: {formatAmount(String(lineTotalAmount(l)))}
              </Text>
            ) : null}
          </View>
        ))}
        <Text style={[typography.body, { color: colors.textSecondary, marginTop: spacing.sm }]}>جمعِ کالاها: {formatAmount(String(cartGrossTotal(cart)))}</Text>
        {cartDiscountTotal(cart) > 0 ? (
          <Text style={[typography.body, { color: colors.textSecondary }]}>تخفیف: {formatAmount(String(cartDiscountTotal(cart)))}</Text>
        ) : null}
        {cartTaxTotal(cart) > 0 ? (
          <Text style={[typography.body, { color: colors.textSecondary }]}>مالياتِ ارزش‌افزوده: {formatAmount(String(cartTaxTotal(cart)))}</Text>
        ) : null}
        <Text style={[typography.bodyBold, { color: colors.textPrimary, marginTop: spacing.xs }]}>مبلغِ فاکتور: {formatAmount(String(total))}</Text>
        <Text style={[typography.caption, { color: colors.textSecondary }]}>
          تخفیف از فهرست/قانونِ قیمتِ همین مشتری و مالیات از درصدِ تعریف‌شده برایِ کالا/انبار/شرکت -- خودکار محاسبه و در مبلغِ بالا لحاظ شده است.
        </Text>
      </Card>

      {methods.map((method) => {
        const draft = drafts[method.method_code];
        const options = method.detail_options ?? [];
        return (
          <Card key={method.method_code}>
            <Text style={[typography.bodyBold, { color: colors.textPrimary, marginBottom: spacing.sm }]}>{method.label}</Text>
            {method.method_code === "CHECK" ? (
              <>
                {draft.checks.map((c, index) => (
                  <View key={c.key} style={{ borderTopWidth: index === 0 ? 0 : 1, borderTopColor: colors.border, paddingTop: index === 0 ? 0 : spacing.sm }}>
                    <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
                      <Text style={[typography.captionBold, { color: colors.textSecondary }]}>چکِ {index + 1}</Text>
                      <Button
                        label="حذف"
                        variant="ghost"
                        fullWidth={false}
                        onPress={() => update("CHECK", { checks: draft.checks.filter((x) => x.key !== c.key) })}
                      />
                    </View>
                    <View style={{ flexDirection: "row", gap: spacing.sm }}>
                      <Input label="شمارهٔ چک *" value={c.check_no} onChangeText={(v) => updateCheck(c.key, { check_no: v })} keyboardType="numeric" numeric style={{ flex: 1 }} />
                      <Input label="سریالِ چک" value={c.check_serial} onChangeText={(v) => updateCheck(c.key, { check_serial: v })} style={{ flex: 1 }} />
                    </View>
                    <View style={{ flexDirection: "row", gap: spacing.sm }}>
                      <Input label="مبلغ *" value={c.amount} onChangeText={(v) => updateCheck(c.key, { amount: v })} keyboardType="numeric" numeric style={{ flex: 1 }} />
                      <Input label="سررسید * (۱۴۰۵/۰۸/۱۵)" value={c.due_date} onChangeText={(v) => updateCheck(c.key, { due_date: v })} numeric style={{ flex: 1 }} />
                    </View>
                    <Text style={[typography.captionBold, { color: colors.textSecondary, marginBottom: spacing.xs }]}>بانک</Text>
                    <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.xs, marginBottom: spacing.sm }}>
                      {banks.map((b) => (
                        <Chip key={b.bank_id} label={b.name} selected={c.bank_id === b.bank_id} onPress={() => updateCheck(c.key, { bank_id: c.bank_id === b.bank_id ? null : b.bank_id })} />
                      ))}
                    </View>
                    {c.bank_id === null ? (
                      <Input label="نامِ بانک (اگر در فهرست نیست)" value={c.bank_name} onChangeText={(v) => updateCheck(c.key, { bank_name: v })} />
                    ) : null}
                    <Input label="شمارهٔ شبا" value={c.iban} onChangeText={(v) => updateCheck(c.key, { iban: v })} numeric autoCapitalize="characters" />
                    <Input label="شمارهٔ حساب" value={c.bank_account_no} onChangeText={(v) => updateCheck(c.key, { bank_account_no: v })} keyboardType="numeric" numeric />
                    <Input label="نامِ صادرکننده" value={c.party_name} onChangeText={(v) => updateCheck(c.key, { party_name: v })} />
                    <View style={{ flexDirection: "row", gap: spacing.sm }}>
                      <Input label="کدِ ملی" value={c.national_id} onChangeText={(v) => updateCheck(c.key, { national_id: v })} keyboardType="numeric" numeric style={{ flex: 1 }} />
                      <Input label="تلفن" value={c.phone} onChangeText={(v) => updateCheck(c.key, { phone: v })} keyboardType="phone-pad" numeric style={{ flex: 1 }} />
                    </View>
                  </View>
                ))}
                <Button label="افزودنِ چک" variant="secondary" onPress={() => update("CHECK", { checks: [...draft.checks, emptyCheck(customer.name)] })} />
                {draft.checks.length > 0 ? (
                  <Text style={[typography.bodyBold, { color: colors.textPrimary, marginTop: spacing.sm }]}>
                    جمعِ چک‌ها: {formatAmount(String(methodAmount("CHECK")))}
                  </Text>
                ) : null}
              </>
            ) : (
              <View style={{ flexDirection: "row", gap: spacing.sm, alignItems: "flex-end" }}>
                <Input
                  label="مبلغ"
                  value={draft.amount}
                  onChangeText={(v) => update(method.method_code, { amount: v })}
                  keyboardType="numeric"
                  numeric
                  style={{ flex: 1 }}
                />
                <Button
                  label="کلِ مانده"
                  variant="ghost"
                  fullWidth={false}
                  onPress={() => update(method.method_code, { amount: String(Math.max(0, remaining + methodAmount(method.method_code))) })}
                  style={{ marginBottom: spacing.md }}
                />
              </View>
            )}
            {method.requires_detail && options.length > 0 && (method.method_code !== "CHECK" || draft.checks.length > 0) ? (
              <>
                <Text style={[typography.captionBold, { color: colors.textSecondary, marginBottom: spacing.xs }]}>
                  {method.method_code === "CHECK" ? "نگه‌داری نزدِ" : "صندوق/حساب"}
                </Text>
                <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.xs, marginBottom: spacing.sm }}>
                  {options.map((o) => (
                    <Chip key={o.detail_account_id} label={o.name} selected={draft.detailAccountId === o.detail_account_id} onPress={() => update(method.method_code, { detailAccountId: o.detail_account_id })} />
                  ))}
                </View>
              </>
            ) : null}
            {methodAmount(method.method_code) > 0 ? (
              <Input label="یادداشت" value={draft.note} onChangeText={(v) => update(method.method_code, { note: v })} />
            ) : null}
          </Card>
        );
      })}

      <Card>
        <Text style={[typography.body, { color: colors.textPrimary }]}>مبلغِ فاکتور: {formatAmount(String(total))}</Text>
        <Text style={[typography.body, { color: colors.success }]}>تسویه‌شده: {formatAmount(String(paid))}</Text>
        <Text style={[typography.bodyBold, { color: remaining < 0 ? colors.danger : colors.textPrimary }]}>
          {remaining < 0 ? `بیش از مبلغِ فاکتور: ${formatAmount(String(-remaining))}` : `مانده (نسیه): ${formatAmount(String(remaining))}`}
        </Text>
      </Card>

      <Input label="نامِ تحویل‌گیرنده" value={receivedByName} onChangeText={setReceivedByName} />

      {errors.length > 0 ? (
        <Card style={{ borderColor: colors.danger }}>
          {errors.map((e) => (
            <Text key={e} style={[typography.caption, { color: colors.danger }]}>{e}</Text>
          ))}
        </Card>
      ) : null}

      <Button label="ثبتِ فاکتور و رسیدِ تحویل" onPress={submit} loading={submitting} disabled={submitting || lines.length === 0} />
    </ScrollView>
  );
}
