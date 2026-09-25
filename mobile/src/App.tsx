import NetInfo from "@react-native-community/netinfo";
import { NavigationContainer, NavigatorScreenParams, useNavigation } from "@react-navigation/native";
import { createBottomTabNavigator } from "@react-navigation/bottom-tabs";
import { createNativeStackNavigator, NativeStackNavigationProp } from "@react-navigation/native-stack";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { AppState, StyleSheet } from "react-native";
import { SafeAreaProvider, SafeAreaView } from "react-native-safe-area-context";
import { CustomerRow, ItemRow, SettlementMethodRow, VisitPlanRow } from "./api/types";
import { CaptureProvider, ExpoCaptureProvider } from "./capture";
import { ExpoLocationProvider, LocationProvider } from "./location";
import { AppBar, BottomNav, BottomNavKey, EmptyState, InlineSpinner, SyncStatus, ToastProvider } from "./components";
import { CollectionListScreen } from "./screens/CollectionListScreen";
import { CollectionScreen } from "./screens/CollectionScreen";
import { CustomerAddressesScreen } from "./screens/CustomerAddressesScreen";
import { CustomerDetailScreen } from "./screens/CustomerDetailScreen";
import { CustomersScreen } from "./screens/CustomersScreen";
import { DeliveryConfirmScreen } from "./screens/DeliveryConfirmScreen";
import { HomeScreen } from "./screens/HomeScreen";
import { LoginScreen } from "./screens/LoginScreen";
import { ManagerDashboardScreen } from "./screens/ManagerDashboardScreen";
import { ModeSelectScreen } from "./screens/ModeSelectScreen";
import { NewCustomerScreen } from "./screens/NewCustomerScreen";
import { NotificationsScreen } from "./screens/NotificationsScreen";
import { PreSalesOrderScreen } from "./screens/PreSalesOrderScreen";
import { VanSalesOrderScreen } from "./screens/VanSalesOrderScreen";
import { ReportsScreen } from "./screens/ReportsScreen";
import { SettingsScreen } from "./screens/SettingsScreen";
import { VehicleSettlementScreen } from "./screens/VehicleSettlementScreen";
import { VisitDetailScreen } from "./screens/VisitDetailScreen";
import { VisitListScreen } from "./screens/VisitListScreen";
import { createServices } from "./services";
import { SignaturePadProvider, useSignaturePad } from "./signature/SignaturePadProvider";
import { applyRtlLayout, ThemeProvider, useTheme } from "./theme";

// طبقِ اصلِ صریح («Sync Status به کاربر نمایش داده شود» + «عملیاتِ
// موفق بعدِ اتصال خودکار Sync شوند»، Phase 6): بازه‌یِ تلاشِ خودکارِ
// ارسالِ صفِ آفلاین -- فقط ارسالِ صف (سبک)، نه pullِ کامل (طبقِ اصلِ
// «اطلاعاتِ غیرِضروری دوباره دانلود نشوند»؛ pull فقط با کنشِ صریحِ
// کاربر -- ورود/pull-to-refresh -- انجام می‌شود).
const AUTO_SYNC_INTERVAL_MS = 20_000;

// طبقِ اصلِ صریح («RTL فارسی صحیح باشد»): پیش از رندرِ هر UIای، یک‌بار
// در همان بارگذاریِ ماژول (نه داخلِ کامپوننت -- تغییرش نیازمندِ Reloadِ
// نیتیو است، نه رندرِ دوباره).
applyRtlLayout();

/** طبقِ R192: جایگزینیِ ناوبریِ دستیِ فازِ اسکلت‌سازی با react-navigation
 * واقعی -- حالا که اپ زیرِ Expo Go اجرا می‌شود (R187)، دیگر محدودیتِ
 * «نبودِ Android SDK/Xcode برایِ تستِ react-native-screens» وجود ندارد.
 * تبِ فعال با هک‌بردنِ اندروید حالا واقعاً کار می‌کند (قبلاً بدونِ
 * Stackِ واقعی، دکمه‌یِ برگشتِ سخت‌افزاری اثری نداشت).
 *
 * BottomNav خودش بدونِ تغییر ماند -- فقط به‌جایِ روتینگِ دستی، به‌عنوانِ
 * tabBarِ سفارشیِ MainTab.Navigator استفاده می‌شود (طبقِ همان طراحیِ
 * بصریِ قبلی، بدونِ نوارِ پیش‌فرضِ react-navigation). */
export type MainTabParamList = {
  HOME: undefined;
  VISITS: undefined;
  CUSTOMERS: undefined;
  ORDER: undefined;
  REPORTS: undefined;
  COLLECTION: undefined;
};

