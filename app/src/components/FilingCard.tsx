import Link from "next/link";
import type { AskAnswer, Filing, PeopleCard, PersonChange, ResultsCard } from "@/lib/contract";
import { CATEGORY, title } from "@/lib/feed";
import { crore, plain, stamp, times, tone, toneText, when } from "@/lib/format";
import { AskPanel } from "./AskPanel";
import { Chip, cx, ExternalLink, Move } from "./ui";

type Props = { f: Filing; name?: string; now: Date; ask?: AskAnswer; isNew?: boolean };

/** A Push card. What it shows depends on what the filing is. */
export function FilingCard({ f, name, now, ask, isNew }: Props) {
  const results = f.cards?.find((c): c is ResultsCard => c.type === "results");
  const people = f.cards?.find((c): c is PeopleCard => c.type === "people");
  return (
    <article id={`card-${f.id}`} className="fade-in mx-3 mb-4 scroll-mt-4 rounded-2xl border border-line bg-surface p-4 shadow-[0_1px_2px_rgba(0,0,0,0.04)]">
      <header className="mb-2 flex items-center gap-2 text-[12px]">
        {isNew && <span className="h-2 w-2 shrink-0 rounded-full bg-accent" aria-label="New since your last visit" />}
        <span className="ticker text-[13px]">{f.symbol}</span>
        {name && <span className="truncate text-muted">{name}</span>}
        <span className="ml-auto shrink-0 text-faint">{when(f.filed_at, now)}</span>
      </header>
      <div className="mb-1 flex flex-wrap gap-1">
        {(f.events?.length ? f.events : [f.category ?? "unclassified"]).slice(0, 3).map((e) => (
          <Chip key={e} tone={e === f.category ? "accent" : "plain"}>{CATEGORY[e] ?? e}</Chip>
        ))}
      </div>
      <h3 className="mt-1 text-[17px] font-semibold leading-snug tracking-[-0.01em]">{title(f)}</h3>

      {results ? (
        <ResultsBlock card={results} why={f.insight?.why_it_matters} />
      ) : (
        <>
          {f.insight?.summary && <p className="mt-1.5 text-[14px] text-muted">{f.insight.summary}</p>}
          {f.insight?.why_it_matters && <p className="mt-1.5 text-[14px]">{f.insight.why_it_matters}</p>}
        </>
      )}
      {people && <PeopleBlock changes={people.changes} />}
      {f.insight?.amount_inr_crore != null && !results && (
        <p className="mt-2 text-[13px] text-muted">
          Amount <span className="num text-text">{crore(f.insight.amount_inr_crore)}</span>
        </p>
      )}
      <Reaction f={f} />

      <div className="mt-3 space-y-2">
        <AskPanel filing={f} ready={ask} />
        <div className="flex gap-4 text-[13px]">
          {f.attachment_url && <ExternalLink href={f.attachment_url}>Filing</ExternalLink>}
          <Link href={`/research/${f.symbol}`} className="text-accent">Did management deliver? →</Link>
        </div>
      </div>
    </article>
  );
}

function Reaction({ f }: { f: Filing }) {
  const r = f.price_reaction;
  if (!r || r.ret_pct == null) return null;
  const heavy = (r.vol_ratio ?? 0) >= 2;
  return (
    <p className="mt-2 text-[13px] text-muted">
      Stock <Move value={r.ret_pct} /> that session
      {r.vol_ratio != null && (
        <>
          {" "}on <span className={cx("num", heavy && "text-text")}>{times(r.vol_ratio)}</span> its usual volume
        </>
      )}
    </p>
  );
}

