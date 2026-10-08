import React, { useCallback, useEffect, useState } from "react";
import { Pressable, RefreshControl, ScrollView, Text, View } from "react-native";
import { ApiClient, ApiError } from "../api/client";
import {
  LocationCountLine, LocationCountSession, LocationDetail, LocationSearchResult, PutawaySuggestion, WarehouseMapNode, WarehouseRow, WmsTask,
  PutawaySource, WmsKpis, WmsTaskType, WmsWave,
} from "../api/types";
import { BarcodeScannerModal, Button, Card, EmptyState, Input, SearchBar, StatusBadge, useToast } from "../components";
import { formatAmount, toAsciiDigits } from "../format";
import { OfflineQueue, PendingActionInput } from "../sync/offlineQueue";
import { SyncEngine } from "../sync/syncEngine";
import { submitWmsAction } from "../sync/wmsSubmit";
import { formatJalaliDate } from "../jalali";
import { useTheme } from "../theme/ThemeProvider";
import { layoutWarehouseMap, occupancyTone } from "../wms/mapLayout";
import { printLocationLabels } from "../print/locationLabel";

interface Props {
  apiClient: ApiClient;
  offlineQueue: OfflineQueue;
  syncEngine: SyncEngine;
  onBack: () => void;
}

type Tab = "SEARCH" | "TASKS" | "TRANSFER" | "COUNT" | "MAP" | "KPI";
type ScanTarget =
  | "SEARCH" | "PUTAWAY_TARGET" | "TRANSFER_ITEM" | "TRANSFER_FROM" | "TRANSFER_TO" | "COUNT_LOCATION" | "COUNT_START" | "COUNT_SERIAL";

