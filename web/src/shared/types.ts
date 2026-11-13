export interface InvoiceRow {
  partner: string;
  name: string;
  month: string;
  currency: string;
  issued: string | null;
  notes: number;
  first_err_pct: number | null;
  final_err_pct: number | null;
  held_days: number;
}

export interface VariantRow {
  key: string;
  label: string;
  final_error_pct: number;
  invoices_wrong_final: number;
  partner_disputes: number;
}

export interface IncidentRow {
  incident: string;
  where: string;
  start: string;
  caught: boolean;
  first_check: string | null;
  hours_to_alert: number | null;
}

export interface Dashboard {
  world: string;
  headline: { backbone_error_pct: number; first_version_error_pct: number; true_billing_eur: number; disputes: [number, number] };
  invoices: InvoiceRow[];
  variants: VariantRow[];
  incidents: IncidentRow[];
}

export interface Answer {
  question: string;
  answered: boolean;
  refusal?: string;
  metric?: string;
  unit?: string;
  sql?: string;
  rows?: (string | number | null)[][];
}
