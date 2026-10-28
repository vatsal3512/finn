import { AlertsView } from "@/components/AlertsView";
import { getFeed, getHoldings, getMeta } from "@/lib/data";

export const metadata = { title: "Alerts · FINN" };

export default async function AlertsPage() {
  const [feed, holdings, meta] = await Promise.all([getFeed(), getHoldings(30), getMeta()]);
  return <AlertsView feed={feed} holdings={holdings} meta={meta} />;
}
