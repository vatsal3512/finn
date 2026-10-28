"use client";

import { useState } from "react";
import type { AskAnswer, Evidence, Filing } from "@/lib/contract";
import { pageLink } from "@/lib/format";
import { contextFor, questionFor } from "@/lib/questions";
import { cx } from "./ui";

type State = { status: "idle" | "loading" | "done" | "error"; answer?: AskAnswer; error?: string };

/**
 * "Was this expected?": what management said about this event on its last two calls, in
 * its own words. When the answer was computed ahead it shows on the card at once, because
 * an alert that explains itself is the point. Otherwise one tap asks live.
 */
export function AskPanel({ filing, ready }: { filing: Filing; ready?: AskAnswer }) {
  return ready ? <Expected a={ready} /> : <AskLive filing={filing} />;
}

function Expected({ a }: { a: AskAnswer }) {
  const [open, setOpen] = useState(false);
  const quotes = a.evidence ?? [];
  return (
    <section className="rounded-xl bg-accent-soft/60 px-3 py-2.5">
      <button onClick={() => setOpen((o) => !o)} aria-expanded={open} className="block w-full text-left">
        <span className="flex items-center justify-between">
          <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-accent">Was this expected?</span>
          <span className="text-[12px] text-accent">
            {open ? "Less" : quotes.length ? `${quotes.length} quote${quotes.length > 1 ? "s" : ""} ›` : "More ›"}
          </span>
        </span>
        <span className={cx("mt-1 block text-[14px] leading-snug", !open && "line-clamp-2")}>
          {open ? a.answer : firstSentences(a.answer, 1)}
        </span>
      </button>
      {open && (
        <div className="fade-in">
          {quotes.map((e, i) => <Quote key={i} e={e} />)}
          <p className="mt-1.5 text-[11px] text-faint">From {a.calls.join(" and ")}. Quotes checked word for word.</p>
        </div>
      )}
    </section>
  );
}

function AskLive({ filing }: { filing: Filing }) {
  const [open, setOpen] = useState(false);
  const [s, setS] = useState<State>({ status: "idle" });

  async function ask() {
    setOpen((o) => !o);
    if (s.status !== "idle") return;
    setS({ status: "loading" });
    try {
      const r = await fetch("/api/ask", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ symbol: filing.symbol, question: questionFor(filing), context: contextFor(filing) }),
      });
      if (!r.ok) throw new Error(((await r.json().catch(() => ({}))) as { detail?: string }).detail ?? `HTTP ${r.status}`);
      setS({ status: "done", answer: (await r.json()) as AskAnswer });
    } catch (e) {
      setS({ status: "error", error: e instanceof Error ? e.message : "Could not reach FINN's server." });
    }
  }

  return (
    <div>
      <button
        onClick={ask}
        className={cx(
          "flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-[13px] font-medium",
          open ? "bg-accent-soft text-accent" : "bg-surface-2 text-text",
        )}
        aria-expanded={open}
      >
        <span>Was this expected? Ask what management said</span>
        <span aria-hidden className="text-faint">{open ? "−" : "+"}</span>
      </button>
      {open && (
        <div className="fade-in mt-2 space-y-2 border-l-2 border-accent pl-3">
          {s.status === "loading" && <p className="text-[13px] text-muted">Reading the last two earnings calls…</p>}
          {s.status === "error" && <p className="text-[13px] text-down">{s.error}</p>}
          {s.status === "done" && s.answer && (
            <>
              <p className="text-[14px] leading-snug">{s.answer.answer}</p>
              {s.answer.evidence?.map((e, i) => <Quote key={i} e={e} />)}
              <p className="text-[11px] text-faint">
                From {s.answer.calls.join(" and ")}. Quotes are checked word for word against the transcripts.
              </p>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function Quote({ e }: { e: Evidence }) {
  return (
    <span className="mt-2 block border-l-2 border-accent/40 pl-2.5 text-[13px]">
      <span className="block leading-snug text-muted">“{e.quote}”</span>
      <a href={pageLink(e.url, e.page)} target="_blank" rel="noopener noreferrer" className="mt-0.5 block text-[12px] text-faint hover:text-accent">
        {e.source}{e.page ? `, p. ${e.page}` : ""} ↗
      </a>
    </span>
  );
}

/** The opening sentences, so the card says the point and the rest waits behind "More". */
function firstSentences(text: string, n: number): string {
  // Split only where a sentence ends and the next begins, not inside "₹2,446.1 crore".
  return text.split(/(?<=[.!?])\s+(?=[A-Z₹“"(])/).slice(0, n).join(" ");
}
