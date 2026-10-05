import React, { useCallback, useEffect, useState } from "react";
import { RefreshControl, ScrollView, Text, View } from "react-native";
import { ApiClient, ApiError } from "../api/client";
import { LocationDetail, LocationSearchResult, PutawaySuggestion, WmsTask, WmsTaskType } from "../api/types";
import { BarcodeScannerModal, Button, Card, EmptyState, Input, SearchBar, StatusBadge, useToast } from "../components";
import { formatAmount, toAsciiDigits } from "../format";
import { OfflineQueue, PendingActionInput } from "../sync/offlineQueue";
import { SyncEngine } from "../sync/syncEngine";
import { submitWmsAction } from "../sync/wmsSubmit";
import { useTheme } from "../theme/ThemeProvider";

interface Props {
  apiClient: ApiClient;
  offlineQueue: OfflineQueue;
  syncEngine: SyncEngine;
  onBack: () => void;
}

type Tab = "SEARCH" | "TASKS" | "TRANSFER";
type ScanTarget = "SEARCH" | "PUTAWAY_TARGET" | "TRANSFER_ITEM" | "TRANSFER_FROM" | "TRANSFER_TO";

const STATUS_LABELS: Record<string, string> = {
  ACTIVE: "فعال", INACTIVE: "غیرفعال", BLOCKED: "مسدود", FULL: "پر", RESERVED: "رزرو", QUARANTINE: "قرنطینه",
  MAINTENANCE: "در حالِ تعمیر", OPEN: "باز", IN_PROGRESS: "در حالِ انجام",
};
const TASK_FILTERS: { key: WmsTaskType | null; label: string }[] = [
  { key: null, label: "همه" },
  { key: "PUTAWAY", label: "جانمایی" },
  { key: "PICK", label: "برداشت" },
  { key: "REPLENISH", label: "تأمین" },
];

/** پیدا کردنِ محل از متنِ اسکن‌شده یا تایپ‌شده (QR، کدِ محل یا بارکدِ محل). */
export async function resolveLocation(api: ApiClient, text: string): Promise<LocationDetail | null> {
  const value = toAsciiDigits(text.trim());
  if (!value) return null;
  if (value.startsWith("PEECHA-LOC:")) return api.scanLocation(value);
  const result = await api.searchLocations(value);
  return result.kind === "LOCATION" && result.locations.length > 0 ? result.locations[0] : null;
}

/** اپِ انباردار (R249): جستجو/اسکنِ محل و کالا، وظایفِ جانمایی/برداشت/تأمین و انتقالِ بینِ محل‌ها.
 * نوشتن‌ها از صفِ آفلاین می‌روند و نتیجهٔ فوری (ثبت/در صف/رد) نشان داده می‌شود. */
