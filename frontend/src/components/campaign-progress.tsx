import { deliveredCount, totalCount, type CampaignListItem } from "@/lib/api";

/** A bar and "12 / 40 sent" for a campaign's counts. */
export function Progress({ item }: { item: Pick<CampaignListItem, "counts"> }) {
  const total = totalCount(item.counts);
  const done = deliveredCount(item.counts);
  const percent = total ? Math.round((done / total) * 100) : 0;
  return (
    <div className="min-w-32">
      <div className="h-1.5 overflow-hidden rounded-full bg-stone-200">
        <div className="h-full rounded-full bg-brand-500" style={{ width: `${percent}%` }} />
      </div>
      <div className="mt-1 font-mono text-[11px] text-stone-500">
        {done} / {total} sent
      </div>
    </div>
  );
}
