// How FINN writes numbers and times: rupees in crore with Indian grouping, signed
// percentages with a true minus sign, and times in IST, the market's clock.

const IST = "Asia/Kolkata";
const inr = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const inr1 = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 1 });

export function crore(v: number | null | undefined): string {
  if (v == null) return "—";
  const sign = v < 0 ? "−" : "";
  const a = Math.abs(v);
  return `${sign}₹${(a >= 100 ? inr : inr1).format(a)} cr`;
}

export function plain(v: number | null | undefined, digits = 0): string {
  if (v == null) return "—";
  return new Intl.NumberFormat("en-IN", { maximumFractionDigits: digits }).format(v);
}

export function pct(v: number | null | undefined, digits = 1): string {
  if (v == null) return "—";
  const sign = v > 0 ? "+" : v < 0 ? "−" : "";
  return `${sign}${Math.abs(v).toFixed(digits)}%`;
}

export function times(v: number | null | undefined): string {
  return v == null ? "—" : `${v.toFixed(1)}×`;
}

export function tone(v: number | null | undefined): "up" | "down" | "flat" {
  if (v == null || Math.abs(v) < 0.05) return "flat";
  return v > 0 ? "up" : "down";
}

export const toneText = { up: "text-up", down: "text-down", flat: "text-muted" } as const;

function istParts(d: Date) {
  const f = new Intl.DateTimeFormat("en-GB", {
    timeZone: IST, day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false,
  });
  const p = Object.fromEntries(f.formatToParts(d).map((x) => [x.type, x.value]));
  return { day: `${p.day} ${p.month}`, time: `${p.hour}:${p.minute}` };
}

function istDay(d: Date): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: IST }).format(d);
}

/** "14:46" today, "Yesterday 14:46", then "27 Oct 14:46". */
export function when(iso: string, now: Date): string {
  const d = new Date(iso);
  const { day, time } = istParts(d);
  const today = istDay(now);
  const yesterday = istDay(new Date(now.getTime() - 86_400_000));
  if (istDay(d) === today) return time;
  if (istDay(d) === yesterday) return `Yesterday ${time}`;
  return `${day} ${time}`;
}

/** "27 Oct 14:46" in IST, for anything rendered ahead of time. */
export function stamp(iso: string): string {
  const { day, time } = istParts(new Date(iso));
  return `${day} ${time}`;
}

/** "27 Oct" for a session date such as 2026-10-27. */
export function sessionDay(date: string): string {
  const d = new Date(`${date}T10:00:00+05:30`);
  return new Intl.DateTimeFormat("en-GB", { timeZone: IST, day: "numeric", month: "short" }).format(d);
}

/**
 * The refresh runs every 30 minutes, around the clock. Data older than two hours means it
 * has stopped: on 28 Oct 2026 the schedule stopped silently for six hours, and nothing on
 * screen said so.
 */
export function isStale(iso: string, now: Date): boolean {
  return now.getTime() - new Date(iso).getTime() > 2 * 3_600_000;
}

export function ago(iso: string, now: Date): string {
  const mins = Math.max(0, (now.getTime() - new Date(iso).getTime()) / 60_000);
  if (mins < 60) return `${Math.round(mins)}m ago`;
  if (mins < 48 * 60) return `${Math.round(mins / 60)}h ago`;
  return `${Math.round(mins / 1440)}d ago`;
}

export function longDate(d: Date): string {
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: IST, weekday: "short", day: "numeric", month: "short",
  }).format(d);
}

export function pageLink(url: string, page?: number | null): string {
  return page ? `${url}#page=${page}` : url;
}
