/* Generated from public/data/schema.json by npm run types. Do not edit. */

/**
 * Every file the app reads, in one schema, so its types are generated from this.
 */
export interface FinnData {
  portfolio: Portfolio;
  filings: Filings;
  meta: Meta;
  research_report: ResearchReport;
  research_index: ResearchIndex;
  ask: AskAnswers;
}
export interface Portfolio {
  holdings: Holding[];
}
export interface Holding {
  symbol: string;
  name: string;
  sector: string | null;
  size: string | null;
  last_date: string | null;
  close: number | null;
  ret_pct: number | null;
  vol_ratio: number | null;
  series: PricePoint[];
  source_url: string;
}
export interface PricePoint {
  date: string;
  close: number;
  /**
   * Close-to-close move, percent
   */
  ret_pct?: number | null;
  /**
   * Volume over the prior 20-session mean
   */
  vol_ratio?: number | null;
  /**
   * Set when the move is a corporate action
   */
  corp_action?: string | null;
}
export interface Filings {
  filings: Filing[];
}
export interface Filing {
  id: string;
  symbol: string;
  exchange: string;
  filed_at: string;
  exchange_label: string | null;
  headline: string | null;
  category: string | null;
  tier: ("must_see" | "glance" | "routine") | null;
  /**
   * rule, ai, or null when not yet sorted
   */
  classified_by: string | null;
  rule: string | null;
  needs_ai: boolean;
  text_quality: string | null;
  attachment_url: string | null;
  source_url: string;
  insight?: Insight | null;
  /**
   * Every event in the filing, lead first
   */
  events?: string[];
  /**
   * On the group lead only, merged across the group
   */
  cards?: (ResultsCard | PeopleCard)[];
  price_reaction?: PriceReaction | null;
  /**
   * Priority for Today's 3: higher shows first
   */
  score?: number;
  /**
   * Filings about the same event share a group
   */
  group_id: string;
  /**
   * The one filing of its group to show; the rest are attachments
   */
  group_lead?: boolean;
  /**
   * Set when this is a copy of an earlier filing's letter
   */
  duplicate_of?: string | null;
}
export interface Insight {
  title: string;
  summary: string;
  why_it_matters: string | null;
  sentiment: "positive" | "negative" | "neutral" | "mixed";
  amount_inr_crore: number | null;
  model: string;
}
/**
 * Headline numbers for one quarter versus last quarter and a year ago, in rupees crore.
 */
export interface ResultsCard {
  type?: "results";
  symbol: string;
  period_end: string;
  /**
   * Indian financial-year quarter, e.g. Q2 FY27
   */
  period_label: string;
  basis: string;
  kind: "standard" | "bank";
  unit?: string;
  metrics: Metric[];
  margin_label?: string | null;
  /**
   * current, previous quarter, year ago
   */
  margin_pct?: (number | null)[];
  source: "xbrl" | "filing_text" | "filing_image" | "screener";
  /**
   * True when it matches screener.in, False on a mismatch
   */
  verified?: boolean | null;
  check_note: string;
  /**
   * Reported separately from PBT in the filing; shown so the check is transparent
   */
  share_of_associates?: number | null;
  source_urls: string[];
}
export interface Metric {
  key: string;
  label: string;
  current: number | null;
  previous_quarter: number | null;
  year_ago: number | null;
  qoq_pct: number | null;
  yoy_pct: number | null;
}
export interface PeopleCard {
  type?: "people";
  changes: PersonChange[];
}
export interface PersonChange {
  person: string;
  role: string;
  change: "appointment" | "reappointment" | "resignation" | "retirement" | "cessation" | "redesignation" | "other";
  effective_date?: string | null;
  reason?: string | null;
  /**
   * Bio taken from the filing's own profile section
   */
  profile?: string | null;
  previous_roles?: string[];
  education?: string | null;
  /**
   * Filing id the profile came from, if not this one
   */
  profile_source?: string | null;
}
export interface PriceReaction {
  session: string;
  ret_pct: number | null;
  vol_ratio: number | null;
}
export interface Meta {
  schema_version?: number;
  generated_at: string;
  latest_session: string | null;
  filings_window_days: number;
  counts: {
    [k: string]: number;
  };
  alert_defaults: AlertDefaults;
  ai?: AIStats | null;
  sources: string[];
}
export interface AlertDefaults {
  price_move_pct: number;
  volume_multiple: number;
  volume_baseline_sessions: number;
}
export interface AIStats {
  calls: number;
  input_tokens: number;
  output_tokens: number;
  by_model: {
    [k: string]: number;
  };
  cached_answers: number;
}
export interface ResearchReport {
  schema_version?: number;
  symbol: string;
  name: string;
  basis: string;
  generated_at: string;
  snapshot: Snapshot;
  narrative: string | null;
  promises: Guidance[];
  cash: CashQuality;
  bull: CasePoint[];
  bear: CasePoint[];
  /**
   * what is missing, and why
   */
  notes?: string[];
  documents: SourceDoc[];
  stats: ResearchStats;
}
export interface Snapshot {
  about: string | null;
  latest_quarter: string | null;
  revenue: number | null;
  revenue_yoy: number | null;
  net_profit: number | null;
  net_profit_yoy: number | null;
  ebitda_margin: number | null;
}
/**
 * One promise from a call, with what was delivered and who judged it.
 */
