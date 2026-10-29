import React, { useCallback, useEffect, useState } from "react";
import { RefreshControl, ScrollView, Text, View } from "react-native";
import { ApiClient, ApiError } from "../api/client";
import { SelfAttendance, SelfLeaveRow, SelfPayslipDetail, SelfPayslipRow, SelfProfile } from "../api/selfTypes";
import { Button, Card, EmptyState, ErrorState, Input, SkeletonList, StatusBadge, useToast } from "../components";
import { formatAmount } from "../format";
import { formatJalaliDate } from "../jalali";
import { buildLeaveRequest, minutesLabel, payslipTitle, toPersianDigits } from "../selfService";
import { OfflineQueue } from "../sync/offlineQueue";
import { useTheme } from "../theme/ThemeProvider";

interface Props {
  apiClient: ApiClient;
  offlineQueue: OfflineQueue;
  onBack: () => void;
}

type Tab = "PAYSLIPS" | "LEAVE" | "ATTENDANCE";
const TABS: { key: Tab; label: string }[] = [
  { key: "PAYSLIPS", label: "فیش حقوقی" }, { key: "LEAVE", label: "مرخصی" }, { key: "ATTENDANCE", label: "حضور و تأخیر" },
];

/** خدماتِ من (R360): فیشِ حقوقیِ قطعی‌شده، درخواست و پیگیریِ مرخصی، و حضور و تأخیرِ روزهایِ اخیر -- فقط پروندهٔ پرسنلیِ
 * خودِ کاربر. درخواستِ مرخصی از صفِ آفلاین می‌رود تا بی‌اینترنت هم ثبت شود. */
