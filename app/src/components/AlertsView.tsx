"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import type { Filing, Holding, Meta } from "@/lib/contract";
import {
  computeAlerts, IMPORTANT, lastSeen, loadSettings, markSeen, saveSettings,
  type AlertSettings, type PriceAlert,
} from "@/lib/alerts";
import { CATEGORY } from "@/lib/feed";
import { sessionDay, times } from "@/lib/format";
import { loadWindow, range, saveWindow, type Window } from "@/lib/window";
import { WindowPicker } from "./WindowPicker";
import { GlanceRow } from "./FilingCard";
import { cx, Move, SectionTitle, Wordmark } from "./ui";



export function AlertsView({ feed, holdings, meta }: { feed: Filing[]; holdings: Holding[]; meta: Meta }) {
  const [now, setNow] = useState<Date | null>(null);
  const [seenBefore, setSeenBefore] = useState(0);
  const [s, setS] = useState<AlertSettings | null>(null);
  const [editing, setEditing] = useState(false);
  const [win, setWin] = useState<Window>({ key: "7d" });

  useEffect(() => {
    const n = Date.now();
    setNow(new Date(n));
    setSeenBefore(lastSeen(n)); // remember what was new on arrival, then clear the badge
    setS(loadSettings(meta.alert_defaults));
    setWin(loadWindow() ?? { key: "7d" }); // the same window as Today, if one was chosen
    markSeen(n);
  }, [meta]);

  function update(next: AlertSettings) {
    setS(next);
    saveSettings(next);
  }

  function choose(w: Window) {
    setWin(w);
    saveWindow(w);
  }

  const r = now ? range(win, now) : null;
  const run = useMemo(
    () => (now && s ? computeAlerts(holdings, feed, s, range(win, now).since, range(win, now).until) : null),
    [now, s, holdings, feed, win],
  );

  return (
    <main>
      <header className="px-4 pb-1 pt-5">
        <Wordmark />
        <h1 className="text-[22px] font-semibold leading-tight">Alerts</h1>
      </header>

      {s && (
        <section className="mx-3 mt-3 rounded-xl border border-line bg-surface">
          <button onClick={() => setEditing((e) => !e)} className="flex w-full items-center justify-between px-4 py-3 text-left" aria-expanded={editing}>
            <span className="min-w-0">
              <span className="block text-[12px] text-faint">Alert me when</span>
              <span className="mt-1 flex flex-wrap gap-1.5 text-[13px]">
                <span className="num rounded-full bg-surface-2 px-2.5 py-1">price moves ±{s.pricePct}%</span>
                <span className="num rounded-full bg-surface-2 px-2.5 py-1">volume {s.volumeX}× usual</span>
                <span className="rounded-full bg-surface-2 px-2.5 py-1">{s.categories.length} kinds of filing</span>
              </span>
            </span>
            <span className="ml-3 shrink-0 text-[13px] text-accent">{editing ? "Done" : "Change"}</span>
          </button>
          {editing && (
            <div className="space-y-4 border-t border-line px-4 py-4">
              <Stepper label="Price move" value={s.pricePct} unit="%" step={1} min={1} max={20}
                       onChange={(v) => update({ ...s, pricePct: v })} />
              <Stepper label="Volume" value={s.volumeX} unit="× average" step={0.5} min={1.5} max={10}
                       onChange={(v) => update({ ...s, volumeX: v })} />
              <div>
                <p className="mb-2 text-[13px] text-muted">Filings that alert me</p>
                <div className="flex flex-wrap gap-1.5">
                  {[...IMPORTANT, "dividend", "capex", "insider_trading", "press_release"].map((c) => {
                    const on = s.categories.includes(c);
                    return (
                      <button key={c} aria-pressed={on}
                        onClick={() => update({ ...s, categories: on ? s.categories.filter((x) => x !== c) : [...s.categories, c] })}
                        className={cx("rounded-full px-3 py-1 text-[13px] ring-1", on ? "bg-accent-soft text-accent ring-accent/30" : "text-muted ring-line")}
                      >
                        {CATEGORY[c] ?? c}
                      </button>
                    );
                  })}
                </div>
              </div>
              <button className="text-[12px] text-faint underline"
                onClick={() => update({ pricePct: meta.alert_defaults.price_move_pct, volumeX: meta.alert_defaults.volume_multiple, categories: IMPORTANT })}>
                Reset to defaults
              </button>
            </div>
          )}
        </section>
      )}

      {!run || !now ? (
        <p className="px-4 py-10 text-center text-[13px] text-faint">Loading…</p>
      ) : (
        <>
          <div className="mt-4"><WindowPicker value={win} now={now} onChange={choose} /></div>
          <SectionTitle aside={r?.long}>{run.alerts.length} alerts</SectionTitle>
          {run.alerts.length === 0 && (
            <p className="mx-4 text-[13px] text-muted">Nothing crossed your thresholds. Loosen them above to see more.</p>
          )}
          {byDay(run.alerts, now).map(([day, items]) => (
            <section key={day}>
              <h3 className="mx-4 mb-1 mt-4 text-[12px] font-semibold text-muted">{day}</h3>
              <div className="mx-3 rounded-xl border border-line bg-surface">
                {items.map((a) => {
                  const isNew = new Date(a.at).getTime() > seenBefore;
                  return a.kind === "price" ? (
                    <PriceRow key={a.id} a={a} isNew={isNew} />
                  ) : (
                    <div key={a.id} className={cx("relative", isNew && "bg-accent-soft/40")}>
                      {isNew && <Dot />}
                      <GlanceRow f={a.filing} now={now} />
                    </div>
                  );
                })}
              </div>
            </section>
          ))}

          {run.skipped.length > 0 && (
            <p className="mx-4 mt-3 text-[12px] text-faint">
              Not alerted, because the move was a corporate action, not news:{" "}
              {run.skipped.map((x) => `${x.symbol} on ${sessionDay(x.date)} (${x.action})`).join("; ")}.
            </p>
          )}
        </>
      )}
    </main>
  );
}

