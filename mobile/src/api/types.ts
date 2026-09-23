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

export interface OrderLineInput {
  item_id: number;
  uom_id: number;
  quantity: string;
  unit_price: string;
}

export interface OrderCreateRequest {
  document_type_code: "SALES_ORDER" | "SALES_INVOICE";
  counterparty_detail_account_id: number;
  currency_id: number;
  warehouse_id: number;
  channel_code: string;
  post_immediately: boolean;
  lines: OrderLineInput[];
}

export interface OrderCreateResponse {
  document_id: number;
  line_ids: number[];
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
}

export interface PriceResolveResponse {
  unit_price: string;
  source: "CONTRACT" | "PRICE_LIST";
  discount_amount: string;
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
  address: string | null;
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

export type PaymentMethod = "CASH" | "BANK" | "CHECK";

export interface PaymentMethodLineInput {
  method: PaymentMethod;
  amount: string;
  description?: string;
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
