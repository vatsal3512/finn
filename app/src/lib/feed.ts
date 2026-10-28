// Which filings the investor sees, and in what order. The ranking itself (score, tier,
// grouping of copies) is computed by the pipeline; this file only applies the time window.

import type { Filing, ResultsCard } from "./contract";

export const WINDOWS = [
  { key: "24h", hours: 24, label: "24h", long: "the last 24 hours" },
  { key: "3d", hours: 72, label: "3 days", long: "the last 3 days" },
  { key: "7d", hours: 168, label: "7 days", long: "the last 7 days" },
  { key: "30d", hours: 720, label: "30 days", long: "the last 30 days" },
] as const;
export type WindowKey = (typeof WINDOWS)[number]["key"];

export const CATEGORY: Record<string, string> = {
  results: "Results",
  "M&A": "Deal",
  fund_raise: "Fund raise",
  management_change: "Leadership",
  litigation: "Litigation",
  insider_trading: "Insider trade",
  earnings_call: "Earnings call",
  investor_meetings: "Investor meeting",
  credit_rating: "Credit rating",
  dividend: "Dividend",
  bonus_split: "Bonus or split",
  capex: "Capex",
  press_release: "Press release",
  postal_ballot: "Postal ballot",
  agm_egm: "AGM or EGM",
  pledging: "Promoter pledge",
  unclassified: "Other",
};

export function hoursOf(key: WindowKey): number {
  return WINDOWS.find((w) => w.key === key)!.hours;
}

export function within(filings: Filing[], hours: number, now: Date): Filing[] {
  const since = now.getTime() - hours * 3_600_000;
  return filings.filter((f) => new Date(f.filed_at).getTime() >= since);
}

/** One card per event: copies of a letter and companion filings fold into the lead. */
export function leads(filings: Filing[]): Filing[] {
  return filings.filter((f) => f.group_lead !== false && !f.duplicate_of);
}

export function byScore(a: Filing, b: Filing): number {
  return (b.score ?? 0) - (a.score ?? 0) || b.filed_at.localeCompare(a.filed_at);
}

export function todays3(filings: Filing[]): Filing[] {
  return leads(filings).filter((f) => f.tier === "must_see").sort(byScore).slice(0, 3);
}

/**
 * The window to open on. The default is 24 hours, as the brief asks; on a quiet day, or
 * when the data has not refreshed, the smallest window that has something worth seeing,
 * and the app says so rather than showing an empty screen.
 */
export function openingWindow(filings: Filing[], now: Date): { key: WindowKey; widened: boolean } {
  for (const w of WINDOWS) {
    if (todays3(within(filings, w.hours, now)).length > 0) return { key: w.key, widened: w.key !== "24h" };
  }
  return { key: "30d", widened: true };
}

/** A results filing is titled by its numbers: the model's title is often "Results submitted". */
export function title(f: Filing): string {
  const card = f.cards?.find((c): c is ResultsCard => c.type === "results");
  return card ? resultsHeadline(card) : (f.insight?.title ?? f.headline ?? f.exchange_label ?? "Filing");
}

/** "Q2 FY27: revenue −16.5%, profit −53.8% year on year", from the card, not the model. */
export function resultsHeadline(card: ResultsCard): string {
  const signed = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(1)}%`;
  const top = card.metrics[0];
  const pat = card.metrics.find((m) => m.key === "pat");
  const parts = [top, pat]
    .filter((m) => m && m.yoy_pct != null)
    .map((m) => `${m!.key === "pat" ? "profit" : m!.label.toLowerCase()} ${signed(m!.yoy_pct!)}`);
  return parts.length ? `${card.period_label}: ${parts.join(", ")} year on year` : `${card.period_label} results`;
}
