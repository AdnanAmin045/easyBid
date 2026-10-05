"use client";

import Link from "next/link";
import { Badge, Button, Card, Empty, Loading, Notice, PageHeader, Stat } from "@/components/ui";
import { timeAgo, useApi, type JobsOverview } from "@/lib/api";

export default function JobsOverviewPage() {
  const { data, error } = useApi<JobsOverview>("/jobs/overview");

  if (error) return <Notice>{error}</Notice>;
  if (!data) return <Loading label="Loading jobs overview…" />;

  const setup = [
    { done: data.gmail.connected, text: "Connect your Gmail", href: "/jobs/settings" },
    { done: data.resumes > 0, text: "Upload a CV", href: "/jobs/profile" },
    { done: data.profile_items > 0, text: "Describe your experience", href: "/jobs/profile" },
    { done: data.prompt_active, text: "Save your own writing prompt (optional, a built-in one is used)", href: "/jobs/prompt" },
  ];
  const remaining = setup.filter((step) => !step.done);

  return (
    <>
      <PageHeader
        title="Jobs overview"
        subtitle="Paste a job description, review the application the AI writes, and send it from your own Gmail."
        action={
          <Link href="/jobs/compose">
            <Button variant="primary">New application</Button>
          </Link>
        }
      />

      {data.ai_problem && <Notice>AI is not available: {data.ai_problem}.</Notice>}

      {remaining.length > 0 && (
        <Card title={`Setup · ${setup.length - remaining.length} of ${setup.length} done`} className="mb-6">
          <ol className="grid gap-2 sm:grid-cols-2">
            {setup.map((step, i) => (
              <li key={step.text} className="flex items-center gap-3 text-sm">
                <span
                  className={`grid h-5 w-5 shrink-0 place-items-center rounded-[4px] font-mono text-[10px] ${
                    step.done ? "bg-emerald-600 text-white" : "border border-stone-300 text-stone-500"
                  }`}
                >
                  {step.done ? "✓" : i + 1}
                </span>
                {step.done ? (
                  <span className="text-stone-400 line-through">{step.text}</span>
                ) : (
                  <Link href={step.href} className="text-stone-800 underline decoration-stone-300 underline-offset-4 hover:decoration-brand-500">
                    {step.text}
                  </Link>
                )}
              </li>
            ))}
          </ol>
        </Card>
      )}

      <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Sent today" value={`${data.sent_today} / ${data.daily_send_limit}`} accent hint="Resets at 00:00 UTC" />
        <Stat label="Drafts" value={data.counts.draft ?? 0} hint="Waiting for your review" />
        <Stat label="Sent in total" value={data.counts.sent ?? 0} />
        <Stat label="Failed" value={data.counts.failed ?? 0} hint="Can be sent again" />
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="Recent applications" className="lg:col-span-2" action={<Link href="/jobs/applications" className="text-xs font-medium text-brand-700 hover:underline">View all</Link>}>
          {data.recent.length === 0 ? (
            <Empty>No applications yet.</Empty>
          ) : (
            <ul className="-my-2 divide-y divide-stone-200">
              {data.recent.map((a) => (
                <li key={a.id}>
                  <Link href={`/jobs/applications/${a.id}`} className="flex items-center justify-between gap-3 py-2.5 hover:bg-stone-50">
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium text-stone-900">{a.role || a.subject || "Untitled role"}</div>
                      <div className="truncate text-xs text-stone-500">
                        {a.company || a.to_email} · {timeAgo(a.sent_at ?? a.created_at)}
                      </div>
                    </div>
                    <Badge>{a.status}</Badge>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Gmail">
          {data.gmail.connected ? (
            <>
              <div className="flex items-center gap-2 text-sm">
                <span className="h-2 w-2 rounded-full bg-emerald-500" aria-hidden="true" />
                <span className="font-medium text-stone-900">{data.gmail.email}</span>
              </div>
              <p className="mt-2 text-sm text-stone-500">Applications are sent from this address.</p>
            </>
          ) : (
            <>
              <div className="flex items-center gap-2 text-sm">
                <span className="h-2 w-2 rounded-full bg-stone-400" aria-hidden="true" />
                <span className="font-medium text-stone-900">Not connected</span>
              </div>
              <p className="mt-2 text-sm text-stone-500">You can write drafts now; sending needs Gmail.</p>
              <Link href="/jobs/settings" className="mt-3 inline-block text-sm font-medium text-brand-700 hover:underline">
                Connect Gmail
              </Link>
            </>
          )}
        </Card>
      </div>
    </>
  );
}
