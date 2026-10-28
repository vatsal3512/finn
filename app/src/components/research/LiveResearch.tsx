"use client";

import { useEffect, useState } from "react";
import type { CashQuality, Guidance, ResearchReport, Snapshot } from "@/lib/contract";
import { CashSection, PromiseRow, ReportView, SnapshotHeader } from "./ReportView";
import { SectionTitle } from "../ui";

type Event = {
  stage: "gather" | "cash" | "claims" | "graded" | "done" | "error";
  message: string;
  cash?: CashQuality;
  snapshot?: Snapshot;
  report?: ResearchReport;
  promises?: Guidance[];
  total?: number;
  not_found?: boolean;
  notes?: string[];
};

const STEPS = [
  { stage: "gather", label: "Collecting the last four call transcripts and the annual report" },
  { stage: "cash", label: "Computing cash quality from the accounts" },
  { stage: "claims", label: "Reading every call for what management promised" },
  { stage: "graded", label: "Grading promises against reported numbers" },
  { stage: "done", label: "Weighing what the numbers cannot settle" },
] as const;

/** Research on a ticker nobody computed ahead: streamed from the API stage by stage. */
export function LiveResearch({ symbol }: { symbol: string }) {
  const [events, setEvents] = useState<Event[]>([]);
  const [report, setReport] = useState<ResearchReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [started] = useState(() => Date.now());
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const t = setInterval(() => setElapsed(Math.round((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(t);
  }, [started]);

  useEffect(() => {
    const ctrl = new AbortController();
    (async () => {
      try {
        const r = await fetch(`/api/research/${encodeURIComponent(symbol)}`, { signal: ctrl.signal });
        if (!r.ok || !r.body) throw new Error(r.status === 422 ? "That is not an NSE symbol." : `FINN's server answered ${r.status}.`);
        const reader = r.body.getReader();
        const dec = new TextDecoder();
        let buf = "";
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += dec.decode(value, { stream: true });
          let nl: number;
          while ((nl = buf.indexOf("\n")) >= 0) {
            const line = buf.slice(0, nl).trim();
            buf = buf.slice(nl + 1);
            if (!line) continue;
            const ev = JSON.parse(line) as Event;
            setEvents((e) => [...e, ev]);
            if (ev.stage === "done" && ev.report) setReport(ev.report);
            if (ev.stage === "error") {
              setError(ev.message);
              setNotFound(!!ev.not_found);
            }
          }
        }
      } catch (e) {
        if (!ctrl.signal.aborted) setError(e instanceof Error ? e.message : "Could not reach FINN's server.");
      }
    })();
    return () => ctrl.abort();
  }, [symbol]);

  if (report) return <ReportView r={report} />;
  // A step is done when the event that completes it arrives, not when it starts.
  const ORDER = ["gather", "cash", "claims", "graded", "done"];
  const DONE_AT = [1, 1, 2, 3, 4];
  const reached = Math.max(-1, ...events.map((e) => ORDER.indexOf(e.stage)));
  const last = events[events.length - 1];
  // What is already known is shown while the rest is worked out.
  const snapshot = [...events].reverse().find((e) => e.snapshot)?.snapshot;
  const cash = events.find((e) => e.cash)?.cash;
  const graded = events.find((e) => e.stage === "graded");
  return (
    <>
    <div className="px-4">
      {notFound ? (
        <p className="text-[14px] text-muted">{error}</p>
      ) : (
        <p className="text-[14px] text-muted">
          FINN has not researched {symbol} before. It is reading the company&apos;s own documents now, which takes one to three minutes. What is settled appears below as it is found.
        </p>
      )}
      {!notFound && (
      <>
      <ol className="mt-4 space-y-2.5">
        {STEPS.map((s, i) => {
          const done = reached >= DONE_AT[i];
          const current = !done && (i === 0 || reached >= DONE_AT[i - 1]);
          const failed = current && !!error;
          return (
            <li key={s.stage} className="flex gap-3 text-[14px]">
              <span className={done ? "text-up" : failed ? "text-down" : current ? "text-accent" : "text-faint"} aria-hidden>
                {done ? "✓" : failed ? "✕" : current ? "●" : "○"}
              </span>
              <span className={done ? "" : current ? "text-text" : "text-faint"}>{s.label}</span>
            </li>
          );
        })}
      </ol>
      {last && !error && <p className="num mt-4 text-[12px] text-faint">{last.message} · {elapsed}s</p>}
      {error && <p className="mt-4 rounded-md bg-down-soft px-3 py-2 text-[13px] text-down">{error}</p>}
      </>
      )}
      {notFound && (
        <a href="/research" className="mt-4 inline-block text-[14px] text-accent">← Search for a company</a>
      )}
    </div>
    {snapshot && <div className="mt-5"><SnapshotHeader s={snapshot} /></div>}
    {graded?.promises && (
      <>
        <SectionTitle aside={`${graded.promises.length} of ${graded.total} so far`}>Settled by the numbers</SectionTitle>
        {graded.promises.length > 0 ? (
          <ul className="mx-3 rounded-xl border border-line bg-surface">
            {graded.promises.map((p) => <PromiseRow key={p.id} p={p} />)}
          </ul>
        ) : (
          <p className="mx-4 text-[13px] text-muted">No promise could be checked against reported numbers; the rest are being weighed.</p>
        )}
      </>
    )}
    {cash && <CashSection c={cash} />}
    </>
  );
}
