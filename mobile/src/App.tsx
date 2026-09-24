import NetInfo from "@react-native-community/netinfo";
import { NavigationContainer, NavigatorScreenParams, useNavigation } from "@react-navigation/native";
import { createBottomTabNavigator } from "@react-navigation/bottom-tabs";
import { createNativeStackNavigator, NativeStackNavigationProp } from "@react-navigation/native-stack";
import React, { useEffect, useMemo, useState } from "react";
import { StyleSheet } from "react-native";
import { SafeAreaProvider, SafeAreaView } from "react-native-safe-area-context";
import { CustomerRow, ItemRow, VisitPlanRow } from "./api/types";
import { CaptureProvider, ExpoCaptureProvider } from "./capture";
import { ExpoLocationProvider, LocationProvider } from "./location";
import { AppBar, BottomNav, BottomNavKey, EmptyState, InlineSpinner, SyncStatus, ToastProvider } from "./components";
import { CollectionListScreen } from "./screens/CollectionListScreen";
import { CollectionScreen } from "./screens/CollectionScreen";
import { CustomerDetailScreen } from "./screens/CustomerDetailScreen";
import { CustomersScreen } from "./screens/CustomersScreen";
import { DeliveryConfirmScreen } from "./screens/DeliveryConfirmScreen";
import { HomeScreen } from "./screens/HomeScreen";
import { LoginScreen } from "./screens/LoginScreen";
import { ManagerDashboardScreen } from "./screens/ManagerDashboardScreen";
import { NotificationsScreen } from "./screens/NotificationsScreen";
import { OrderScreen } from "./screens/OrderScreen";
import { SettingsScreen } from "./screens/SettingsScreen";
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
  COLLECTION: undefined;
};

