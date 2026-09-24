// طبقِ دستورالعملِ رسمیِ react-navigation: باید همیشه اولین importِ
// کلِ اپ باشد (پیش از هر importِ دیگری، حتی expo)، وگرنه ژست‌هایِ
// ناوبری (کشیدنِ لبه برایِ برگشت) رویِ اندروید درست کار نمی‌کنند.
import "react-native-gesture-handler";
import { registerRootComponent } from "expo";
import { AppRoot } from "./src/AppRoot";

registerRootComponent(AppRoot);
