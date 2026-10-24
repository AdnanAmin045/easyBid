"use client";

import Link from "next/link";
import { Progress } from "@/components/campaign-progress";
import { Badge, Button, Card, Empty, Loading, Notice, PageHeader, Stat } from "@/components/ui";
import { deliveredCount, useApi, type OutreachOverview } from "@/lib/api";

export default function OutreachOverviewPage() {
  const { data, error } = useApi<OutreachOverview>("/outreach/overview");

  if (error) return <Notice>{error}</Notice>;
  if (!data) return <Loading label="Loading outreach overview…" />;

  return (
    <>
      <PageHeader
        title="Outreach overview"
        subtitle="Send one email to many people, personalised, paced like a person and paused automatically when something goes wrong."
        action={
          <Link href="/outreach/campaigns/new">
            <Button variant="primary">New campaign</Button>
          </Link>
        }
      />

      {data.ai_problem && <Notice tone="amber">AI is not available: {data.ai_problem}. Template campaigns still work.</Notice>}
      {!data.gmail.connected && (
        <Notice tone="amber">
          Gmail is not connected, so nothing can be sent.{" "}
          <Link href="/jobs/settings" className="font-medium underline">
            Connect Gmail
          </Link>
        </Notice>
      )}

      <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Sent in 24 hours" value={`${data.sent_24h} / ${data.daily_limit}`} accent hint="Job applications count too" />
        <Stat label="Running campaigns" value={data.campaigns.running ?? 0} hint={`${data.campaigns.paused ?? 0} paused`} />
        <Stat label="Emails sent" value={deliveredCount(data.recipients)} hint={`${data.recipients.replied ?? 0} replies`} />
        <Stat label="Do not contact" value={data.suppressed} hint="Bounces are added automatically" />
      </div>

      <Card title="Recent campaigns" action={<Link href="/outreach/campaigns" className="text-xs font-medium text-brand-700 hover:underline">View all</Link>}>
        {data.recent.length === 0 ? (
          <Empty>No campaigns yet.</Empty>
        ) : (
          <ul className="-my-2 divide-y divide-stone-200">
            {data.recent.map((c) => (
              <li key={c.id}>
                <Link href={`/outreach/campaigns/${c.id}`} className="flex items-center justify-between gap-4 py-3 hover:bg-stone-50">
                  <span className="min-w-0 truncate text-sm font-medium text-stone-900">{c.name}</span>
                  <span className="flex shrink-0 items-center gap-4">
                    <Progress item={c} />
                    <Badge>{c.status}</Badge>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}
