// Triggered alerts, computed on the phone from end-of-day data, so the investor's
// thresholds take effect instantly with no server: thresholds live in the app.

import type { Filing, Holding } from "./contract";

export type AlertSettings = { pricePct: number; volumeX: number; categories: string[] };
export type Defaults = { price_move_pct: number; volume_multiple: number };

export const IMPORTANT = [
  "results", "M&A", "management_change", "fund_raise", "litigation", "pledging", "credit_rating",
];

type AlertFiling = Pick<Filing, "id" | "filed_at" | "category" | "tier" | "group_lead" | "duplicate_of">;
type AlertHolding = Pick<Holding, "symbol" | "name" | "series">;

export type PriceAlert = {
  kind: "price";
  id: string;
  symbol: string;
  name: string;
  date: string;
  at: string; // the session's close, 15:30 IST
  close: number;
  ret: number | null;
  vol: number | null;
  byPrice: boolean;
  byVolume: boolean;
};

export type FilingAlert<F> = { kind: "filing"; id: string; at: string; filing: F };
export type Alert<F> = PriceAlert | FilingAlert<F>;
export type Skipped = { symbol: string; date: string; action: string };

const STORE = "finn.alerts.v1";
const SEEN = "finn.alerts.seen.v1";
export const SEEN_EVENT = "finn:alerts-seen";

export function loadSettings(d: Defaults): AlertSettings {
  const base = { pricePct: d.price_move_pct, volumeX: d.volume_multiple, categories: IMPORTANT };
  try {
    const raw = localStorage.getItem(STORE);
    return raw ? { ...base, ...JSON.parse(raw) } : base;
  } catch {
    return base;
  }
}

export function saveSettings(s: AlertSettings): void {
  try {
    localStorage.setItem(STORE, JSON.stringify(s));
  } catch {
    /* private browsing: the settings last for this visit */
  }
  window.dispatchEvent(new Event(SEEN_EVENT));
}

/** When the inbox was last opened. A first visit counts the last day as new. */
export function lastSeen(now: number): number {
  try {
    return Number(localStorage.getItem(SEEN)) || now - 86_400_000;
  } catch {
    return now - 86_400_000;
  }
}

export function markSeen(t: number): void {
  try {
    localStorage.setItem(SEEN, String(t));
  } catch {
    /* ignore */
  }
  window.dispatchEvent(new Event(SEEN_EVENT));
}

export function computeAlerts<F extends AlertFiling>(
  holdings: AlertHolding[], filings: F[], s: AlertSettings, sinceMs: number, untilMs = Infinity,
): { alerts: Alert<F>[]; skipped: Skipped[] } {
  const alerts: Alert<F>[] = [];
  const skipped: Skipped[] = [];
  for (const h of holdings) {
    for (const p of h.series) {
      const at = `${p.date}T15:30:00+05:30`;
      const t = new Date(at).getTime();
      if (t < sinceMs || t > untilMs) continue;
      const byPrice = p.ret_pct != null && Math.abs(p.ret_pct) >= s.pricePct;
      const byVolume = p.vol_ratio != null && p.vol_ratio >= s.volumeX;
      if (!byPrice && !byVolume) continue;
      if (p.corp_action) {
        // A demerger or split moves the price mechanically; it is not news.
        skipped.push({ symbol: h.symbol, date: p.date, action: p.corp_action });
        continue;
      }
      alerts.push({
        kind: "price", id: `px:${h.symbol}:${p.date}`, symbol: h.symbol, name: h.name, date: p.date,
        at, close: p.close, ret: p.ret_pct ?? null, vol: p.vol_ratio ?? null, byPrice, byVolume,
      });
    }
  }
  for (const f of filings) {
    if (f.group_lead === false || f.duplicate_of) continue;
    const ft = new Date(f.filed_at).getTime();
    if (ft < sinceMs || ft > untilMs) continue;
    // Only material filings alert, as the brief asks; the rest wait in the digest.
    if (f.tier !== "must_see" || !s.categories.includes(f.category ?? "")) continue;
    alerts.push({ kind: "filing", id: f.id, at: f.filed_at, filing: f });
  }
  alerts.sort((a, b) => new Date(b.at).getTime() - new Date(a.at).getTime());
  return { alerts, skipped };
}
