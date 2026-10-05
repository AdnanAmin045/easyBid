"use client";

import { useState } from "react";
import { ListBody, Pagination, SearchInput, emptyMessage } from "@/components/list";
import { Badge, Empty, Notice, PageHeader, Select } from "@/components/ui";
import { timeAgo, usePaged, type ProposalWithProject } from "@/lib/api";

const BID_STATUSES = ["", "active", "awarded", "rejected", "revoked", "retracted"];

export default function BidsPage() {
  const [bidStatus, setBidStatus] = useState("");
  const { data, error, loading, fetching, setPage, q, search } = usePaged<ProposalWithProject>("/proposals", {
    filters: { status: "sent", bid_status: bidStatus },
  });
  const [open, setOpen] = useState<number | null>(null);

  return (
    <>
      <PageHeader
        title="Bids"
        subtitle="Bids sent from your account. Status is refreshed from Freelancer every 10 minutes."
        action={
          <div className="flex flex-wrap gap-2">
            <SearchInput onSearch={search} placeholder="Search project or proposal text" />
            <div className="w-40">
              <Select aria-label="Bid status" value={bidStatus} onChange={(e) => setBidStatus(e.target.value)}>
                {BID_STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {s || "All bid statuses"}
                  </option>
                ))}
              </Select>
            </div>
          </div>
        }
      />
      <Notice>{error}</Notice>
      <ListBody loading={loading} fetching={fetching}>
        {data?.total === 0 && <Empty>{emptyMessage(Boolean(q || bidStatus), "No bids sent yet.")}</Empty>}
        <div className="space-y-2">
          {data?.items.map((bid) => (
            <div key={bid.id} className="rounded-lg border border-stone-200 bg-white p-4">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <a href={bid.project.url} target="_blank" rel="noreferrer" className="min-w-0 font-medium text-stone-900 hover:text-brand-700">
                  {bid.project.title}
                </a>
                <Badge>{bid.bid_status ?? "sent"}</Badge>
              </div>
              <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-stone-500">
                <span>
                  {bid.amount} {bid.project.currency}
                  {bid.project.type === "hourly" ? "/hr" : ""}
                </span>
                <span>{bid.project.type === "hourly" ? `${bid.period} h/week` : `${bid.period} days`}</span>
                {bid.sent_at && <span>sent {timeAgo(bid.sent_at)}</span>}
                <span>{bid.auto ? "automatic" : "approved by you"}</span>
                <button type="button" className="font-medium text-brand-700" onClick={() => setOpen(open === bid.id ? null : bid.id)}>
                  {open === bid.id ? "Hide proposal" : "Show proposal"}
                </button>
              </div>
              {open === bid.id && <p className="mt-3 whitespace-pre-wrap rounded-md bg-stone-50 p-3 text-sm text-stone-700">{bid.text}</p>}
            </div>
          ))}
        </div>
      </ListBody>
      <Pagination data={data} fetching={fetching} onPage={setPage} />
    </>
  );
}
