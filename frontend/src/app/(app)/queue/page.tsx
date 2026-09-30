"use client";

import { useState } from "react";
import { Badge, Button, Empty, Field, Input, Notice, PageHeader, Textarea } from "@/components/ui";
import { ListBody, Pagination, SearchInput, emptyMessage } from "@/components/list";
import { api, budgetLabel, timeAgo, useApi, usePaged, type ProposalWithProject, type Settings } from "@/lib/api";

interface QueueItemProps {
  item: ProposalWithProject;
  maxChars: number;
  /** The list is being fetched again; actions wait for the fresh state. */
  refreshing: boolean;
  onChange: () => void;
}

function QueueItem({ item, maxChars, refreshing, onChange }: QueueItemProps) {
  const { project } = item;
  const [text, setText] = useState(item.text);
  const [amount, setAmount] = useState(String(item.amount));
  const [period, setPeriod] = useState(String(item.period));
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [showJob, setShowJob] = useState(false);

  const dirty = text !== item.text || Number(amount) !== item.amount || Number(period) !== item.period;
  const save = () =>
    api(`/proposals/${item.id}`, { method: "PATCH", body: { text, amount: Number(amount), period: Number(period) } });

  async function run(name: string, fn: () => Promise<unknown>) {
    setBusy(name);
    setError("");
    try {
      await fn();
      onChange();
    } catch (e) {
      setError((e as Error).message);
    }
    setBusy("");
  }

  const locked = Boolean(busy) || refreshing;

  return (
    <article className="rounded-lg border border-zinc-200 bg-white p-5">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <a href={project.url} target="_blank" rel="noreferrer" className="font-semibold text-zinc-900 hover:text-indigo-700">
            {project.title}
          </a>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-zinc-500">
            <span>{budgetLabel(project)}</span>
            <span>{project.bid_count} bids</span>
            <span>score {project.score ?? "–"}</span>
            <span>posted {timeAgo(project.submitted_at)}</span>
          </div>
        </div>
        <Badge>{item.status}</Badge>
      </div>

      {project.reason && <p className="mb-3 text-sm text-zinc-600">AI: {project.reason}</p>}
      {item.error && <Notice>{item.error}</Notice>}
      <Notice>{error}</Notice>

      <button type="button" className="mb-3 text-xs font-medium text-indigo-700" onClick={() => setShowJob(!showJob)}>
        {showJob ? "Hide job description" : "Show job description"}
      </button>
      {showJob && (
        <div className="mb-4 rounded-md bg-zinc-50 p-3 text-sm text-zinc-700">
          <p className="whitespace-pre-wrap">{project.description}</p>
          <p className="mt-2 text-xs text-zinc-500">{project.skills.join(" · ")}</p>
        </div>
      )}

      <Textarea rows={9} value={text} onChange={(e) => setText(e.target.value)} />
      <div className={`mt-1 text-right text-xs ${text.length > maxChars ? "text-red-600" : "text-zinc-500"}`}>
        {text.length} / {maxChars} characters
      </div>

      <div className="mt-3 flex flex-wrap items-end gap-3">
        <div className="w-36">
          <Field label={`Amount (${project.currency}${project.type === "hourly" ? "/hr" : ""})`}>
            <Input type="number" min={1} value={amount} onChange={(e) => setAmount(e.target.value)} />
          </Field>
        </div>
        <div className="w-36">
          <Field label={project.type === "hourly" ? "Hours per week" : "Delivery (days)"}>
            <Input type="number" min={1} value={period} onChange={(e) => setPeriod(e.target.value)} />
          </Field>
        </div>
        <div className="ml-auto flex flex-wrap gap-2">
          <Button
            loading={busy === "reject"}
            disabled={locked}
            onClick={() => run("reject", () => api(`/proposals/${item.id}/reject`, { method: "POST" }))}
          >
            {busy === "reject" ? "Rejecting…" : "Reject"}
          </Button>
          <Button
            loading={busy === "rewrite"}
            disabled={locked}
            onClick={() => run("rewrite", () => api(`/projects/${project.id}/generate`, { method: "POST" }))}
          >
            {busy === "rewrite" ? "Writing…" : "Rewrite"}
          </Button>
          <Button loading={busy === "save"} disabled={locked || !dirty} onClick={() => run("save", save)}>
            {busy === "save" ? "Saving…" : "Save"}
          </Button>
          <Button
            variant="primary"
            loading={busy === "send"}
            disabled={locked || !text.trim()}
            onClick={() =>
              run("send", async () => {
                if (dirty) await save();
                await api(`/proposals/${item.id}/approve`, { method: "POST" });
              })
            }
          >
            {busy === "send" ? "Sending…" : item.status === "failed" ? "Retry bid" : "Approve and send bid"}
          </Button>
        </div>
      </div>
    </article>
  );
}

const QUEUE = { status: "pending,failed" };

export default function QueuePage() {
  const { data, error, loading, fetching, reload, setPage, q, search } = usePaged<ProposalWithProject>("/proposals", {
    pageSize: 10,
    filters: QUEUE,
  });
  const { data: settings } = useApi<Settings>("/settings");

  return (
    <>
      <PageHeader
        title="Queue"
        subtitle="Proposals waiting for your approval. Approving sends the bid on Freelancer."
        action={<SearchInput onSearch={search} placeholder="Search project or proposal text" />}
      />
      <Notice>{error}</Notice>
      <ListBody loading={loading} fetching={fetching} rows={2}>
        {data?.total === 0 && <Empty>{emptyMessage(Boolean(q), "Nothing is waiting.")}</Empty>}
        <div className="space-y-4">
          {data?.items.map((item) => (
            // Re-mount when the proposal is rewritten so the editor picks up the new text.
            <QueueItem
              key={`${item.id}-${item.text.length}-${item.status}`}
              item={item}
              maxChars={settings?.proposal_max_chars ?? 1500}
              refreshing={fetching}
              onChange={reload}
            />
          ))}
        </div>
      </ListBody>
      <Pagination data={data} fetching={fetching} onPage={setPage} />
    </>
  );
}