export interface Guidance {
  id: string;
  metric: string;
  period: string | null;
  /**
   * e.g. "≥ ₹4,000 crore" or "1–2% (constant currency)"
   */
  target: string | null;
  statement: string;
  said: Evidence;
  /**
   * later calls that repeated it
   */
  repeated_in?: string[];
  actual?: string | null;
  actual_source?: Evidence | null;
  verdict: "beat" | "met" | "missed" | "on_track" | "at_risk" | "pending" | "unclear";
  verdict_by: "code" | "model";
  note?: string | null;
}
/**
 * A sentence from a primary document, checked by code to be there, or a computed fact.
 */
export interface Evidence {
  quote: string;
  /**
   * e.g. "Q1 FY27 call, 8 Aug 2026" or "Annual report FY26"
   */
  source: string;
  page?: number | null;
  url: string;
}
export interface CashQuality {
  applicable: boolean;
  reason?: string | null;
  years?: CashYear[];
  conversion_5y?: number | null;
  /**
   * the parent company alone, when its accounts tell a different story
   */
  parent_conversion_5y?: number | null;
  signals?: Evidence[];
  read?: string | null;
}
export interface CashYear {
  year: string;
  operating_cash_flow: number | null;
  net_profit: number | null;
  free_cash_flow: number | null;
  /**
   * operating cash flow / net profit
   */
  cash_conversion: number | null;
  debtor_days: number | null;
  inventory_days: number | null;
  working_capital_days: number | null;
}
export interface CasePoint {
  point: string;
  evidence: Evidence[];
}
export interface SourceDoc {
  label: string;
  kind: string;
  url: string;
  pages: number;
}
export interface ResearchStats {
  calls_read: number;
  claims_found: number;
  quotes_verified: number;
  quotes_dropped: number;
  graded_by_code: number;
  graded_by_model: number;
  ai_calls: number;
  cached_calls: number;
  models: string[];
  seconds: number;
}
export interface ResearchIndex {
  reports: ResearchIndexEntry[];
}
export interface ResearchIndexEntry {
  symbol: string;
  name: string;
  generated_at: string;
  promises: number;
  missed: number;
  kept: number;
  pending: number;
}
export interface AskAnswers {
  /**
   * by filing id
   */
  answers: {
    [k: string]: AskAnswer;
  };
}
/**
 * 'Ask about this': what management said about an event, with quotes found by code.
 */
export interface AskAnswer {
  symbol: string;
  question: string;
  addressed: boolean;
  answer: string;
  evidence?: Evidence[];
  /**
   * the calls that were read
   */
  calls: string[];
  model?: string | null;
  asked_at: string;
}
