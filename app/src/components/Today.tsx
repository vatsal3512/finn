"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import type { AskAnswer, Filing, Holding, Meta } from "@/lib/contract";
import { computeAlerts, loadSettings, type PriceAlert } from "@/lib/alerts";
import { between, byScore, CATEGORY, openingWindow, title, todays3 } from "@/lib/feed";
import { longDate, sessionDay, times, when } from "@/lib/format";
import { dismissIntro, introDismissed, previousVisit } from "@/lib/visit";
import { loadWindow, range, saveWindow, type Window } from "@/lib/window";
import { FilingCard, GlanceRow } from "./FilingCard";
import { cx, Move, SectionTitle, Wordmark } from "./ui";
import { WindowPicker } from "./WindowPicker";

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
  const [win, setWin] = useState<Window>({ key: "24h" });
  const [widened, setWidened] = useState(false);
  const [lastVisit, setLastVisit] = useState<number | null>(null);
  const [intro, setIntro] = useState(false);
  useEffect(() => {
    const n = new Date();
    setNow(n);
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
    if (!now) return null;
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
          <h1 className="mt-1 text-[22px] font-semibold leading-tight">{now ? longDate(now) : "Today"}</h1>
        </div>
        <p className="text-right text-[11px] leading-tight text-faint">
          Prices to {meta.latest_session ? sessionDay(meta.latest_session) : "—"} close
          <br />
          {meta.counts.holdings} holdings
        </p>
      </header>

      {intro && (
        <section className="fade-in mx-3 mb-3 flex items-start gap-3 rounded-2xl border border-line bg-surface p-3.5">
          <div className="min-w-0 flex-1">
            <p className="text-[14px] font-semibold leading-snug">FINN reads your companies&apos; filings, so you don&apos;t have to.</p>
            <div className="mt-2 flex flex-wrap gap-1.5 text-[12px]">
              <a href="#top" className="rounded-full bg-surface-2 px-2.5 py-1">See what matters ↓</a>
              <Link href="/alerts" className="rounded-full bg-surface-2 px-2.5 py-1">Set your alerts</Link>
              <Link href="/research/KAYNES" className="rounded-full bg-surface-2 px-2.5 py-1">Did a company deliver?</Link>
            </div>
          </div>
          <button onClick={() => { dismissIntro(); setIntro(false); }} aria-label="Dismiss" className="-mr-1 -mt-1 h-7 w-7 shrink-0 rounded-full text-faint">✕</button>
        </section>
      )}

      {now && <WindowPicker value={win} now={now} onChange={choose} />}

      {!view ? (
        <p className="px-4 py-10 text-center text-[13px] text-faint">Loading…</p>
      ) : (
        <>
          <Briefing view={view} widened={widened} lastVisit={lastVisit} now={now!} />

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

          <div id="top" className="scroll-mt-2">
            <SectionTitle aside={view.top.length ? `${view.top.length} of ${view.total}` : undefined}>
              {win.key === "24h" ? "Today's 3" : "Top 3"}
            </SectionTitle>
          </div>
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
              <FilingCard key={f.id} f={f} name={names[f.symbol]} now={now!} ask={ask[f.id]} isNew={isNew(f)} />
            ))
          )}

          {view.glance.length > 0 && (
            <>
              <div id="glance" className="scroll-mt-2"><SectionTitle aside={view.glance.length}>Worth a glance</SectionTitle></div>
              <div className="mx-3 rounded-2xl border border-line bg-surface">
                {view.glance.map((f) => <GlanceRow key={f.id} f={f} now={now!} isNew={isNew(f)} />)}
              </div>
            </>
          )}

          {view.routine.length > 0 && <Routine items={view.routine} now={now!} />}
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

/** The filter, made visible: how much FINN read, and how little needs reading. */
function Briefing({ view, widened, lastVisit, now }: { view: View; widened: boolean; lastVisit: number | null; now: Date }) {
  if (view.total === 0) return null;
  const parts = [
    { n: view.routine.length, label: "routine", to: "routine", bar: "bg-faint/40" },
    { n: view.glance.length, label: "worth a look", to: "glance", bar: "bg-accent/40" },
    { n: view.top.length, label: view.top.length === 1 ? "matters" : "matter", to: "top", bar: "bg-accent" },
  ];
  function go(id: string) {
    const el = document.getElementById(id);
    if (el instanceof HTMLDetailsElement) el.open = true;
    el?.scrollIntoView({ behavior: "smooth", block: "start" });
  }
  return (
    <section className="mx-3 mt-3 rounded-2xl border border-line bg-surface px-4 py-3.5">
      <p className="text-[12px] text-faint">
        {widened ? `Quiet day · showing ${view.long}` : view.long.charAt(0).toUpperCase() + view.long.slice(1)}
      </p>
      <div className="mt-2 grid grid-cols-4 items-end gap-1">
        <div>
          <p className="num text-[26px] font-semibold leading-none">{view.total}</p>
          <p className="mt-1 text-[11px] text-muted">filings read</p>
        </div>
        {[...parts].reverse().map((x) => (
          <button key={x.to} onClick={() => go(x.to)} disabled={!x.n} className="text-left disabled:opacity-50">
            <p className={cx("num text-[26px] font-semibold leading-none", x.to === "top" ? "text-accent" : "")}>{x.n}</p>
            <p className="mt-1 text-[11px] text-muted">{x.label} ›</p>
          </button>
        ))}
      </div>
      <div className="mt-3 flex h-2 overflow-hidden rounded-full bg-surface-2" aria-hidden>
        {parts.map((x) => (
          <span key={x.to} className={x.bar} style={{ width: `${(x.n / view.total) * 100}%`, minWidth: x.n ? 6 : 0 }} />
        ))}
      </div>
      {lastVisit && view.fresh > 0 && (
        <p className="mt-2.5 flex items-center gap-1.5 text-[12px] text-accent">
          <span className="h-1.5 w-1.5 rounded-full bg-accent" aria-hidden />
          {view.fresh} new since you last looked, {when(new Date(lastVisit).toISOString(), now)}
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
    <details id="routine" className="mx-3 mt-6 scroll-mt-2 rounded-2xl border border-line bg-surface">
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
