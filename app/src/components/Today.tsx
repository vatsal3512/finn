"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import type { AskAnswer, Filing, Holding, Meta } from "@/lib/contract";
import { computeAlerts, loadSettings, type PriceAlert } from "@/lib/alerts";
import { between, byScore, CATEGORY, openingWindow, title, todays3 } from "@/lib/feed";
import { ago, isStale, longDate, sessionDay, times, when } from "@/lib/format";
import { dismissIntro, introDismissed, previousVisit } from "@/lib/visit";
import { loadWindow, range, saveWindow, type Window } from "@/lib/window";
import { FilingCard, GlanceRow } from "./FilingCard";
import { Move, SectionTitle, Wordmark } from "./ui";
import { WindowPicker } from "./WindowPicker";

type Props = {
  feed: Filing[];
  holdings: Holding[];
  meta: Meta;
  ask: Record<string, AskAnswer>;
};

export function Today({ feed, holdings, meta, ask }: Props) {
  // The page is built ahead of time, so the first paint measures "the last 24 hours" from
  // when the data was made, and shows the feed at once instead of "Loading…". On mount the
  // phone's clock takes over (live), since a page built hours ago must not decide "today".
  const [now, setNow] = useState<Date>(() => new Date(meta.generated_at));
  const [live, setLive] = useState(false);
  const [win, setWin] = useState<Window>({ key: "24h" });
  const [widened, setWidened] = useState(false);
  const [lastVisit, setLastVisit] = useState<number | null>(null);
  const [intro, setIntro] = useState(false);
  useEffect(() => {
    const n = new Date();
    setNow(n);
    setLive(true);
    setLastVisit(previousVisit(n.getTime()));
    setIntro(!introDismissed());
    const chosen = loadWindow();
    if (chosen) {
      setWin(chosen); // the investor's own choice stands, even if it is quiet
    } else {
      const open = openingWindow(feed, n);
      setWin({ key: open.key });
      setWidened(open.widened);
    }
  }, [feed]);

  function choose(w: Window) {
    setWin(w);
    setWidened(false);
    saveWindow(w);
  }

  const names = useMemo(() => Object.fromEntries(holdings.map((h) => [h.symbol, h.name])), [holdings]);
  const view = useMemo(() => {
    const r = range(win, now);
    const inWin = between(feed, r.since, r.until);
    const top = todays3(inWin);
    const shown = new Set(top.map((f) => f.id));
    const rest = inWin.filter((f) => !shown.has(f.id)).sort((a, b) => b.filed_at.localeCompare(a.filed_at));
    const moves = computeAlerts(holdings, [], loadSettings(meta.alert_defaults), r.since, r.until).alerts as PriceAlert[];
    const fresh = lastVisit ? inWin.filter((f) => new Date(f.filed_at).getTime() > lastVisit).length : 0;
    return {
      long: r.long,
      lead: win.key === "custom" ? `From ${r.long}` : `In ${r.long}`,
      total: inWin.length,
      top,
      glance: rest.filter((f) => f.tier !== "routine"),
      routine: rest.filter((f) => f.tier === "routine"),
      moves: moves.slice(0, 12),
      fresh,
      latest: [...feed].sort(byScore).find((f) => f.tier === "must_see"),
    };
  }, [feed, holdings, meta, now, win, lastVisit]);

  const isNew = (f: Filing) => !!lastVisit && new Date(f.filed_at).getTime() > lastVisit;

  return (
    <main>
      <header className="flex items-end justify-between px-4 pb-3 pt-5">
        <div>
          <Wordmark />
          <h1 className="mt-1 text-[22px] font-semibold leading-tight">{live ? longDate(now) : "Today"}</h1>
        </div>
        <p className="text-right text-[11px] leading-tight text-faint">
          Prices to {meta.latest_session ? sessionDay(meta.latest_session) : "—"} close
          <br />
          {live ? <>Updated {ago(meta.generated_at, now)}</> : <>{meta.counts.holdings} holdings</>}
        </p>
      </header>

      {live && isStale(meta.generated_at, now) && (
        <p role="status" className="mx-3 mb-3 rounded-xl bg-warn-soft px-3.5 py-2.5 text-[13px] text-warn">
          Last update {ago(meta.generated_at, now)}. Filings since then are not shown yet.
        </p>
      )}

      {intro && (
        <section className="fade-in mx-3 mb-3 rounded-2xl border border-line bg-surface p-4">
          <p className="text-[15px] font-semibold">FINN reads your companies&apos; filings so you don&apos;t have to.</p>
          <p className="mt-1 text-[13px] leading-snug text-muted">
            Every filing from your 18 holdings is read and sorted. You see the few that matter, each with what
            management said about it beforehand. Three things to try:
          </p>
          <ol className="mt-2 list-decimal space-y-1 pl-5 text-[13px]">
            <li>Read the cards below, then change the time window above them.</li>
            <li><Link href="/alerts" className="text-accent">Alerts</Link>: set your own price and volume limits.</li>
            <li><Link href="/research/KAYNES" className="text-accent">Research</Link>: see whether a company kept its promises. Try any NSE company.</li>
          </ol>
          <button onClick={() => { dismissIntro(); setIntro(false); }} className="mt-3 text-[13px] font-medium text-accent">
            Got it
          </button>
        </section>
      )}

      <WindowPicker value={win} now={now} onChange={choose} />

      {(
        <>
          <Briefing view={view} widened={widened} lastVisit={lastVisit} now={now} />

          {view.moves.length > 0 && (
            <>
              <SectionTitle aside={<Link href="/alerts" className="text-accent">Set limits</Link>}>Big moves</SectionTitle>
              <div className="flex gap-2 overflow-x-auto px-4 pb-1 [scrollbar-width:none]">
                {view.moves.map((m) => (
                  <Link key={m.id} href={`/research/${encodeURIComponent(m.symbol)}`} className="shrink-0 rounded-lg border border-line bg-surface px-3 py-2">
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

          <SectionTitle aside={view.top.length ? `${view.top.length} of ${view.total}` : undefined}>
            {win.key === "24h" ? "Today's 3" : "Top 3"}
          </SectionTitle>
          {view.top.length === 0 ? (
            <div className="mx-4 rounded-lg border border-dashed border-line px-4 py-6 text-center text-[13px] text-muted">
              <p>Nothing must-see in {view.long}.</p>
              {view.latest && win.key !== "30d" && (
                <button onClick={() => choose({ key: "30d" })} className="mt-2 text-accent">
                  Show the last 30 days
                </button>
              )}
            </div>
          ) : (
            view.top.map((f) => (
              <FilingCard key={f.id} f={f} name={names[f.symbol]} now={now} ask={ask[f.id]} isNew={isNew(f)} />
            ))
          )}

          {view.glance.length > 0 && (
            <>
              <SectionTitle aside={view.glance.length}>Worth a glance</SectionTitle>
              <div className="mx-3 rounded-2xl border border-line bg-surface">
                {view.glance.map((f) => <GlanceRow key={f.id} f={f} now={now} isNew={isNew(f)} />)}
              </div>
            </>
          )}

          {view.routine.length > 0 && <Routine items={view.routine} now={now} />}
        </>
      )}
    </main>
  );
}

type View = {
  long: string;
  lead: string;
  total: number;
  top: Filing[];
  glance: Filing[];
  routine: Filing[];
  fresh: number;
};

/** The filter, made visible: how much was read, and how little needs reading. */
function Briefing({ view, widened, lastVisit, now }: { view: View; widened: boolean; lastVisit: number | null; now: Date }) {
  if (view.total === 0) return null;
  return (
    <section className="mx-3 mt-3 rounded-2xl border border-line bg-surface px-4 py-3.5">
      {widened && <p className="mb-1.5 text-[12px] text-warn">Quiet day: nothing must-see in the last 24 hours.</p>}
      <p className="text-[15px] leading-snug">
        {view.lead}, FINN read <b className="num">{view.total}</b> filings from your companies.{" "}
        <b className="num">{view.top.length}</b> {view.top.length === 1 ? "matters" : "matter"},{" "}
        <span className="num">{view.glance.length}</span> are worth a glance and{" "}
        <span className="num">{view.routine.length}</span> are routine.
      </p>
      {view.top.length > 0 && (
        <ol className="mt-2.5 space-y-1.5">
          {view.top.map((f, i) => (
            <li key={f.id}>
              <a href={`#card-${f.id}`} className="flex gap-2 text-[13px] leading-snug">
                <span className="num w-3 shrink-0 text-faint">{i + 1}</span>
                <span><span className="ticker text-[12px]">{f.symbol}</span> <span className="text-muted">{title(f)}</span></span>
              </a>
            </li>
          ))}
        </ol>
      )}
      {lastVisit && view.fresh > 0 && (
        <p className="mt-2.5 flex items-center gap-1.5 text-[12px] text-accent">
          <span className="h-1.5 w-1.5 rounded-full bg-accent" aria-hidden />
          {view.fresh} new since your last visit, {when(new Date(lastVisit).toISOString(), now)}
        </p>
      )}
    </section>
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
    <details className="mx-3 mt-6 rounded-2xl border border-line bg-surface">
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
