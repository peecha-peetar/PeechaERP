import React, { useCallback, useEffect, useState } from "react";
import { ScrollView, Text, View } from "react-native";
import { ApiClient, ApiError } from "../api/client";
import { Customer360Response } from "../api/types";
import { Button, Card, ErrorState, Input, SkeletonList, StatusBadge, useToast } from "../components";
import { formatAmount } from "../format";
import { formatJalaliDate, formatJalaliDateTime } from "../jalali";
import { useTheme } from "../theme/ThemeProvider";

interface Props {
  apiClient: ApiClient;
  detailAccountId: number;
  onBack: () => void;
}

const GUARANTEE_TYPE_LABELS: Record<string, string> = {
  CHECK: "چکِ تضمینی", PROMISSORY_NOTE: "سفته", BANK_GUARANTEE: "ضمانت‌نامه", GUARANTOR: "ضامن", COLLATERAL: "وثیقه",
};
const GUARANTEE_STATUS_LABELS: Record<string, string> = {
  ACTIVE: "فعال", RELEASED: "آزادشده", CALLED: "ضبط‌شده", EXPIRED: "منقضی",
};
const ACTIVITY_TYPE_OPTIONS: { code: "COMPLAINT" | "MEETING" | "OPPORTUNITY" | "TASK"; label: string }[] = [
  { code: "COMPLAINT", label: "شکایت" }, { code: "MEETING", label: "جلسه" },
  { code: "OPPORTUNITY", label: "فرصتِ فروش" }, { code: "TASK", label: "وظیفه" },
];
const ACTIVITY_TYPE_LABELS: Record<string, string> = Object.fromEntries(ACTIVITY_TYPE_OPTIONS.map((o) => [o.code, o.label]));
const ACTIVITY_STATUS_LABELS: Record<string, string> = {
  OPEN: "باز", IN_PROGRESS: "درحالِ انجام", RESOLVED: "حل‌شده", DONE: "انجام‌شده",
  WON: "موفق", LOST: "ناموفق", CANCELLED: "لغوشده",
};
/** طبقِ گردشِ کارِ سرور (partners_service._ACTIVITY_CLOSE_STATUSES): هر
 * نوعِ فعالیت فقط با یکی از همین وضعیت‌ها قابلِ‌بستن است. */
const ACTIVITY_CLOSE_OPTIONS: Record<string, { code: string; label: string }[]> = {
  COMPLAINT: [{ code: "RESOLVED", label: "حل شد" }, { code: "CANCELLED", label: "لغو شد" }],
  MEETING: [{ code: "DONE", label: "انجام شد" }, { code: "CANCELLED", label: "لغو شد" }],
  OPPORTUNITY: [{ code: "WON", label: "موفق" }, { code: "LOST", label: "ناموفق" }, { code: "CANCELLED", label: "لغو شد" }],
  TASK: [{ code: "DONE", label: "انجام شد" }, { code: "CANCELLED", label: "لغو شد" }],
};
const CONTRACT_CATEGORY_LABELS: Record<string, string> = {
  STANDARD: "استاندارد", AGENCY: "نمایندگی", ORGANIZATIONAL: "سازمانی",
};
const CONTRACT_STATUS_LABELS: Record<string, string> = { ACTIVE: "فعال", CANCELLED: "لغوشده", EXPIRED: "منقضی" };
const ADDRESS_TYPE_LABELS: Record<string, string> = {
  OFFICE: "دفتر", STORE: "فروشگاه", WAREHOUSE: "انبار", DELIVERY: "تحویل", BILLING: "صورتحساب", RETURN: "مرجوعی",
};
const SEGMENT_LABELS: Record<string, string> = {
  NEW: "مشتریِ جدید", ACTIVE: "فعال", LOYAL: "وفادار", LOW_PURCHASE: "کم‌خرید",
  AT_RISK: "در معرضِ ریزش", INACTIVE: "غیرفعال", DEBTOR: "بدهکار", VIP: "VIP",
};