/** "Today", "Yesterday", then "Mon 26 Oct", in IST. */
function byDay<T extends { at: string }>(alerts: T[], now: Date): [string, T[]][] {
  const fmt = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Kolkata", weekday: "short", day: "numeric", month: "short" });
  const key = (d: Date) => new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(d);
  const today = key(now), yesterday = key(new Date(now.getTime() - 86_400_000));
  const groups = new Map<string, T[]>();
  for (const a of alerts) {
    const d = new Date(a.at);
    const k = key(d);
    const label = k === today ? "Today" : k === yesterday ? "Yesterday" : fmt.format(d);
    groups.set(label, [...(groups.get(label) ?? []), a]);
  }
  return [...groups];
}

function Dot() {
  return <span className="absolute left-1.5 top-4 h-1.5 w-1.5 rounded-full bg-accent" aria-label="new" />;
}

function PriceRow({ a, isNew }: { a: PriceAlert; isNew: boolean }) {
  return (
    <Link href={`/research/${a.symbol}`}
      className={cx("relative flex items-baseline gap-2 border-t border-line px-4 py-2.5 first:border-t-0", isNew && "bg-accent-soft/40")}>
      {isNew && <Dot />}
      <span className="ticker w-[88px] shrink-0 truncate text-[12px]">{a.symbol}</span>
      <span className="min-w-0 flex-1 text-[14px]">
        {/* Both figures always show; the one that crossed a threshold is bold. */}
        <Move value={a.ret} className={a.byPrice ? "font-semibold" : "opacity-70"} />
        <span className={cx("num", a.byVolume ? "font-semibold text-text" : "text-muted")}> · {times(a.vol)} volume</span>
      </span>
      <span className="shrink-0 text-[11px] text-faint">{sessionDay(a.date)}</span>
    </Link>
  );
}

function Stepper({ label, value, unit, step, min, max, onChange }: {
  label: string; value: number; unit: string; step: number; min: number; max: number; onChange: (v: number) => void;
}) {
  const set = (v: number) => onChange(Math.min(max, Math.max(min, Math.round(v * 2) / 2)));
  return (
    <div className="flex items-center justify-between">
      <span className="text-[13px] text-muted">{label}</span>
      <div className="flex items-center gap-2">
        <button onClick={() => set(value - step)} className="h-8 w-8 rounded-md bg-surface-2 text-[16px]" aria-label={`Lower ${label}`}>−</button>
        <span className="num w-[96px] text-center text-[14px]">{value} {unit}</span>
        <button onClick={() => set(value + step)} className="h-8 w-8 rounded-md bg-surface-2 text-[16px]" aria-label={`Raise ${label}`}>+</button>
      </div>
    </div>
  );
}

