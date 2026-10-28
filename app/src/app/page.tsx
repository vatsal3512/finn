import { Today } from "@/components/Today";
import { getAsk, getFeed, getHoldings, getMeta } from "@/lib/data";

export default async function TodayPage() {
  const [feed, holdings, meta, ask] = await Promise.all([getFeed(), getHoldings(30), getMeta(), getAsk()]);
  return <Today feed={feed} holdings={holdings} meta={meta} ask={ask} />;
}
