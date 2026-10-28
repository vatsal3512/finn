"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import type { AskAnswer, Filing, Holding, Meta } from "@/lib/contract";
import { computeAlerts, loadSettings, type PriceAlert } from "@/lib/alerts";
import { CATEGORY, hoursOf, openingWindow, todays3, within, WINDOWS, type WindowKey } from "@/lib/feed";
import { longDate, sessionDay, times } from "@/lib/format";
import { FilingCard, GlanceRow } from "./FilingCard";
import { cx, Move, SectionTitle } from "./ui";

type Props = {
  feed: Filing[];
  holdings: Holding[];
  meta: Meta;
  ask: Record<string, AskAnswer>;
};

export function Today({ feed, holdings, meta, ask }: Props) {
  // "Now" is the phone's clock, so this renders after mount: a static page built hours
  // ago must not decide what "the last 24 hours" means.
  const [now, setNow] = useState<Date | null>(null);
  const [win, setWin] = useState<WindowKey>("24h");
  const [widened, setWidened] = useState(false);
  useEffect(() => {
    const n = new Date();
    const open = openingWindow(feed, n);
    setNow(n);
    setWin(open.key);
    setWidened(open.widened);
  }, [feed]);

  const names = useMemo(() => Object.fromEntries(holdings.map((h) => [h.symbol, h.name])), [holdings]);
  const view = useMemo(() => {
    if (!now) return null;
    const hours = hoursOf(win);
    const inWin = within(feed, hours, now);
    const top = todays3(inWin);
    const shown = new Set(top.map((f) => f.id));
    const rest = inWin.filter((f) => !shown.has(f.id)).sort((a, b) => b.filed_at.localeCompare(a.filed_at));
    const s = loadSettings(meta.alert_defaults);
    const moves = computeAlerts(holdings, [], s, now.getTime() - hours * 3_600_000).alerts as PriceAlert[];
    return {
      top,
      glance: rest.filter((f) => f.tier !== "routine"),
      routine: rest.filter((f) => f.tier === "routine"),
      moves: moves.slice(0, 12),
    };
  }, [feed, holdings, meta, now, win]);

  return (
    <main>
      <header className="flex items-end justify-between px-4 pb-2 pt-5">
        <div>
          <p className="text-[12px] font-semibold tracking-[0.12em] text-faint">FINN</p>
          <h1 className="text-[22px] font-semibold leading-tight">{now ? longDate(now) : "Today"}</h1>
        </div>
        <p className="text-right text-[11px] leading-tight text-faint">
          Prices to {meta.latest_session ? sessionDay(meta.latest_session) : "—"} close
          <br />
          {meta.counts.holdings} holdings
        </p>
      </header>

      <div className="px-4" role="tablist" aria-label="Time window">
        <div className="grid grid-cols-4 rounded-lg bg-surface-2 p-0.5">
          {WINDOWS.map((w) => (
            <button
              key={w.key}
              role="tab"
              aria-selected={win === w.key}
              onClick={() => { setWin(w.key); setWidened(false); }}
              className={cx("rounded-md py-1.5 text-[13px]", win === w.key ? "bg-surface font-semibold shadow-sm" : "text-muted")}
            >
              {w.label}
            </button>
          ))}
        </div>
      </div>

      {!view ? (
        <p className="px-4 py-10 text-center text-[13px] text-faint">Loading…</p>
      ) : (
        <>
          {widened && (
            <p className="mx-4 mt-3 rounded-md bg-warn-soft px-3 py-2 text-[13px] text-warn">
              Quiet: nothing must-see in the last 24 hours. Showing {WINDOWS.find((w) => w.key === win)!.long}.
            </p>
          )}

          {view.moves.length > 0 && (
            <>
              <SectionTitle aside={<Link href="/alerts" className="text-accent">Set thresholds</Link>}>Moves</SectionTitle>
              <div className="flex gap-2 overflow-x-auto px-4 pb-1 [scrollbar-width:none]">
                {view.moves.map((m) => (
                  <Link key={m.id} href={`/research/${m.symbol}`} className="shrink-0 rounded-lg border border-line bg-surface px-3 py-2">
                    <div className="flex items-baseline gap-2">
                      <span className="ticker text-[12px]">{m.symbol}</span>
                      <Move value={m.ret} className="text-[14px] font-semibold" />
                    </div>
                    <p className="num text-[11px] text-faint">
                      {sessionDay(m.date)} · {m.vol != null ? `${times(m.vol)} vol` : ""}
                    </p>
                  </Link>
                ))}
              </div>
            </>
          )}

          <SectionTitle aside={`${view.top.length} of ${view.top.length + view.glance.length + view.routine.length}`}>
            {win === "24h" ? "Today's 3" : "Top 3"}
          </SectionTitle>
          {view.top.length === 0 ? (
            <p className="mx-4 rounded-lg border border-dashed border-line px-4 py-6 text-center text-[13px] text-muted">
              Nothing must-see in {WINDOWS.find((w) => w.key === win)!.long}.
            </p>
          ) : (
            view.top.map((f) => <FilingCard key={f.id} f={f} name={names[f.symbol]} now={now!} ask={ask[f.id]} />)
          )}

          {view.glance.length > 0 && (
            <>
              <SectionTitle aside={view.glance.length}>Worth a glance</SectionTitle>
              <div className="mx-3 rounded-xl border border-line bg-surface">
                {view.glance.map((f) => <GlanceRow key={f.id} f={f} now={now!} />)}
              </div>
            </>
          )}

          {view.routine.length > 0 && <Routine items={view.routine} now={now!} />}
        </>
      )}
    </main>
  );
}

function Routine({ items, now }: { items: Filing[]; now: Date }) {
  const counts = Object.entries(
    items.reduce<Record<string, number>>((acc, f) => {
      const k = CATEGORY[f.category ?? ""] ?? "Other";
      acc[k] = (acc[k] ?? 0) + 1;
      return acc;
    }, {}),
  ).sort((a, b) => b[1] - a[1]);
  return (
    <details className="mx-3 mt-6 rounded-xl border border-line bg-surface">
      <summary className="cursor-pointer list-none px-4 py-3">
        <p className="text-[14px]">
          <span className="font-semibold">{items.length} routine filings</span>
          <span className="text-muted">, hidden</span>
        </p>
        <p className="mt-0.5 text-[12px] text-faint">
          {counts.slice(0, 4).map(([k, n]) => `${n} ${k.toLowerCase()}`).join(" · ")}
          {counts.length > 4 && " · …"}
        </p>
      </summary>
      <div className="border-t border-line">
        {items.map((f) => <GlanceRow key={f.id} f={f} now={now} />)}
      </div>
    </details>
  );
}
