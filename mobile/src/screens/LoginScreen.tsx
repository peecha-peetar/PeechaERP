import React, { useEffect, useState } from "react";
import { Text, TextInput, View } from "react-native";
import { ApiClient, ApiError } from "../api/client";
import { Button } from "../components";
import { useTheme } from "../theme/ThemeProvider";
import { LoginResponse } from "../api/types";
import { KeyValueStore } from "../storage/keyValueStore";

interface Props {
  apiClient: ApiClient;
  kvStore: KeyValueStore;
  onLoggedIn: (data: LoginResponse) => void;
}

const SERVER_URL_KEY = "peecha.server_base_url";

/** صفحه‌یِ ورود -- با همان کاربرِ ERP وارد می‌شود (طبقِ تصمیمِ کاربر:
 * «حساب‌کاربری همان حساب‌کاربریِ erp باشد»)، نه یک سیستمِ کاربریِ جدا.
 *
 * طبقِ نیازِ واقعیِ اجرا رویِ گوشیِ فیزیکی (نه شبیه‌ساز/localhost): هر
 * نصب باید بتواند بدونِ بیلدِ دوباره به آدرسِ سرورِ peecha_apiِ خودش
 * (مثلاً IPِ شبکه‌یِ محلی یا دامنه‌یِ عمومی) وصل شود -- این آدرس این‌جا
 * ذخیره و رویِ apiClient اعمال می‌شود، پیش از هر تلاشِ ورود. */
export function LoginScreen({ apiClient, kvStore, onLoggedIn }: Props) {
  const { colors, spacing, radius, typography } = useTheme();
  const [serverUrl, setServerUrl] = useState(apiClient.getBaseUrl());
  const [showServerField, setShowServerField] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    kvStore.getItem(SERVER_URL_KEY).then((stored) => {
      if (stored) {
        setServerUrl(stored);
        apiClient.setBaseUrl(stored);
      }
    });
  }, [apiClient, kvStore]);

  const saveServerUrl = async () => {
    const trimmed = serverUrl.trim();
    if (!trimmed) return;
    apiClient.setBaseUrl(trimmed);
    await kvStore.setItem(SERVER_URL_KEY, trimmed);
    setShowServerField(false);
  };

  const handleLogin = async () => {
    setError(null);
    setLoading(true);
    try {
      const data = await apiClient.login(username.trim(), password);
      onLoggedIn(data);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "اتصال به سرور برقرار نشد.");
    } finally {
      setLoading(false);
    }
  };

  const inputStyle = [
    typography.body,
    {
      color: colors.textPrimary,
      backgroundColor: colors.surface,
      borderWidth: 1,
      borderColor: colors.border,
      borderRadius: radius.md,
      padding: spacing.md,
      marginBottom: spacing.md,
    },
  ];

  return (
    <View style={{ flex: 1, justifyContent: "center", padding: spacing.xl, backgroundColor: colors.background }}>
      <Text style={[typography.h2, { color: colors.textPrimary, textAlign: "center", marginBottom: spacing.xl }]}>
        ورود به پیچا -- پخشِ سرد/گرم
      </Text>
      <TextInput
        style={inputStyle}
        placeholder="نامِ کاربری"
        placeholderTextColor={colors.textSecondary}
        value={username}
        onChangeText={setUsername}
        autoCapitalize="none"
      />
      <TextInput
        style={inputStyle}
        placeholder="رمزِ عبور"
        placeholderTextColor={colors.textSecondary}
        value={password}
        onChangeText={setPassword}
        secureTextEntry
      />
      {error !== null ? <Text style={[typography.caption, { color: colors.danger, marginBottom: spacing.md }]}>{error}</Text> : null}
      <Button label="ورود" onPress={handleLogin} loading={loading} disabled={!username || !password} />

      {showServerField ? (
        <View style={{ marginTop: spacing.xl, gap: spacing.sm }}>
          <TextInput
            style={inputStyle}
            placeholder="آدرسِ سرور (مثلاً http://192.168.1.10:8000)"
            placeholderTextColor={colors.textSecondary}
            value={serverUrl}
            onChangeText={setServerUrl}
            autoCapitalize="none"
            keyboardType="url"
          />
          <Button label="ذخیره‌یِ آدرسِ سرور" variant="secondary" onPress={saveServerUrl} />
        </View>
      ) : (
        <Text
          style={[typography.caption, { color: colors.primary, textAlign: "center", marginTop: spacing.xl }]}
          onPress={() => setShowServerField(true)}
        >
          آدرسِ سرور: {serverUrl}  (تغییر)
        </Text>
      )}
    </View>
  );
}
