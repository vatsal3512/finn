import Link from "next/link";
import type { ReactNode } from "react";
import type { AskAnswer, Filing, PeopleCard, PersonChange, ResultsCard } from "@/lib/contract";
import { CATEGORY, title } from "@/lib/feed";
import { crore, plain, stamp, times, tone, toneText, when } from "@/lib/format";
import { AskPanel } from "./AskPanel";
import { Chip, cx, Move } from "./ui";

type Props = { f: Filing; name?: string; now: Date; ask?: AskAnswer; isNew?: boolean };

/**
 * A Push card. Numbers and short chips up front; anything longer opens on a tap, so the
 * card can be read in one glance and explored in a few.
 */
export function FilingCard({ f, name, now, ask, isNew }: Props) {
  const results = f.cards?.find((c): c is ResultsCard => c.type === "results");
  const people = f.cards?.find((c): c is PeopleCard => c.type === "people");
  return (
    <article id={`card-${f.id}`} className="fade-in mx-3 mb-4 scroll-mt-4 rounded-2xl border border-line bg-surface p-4 shadow-[0_1px_2px_rgba(0,0,0,0.04)]">
      <header className="flex items-center gap-2 text-[12px]">
        {isNew && <span className="h-2 w-2 shrink-0 rounded-full bg-accent" aria-label="New since your last visit" />}
        <span className="ticker text-[13px]">{f.symbol}</span>
        {name && <span className="truncate text-muted">{name}</span>}
        <Chip tone="accent">{CATEGORY[f.category ?? ""] ?? "Other"}</Chip>
        <span className="ml-auto shrink-0 text-faint">{when(f.filed_at, now)}</span>
      </header>
      <h3 className="mt-2 text-[17px] font-semibold leading-snug tracking-[-0.01em]">{title(f)}</h3>

      {results ? (
        <ResultsBlock card={results} f={f} />
      ) : (
        <>
          {f.insight?.summary && <p className="mt-1.5 line-clamp-3 text-[14px] leading-snug text-muted">{f.insight.summary}</p>}
          <div className="mt-2.5 flex flex-wrap gap-1.5">
            {f.insight?.amount_inr_crore != null && <Pill label="Amount" value={crore(f.insight.amount_inr_crore)} />}
            <Reaction f={f} />
          </div>
          {f.insight?.why_it_matters && <Reveal label="Why it matters">{f.insight.why_it_matters}</Reveal>}
        </>
      )}
      {people && <PeopleBlock changes={people.changes} />}

      <div className="mt-3">
        <AskPanel filing={f} ready={ask} />
      </div>
      <div className="mt-3 flex gap-2">
        {f.attachment_url && (
          <a href={f.attachment_url} target="_blank" rel="noopener noreferrer"
            className="flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-line py-2 text-[13px] text-muted active:bg-surface-2">
            <DocIcon /> Filing
          </a>
        )}
        <Link href={`/research/${encodeURIComponent(f.symbol)}`}
          className="flex flex-[1.4] items-center justify-center gap-1.5 rounded-lg bg-surface-2 py-2 text-[13px] font-medium active:opacity-80">
          Did they deliver? <span aria-hidden>→</span>
        </Link>
      </div>
    </article>
  );
}

/** A small labelled figure: "Stock −6.5% · 6.7× vol". */
function Pill({ label, value, children }: { label: string; value?: ReactNode; children?: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-surface-2 px-2.5 py-1 text-[12px]">
      <span className="text-faint">{label}</span>
      <span className="num">{value}{children}</span>
    </span>
  );
}

/** Text that waits behind a tap. */
function Reveal({ label, children }: { label: string; children: ReactNode }) {
  return (
    <details className="group mt-2">
      <summary className="inline-flex cursor-pointer list-none items-center gap-1 text-[13px] text-accent">
        {label} <span className="transition-transform group-open:rotate-90" aria-hidden>›</span>
      </summary>
      <div className="fade-in mt-1 text-[14px] leading-snug">{children}</div>
    </details>
  );
}

function Reaction({ f }: { f: Filing }) {
  const r = f.price_reaction;
  if (!r || r.ret_pct == null) return null;
  return (
    <Pill label="Stock">
      <Move value={r.ret_pct} />
      {r.vol_ratio != null && <span className={cx((r.vol_ratio ?? 0) >= 2 ? "text-text" : "text-faint")}> · {times(r.vol_ratio)} vol</span>}
    </Pill>
  );
}

