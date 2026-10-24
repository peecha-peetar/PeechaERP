import React, { useMemo, useState } from "react";
import { FlatList, ScrollView, Text, TouchableOpacity, View } from "react-native";
import { CatalogItem, CatalogResponse, CatalogUnit, CustomerRow } from "../../api/types";
import { BarcodeScannerModal, BottomSheet, Button, EmptyState, Input, ProductCard, SearchBar, useToast } from "../../components";
import { formatAmount, parseAmount } from "../../format";
import { useTheme } from "../../theme/ThemeProvider";
import {
  Cart, cartDiscountTotal, cartKey, cartLines, cartTaxTotal, cartTotal, defaultSalesUnit, itemBaseQuantity, itemUnits,
  resolveScannedCode, unitLabel,
} from "./cart";

interface Props {
  customer: CustomerRow;
  catalog: CatalogResponse;
  /** مثلاً «آفلاین -- کاتالوگِ ذخیره‌شده» */
  catalogNote: string | null;
  cart: Cart;
  /** در پخشِ گرم: تعداد از موجودیِ خودرو بیشتر نمی‌شود. */
  stockLimited: boolean;
  onSetQuantity: (item: CatalogItem, unit: CatalogUnit, quantity: number) => void;
  /** طبقِ درخواستِ صریحِ کاربر («مقدار و قیمت در همان حالتِ اولیه وارد
   * بشه»): تغییرِ دستیِ قیمت همین‌جا، بدونِ نیاز به رفتن به گامِ تسویه. */
  onSetPrice: (key: string, price: number | null) => void;
  onNext: () => void;
  onBack: () => void;
}

function Chip({ label, selected, onPress }: { label: string; selected: boolean; onPress: () => void }) {
  const { colors, spacing, radius, typography } = useTheme();
  return (
    <TouchableOpacity
      onPress={onPress}
      accessibilityRole="button"
      accessibilityState={{ selected }}
      style={{
        paddingHorizontal: spacing.md,
        paddingVertical: spacing.xs,
        borderRadius: radius.pill,
        backgroundColor: selected ? colors.primary : colors.surfaceAlt,
      }}
    >
      <Text style={[typography.captionBold, { color: selected ? colors.textInverse : colors.textPrimary }]}>{label}</Text>
    </TouchableOpacity>
  );
}

/** طبقِ درخواستِ صریحِ کاربر («کاتالوگِ کالا باز میشه که انواعِ فیلترها
 * روش داره -- دسته‌بندی‌ها و برند و غیره -- و امکانِ جستجویِ زنده و اسکنِ
 * بارکد از طریقِ دوربینِ موبایل»): همهٔ فیلتر/جستجو رویِ گوشی و بدونِ
 * درخواستِ شبکه انجام می‌شود (کاتالوگ یک‌جا بارگذاری/کش شده). */