export type RootStackParamList = {
  Main: NavigatorScreenParams<MainTabParamList> | undefined;
  VisitDetail: { customer: CustomerRow; visitPlan: VisitPlanRow };
  OrderForm: { customer: CustomerRow };
  CustomerDetail: { detailAccountId: number };
  CustomerAddresses: { detailAccountId: number };
  NewCustomer: undefined;
  CollectPayment: { customer: CustomerRow };
  Notifications: undefined;
  Settings: undefined;
  ManagerDashboard: undefined;
  VehicleSettlement: undefined;
};

const RootStack = createNativeStackNavigator<RootStackParamList>();
const MainTab = createBottomTabNavigator<MainTabParamList>();

interface Props {
  locationProvider?: LocationProvider;
  captureProvider?: CaptureProvider;
}

export function App(props: Props) {
  return (
    <ThemeProvider>
      <SafeAreaProvider>
        <ToastProvider>
          <SignaturePadProvider>
            <AppContent {...props} />
          </SignaturePadProvider>
        </ToastProvider>
      </SafeAreaProvider>
    </ThemeProvider>
  );
}

function AppContent({ locationProvider = new ExpoLocationProvider(), captureProvider }: Props) {
  const { colors } = useTheme();
  const { requestSignature } = useSignaturePad();
  const resolvedCaptureProvider = useMemo(
    () => captureProvider ?? new ExpoCaptureProvider(requestSignature),
    [captureProvider, requestSignature],
  );
  const [services] = useState(() => createServices());
  const [loggedIn, setLoggedIn] = useState(false);
  const [items, setItems] = useState<ItemRow[]>([]);
  const [userFullName, setUserFullName] = useState("");
  const [companyName, setCompanyName] = useState("");
  const [syncStatus, setSyncStatus] = useState<SyncStatus>("IDLE");
  const [unreadCount, setUnreadCount] = useState(0);
  // طبقِ درخواستِ صریحِ کاربر («رابطِ کاربریِ موبایل برایِ پخشِ گرم و
  // سرد جدا بشه و کاربر اول برنامه انتخاب کنه -- ممکنه یک نفر روزی
  // گرم روزی سرد کار کند»): برخلافِ نسخهٔ قبلی (که این مسیر را فقط از
  // تنظیماتِ دسکتاپ می‌خواند و اگر تنظیم نشده بود کاربر رویِ «در حالِ
  // بررسیِ تنظیماتِ سفارش...» گیر می‌کرد)، حالا خودِ ویزیتور هر بار که
  // وارد اپ می‌شود (بعدِ لاگین، پیش از هر صفحهٔ دیگر) صراحتاً انتخاب
  // می‌کند -- null یعنی هنوز انتخاب نکرده (ModeSelectScreen نشان داده می‌شود).
  const [selectedMode, setSelectedMode] = useState<"VAN_SALES" | "PRE_SALES" | "COLLECTION" | null>(null);
  // مقدارِ /auth/me فقط به‌عنوانِ پیش‌فرضِ پیشنهادی در ModeSelectScreen
  // استفاده می‌شود (برجسته‌کردنِ دکمه‌یِ معمولِ همین ویزیتور) -- دیگر
  // چیزی را قفل/گیت نمی‌کند.
  const [suggestedMode, setSuggestedMode] = useState<"VAN_SALES" | "PRE_SALES" | null>(null);
  // طبقِ درخواستِ صریحِ کاربر («فروش بر اساسِ موجودیِ خودرو»، فازِ ۲):
  // فقط برایِ پخشِ گرم معنا دارد -- undefined یعنی هنوز نخوانده‌ایم.
  const [assignedVehicleWarehouseId, setAssignedVehicleWarehouseId] = useState<number | null | undefined>(undefined);
  // طبقِ درخواستِ صریحِ کاربر («تسویه آخر روز باید بصورتِ انتخابی به یک
  // نفر از ۳ نقش واگذار بشه»): اگر مقدار داشته باشد، دکمه‌یِ تسویهٔ
  // پایانِ روز در تنظیمات نشان داده می‌شود.
  const [settlementVehicleWarehouseId, setSettlementVehicleWarehouseId] = useState<number | null | undefined>(undefined);
  // طبقِ باگِ واقعیِ کشف‌شده (R196): سفارش نباید یک channel_codeِ
  // هاردکدشده/نامعتبر بفرستد -- undefined یعنی «هنوز بارگذاری‌نشده»،
  // null یعنی «بارگذاری شد ولی هیچ کانالی از این نوع در این شرکت
  // تعریف نشده».
  const [orderChannelCode, setOrderChannelCode] = useState<string | null | undefined>(undefined);
  // طبقِ باگِ واقعیِ دومِ کشف‌شده (R198، هم‌الگو با بالا): warehouse_id=1
  // در بسیاری از شرکت‌ها اصلاً وجود ندارد.
  const [defaultWarehouseId, setDefaultWarehouseId] = useState<number | null | undefined>(undefined);
  // طبقِ درخواستِ صریحِ کاربر («در تنظیماتِ موبایل مرکزِ هزینه/پروژه
  // تعیین شود»): پیش‌فرضِ ثابتِ همان کانال -- null یعنی تنظیم نشده
  // (بدونِ مرکزِ هزینه/پروژه فرستاده می‌شود، هم‌مثلِ قبل).
  const [orderCostCenterId, setOrderCostCenterId] = useState<number | null | undefined>(undefined);
  const [orderProjectId, setOrderProjectId] = useState<number | null | undefined>(undefined);
  // طبقِ درخواستِ صریحِ کاربر («نوعِ تسویه در پخشِ گرم باید همانندِ
  // انواعِ تسویه در دسکتاپ باشد»): فقط برایِ پخشِ گرم لازم است.
  const [settlementMethods, setSettlementMethods] = useState<SettlementMethodRow[]>([]);
  // طبقِ درخواستِ صریحِ کاربر («تاییدِ مشتری، داشبوردِ سرپرست»): دکمه‌هایِ
  // مدیریتی (تاییدِ مشتری) فقط برایِ سرپرست نمایش داده می‌شوند.
  const [isManager, setIsManager] = useState(false);

  useEffect(() => {
    services.localCache.getPullResponse().then((cached) => {
      if (cached) setItems(cached.items);
    });
  }, [services]);

  // طبقِ رفعِ باگِ واقعیِ گزارش‌شده («از دسکتاپ به‌عنوانِ ویزیتور به
  // خودرو وصل کردم ولی موبایل هنوز پیامِ «وصل نیستید» را نشان می‌دهد و
  // نمی‌شود ادامه داد»): قبلاً /auth/me فقط یک‌بار -- درست بعدِ لاگین --
  // خوانده می‌شد. اگر مدیر این وصل‌کردن را *بعدِ* آن لحظه (مثلاً همین
  // اپِ بازِ ویزیتور روی گوشی، در حینِ رفت‌وبرگشت به دسکتاپ) انجام دهد،
  // این مقدار تا آخرِ همان نشستِ اپ برایِ همیشه قدیمی (null) می‌ماند --
  // چون هیچ رویدادی دوباره آن را نمی‌خواند. حالا هم با برگشتِ اپ از
  // پس‌زمینه (AppState) و هم با دکمهٔ «تلاشِ دوباره» رویِ خودِ پیامِ
  // خطا (پایین‌تر) دوباره خوانده می‌شود.
  const refetchMe = useCallback(() => {
    if (!loggedIn) return;
    services.apiClient
      .getMe()
      .then((me) => {
        setSuggestedMode(me.mobile_channel_type_code);
        setAssignedVehicleWarehouseId(me.assigned_vehicle_warehouse_id);
        setSettlementVehicleWarehouseId(me.settlement_vehicle_warehouse_id);
        setIsManager(me.is_manager);
      })
      .catch(() => {
        setSuggestedMode(null);
        setAssignedVehicleWarehouseId(null);
        setSettlementVehicleWarehouseId(null);
        setIsManager(false);
      });
  }, [loggedIn, services]);

  useEffect(() => {
    refetchMe();
  }, [refetchMe]);

  useEffect(() => {
    if (!loggedIn) return;
    const subscription = AppState.addEventListener("change", (nextState) => {
      if (nextState === "active") refetchMe();
    });
    return () => subscription.remove();
  }, [loggedIn, refetchMe]);

  useEffect(() => {
    // طبقِ درخواستِ صریحِ کاربر («وصولگر فقط به دنبالِ وصول باشه»): هیچ‌کدام
    // از این‌ها (کانال/انبار/تسویه) برایِ حالتِ خالصِ وصول معنا ندارند.
    if (!loggedIn || !selectedMode || selectedMode === "COLLECTION") return;
    services.apiClient
      .listChannels(selectedMode)
      .then((channels) => {
        const channel = channels[0];
        setOrderChannelCode(channel?.channel_code ?? null);
        setOrderCostCenterId(channel?.default_cost_center_detail_account_id ?? null);
        setOrderProjectId(channel?.default_project_detail_account_id ?? null);
      })
      .catch(() => {
        setOrderChannelCode(null);
        setOrderCostCenterId(null);
        setOrderProjectId(null);
      });

    // طبقِ درخواستِ صریحِ کاربر («فروش بر اساسِ موجودیِ خودرو»، فازِ ۲):
    // پخشِ گرم دیگر از انبارِ پیش‌فرضِ شرکت نمی‌فروشد -- از انبارِ همان
    // خودرویی که این ویزیتور به آن وصل است (اگر وصل نباشد، EmptyState
    // نشان داده می‌شود، نه سقوطِ خاموش به انبارِ پیش‌فرض). پخشِ سرد
    // (سفارش، نه فاکتورِ آنی) هم‌چنان انبارِ پیش‌فرضِ شرکت را می‌گیرد.
    if (selectedMode === "VAN_SALES") {
      setDefaultWarehouseId(assignedVehicleWarehouseId ?? null);
      // طبقِ درخواستِ صریحِ کاربر («نوعِ تسویه در پخشِ گرم باید همانندِ
      // انواعِ تسویه در دسکتاپ باشد»): فقط برایِ فاکتورِ آنیِ پخشِ گرم لازم است.
      services.apiClient.listSettlementMethods().then(setSettlementMethods).catch(() => setSettlementMethods([]));
    } else {
      services.apiClient
        .listWarehouses()
        .then((warehouses) => {
          const chosen = warehouses.find((w) => w.is_default) ?? warehouses[0];
          setDefaultWarehouseId(chosen?.warehouse_id ?? null);
        })
        .catch(() => setDefaultWarehouseId(null));
    }
  }, [loggedIn, selectedMode, assignedVehicleWarehouseId, services]);

  useEffect(() => {
    if (!loggedIn) return;
    let cancelled = false;

    const refreshUnread = async () => {
      try {
        const notifs = await services.apiClient.listNotifications(true);
        if (!cancelled) setUnreadCount(notifs.length);
      } catch {
        // شکستِ شبکه در به‌روزرسانیِ شمارشِ اعلان‌ها بی‌اهمیت است -- دفعه‌یِ بعد دوباره امتحان می‌شود
      }
    };

    const tick = async () => {
      const pending = await services.offlineQueue.size();
      if (pending === 0) {
        if (!cancelled) setSyncStatus("SYNCED");
      } else {
        if (!cancelled) setSyncStatus("SYNCING");
        // طبقِ رفتارِ واقعیِ pushQueue: برایِ خطایِ شبکه (نه ۴xx) پرتاب
        // نمی‌کند -- فقط پردازشِ صف را متوقف می‌کند (succeeded/failedButKept
        // هردو خالی می‌مانند ولی صف هنوز پر است) -- این‌جا دقیقاً همان
        // حالت به‌عنوانِ «آفلاین» تشخیص داده می‌شود، نه استثنا.
        const result = await services.syncEngine.pushQueue();
        const remaining = await services.offlineQueue.size();
        if (cancelled) return;
        // طبقِ نیازِ واقعیِ کشف‌شده: قبلاً پیامِ دقیقِ خطا (result.failedButKept[].reason)
        // فقط همین‌جا در حافظه ساخته می‌شد و بلافاصله دور ریخته می‌شد --
        // کاربر برایِ فهمیدنِ چرایی مجبور بود لاگِ سرور را دستی بخواند.
        if (result.failedButKept.length > 0) {
          services.syncErrorLog.record(result.failedButKept);
        }
        if (remaining === 0) {
          setSyncStatus("SYNCED");
        } else if (result.succeeded.length === 0 && result.failedButKept.length === 0) {
          setSyncStatus("OFFLINE");
        } else if (result.failedButKept.length > 0) {
          setSyncStatus("ERROR");
        } else {
          setSyncStatus("SYNCING");
        }
      }
      await refreshUnread();
    };

    tick();
    const interval = setInterval(tick, AUTO_SYNC_INTERVAL_MS);
    // طبقِ اصلِ صریح («Sync Status به کاربر نمایش داده شود»): بدونِ
    // NetInfo، قطعیِ اتصال فقط بعدِ شکستِ یک تلاشِ واقعیِ ارسال (تا
    // AUTO_SYNC_INTERVAL_MS/۲۰ثانیه بعد) کشف می‌شد؛ این‌جا هم خودِ
    // قطعی فوری نشان داده می‌شود (بدونِ نیاز به صفِ غیرِخالی) و هم
    // برگشتِ اتصال بی‌درنگ یک تلاشِ ارسالِ تازه را شروع می‌کند (نه صبر
    // تا تیکِ بعدی).
    const unsubscribeNetInfo = NetInfo.addEventListener((state) => {
      if (cancelled) return;
      if (state.isConnected === false) {
        setSyncStatus((prev) => (prev === "SYNCED" ? prev : "OFFLINE"));
      } else if (state.isConnected === true) {
        tick();
      }
    });
    return () => {
      cancelled = true;
      clearInterval(interval);
      unsubscribeNetInfo();
    };
  }, [loggedIn, services]);

  if (!loggedIn) {
    return (
      <SafeAreaView style={styles.flex}>
        <LoginScreen
          apiClient={services.apiClient}
          kvStore={services.kvStore}
          onLoggedIn={async (loginData) => {
            setUserFullName(loginData.full_name);
            setCompanyName(loginData.company_name);
            await services.syncEngine.pull();
            const cached = await services.localCache.getPullResponse();
            setItems(cached?.items ?? []);
            setLoggedIn(true);
          }}
        />
      </SafeAreaView>
    );
  }

  // طبقِ درخواستِ صریحِ کاربر («کاربر اول برنامه انتخاب کنه پخش گرم و
  // سرد و کلاً پروسه‌هاشون جدا باشه»): این انتخاب پیش از هر صفحهٔ دیگر
  // (حتی صفحهٔ اصلی/Home) نشان داده می‌شود -- نه فقط دفنِ شده در اعماقِ
  // فرمِ سفارش.
  if (selectedMode === null) {
    return (
      <SafeAreaView style={[styles.flex, { backgroundColor: colors.background }]}>
        <ModeSelectScreen suggestedMode={suggestedMode} onSelect={setSelectedMode} />
      </SafeAreaView>
    );
  }

  return (
    <NavigationContainer>
      <RootStack.Navigator screenOptions={{ headerShown: false }}>
        <RootStack.Screen name="Main">
          {() => (
            <MainScreen
              services={services}
              userFullName={userFullName}
              syncStatus={syncStatus}
              unreadCount={unreadCount}
              selectedMode={selectedMode}
            />
          )}
        </RootStack.Screen>

        <RootStack.Screen name="VisitDetail">
          {({ route, navigation }) => (
            <SafeAreaView style={[styles.flex, { backgroundColor: colors.background }]}>
              <VisitDetailScreen
                customer={route.params.customer}
                visitPlan={route.params.visitPlan}
                offlineQueue={services.offlineQueue}
                locationProvider={locationProvider}
                captureProvider={resolvedCaptureProvider}
                onDone={() =>
                  // طبقِ درخواستِ صریحِ کاربر («وصولگر فقط به دنبالِ وصول
                  // باشه»): برایِ حالتِ خالصِ وصول، ویزیت به فرمِ سفارش
                  // ختم نمی‌شود (که اصلاً برایِ این حالت وجود ندارد).
                  selectedMode === "COLLECTION"
                    ? navigation.navigate("Main", { screen: "HOME" })
                    : navigation.navigate("OrderForm", { customer: route.params.customer })
                }
              />
            </SafeAreaView>
          )}
        </RootStack.Screen>

        <RootStack.Screen name="OrderForm">
          {({ route, navigation }) => (
            <SafeAreaView style={[styles.flex, { backgroundColor: colors.background }]}>
              {/* currencyId فعلاً ثابت است -- در فازِ بعدی باید از تنظیماتِ
                  مسیرِ اختصاص‌یافته به ویزیتور (که در /sync/pull هنوز
                  برنمی‌گردد) خوانده شود، نه این‌جا هاردکد شود. اگر این هم
                  مثلِ channelCode/warehouseId (R196/R198) برایِ یک شرکتِ
                  خاص نامعتبر باشد، همان الگو (اندپوینتِ واقعی + guard)
                  باید برایِ آن هم تکرار شود.
                  channelCode/warehouseId دیگر هاردکد نیستند (باگ‌هایِ
                  واقعیِ R196/R198: قبلاً «VAN_SALES» و «۱» مستقیم
                  فرستاده می‌شدند و سند به‌خاطرِ شکستِ کلیدِ خارجی اصلاً
                  ساخته نمی‌شد -- هردو رویِ گوشیِ فیزیکیِ کاربر تایید شد).
                  انتخابِ پخشِ گرم/سرد خودِ selectedMode است (طبقِ درخواستِ
                  صریحِ کاربر «کاربر اول برنامه انتخاب کنه») -- همیشه
                  غیرِnullِ است چون بدونِ آن اصلاً به این صفحه نمی‌رسیم.
                  customerVisitId هم فعلاً null است: شناسه‌یِ واقعیِ ویزیت
                  مثلِ document_id فقط بعدِ سینکِ موفقِ START_VISIT از
                  سرور می‌آید -- وصل‌کردنِ آن به تاییدِ تحویل (هم‌الگو با
                  resolvedDocumentId در syncEngine.ts) کارِ باقی‌ماندهٔ
                  فازِ بعد است. */}
              {orderChannelCode === undefined || defaultWarehouseId === undefined ? (
                <InlineSpinner label="در حالِ بررسیِ تنظیماتِ سفارش..." />
              ) : orderChannelCode === null ? (
                <EmptyState
                  title="کانالِ فروشِ ویزیت تعریف نشده"
                  description={
                    selectedMode === "VAN_SALES"
                      ? "مدیر باید ابتدا از دسکتاپ، در تنظیماتِ کانال‌هایِ فروش، یک کانال از نوعِ «پخشِ گرم/VAN_SALES» بسازد -- بدونِ آن، سفارش قابلِ‌ثبت نیست."
                      : "مدیر باید ابتدا از دسکتاپ، در تنظیماتِ کانال‌هایِ فروش، یک کانال از نوعِ «پخشِ سرد/PRE_SALES» بسازد -- بدونِ آن، سفارش قابلِ‌ثبت نیست."
                  }
                />
              ) : defaultWarehouseId === null ? (
                <EmptyState
                  title={selectedMode === "VAN_SALES" ? "شما به هیچ خودرویی وصل نیستید" : "هیچ انباری تعریف نشده"}
                  description={
                    selectedMode === "VAN_SALES"
                      ? "مدیر باید ابتدا از دسکتاپ، در بخشِ «پخشِ کالا / تیمِ خودرو»، شما را به‌عنوانِ «ویزیتور» به یک خودرو وصل کند -- بدونِ آن، فروش قابلِ‌ثبت نیست (فروشِ پخشِ گرم فقط از موجودیِ خودروی خودتان انجام می‌شود). اگر همین الان این کار را انجام داده‌اید، «تلاشِ دوباره» را بزنید."
                      : "مدیر باید ابتدا از دسکتاپ، حداقل یک انبار (ترجیحاً به‌عنوانِ پیش‌فرض) بسازد -- بدونِ آن، سفارش قابلِ‌ثبت نیست."
                  }
                  actionLabel="تلاشِ دوباره"
                  onPressAction={refetchMe}
                />
              ) : selectedMode === "VAN_SALES" ? (
                <VanSalesOrderScreen
                  customer={route.params.customer}
                  items={items}
                  channelCode={orderChannelCode}
                  warehouseId={defaultWarehouseId}
                  currencyId={1}
                  costCenterDetailAccountId={orderCostCenterId ?? null}
                  projectDetailAccountId={orderProjectId ?? null}
                  settlementMethods={settlementMethods}
                  customerVisitId={null}
                  companyName={companyName}
                  sellerName={userFullName}
                  apiClient={services.apiClient}
                  offlineQueue={services.offlineQueue}
                  syncEngine={services.syncEngine}
                  invoiceResults={services.invoiceResults}
                  catalogCache={services.catalogCache}
                  captureProvider={resolvedCaptureProvider}
                  locationProvider={locationProvider}
                  onSubmitted={() => navigation.navigate("Main", { screen: "ORDER" })}
                />
              ) : (
                <PreSalesOrderScreen
                  customer={route.params.customer}
                  items={items}
                  channelCode={orderChannelCode}
                  warehouseId={defaultWarehouseId}
                  currencyId={1}
                  apiClient={services.apiClient}
                  offlineQueue={services.offlineQueue}
                  onSubmitted={() => navigation.navigate("Main", { screen: "VISITS" })}
                />
              )}
            </SafeAreaView>
          )}
        </RootStack.Screen>

        <RootStack.Screen name="CustomerDetail">
          {({ route, navigation }) => (
            <SafeAreaView style={[styles.flex, { backgroundColor: colors.background }]}>
              <CustomerDetailScreen
                apiClient={services.apiClient}
                localCache={services.localCache}
                detailAccountId={route.params.detailAccountId}
                onBack={() => navigation.navigate("Main", { screen: "CUSTOMERS" })}
                onStartVisit={(customer, visitPlan) => navigation.navigate("VisitDetail", { customer, visitPlan })}
                onCreateOrder={(customer) => navigation.navigate("OrderForm", { customer })}
                onCreateCollection={(customer) => navigation.navigate("CollectPayment", { customer })}
                // طبقِ درخواستِ صریحِ کاربر («وصولگر فقط به دنبالِ وصول
                // باشه»): در حالتِ خالصِ وصول، دکمه‌هایِ ویزیت/سفارش
                // اصلاً معنا ندارند -- فقط «ثبتِ وصول» می‌ماند.
                collectionOnly={selectedMode === "COLLECTION"}
                vanSales={selectedMode === "VAN_SALES"}
                salesMode={selectedMode === "COLLECTION" ? undefined : selectedMode}
                isManager={isManager}
                onOpenAddresses={() => navigation.navigate("CustomerAddresses", { detailAccountId: route.params.detailAccountId })}
              />
            </SafeAreaView>
          )}
        </RootStack.Screen>

        <RootStack.Screen name="CustomerAddresses">
          {({ route, navigation }) => (
            <SafeAreaView style={[styles.flex, { backgroundColor: colors.background }]}>
              <CustomerAddressesScreen
                apiClient={services.apiClient}
                locationProvider={locationProvider}
                detailAccountId={route.params.detailAccountId}
                onBack={() => navigation.navigate("CustomerDetail", { detailAccountId: route.params.detailAccountId })}
              />
            </SafeAreaView>
          )}
        </RootStack.Screen>

        <RootStack.Screen name="NewCustomer">
          {({ navigation }) => (
            <SafeAreaView style={[styles.flex, { backgroundColor: colors.background }]}>
              <NewCustomerScreen
                apiClient={services.apiClient}
                offlineQueue={services.offlineQueue}
                locationProvider={locationProvider}
                captureProvider={resolvedCaptureProvider}
                localCache={services.localCache}
                onDone={() => navigation.navigate("Main", { screen: "CUSTOMERS" })}
                onOpenCustomer={(detailAccountId) => navigation.navigate("CustomerDetail", { detailAccountId })}
              />
            </SafeAreaView>
          )}
        </RootStack.Screen>

        <RootStack.Screen name="CollectPayment">
          {({ route, navigation }) => (
            <SafeAreaView style={[styles.flex, { backgroundColor: colors.background }]}>
              <CollectionScreen
                apiClient={services.apiClient}
                customer={route.params.customer}
                offlineQueue={services.offlineQueue}
                onDone={() =>
                  navigation.navigate("CustomerDetail", { detailAccountId: route.params.customer.detail_account_id })
                }
              />
            </SafeAreaView>
          )}
        </RootStack.Screen>

        <RootStack.Screen name="Notifications">
          {({ navigation }) => (
            <SafeAreaView style={[styles.flex, { backgroundColor: colors.background }]}>
              <NotificationsScreen
                apiClient={services.apiClient}
                onBack={() => navigation.navigate("Main", { screen: "HOME" })}
              />
            </SafeAreaView>
          )}
        </RootStack.Screen>

        <RootStack.Screen name="Settings">
          {({ navigation }) => (
            <SafeAreaView style={[styles.flex, { backgroundColor: colors.background }]}>
              <SettingsScreen
                apiClient={services.apiClient}
                offlineQueue={services.offlineQueue}
                syncEngine={services.syncEngine}
                syncErrorLog={services.syncErrorLog}
                userFullName={userFullName}
                onLoggedOut={() => {
                  setLoggedIn(false);
                  setSelectedMode(null);
                }}
                onChangeMode={() => setSelectedMode(null)}
                onBack={() => navigation.navigate("Main", { screen: "HOME" })}
                onOpenManagerDashboard={() => navigation.navigate("ManagerDashboard")}
                onOpenVehicleSettlement={
                  settlementVehicleWarehouseId != null ? () => navigation.navigate("VehicleSettlement") : undefined
                }
              />
            </SafeAreaView>
          )}
        </RootStack.Screen>

        <RootStack.Screen name="ManagerDashboard">
          {({ navigation }) => (
            <SafeAreaView style={[styles.flex, { backgroundColor: colors.background }]}>
              <ManagerDashboardScreen
                apiClient={services.apiClient}
                onBack={() => navigation.navigate("Main", { screen: "HOME" })}
              />
            </SafeAreaView>
          )}
        </RootStack.Screen>

        <RootStack.Screen name="VehicleSettlement">
          {({ navigation }) => (
            <SafeAreaView style={[styles.flex, { backgroundColor: colors.background }]}>
              <VehicleSettlementScreen
                apiClient={services.apiClient}
                onBack={() => navigation.navigate("Settings")}
              />
            </SafeAreaView>
          )}
        </RootStack.Screen>
      </RootStack.Navigator>
    </NavigationContainer>
  );
}