export type RootStackParamList = {
  Main: NavigatorScreenParams<MainTabParamList> | undefined;
  VisitDetail: { customer: CustomerRow; visitPlan: VisitPlanRow };
  OrderForm: { customer: CustomerRow };
  CustomerDetail: { detailAccountId: number };
  CollectPayment: { customer: CustomerRow };
  Notifications: undefined;
  Settings: undefined;
  ManagerDashboard: undefined;
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
  const [syncStatus, setSyncStatus] = useState<SyncStatus>("IDLE");
  const [unreadCount, setUnreadCount] = useState(0);
  // طبقِ باگِ واقعیِ کشف‌شده (R196): سفارش نباید یک channel_codeِ
  // هاردکدشده/نامعتبر بفرستد -- undefined یعنی «هنوز بارگذاری‌نشده»،
  // null یعنی «بارگذاری شد ولی هیچ کانالِ VAN_SALES‌ای در این شرکت
  // تعریف نشده».
  const [vanSalesChannelCode, setVanSalesChannelCode] = useState<string | null | undefined>(undefined);

  useEffect(() => {
    services.localCache.getPullResponse().then((cached) => {
      if (cached) setItems(cached.items);
    });
  }, [services]);

  useEffect(() => {
    if (!loggedIn) return;
    services.apiClient
      .listChannels("VAN_SALES")
      .then((channels) => setVanSalesChannelCode(channels[0]?.channel_code ?? null))
      .catch(() => setVanSalesChannelCode(null));
  }, [loggedIn, services]);

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
            await services.syncEngine.pull();
            const cached = await services.localCache.getPullResponse();
            setItems(cached?.items ?? []);
            setLoggedIn(true);
          }}
        />
      </SafeAreaView>
    );
  }

  return (
    <NavigationContainer>
      <RootStack.Navigator screenOptions={{ headerShown: false }}>
        <RootStack.Screen name="Main">
          {() => (
            <MainScreen services={services} userFullName={userFullName} syncStatus={syncStatus} unreadCount={unreadCount} />
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
                onDone={() => navigation.navigate("OrderForm", { customer: route.params.customer })}
              />
            </SafeAreaView>
          )}
        </RootStack.Screen>

        <RootStack.Screen name="OrderForm">
          {({ route, navigation }) => (
            <SafeAreaView style={[styles.flex, { backgroundColor: colors.background }]}>
              {/* warehouseId/currencyId فعلاً ثابت‌اند -- در فازِ بعدی باید از
                  تنظیماتِ مسیرِ اختصاص‌یافته به ویزیتور (که در /sync/pull
                  هنوز برنمی‌گردد) خوانده شوند، نه این‌جا هاردکد شوند.
                  channelCode برخلافِ این دو دیگر هاردکد نیست (باگِ واقعیِ
                  R196: قبلاً «VAN_SALES» -- که یک نوعِ کانال است، نه یک
                  channel_codeِ واقعی -- مستقیم فرستاده می‌شد و سند به‌خاطرِ
                  شکستِ کلیدِ خارجی اصلاً ساخته نمی‌شد).
                  customerVisitId هم فعلاً null است: شناسه‌یِ واقعیِ ویزیت مثلِ
                  document_id فقط بعدِ سینکِ موفقِ START_VISIT از سرور می‌آید --
                  وصل‌کردنِ آن به تاییدِ تحویل (هم‌الگو با resolvedDocumentId در
                  syncEngine.ts) کارِ باقی‌ماندهٔ فازِ بعد است. */}
              {vanSalesChannelCode === undefined ? (
                <InlineSpinner label="در حالِ بررسیِ کانالِ فروش..." />
              ) : vanSalesChannelCode === null ? (
                <EmptyState
                  icon="⚠️"
                  title="کانالِ فروشِ ویزیت تعریف نشده"
                  description="مدیر باید ابتدا از دسکتاپ، در تنظیماتِ کانال‌هایِ فروش، یک کانال از نوعِ «پخشِ گرم/VAN_SALES» بسازد -- بدونِ آن، سفارش قابلِ‌ثبت نیست."
                />
              ) : (
                <OrderScreen
                  customer={route.params.customer}
                  items={items}
                  channelTypeCode="VAN_SALES"
                  channelCode={vanSalesChannelCode}
                  warehouseId={1}
                  currencyId={1}
                  customerVisitId={null}
                  apiClient={services.apiClient}
                  offlineQueue={services.offlineQueue}
                  captureProvider={resolvedCaptureProvider}
                  locationProvider={locationProvider}
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
              />
            </SafeAreaView>
          )}
        </RootStack.Screen>

        <RootStack.Screen name="CollectPayment">
          {({ route, navigation }) => (
            <SafeAreaView style={[styles.flex, { backgroundColor: colors.background }]}>
              <CollectionScreen
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
                onLoggedOut={() => setLoggedIn(false)}
                onBack={() => navigation.navigate("Main", { screen: "HOME" })}
                onOpenManagerDashboard={() => navigation.navigate("ManagerDashboard")}
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
      </RootStack.Navigator>
    </NavigationContainer>
  );
}

interface MainScreenProps {
  services: ReturnType<typeof createServices>;
  userFullName: string;
  syncStatus: SyncStatus;
  unreadCount: number;
}

function MainScreen({ services, userFullName, syncStatus, unreadCount }: MainScreenProps) {
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
            />
          )}
        </MainTab.Screen>
        <MainTab.Screen name="VISITS">
          {() => <VisitListScreen syncEngine={services.syncEngine} localCache={services.localCache} onOpenVisit={onOpenVisit} />}
        </MainTab.Screen>
        <MainTab.Screen name="CUSTOMERS">
          {() => <CustomersScreen apiClient={services.apiClient} onOpenCustomer={onOpenCustomer} title="مشتریان" />}
        </MainTab.Screen>
        <MainTab.Screen name="ORDER">
          {() => (
            <CustomersScreen
              apiClient={services.apiClient}
              onOpenCustomer={onOpenCustomer}
              title="سفارشِ جدید — انتخابِ مشتری"
            />
          )}
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
