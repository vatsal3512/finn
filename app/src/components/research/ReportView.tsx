// The research report. No hooks, so the static pages render it on the server and the
// live view renders the same component as its stream completes.

import type { CasePoint, CashQuality, Evidence, Guidance, ResearchReport, Snapshot } from "@/lib/contract";
import { crore, pageLink, pct } from "@/lib/format";
import { Chip, cx, Move, SectionTitle, type ChipTone } from "../ui";
import { CashChart } from "./CashChart";

const VERDICT: Record<Guidance["verdict"], { label: string; tone: ChipTone }> = {
  missed: { label: "Missed", tone: "down" },
  at_risk: { label: "At risk", tone: "warn" },
  beat: { label: "Beat", tone: "up" },
  met: { label: "Kept", tone: "up" },
  on_track: { label: "On track", tone: "accent" },
  pending: { label: "Open", tone: "plain" },
  unclear: { label: "Can't tell", tone: "faint" },
};

export function ReportView({ r }: { r: ResearchReport }) {
  const graded = r.promises.filter((p) => !["pending", "unclear"].includes(p.verdict));
  const open = r.promises.filter((p) => p.verdict === "pending");
  const unclear = r.promises.filter((p) => p.verdict === "unclear");
  const count = (...v: Guidance["verdict"][]) => r.promises.filter((p) => v.includes(p.verdict)).length;
  return (
    <div className="fade-in">
      <SnapshotHeader s={r.snapshot} />

      {r.stats.calls_read === 0 ? (
        // No earnings calls: nothing to hold management to, but the accounts still speak.
        <p className="mx-4 mt-4 rounded-lg bg-warn-soft px-3 py-2.5 text-[14px] leading-snug text-warn">{r.notes?.[0]}</p>
      ) : (
      <>
      <SectionTitle aside={`${r.promises.length} promises from ${r.stats.calls_read} calls`}>Promised vs delivered</SectionTitle>
      <div className="mx-3 grid grid-cols-4 gap-2">
        <Tile n={count("missed")} label="Missed" tone="text-down" />
        <Tile n={count("met", "beat")} label="Kept" tone="text-up" />
        <Tile n={count("at_risk")} label="At risk" tone="text-warn" />
        <Tile n={count("pending", "on_track")} label="Still open" tone="text-muted" />
      </div>
      {r.narrative && <p className="mx-4 mt-3 text-[15px] leading-snug">{r.narrative}</p>}
      {r.promises.length === 0 && (
        <p className="mx-4 mt-3 text-[13px] text-muted">
          Management gave no explicit guidance on its last {r.stats.calls_read} calls. Many large companies choose not to.
        </p>
      )}

      {graded.length > 0 && (
        <ul className="mx-3 mt-3 rounded-xl border border-line bg-surface">{graded.map((p) => <PromiseRow key={p.id} p={p} />)}</ul>
      )}
      {open.length > 0 && <Folded title={`${open.length} still open`} items={open} />}
      {unclear.length > 0 && <Folded title={`${unclear.length} that the documents do not settle`} items={unclear} />}
      </>
      )}

      <CashSection c={r.cash} />

      {(r.bull.length > 0 || r.bear.length > 0) && (
        <>
          <SectionTitle>Bull and bear</SectionTitle>
          <div className="mx-3 space-y-3">
            <Case title="Bull" points={r.bull} tone="text-up" />
            <Case title="Bear" points={r.bear} tone="text-down" />
          </div>
        </>
      )}

      {!!r.notes?.length && r.stats.calls_read > 0 && (
        <ul className="mx-4 mt-5 space-y-1 text-[12px] text-warn">{r.notes!.map((n) => <li key={n}>{n}</li>)}</ul>
      )}
      <Method r={r} />
    </div>
  );
}