const STATUS_LABELS: Record<string, string> = {
  ACTIVE: "فعال", INACTIVE: "غیرفعال", BLOCKED: "مسدود", FULL: "پر", RESERVED: "رزرو", QUARANTINE: "قرنطینه",
  MAINTENANCE: "در حال تعمیر", OPEN: "باز", IN_PROGRESS: "در حال انجام",
};
const TASK_FILTERS: { key: WmsTaskType | null; label: string }[] = [
  { key: null, label: "همه" },
  { key: "PUTAWAY", label: "جانمایی" },
  { key: "PICK", label: "برداشت" },
  { key: "REPLENISH", label: "تامین" },
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

  // R250: موج، شمارشِ محل، نقشه
  const [waves, setWaves] = useState<WmsWave[]>([]);
  const [activeWave, setActiveWave] = useState<number | null>(null);
  const [warehouses, setWarehouses] = useState<WarehouseRow[]>([]);
  const [counts, setCounts] = useState<LocationCountSession[]>([]);
  const [countId, setCountId] = useState<number | null>(null);
  const [countLines, setCountLines] = useState<LocationCountLine[]>([]);
  const [countLocation, setCountLocation] = useState<{ id: number; code: string } | null>(null);
  const [countQty, setCountQty] = useState<Record<string, string>>({});
  const [mapWarehouse, setMapWarehouse] = useState<number | null>(null);
  const [mapNodes, setMapNodes] = useState<WarehouseMapNode[]>([]);
  const [mapZoom, setMapZoom] = useState(1);
  const [mapSelected, setMapSelected] = useState<LocationDetail | null>(null);
  const [kpis, setKpis] = useState<WmsKpis | null>(null);
  // R252: شمارشِ سریال، منابعِ جانمایی
  const [serialKey, setSerialKey] = useState<string | null>(null);
  const [countSerials, setCountSerials] = useState<Record<string, string[]>>({});
  const [putawaySources, setPutawaySources] = useState<PutawaySource[] | null>(null);

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
      setWaves(await apiClient.listWaves().catch(() => []));
    } catch (e) {
      toast.show(errorText(e, "دریافت وظایف ناموفق بود."), "danger");
    } finally {
      setLoadingTasks(false);
    }
  }, [apiClient, taskFilter]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (tab === "TASKS") loadTasks();
  }, [tab, loadTasks]);

  useEffect(() => {
    if ((tab === "COUNT" || tab === "MAP" || tab === "TASKS") && warehouses.length === 0) {
      apiClient.listWarehouses().then(setWarehouses).catch(() => setWarehouses([]));
    }
    if (tab === "COUNT") apiClient.listLocationCounts().then(setCounts).catch(() => setCounts([]));
    if (tab === "KPI") apiClient.getWmsKpis().then(setKpis).catch((e) => toast.show(errorText(e, "دریافت شاخص‌ها ناموفق بود."), "danger"));
  }, [tab]); // eslint-disable-line react-hooks/exhaustive-deps

  const openCount = async (sessionId: number) => {
    setCountId(sessionId);
    setCountLocation(null);
    setCountQty({});
    try {
      setCountLines(await apiClient.getLocationCountLines(sessionId));
    } catch (e) {
      toast.show(errorText(e, "دریافت شمارش ناموفق بود."), "danger");
    }
  };

  const countKey = (line: LocationCountLine) => `${line.location_id}-${line.item_id}-${line.batch_no ?? ""}`;

  const submitCount = async (line: LocationCountLine) => {
    const qty = toAsciiDigits(countQty[countKey(line)] ?? "");
    if (countId === null || !qty) return;
    const ok = await submit(
      {
        type: "WMS_COUNT",
        payload: { sessionId: countId, locationId: line.location_id, itemId: line.item_id, quantity: qty, batchNo: line.batch_no ?? null },
      },
      "شمارش ثبت شد.",
    );
    if (ok) await openCount(countId);
  };

  const loadMap = async (warehouseId: number) => {
    setMapWarehouse(warehouseId);
    setMapSelected(null);
    try {
      setMapNodes(await apiClient.getWarehouseMap(warehouseId));
    } catch (e) {
      toast.show(errorText(e, "دریافت نقشه ناموفق بود."), "danger");
    }
  };

  const createWave = async (warehouseId: number) => {
    try {
      const { wave_id } = await apiClient.createWave(warehouseId);
      setActiveWave(wave_id);
      await loadTasks();
      toast.show("موج برداشت ساخته شد.", "success");
    } catch (e) {
      toast.show(errorText(e, "ساخت موج ناموفق بود."), "danger");
    }
  };

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
      toast.show(errorText(e, "شروع وظیفه ناموفق بود."), "danger");
    }
  };

  const completeTask = async () => {
    if (!activeTask) return;
    const qty = toAsciiDigits(taskQty);
    let ok = false;
    if (activeTask.task_type === "PUTAWAY") {
      if (!putawayTarget) {
        toast.show("محل مقصد را انتخاب یا اسکن کنید.", "warning");
        return;
      }
      ok = await submit({ type: "WMS_PUTAWAY", payload: { taskId: activeTask.task_id, toLocationId: putawayTarget.id } }, "جانمایی ثبت شد.");
    } else if (activeTask.task_type === "PICK") {
      ok = await submit({ type: "WMS_PICK", payload: { taskId: activeTask.task_id, quantity: qty } }, "برداشت ثبت شد.");
    } else {
      ok = await submit({ type: "WMS_REPLENISH", payload: { taskId: activeTask.task_id, quantity: qty || null } }, "تامین مجدد ثبت شد.");
    }
    if (ok) {
      setActiveTask(null);
      await loadTasks();
    }
  };

  const submitTransfer = async () => {
    if (!transferItem || !transferFrom || !transferTo || !toAsciiDigits(transferQty)) {
      toast.show("کالا، محل مبدا، محل مقصد و مقدار را کامل کنید.", "warning");
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
    if (target === "COUNT_SERIAL" && serialKey !== null) {  // اسکنِ پشتِ‌سرِهمِ سریال‌ها؛ اسکنر باز می‌ماند
      const serial = code.trim();
      const current = countSerials[serialKey] ?? [];
      if (serial && !current.includes(serial)) setCountSerials({ ...countSerials, [serialKey]: [...current, serial] });
      return;
    }
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
        if (target === "COUNT_LOCATION") setCountLocation(picked);
        if (target === "COUNT_START") {
          const { session_id } = await apiClient.createLocationCount(loc.warehouse_id, [loc.location_id]);
          setCounts(await apiClient.listLocationCounts());
          await openCount(session_id);
          setCountLocation(picked);
          toast.show(`شمارش «${loc.code}» شروع شد.`, "success");
        }
      }
    } catch (e) {
      toast.show(errorText(e, "خواندن کد ناموفق بود."), "danger");
    }
  };

  const submitSerialCount = async (line: LocationCountLine) => {
    if (countId === null) return;
    const ok = await submit(
      {
        type: "WMS_SERIAL_COUNT",
        payload: { sessionId: countId, locationId: line.location_id, itemId: line.item_id, serialNos: countSerials[countKey(line)] ?? [] },
      },
      "سریال‌ها ثبت شد.",
    );
    if (ok) await openCount(countId);
  };

  const loadPutawaySources = async () => {
    try {
      setPutawaySources(await apiClient.listPutawaySources());
    } catch (e) {
      toast.show(errorText(e, "دریافت رسیدها ناموفق بود."), "danger");
    }
  };

  const createPutaway = async (documentId: number) => {
    try {
      const { task_ids } = await apiClient.generatePutawayTasks(documentId);
      toast.show(`${task_ids.length} وظیفهٔ جانمایی ساخته شد.`, "success");
      setPutawaySources(null);
      await loadTasks();
    } catch (e) {
      toast.show(errorText(e, "ساخت وظیفه ناموفق بود."), "danger");
    }
  };

  const printChildLabels = async (locationId: number) => {
    try {
      const labels = await apiClient.getLocationLabels(locationId);
      if (labels.length === 0) throw new ApiError(404, "محلی برای چاپ نیست.");
      await printLocationLabels(labels);
    } catch (e) {
      toast.show(errorText(e, "چاپ برچسب‌ها ناموفق بود."), "danger");
    }
  };

  const printLabel = async (locationId: number) => {
    try {
      await printLocationLabels([await apiClient.getLocationLabel(locationId)]);
    } catch (e) {
      toast.show(errorText(e, "چاپ برچسب ناموفق بود."), "danger");
    }
  };

  const renderKpis = () => (
    <View style={{ gap: spacing.sm }}>
      {kpis === null ? <EmptyState title="در حال دریافت..." /> : null}
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.sm }}>
        {kpis?.kpis.map((k) => (
          <Card key={k.code} style={{ width: "47%" }}>
            <Text style={[typography.caption, { color: colors.textSecondary }]}>{k.title}</Text>
            {text(typography.h2, k.value === null ? "—" : `${Number(k.value).toLocaleString("en-US", { maximumFractionDigits: 1 })} ${k.unit}`)}
          </Card>
        ))}
      </View>
      {kpis?.by_type.map((t) => (
        <Card key={t.type}>
          {text(typography.bodyBold, t.label)}
          <Text style={[typography.caption, { color: colors.textSecondary }]}>
            {`انجام‌شده ${t.done} · باز ${t.open}${t.avg_minutes !== null ? ` · میانگین ${t.avg_minutes} دقیقه` : ""}`}
          </Text>
        </Card>
      ))}
    </View>
  );

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
      <View style={{ flexDirection: "row", gap: spacing.xs }}>
        <Button label="چاپ برچسب" size="md" variant="ghost" fullWidth={false} onPress={() => printLabel(loc.location_id)} />
        <Button label="برچسب همهٔ زیرمحل‌ها" size="md" variant="ghost" fullWidth={false} onPress={() => printChildLabels(loc.location_id)} />
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
      <SearchBar value={query} onChangeText={setQuery} placeholder="کد/بارکد کالا یا کد/QR محل" />
      <View style={{ flexDirection: "row", gap: spacing.sm }}>
        <Button label="جستجو" size="md" fullWidth={false} loading={searching} onPress={() => runSearch(query)} />
        <Button label="اسکن" size="md" variant="secondary" fullWidth={false} onPress={() => setScanTarget("SEARCH")} />
      </View>
      {result === null ? null : result.kind === "NONE" || result.locations.length === 0 ? (
        <EmptyState title="چیزی پیدا نشد" />
      ) : (
        <>
          <Text style={[typography.captionBold, { color: colors.textSecondary }]}>
            {result.kind === "PRODUCT" ? `محل‌های کالا (${result.locations.length})` : "محل"}
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
          <Text style={[typography.captionBold, { color: colors.textSecondary }]}>محل‌های پیشنهادی</Text>
          {suggestions.length === 0 ? (
            <Text style={[typography.caption, { color: colors.textSecondary }]}>پیشنهادی نیست؛ محل مقصد را اسکن کنید.</Text>
          ) : (
            suggestions.map((s) => (
              <Card key={s.location_id} onPress={() => setPutawayTarget({ id: s.location_id, code: s.location_code })}>
                {text(typography.bodyBold, s.location_code, putawayTarget?.id === s.location_id ? { color: colors.primary } : undefined)}
                <Text style={[typography.caption, { color: colors.textSecondary }]}>{s.reasons.join("، ")}</Text>
              </Card>
            ))
          )}
          <Button label="اسکن محل مقصد" size="md" variant="secondary" onPress={() => setScanTarget("PUTAWAY_TARGET")} />
          {putawayTarget ? text(typography.body, `مقصد: ${putawayTarget.code}`) : null}
        </View>
      ) : (
        <Input label="مقدار انجام‌شده" value={taskQty} onChangeText={setTaskQty} numeric keyboardType="decimal-pad" style={{ marginTop: spacing.md }} />
      )}
      <View style={{ flexDirection: "row", gap: spacing.sm, marginTop: spacing.md }}>
        <Button label="تایید" size="md" fullWidth={false} loading={busy} onPress={completeTask} />
        <Button label="انصراف" size="md" variant="ghost" fullWidth={false} onPress={() => setActiveTask(null)} />
      </View>
    </Card>
  );

  const visibleTasks = () =>
    activeWave === null
      ? tasks
      : tasks.filter((t) => t.wave_id === activeWave).sort((a, b) => (a.wave_sequence ?? 0) - (b.wave_sequence ?? 0));

  const renderWaves = () => (
    <View style={{ gap: spacing.xs }}>
      <Text style={[typography.captionBold, { color: colors.textSecondary }]}>موج‌های برداشت (ترتیب مسیر)</Text>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.xs }}>
        <Button label="همهٔ وظایف" size="md" fullWidth={false} variant={activeWave === null ? "primary" : "secondary"} onPress={() => setActiveWave(null)} />
        {waves.map((w) => (
          <Button
            key={w.wave_id}
            label={`${w.code} (${w.done}/${w.tasks})`}
            size="md"
            fullWidth={false}
            variant={activeWave === w.wave_id ? "primary" : "secondary"}
            onPress={() => setActiveWave(w.wave_id)}
          />
        ))}
        {warehouses.map((wh) => (
          <Button key={`new-${wh.warehouse_id}`} label={`موج تازه: ${wh.name}`} size="md" variant="ghost" fullWidth={false} onPress={() => createWave(wh.warehouse_id)} />
        ))}
      </View>
    </View>
  );

  const renderCount = () => (
    <View style={{ gap: spacing.md }}>
      {countId === null ? (
        <Button label="شروع شمارش: اسکن محل/قفسه/منطقه" size="md" onPress={() => setScanTarget("COUNT_START")} />
      ) : null}
      {countId === null ? (
        counts.length === 0 ? (
          <EmptyState title="شمارش بازی نیست" description="محلی را اسکن کنید تا شمارش آن شروع شود." />
        ) : (
          counts.map((c) => (
            <Card key={c.session_id} onPress={() => openCount(c.session_id)}>
              {text(typography.bodyBold, c.code)}
              <Text style={[typography.caption, { color: colors.textSecondary }]}>{c.blind ? "شمارش کور" : "با نمایش مقدار دفتری"}</Text>
            </Card>
          ))
        )
      ) : (
        <>
          <Button label="بازگشت به فهرست شمارش‌ها" size="md" variant="ghost" fullWidth={false} onPress={() => setCountId(null)} />
          <Button label="اسکن محل" size="md" variant="secondary" onPress={() => setScanTarget("COUNT_LOCATION")} />
          {countLocation ? text(typography.bodyBold, `محل: ${countLocation.code}`) : (
            <Text style={[typography.caption, { color: colors.textSecondary }]}>محلی را اسکن یا از فهرست انتخاب کنید.</Text>
          )}
          {countLines
            .filter((ln) => countLocation === null || ln.location_id === countLocation.id)
            .map((ln) => (
              <Card key={countKey(ln)} onPress={() => setCountLocation({ id: ln.location_id, code: ln.location_code })}>
                {text(typography.body, `${ln.item_code} — ${ln.item_name}${ln.batch_no ? ` · بچ ${ln.batch_no}` : ""}`)}
                <Text style={[typography.caption, { color: colors.textSecondary }]}>
                  {ln.location_code}
                  {ln.expected !== null ? ` · دفتری ${formatAmount(ln.expected)}` : ""}
                  {ln.counted !== null ? ` · شمرده‌شده ${formatAmount(ln.counted)}` : ""}
                </Text>
                {countLocation?.id === ln.location_id && ln.serial ? (
                  <View style={{ gap: spacing.xs, marginTop: spacing.sm }}>
                    <Text style={[typography.caption, { color: colors.textSecondary }]}>
                      {`اسکن‌شده (${(countSerials[countKey(ln)] ?? []).length}): ${(countSerials[countKey(ln)] ?? []).join("، ")}`}
                    </Text>
                    <View style={{ flexDirection: "row", gap: spacing.sm }}>
                      <Button label="اسکن سریال‌ها" size="md" variant="secondary" fullWidth={false}
                        onPress={() => { setSerialKey(countKey(ln)); setScanTarget("COUNT_SERIAL"); }} />
                      <Button label="ثبت سریال‌ها" size="md" fullWidth={false} loading={busy} onPress={() => submitSerialCount(ln)} />
                    </View>
                  </View>
                ) : null}
                {countLocation?.id === ln.location_id && !ln.serial ? (
                  <View style={{ flexDirection: "row", gap: spacing.sm, alignItems: "flex-end", marginTop: spacing.sm }}>
                    <Input
                      label={`مقدار (${ln.unit})`}
                      value={countQty[countKey(ln)] ?? ""}
                      onChangeText={(v) => setCountQty({ ...countQty, [countKey(ln)]: v })}
                      numeric
                      keyboardType="decimal-pad"
                      style={{ flex: 1, marginBottom: 0 }}
                    />
                    <Button label="ثبت" size="md" fullWidth={false} loading={busy} onPress={() => submitCount(ln)} />
                  </View>
                ) : null}
              </Card>
            ))}
        </>
      )}
    </View>
  );

  const toneColor = (tone: ReturnType<typeof occupancyTone>) =>
    ({ empty: colors.surfaceAlt, low: colors.successSoft, mid: colors.warningSoft, high: colors.warning, full: colors.dangerSoft })[tone];

  const renderMap = () => {
    const width = 320 * mapZoom;
    const { rects, height } = layoutWarehouseMap(mapNodes, width);
    return (
      <View style={{ gap: spacing.md }}>
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.xs }}>
          {warehouses.map((wh) => (
            <Button key={wh.warehouse_id} label={wh.name} size="md" fullWidth={false}
              variant={mapWarehouse === wh.warehouse_id ? "primary" : "secondary"} onPress={() => loadMap(wh.warehouse_id)} />
          ))}
        </View>
        {mapWarehouse !== null ? (
          <View style={{ flexDirection: "row", gap: spacing.sm }}>
            <Button label="بزرگ‌نمایی" size="md" variant="ghost" fullWidth={false} onPress={() => setMapZoom(Math.min(4, mapZoom * 1.5))} />
            <Button label="کوچک‌نمایی" size="md" variant="ghost" fullWidth={false} onPress={() => setMapZoom(Math.max(1, mapZoom / 1.5))} />
          </View>
        ) : null}
        {mapWarehouse !== null && rects.length === 0 ? <EmptyState title="این انبار نقشه ندارد" /> : null}
        <ScrollView horizontal>
          <View style={{ width, height, direction: "ltr" }}>
            {rects.map((r) => (
              <Pressable
                key={r.locationId}
                onPress={() => apiClient.getLocation(r.locationId).then(setMapSelected).catch(() => setMapSelected(null))}
                style={{
                  position: "absolute", left: r.left, top: r.top, width: r.width, height: r.height,
                  backgroundColor: r.level === "AREA" || r.level === "AISLE" ? "transparent" : toneColor(occupancyTone(r.occupancy)),
                  borderWidth: mapSelected?.location_id === r.locationId ? 2 : 1,
                  borderColor: mapSelected?.location_id === r.locationId ? colors.primary : colors.border,
                  opacity: r.status === "ACTIVE" ? 1 : 0.4,
                }}
              />
            ))}
          </View>
        </ScrollView>
        {mapSelected ? renderLocation(mapSelected, []) : null}
      </View>
    );
  };

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
      {renderWaves()}
      <Button label="ساخت وظیفهٔ جانمایی از رسید تازه" size="md" variant="secondary" onPress={loadPutawaySources} />
      {putawaySources !== null && putawaySources.length === 0 ? <EmptyState title="رسید بی‌وظیفه‌ای نیست" /> : null}
      {(putawaySources ?? []).map((src) => (
        <Card key={src.document_id} onPress={() => createPutaway(src.document_id)}>
          {text(typography.bodyBold, `رسید ${src.document_no}`)}
          <Text style={[typography.caption, { color: colors.textSecondary }]}>
            {`${formatJalaliDate(src.document_date)}${src.open_lines !== null ? ` · ${src.open_lines} ردیف بی‌وظیفه` : ""}`}
          </Text>
        </Card>
      ))}
      {tasks.length === 0 && !loadingTasks ? <EmptyState title="وظیفهٔ بازی نیست" /> : null}
      {visibleTasks().map((t) => (
        <Card key={t.task_id}>
          <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
            {text(typography.bodyBold, `${t.wave_sequence && activeWave !== null ? `${t.wave_sequence}. ` : ""}${t.task_label} #${t.task_id}`)}
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
      {text(typography.bodyBold, "انتقال کالا بین محل‌ها")}
      <View style={{ gap: spacing.sm, marginTop: spacing.md }}>
        {text(typography.body, `کالا: ${transferItem?.label ?? "—"}`)}
        <Button label="اسکن کالا" size="md" variant="secondary" onPress={() => setScanTarget("TRANSFER_ITEM")} />
        {text(typography.body, `از محل: ${transferFrom?.code ?? "—"}`)}
        <Button label="اسکن محل مبدا" size="md" variant="secondary" onPress={() => setScanTarget("TRANSFER_FROM")} />
        {text(typography.body, `به محل: ${transferTo?.code ?? "—"}`)}
        <Button label="اسکن محل مقصد" size="md" variant="secondary" onPress={() => setScanTarget("TRANSFER_TO")} />
        <Input label="مقدار" value={transferQty} onChangeText={setTransferQty} numeric keyboardType="decimal-pad" />
        <Button label="ثبت انتقال" loading={busy} onPress={submitTransfer} />
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
        <View style={{ flexDirection: "row", gap: spacing.xs, flexWrap: "wrap" }}>
          {([
            ["SEARCH", "جستجو و اسکن"],
            ["TASKS", "وظایف"],
            ["TRANSFER", "انتقال"],
            ["COUNT", "شمارش"],
            ["MAP", "نقشه"],
            ["KPI", "خلاصه"],
          ] as [Tab, string][]).map(([key, label]) => (
            <Button key={key} label={label} size="md" fullWidth={false} variant={tab === key ? "primary" : "secondary"} onPress={() => setTab(key)} />
          ))}
        </View>
        {tab === "SEARCH"
          ? renderSearch()
          : tab === "TASKS"
            ? renderTasks()
            : tab === "TRANSFER"
              ? renderTransfer()
              : tab === "COUNT"
                ? renderCount()
                : tab === "MAP"
                  ? renderMap()
                  : renderKpis()}
      </ScrollView>
      <BarcodeScannerModal visible={scanTarget !== null} onClose={() => setScanTarget(null)} onScanned={onScanned} />
    </View>
  );
}
