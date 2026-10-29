/** R360: سلف‌سرویس کارمند — همان پاسخ‌های peecha_api/routers/self_service.py */

export interface SelfProfile {
  employee_id: number;
  employee_code: string;
  name: string;
  leave_types: Record<string, string>;
  leave_statuses: Record<string, string>;
}

export interface SelfPayslipRow {
  payslip_id: number;
  jalali_year: number;
  jalali_month: number;
  gross_amount: string;
  total_deductions: string;
  net_pay: string;
  status: string;
}

export interface SelfPayslipLine {
  code: string;
  label: string;
  amount: string;
}

export interface SelfPayslipDetail extends Omit<SelfPayslipRow, "status"> {
  employee_code: string;
  employee_name: string;
  earnings: SelfPayslipLine[];
  deductions: SelfPayslipLine[];
}

export interface SelfLeaveRow {
  leave_request_id: number;
  leave_type: string;
  leave_type_label: string;
  from_date: string;
  to_date: string;
  days: string | null;
  hours: string | null;
  reason: string;
  status_code: string;
  status_label: string;
  decision_note: string;
}

export interface SelfLeaveRequest {
  leave_type: string;
  from_date: string;
  to_date: string;
  hours?: string | null;
  reason: string;
}

export interface SelfAttendanceDay {
  work_date: string;
  kind: string;
  kind_label: string;
  shift: string;
  clock_in: string | null;
  clock_out: string | null;
  late_minutes: number;
  early_minutes: number;
  extra_minutes: number;
  pending: boolean;
}

export interface SelfAttendance {
  date_from: string;
  date_to: string;
  days: SelfAttendanceDay[];
  summary: {
    workdays: number;
    present: number;
    absent: number;
    leave: number;
    late_days: number;
    late_minutes: number;
    early_minutes: number;
    extra_minutes: number;
  } | null;
}