function ResultsBlock({ card, f }: { card: ResultsCard; f: Filing }) {
  const mg = card.margin_pct ?? [];
  const change = mg[0] != null && mg[2] != null ? mg[0]! - mg[2]! : null;
  return (
    <div className="mt-2">
      <table className="w-full text-[13px]">
        <thead>
          <tr className="text-[11px] text-faint">
            <th className="py-1 text-left font-normal">{card.period_label}</th>
            <th className="py-1 text-right font-normal">₹ crore</th>
            <th className="py-1 text-right font-normal">vs last qtr</th>
            <th className="py-1 text-right font-normal">vs last yr</th>
          </tr>
        </thead>
        <tbody>
          {card.metrics.map((m) => (
            <tr key={m.key} className="border-t border-line">
              <td className="py-1.5">{m.label}</td>
              <td className="num py-1.5 text-right">{plain(m.current, Math.abs(m.current ?? 0) >= 100 ? 0 : 1)}</td>
              <td className="py-1.5 text-right"><Move value={m.qoq_pct} /></td>
              <td className="py-1.5 text-right font-semibold"><Move value={m.yoy_pct} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-2.5 flex flex-wrap gap-1.5">
        {card.margin_label && mg[0] != null && (
          <Pill label={card.margin_label.replace(" margin", "")}>
            {mg[0]}%
            {change != null && (
              <span className={toneText[tone(change)]}> {change >= 0 ? "▲" : "▼"} from {mg[2]}%</span>
            )}
          </Pill>
        )}
        <Reaction f={f} />
        <details className="group">
          <summary className={cx("inline-flex cursor-pointer list-none items-center gap-1 rounded-full px-2.5 py-1 text-[12px]",
            card.verified === false ? "bg-warn-soft text-warn" : card.verified ? "bg-up-soft text-up" : "bg-surface-2 text-faint")}>
            {card.verified === true ? "✓ Verified" : card.verified === false ? "⚠ Mismatch" : "Unchecked"}
          </summary>
          <p className="fade-in mt-1.5 max-w-[300px] text-[12px] leading-snug text-muted">
            {sourceLabel(card.source)}, checked against screener.in. {card.check_note}
          </p>
        </details>
      </div>
    </div>
  );
}

function sourceLabel(s: ResultsCard["source"]): string {
  return {
    xbrl: "From the exchange's own data file",
    filing_text: "Read from the results PDF",
    filing_image: "Read from the results PDF's page images",
    screener: "From screener.in",
  }[s];
}

const CHANGE: Record<PersonChange["change"], { label: string; tone: "up" | "down" | "plain" | "accent" }> = {
  appointment: { label: "Joins", tone: "up" },
  reappointment: { label: "Reappointed", tone: "plain" },
  resignation: { label: "Resigned", tone: "down" },
  retirement: { label: "Retiring", tone: "down" },
  cessation: { label: "Leaves", tone: "down" },
  redesignation: { label: "New role", tone: "accent" },
  other: { label: "Change", tone: "plain" },
};

const SHOWN = 3;

function PeopleBlock({ changes }: { changes: PersonChange[] }) {
  // Who is coming in matters most, and has a profile.
  const order = ["appointment", "redesignation", "resignation", "cessation", "retirement", "reappointment", "other"];
  const sorted = [...changes].sort((a, b) => order.indexOf(a.change) - order.indexOf(b.change));
  const rest = sorted.length - SHOWN;
  return (
    <ul className="mt-3 divide-y divide-line rounded-xl border border-line">
      {sorted.slice(0, SHOWN).map((c) => {
        const more = c.profile || c.previous_roles?.length;
        const row = (
          <span className="flex items-center gap-2">
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[14px] font-semibold">{c.person}</span>
              <span className="block truncate text-[12px] text-muted">{c.role}</span>
            </span>
            <Chip tone={CHANGE[c.change].tone}>{CHANGE[c.change].label}</Chip>
            {more && <span className="text-faint transition-transform group-open:rotate-90" aria-hidden>›</span>}
          </span>
        );
        return (
          <li key={`${c.person}-${c.change}`} className="px-3 py-2">
            {more ? (
              <details className="group">
                <summary className="cursor-pointer list-none">{row}</summary>
                <div className="fade-in mt-2 space-y-1 text-[13px] leading-snug">
                  {c.profile && <p>{c.profile}</p>}
                  {!!c.previous_roles?.length && <p className="text-[12px] text-faint">Before: {c.previous_roles.slice(0, 3).join(" · ")}</p>}
                  {(c.effective_date || c.reason) && (
                    <p className="text-[12px] text-faint">{[c.effective_date && `From ${c.effective_date}`, c.reason].filter(Boolean).join(" · ")}</p>
                  )}
                  {c.profile_source && <p className="text-[11px] text-faint">Profile from the original appointment filing.</p>}
                </div>
              </details>
            ) : row}
          </li>
        );
      })}
      {rest > 0 && (
        <li className="px-3 py-2 text-[12px] text-faint">
          +{rest} more: {sorted.slice(SHOWN).map((c) => c.person).join(", ")}
        </li>
      )}
    </ul>
  );
}

function DocIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" /><path d="M14 3v6h6" />
    </svg>
  );
}

export function GlanceRow({ f, now, isNew }: { f: Filing; now?: Date; isNew?: boolean }) {
  return (
    <details className="group border-t border-line px-4 py-2.5 first:border-t-0">
      <summary className="flex cursor-pointer list-none items-baseline gap-2">
        <span className="ticker relative w-[88px] shrink-0 truncate text-[12px]">
          {isNew && <span className="absolute -left-2.5 top-1.5 h-1.5 w-1.5 rounded-full bg-accent" aria-label="new" />}
          {f.symbol}
        </span>
        <span className="min-w-0 flex-1 text-[14px] leading-snug">{title(f)}</span>
        <span className="shrink-0 text-[11px] text-faint">{now ? when(f.filed_at, now) : stamp(f.filed_at)}</span>
        <span className="text-faint transition-transform group-open:rotate-90" aria-hidden>›</span>
      </summary>
      <div className="fade-in mt-2 space-y-1.5 pl-[96px] text-[13px] leading-snug">
        {f.insight?.summary && <p className="text-muted">{f.insight.summary}</p>}
        {f.insight?.why_it_matters && <p>{f.insight.why_it_matters}</p>}
        {!f.insight && f.headline && <p className="text-muted">{f.headline}</p>}
        <div className="flex items-center gap-3">
          {f.attachment_url && (
            <a href={f.attachment_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-accent">
              <DocIcon /> Filing
            </a>
          )}
          <span className="text-faint">{CATEGORY[f.category ?? ""] ?? f.category}</span>
        </div>
      </div>
    </details>
  );
}

