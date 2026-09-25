/** انواعِ TypeScript هم‌شکل با src/peecha_api/schemas.py -- عمداً دستی
 * نگه‌داشته‌شده (نه تولیدِ خودکار) چون تعدادِ اندپوینت‌ها کم است؛ اگر
 * اسکیمایِ API عوض شود، این فایل هم باید دستی هم‌گام شود. */

export interface LoginResponse {
  access_token: string;
  refresh_token: string;
  user_id: number;
  full_name: string;
  company_id: number;
  company_name: string;
}

export interface RefreshResponse {
  access_token: string;
}

/** طبقِ درخواستِ صریحِ کاربر («تعیینِ کانالِ مجزا برایِ پخشِ سرد و
 * گرم»): null یعنی مدیر هنوز این ویزیتور را تنظیم نکرده -- اپِ موبایل
 * نباید حدس بزند. */
export interface MeResponse {
  mobile_channel_type_code: "VAN_SALES" | "PRE_SALES" | null;
  /** طبقِ درخواستِ صریحِ کاربر («فروش بر اساسِ موجودیِ خودرو»، فازِ ۲):
   * فقط برایِ پخشِ گرم پر می‌شود -- انبارِ همان خودرویی که این ویزیتور
   * در «تیمِ خودرو»یِ دسکتاپ به‌عنوانِ نقشِ VISITOR به آن وصل است. */
  assigned_vehicle_warehouse_id: number | null;
  /** طبقِ درخواستِ صریحِ کاربر («تسویه آخر روز باید بصورتِ انتخابی به
   * یک نفر از ۳ نقش واگذار بشه»): نقشِ مسئولِ تسویه لزوماً VISITOR نیست
   * -- پس این مقدار مستقل از assigned_vehicle_warehouse_id بالاست. */
  settlement_vehicle_warehouse_id: number | null;
  /** طبقِ درخواستِ صریحِ کاربر («تاییدِ مشتری، داشبوردِ سرپرست»): بدونِ
   * این، موبایل نمی‌توانست بدونِ حدس‌زدن دکمه‌هایِ مدیریتی را نشان بدهد. */
  is_manager: boolean;
}

export interface VehicleSettlementSummaryLine {
  item_id: number;
  item_name: string | null;
  uom_id: number;
  loaded_quantity: string;
  sold_quantity: string;
}

export interface VehicleSettlementSummaryResponse {
  invoiced_amount: string;
  lines: VehicleSettlementSummaryLine[];
}

export interface VehicleSettlementLineInput {
  item_id: number;
  uom_id: number;
  returned_quantity: string;
}

export interface VehicleSettlementSubmitRequest {
  declared_cash_amount: string;
  lines: VehicleSettlementLineInput[];
}

export interface VehicleSettlementSubmitResponse {
  vehicle_settlement_id: number;
}

export interface VisitPlanRow {
  visit_plan_id: number;
  customer_detail_account_id: number;
  visit_day_of_week: number;
  sequence_order: number;
}

export interface CustomerRow {
  detail_account_id: number;
  code: string;
  name: string;
  gps_latitude: number | null;
  gps_longitude: number | null;
}

export interface ItemRow {
  item_id: number;
  code: string;
  name: string;
  base_uom_id: number;
  base_uom_code: string;
}

export interface PullResponse {
  visit_plans: VisitPlanRow[];
  customers: CustomerRow[];
  items: ItemRow[];
}

export interface StartVisitRequest {
  customer_detail_account_id: number;
  visit_plan_id?: number | null;
  check_in_latitude?: number | null;
  check_in_longitude?: number | null;
}

export interface StartVisitResponse {
  customer_visit_id: number;
}

export interface ChannelRow {
  channel_code: string;
  name: string;
  channel_type_code: string;
  default_cost_center_detail_account_id: number | null;
  default_project_detail_account_id: number | null;
}

export interface WarehouseRow {
  warehouse_id: number;
  code: string;
  name: string;
  is_default: boolean;
}

/** طبقِ درخواستِ صریحِ کاربر («نوعِ تسویه در پخشِ گرم باید همانندِ
 * انواعِ تسویه در دسکتاپ باشد»): فقط روش‌هایِ فعال‌شده‌یِ موبایل. */
export interface SettlementDetailOption {
  detail_account_id: number;
  code: string;
  name: string;
}

