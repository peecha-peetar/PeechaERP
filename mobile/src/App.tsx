import React, { useEffect, useState } from "react";
import { SafeAreaView, StyleSheet } from "react-native";
import { CustomerRow, ItemRow, VisitPlanRow } from "./api/types";
import { CaptureProvider, NullCaptureProvider } from "./capture";
import { LocationProvider, NullLocationProvider } from "./location";
import { DeliveryConfirmScreen } from "./screens/DeliveryConfirmScreen";
import { LoginScreen } from "./screens/LoginScreen";
import { OrderScreen } from "./screens/OrderScreen";
import { VisitDetailScreen } from "./screens/VisitDetailScreen";
import { VisitListScreen } from "./screens/VisitListScreen";
import { createServices } from "./services";

/** ناوبریِ حداقلی و دستی (بدونِ react-navigation) -- عمداً، تا در این
 * فازِ اسکلت‌سازی وابستگیِ نیتیوِ اضافه (react-native-screens و
 * react-native-safe-area-context) اضافه نشود که در سندباکسِ بدونِ
 * Android SDK/Xcode قابلِ‌ساخت/تست نیستند. اگر پروژه به‌سمتِ بیلدِ
 * واقعیِ اپ رفت، این بخش با react-navigation جایگزین می‌شود -- منطقِ
 * صفحه‌ها (services.ts, sync/*, api/*) بدونِ تغییر باقی می‌ماند. */
type Route =
  | { name: "LOGIN" }
  | { name: "VISIT_LIST" }
  | { name: "VISIT_DETAIL"; customer: CustomerRow; visitPlan: VisitPlanRow }
  | { name: "ORDER"; customer: CustomerRow };

interface Props {
  locationProvider?: LocationProvider;
  captureProvider?: CaptureProvider;
}

export function App({ locationProvider = new NullLocationProvider(), captureProvider = new NullCaptureProvider() }: Props) {
  const [services] = useState(() => createServices());
  const [route, setRoute] = useState<Route>({ name: "LOGIN" });
  const [items, setItems] = useState<ItemRow[]>([]);

  useEffect(() => {
    services.localCache.getPullResponse().then((cached) => {
      if (cached) setItems(cached.items);
    });
  }, [services]);

  if (route.name === "LOGIN") {
    return (
      <SafeAreaView style={styles.flex}>
        <LoginScreen
          apiClient={services.apiClient}
          onLoggedIn={async () => {
            await services.syncEngine.pull();
            const cached = await services.localCache.getPullResponse();
            setItems(cached?.items ?? []);
            setRoute({ name: "VISIT_LIST" });
          }}
        />
      </SafeAreaView>
    );
  }

  if (route.name === "VISIT_LIST") {
    return (
      <SafeAreaView style={styles.flex}>
        <VisitListScreen
          syncEngine={services.syncEngine}
          localCache={services.localCache}
          onOpenVisit={(customer, visitPlan) => setRoute({ name: "VISIT_DETAIL", customer, visitPlan })}
        />
      </SafeAreaView>
    );
  }

  if (route.name === "VISIT_DETAIL") {
    return (
      <SafeAreaView style={styles.flex}>
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

  return (
    <SafeAreaView style={styles.flex}>
      {/* warehouseId/currencyId/channelCode فعلاً ثابت‌اند -- در R133 باید
          از تنظیماتِ مسیرِ اختصاص‌یافته به ویزیتور (که در /sync/pull هنوز
          برنمی‌گردد) خوانده شوند، نه این‌جا هاردکد شوند. */}
      <OrderScreen
        customer={route.customer}
        items={items}
        channelCode="VAN_SALES"
        warehouseId={1}
        currencyId={1}
        offlineQueue={services.offlineQueue}
        onSubmitted={() => setRoute({ name: "VISIT_LIST" })}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({ flex: { flex: 1 } });

export { DeliveryConfirmScreen };
