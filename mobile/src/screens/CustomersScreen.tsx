import React, { useCallback, useEffect, useState } from "react";
import { FlatList, RefreshControl, Text, View } from "react-native";
import { ApiClient, ApiError } from "../api/client";
import { CustomerListRow } from "../api/types";
import { CustomerCard, EmptyState, ErrorState, SearchBar, SkeletonList } from "../components";
import { useTheme } from "../theme/ThemeProvider";

interface Props {
  apiClient: ApiClient;
  onOpenCustomer: (detailAccountId: number) => void;
  /** طبقِ استفاده‌یِ دوباره از همین صفحه برایِ تبِ «سفارش» (App.tsx):
   * تبِ سفارش هم دقیقاً همین جستجو/فهرست را می‌خواهد (چون شروعِ سفارش
   * از دکمه‌یِ «ثبتِ سفارش» در CustomerDetailScreen انجام می‌شود، نه
   * فرمِ جداگانه‌ای این‌جا) -- فقط عنوان فرق دارد تا با تبِ «مشتریان»
   * اشتباه گرفته نشود. */
  title?: string;
}

/** طبقِ اصلِ صریح («Search مشتری سریع و قابلِ‌استفاده باشد»): فیلترِ
 * سمتِ سرور با یک تاخیرِ کوتاه (debounce) تا هر کاراکتر یک درخواستِ
 * جداگانه نسازد. */
export function CustomersScreen({ apiClient, onOpenCustomer, title }: Props) {
  const { colors, spacing, typography } = useTheme();
  const [query, setQuery] = useState("");
  const [customers, setCustomers] = useState<CustomerListRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (q: string) => {
    setError(null);
    try {
      const rows = await apiClient.listCustomers(q || undefined);
      setCustomers(rows);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "دریافتِ فهرستِ مشتریان ناموفق بود.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [apiClient]);

  useEffect(() => {
    setLoading(true);
    const timer = setTimeout(() => load(query), 300);
    return () => clearTimeout(timer);
  }, [query, load]);

  return (
    <View style={{ flex: 1, backgroundColor: colors.background, padding: spacing.lg, gap: spacing.md }}>
      {title ? <Text style={[typography.h2, { color: colors.textPrimary }]}>{title}</Text> : null}
      <SearchBar value={query} onChangeText={setQuery} placeholder="جستجویِ مشتری با نام یا کد..." />
      {loading ? (
        <SkeletonList count={5} />
      ) : error ? (
        <ErrorState description={error} onRetry={() => load(query)} />
      ) : (
        <FlatList
          data={customers}
          keyExtractor={(item) => String(item.detail_account_id)}
          contentContainerStyle={{ gap: spacing.sm }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(query); }} />}
          renderItem={({ item }) => (
            <CustomerCard code={item.code} name={item.name} onPress={() => onOpenCustomer(item.detail_account_id)} />
          )}
          ListEmptyComponent={<EmptyState icon="🔍" title="مشتری‌ای پیدا نشد" description="کلیدواژه‌یِ دیگری امتحان کنید." />}
        />
      )}
    </View>
  );
}
