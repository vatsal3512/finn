"use client";

import { useState } from "react";
import { istDate, KEPT_DAYS, PRESETS, type Window } from "@/lib/window";
import { cx } from "./ui";

/** Presets in one tap, or "Custom" for any range of dates inside what FINN keeps. */
export function WindowPicker({ value, now, onChange }: { value: Window; now: Date; onChange: (w: Window) => void }) {
  const today = istDate(now);
  const earliest = istDate(new Date(now.getTime() - KEPT_DAYS * 86_400_000));
  const [from, setFrom] = useState(value.key === "custom" ? value.from : istDate(new Date(now.getTime() - 2 * 86_400_000)));
  const [to, setTo] = useState(value.key === "custom" ? value.to : today);
  const custom = value.key === "custom";

  function setRange(f: string, t: string) {
    const [a, b] = f <= t ? [f, t] : [t, f]; // a reversed range is read the sensible way
    setFrom(a);
    setTo(b);
    onChange({ key: "custom", from: a, to: b });
  }

  return (
    <div className="px-4">
      <div className="grid grid-cols-5 rounded-lg bg-surface-2 p-0.5" role="tablist" aria-label="Time window">
        {PRESETS.map((p) => (
          <button key={p.key} role="tab" aria-selected={value.key === p.key} onClick={() => onChange({ key: p.key })}
            className={cx("rounded-md py-1.5 text-[13px]", value.key === p.key ? "bg-surface font-semibold shadow-sm" : "text-muted")}>
            {p.short}
          </button>
        ))}
        <button role="tab" aria-selected={custom} onClick={() => setRange(from, to)}
          className={cx("rounded-md py-1.5 text-[13px]", custom ? "bg-surface font-semibold shadow-sm" : "text-muted")}>
          Custom
        </button>
      </div>
      {custom && (
        <div className="fade-in mt-2 flex items-center gap-2 text-[13px]">
          <label className="flex flex-1 items-center gap-1.5">
            <span className="text-faint">From</span>
            <input type="date" value={from} min={earliest} max={today} onChange={(e) => e.target.value && setRange(e.target.value, to)}
              className="num min-w-0 flex-1 rounded-md border border-line bg-surface px-2 py-1.5" />
          </label>
          <label className="flex flex-1 items-center gap-1.5">
            <span className="text-faint">to</span>
            <input type="date" value={to} min={earliest} max={today} onChange={(e) => e.target.value && setRange(from, e.target.value)}
              className="num min-w-0 flex-1 rounded-md border border-line bg-surface px-2 py-1.5" />
          </label>
        </div>
      )}
      {custom && from < earliest && (
        <p className="mt-1 text-[12px] text-faint">FINN keeps the last {KEPT_DAYS} days of filings.</p>
      )}
    </div>
  );
}