function SectionHeader({ label, count }: { label: string; count: number }) {
  const { colors, spacing, radius, typography } = useTheme();
  return (
    <View style={{ flexDirection: "row", alignItems: "center", marginTop: spacing.lg, marginBottom: spacing.sm }}>
      <View style={{ width: 4, height: 16, borderRadius: radius.pill, backgroundColor: colors.primary, marginEnd: spacing.sm }} />
      <Text style={[typography.h3, { color: colors.textPrimary }]}>{label}</Text>
      <Text style={[typography.caption, { color: colors.textSecondary, marginStart: spacing.xs }]}>({count})</Text>
    </View>
  );
}

function StatTile({ label, value, tone }: { label: string; value: string; tone?: "success" | "danger" }) {
  const { colors, spacing, radius, typography } = useTheme();
  return (
    <View
      style={{
        flexBasis: "48%", backgroundColor: colors.surfaceAlt, borderRadius: radius.md,
        padding: spacing.md, marginBottom: spacing.sm,
      }}
    >
      <Text style={[typography.caption, { color: colors.textSecondary }]}>{label}</Text>
      <Text style={[typography.h3, { color: tone === "danger" ? colors.danger : tone === "success" ? colors.success : colors.textPrimary, marginTop: spacing.xxs }]}>
        {value}
      </Text>
    </View>
  );
}

/** طبقِ بازبینیِ ساختارِ «تعریفِ مشتری» (R219، بخشِ ۱۲ -- Customer 360)
 * و بازخوردِ کاربر رویِ R220 («بسیار ساده، بدونِ جذابیتِ گرافیکی» +
 * «CRM کجاست؟»): یک صفحه‌یِ واحد -- مالی/اعتبار، ضمانت‌ها، قراردادها،
 * CRM (فعالیت/تماس/یادداشت -- حالا با فرمِ ثبت/بستن، نه فقط نمایش)،
 * آدرس‌ها، Merchandising، ویزیت‌هایِ اخیر -- با ساختاربندیِ بصریِ
 * روشن‌تر (StatusBadge/کارت‌هایِ آماری) به‌جایِ فهرستِ متنیِ ساده. */
