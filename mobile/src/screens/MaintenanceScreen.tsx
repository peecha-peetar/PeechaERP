import React, { useCallback, useEffect, useRef, useState } from "react";
import { Pressable, RefreshControl, ScrollView, Text, View } from "react-native";
import { ApiClient, ApiError } from "../api/client";
import { MntEquipmentCard, MntTask, MntWorkOrderDetail, MntWorkOrderRow } from "../api/maintenanceTypes";
import { BarcodeScannerModal, Button, Card, EmptyState, Input, StatusBadge, useToast } from "../components";
import { CaptureProvider } from "../capture";
import { toAsciiDigits } from "../format";
import { formatJalaliDate } from "../jalali";
import { generateIdempotencyKey } from "../sync/idempotency";
import { OfflineQueue } from "../sync/offlineQueue";
import { SyncEngine } from "../sync/syncEngine";
import { submitWmsAction } from "../sync/wmsSubmit";
import { useTheme } from "../theme/ThemeProvider";

interface Props {
  apiClient: ApiClient;
  offlineQueue: OfflineQueue;
  syncEngine: SyncEngine;
  captureProvider?: CaptureProvider;
  onBack: () => void;
}

type Tab = "SCAN" | "MINE";
const SEVERITIES = [
  { code: "LOW", label: "کم" }, { code: "MEDIUM", label: "متوسط" }, { code: "HIGH", label: "زیاد" }, { code: "CRITICAL", label: "بحرانی" },
];

/** صفحهٔ تکنسین نگهداری (R312): اسکن برچسب تجهیز، ثبت سریع خرابی، کارهای من، چک‌لیست و ثبت انجام کار.
 * نوشتن‌ها از صف آفلاین می‌رود و نتیجهٔ فوری (ثبت/در صف/رد) نشان داده می‌شود. «انجام‌شده» ماشین را آماده نمی‌کند؛
 * آزمون و آماده‌به‌کاری را سرپرست ثبت می‌کند. */
