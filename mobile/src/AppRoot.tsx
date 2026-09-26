import { useFonts } from "expo-font";
import React from "react";
import { ActivityIndicator, View } from "react-native";
import { App } from "./App";

/** ریشه‌یِ واقعیِ اپ زیرِ Expo Go -- طبقِ محدودیتِ فونت‌هایِ استاتیکِ
 * سفارشی (typography.ts): در بیلدِ نیتیوِ خام، این فونت‌ها با
 * react-native.config.js به‌صورتِ فایل‌هایِ نیتیو لینک می‌شوند؛ زیرِ
 * Expo Go (که هیچ کدِ نیتیوِ سفارشی نمی‌پذیرد) باید در زمانِ اجرا با
 * expo-font بارگذاری شوند -- کلیدها باید دقیقاً همان نامِ fontFamilyِ
 * استفاده‌شده در typography.ts باشند. */
export function AppRoot() {
  const [fontsLoaded] = useFonts({
    "Vazirmatn-Regular": require("../assets/fonts/Vazirmatn-Regular.ttf"),
    "Vazirmatn-SemiBold": require("../assets/fonts/Vazirmatn-SemiBold.ttf"),
    "Vazirmatn-Bold": require("../assets/fonts/Vazirmatn-Bold.ttf"),
  });

  if (!fontsLoaded) {
    return (
      <View style={{ flex: 1, alignItems: "center", justifyContent: "center" }}>
        <ActivityIndicator size="large" />
      </View>
    );
  }

  return <App />;
}
