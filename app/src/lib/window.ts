// The time window the investor reads in. The brief: "by default the last 24 hours, but
// let me pick the period". Presets for the usual cases, or any custom range of dates.
// One choice drives both Today and Alerts, and is remembered on this phone.

export const PRESETS = [
  { key: "24h", hours: 24, short: "24h", long: "the last 24 hours" },
  { key: "3d", hours: 72, short: "3d", long: "the last 3 days" },
  { key: "7d", hours: 168, short: "7d", long: "the last 7 days" },
  { key: "30d", hours: 720, short: "30d", long: "the last 30 days" },
] as const;
export type PresetKey = (typeof PRESETS)[number]["key"];
export type Window = { key: PresetKey } | { key: "custom"; from: string; to: string }; // YYYY-MM-DD, IST

export const KEPT_DAYS = 30; // how far back the pipeline keeps filings
const STORE = "finn.window.v1";
const IST_OFFSET = "+05:30";

export function istDate(d: Date): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(d);
}

/** [since, until) in milliseconds, and how to say it. */
export function range(w: Window, now: Date): { since: number; until: number; long: string } {
  if (w.key === "custom") {
    const since = new Date(`${w.from}T00:00:00${IST_OFFSET}`).getTime();
    const until = new Date(`${w.to}T23:59:59.999${IST_OFFSET}`).getTime();
    return { since, until: Math.min(until, now.getTime()), long: `${fmt(w.from)} to ${fmt(w.to)}` };
  }
  const p = PRESETS.find((x) => x.key === w.key)!;
  return { since: now.getTime() - p.hours * 3_600_000, until: now.getTime(), long: p.long };
}

function fmt(day: string): string {
  return new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Kolkata", day: "numeric", month: "short" }).format(
    new Date(`${day}T12:00:00${IST_OFFSET}`),
  );
}

/** The window the investor last chose on this phone, if any. */
export function loadWindow(): Window | null {
  try {
    const raw = localStorage.getItem(STORE);
    return raw ? (JSON.parse(raw) as Window) : null;
  } catch {
    return null;
  }
}

export function saveWindow(w: Window): void {
  try {
    localStorage.setItem(STORE, JSON.stringify(w));
  } catch {
    /* private browsing: the choice lasts for this visit */
  }
}

export function sameWindow(a: Window, b: Window): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}
