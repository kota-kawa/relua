export type MasterItem = {
  id: number;
  slug: string;
  name: string;
};

export type SectorItem = MasterItem & { industry_id: number };

export type Masters = {
  recruitment_statuses: MasterItem[];
  industries: MasterItem[];
  sectors: SectorItem[];
  event_types: MasterItem[];
  event_formats: MasterItem[];
  job_categories: MasterItem[];
  graduation_years: MasterItem[];
  degrees: MasterItem[];
};

export type Opportunity = {
  id: string;
  /** Short identifier used in transfer and share links. */
  public_code: string;
  /** Absolute link to the public detail page, so API consumers can cite an entry. */
  url: string;
  recruitment_status: MasterItem;
  company: { id: number; name: string };
  industry: MasterItem;
  sector: MasterItem;
  event_name: string;
  deadline: string | null;
  event_type: MasterItem;
  description: string;
  event_format: MasterItem;
  location: string | null;
  selection_process: string | null;
  homepage_url: string | null;
  job_categories: MasterItem[];
  tags: string[];
  event_start_date: string | null;
  event_end_date: string | null;
  period_note: string | null;
  requirements: string | null;
  compensation: string | null;
  graduation_years: MasterItem[];
  degrees: MasterItem[];
  audience_note: string | null;
  recruitment_start_date: string | null;
  entry_url: string | null;
  source_url: string;
  created_at: string;
  updated_at: string;
  /** Last time the official source was confirmed to match this record. */
  source_checked_at: string | null;
};

export type OpportunityList = {
  items: Opportunity[];
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
};

export type SearchParams = Record<string, string | string[] | undefined>;