interface MainScreenProps {
  services: ReturnType<typeof createServices>;
  userFullName: string;
  syncStatus: SyncStatus;
  unreadCount: number;
  selectedMode: "VAN_SALES" | "PRE_SALES" | "COLLECTION";
}

// طبقِ رفعِ باگِ واقعی («در پخشِ گرم ویزیت معنی نداره و آیتم‌هایِ مشتری
// و فاکتور و وصول و گزارشات باید باشه و در پخشِ سرد ویزیت و مشتری و
// سفارش و وصول»): پخشِ گرم چون فروش/امضا/عکس/تسویه همه در همان لحظه‌یِ
// فاکتور اتفاق می‌افتد، دیگر نیازی به آیینِ جداگانه‌یِ «شروع/پایانِ
// ویزیت» ندارد -- برخلافِ پخشِ سرد که هنوز به همان چرخهٔ ویزیت نیاز
// دارد. تبِ «سفارش» در پخشِ گرم برچسبِ «فاکتور» می‌گیرد (labelOverrides
// پایین‌تر) چون همیشه بلافاصله فاکتورِ آنی می‌سازد، نه سفارش.
const TABS_BY_MODE: Record<"VAN_SALES" | "PRE_SALES" | "COLLECTION", BottomNavKey[]> = {
  VAN_SALES: ["HOME", "CUSTOMERS", "ORDER", "REPORTS", "COLLECTION"],
  PRE_SALES: ["HOME", "VISITS", "CUSTOMERS", "ORDER", "COLLECTION"],
  COLLECTION: ["HOME", "CUSTOMERS", "COLLECTION"],
};

