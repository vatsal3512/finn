import Link from "next/link";
import { Chip, Move, SectionTitle, Sparkline, Wordmark } from "@/components/ui";
import { getFeed, getHoldings, getMeta, getResearchIndex } from "@/lib/data";
import { plain, sessionDay, times } from "@/lib/format";

export const metadata = { title: "Portfolio · FINN" };

const SPARK = 60;

export default async function PortfolioPage() {
  const [holdings, feed, meta, index] = await Promise.all([getHoldings(), getFeed(), getMeta(), getResearchIndex()]);
  const mustSee = feed.filter((f) => f.tier === "must_see").reduce<Record<string, number>>((acc, f) => {
    acc[f.symbol] = (acc[f.symbol] ?? 0) + 1;
    return acc;
  }, {});
  const missed = Object.fromEntries(index.map((r) => [r.symbol, r.missed]));
  // Most attention first: a big move, heavy volume or a must-see filing pushes a holding up.
  const rows = holdings
    .map((h) => {
      const closes = h.series.slice(-SPARK).map((p) => p.close);
      const month = closes.length > 21 ? (closes[closes.length - 1] / closes[closes.length - 22] - 1) * 100 : null;
      const attention =
        Math.abs(h.ret_pct ?? 0) / meta.alert_defaults.price_move_pct +
        (h.vol_ratio ?? 0) / meta.alert_defaults.volume_multiple +
        (mustSee[h.symbol] ?? 0) * 0.5;
      return { h, closes, month, attention };
    })
    .sort((a, b) => b.attention - a.attention);

  return (
    <main>
      <header className="px-4 pb-1 pt-5">
        <Wordmark />
        <h1 className="text-[22px] font-semibold leading-tight">Portfolio</h1>
        <p className="text-[12px] text-faint">
          {holdings.length} holdings · end of day {meta.latest_session ? sessionDay(meta.latest_session) : ""} · most attention first
        </p>
      </header>
      <SectionTitle aside="3 months · close, day · volume, month">Holdings</SectionTitle>
      <ul className="mx-3 rounded-xl border border-line bg-surface">
        {rows.map(({ h, closes, month }) => (
          <li key={h.symbol} className="border-t border-line first:border-t-0">
            <Link href={`/research/${h.symbol}`} className="flex items-center gap-3 px-4 py-2.5">
              <div className="min-w-0 flex-1">
                <p className="flex min-w-0 items-baseline gap-1.5">
                  <span className="ticker shrink-0 text-[13px]">{h.symbol}</span>
                  <span className="truncate text-[12px] text-faint">{h.name}</span>
                </p>
                {(!!mustSee[h.symbol] || !!missed[h.symbol]) && (
                  <p className="mt-1 flex gap-1">
                    {!!mustSee[h.symbol] && <Chip tone="accent">{mustSee[h.symbol]} must-see</Chip>}
                    {!!missed[h.symbol] && <Chip tone="down">{missed[h.symbol]} missed</Chip>}
                  </p>
                )}
              </div>
              {/* Below 360 px a sparkline cannot be read, and it squeezes the names. */}
              <span className="hidden min-[360px]:block"><Sparkline values={closes} /></span>
              <div className="w-[76px] text-right">
                <p className="num text-[13px]">{plain(h.close, 1)}</p>
                <p className="text-[12px]"><Move value={h.ret_pct} /></p>
              </div>
              <div className="w-[52px] text-right text-[12px]">
                <p className={(h.vol_ratio ?? 0) >= meta.alert_defaults.volume_multiple ? "num font-semibold" : "num text-muted"}>
                  {times(h.vol_ratio)}
                </p>
                <p><Move value={month} digits={0} className="text-[11px]" /></p>
              </div>
            </Link>
          </li>
        ))}
      </ul>
      <p className="mx-4 mt-3 text-[11px] text-faint">
        The chart is three months of closes. Volume is the last session&apos;s volume over its 20-day average; the figure under it is the move over the last month. Must-see counts filings in the last 30 days.
      </p>
    </main>
  );
}
