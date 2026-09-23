import React, { useEffect, useState } from "react";
import { SafeAreaView, StyleSheet, View } from "react-native";
import { CustomerRow, ItemRow, VisitPlanRow } from "./api/types";
import { CaptureProvider, ExpoCaptureProvider } from "./capture";
import { ExpoLocationProvider, LocationProvider } from "./location";
import { AppBar, BottomNav, BottomNavKey, EmptyState, SyncStatus, ToastProvider } from "./components";
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

/** ناوبریِ حداقلی و دستی (بدونِ react-navigation) -- عمداً، تا در این
 * فازِ اسکلت‌سازی وابستگیِ نیتیوِ اضافه (react-native-screens و
 * react-native-safe-area-context) اضافه نشود که در سندباکسِ بدونِ
 * Android SDK/Xcode قابلِ‌ساخت/تست نیستند. اگر پروژه به‌سمتِ بیلدِ
 * واقعیِ اپ رفت، این بخش با react-navigation جایگزین می‌شود -- منطقِ
 * صفحه‌ها (services.ts, sync/*, api/*) بدونِ تغییر باقی می‌ماند.
 *
 * UI-1: بعدِ ورود، اپ همیشه رویِ یکی از ۵ تبِ BottomNav است (MAIN)؛
 * بازکردنِ یک ویزیت/سفارش همان یک‌روتِ تمام‌صفحه‌یِ قبلی را جایگزین
 * می‌کند (نه یک Stack) و با بستن، به همان تبِ MAIN برمی‌گردد. */
type Route =
  | { name: "LOGIN" }
  | { name: "MAIN"; tab: BottomNavKey }
  | { name: "VISIT_DETAIL"; customer: CustomerRow; visitPlan: VisitPlanRow }
  | { name: "ORDER"; customer: CustomerRow }
  | { name: "CUSTOMER_DETAIL"; detailAccountId: number }
  | { name: "COLLECT_PAYMENT"; customer: CustomerRow }
  | { name: "NOTIFICATIONS" }
  | { name: "SETTINGS" }
  | { name: "MANAGER_DASHBOARD" };

interface Props {
  locationProvider?: LocationProvider;
  captureProvider?: CaptureProvider;
}

export function App(props: Props) {
  return (
    <ThemeProvider>
      <ToastProvider>
        <AppContent {...props} />
      </ToastProvider>
    </ThemeProvider>
  );
}