export function MaintenanceScreen({ apiClient, offlineQueue, syncEngine, captureProvider, onBack }: Props) {
  const { colors, spacing, typography } = useTheme();
  const toast = useToast();
  const [tab, setTab] = useState<Tab>("SCAN");
  const [scanning, setScanning] = useState(false);
  const [code, setCode] = useState("");
  const [card, setCard] = useState<MntEquipmentCard | null>(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [stopped, setStopped] = useState(false);
  const [severity, setSeverity] = useState("MEDIUM");
  const [photo, setPhoto] = useState<string | null>(null);
  // تلاش دوباره پس از قطع ارسال عکس، همان درخواست را برمی‌گرداند (نه درخواست تکراری)
  const draftKey = useRef(generateIdempotencyKey());
  const [busy, setBusy] = useState(false);
  const [jobs, setJobs] = useState<MntWorkOrderRow[]>([]);
  const [loadingJobs, setLoadingJobs] = useState(false);
  const [job, setJob] = useState<MntWorkOrderDetail | null>(null);
  const [values, setValues] = useState<Record<number, string>>({});
  const [hours, setHours] = useState("");
  const [note, setNote] = useState("");

  const errorText = (e: unknown, fallback: string) => (e instanceof ApiError ? e.message : fallback);
  const caption = [typography.caption, { color: colors.textSecondary }];
  const label = [typography.captionBold, { color: colors.textSecondary, marginBottom: spacing.xs }];
  const body = [typography.body, { color: colors.textPrimary }];

  const lookup = async (text: string) => {
    const value = toAsciiDigits(text.trim());
    if (!value) return;
    setBusy(true);
    try {
      setCard(await apiClient.lookupEquipment(value));
      setCode(value);
    } catch (e) {
      setCard(null);
      toast.show(errorText(e, "تجهیز پیدا نشد."), "danger");
    } finally {
      setBusy(false);
    }
  };

  const loadJobs = useCallback(async () => {
    setLoadingJobs(true);
    try {
      setJobs(await apiClient.listMyWorkOrders());
    } catch (e) {
      toast.show(errorText(e, "دریافت کارها ناموفق بود."), "danger");
    } finally {
      setLoadingJobs(false);
    }
  }, [apiClient, toast]);

  useEffect(() => {
    if (tab === "MINE") void loadJobs();
  }, [tab, loadJobs]);

  const openJob = async (id: number) => {
    try {
      const detail = await apiClient.getWorkOrder(id);
      setJob(detail);
      const v: Record<number, string> = {};
      detail.tasks.forEach((t) => {
        v[t.task_id] = t.value_numeric ?? t.value_text ?? "";
      });
      setValues(v);
    } catch (e) {
      toast.show(errorText(e, "دریافت دستور کار ناموفق بود."), "danger");
    }
  };

  const report = (outcome: Awaited<ReturnType<typeof submitWmsAction>>, done: string) => {
    if (outcome.status === "DONE") toast.show(done, "success");
    else if (outcome.status === "QUEUED") toast.show("بی‌اینترنت در صف ماند؛ پس از اتصال ثبت می‌شود.", "info");
    else toast.show(outcome.reason, "danger");
    return outcome.status !== "REJECTED";
  };

  const submitRequest = async () => {
    if (!card) {
      toast.show("ابتدا برچسب تجهیز را اسکن کنید.", "danger");
      return;
    }
    if (!title.trim()) {
      toast.show("شرح کوتاه خرابی را بنویسید.", "danger");
      return;
    }
    setBusy(true);
    try {
      if (photo) {
        // عکس آنلاین فرستاده می‌شود (حجم زیاد در صف آفلاین نمی‌ماند)؛ ابتدا خود درخواست ثبت می‌شود
        const created = await apiClient.createMaintenanceRequest({
          asset_id: card.asset_id, title: title.trim(), description: description.trim() || null, machine_stopped: stopped,
          severity_code: severity, scanned: true,
        }, draftKey.current);
        await apiClient.addMaintenancePhoto(created.request_id, "photo.jpg", photo);
        toast.show("درخواست با عکس ثبت شد.", "success");
      } else {
        const outcome = await submitWmsAction(offlineQueue, syncEngine, {
          type: "MNT_CREATE_REQUEST",
          payload: {
            asset_id: card.asset_id, title: title.trim(), description: description.trim() || null, machine_stopped: stopped,
            severity_code: severity, scanned: true, failure_at: new Date().toISOString(),
          },
        });
        if (!report(outcome, "درخواست ثبت شد.")) return;
      }
      setTitle("");
      setDescription("");
      setStopped(false);
      setPhoto(null);
      draftKey.current = generateIdempotencyKey();
      await lookup(code);
    } catch (e) {
      toast.show(errorText(e, "ثبت ناموفق بود."), "danger");
    } finally {
      setBusy(false);
    }
  };

  const takePhoto = async () => {
    if (!captureProvider) return;
    const shot = await captureProvider.capturePhoto();
    if (shot) setPhoto(shot);
  };

  const act = async (action: "start" | "hold" | "resume" | "complete" | "labor", payload: Record<string, unknown>, done: string) => {
    if (!job) return;
    setBusy(true);
    try {
      const outcome = await submitWmsAction(offlineQueue, syncEngine, {
        type: "MNT_ACTION", payload: { workOrderId: job.work_order_id, action, body: payload },
      });
      if (report(outcome, done) && outcome.status === "DONE") await openJob(job.work_order_id);
    } finally {
      setBusy(false);
    }
  };

  const recordTask = async (task: MntTask, done: boolean) => {
    const raw = toAsciiDigits((values[task.task_id] ?? "").trim());
    if (task.result_type === "NUMERIC" && !raw) {
      toast.show("مقدار اندازه‌گیری‌شده را وارد کنید.", "danger");
      return;
    }
    const outcome = await submitWmsAction(offlineQueue, syncEngine, {
      type: "MNT_TASK",
      payload: {
        taskId: task.task_id, done,
        valueNumeric: task.result_type === "NUMERIC" ? raw : null,
        valueText: task.result_type !== "NUMERIC" ? raw || null : null,
      },
    });
    if (report(outcome, "ثبت شد.") && outcome.status === "DONE" && job) await openJob(job.work_order_id);
  };

  const severityChips = (
    <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.xs, marginBottom: spacing.md }}>
      {SEVERITIES.map((s) => (
        <Button key={s.code} label={s.label} size="md" fullWidth={false} variant={severity === s.code ? "primary" : "secondary"}
          onPress={() => setSeverity(s.code)} />
      ))}
    </View>
  );

  const renderScan = () => (
    <ScrollView contentContainerStyle={{ padding: spacing.lg }}>
      <Button label="اسکن برچسب تجهیز" onPress={() => setScanning(true)} />
      <View style={{ height: spacing.sm }} />
      <Input label="یا کد تجهیز" value={code} onChangeText={setCode} onSubmitEditing={() => lookup(code)} />
      <Button label="نمایش تجهیز" variant="secondary" loading={busy} onPress={() => lookup(code)} />
      {card ? (
        <Card style={{ marginTop: spacing.lg }}>
          <Text style={[typography.h3, { color: colors.textPrimary }]}>{`${card.code} — ${card.name}`}</Text>
          <Text style={caption}>{[card.location, card.line].filter(Boolean).join(" | ")}</Text>
          <Text style={caption}>{`سریال: ${card.serial_no ?? "—"} | ${card.manufacturer ?? ""} ${card.model ?? ""}`}</Text>
          <View style={{ flexDirection: "row", gap: spacing.xs, marginTop: spacing.xs }}>
            <StatusBadge statusCode={card.down_now ? "FAILED" : "ACTIVE"} label={card.down_now ? "متوقف" : card.status_label} />
            <StatusBadge statusCode="IN_PROGRESS" label={`اهمیت: ${card.criticality_label}`} />
          </View>
          {card.safety_notes ? <Text style={[body, { marginTop: spacing.sm }]}>{`ایمنی: ${card.safety_notes}`}</Text> : null}
          {card.open_work_orders.length ? (
            <Text style={[caption, { marginTop: spacing.sm }]}>
              {`کار باز: ${card.open_work_orders.map((w) => `${w.wo_no} ${w.title} (${w.status_label})`).join("، ")}`}
            </Text>
          ) : null}
        </Card>
      ) : null}
      {card ? (
        <View style={{ marginTop: spacing.lg }}>
          <Text style={[typography.h3, { color: colors.textPrimary, marginBottom: spacing.sm }]}>ثبت خرابی</Text>
          <Input label="شرح کوتاه خرابی *" value={title} onChangeText={setTitle} />
          <Input label="توضیح" value={description} onChangeText={setDescription} multiline />
          <Text style={label}>شدت</Text>
          {severityChips}
          <Button label={stopped ? "ماشین متوقف است ✓" : "ماشین متوقف است؟"} variant={stopped ? "primary" : "secondary"}
            onPress={() => setStopped(!stopped)} />
          <Text style={[caption, { marginVertical: spacing.xs }]}>
            با «ماشین متوقف است» توقف همین حالا ثبت و ماشین از ظرفیت تولید کم می‌شود.
          </Text>
          {captureProvider ? (
            <Button label={photo ? "عکس گرفته شد ✓" : "گرفتن عکس"} variant="secondary" onPress={takePhoto} />
          ) : null}
          <View style={{ height: spacing.sm }} />
          <Button label="ثبت درخواست" loading={busy} onPress={submitRequest} />
        </View>
      ) : null}
    </ScrollView>
  );

  const renderTask = (t: MntTask) => (
    <Card key={t.task_id} style={{ marginBottom: spacing.sm }}>
      <Text style={body}>{`${t.seq}. ${t.description}${t.is_mandatory ? " *" : ""}${t.is_safety ? " (ایمنی)" : ""}`}</Text>
      {t.result_type === "NUMERIC" ? (
        <Text style={caption}>{`حدود مجاز: ${t.min_value ?? "—"} تا ${t.max_value ?? "—"} ${t.uom_label ?? ""}`}</Text>
      ) : null}
      {t.is_done ? (
        <Text style={[caption, { color: t.is_ok === false ? colors.danger : colors.success }]}>
          {t.is_ok === false ? `خارج از حدود: ${t.value_numeric ?? ""}` : `انجام شد ${t.value_numeric ?? t.value_text ?? ""}`}
        </Text>
      ) : null}
      {job?.status_code === "IN_PROGRESS" ? (
        <View>
          {t.result_type !== "CHECK" ? (
            <Input value={values[t.task_id] ?? ""} onChangeText={(v) => setValues({ ...values, [t.task_id]: v })}
              keyboardType={t.result_type === "NUMERIC" ? "numeric" : "default"}
              placeholder={t.result_type === "NUMERIC" ? "مقدار" : "شرح نتیجه"} />
          ) : null}
          <View style={{ flexDirection: "row", gap: spacing.xs }}>
            <Button label="ثبت" size="md" fullWidth={false} onPress={() => recordTask(t, true)} />
            {t.result_type === "CHECK" ? (
              <Button label="انجام نشد" size="md" fullWidth={false} variant="secondary" onPress={() => recordTask(t, false)} />
            ) : null}
          </View>
        </View>
      ) : null}
    </Card>
  );

  const renderJob = (j: MntWorkOrderDetail) => (
    <ScrollView contentContainerStyle={{ padding: spacing.lg }}>
      <Button label="بازگشت به فهرست" variant="secondary" onPress={() => { setJob(null); void loadJobs(); }} />
      <Card style={{ marginTop: spacing.md }}>
        <Text style={[typography.h3, { color: colors.textPrimary }]}>{`دستور کار ${j.wo_no} — ${j.title}`}</Text>
        <Text style={caption}>{`${j.asset_label} | ${j.work_type_label} | اولویت ${j.priority_label}`}</Text>
        <View style={{ flexDirection: "row", gap: spacing.xs, marginTop: spacing.xs }}>
          <StatusBadge statusCode={j.status_code} label={j.status_label} />
          {j.machine_down ? <StatusBadge statusCode="FAILED" label="ماشین متوقف" /> : null}
        </View>
        {j.safety_instructions ? <Text style={[body, { marginTop: spacing.sm }]}>{`ایمنی: ${j.safety_instructions}`}</Text> : null}
        {j.hold_reason ? <Text style={caption}>{`توقف موقت: ${j.hold_reason}`}</Text> : null}
        {j.parts.length ? <Text style={caption}>{`قطعه‌ها: ${j.parts.map((p) => `${p.item} (${p.issued ?? 0} از ${p.planned ?? 0})`).join("، ")}`}</Text> : null}
      </Card>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.xs, marginVertical: spacing.md }}>
        {["OPEN", "PLANNED", "ASSIGNED"].includes(j.status_code) ? (
          <Button label="شروع کار" size="md" fullWidth={false} loading={busy} onPress={() => act("start", {}, "کار شروع شد.")} />
        ) : null}
        {j.status_code === "IN_PROGRESS" ? (
          <Button label="توقف موقت" size="md" fullWidth={false} variant="secondary"
            onPress={() => (note.trim() ? act("hold", { reason: note.trim() }, "متوقف شد.") : toast.show("علت را در یادداشت بنویسید.", "danger"))} />
        ) : null}
        {j.status_code === "ON_HOLD" ? (
          <Button label="ادامهٔ کار" size="md" fullWidth={false} onPress={() => act("resume", {}, "ادامه یافت.")} />
        ) : null}
      </View>
      {j.tasks.length ? <Text style={label}>چک‌لیست</Text> : null}
      {j.tasks.map(renderTask)}
      {["IN_PROGRESS", "ON_HOLD", "COMPLETED"].includes(j.status_code) ? (
        <View style={{ marginTop: spacing.md }}>
          <Input label="ساعت کار امروز" value={hours} onChangeText={setHours} keyboardType="numeric" />
          <Button label="ثبت ساعت کار" variant="secondary"
            onPress={() => {
              const h = toAsciiDigits(hours.trim());
              if (!h) return;
              void act("labor", { hours: h }, "ساعت کار ثبت شد.");
              setHours("");
            }} />
        </View>
      ) : null}
      <Input label="یادداشت (علت توقف موقت یا شرح کار انجام‌شده)" value={note} onChangeText={setNote} multiline />
      {j.status_code === "IN_PROGRESS" ? (
        <Button label="ثبت انجام کار" loading={busy}
          onPress={() => (note.trim() ? act("complete", { note: note.trim() }, "انجام کار ثبت شد؛ منتظر آزمون است.")
            : toast.show("شرح کار انجام‌شده را بنویسید.", "danger"))} />
      ) : null}
      <Text style={[caption, { marginTop: spacing.sm }]}>
        پس از «انجام کار»، ماشین تا آزمون و ثبت آماده‌به‌کاری توسط سرپرست هنوز در دسترس تولید نیست.
      </Text>
    </ScrollView>
  );

  const renderMine = () =>
    job ? renderJob(job) : (
      <ScrollView contentContainerStyle={{ padding: spacing.lg }}
        refreshControl={<RefreshControl refreshing={loadingJobs} onRefresh={loadJobs} />}>
        {jobs.length === 0 && !loadingJobs ? <EmptyState title="کار بازی به شما واگذار نشده است." /> : null}
        {jobs.map((w) => (
          <Card key={w.work_order_id} onPress={() => openJob(w.work_order_id)} style={{ marginBottom: spacing.sm }}>
            <Text style={body}>{`${w.wo_no} — ${w.title}`}</Text>
            <Text style={caption}>{`${w.asset_label} | ${w.work_type_label}`}</Text>
            <View style={{ flexDirection: "row", gap: spacing.xs, marginTop: spacing.xs }}>
              <StatusBadge statusCode={w.status_code} label={w.status_label} />
              <StatusBadge statusCode={w.priority_code === "URGENT" ? "FAILED" : "IN_PROGRESS"} label={w.priority_label} />
            </View>
            {w.planned_start ? <Text style={caption}>{`برنامه: ${formatJalaliDate(w.planned_start)}`}</Text> : null}
          </Card>
        ))}
      </ScrollView>
    );

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <View style={{ flexDirection: "row", alignItems: "center", padding: spacing.md, gap: spacing.sm }}>
        <Pressable onPress={onBack}>
          <Text style={[typography.bodyBold, { color: colors.primary }]}>بازگشت</Text>
        </Pressable>
        <Text style={[typography.h2, { color: colors.textPrimary, flex: 1 }]}>نگهداری و تعمیرات</Text>
      </View>
      <View style={{ flexDirection: "row", gap: spacing.xs, paddingHorizontal: spacing.md }}>
        <Button label="اسکن و ثبت خرابی" size="md" fullWidth={false} variant={tab === "SCAN" ? "primary" : "secondary"}
          onPress={() => setTab("SCAN")} />
        <Button label="کارهای من" size="md" fullWidth={false} variant={tab === "MINE" ? "primary" : "secondary"}
          onPress={() => setTab("MINE")} />
      </View>
      {tab === "SCAN" ? renderScan() : renderMine()}
      <BarcodeScannerModal visible={scanning} onClose={() => setScanning(false)}
        onScanned={(value) => { setScanning(false); void lookup(value); }} />
    </View>
  );
}
