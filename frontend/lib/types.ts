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

/** A company as it appears inside a posting: enough to name it and link to its page. */
export type CompanyRef = {
  id: number;
  name: string;
  /** Short identifier used in the company page URL. */
  public_code: string;
  /** Absolute link to the public company page. */
  url: string;
};

export type Opportunity = {
  id: string;
  /** Short identifier used in transfer and share links. */
  public_code: string;
  /** Absolute link to the public detail page, so API consumers can cite an entry. */
  url: string;
  recruitment_status: MasterItem;
  company: CompanyRef;
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

export type CompanyIndustry = {
  industry: MasterItem;
  sector: MasterItem | null;
  is_primary: boolean;
};

/** One of a company's main businesses, shown as its own block on the company page. */
export type CompanyBusinessArea = {
  name: string;
  description: string;
};

export type CompanySummary = {
  id: number;
  public_code: string;
  url: string;
  name: string;
  /** One or two sentences naming the business. Doubles as the page's meta description. */
  business_summary: string | null;
  /** The body of the profile. Blank lines separate paragraphs. */
  description: string | null;
  business_areas: CompanyBusinessArea[];
  website_url: string | null;
  industries: CompanyIndustry[];
  current_opportunity_count: number;
  /** Newest update among the current openings, so a page's own freshness is visible. */
  openings_updated_at: string | null;
  created_at: string;
  updated_at: string;
};

export type CompanyDetail = CompanySummary & {
  current_opportunities: Opportunity[];
  past_opportunities: Opportunity[];
};

export type CompanyList = {
  items: CompanySummary[];
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
};

export type SearchParams = Record<string, string | string[] | undefined>;
