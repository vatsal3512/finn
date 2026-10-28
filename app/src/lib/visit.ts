// "Since your last visit", on this phone. A visit is a fresh look after 30 minutes away,
// so coming back to Today a minute later does not wipe what was new.

const CURRENT = "finn.visit.current.v1";
const PREVIOUS = "finn.visit.previous.v1";
const INTRO = "finn.intro.dismissed.v1";
const NEW_VISIT_AFTER = 30 * 60_000;

function read(key: string): number | null {
  try {
    const v = Number(localStorage.getItem(key));
    return Number.isFinite(v) && v > 0 ? v : null;
  } catch {
    return null;
  }
}

function write(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* private browsing: nothing is remembered between visits */
  }
}

/** When the investor last looked before this visit, or null on a first visit. */
export function previousVisit(now: number): number | null {
  const current = read(CURRENT);
  if (current === null) {
    write(CURRENT, String(now));
    return null;
  }
  if (now - current > NEW_VISIT_AFTER) {
    write(PREVIOUS, String(current));
    write(CURRENT, String(now));
    return current;
  }
  write(CURRENT, String(now));
  return read(PREVIOUS);
}

export function introDismissed(): boolean {
  try {
    return localStorage.getItem(INTRO) === "1";
  } catch {
    return false;
  }
}

export function dismissIntro(): void {
  write(INTRO, "1");
}
