import React, { useEffect, useState } from "react";
import { ActivityIndicator, Button, StyleSheet, Text, TextInput, View } from "react-native";
import { ApiClient, ApiError } from "../api/client";
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

  return (
    <View style={styles.container}>
      <Text style={styles.title}>ورود به پیچا -- پخشِ سرد/گرم</Text>
      <TextInput
        style={styles.input}
        placeholder="نامِ کاربری"
        value={username}
        onChangeText={setUsername}
        autoCapitalize="none"
      />
      <TextInput
        style={styles.input}
        placeholder="رمزِ عبور"
        value={password}
        onChangeText={setPassword}
        secureTextEntry
      />
      {error !== null ? <Text style={styles.error}>{error}</Text> : null}
      {loading ? <ActivityIndicator /> : <Button title="ورود" onPress={handleLogin} disabled={!username || !password} />}

      {showServerField ? (
        <View style={styles.serverBox}>
          <TextInput
            style={styles.input}
            placeholder="آدرسِ سرور (مثلاً http://192.168.1.10:8000)"
            value={serverUrl}
            onChangeText={setServerUrl}
            autoCapitalize="none"
            keyboardType="url"
          />
          <Button title="ذخیره‌یِ آدرسِ سرور" onPress={saveServerUrl} />
        </View>
      ) : (
        <Text style={styles.serverLink} onPress={() => setShowServerField(true)}>
          آدرسِ سرور: {serverUrl}  (تغییر)
        </Text>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, justifyContent: "center", padding: 24 },
  title: { fontSize: 20, marginBottom: 24, textAlign: "center", writingDirection: "rtl" },
  input: { borderWidth: 1, borderColor: "#ccc", borderRadius: 6, padding: 10, marginBottom: 12, textAlign: "right", writingDirection: "rtl" },
  error: { color: "#c0392b", marginBottom: 12, textAlign: "right", writingDirection: "rtl" },
  serverBox: { marginTop: 24, gap: 8 },
  serverLink: { marginTop: 24, textAlign: "center", color: "#2563eb", writingDirection: "rtl" },
});