export interface SettlementMethodRow {
  method_code: string;
  label: string;
  /** هم‌الگو با ستونِ «تفصیلی» در دیالوگِ نحوه‌یِ تسویهٔ دسکتاپ: اگر true،
   * باید یکی از detail_options (صندوق/حسابِ بانکی) انتخاب شود. */
  requires_detail?: boolean;
  detail_options?: SettlementDetailOption[];
  default_detail_account_id?: number | null;
}

/** هم‌فرمت با چکِ دریافتیِ فرمِ دریافتِ خزانه‌داریِ دسکتاپ. */
export interface ReceivedCheckInput {
  check_no: string;
  due_date: string;
  amount: string;
  check_serial?: string | null;
  bank_id?: number | null;
  check_bank_name?: string | null;
  iban?: string | null;
  bank_account_no?: string | null;
  party_name?: string | null;
  national_id?: string | null;
  phone?: string | null;
}

export interface OrderSettlementLineInput {
  method_code: string;
  amount: string;
  detail_account_id?: number | null;
  note?: string | null;
  checks?: ReceivedCheckInput[];
}

export interface OrderLineInput {
  item_id: number;
  uom_id: number;
  quantity: string;
  unit_price: string;
  /** طبقِ باگِ واقعیِ کشف‌شده (R210): قبلاً اصلاً فرستاده نمی‌شد -- پس
   * تخفیفِ برگشته از GET /pricing/resolve همیشه گم می‌شد. */
  discount_amount: string;
}

export interface OrderCreateRequest {
  document_type_code: "SALES_ORDER" | "SALES_INVOICE";
  counterparty_detail_account_id: number;
  currency_id: number;
  warehouse_id: number;
  channel_code: string;
  post_immediately: boolean;
  lines: OrderLineInput[];
  cost_center_detail_account_id?: number | null;
  project_detail_account_id?: number | null;
  /** طبقِ درخواستِ صریح: undefined یعنی نفرستادن (سازگاریِ عقب‌رو با
   * رفتارِ قدیمیِ سرور -- ۱۰۰٪ نقدی)؛ فهرستِ خالی یعنی صراحتاً «همه‌اش
   * نسیه». */
  settlement_lines?: OrderSettlementLineInput[];
}

export interface OrderCreateResponse {
  document_id: number;
  line_ids: number[];
  document_no?: number;
  settlement_warning?: string | null;
}

export interface DeliveryLineInput {
  document_line_id: number;
  delivered_quantity: string;
  shortage_reason?: string | null;
}

export interface DeliveryConfirmationRequest {
  document_id: number;
  customer_visit_id?: number | null;
  received_by_name?: string | null;
  signature_base64?: string | null;
  photo_base64?: string | null;
  gps_latitude?: number | null;
  gps_longitude?: number | null;
  notes?: string | null;
  lines: DeliveryLineInput[];
}

export interface DeliveryConfirmationResponse {
  delivery_confirmation_id: number;
}

export interface PriceResolveRequest {
  counterpartyDetailAccountId: number;
  itemId: number;
  uomId: number;
  quantity: string;
  documentTypeCode: "SALES_ORDER" | "SALES_INVOICE";
  /** برایِ محاسبهٔ درصدِ مالیات با همان اولویتِ دسکتاپ (شرکت→انبار→کالا). */
  warehouseId?: number | null;
  /** طبقِ درخواستِ صریحِ کاربر («کدام قیمت برایِ پخشِ گرم/سرد قابلِ‌انتخاب
   * باشه»): اگر این کانال در تنظیماتِ بازرگانی لیست‌قیمت/تخفیفِ پیش‌فرضِ
   * خودش را داشته باشد، به‌جایِ پیش‌فرضِ خودِ مشتری اعمال می‌شود. */
  channelCode?: string | null;
}

export interface PriceResolveResponse {
  unit_price: string;
  source: "CONTRACT" | "PRICE_LIST";
  discount_amount: string;
  /** فقط برایِ پیش‌نمایشِ محلی -- سرور هنگامِ ثبتِ سند دوباره تعیین می‌کند. */
  tax_percent: string;
}

export interface NextVisitSummary {
  customer_detail_account_id: number;
  customer_name: string;
  visit_plan_id: number;
}