export function SelfServiceScreen({ apiClient, offlineQueue, onBack }: Props) {
  const { colors, spacing, typography } = useTheme();
  const toast = useToast();
  const [tab, setTab] = useState<Tab>("PAYSLIPS");
  const [profile, setProfile] = useState<SelfProfile | null>(null);
  const [payslips, setPayslips] = useState<SelfPayslipRow[]>([]);
  const [detail, setDetail] = useState<SelfPayslipDetail | null>(null);
  const [leave, setLeave] = useState<SelfLeaveRow[]>([]);
  const [attendance, setAttendance] = useState<SelfAttendance | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notLinked, setNotLinked] = useState(false);
  const [leaveType, setLeaveType] = useState("ANNUAL");
  const [fromText, setFromText] = useState("");
  const [toText, setToText] = useState("");
  const [hoursText, setHoursText] = useState("");
  const [reason, setReason] = useState("");
  const [queued, setQueued] = useState(0);

  const load = useCallback(async () => {
    setError(null);
    try {
      const p = await apiClient.getSelfProfile();
      setProfile(p);
      const [slips, leaves, att] = await Promise.all([
        apiClient.getSelfPayslips(), apiClient.getSelfLeave(), apiClient.getSelfAttendance(31),
      ]);
      setPayslips(slips);
      setLeave(leaves);
      setAttendance(att);
      setQueued(0);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) setNotLinked(true);
      else setError(e instanceof ApiError ? e.message : "دریافت اطلاعات ناموفق بود.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [apiClient]);

  useEffect(() => {
    load();
  }, [load]);

  const openPayslip = async (id: number) => {
    try {
      setDetail(await apiClient.getSelfPayslip(id));
    } catch (e) {
      toast.show(e instanceof ApiError ? e.message : "فیش باز نشد.", "danger");
    }
  };

  const submitLeave = async () => {
    const built = buildLeaveRequest({ leaveType, fromText, toText, hoursText, reason });
    if ("error" in built) {
      toast.show(built.error, "danger");
      return;
    }
    await offlineQueue.enqueue({ type: "SELF_LEAVE_REQUEST", payload: built.payload });
    setFromText("");
    setToText("");
    setHoursText("");
    setReason("");
    setQueued((n) => n + 1);
    toast.show("درخواست ثبت شد؛ پس از اتصال برای تایید فرستاده می‌شود.", "success");
  };

  const cancelLeave = async (row: SelfLeaveRow) => {
    try {
      const updated = await apiClient.cancelSelfLeave(row.leave_request_id);
      setLeave((rows) => rows.map((r) => (r.leave_request_id === updated.leave_request_id ? updated : r)));
      toast.show("درخواست لغو شد.", "success");
    } catch (e) {
      toast.show(e instanceof ApiError ? e.message : "لغو فقط با اینترنت ممکن است.", "danger");
    }
  };

  if (loading) return <SkeletonList count={4} />;
  if (notLinked) {
    return (
      <View style={{ flex: 1, padding: spacing.lg, backgroundColor: colors.background }}>
        <EmptyState title="پروندهٔ پرسنلی به کاربر شما وصل نیست" description="از واحد منابع انسانی بخواهید کاربر شما را در پروندهٔ پرسنلی ثبت کند."
          actionLabel="بازگشت" onPressAction={onBack} />
      </View>
    );
  }
  if (error) return <ErrorState description={error} onRetry={load} />;

  const muted = [typography.caption, { color: colors.textSecondary }];
  const line = (label: string, amount: string, key: string) => (
    <View key={key} style={{ flexDirection: "row", justifyContent: "space-between", marginTop: spacing.xxs }}>
      <Text style={[typography.body, { color: colors.textPrimary }]}>{label}</Text>
      <Text style={[typography.body, { color: colors.textPrimary }]}>{formatAmount(amount)}</Text>
    </View>
  );

  return (
    <ScrollView
      style={{ flex: 1, backgroundColor: colors.background }}
      contentContainerStyle={{ padding: spacing.lg, gap: spacing.md }}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
    >
      <View style={{ flexDirection: "row", gap: spacing.sm }}>
        <Button label="بازگشت" variant="secondary" onPress={detail ? () => setDetail(null) : onBack} fullWidth={false} size="md" />
      </View>
      <Text style={[typography.h2, { color: colors.textPrimary }]}>خدمات من</Text>
      <Text style={muted}>{profile ? `${profile.name} — کد ${toPersianDigits(profile.employee_code)}` : ""}</Text>
      <View style={{ flexDirection: "row", gap: spacing.sm, flexWrap: "wrap" }}>
        {TABS.map((t) => (
          <Button key={t.key} label={t.label} size="md" fullWidth={false} variant={tab === t.key ? "primary" : "secondary"}
            onPress={() => { setTab(t.key); setDetail(null); }} />
        ))}
      </View>

      {tab === "PAYSLIPS" && detail ? (
        <Card>
          <Text style={[typography.bodyBold, { color: colors.textPrimary }]}>فیش {payslipTitle(detail)}</Text>
          <Text style={[typography.captionBold, { color: colors.textSecondary, marginTop: spacing.sm }]}>مزایا</Text>
          {detail.earnings.map((ln, i) => line(ln.label, ln.amount, `e${i}`))}
          <Text style={[typography.captionBold, { color: colors.textSecondary, marginTop: spacing.sm }]}>کسورات</Text>
          {detail.deductions.length ? detail.deductions.map((ln, i) => line(ln.label, ln.amount, `d${i}`)) : <Text style={muted}>—</Text>}
          <View style={{ marginTop: spacing.sm }}>
            {line("جمع مزایا", detail.gross_amount, "g")}
            {line("جمع کسورات", detail.total_deductions, "t")}
            {line("خالص پرداختی", detail.net_pay, "n")}
          </View>
        </Card>
      ) : null}
      {tab === "PAYSLIPS" && !detail ? (
        payslips.length === 0 ? <EmptyState title="هنوز فیش قطعی‌شده‌ای ندارید" /> : payslips.map((p) => (
          <Card key={p.payslip_id} onPress={() => openPayslip(p.payslip_id)}>
            <Text style={[typography.bodyBold, { color: colors.textPrimary }]}>{payslipTitle(p)}</Text>
            <Text style={muted}>خالص پرداختی: {formatAmount(p.net_pay)}</Text>
          </Card>
        ))
      ) : null}

      {tab === "LEAVE" ? (
        <>
          <Card>
            <Text style={[typography.bodyBold, { color: colors.textPrimary }]}>درخواست مرخصی جدید</Text>
            <View style={{ flexDirection: "row", gap: spacing.xs, flexWrap: "wrap", marginTop: spacing.sm }}>
              {Object.entries(profile?.leave_types ?? {}).map(([code, label]) => (
                <Button key={code} label={label} size="md" fullWidth={false} variant={leaveType === code ? "primary" : "ghost"}
                  onPress={() => setLeaveType(code)} />
              ))}
            </View>
            <Input label="از تاریخ (شمسی)" value={fromText} onChangeText={setFromText} placeholder="۱۴۰۵/۰۸/۱۵" />
            {leaveType === "HOURLY" ? (
              <Input label="تعداد ساعت" value={hoursText} onChangeText={setHoursText} numeric keyboardType="decimal-pad" />
            ) : (
              <Input label="تا تاریخ (شمسی، برای یک روز خالی بگذارید)" value={toText} onChangeText={setToText} placeholder="۱۴۰۵/۰۸/۱۷" />
            )}
            <Input label="دلیل" value={reason} onChangeText={setReason} multiline />
            <Button label="ثبت و ارسال برای تایید" onPress={submitLeave} />
            {queued ? <Text style={[typography.caption, { color: colors.info, marginTop: spacing.xs }]}>
              {toPersianDigits(queued)} درخواست در صف ارسال است.
            </Text> : null}
          </Card>
          {leave.length === 0 ? <EmptyState title="درخواست مرخصی ندارید" /> : leave.map((r) => (
            <Card key={r.leave_request_id}>
              <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
                <Text style={[typography.bodyBold, { color: colors.textPrimary }]}>مرخصی {r.leave_type_label}</Text>
                <StatusBadge statusCode={r.status_code} label={r.status_label} />
              </View>
              <Text style={muted}>
                {formatJalaliDate(r.from_date)}{r.to_date !== r.from_date ? ` تا ${formatJalaliDate(r.to_date)}` : ""}
                {r.hours ? ` — ${toPersianDigits(Number(r.hours))} ساعت` : ` — ${toPersianDigits(Number(r.days ?? 0))} روز`}
              </Text>
              {r.decision_note ? <Text style={muted}>نظر تاییدکننده: {r.decision_note}</Text> : null}
              {r.status_code === "SUBMITTED" || r.status_code === "DRAFT" ? (
                <Button label="لغو درخواست" variant="danger" size="md" fullWidth={false} onPress={() => cancelLeave(r)}
                  style={{ marginTop: spacing.sm }} />
              ) : null}
            </Card>
          ))}
        </>
      ) : null}

      {tab === "ATTENDANCE" ? (
        attendance && attendance.days.length ? (
          <>
            {attendance.summary ? (
              <Card>
                <Text style={[typography.bodyBold, { color: colors.textPrimary }]}>
                  {formatJalaliDate(attendance.date_from)} تا {formatJalaliDate(attendance.date_to)}
                </Text>
                <Text style={muted}>
                  روز کاری {toPersianDigits(attendance.summary.workdays)} — حاضر {toPersianDigits(attendance.summary.present)} — غایب{" "}
                  {toPersianDigits(attendance.summary.absent)} — مرخصی {toPersianDigits(attendance.summary.leave)}
                </Text>
                <Text style={[typography.caption, { color: attendance.summary.late_minutes ? colors.danger : colors.textSecondary }]}>
                  تأخیر: {minutesLabel(attendance.summary.late_minutes) || "ندارد"}
                  {attendance.summary.early_minutes ? ` — تعجیل: ${minutesLabel(attendance.summary.early_minutes)}` : ""}
                </Text>
              </Card>
            ) : null}
            {attendance.days.map((d) => (
              <Card key={d.work_date}>
                <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
                  <Text style={[typography.bodyBold, { color: colors.textPrimary }]}>{formatJalaliDate(d.work_date)}</Text>
                  <Text style={[typography.captionBold, { color: d.kind === "ABSENT" ? colors.danger : colors.textSecondary }]}>
                    {d.kind_label}{d.pending ? " (منتظر تایید)" : ""}
                  </Text>
                </View>
                {d.clock_in || d.clock_out ? (
                  <Text style={muted}>ورود {toPersianDigits(d.clock_in ?? "—")} — خروج {toPersianDigits(d.clock_out ?? "—")}</Text>
                ) : null}
                {d.late_minutes ? <Text style={[typography.caption, { color: colors.danger }]}>تأخیر {minutesLabel(d.late_minutes)}</Text> : null}
                {d.early_minutes ? <Text style={muted}>تعجیل {minutesLabel(d.early_minutes)}</Text> : null}
              </Card>
            ))}
          </>
        ) : <EmptyState title="شیفتی برای شما تعریف نشده یا روزی ثبت نشده است" />
      ) : null}
    </ScrollView>
  );
}
