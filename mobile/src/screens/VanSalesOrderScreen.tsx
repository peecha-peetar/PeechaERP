import React, { useCallback, useEffect, useState } from "react";
import { View } from "react-native";
import { ApiClient } from "../api/client";
import {
  BankRow, CatalogItem, CatalogResponse, CustomerRow, InvoicePrintData, ItemRow, OrderLineInput,
  OrderSettlementLineInput, SettlementMethodRow,
} from "../api/types";
import { CaptureProvider } from "../capture";
import { InlineSpinner, useToast } from "../components";
import { LocationProvider } from "../location";
import { CatalogCache } from "../storage/catalogCache";
import { InvoiceResultStore } from "../sync/invoiceResults";
import { OfflineQueue } from "../sync/offlineQueue";
import { SyncEngine } from "../sync/syncEngine";
import { useTheme } from "../theme/ThemeProvider";
import { buildLocalPrintData, Cart, cartLines } from "./invoice/cart";
import { InvoiceCatalogStep } from "./invoice/InvoiceCatalogStep";
import { InvoiceReceiptStep } from "./invoice/InvoiceReceiptStep";
import { InvoiceSettlementStep } from "./invoice/InvoiceSettlementStep";

interface Props {
  customer: CustomerRow;
  /** فهرستِ کالایِ /sync/pull -- فقط وقتی هیچ کاتالوگی (نه از سرور، نه
   * از کش) در دسترس نیست استفاده می‌شود (بدونِ دسته/برند/موجودی). */
  items: ItemRow[];
  /** طبقِ باگِ واقعیِ کشف‌شده (R196): channel_codeِ واقعیِ تعریف‌شده در
   * comm.channelsِ همین شرکت (مثلِ «VAN-1»). */
  channelCode: string;
  /** انبارِ خودرویِ همین ویزیتور. */
  warehouseId: number;
  currencyId: number;
  costCenterDetailAccountId: number | null;
  projectDetailAccountId: number | null;
  settlementMethods: SettlementMethodRow[];
  customerVisitId: number | null;
  companyName: string;
  sellerName: string;
  apiClient: ApiClient;
  offlineQueue: OfflineQueue;
  syncEngine: SyncEngine;
  invoiceResults: InvoiceResultStore;
  catalogCache: CatalogCache;
  captureProvider: CaptureProvider;
  locationProvider: LocationProvider;
  onSubmitted: () => void;
}

type Step = "CATALOG" | "SETTLEMENT" | "RECEIPT";

function catalogFromPull(items: ItemRow[]): CatalogResponse {
  return {
    items: items.map((it) => ({
      item_id: it.item_id, code: it.code, name: it.name, barcode: null, sku: null, category_id: null, brand_id: null,
      base_uom_id: it.base_uom_id, base_uom_code: it.base_uom_code, default_tax_percent: null, stock_quantity: null,
    })),
    categories: [],
    brands: [],
  };
}

/** طبقِ درخواستِ صریحِ کاربر («روشِ ثبتِ فاکتور: مشتری انتخاب میشه،
 * کاتالوگِ کالا باز میشه... با انتخابِ کالاها و تایید، قسمتِ تسویه بیاد...
 * و در ادامه پرینتِ فاکتور و فایلِ pdf»): سه گامِ پشتِ‌سرِهم در همین
 * صفحه -- کاتالوگ/سبد، تسویه، رسید/چاپ. ثبتِ نهایی همچنان یک اقدامِ
 * ترکیبیِ صفِ آفلاین است (CREATE_VAN_SALE_DELIVERY: فاکتور + رسیدِ تحویل)
 * تا فروش در نبودِ اینترنت هم گم نشود. */
