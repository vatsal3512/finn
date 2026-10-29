import Link from "next/link";
import { Wordmark } from "@/components/ui";

export const metadata = { title: "Not found · FINN" };

export default function NotFound() {
  return (
    <main>
      <header className="px-4 pb-3 pt-5">
        <Wordmark />
        <h1 className="text-[22px] font-semibold leading-tight">This page does not exist</h1>
        <p className="mt-1 text-[13px] leading-snug text-muted">The link may be mistyped, or the page may have moved.</p>
      </header>
      <div className="flex gap-4 px-4 text-[14px]">
        <Link href="/" className="text-accent">
          Today
        </Link>
        <Link href="/research" className="text-accent">
          Research a company
        </Link>
      </div>
    </main>
  );
}
