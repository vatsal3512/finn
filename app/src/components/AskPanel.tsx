"use client";

import { useState } from "react";
import type { AskAnswer, Filing } from "@/lib/contract";
import { contextFor, questionFor } from "@/lib/questions";
import { pageLink } from "@/lib/format";
import { cx } from "./ui";

type State = { status: "idle" | "loading" | "done" | "error"; answer?: AskAnswer; error?: string };

/**
 * "Ask about this": what management said about this event on its last two calls, in its
 * own words. Answers for the top cards are computed ahead; others are asked live.
 */
export function AskPanel({ filing, ready }: { filing: Filing; ready?: AskAnswer }) {
  const [open, setOpen] = useState(false);
  const [s, setS] = useState<State>(ready ? { status: "done", answer: ready } : { status: "idle" });

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
        <span>What did management say about this?</span>
        <span aria-hidden className="text-faint">{open ? "−" : "+"}</span>
      </button>
      {open && (
        <div className="fade-in mt-2 space-y-2 border-l-2 border-accent pl-3">
          {s.status === "loading" && <p className="text-[13px] text-muted">Reading the last two earnings calls…</p>}
          {s.status === "error" && <p className="text-[13px] text-down">{s.error}</p>}
          {s.status === "done" && s.answer && <Answer a={s.answer} />}
        </div>
      )}
    </div>
  );
}

function Answer({ a }: { a: AskAnswer }) {
  return (
    <>
      <p className="text-[14px] leading-snug">{a.answer}</p>
      {a.evidence?.map((e, i) => (
        <figure key={i} className="text-[13px]">
          <blockquote className="text-muted">“{e.quote}”</blockquote>
          <figcaption className="mt-0.5 text-[12px] text-faint">
            <a href={pageLink(e.url, e.page)} target="_blank" rel="noopener noreferrer" className="hover:text-accent">
              {e.source}{e.page ? `, p. ${e.page}` : ""} ↗
            </a>
          </figcaption>
        </figure>
      ))}
      <p className="text-[11px] text-faint">
        From {a.calls.join(" and ")}. Quotes are checked word for word against the transcripts.
      </p>
    </>
  );
}