function MainScreen({ services, userFullName, syncStatus, unreadCount, selectedMode }: MainScreenProps) {
  const { colors } = useTheme();
  const navigation = useNavigation<NativeStackNavigationProp<RootStackParamList>>();

  const onOpenVisit = (customer: CustomerRow, visitPlan: VisitPlanRow) =>
    navigation.navigate("VisitDetail", { customer, visitPlan });
  const onOpenCustomer = (detailAccountId: number) => navigation.navigate("CustomerDetail", { detailAccountId });

  return (
    <SafeAreaView style={[styles.flex, { backgroundColor: colors.background }]}>
      <AppBar
        userFullName={userFullName}
        syncStatus={syncStatus}
        unreadNotificationCount={unreadCount}
        onPressNotifications={() => navigation.navigate("Notifications")}
        onPressProfile={() => navigation.navigate("Settings")}
      />
      <MainTab.Navigator
        screenOptions={{ headerShown: false }}
        tabBar={(tabBarProps) => (
          <BottomNav
            active={tabBarProps.state.routeNames[tabBarProps.state.index] as BottomNavKey}
            onChange={(key) => tabBarProps.navigation.navigate(key)}
            visibleKeys={TABS_BY_MODE[selectedMode]}
            labelOverrides={selectedMode === "VAN_SALES" ? { ORDER: "فاکتور" } : undefined}
          />
        )}
      >
        <MainTab.Screen name="HOME">
          {() => (
            <HomeScreen
              apiClient={services.apiClient}
              localCache={services.localCache}
              userFullName={userFullName}
              onOpenVisit={onOpenVisit}
              hideVisitPlan={selectedMode === "VAN_SALES"}
              salesMode={selectedMode === "COLLECTION" ? undefined : selectedMode}
            />
          )}
        </MainTab.Screen>
        <MainTab.Screen name="VISITS">
          {() => (
            <VisitListScreen
              apiClient={services.apiClient}
              syncEngine={services.syncEngine}
              localCache={services.localCache}
              onOpenVisit={onOpenVisit}
            />
          )}
        </MainTab.Screen>
        <MainTab.Screen name="CUSTOMERS">
          {() => (
            <CustomersScreen
              apiClient={services.apiClient}
              onOpenCustomer={onOpenCustomer}
              title="مشتریان"
              onAddCustomer={() => navigation.navigate("NewCustomer")}
            />
          )}
        </MainTab.Screen>
        <MainTab.Screen name="ORDER">
          {() => (
            <CustomersScreen
              apiClient={services.apiClient}
              onOpenCustomer={onOpenCustomer}
              title={selectedMode === "VAN_SALES" ? "فاکتورِ جدید — انتخابِ مشتری" : "سفارشِ جدید — انتخابِ مشتری"}
            />
          )}
        </MainTab.Screen>
        <MainTab.Screen name="REPORTS">
          {() => <ReportsScreen apiClient={services.apiClient} salesMode="VAN_SALES" />}
        </MainTab.Screen>
        <MainTab.Screen name="COLLECTION">
          {() => <CollectionListScreen apiClient={services.apiClient} onOpenCustomer={onOpenCustomer} />}
        </MainTab.Screen>
      </MainTab.Navigator>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({ flex: { flex: 1 } });

export { DeliveryConfirmScreen };