export function SnapshotHeader({ s }: { s: Snapshot }) {
  return (
    <div className="px-4">
      {s.about && <p className="text-[14px] leading-snug text-muted">{s.about}</p>}
      {s.latest_quarter && (
        <div className="mt-3 grid grid-cols-3 gap-2 rounded-xl border border-line bg-surface px-3 py-2.5">
          <Fig label={`Revenue ${s.latest_quarter}`} value={crore(s.revenue)} move={s.revenue_yoy} />
          <Fig label="Net profit" value={crore(s.net_profit)} move={s.net_profit_yoy} />
          <Fig label="EBITDA margin" value={s.ebitda_margin == null ? "—" : `${s.ebitda_margin}%`} />
        </div>
      )}
    </div>
  );
}

function Fig({ label, value, move }: { label: string; value: string; move?: number | null }) {
  return (
    <div>
      <p className="text-[11px] text-faint">{label}</p>
      <p className="num text-[15px] font-semibold">{value}</p>
      {move !== undefined && <p className="text-[11px]"><Move value={move} /> <span className="text-faint">YoY</span></p>}
    </div>
  );
}

function Tile({ n, label, tone }: { n: number; label: string; tone: string }) {
  return (
    <div className="rounded-lg border border-line bg-surface px-2 py-2 text-center">
      <p className={cx("num text-[22px] font-semibold leading-none", n ? tone : "text-faint")}>{n}</p>
      <p className="mt-1 text-[11px] text-muted">{label}</p>
    </div>
  );
}

export function PromiseRow({ p }: { p: Guidance }) {
  const v = VERDICT[p.verdict];
  return (
    <li className="border-t border-line first:border-t-0">
      <details>
        <summary className="flex cursor-pointer list-none items-start gap-2 px-4 py-2.5">
          <span className="w-[68px] shrink-0 pt-0.5"><Chip tone={v.tone}>{v.label}</Chip></span>
          <span className="min-w-0 flex-1">
            <span className="block text-[14px] leading-snug">{p.metric}{p.period ? <span className="text-faint"> · {p.period}</span> : null}</span>
            {(p.target || p.actual) && (
              <span className="num block text-[12px] text-muted">
                {p.target ?? "—"}{p.actual ? <> → <span className="text-text">{p.actual}</span></> : null}
              </span>
            )}
            {!!p.revised_from?.length && (
              <span className="num block text-[11px] text-faint">
                Revised from {p.revised_from.map((r) => r.target ?? "—").join(", then ")}
              </span>
            )}
          </span>
        </summary>
        <div className="space-y-2 px-4 pb-3 pl-[88px] text-[13px]">
          {p.revised_from?.map((r) => <Quote key={r.source} label="Earlier" e={r.said} />)}
          <Quote label={p.revised_from?.length ? "Latest" : "Said"} e={p.said} />
          {!!p.repeated_in?.length && <p className="text-[12px] text-faint">Repeated on the {p.repeated_in.join(", ")}.</p>}
          {p.actual_source && <Quote label="Delivered" e={p.actual_source} />}
          {p.note && <p>{p.note}</p>}
          <p className="text-[11px] text-faint">
            {p.verdict_by === "code"
              ? "Verdict computed by code from the reported numbers."
              : "Verdict by the model, from management's own later statements."}
          </p>
        </div>
      </details>
    </li>
  );
}

function Folded({ title, items }: { title: string; items: Guidance[] }) {
  return (
    <details className="mx-3 mt-2 rounded-xl border border-line bg-surface">
      <summary className="cursor-pointer list-none px-4 py-2.5 text-[13px] text-muted">{title} <span aria-hidden>+</span></summary>
      <ul className="border-t border-line">{items.map((p) => <PromiseRow key={p.id} p={p} />)}</ul>
    </details>
  );
}

