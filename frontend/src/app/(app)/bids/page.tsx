"use client";

import { useState } from "react";
import { Badge, Empty, Notice, PageHeader } from "@/components/ui";
import { timeAgo, useApi, type ProposalWithProject } from "@/lib/api";

export default function BidsPage() {
  const { data, error } = useApi<ProposalWithProject[]>("/proposals?status=sent&limit=200");
  const [open, setOpen] = useState<number | null>(null);

  return (
    <>
      <PageHeader title="Bids" subtitle="Bids sent from your account. Status is refreshed from Freelancer every 10 minutes." />
      <Notice>{error}</Notice>
      {data?.length === 0 && <Empty>No bids sent yet.</Empty>}
      <div className="space-y-2">
        {data?.map((bid) => (
          <div key={bid.id} className="rounded-lg border border-zinc-200 bg-white p-4">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <a href={bid.project.url} target="_blank" rel="noreferrer" className="min-w-0 font-medium text-zinc-900 hover:text-indigo-700">
                {bid.project.title}
              </a>
              <Badge>{bid.bid_status ?? "sent"}</Badge>
            </div>
            <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-zinc-500">
              <span>
                {bid.amount} {bid.project.currency}
                {bid.project.type === "hourly" ? "/hr" : ""}
              </span>
              <span>{bid.project.type === "hourly" ? `${bid.period} h/week` : `${bid.period} days`}</span>
              {bid.sent_at && <span>sent {timeAgo(bid.sent_at)}</span>}
              <span>{bid.auto ? "automatic" : "approved by you"}</span>
              <button type="button" className="font-medium text-indigo-700" onClick={() => setOpen(open === bid.id ? null : bid.id)}>
                {open === bid.id ? "Hide proposal" : "Show proposal"}
              </button>
            </div>
            {open === bid.id && <p className="mt-3 whitespace-pre-wrap rounded-md bg-zinc-50 p-3 text-sm text-zinc-700">{bid.text}</p>}
          </div>
        ))}
      </div>
    </>
  );
}
