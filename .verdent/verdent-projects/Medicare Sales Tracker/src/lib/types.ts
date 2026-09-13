export type ProductLine = 'MA' | 'MEDSUPP' | 'PARTD' | 'ANCILLARY';

export type Status =
  | 'lead'
  | 'quote'
  | 'application'
  | 'pending'
  | 'effective'
  | 'declined'
  | 'cancelled';

export interface Client {
  id: string;
  first_name: string;
  last_name: string;
  phone: string | null;
  email: string | null;
  dob: string | null;
  county: string | null;
  notes: string | null;
  created_at?: string;
}

export interface Carrier {
  id: string;
  name: string;
  product_lines: string[];
}

export interface Policy {
  id: string;
  client_id: string;
  carrier_id: string | null;
  product_line: ProductLine;
  ancillary_type: string | null;
  plan_name: string | null;
  status: Status;
  monthly_premium: number;
  commission_amount: number;
  app_date: string | null;
  effective_date: string | null;
  renewal_date: string | null;
  notes: string | null;
}

export interface Goal {
  id: string;
  month: string;
  product_line: ProductLine;
  target_apps: number;
}