export function WarehouseScreen({ apiClient, offlineQueue, syncEngine, onBack }: Props) {
  const { colors, spacing, typography } = useTheme();
  const toast = useToast();
  const [tab, setTab] = useState<Tab>("SEARCH");
  const [scanTarget, setScanTarget] = useState<ScanTarget | null>(null);

  // جستجو
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<LocationSearchResult | null>(null);
  const [searching, setSearching] = useState(false);

  // وظایف
  const [taskFilter, setTaskFilter] = useState<WmsTaskType | null>(null);
  const [tasks, setTasks] = useState<WmsTask[]>([]);
  const [loadingTasks, setLoadingTasks] = useState(false);
  const [activeTask, setActiveTask] = useState<WmsTask | null>(null);
  const [taskQty, setTaskQty] = useState("");
  const [suggestions, setSuggestions] = useState<PutawaySuggestion[]>([]);
  const [putawayTarget, setPutawayTarget] = useState<{ id: number; code: string } | null>(null);

  // انتقال
  const [transferItem, setTransferItem] = useState<{ id: number; label: string } | null>(null);
  const [transferFrom, setTransferFrom] = useState<{ id: number; code: string } | null>(null);
  const [transferTo, setTransferTo] = useState<{ id: number; code: string } | null>(null);
  const [transferQty, setTransferQty] = useState("");
  const [busy, setBusy] = useState(false);

  const errorText = (e: unknown, fallback: string) => (e instanceof ApiError ? e.message : fallback);

  const runSearch = async (text: string) => {
    const value = toAsciiDigits(text.trim());
    if (!value) return;
    setSearching(true);
    try {
      setResult(await apiClient.searchLocations(value));
    } catch (e) {
      toast.show(errorText(e, "جستجو ناموفق بود."), "danger");
    } finally {
      setSearching(false);
    }
  };

  const loadTasks = useCallback(async () => {
    setLoadingTasks(true);
    try {
      setTasks(await apiClient.listWmsTasks(taskFilter ?? undefined));
    } catch (e) {
      toast.show(errorText(e, "دریافتِ وظایف ناموفق بود."), "danger");
    } finally {
      setLoadingTasks(false);
    }
  }, [apiClient, taskFilter]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (tab === "TASKS") loadTasks();
  }, [tab, loadTasks]);

  const submit = async (input: PendingActionInput, okText: string): Promise<boolean> => {
    setBusy(true);
    try {
      const outcome = await submitWmsAction(offlineQueue, syncEngine, input);
      if (outcome.status === "DONE") toast.show(okText, "success");
      else if (outcome.status === "QUEUED") toast.show("اتصال برقرار نیست؛ در صف ماند و بعداً ارسال می‌شود.", "warning");
      else toast.show(outcome.reason, "danger");
      return outcome.status !== "REJECTED";
    } finally {
      setBusy(false);
    }
  };

  const openTask = async (task: WmsTask) => {
    setActiveTask(task);
    setTaskQty(task.quantity);
    setPutawayTarget(null);
    setSuggestions([]);
    if (task.task_type === "PUTAWAY") {
      try {
        setSuggestions(await apiClient.getPutawaySuggestions(task.warehouse_id, task.item_id, task.quantity));
      } catch {
        setSuggestions([]);
      }
    }
  };

  const startTask = async (task: WmsTask) => {
    try {
      await apiClient.startWmsTask(task.task_id);
      await loadTasks();
    } catch (e) {
      toast.show(errorText(e, "شروعِ وظیفه ناموفق بود."), "danger");
    }
  };

  const completeTask = async () => {
    if (!activeTask) return;
    const qty = toAsciiDigits(taskQty);
    let ok = false;
    if (activeTask.task_type === "PUTAWAY") {
      if (!putawayTarget) {
        toast.show("محلِ مقصد را انتخاب یا اسکن کنید.", "warning");
        return;
      }
      ok = await submit({ type: "WMS_PUTAWAY", payload: { taskId: activeTask.task_id, toLocationId: putawayTarget.id } }, "جانمایی ثبت شد.");
    } else if (activeTask.task_type === "PICK") {
      ok = await submit({ type: "WMS_PICK", payload: { taskId: activeTask.task_id, quantity: qty } }, "برداشت ثبت شد.");
    } else {
      ok = await submit({ type: "WMS_REPLENISH", payload: { taskId: activeTask.task_id, quantity: qty || null } }, "تأمینِ مجدد ثبت شد.");
    }
    if (ok) {
      setActiveTask(null);
      await loadTasks();
    }
  };

  const submitTransfer = async () => {
    if (!transferItem || !transferFrom || !transferTo || !toAsciiDigits(transferQty)) {
      toast.show("کالا، محلِ مبدا، محلِ مقصد و مقدار را کامل کنید.", "warning");
      return;
    }
    const ok = await submit(
      {
        type: "WMS_TRANSFER",
        payload: { item_id: transferItem.id, from_location_id: transferFrom.id, to_location_id: transferTo.id, quantity: toAsciiDigits(transferQty) },
      },
      "انتقال ثبت شد.",
    );
    if (ok) {
      setTransferTo(null);
      setTransferQty("");
    }
  };

  const onScanned = async (code: string) => {
    const target = scanTarget;
    setScanTarget(null);
    try {
      if (target === "SEARCH") {
        setQuery(code);
        await runSearch(code);
      } else if (target === "TRANSFER_ITEM") {
        const found = await apiClient.searchLocations(toAsciiDigits(code));
        if (found.kind !== "PRODUCT" || found.item_ids.length === 0) throw new ApiError(404, "کالایی با این بارکد پیدا نشد.");
        const itemId = found.item_ids[0];
        const row = found.locations.flatMap((l) => l.contents).find((c) => c.item_id === itemId);
        setTransferItem({ id: itemId, label: row ? `${row.item_code} — ${row.item_name}` : code });
      } else if (target) {
        const loc = await resolveLocation(apiClient, code);
        if (!loc) throw new ApiError(404, "محلی با این کد پیدا نشد.");
        const picked = { id: loc.location_id, code: loc.code };
        if (target === "PUTAWAY_TARGET") setPutawayTarget(picked);
        if (target === "TRANSFER_FROM") setTransferFrom(picked);
        if (target === "TRANSFER_TO") setTransferTo(picked);
      }
    } catch (e) {
      toast.show(errorText(e, "خواندنِ کد ناموفق بود."), "danger");
    }
  };

  const startTransferFrom = (loc: LocationDetail, itemId: number, label: string) => {
    setTransferItem({ id: itemId, label });
    setTransferFrom({ id: loc.location_id, code: loc.code });
    setTransferTo(null);
    setTab("TRANSFER");
  };

  const text = (style: object, value: string, extra?: object) => <Text style={[style, { color: colors.textPrimary }, extra]}>{value}</Text>;

  const renderLocation = (loc: LocationDetail, focusItemIds: number[]) => (
    <Card key={loc.location_id}>
      <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
        {text(typography.bodyBold, loc.code)}
        <StatusBadge statusCode={loc.status} label={STATUS_LABELS[loc.status] ?? loc.status} />
      </View>
      <Text style={[typography.caption, { color: colors.textSecondary, marginTop: spacing.xs }]}>
        {loc.name ?? ""}
        {loc.occupancy_percent !== null ? ` · اشغال ${formatAmount(loc.occupancy_percent)}٪` : ""}
        {loc.putaway_allowed ? "" : " · جانمایی مجاز نیست"}
      </Text>
      {loc.contents.length === 0 ? (
        <Text style={[typography.caption, { color: colors.textSecondary, marginTop: spacing.sm }]}>خالی</Text>
      ) : (
        loc.contents.map((c) => (
          <View
            key={`${c.location_code}-${c.item_id}`}
            style={{
              marginTop: spacing.sm, paddingTop: spacing.sm, borderTopWidth: 1, borderColor: colors.border,
              opacity: focusItemIds.length === 0 || focusItemIds.includes(c.item_id) ? 1 : 0.45,
            }}
          >
            {text(typography.body, `${c.item_code} — ${c.item_name}`)}
            <Text style={[typography.caption, { color: colors.textSecondary }]}>
              {`${formatAmount(c.quantity)} ${c.unit} · ${c.location_code}`}
              {c.batches ? ` · بچ: ${c.batches}` : ""}
            </Text>
            <Button
              label="انتقال از این محل"
              size="md"
              variant="ghost"
              fullWidth={false}
              onPress={() => startTransferFrom({ ...loc, location_id: loc.location_id, code: c.location_code || loc.code }, c.item_id, `${c.item_code} — ${c.item_name}`)}
            />
          </View>
        ))
      )}
    </Card>
  );

  const renderSearch = () => (
    <View style={{ gap: spacing.md }}>
      <SearchBar value={query} onChangeText={setQuery} placeholder="کد/بارکدِ کالا یا کد/QRِ محل" />
      <View style={{ flexDirection: "row", gap: spacing.sm }}>
        <Button label="جستجو" size="md" fullWidth={false} loading={searching} onPress={() => runSearch(query)} />
        <Button label="اسکن" size="md" variant="secondary" fullWidth={false} onPress={() => setScanTarget("SEARCH")} />
      </View>
      {result === null ? null : result.kind === "NONE" || result.locations.length === 0 ? (
        <EmptyState title="چیزی پیدا نشد" />
      ) : (
        <>
          <Text style={[typography.captionBold, { color: colors.textSecondary }]}>
            {result.kind === "PRODUCT" ? `محل‌هایِ کالا (${result.locations.length})` : "محل"}
          </Text>
          {result.locations.map((loc) => renderLocation(loc, result.kind === "PRODUCT" ? result.item_ids : []))}
        </>
      )}
    </View>
  );

  const renderTaskPanel = (task: WmsTask) => (
    <Card>
      {text(typography.bodyBold, `${task.task_label} · ${task.item_code} — ${task.item_name}`)}
      <Text style={[typography.caption, { color: colors.textSecondary, marginTop: spacing.xs }]}>
        {`مقدار: ${formatAmount(task.quantity)} ${task.unit}`}
        {task.from_location_code ? ` · از ${task.from_location_code}` : ""}
        {task.to_location_code ? ` · به ${task.to_location_code}` : ""}
      </Text>
      {task.task_type === "PUTAWAY" ? (
        <View style={{ marginTop: spacing.md, gap: spacing.sm }}>
          <Text style={[typography.captionBold, { color: colors.textSecondary }]}>محل‌هایِ پیشنهادی</Text>
          {suggestions.length === 0 ? (
            <Text style={[typography.caption, { color: colors.textSecondary }]}>پیشنهادی نیست؛ محلِ مقصد را اسکن کنید.</Text>
          ) : (
            suggestions.map((s) => (
              <Card key={s.location_id} onPress={() => setPutawayTarget({ id: s.location_id, code: s.location_code })}>
                {text(typography.bodyBold, s.location_code, putawayTarget?.id === s.location_id ? { color: colors.primary } : undefined)}
                <Text style={[typography.caption, { color: colors.textSecondary }]}>{s.reasons.join("، ")}</Text>
              </Card>
            ))
          )}
          <Button label="اسکنِ محلِ مقصد" size="md" variant="secondary" onPress={() => setScanTarget("PUTAWAY_TARGET")} />
          {putawayTarget ? text(typography.body, `مقصد: ${putawayTarget.code}`) : null}
        </View>
      ) : (
        <Input label="مقدارِ انجام‌شده" value={taskQty} onChangeText={setTaskQty} numeric keyboardType="decimal-pad" style={{ marginTop: spacing.md }} />
      )}
      <View style={{ flexDirection: "row", gap: spacing.sm, marginTop: spacing.md }}>
        <Button label="تأیید" size="md" fullWidth={false} loading={busy} onPress={completeTask} />
        <Button label="انصراف" size="md" variant="ghost" fullWidth={false} onPress={() => setActiveTask(null)} />
      </View>
    </Card>
  );

  const renderTasks = () => (
    <View style={{ gap: spacing.md }}>
      <View style={{ flexDirection: "row", gap: spacing.xs, flexWrap: "wrap" }}>
        {TASK_FILTERS.map((f) => (
          <Button
            key={f.label}
            label={f.label}
            size="md"
            fullWidth={false}
            variant={taskFilter === f.key ? "primary" : "secondary"}
            onPress={() => setTaskFilter(f.key)}
          />
        ))}
      </View>
      {activeTask ? renderTaskPanel(activeTask) : null}
      {tasks.length === 0 && !loadingTasks ? <EmptyState title="وظیفهٔ بازی نیست" /> : null}
      {tasks.map((t) => (
        <Card key={t.task_id}>
          <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
            {text(typography.bodyBold, `${t.task_label} #${t.task_id}`)}
            <StatusBadge statusCode={t.status} label={STATUS_LABELS[t.status] ?? t.status} />
          </View>
          {text(typography.body, `${t.item_code} — ${t.item_name}`)}
          <Text style={[typography.caption, { color: colors.textSecondary }]}>
            {`${formatAmount(t.quantity)} ${t.unit}`}
            {t.from_location_code ? ` · از ${t.from_location_code}` : ""}
            {t.to_location_code ? ` · به ${t.to_location_code}` : ""}
          </Text>
          <View style={{ flexDirection: "row", gap: spacing.sm, marginTop: spacing.sm }}>
            {t.status === "OPEN" ? (
              <Button label="شروع" size="md" variant="secondary" fullWidth={false} onPress={() => startTask(t)} />
            ) : null}
            <Button label="انجام" size="md" fullWidth={false} onPress={() => openTask(t)} />
          </View>
        </Card>
      ))}
    </View>
  );

  const renderTransfer = () => (
    <Card>
      {text(typography.bodyBold, "انتقالِ کالا بینِ محل‌ها")}
      <View style={{ gap: spacing.sm, marginTop: spacing.md }}>
        {text(typography.body, `کالا: ${transferItem?.label ?? "—"}`)}
        <Button label="اسکنِ کالا" size="md" variant="secondary" onPress={() => setScanTarget("TRANSFER_ITEM")} />
        {text(typography.body, `از محل: ${transferFrom?.code ?? "—"}`)}
        <Button label="اسکنِ محلِ مبدا" size="md" variant="secondary" onPress={() => setScanTarget("TRANSFER_FROM")} />
        {text(typography.body, `به محل: ${transferTo?.code ?? "—"}`)}
        <Button label="اسکنِ محلِ مقصد" size="md" variant="secondary" onPress={() => setScanTarget("TRANSFER_TO")} />
        <Input label="مقدار" value={transferQty} onChangeText={setTransferQty} numeric keyboardType="decimal-pad" />
        <Button label="ثبتِ انتقال" loading={busy} onPress={submitTransfer} />
      </View>
    </Card>
  );

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <ScrollView
        contentContainerStyle={{ padding: spacing.lg, gap: spacing.md }}
        refreshControl={<RefreshControl refreshing={loadingTasks} onRefresh={() => (tab === "TASKS" ? loadTasks() : undefined)} />}
      >
        <Button label="بازگشت" variant="ghost" fullWidth={false} onPress={onBack} />
        <Text style={[typography.h2, { color: colors.textPrimary }]}>انبار</Text>
        <View style={{ flexDirection: "row", gap: spacing.xs }}>
          {([
            ["SEARCH", "جستجو و اسکن"],
            ["TASKS", "وظایف"],
            ["TRANSFER", "انتقال"],
          ] as [Tab, string][]).map(([key, label]) => (
            <Button key={key} label={label} size="md" fullWidth={false} variant={tab === key ? "primary" : "secondary"} onPress={() => setTab(key)} />
          ))}
        </View>
        {tab === "SEARCH" ? renderSearch() : tab === "TASKS" ? renderTasks() : renderTransfer()}
      </ScrollView>
      <BarcodeScannerModal visible={scanTarget !== null} onClose={() => setScanTarget(null)} onScanned={onScanned} />
    </View>
  );
}
