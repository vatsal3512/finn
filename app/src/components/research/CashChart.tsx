import type { CashYear } from "@/lib/contract";

/** Operating cash flow (solid) against net profit (outline), year by year. */
export function CashChart({ years }: { years: CashYear[] }) {
  const ys = years.filter((y) => y.operating_cash_flow != null || y.net_profit != null);
  if (ys.length < 2) return null;
  const W = 320, H = 132, top = 10, bottom = 22;
  const vals = ys.flatMap((y) => [y.operating_cash_flow ?? 0, y.net_profit ?? 0, 0]);
  const hi = Math.max(...vals), lo = Math.min(...vals);
  const span = hi - lo || 1;
  const y = (v: number) => top + ((hi - v) / span) * (H - top - bottom);
  const slot = W / ys.length, bar = Math.min(18, slot / 3.2);
  return (
    <figure>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img"
        aria-label="Operating cash flow against net profit, by financial year">
        <line x1={0} x2={W} y1={y(0)} y2={y(0)} stroke="var(--line)" />
        {ys.map((yr, i) => {
          const cx = slot * i + slot / 2;
          const cfo = yr.operating_cash_flow ?? 0, pat = yr.net_profit ?? 0;
          return (
            <g key={yr.year}>
              <rect x={cx - bar - 1} width={bar} y={Math.min(y(cfo), y(0))} height={Math.max(1, Math.abs(y(cfo) - y(0)))}
                fill={cfo < 0 ? "var(--down)" : "var(--up)"} rx={1.5} />
              <rect x={cx + 1} width={bar} y={Math.min(y(pat), y(0))} height={Math.max(1, Math.abs(y(pat) - y(0)))}
                fill="none" stroke="var(--muted)" strokeWidth={1.2} rx={1.5} />
              <text x={cx} y={H - 6} textAnchor="middle" fontSize={11} fill="var(--faint)">{yr.year}</text>
            </g>
          );
        })}
      </svg>
      <figcaption className="mt-1 flex gap-4 text-[11px] text-faint">
        <span><span className="mr-1 inline-block h-2 w-2 rounded-sm bg-up align-middle" />Operating cash flow</span>
        <span><span className="mr-1 inline-block h-2 w-2 rounded-sm ring-1 ring-muted align-middle" />Net profit</span>
      </figcaption>
    </figure>
  );
}
