// The question each kind of card asks of management's own words. The same table as the
// pipeline's (backend/finn/research/__main__.py), so a live answer matches a precomputed one.

import type { Filing, ResultsCard } from "./contract";

const QUESTIONS: Record<string, string> = {
  results:
    "What had management said on recent calls about revenue and margins for this period, and does this result match it?",
  management_change: "What has management said on recent calls about leadership, succession or this role?",
  "M&A": "What has management said about this deal: its purpose, its price and how it fits the plan?",
  fund_raise: "What has management said about raising money: how much, why, and what it is for?",
  litigation: "Has management discussed this case or its possible financial impact on its calls?",
  credit_rating: "What has management said about debt, leverage and its credit profile?",
};
const DEFAULT = "What has management said about this on its recent calls?";

export function questionFor(f: Filing): string {
  return QUESTIONS[f.category ?? ""] ?? DEFAULT;
}

export function resultsCard(f: Filing): ResultsCard | undefined {
  return f.cards?.find((c): c is ResultsCard => c.type === "results");
}

export function contextFor(f: Filing): string {
  let ctx = `${f.insight?.title ?? f.headline ?? ""}. ${f.insight?.summary ?? ""}`.trim();
  const card = resultsCard(f);
  if (card) {
    const parts = card.metrics
      .filter((m) => m.current != null && m.yoy_pct != null)
      .map((m) => `${m.label} ₹${m.current!.toFixed(1)} crore (${m.yoy_pct! > 0 ? "+" : ""}${m.yoy_pct!.toFixed(1)}% YoY)`);
    const mg = card.margin_pct;
    if (card.margin_label && mg && mg[0] != null && mg[2] != null) {
      parts.push(`${card.margin_label} ${mg[0]}% against ${mg[2]}% a year ago`);
    }
    ctx += ` ${card.period_label} results: ${parts.join("; ")}.`;
  }
  return ctx.slice(0, 600);
}