function ResultsBlock({ card, why }: { card: ResultsCard; why?: string | null }) {
  const mg = card.margin_pct ?? [];
  return (
    <div className="mt-2">
      <table className="w-full text-[13px]">
        <thead>
          <tr className="text-[11px] text-faint">
            <th className="py-1 text-left font-normal">{card.period_label} · {card.basis}</th>
            <th className="py-1 text-right font-normal">₹ crore</th>
            <th className="py-1 text-right font-normal">QoQ</th>
            <th className="py-1 text-right font-normal">YoY</th>
          </tr>
        </thead>
        <tbody>
          {card.metrics.map((m) => (
            <tr key={m.key} className="border-t border-line">
              <td className="py-1.5">{m.label}</td>
              <td className="num py-1.5 text-right">{plain(m.current, Math.abs(m.current ?? 0) >= 100 ? 0 : 1)}</td>
              <td className="py-1.5 text-right"><Move value={m.qoq_pct} /></td>
              <td className="py-1.5 text-right"><Move value={m.yoy_pct} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      {card.margin_label && mg[0] != null && (
        <p className="mt-1.5 text-[13px] text-muted">
          {card.margin_label} <span className="num text-text">{mg[0]}%</span>
          {mg[1] != null && <> · <span className="num">{mg[1]}%</span> last quarter</>}
          {mg[2] != null && (
            <> · <span className={cx("num", toneText[tone(mg[0]! - mg[2]!)])}>{mg[2]}%</span> a year ago</>
          )}
        </p>
      )}
      {why && <p className="mt-1.5 text-[14px]">{why}</p>}
      <details className="mt-1.5 text-[12px]">
        <summary className={cx("cursor-pointer list-none", card.verified === false ? "text-warn" : "text-faint")}>
          {card.verified === true && "✓ Checked against screener.in"}
          {card.verified === false && "⚠ Differs from screener.in"}
          {card.verified == null && "Not yet checked against screener.in"}
          <span aria-hidden> · how</span>
        </summary>
        <p className="mt-1 text-faint">{sourceLabel(card.source)}. {card.check_note}</p>
      </details>
    </div>
  );
}

function sourceLabel(s: ResultsCard["source"]): string {
  return {
    xbrl: "From the exchange's XBRL",
    filing_text: "Read from the results PDF",
    filing_image: "Read from the results PDF's page images",
    screener: "From screener.in, not yet checked",
  }[s];
}

const CHANGE: Record<PersonChange["change"], { label: string; tone: "up" | "down" | "plain" | "accent" }> = {
  appointment: { label: "Appointed", tone: "up" },
  reappointment: { label: "Reappointed", tone: "plain" },
  resignation: { label: "Resigned", tone: "down" },
  retirement: { label: "Retiring", tone: "down" },
  cessation: { label: "Leaves", tone: "down" },
  redesignation: { label: "New role", tone: "accent" },
  other: { label: "Change", tone: "plain" },
};

const SHOWN = 3;

function PeopleBlock({ changes }: { changes: PersonChange[] }) {
  // Appointments first: who is coming in matters most, and has a profile.
  const order = ["appointment", "redesignation", "resignation", "cessation", "retirement", "reappointment", "other"];
  const sorted = [...changes].sort((a, b) => order.indexOf(a.change) - order.indexOf(b.change));
  const rest = sorted.length - SHOWN;
  return (
    <ul className="mt-3 space-y-3">
      {sorted.slice(0, SHOWN).map((c) => (
        <li key={`${c.person}-${c.change}`}>
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="font-semibold">{c.person}</span>
            <Chip tone={CHANGE[c.change].tone}>{CHANGE[c.change].label}</Chip>
          </div>
          <p className="text-[13px] text-muted">
            {c.role}
            {c.effective_date && <> · from {c.effective_date}</>}
            {c.reason && <> · {c.reason}</>}
          </p>
          {c.profile && <p className="mt-1 text-[13px] leading-snug">{c.profile}</p>}
          {!!c.previous_roles?.length && (
            <p className="mt-1 text-[12px] text-faint">Before: {c.previous_roles.slice(0, 3).join(" · ")}</p>
          )}
          {c.profile_source && <p className="text-[11px] text-faint">Profile from the original appointment filing.</p>}
        </li>
      ))}
      {rest > 0 && (
        <li className="text-[12px] text-faint">
          and {rest} more {rest === 1 ? "change" : "changes"}: {sorted.slice(SHOWN).map((c) => c.person).join(", ")}
        </li>
      )}
    </ul>
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
      </summary>
      <div className="mt-2 space-y-1.5 pl-[96px] text-[13px]">
        {f.insight?.summary && <p className="text-muted">{f.insight.summary}</p>}
        {f.insight?.why_it_matters && <p>{f.insight.why_it_matters}</p>}
        {!f.insight && f.headline && <p className="text-muted">{f.headline}</p>}
        <div className="flex gap-4">
          {f.attachment_url && <ExternalLink href={f.attachment_url}>Filing</ExternalLink>}
          <span className="text-faint">{CATEGORY[f.category ?? ""] ?? f.category}</span>
        </div>
      </div>
    </details>
  );
}

