import Link from "next/link";
import { GlanceRow } from "@/components/FilingCard";
import { LiveResearch } from "@/components/research/LiveResearch";
import { ReportView } from "@/components/research/ReportView";
import { SectionTitle } from "@/components/ui";
import { getFeed, getReport, getResearchIndex } from "@/lib/data";

export async function generateStaticParams() {
  return (await getResearchIndex()).map((r) => ({ symbol: r.symbol }));
}

type Params = { params: Promise<{ symbol: string }> };

export async function generateMetadata({ params }: Params) {
  const { symbol } = await params;
  return { title: `${decodeURIComponent(symbol).toUpperCase()} · FINN` };
}

export default async function CompanyResearch({ params }: Params) {
  const symbol = decodeURIComponent((await params).symbol).toUpperCase();
  const [report, feed] = await Promise.all([getReport(symbol), getFeed()]);
  const recent = feed
    .filter((f) => f.symbol === symbol && f.tier !== "routine")
    .sort((a, b) => b.filed_at.localeCompare(a.filed_at))
    .slice(0, 5);
  return (
    <main>
      <header className="px-4 pb-3 pt-5">
        <Link href="/research" className="text-[12px] text-accent">← Research</Link>
        <h1 className="mt-1 flex items-baseline gap-2">
          <span className="ticker text-[22px]">{symbol}</span>
          {report && <span className="truncate text-[15px] text-muted">{report.name}</span>}
        </h1>
      </header>
      {report ? <ReportView r={report} /> : <LiveResearch symbol={symbol} />}
      {recent.length > 0 && (
        <>
          <SectionTitle aside="last 30 days">Recent filings</SectionTitle>
          <div className="mx-3 mb-6 rounded-xl border border-line bg-surface">
            {recent.map((f) => <GlanceRow key={f.id} f={f} />)}
          </div>
        </>
      )}
    </main>
  );
}