export interface TodayRouteEntry {
  visit_plan_id: number;
  customer_detail_account_id: number;
  customer_name: string;
  state: "DONE" | "CURRENT" | "UPCOMING" | "SKIPPED";
}

export interface TodaySummaryResponse {
  visit_count: number;
  visit_completed_count: number;
  order_count: number;
  sales_amount: string;
  collection_amount: string;
  next_visit: NextVisitSummary | null;
  today_route: TodayRouteEntry[];
}

export interface CustomerListRow {
  detail_account_id: number;
  code: string;
  name: string;
  phone: string | null;
}

export interface CustomerTopProduct {
  item_id: number;
  item_name: string | null;
  total_quantity: string;
  total_amount: string;
}

export interface CustomerRecentDocument {
  document_id: number;
  document_type_code: "SALES_ORDER" | "SALES_INVOICE";
  document_no: number;
  document_date: string;
  status_code: string;
  total_amount: string;
}

export interface CustomerDetailResponse {
  detail_account_id: number;
  code: string;
  name: string;
  phone: string | null;
  mobile: string | null;
  address: string | null;
  notes: string | null;
  customer_type_code: string | null;
  customer_class: string | null;
  status_code: string | null;
  customer_group_id: number | null;
  credit_limit_amount: string | null;
  payment_term_days: number | null;
  gps_latitude: string | null;
  gps_longitude: string | null;
  balance_amount: string;
  balance_nature: "بدهکار" | "بستانکار";
  last_purchase_date: string | null;
  top_products: CustomerTopProduct[];
  recent_documents: CustomerRecentDocument[];
}

/** طبقِ درخواستِ صریحِ کاربر (Customer Acquisition): code عمداً اختیاری
 * است -- اگر ویزیتور آفلاین باشد نمی‌تواند کدِ بعدیِ شرکت را بداند؛
 * سرور خودش هنگامِ همگام‌سازیِ واقعی کدِ بعدی را اختصاص می‌دهد. */
export interface CustomerCreateRequest {
  code?: string | null;
  name: string;
  customer_group_id?: number | null;
  default_channel_code?: string | null;
  distribution_route_detail_account_id?: number | null;
  address?: string | null;
  phone?: string | null;
  mobile?: string | null;
  notes?: string | null;
  photo_base64?: string | null;
  gps_latitude?: number | null;
  gps_longitude?: number | null;
  customer_type_code?: string | null;
  customer_class?: string | null;
  /** طبقِ بازبینیِ صریحِ کاربر (R218 -- مشتری یک تفصیلیِ چندسطحی‌ست):
   * فقط وقتی NewCustomerFormOptions.max_level_no > 1 الزامی است. */
  parent_detail_account_id?: number | null;
}

export interface CustomerCreateResponse {
  detail_account_id: number;
  code: string;
  status_code: "PENDING_APPROVAL";
}

export interface CustomerGroupRow {
  group_id: number;
  code: string;
  name: string;
}

export interface CustomerParentOption {
  detail_account_id: number;
  code: string;
  name: string;
  full_code: string;
}

export interface NewCustomerFormOptions {
  suggested_code: string;
  groups: CustomerGroupRow[];
  /** ۱ یعنی گروهِ مشتری تک‌سطحی است (پیش‌فرض) -- parent_options همیشه
   * خالی و انتخابِ والد لازم نیست. */
  max_level_no: number;
  parent_options: CustomerParentOption[];
}

export interface DuplicateCustomerRow {
  detail_account_id: number;
  code: string;
  name: string;
  mobile: string | null;
  phone: string | null;
  address: string | null;
  match_reasons: string[];
}

/** طبقِ بازبینیِ ساختارِ «تعریفِ مشتری» (R216، بخشِ ۲ -- چندآدرسیِ واقعی
 * + GeoFence). */
export interface PartyAddressRow {
  address_id: number;
  address_type_code: "OFFICE" | "STORE" | "WAREHOUSE" | "DELIVERY" | "BILLING" | "RETURN";
  line1: string;
  city: string | null;
  province: string | null;
  postal_code: string | null;
  is_default: boolean;
  gps_latitude: string | null;
  gps_longitude: string | null;
  geofence_radius_meters: number | null;
}

