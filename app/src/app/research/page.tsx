import Link from "next/link";
import { SearchBox } from "@/components/research/SearchBox";
import { SectionTitle } from "@/components/ui";
import type { ResearchIndexEntry } from "@/lib/contract";
import { getHoldings, getResearchIndex } from "@/lib/data";

export const metadata = { title: "Research · FINN" };

export default async function ResearchPage() {
  const [index, holdings] = await Promise.all([getResearchIndex(), getHoldings(1)]);
  const owned = new Set(holdings.map((h) => h.symbol));
  const byMisses = (a: ResearchIndexEntry, b: ResearchIndexEntry) => b.missed - a.missed || b.promises - a.promises;
  const outside = index.filter((r) => !owned.has(r.symbol)).sort(byMisses);
  const mine = index.filter((r) => owned.has(r.symbol)).sort(byMisses);
  return (
    <main>
      <header className="px-4 pb-3 pt-5">
        <p className="text-[12px] font-semibold tracking-[0.12em] text-faint">FINN</p>
        <h1 className="text-[22px] font-semibold leading-tight">Did management deliver?</h1>
        <p className="mt-1 text-[13px] leading-snug text-muted">
          Every promise from a company&apos;s last four earnings calls, checked against what it reported. Built only from
          its own transcripts and annual report; every quote is matched word for word.
        </p>
      </header>
      <SearchBox />
      <List title="Research picks" rows={outside} />
      <List title="Your portfolio" rows={mine} />
    </main>
  );
}

function List({ title, rows }: { title: string; rows: ResearchIndexEntry[] }) {
  if (!rows.length) return null;
  return (
    <>
      <SectionTitle aside="missed · kept · open">{title}</SectionTitle>
      <ul className="mx-3 rounded-xl border border-line bg-surface">
        {rows.map((r) => (
          <li key={r.symbol} className="border-t border-line first:border-t-0">
            <Link href={`/research/${r.symbol}`} className="flex items-center gap-3 px-4 py-2.5">
              <span className="min-w-0 flex-1">
                <span className="ticker block text-[13px]">{r.symbol}</span>
                <span className="block truncate text-[12px] text-faint">{r.name}</span>
              </span>
              <span className="num flex gap-3 text-[14px]">
                <span className={r.missed ? "font-semibold text-down" : "text-faint"}>{r.missed}</span>
                <span className={r.kept ? "text-up" : "text-faint"}>{r.kept}</span>
                <span className="text-muted">{r.pending}</span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </>
  );
}