export function InvoiceCatalogStep({ customer, catalog, catalogNote, cart, stockLimited, onSetQuantity, onSetPrice, onNext, onBack }: Props) {
  const { colors, spacing, typography } = useTheme();
  const toast = useToast();
  const [search, setSearch] = useState("");
  const [categoryId, setCategoryId] = useState<number | null>(null);
  const [brandId, setBrandId] = useState<number | null>(null);
  const [onlyInStock, setOnlyInStock] = useState(stockLimited);
  const [scannerOpen, setScannerOpen] = useState(false);
  const [editing, setEditing] = useState<CatalogItem | null>(null);
  const [editingQty, setEditingQty] = useState("");
  const [editingPrice, setEditingPrice] = useState("");
  // واحدِ انتخاب‌شدهٔ هر کالا رویِ کارت (پیش‌فرض: واحدِ پیش‌فرضِ فروش).
  const [selectedUnits, setSelectedUnits] = useState<Record<number, number>>({});

  const unitOf = (item: CatalogItem): CatalogUnit => {
    const units = itemUnits(item);
    const chosen = selectedUnits[item.item_id];
    return units.find((u) => u.uom_id === chosen) ?? defaultSalesUnit(item);
  };
  const lineOf = (item: CatalogItem, unit: CatalogUnit) => cart[cartKey(item.item_id, unit.uom_id)];

  const stockOf = (item: CatalogItem): number | null => (item.stock_quantity === null ? null : Number(item.stock_quantity));
  const categoryNames = useMemo(() => Object.fromEntries(catalog.categories.map((c) => [c.category_id, c.name])), [catalog]);
  const brandNames = useMemo(() => Object.fromEntries(catalog.brands.map((b) => [b.brand_id, b.name])), [catalog]);

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return catalog.items.filter((item) => {
      if (categoryId !== null && item.category_id !== categoryId) return false;
      if (brandId !== null && item.brand_id !== brandId) return false;
      if (onlyInStock && stockOf(item) !== null && stockOf(item)! <= 0 && itemBaseQuantity(cart, item.item_id) <= 0) return false;
      if (!needle) return true;
      return (
        item.name.toLowerCase().includes(needle) ||
        item.code.toLowerCase().includes(needle) ||
        (item.barcode ?? "").toLowerCase().includes(needle) ||
        (item.sku ?? "").toLowerCase().includes(needle) ||
        (item.units ?? []).some((u) => u.barcodes.some((b) => b.toLowerCase().includes(needle)))
      );
    });
  }, [catalog, search, categoryId, brandId, onlyInStock, cart]);

  /** موجودی به واحدِ پایه است: جمعِ (مقدار × ضریب) همهٔ واحدهایِ همین کالا
   * در سبد نباید از آن بیشتر شود. */
  const setQuantity = (item: CatalogItem, unit: CatalogUnit, requested: number): boolean => {
    const stock = stockOf(item);
    const factor = Number(unit.factor) || 1;
    let quantity = Math.max(0, requested);
    if (!unit.allow_decimal) quantity = Math.floor(quantity);
    if (stockLimited && stock !== null) {
      const others = itemBaseQuantity(cart, item.item_id, cartKey(item.item_id, unit.uom_id));
      const maxForUnit = Math.max(0, Math.floor(((stock - others) / factor) * 1e6) / 1e6);
      if (quantity > maxForUnit) {
        const allowed = unit.allow_decimal ? maxForUnit : Math.floor(maxForUnit);
        toast.show(
          `موجودی خودرو برای «${item.name}» فقط ${formatAmount(String(stock))} ${item.base_uom_code} است` +
            (factor !== 1 ? ` (حداکثر ${formatAmount(String(allowed))} ${unit.name}).` : "."),
          "warning",
        );
        onSetQuantity(item, unit, allowed);
        return false;
      }
    }
    onSetQuantity(item, unit, quantity);
    return true;
  };

  const onScanned = (code: string) => {
    const match = resolveScannedCode(catalog.items, code);
    if (!match) {
      toast.show(`کالایی با بارکد ${code.trim()} پیدا نشد.`, "danger");
      return;
    }
    const { item, unit } = match;
    setSelectedUnits((prev) => ({ ...prev, [item.item_id]: unit.uom_id }));
    const next = (lineOf(item, unit)?.quantity ?? 0) + 1;
    if (setQuantity(item, unit, next)) {
      toast.show(`${item.name} -- ${formatAmount(String(next))} ${unit.name}`, "success");
    }
  };

  const lines = cartLines(cart);
  const total = cartTotal(cart);
  const discount = cartDiscountTotal(cart);
  const tax = cartTaxTotal(cart);

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <View style={{ padding: spacing.lg, paddingBottom: spacing.sm, gap: spacing.sm }}>
        <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
          <Text style={[typography.h3, { color: colors.textPrimary, flex: 1 }]} numberOfLines={1}>
            فاکتور -- {customer.name}
          </Text>
          <Button label="بازگشت" variant="ghost" fullWidth={false} onPress={onBack} />
        </View>
        {catalogNote ? <Text style={[typography.caption, { color: colors.warning }]}>{catalogNote}</Text> : null}
        <View style={{ flexDirection: "row", gap: spacing.sm, alignItems: "center" }}>
          <View style={{ flex: 1 }}>
            <SearchBar value={search} onChangeText={setSearch} placeholder="جستجو: نام، کد، بارکد..." />
          </View>
          <Button label="اسکن بارکد" variant="secondary" fullWidth={false} onPress={() => setScannerOpen(true)} />
        </View>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: spacing.xs }}>
          <Chip label={onlyInStock ? "فقط موجود" : "همه (حتی ناموجود)"} selected={onlyInStock} onPress={() => setOnlyInStock((v) => !v)} />
          {catalog.categories.length > 0 ? <Chip label="همهٔ دسته‌ها" selected={categoryId === null} onPress={() => setCategoryId(null)} /> : null}
          {catalog.categories.map((c) => (
            <Chip key={`c${c.category_id}`} label={c.name} selected={categoryId === c.category_id} onPress={() => setCategoryId(categoryId === c.category_id ? null : c.category_id)} />
          ))}
        </ScrollView>
        {catalog.brands.length > 0 ? (
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: spacing.xs }}>
            <Chip label="همهٔ برندها" selected={brandId === null} onPress={() => setBrandId(null)} />
            {catalog.brands.map((b) => (
              <Chip key={`b${b.brand_id}`} label={b.name} selected={brandId === b.brand_id} onPress={() => setBrandId(brandId === b.brand_id ? null : b.brand_id)} />
            ))}
          </ScrollView>
        ) : null}
      </View>

      <FlatList
        data={filtered}
        keyExtractor={(item) => String(item.item_id)}
        contentContainerStyle={{ paddingHorizontal: spacing.lg, paddingBottom: spacing.lg, gap: spacing.sm }}
        keyboardShouldPersistTaps="handled"
        renderItem={({ item }) => {
          const units = itemUnits(item);
          const unit = unitOf(item);
          const line = lineOf(item, unit);
          const otherLines = units
            .filter((u) => u.uom_id !== unit.uom_id)
            .map((u) => ({ u, l: lineOf(item, u) }))
            .filter(({ l }) => l && l.quantity > 0);
          const meta = [item.category_id ? categoryNames[item.category_id] : null, item.brand_id ? brandNames[item.brand_id] : null]
            .filter(Boolean)
            .join(" · ");
          return (
            <ProductCard
              code={meta ? `${item.code} · ${meta}` : item.code}
              name={item.name}
              uomLabel={unitLabel(unit)}
              photoBase64={item.photo_base64}
              stockQuantity={item.stock_quantity !== null ? formatAmount(item.stock_quantity) : undefined}
              unitPrice={line?.unitPrice ? formatAmount(String(line.unitPrice)) : undefined}
              quantity={line?.quantity ?? 0}
              onIncrease={() => setQuantity(item, unit, (line?.quantity ?? 0) + 1)}
              onDecrease={() => setQuantity(item, unit, (line?.quantity ?? 0) - 1)}
              footer={
                units.length > 1 ? (
                  <View style={{ gap: spacing.xs }}>
                    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: spacing.xs }}>
                      {units.map((u) => (
                        <Chip
                          key={`u${u.uom_id}`}
                          label={unitLabel(u)}
                          selected={u.uom_id === unit.uom_id}
                          onPress={() => setSelectedUnits((prev) => ({ ...prev, [item.item_id]: u.uom_id }))}
                        />
                      ))}
                    </ScrollView>
                    {otherLines.length > 0 ? (
                      <Text style={[typography.caption, { color: colors.textSecondary }]}>
                        در سبد: {otherLines.map(({ u, l }) => `${formatAmount(String(l!.quantity))} ${u.name}`).join("، ")}
                      </Text>
                    ) : null}
                  </View>
                ) : undefined
              }
              onPress={() => {
                setEditing(item);
                setEditingQty(line?.quantity ? String(line.quantity) : "");
                setEditingPrice(line?.unitPrice ? String(line.unitPrice) : "");
              }}
            />
          );
        }}
        ListEmptyComponent={<EmptyState title="کالایی پیدا نشد" description="فیلتر یا عبارت جستجو را تغییر دهید." />}
      />

      <View style={{ padding: spacing.lg, borderTopWidth: 1, borderTopColor: colors.border, backgroundColor: colors.surface, gap: spacing.sm }}>
        <Text style={[typography.bodyBold, { color: colors.textPrimary }]}>
          سبد: {lines.length} قلم — جمع: {formatAmount(String(total))}
        </Text>
        {discount > 0 || tax > 0 ? (
          <Text style={[typography.caption, { color: colors.textSecondary }]}>
            {discount > 0 ? `تخفیف: ${formatAmount(String(discount))}` : ""}
            {discount > 0 && tax > 0 ? " -- " : ""}
            {tax > 0 ? `مالیات ارزش‌افزوده: ${formatAmount(String(tax))}` : ""}
          </Text>
        ) : null}
        <Button label="ادامه: تسویه" onPress={onNext} disabled={lines.length === 0} />
      </View>

      <BottomSheet visible={editing !== null} onClose={() => setEditing(null)} title={editing?.name}>
        <Input
          label={editing ? `تعداد (${unitOf(editing).name})` : "تعداد"}
          value={editingQty}
          onChangeText={setEditingQty}
          keyboardType="numeric"
          numeric
          autoFocus
        />
        <Input
          label="قیمت واحد"
          value={editingPrice}
          onChangeText={setEditingPrice}
          keyboardType="numeric"
          numeric
          placeholder={editing && lineOf(editing, unitOf(editing))?.unitPrice === null ? "در حال دریافت قیمت..." : undefined}
        />
        <Button
          label="تایید"
          onPress={() => {
            if (editing) {
              const unit = unitOf(editing);
              setQuantity(editing, unit, parseAmount(editingQty));
              if (editingPrice.trim()) onSetPrice(cartKey(editing.item_id, unit.uom_id), parseAmount(editingPrice));
            }
            setEditing(null);
          }}
        />
      </BottomSheet>

      <BarcodeScannerModal visible={scannerOpen} onClose={() => setScannerOpen(false)} onScanned={onScanned} />
    </View>
  );
}