export interface PartyAddressRequest {
  address_type_code: string;
  line1: string;
  city?: string | null;
  province?: string | null;
  postal_code?: string | null;
  is_default?: boolean;
  gps_latitude?: number | null;
  gps_longitude?: number | null;
  geofence_radius_meters?: number | null;
}

export interface CustomerApprovalResponse {
  detail_account_id: number;
  status_code: string;
}

export type PaymentMethod = "CASH" | "BANK" | "CHECK";

export interface PaymentMethodLineInput {
  method: PaymentMethod;
  amount: string;
  description?: string;
  detail_account_id?: number | null;
  check_no?: string | null;
  check_bank_name?: string | null;
  check_due_date?: string | null;
  check_party_name?: string | null;
}

export interface PaymentCreateRequest {
  customer_detail_account_id: number;
  document_date?: string | null;
  description?: string;
  customer_visit_id?: number | null;
  method_lines: PaymentMethodLineInput[];
}

export interface PaymentCreateResponse {
  journal_entry_id: number;
  temporary_no: number;
}

export interface NotificationRow {
  notification_id: number;
  type_code: string;
  title: string;
  body: string | null;
  entity_type: string | null;
  entity_id: number | null;
  is_read: boolean;
  created_at: string | null;
}

export interface VisitorPerformanceRow {
  user_id: number;
  full_name: string;
  visit_count: number;
  visit_completed_count: number;
  order_count: number;
  sales_amount: string;
  collection_amount: string;
}

export interface ManagerDashboardResponse {
  date_from: string;
  date_to: string;
  sales_amount: string;
  order_count: number;
  average_order_value: string;
  collection_amount: string;
  collection_rate: string;
  visit_count: number;
  visit_completed_count: number;
  visit_to_order_conversion: string;
  new_customer_count: number;
  customers_without_purchase_count: number;
  by_visitor: VisitorPerformanceRow[];
}

export interface RouteRow {
  detail_account_id: number;
  code: string;
  name: string | null;
}

export interface DebtorRow {
  detail_account_id: number;
  code: string;
  name: string;
  balance_amount: string;
}

export interface TodayCollectionRow {
  journal_entry_id: number;
  customer_name: string | null;
  amount: string;
  description: string | null;
}

/** حالتِ فروشِ انتخاب‌شده در موبایل -- پخشِ گرم (فاکتورِ آنی) یا پخشِ سرد (سفارش). */
export type SalesMode = "VAN_SALES" | "PRE_SALES";

export interface CatalogItem {
  item_id: number;
  code: string;
  name: string;
  barcode: string | null;
  sku: string | null;
  category_id: number | null;
  brand_id: number | null;
  base_uom_id: number;
  base_uom_code: string;
  default_tax_percent: string | null;
  /** null یعنی انبار مشخص نشده (موجودی نامعلوم). */
  stock_quantity: string | null;
  /** JPEGِ کوچک‌شده‌یِ Base64 -- null یعنی این کالا عکسِ اصلی ندارد یا
   * عکس برایِ گروهِ «کالا» در دسکتاپ فعال نیست. */
  photo_base64: string | null;
}

export interface CatalogResponse {
  items: CatalogItem[];
  categories: { category_id: number; parent_category_id: number | null; name: string }[];
  brands: { brand_id: number; name: string }[];
}

export interface BankRow {
  bank_id: number;
  name: string;
}

export interface InvoicePrintLine {
  line_no: number;
  item_code: string;
  item_name: string | null;
  uom_code: string;
  quantity: string;
  unit_price: string;
  discount_amount: string;
  tax_amount: string;
  line_total: string;
}

export interface InvoicePrintData {
  document_id: number | null;
  document_type_code: string;
  document_no: number | null;
  document_date: string;
  status_code: string;
  company: { name: string; legal_name?: string | null; economic_code: string | null; national_id: string | null; registration_no?: string | null };
  seller_name: string | null;
  customer: { detail_account_id: number; code: string | null; name: string | null; phone: string | null; address: string | null };
  lines: InvoicePrintLine[];
  gross_amount: string;
  discount_amount: string;
  tax_amount: string;
  total_amount: string;
  settlement_lines: { method_code: string; label: string; amount: string; note: string | null }[];
  checks: { check_no: string; bank_name: string | null; due_date: string; amount: string }[];
  settled_amount: string;
  remaining_amount: string;
}