export function VanSalesOrderScreen(props: Props) {
  const {
    customer, items, channelCode, warehouseId, currencyId, costCenterDetailAccountId, projectDetailAccountId,
    settlementMethods, customerVisitId, companyName, sellerName, apiClient, offlineQueue, syncEngine, invoiceResults,
    catalogCache, captureProvider, locationProvider, onSubmitted,
  } = props;
  const { colors } = useTheme();
  const toast = useToast();
  const [step, setStep] = useState<Step>("CATALOG");
  const [catalog, setCatalog] = useState<CatalogResponse | null>(null);
  const [catalogNote, setCatalogNote] = useState<string | null>(null);
  const [banks, setBanks] = useState<BankRow[]>([]);
  const [cart, setCart] = useState<Cart>({});
  const [submitting, setSubmitting] = useState(false);
  const [receipt, setReceipt] = useState<{ actionKey: string; printData: InvoicePrintData } | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const fresh = await apiClient.getCatalog(warehouseId);
        await catalogCache.saveCatalog(warehouseId, fresh);
        if (!cancelled) setCatalog(fresh);
      } catch {
        const cached = await catalogCache.getCatalog(warehouseId);
        if (cancelled) return;
        if (cached) {
          setCatalog(cached);
          setCatalogNote("اتصال به سرور برقرار نشد -- کاتالوگ و موجودیِ ذخیره‌شدهٔ آخرین همگام‌سازی نمایش داده می‌شود.");
        } else {
          setCatalog(catalogFromPull(items));
          setCatalogNote("کاتالوگِ کامل هنوز دریافت نشده -- فیلترِ دسته/برند و موجودیِ خودرو پس از اتصال نمایش داده می‌شود.");
        }
      }
      try {
        const freshBanks = await apiClient.listBanks();
        await catalogCache.saveBanks(freshBanks);
        if (!cancelled) setBanks(freshBanks);
      } catch {
        const cachedBanks = await catalogCache.getBanks();
        if (!cancelled) setBanks(cachedBanks);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [apiClient, catalogCache, items, warehouseId]);

  const resolvePrice = useCallback(
    async (item: CatalogItem, quantity: number): Promise<number | null> => {
      try {
        const resolved = await apiClient.resolvePrice({
          counterpartyDetailAccountId: customer.detail_account_id,
          itemId: item.item_id,
          uomId: item.base_uom_id,
          quantity: String(quantity),
          documentTypeCode: "SALES_INVOICE",
        });
        return Number(resolved.unit_price);
      } catch {
        return null;
      }
    },
    [apiClient, customer.detail_account_id],
  );

  const setQuantity = (item: CatalogItem, quantity: number) => {
    const isNew = !cart[item.item_id];
    setCart((prev) => {
      if (quantity <= 0) {
        const { [item.item_id]: _removed, ...rest } = prev;
        return rest;
      }
      return { ...prev, [item.item_id]: { item, quantity, unitPrice: prev[item.item_id]?.unitPrice ?? null, manualPrice: prev[item.item_id]?.manualPrice } };
    });
    if (isNew && quantity > 0) {
      resolvePrice(item, quantity).then((price) => {
        if (price === null) return;
        setCart((prev) => (prev[item.item_id] && !prev[item.item_id].manualPrice ? { ...prev, [item.item_id]: { ...prev[item.item_id], unitPrice: price } } : prev));
      });
    }
  };

  const goToSettlement = async () => {
    // قیمتِ پلکانی به تعداد وابسته است -- با تعدادِ نهایی دوباره گرفته می‌شود
    // (قیمتِ دستیِ ویزیتور دست‌نخورده می‌ماند).
    const lines = cartLines(cart).filter((l) => !l.manualPrice);
    const prices = await Promise.all(lines.map((l) => resolvePrice(l.item, l.quantity)));
    setCart((prev) => {
      const next = { ...prev };
      lines.forEach((l, i) => {
        if (prices[i] !== null && next[l.item.item_id]) next[l.item.item_id] = { ...next[l.item.item_id], unitPrice: prices[i] };
      });
      return next;
    });
    setStep("SETTLEMENT");
  };

  const changePrice = (itemId: number, price: number | null) =>
    setCart((prev) => (prev[itemId] ? { ...prev, [itemId]: { ...prev[itemId], unitPrice: price, manualPrice: true } } : prev));

  const submit = async (settlementLines: OrderSettlementLineInput[], receivedByName: string) => {
    const lines = cartLines(cart);
    const orderLines: OrderLineInput[] = lines.map((l) => ({
      item_id: l.item.item_id,
      uom_id: l.item.base_uom_id,
      quantity: String(l.quantity),
      unit_price: String(l.unitPrice ?? 0),
    }));
    const order = {
      document_type_code: "SALES_INVOICE" as const,
      counterparty_detail_account_id: customer.detail_account_id,
      warehouse_id: warehouseId,
      channel_code: channelCode,
      currency_id: currencyId,
      lines: orderLines,
      post_immediately: true,
      cost_center_detail_account_id: costCenterDetailAccountId,
      project_detail_account_id: projectDetailAccountId,
      settlement_lines: settlementLines,
    };
    setSubmitting(true);
    try {
      // طبقِ باگِ واقعیِ R191: امضا (Modalِ درون‌اپ) باید اول و تنها اجرا
      // شود؛ دوربین/GPS بعد از بستنِ آن.
      const signature = await captureProvider.captureSignature();
      const [photo, position] = await Promise.all([captureProvider.capturePhoto(), locationProvider.getCurrentPosition()]);
      const action = await offlineQueue.enqueue({
        type: "CREATE_VAN_SALE_DELIVERY",
        payload: {
          order,
          delivery: {
            customer_visit_id: customerVisitId,
            received_by_name: receivedByName || null,
            signature_base64: signature,
            photo_base64: photo,
            gps_latitude: position?.latitude ?? null,
            gps_longitude: position?.longitude ?? null,
            notes: null,
          },
        },
      });
      const updatedCatalog = await catalogCache.deductStock(
        warehouseId,
        Object.fromEntries(lines.map((l) => [l.item.item_id, l.quantity])),
      );
      if (updatedCatalog) setCatalog(updatedCatalog);
      setReceipt({
        actionKey: action.idempotencyKey,
        printData: buildLocalPrintData({ companyName, sellerName, customer, cart, settlementLines, methods: settlementMethods }),
      });
      setCart({});
      setStep("RECEIPT");
    } catch {
      toast.show("ثبتِ فاکتور انجام نشد -- دوباره تلاش کنید.", "danger");
    } finally {
      setSubmitting(false);
    }
  };

  if (catalog === null) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.background }}>
        <InlineSpinner label="در حالِ بارگذاریِ کاتالوگ..." />
      </View>
    );
  }

  if (step === "RECEIPT" && receipt) {
    return (
      <InvoiceReceiptStep
        actionKey={receipt.actionKey}
        localPrintData={receipt.printData}
        apiClient={apiClient}
        syncEngine={syncEngine}
        invoiceResults={invoiceResults}
        onNewInvoice={onSubmitted}
      />
    );
  }

  if (step === "SETTLEMENT") {
    return (
      <InvoiceSettlementStep
        customer={customer}
        cart={cart}
        methods={settlementMethods}
        banks={banks}
        submitting={submitting}
        onChangePrice={changePrice}
        onBack={() => setStep("CATALOG")}
        onSubmit={submit}
      />
    );
  }

  return (
    <InvoiceCatalogStep
      customer={customer}
      catalog={catalog}
      catalogNote={catalogNote}
      cart={cart}
      stockLimited
      onSetQuantity={setQuantity}
      onNext={goToSettlement}
      onBack={onSubmitted}
    />
  );
}
