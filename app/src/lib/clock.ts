"use client";

import { useEffect } from "react";

/**
 * Keeps a screen's "now" current while it stays open. An installed app can sit in the
 * background for hours; without this, "Updated 19m ago" and the stale warning would stay
 * as they were when the page loaded.
 */
export function useTicking(setNow: (d: Date) => void, everyMs = 60_000) {
  useEffect(() => {
    const tick = () => setNow(new Date());
    const back = () => document.visibilityState === "visible" && tick();
    const t = setInterval(tick, everyMs);
    document.addEventListener("visibilitychange", back);
    return () => {
      clearInterval(t);
      document.removeEventListener("visibilitychange", back);
    };
  }, [setNow, everyMs]);
}
