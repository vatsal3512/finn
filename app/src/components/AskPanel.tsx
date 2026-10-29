"use client";

import { useState } from "react";
import type { AskAnswer, Evidence, Filing } from "@/lib/contract";
import { pageLink } from "@/lib/format";
import { contextFor, questionFor } from "@/lib/questions";
import { cx } from "./ui";

class ServerSaid extends Error {}

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
  const [more, setMore] = useState(false);
  const first = firstSentences(a.answer, 2);
  const quote = a.evidence?.[0];
  if (!a.addressed) {
    // "Management did not discuss this on its last two calls" is an answer, but one line's worth.
    return (
      <p className="text-[12px] text-faint">
        <span className="font-semibold uppercase tracking-[0.08em]">Was this expected?</span>{" "}
        Not mentioned on the {a.calls.join(" or ")}.
      </p>
    );
  }
  return (
    <section className="rounded-lg bg-accent-soft/60 px-3 py-2.5">
      <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-accent">Was this expected?</p>
      <p className="mt-1 text-[14px] leading-snug">{more ? a.answer : first}</p>
      {quote && !more && <Quote e={quote} />}
      {more && a.evidence?.map((e, i) => <Quote key={i} e={e} />)}
      <div className="mt-1.5 flex items-center justify-between text-[12px]">
        <span className="text-faint">From {a.calls.join(" and ")}</span>
        {(a.answer !== first || (a.evidence?.length ?? 0) > 1) && (
          <button onClick={() => setMore((m) => !m)} className="text-accent">{more ? "Less" : "More"}</button>
        )}
      </div>
    </section>
  );
}

function AskLive({ filing }: { filing: Filing }) {
  const [open, setOpen] = useState(false);
  const [s, setS] = useState<State>({ status: "idle" });

  async function ask() {
    setOpen((o) => !o);
    if (s.status !== "idle") return;
    await load();
  }

  async function load() {
    setS({ status: "loading" });
    const post = (timeoutMs?: number) =>
      fetch("/api/ask", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ symbol: filing.symbol, question: questionFor(filing), context: contextFor(filing) }),
        signal: timeoutMs ? AbortSignal.timeout(timeoutMs) : undefined,
      });
    try {
      // One quiet retry: while a new version of the server goes live, a request can fail or
      // hang. An answer normally takes 1 to 20 seconds.
      let r = await post(40_000).catch(() => null);
      if (!r || r.status >= 500) {
        await new Promise((res) => setTimeout(res, 2000));
        r = await post();
      }
      if (!r.ok) {
        const detail = ((await r.json().catch(() => ({}))) as { detail?: unknown }).detail;
        throw new ServerSaid(typeof detail === "string" ? detail : "FINN's server could not answer just now.");
      }
      setS({ status: "done", answer: (await r.json()) as AskAnswer });
    } catch (e) {
      setS({ status: "error", error: e instanceof ServerSaid ? e.message : "Could not reach FINN's server." });
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
          {s.status === "error" && (
            <p className="text-[13px] text-down">
              {s.error}{" "}
              <button onClick={load} className="font-semibold underline underline-offset-2">Try again</button>
            </p>
          )}
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
    <figure className="mt-1.5 text-[13px]">
      <blockquote className="leading-snug text-muted">“{e.quote}”</blockquote>
      <figcaption className="mt-0.5 text-[12px] text-faint">
        <a href={pageLink(e.url, e.page)} target="_blank" rel="noopener noreferrer" className="hover:text-accent">
          {e.source}{e.page ? `, p. ${e.page}` : ""} ↗
        </a>
      </figcaption>
    </figure>
  );
}

/** The opening sentences, so the card says the point and the rest waits behind "More". */
function firstSentences(text: string, n: number): string {
  // Split only where a sentence ends and the next begins, not inside "₹2,446.1 crore".
  return text.split(/(?<=[.!?])\s+(?=[A-Z₹“"(])/).slice(0, n).join(" ");
}
