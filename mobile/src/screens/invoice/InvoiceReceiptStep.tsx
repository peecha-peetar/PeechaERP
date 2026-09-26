import React, { useCallback, useEffect, useState } from "react";
import { ScrollView, Text } from "react-native";
import { ApiClient } from "../../api/client";
import { InvoicePrintData } from "../../api/types";
import { Button, Card, InlineSpinner, useToast } from "../../components";
import { formatAmount } from "../../format";
import { printInvoice, shareInvoicePdf } from "../../print/printInvoice";
import { InvoiceResultStore } from "../../sync/invoiceResults";
import { SyncEngine } from "../../sync/syncEngine";
import { useTheme } from "../../theme/ThemeProvider";

interface Props {
  actionKey: string;
  localPrintData: InvoicePrintData;
  apiClient: ApiClient;
  syncEngine: SyncEngine;
  invoiceResults: InvoiceResultStore;
  onNewInvoice: () => void;
}

/** طبقِ درخواستِ صریحِ کاربر («در ادامه پرینتِ فاکتور و فایلِ pdf»): اگر
 * فاکتور همان لحظه همگام‌سازی شد، نسخهٔ رسمیِ سرور (با شماره، تخفیف/
 * مالیات و چک‌هایِ واقعاً ثبت‌شده) چاپ می‌شود؛ در غیرِ این صورت یک
 * پیش‌نمایش از دادهٔ همین گوشی (بدونِ شماره) -- و هر وقت همگام‌سازی شد،
 * همین صفحه یا سوابقِ مشتری نسخهٔ رسمی را چاپ می‌کند. */
export function InvoiceReceiptStep({ actionKey, localPrintData, apiClient, syncEngine, invoiceResults, onNewInvoice }: Props) {
  const { colors, spacing, typography } = useTheme();
  const toast = useToast();
  const [syncing, setSyncing] = useState(true);
  const [printData, setPrintData] = useState<InvoicePrintData>(localPrintData);
  const [warning, setWarning] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    setSyncing(true);
    try {
      await syncEngine.pushQueue();
    } catch {
      // آفلاین -- پیش‌نمایشِ محلی می‌ماند
    }
    const result = await invoiceResults.get(actionKey);
    if (result) {
      setWarning(result.settlementWarning);
      try {
        setPrintData(await apiClient.getInvoicePrintData(result.documentId));
      } catch {
        setPrintData({ ...localPrintData, document_id: result.documentId, document_no: result.documentNo });
      }
    }
    setSyncing(false);
  }, [actionKey, apiClient, invoiceResults, localPrintData, syncEngine]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const run = async (action: (data: InvoicePrintData) => Promise<void>) => {
    setBusy(true);
    try {
      await action(printData);
    } catch {
      toast.show("چاپ/ساختِ PDF انجام نشد.", "danger");
    } finally {
      setBusy(false);
    }
  };

  const synced = printData.document_no !== null;

  return (
    <ScrollView contentContainerStyle={{ padding: spacing.lg, gap: spacing.md, backgroundColor: colors.background, flexGrow: 1 }}>
      <Text style={[typography.h2, { color: colors.textPrimary }]}>فاکتور ثبت شد</Text>
      <Card>
        <Text style={[typography.body, { color: colors.textPrimary }]}>مشتری: {printData.customer.name}</Text>
        <Text style={[typography.body, { color: colors.textPrimary }]}>
          شمارهٔ فاکتور: {synced ? printData.document_no : "پس از همگام‌سازی"}
        </Text>
        <Text style={[typography.bodyBold, { color: colors.textPrimary }]}>مبلغ: {formatAmount(printData.total_amount)}</Text>
        <Text style={[typography.body, { color: colors.textSecondary }]}>مانده (نسیه): {formatAmount(printData.remaining_amount)}</Text>
      </Card>

      {syncing ? <InlineSpinner label="در حالِ همگام‌سازی با سرور..." /> : null}
      {!syncing && !synced ? (
        <Card style={{ borderColor: colors.warning }}>
          <Text style={[typography.caption, { color: colors.warning }]}>
            اتصال به سرور برقرار نشد -- فاکتور در صفِ آفلاین است و خودکار ارسال می‌شود. چاپِ فعلی پیش‌نمایش (بدونِ شمارهٔ رسمی) است.
          </Text>
          <Button label="تلاشِ دوباره" variant="ghost" fullWidth={false} onPress={refresh} />
        </Card>
      ) : null}
      {warning ? (
        <Card style={{ borderColor: colors.danger }}>
          <Text style={[typography.caption, { color: colors.danger }]}>{warning}</Text>
          <Text style={[typography.caption, { color: colors.textSecondary }]}>دریافتِ این فاکتور را در دسکتاپ (خزانه‌داری) ثبت کنید.</Text>
        </Card>
      ) : null}

      <Button label="چاپِ فاکتور" onPress={() => run(printInvoice)} loading={busy} disabled={busy || syncing} />
      <Button label="فایلِ PDF (ذخیره/ارسال)" variant="secondary" onPress={() => run(shareInvoicePdf)} disabled={busy || syncing} />
      <Button label="فاکتورِ جدید" variant="ghost" onPress={onNewInvoice} />
    </ScrollView>
  );
}