function AppContent({ locationProvider = new ExpoLocationProvider(), captureProvider = new ExpoCaptureProvider() }: Props) {
  const { colors } = useTheme();
  const [services] = useState(() => createServices());
  const [route, setRoute] = useState<Route>({ name: "LOGIN" });
  const [items, setItems] = useState<ItemRow[]>([]);
  const [userFullName, setUserFullName] = useState("");
  const [syncStatus, setSyncStatus] = useState<SyncStatus>("IDLE");
  const [unreadCount, setUnreadCount] = useState(0);

  useEffect(() => {
    services.localCache.getPullResponse().then((cached) => {
      if (cached) setItems(cached.items);
    });
  }, [services]);

  const loggedIn = route.name !== "LOGIN";
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
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [loggedIn, services]);

  if (route.name === "LOGIN") {
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
            setRoute({ name: "MAIN", tab: "HOME" });
          }}
        />
      </SafeAreaView>
    );
  }

  if (route.name === "VISIT_DETAIL") {
    return (
      <SafeAreaView style={[styles.flex, { backgroundColor: colors.background }]}>
        <VisitDetailScreen
          customer={route.customer}
          visitPlan={route.visitPlan}
          offlineQueue={services.offlineQueue}
          locationProvider={locationProvider}
          onDone={() => setRoute({ name: "ORDER", customer: route.customer })}
        />
      </SafeAreaView>
    );
  }

  if (route.name === "ORDER") {
    return (
      <SafeAreaView style={[styles.flex, { backgroundColor: colors.background }]}>
        {/* warehouseId/currencyId/channelCode فعلاً ثابت‌اند -- در فازِ بعدی
            باید از تنظیماتِ مسیرِ اختصاص‌یافته به ویزیتور (که در /sync/pull
            هنوز برنمی‌گردد) خوانده شوند، نه این‌جا هاردکد شوند.
            customerVisitId هم فعلاً null است: شناسه‌یِ واقعیِ ویزیت مثلِ
            document_id فقط بعدِ سینکِ موفقِ START_VISIT از سرور می‌آید --
            وصل‌کردنِ آن به تاییدِ تحویل (هم‌الگو با resolvedDocumentId در
            syncEngine.ts) کارِ باقی‌ماندهٔ فازِ بعد است. */}
        <OrderScreen
          customer={route.customer}
          items={items}
          channelCode="VAN_SALES"
          warehouseId={1}
          currencyId={1}
          customerVisitId={null}
          apiClient={services.apiClient}
          offlineQueue={services.offlineQueue}
          captureProvider={captureProvider}
          locationProvider={locationProvider}
          onSubmitted={() => setRoute({ name: "MAIN", tab: "VISITS" })}
        />
      </SafeAreaView>
    );
  }

  if (route.name === "CUSTOMER_DETAIL") {
    return (
      <SafeAreaView style={[styles.flex, { backgroundColor: colors.background }]}>
        <CustomerDetailScreen
          apiClient={services.apiClient}
          localCache={services.localCache}
          detailAccountId={route.detailAccountId}
          onBack={() => setRoute({ name: "MAIN", tab: "CUSTOMERS" })}
          onStartVisit={(customer, visitPlan) => setRoute({ name: "VISIT_DETAIL", customer, visitPlan })}
          onCreateOrder={(customer) => setRoute({ name: "ORDER", customer })}
          onCreateCollection={(customer) => setRoute({ name: "COLLECT_PAYMENT", customer })}
        />
      </SafeAreaView>
    );
  }

  if (route.name === "COLLECT_PAYMENT") {
    return (
      <SafeAreaView style={[styles.flex, { backgroundColor: colors.background }]}>
        <CollectionScreen
          customer={route.customer}
          offlineQueue={services.offlineQueue}
          onDone={() => setRoute({ name: "CUSTOMER_DETAIL", detailAccountId: route.customer.detail_account_id })}
        />
      </SafeAreaView>
    );
  }

  if (route.name === "NOTIFICATIONS") {
    return (
      <SafeAreaView style={[styles.flex, { backgroundColor: colors.background }]}>
        <NotificationsScreen apiClient={services.apiClient} onBack={() => setRoute({ name: "MAIN", tab: "HOME" })} />
      </SafeAreaView>
    );
  }

  if (route.name === "SETTINGS") {
    return (
      <SafeAreaView style={[styles.flex, { backgroundColor: colors.background }]}>
        <SettingsScreen
          apiClient={services.apiClient}
          userFullName={userFullName}
          onLoggedOut={() => setRoute({ name: "LOGIN" })}
          onBack={() => setRoute({ name: "MAIN", tab: "HOME" })}
          onOpenManagerDashboard={() => setRoute({ name: "MANAGER_DASHBOARD" })}
        />
      </SafeAreaView>
    );
  }

  if (route.name === "MANAGER_DASHBOARD") {
    return (
      <SafeAreaView style={[styles.flex, { backgroundColor: colors.background }]}>
        <ManagerDashboardScreen apiClient={services.apiClient} onBack={() => setRoute({ name: "MAIN", tab: "HOME" })} />
      </SafeAreaView>
    );
  }

  const activeTab = route.tab;
  return (
    <SafeAreaView style={[styles.flex, { backgroundColor: colors.background }]}>
      <AppBar
        userFullName={userFullName}
        syncStatus={syncStatus}
        unreadNotificationCount={unreadCount}
        onPressNotifications={() => setRoute({ name: "NOTIFICATIONS" })}
        onPressProfile={() => setRoute({ name: "SETTINGS" })}
      />
      <View style={styles.flex}>
        <MainTabContent
          tab={activeTab}
          services={services}
          userFullName={userFullName}
          onOpenVisit={(customer, visitPlan) => setRoute({ name: "VISIT_DETAIL", customer, visitPlan })}
          onOpenCustomer={(detailAccountId) => setRoute({ name: "CUSTOMER_DETAIL", detailAccountId })}
        />
      </View>
      <BottomNav active={activeTab} onChange={(tab) => setRoute({ name: "MAIN", tab })} />
    </SafeAreaView>
  );
}

interface MainTabContentProps {
  tab: BottomNavKey;
  services: ReturnType<typeof createServices>;
  userFullName: string;
  onOpenVisit: (customer: CustomerRow, visitPlan: VisitPlanRow) => void;
  onOpenCustomer: (detailAccountId: number) => void;
}

function MainTabContent({ tab, services, userFullName, onOpenVisit, onOpenCustomer }: MainTabContentProps) {
  switch (tab) {
    case "HOME":
      return (
        <HomeScreen
          apiClient={services.apiClient}
          localCache={services.localCache}
          userFullName={userFullName}
          onOpenVisit={onOpenVisit}
        />
      );
    case "VISITS":
      return (
        <VisitListScreen syncEngine={services.syncEngine} localCache={services.localCache} onOpenVisit={onOpenVisit} />
      );
    case "CUSTOMERS":
      return <CustomersScreen apiClient={services.apiClient} onOpenCustomer={onOpenCustomer} />;
    case "ORDER":
      return <ComingSoon icon="🛒" title="سفارش‌ها" />;
    case "COLLECTION":
      return <CollectionListScreen apiClient={services.apiClient} onOpenCustomer={onOpenCustomer} />;
    default:
      return null;
  }
}

function ComingSoon({ icon, title }: { icon: string; title: string }) {
  return (
    <EmptyState icon={icon} title={title} description="این بخش در فازِ بعدیِ توسعه (UI-2 تا UI-5) اضافه می‌شود." />
  );
}

const styles = StyleSheet.create({ flex: { flex: 1 } });

export { DeliveryConfirmScreen };