function Quote({ label, e }: { label: string; e: Evidence }) {
  return (
    <figure>
      <p className="text-[11px] font-semibold uppercase tracking-wide text-faint">{label}</p>
      <blockquote className="leading-snug">“{e.quote}”</blockquote>
      <figcaption className="text-[12px] text-faint">
        {e.url ? (
          <a href={pageLink(e.url, e.page)} target="_blank" rel="noopener noreferrer" className="hover:text-accent">
            {e.source}{e.page ? `, p. ${e.page}` : ""} ↗
          </a>
        ) : e.source}
      </figcaption>
    </figure>
  );
}

export function CashSection({ c }: { c: CashQuality }) {
  return (
    <>
      <SectionTitle aside={c.conversion_5y != null ? `5-year cash conversion ${pct(c.conversion_5y * 100, 0).replace("+", "")}${c.parent_conversion_5y != null ? ` · parent alone ${Math.round(c.parent_conversion_5y * 100)}%` : ""}` : undefined}>
        Do profits turn into cash?
      </SectionTitle>
      <div className="mx-3 rounded-xl border border-line bg-surface p-4">
        {!c.applicable ? (
          <p className="text-[13px] text-muted">{c.reason}</p>
        ) : (
          <>
            {c.read && <p className="mb-3 text-[14px] leading-snug">{c.read}</p>}
            <CashChart years={c.years ?? []} />
            <ul className="mt-3 space-y-1.5 text-[13px] text-muted">
              {(c.signals ?? []).map((s) => <li key={s.quote}>{s.quote}</li>)}
            </ul>
            <p className="mt-2 text-[11px] text-faint">Computed by code from the filed cash-flow statements, via screener.in.</p>
          </>
        )}
      </div>
    </>
  );
}

function Case({ title, points, tone }: { title: string; points: CasePoint[]; tone: string }) {
  if (!points.length) return null;
  return (
    <section className="rounded-xl border border-line bg-surface p-4">
      <h3 className={cx("mb-2 text-[12px] font-semibold uppercase tracking-[0.08em]", tone)}>{title}</h3>
      <ol className="space-y-3">
        {points.map((pt, i) => (
          <li key={i} className="text-[14px] leading-snug">
            {pt.point}
            <details className="mt-1">
              <summary className="cursor-pointer list-none text-[12px] text-accent">
                {pt.evidence.length} source{pt.evidence.length > 1 ? "s" : ""}
              </summary>
              <div className="mt-1.5 space-y-2 border-l-2 border-line pl-3 text-[13px]">
                {pt.evidence.map((e, j) => <Quote key={j} label={e.page ? "Document" : "Accounts"} e={e} />)}
              </div>
            </details>
          </li>
        ))}
      </ol>
    </section>
  );
}

function Method({ r }: { r: ResearchReport }) {
  const s = r.stats;
  return (
    <details className="mx-3 mb-6 mt-5 rounded-xl border border-line bg-surface">
      <summary className="cursor-pointer list-none px-4 py-3 text-[12px] text-muted">
        Built from {s.calls_read} call transcripts{r.documents.some((d) => d.kind === "annual_report") ? " and the annual report" : ""}.{" "}
        <span className="text-text">{s.quotes_verified} of {s.claims_found} quotes</span> found word for word in the documents ·{" "}
        {s.graded_by_code} verdicts by code · {s.ai_calls} AI calls
      </summary>
      <div className="space-y-2 border-t border-line px-4 py-3 text-[12px] text-muted">
        <p>
          FINN reads only the company&apos;s own documents: no news, no broker notes, and no model memory. A model
          lists what management promised; code checks each quote against the transcript and grades every promise
          the reported numbers can settle.
        </p>
        <ul className="space-y-1">
          {r.documents.map((d) => (
            <li key={d.url}>
              <a href={d.url} target="_blank" rel="noopener noreferrer" className="text-accent">{d.label}</a>
              <span className="text-faint"> · {d.pages} pages</span>
            </li>
          ))}
        </ul>
        <p className="text-faint">Models: {s.models.join(", ") || "none"} · {s.seconds.toFixed(0)} s · {r.generated_at.slice(0, 10)}</p>
      </div>
    </details>
  );
}
