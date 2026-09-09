import React, { useState } from "react";
import { ActivityIndicator, Button, StyleSheet, Text, TextInput, View } from "react-native";
import { ApiClient, ApiError } from "../api/client";

interface Props {
  apiClient: ApiClient;
  onLoggedIn: () => void;
}

/** صفحه‌یِ ورود -- با همان کاربرِ ERP وارد می‌شود (طبقِ تصمیمِ کاربر:
 * «حساب‌کاربری همان حساب‌کاربریِ erp باشد»)، نه یک سیستمِ کاربریِ جدا. */
export function LoginScreen({ apiClient, onLoggedIn }: Props) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleLogin = async () => {
    setError(null);
    setLoading(true);
    try {
      await apiClient.login(username.trim(), password);
      onLoggedIn();
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
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, justifyContent: "center", padding: 24 },
  title: { fontSize: 20, marginBottom: 24, textAlign: "center", writingDirection: "rtl" },
  input: { borderWidth: 1, borderColor: "#ccc", borderRadius: 6, padding: 10, marginBottom: 12, textAlign: "right", writingDirection: "rtl" },
  error: { color: "#c0392b", marginBottom: 12, textAlign: "right", writingDirection: "rtl" },
});
