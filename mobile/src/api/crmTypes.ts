/** انواعِ API CRM (R286) -- منطبق با peecha_api/routers/crm.py؛ مبلغ‌ها رشته‌اند (Decimal سرور). */

export interface CrmActivityRow {
  activity_id: number;
  activity_type_code: string;
  type_label: string;
  subject: string;
  description: string | null;
  status_code: string;
  status_label: string;
  priority_code: string;
  due_date: string | null;
  customer_detail_account_id: number | null;
  customer_name: string;
  lead_id: number | null;
  lead_name: string;
  opportunity_id: number | null;
  assigned_name: string;
  result_text: string | null;
  next_action: string | null;
  is_open: boolean;
}

export interface CrmOpenTicket {
  ticket_id: number;
  ticket_no: number | null;
  customer_detail_account_id: number;
  customer_name: string;
  subject: string;
  type_label: string;
  priority_code: string;
  resolution_due_at: string | null;
  sla_state: "OK" | "AT_RISK" | "BREACHED" | "NONE";
}

export interface CrmTasksResponse {
  buckets: Record<string, CrmActivityRow[]>;
  counts: Record<string, number>;
  planned_visits: { customer_detail_account_id: number; customer_name: string; visited?: boolean }[];
  pending_orders: unknown[];
  due_collections: unknown[];
  open_tickets?: CrmOpenTicket[];
}

export interface CrmActivityRequest {
  activity_type_code: string;
  subject: string;
  customer_detail_account_id?: number | null;
  lead_id?: number | null;
  customer_visit_id?: number | null;
  description?: string | null;
  due_date?: string | null;
  priority_code?: string;
  next_action?: string | null;
  next_action_date?: string | null;
}

export interface CrmActivityCompleteRequest {
  result_text?: string | null;
  follow_up_date?: string | null;
  follow_up_subject?: string | null;
}

export interface CrmLeadRequest {
  full_name: string;
  company_name?: string | null;
  mobile?: string | null;
  phone?: string | null;
  email?: string | null;
  source_id?: number | null;
  interested_text?: string | null;
  estimated_value?: string | null;
  city?: string | null;
  notes?: string | null;
  allow_duplicate?: boolean;
  campaign_id?: number | null;
}

export interface CrmLeadSource {
  source_id: number;
  code: string;
  name: string;
}

export interface CrmLeadRow {
  lead_id: number;
  lead_no: number;
  full_name: string;
  company_name: string | null;
  mobile: string | null;
  status_code: string;
  status_label: string;
  score: number;
  band_label: string;
  source_name: string;
  next_action: string | null;
}

export interface CrmTicketRequest {
  customer_detail_account_id: number;
  subject: string;
  ticket_type: string;
  priority_code: string;
  channel_code?: string | null;
  description?: string | null;
}

export interface CrmCustomerAnalytics {
  health_score: number;
  health_label: string;
  health_band: string;
  churn_risk: number;
  churn_label: string;
  churn_band: string;
  rfm: string;
  rfm_label: string;
  clv_historical: string;
  next_best_action: string | null;
  segments: string[];
}

export interface CrmSmartAction {
  code: string;
  severity: "danger" | "warning" | "info";
  text: string;
  suggestion: string;
  action?: string;
}

export interface Crm360Response {
  summary: string;
  smart_actions: CrmSmartAction[];
  counts: { open_activities: number; overdue_activities: number; open_opportunities: number; open_opportunity_value: string; open_tickets: number };
  analytics: CrmCustomerAnalytics | null;
  loyalty?: { points: number; tier_label: string; lifetime_points: number } | null;
}

export const CRM_ACTIVITY_TYPES: { code: string; label: string }[] = [
  { code: "CALL", label: "تماس" }, { code: "VISIT", label: "بازدید" }, { code: "FOLLOW_UP", label: "پیگیری" },
  { code: "MEETING", label: "جلسه" }, { code: "TASK", label: "وظیفه" }, { code: "NOTE", label: "یادداشت" },
];

export const CRM_TICKET_TYPES: { code: string; label: string }[] = [
  { code: "COMPLAINT", label: "شکایت" }, { code: "REQUEST", label: "درخواست" }, { code: "INQUIRY", label: "استعلام" },
  { code: "SUPPORT", label: "پشتیبانی" }, { code: "RETURN", label: "مرجوعی" }, { code: "SUGGESTION", label: "پیشنهاد" },
];

export const CRM_PRIORITIES: { code: string; label: string }[] = [
  { code: "LOW", label: "کم" }, { code: "NORMAL", label: "عادی" }, { code: "HIGH", label: "بالا" }, { code: "CRITICAL", label: "بحرانی" },
];