export function Customer360Screen({ apiClient, detailAccountId, onBack }: Props) {
  const { colors, spacing, typography } = useTheme();
  const toast = useToast();
  const [data, setData] = useState<Customer360Response | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [showActivityForm, setShowActivityForm] = useState(false);
  const [activityType, setActivityType] = useState<"COMPLAINT" | "MEETING" | "OPPORTUNITY" | "TASK">("COMPLAINT");
  const [activitySubject, setActivitySubject] = useState("");
  const [activityDescription, setActivityDescription] = useState("");
  const [activityEstimatedValue, setActivityEstimatedValue] = useState("");
  const [savingActivity, setSavingActivity] = useState(false);
  const [closingActivityId, setClosingActivityId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setData(await apiClient.getCustomer360(detailAccountId));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "دریافتِ اطلاعاتِ کاملِ مشتری ناموفق بود.");
    } finally {
      setLoading(false);
    }
  }, [apiClient, detailAccountId]);

  useEffect(() => {
    load();
  }, [load]);

  const resetActivityForm = () => {
    setShowActivityForm(false);
    setActivityType("COMPLAINT");
    setActivitySubject("");
    setActivityDescription("");
    setActivityEstimatedValue("");
  };

  const saveActivity = async () => {
    if (!activitySubject.trim()) {
      toast.show("موضوعِ فعالیت الزامی است.", "danger");
      return;
    }
    setSavingActivity(true);
    try {
      await apiClient.createCustomerActivity(detailAccountId, {
        activity_type_code: activityType,
        subject: activitySubject.trim(),
        description: activityDescription.trim() || null,
        estimated_value: activityType === "OPPORTUNITY" && activityEstimatedValue.trim() ? activityEstimatedValue.trim() : null,
      });
      toast.show("فعالیت ثبت شد.", "success");
      resetActivityForm();
      await load();
    } catch (e) {
      toast.show(e instanceof ApiError ? e.message : "ثبتِ فعالیت ناموفق بود.", "danger");
    } finally {
      setSavingActivity(false);
    }
  };

  const closeActivity = async (activityId: number, statusCode: string) => {
    setClosingActivityId(activityId);
    try {
      await apiClient.closeCustomerActivity(detailAccountId, activityId, statusCode);
      toast.show("فعالیت بسته شد.", "success");
      await load();
    } catch (e) {
      toast.show(e instanceof ApiError ? e.message : "بستنِ فعالیت ناموفق بود.", "danger");
    } finally {
      setClosingActivityId(null);
    }
  };

  if (loading) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.background, padding: spacing.lg }}>
        <SkeletonList count={5} />
      </View>
    );
  }

  if (error || data === null) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.background }}>
        <ErrorState description={error ?? "اطلاعات یافت نشد."} onRetry={load} />
      </View>
    );
  }

  const { detail, guarantees, contracts, activities, addresses, merchandising, calls, notes, recent_visits: recentVisits, segment } = data;
  const openActivities = activities.filter((a) => a.status_code === "OPEN" || a.status_code === "IN_PROGRESS");

  return (
    <ScrollView contentContainerStyle={{ padding: spacing.lg, backgroundColor: colors.background }}>
      <Button label="بازگشت" variant="ghost" fullWidth={false} onPress={onBack} />

      <View style={{ backgroundColor: colors.primarySoft, borderRadius: 16, padding: spacing.lg, marginTop: spacing.sm }}>
        <Text style={[typography.h2, { color: colors.textPrimary }]}>{detail.name}</Text>
        <View style={{ flexDirection: "row", alignItems: "center", marginTop: spacing.xs }}>
          <Text style={[typography.caption, { color: colors.textSecondary, marginEnd: spacing.sm }]}>{detail.code}</Text>
          <StatusBadge statusCode={segment.segment_code} label={SEGMENT_LABELS[segment.segment_code] ?? segment.segment_code} />
        </View>

        <View style={{ flexDirection: "row", flexWrap: "wrap", justifyContent: "space-between", marginTop: spacing.md }}>
          <StatTile label="فروشِ ماهِ جاری" value={formatAmount(segment.sales_this_month)} />
          <StatTile label="فروشِ ۳ماهِ اخیر" value={formatAmount(segment.sales_last_3_months)} />
          <StatTile label="تعدادِ سفارش (۱۲ماهِ اخیر)" value={String(segment.order_count_last_12_months)} />
          <StatTile
            label="سودِ برآوردیِ ۳ماهِ اخیر"
            value={formatAmount(segment.estimated_profit_last_3_months)}
            tone={Number(segment.estimated_profit_last_3_months) >= 0 ? "success" : "danger"}
          />
        </View>
        <Text style={[typography.caption, { color: colors.textSecondary, marginTop: spacing.xs }]}>
          سودِ برآوردی بر مبنایِ آخرین بهایِ شناخته‌شده است، نه حسابداریِ دقیق.
        </Text>

        <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginTop: spacing.md }}>
          <Text style={[typography.caption, { color: colors.textSecondary }]}>مانده‌یِ حساب</Text>
          <Text style={[typography.caption, { color: colors.textSecondary }]}>{detail.balance_nature}</Text>
        </View>
        <Text style={[typography.numeric, { fontSize: 22, color: detail.balance_nature === "بدهکار" ? colors.danger : colors.success }]}>
          {formatAmount(detail.balance_amount)}
        </Text>
        {detail.credit_limit_amount ? (
          <Text style={[typography.caption, { color: colors.textSecondary, marginTop: spacing.xs }]}>
            سقفِ اعتبار: {formatAmount(detail.credit_limit_amount)}
          </Text>
        ) : null}
      </View>

      <SectionHeader label="ضمانت‌ها" count={guarantees.length} />
      {guarantees.length === 0 ? (
        <Text style={[typography.caption, { color: colors.textSecondary }]}>ضمانتی ثبت نشده.</Text>
      ) : (
        guarantees.map((g) => (
          <Card key={g.guarantee_id}>
            <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" }}>
              <Text style={[typography.body, { color: colors.textPrimary }]}>
                {GUARANTEE_TYPE_LABELS[g.guarantee_type_code] ?? g.guarantee_type_code} · {formatAmount(g.amount)}
              </Text>
              <StatusBadge statusCode={g.status_code} label={GUARANTEE_STATUS_LABELS[g.status_code] ?? g.status_code} />
            </View>
            {g.description ? <Text style={[typography.caption, { color: colors.textSecondary, marginTop: spacing.xs }]}>{g.description}</Text> : null}
          </Card>
        ))
      )}

      <SectionHeader label="قراردادها" count={contracts.length} />
      {contracts.length === 0 ? (
        <Text style={[typography.caption, { color: colors.textSecondary }]}>قراردادی ثبت نشده.</Text>
      ) : (
        contracts.map((c) => (
          <Card key={c.contract_id}>
            <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" }}>
              <Text style={[typography.body, { color: colors.textPrimary }]}>
                {CONTRACT_CATEGORY_LABELS[c.contract_category_code] ?? c.contract_category_code}
              </Text>
              <StatusBadge statusCode={c.status_code} label={CONTRACT_STATUS_LABELS[c.status_code] ?? c.status_code} />
            </View>
            {c.committed_amount ? (
              <Text style={[typography.caption, { color: colors.textSecondary, marginTop: spacing.xs }]}>
                سهمیه: {formatAmount(c.committed_amount)} · مصرف‌شده: {formatAmount(c.consumed_amount)}
              </Text>
            ) : null}
            {c.commitments_text ? <Text style={[typography.caption, { color: colors.textSecondary }]}>{c.commitments_text}</Text> : null}
          </Card>
        ))
      )}

      <SectionHeader label="فعالیت‌هایِ CRM" count={activities.length} />
      {openActivities.length > 0 ? (
        <Text style={[typography.caption, { color: colors.warning, marginBottom: spacing.sm }]}>
          {openActivities.length} فعالیتِ باز نیاز به پیگیری دارد.
        </Text>
      ) : null}
      {activities.length === 0 ? (
        <Text style={[typography.caption, { color: colors.textSecondary }]}>فعالیتی ثبت نشده.</Text>
      ) : (
        activities.map((a) => (
          <Card key={a.activity_id}>
            <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" }}>
              <Text style={[typography.body, { color: colors.textPrimary, flex: 1 }]}>
                {ACTIVITY_TYPE_LABELS[a.activity_type_code] ?? a.activity_type_code}: {a.subject}
              </Text>
              <StatusBadge statusCode={a.status_code} label={ACTIVITY_STATUS_LABELS[a.status_code] ?? a.status_code} />
            </View>
            {a.description ? <Text style={[typography.caption, { color: colors.textSecondary, marginTop: spacing.xs }]}>{a.description}</Text> : null}
            <Text style={[typography.caption, { color: colors.textSecondary, marginTop: spacing.xs }]}>{formatJalaliDate(a.created_at)}</Text>
            {(a.status_code === "OPEN" || a.status_code === "IN_PROGRESS") ? (
              <View style={{ flexDirection: "row", flexWrap: "wrap", marginTop: spacing.sm }}>
                {(ACTIVITY_CLOSE_OPTIONS[a.activity_type_code] ?? []).map((opt) => (
                  <Button
                    key={opt.code}
                    label={opt.label}
                    size="md"
                    fullWidth={false}
                    variant="secondary"
                    loading={closingActivityId === a.activity_id}
                    onPress={() => closeActivity(a.activity_id, opt.code)}
                    style={{ marginEnd: spacing.xs, marginTop: spacing.xs }}
                  />
                ))}
              </View>
            ) : null}
          </Card>
        ))
      )}

      {showActivityForm ? (
        <Card>
          <Text style={[typography.captionBold, { color: colors.textSecondary, marginBottom: spacing.xs }]}>نوعِ فعالیت</Text>
          <View style={{ flexDirection: "row", flexWrap: "wrap", marginBottom: spacing.sm }}>
            {ACTIVITY_TYPE_OPTIONS.map((o) => (
              <Button
                key={o.code}
                label={o.label}
                size="md"
                fullWidth={false}
                variant={activityType === o.code ? "primary" : "secondary"}
                onPress={() => setActivityType(o.code)}
                style={{ marginEnd: spacing.xs, marginBottom: spacing.xs }}
              />
            ))}
          </View>
          <Input label="موضوع *" value={activitySubject} onChangeText={setActivitySubject} />
          <Input label="توضیح" value={activityDescription} onChangeText={setActivityDescription} multiline />
          {activityType === "OPPORTUNITY" ? (
            <Input label="ارزشِ برآوردی" value={activityEstimatedValue} onChangeText={setActivityEstimatedValue} keyboardType="number-pad" />
          ) : null}
          <Button label="ثبتِ فعالیت" onPress={saveActivity} loading={savingActivity} disabled={!activitySubject.trim()} />
          <Button label="انصراف" variant="ghost" onPress={resetActivityForm} style={{ marginTop: spacing.sm }} />
        </Card>
      ) : (
        <Button label="افزودنِ فعالیتِ CRM" variant="secondary" onPress={() => setShowActivityForm(true)} />
      )}

      <SectionHeader label="آدرس‌ها" count={addresses.length} />
      {addresses.length === 0 ? (
        <Text style={[typography.caption, { color: colors.textSecondary }]}>آدرسی ثبت نشده.</Text>
      ) : (
        addresses.map((ad) => (
          <Card key={ad.address_id}>
            <Text style={[typography.body, { color: colors.textPrimary }]}>
              {ADDRESS_TYPE_LABELS[ad.address_type_code] ?? ad.address_type_code}
            </Text>
            <Text style={[typography.caption, { color: colors.textSecondary }]}>{ad.line1}</Text>
          </Card>
        ))
      )}

      {merchandising ? (
        <>
          <SectionHeader label="اطلاعاتِ فروشگاهی" count={1} />
          <Card>
            {merchandising.store_area_sqm ? (
              <Text style={[typography.caption, { color: colors.textSecondary }]}>متراژ: {merchandising.store_area_sqm} مترمربع</Text>
            ) : null}
            <Text style={[typography.caption, { color: colors.textSecondary }]}>
              {[
                merchandising.checkout_count !== null ? `صندوق: ${merchandising.checkout_count}` : null,
                merchandising.fridge_count !== null ? `یخچال: ${merchandising.fridge_count}` : null,
                merchandising.shelf_count !== null ? `قفسه: ${merchandising.shelf_count}` : null,
              ]
                .filter(Boolean)
                .join(" · ")}
            </Text>
            {merchandising.available_brands ? (
              <Text style={[typography.caption, { color: colors.textSecondary }]}>برندهایِ موجود: {merchandising.available_brands}</Text>
            ) : null}
            {merchandising.competitor_brands ? (
              <Text style={[typography.caption, { color: colors.textSecondary }]}>رقبا: {merchandising.competitor_brands}</Text>
            ) : null}
          </Card>
        </>
      ) : null}

      <SectionHeader label="ویزیت‌هایِ اخیر" count={recentVisits.length} />
      {recentVisits.length === 0 ? (
        <Text style={[typography.caption, { color: colors.textSecondary }]}>ویزیتی ثبت نشده.</Text>
      ) : (
        recentVisits.map((v) => (
          <Card key={v.customer_visit_id}>
            <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
              <Text style={[typography.body, { color: colors.textPrimary }]}>{formatJalaliDateTime(v.checked_in_at)}</Text>
              <StatusBadge statusCode={v.status_code} label={v.status_code} />
            </View>
            {v.is_outside_geofence ? (
              <Text style={[typography.caption, { color: colors.danger, marginTop: spacing.xs }]}>خارج از محدوده‌یِ مجاز</Text>
            ) : null}
          </Card>
        ))
      )}

      {calls.length > 0 ? (
        <>
          <SectionHeader label="تماس‌ها" count={calls.length} />
          {calls.map((c) => (
            <Card key={c.call_log_id}>
              <Text style={[typography.body, { color: colors.textPrimary }]}>{c.phone_number}</Text>
              <Text style={[typography.caption, { color: colors.textSecondary }]}>
                {formatJalaliDateTime(c.started_at)} · {c.was_successful ? "موفق" : "ناموفق"}
              </Text>
            </Card>
          ))}
        </>
      ) : null}

      {notes.length > 0 ? (
        <>
          <SectionHeader label="یادداشت‌ها" count={notes.length} />
          {notes.map((n) => (
            <Card key={n.note_id}>
              <Text style={[typography.body, { color: colors.textPrimary }]}>{n.note_text}</Text>
              <Text style={[typography.caption, { color: colors.textSecondary }]}>{formatJalaliDate(n.created_at)}</Text>
            </Card>
          ))}
        </>
      ) : null}
    </ScrollView>
  );
}
