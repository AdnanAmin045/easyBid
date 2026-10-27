"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { CampaignForm } from "@/components/campaign-form";
import { ListBody, Pagination, SearchInput, emptyMessage } from "@/components/list";
import { Badge, Button, Card, Empty, Field, Input, Loading, Notice, PageHeader, Select, Stat, Textarea } from "@/components/ui";
import {
  api,
  deliveredCount,
  download,
  gmailThreadUrl,
  timeAgo,
  totalCount,
  upload,
  useApi,
  usePaged,
  type Campaign,
  type CampaignCheck,
  type CampaignInput,
  type EmailPreview,
  type ImportResult,
  type OutreachRecipient,
} from "@/lib/api";

const POLL_MS = 10_000;
const STATUSES = ["", "pending", "sent", "replied", "bounced", "failed", "skipped"];

function Import({ campaign, onDone }: { campaign: Campaign; onDone: () => void }) {
  const [text, setText] = useState("");
  const [excel, setExcel] = useState<File | null>(null);
  const [skipRecent, setSkipRecent] = useState(true);
  const [checkDomains, setCheckDomains] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<ImportResult | null>(null);

  async function readFile(file: File | undefined) {
    if (!file) return;
    if (file.size > 5_000_000) return setError("The file is larger than 5 MB. Split it and import in parts.");
    setError("");
    if (file.name.toLowerCase().endsWith(".xlsx")) {
      setExcel(file);
      setText("");
    } else {
      setExcel(null);
      setText(await file.text());
    }
  }

  async function run() {
    setBusy(true);
    setError("");
    setResult(null);
    try {
      let done: ImportResult;
      if (excel) {
        const form = new FormData();
        form.append("file", excel);
        form.append("skip_recent", String(skipRecent));
        form.append("check_domains", String(checkDomains));
        done = await upload<ImportResult>(`/outreach/campaigns/${campaign.id}/recipients/import-file`, form);
      } else {
        done = await api<ImportResult>(`/outreach/campaigns/${campaign.id}/recipients/import`, {
          method: "POST",
          body: { text, skip_recent: skipRecent, check_domains: checkDomains },
        });
      }
      setResult(done);
      setText("");
      setExcel(null);
      onDone();
    } catch (e) {
      setError((e as Error).message);
    }
    setBusy(false);
  }

  return (
    <Card title="Add recipients">
      <Notice>{error}</Notice>
      <p className="mb-3 text-sm text-stone-600">
        Paste email addresses in any form, or upload an Excel (.xlsx) or CSV file. Columns <b>email</b>, <b>name</b>, <b>company</b> are recognised; any other column becomes a{" "}
        <code>{"{{variable}}"}</code>. <b>Already written your emails?</b> Use two columns, the address and the whole email: they are sent exactly as written. A first line like{" "}
        <code>Subject: Hello</code> becomes the subject; a <b>subject</b> column works too.
      </p>
      <Textarea
        rows={7}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          setExcel(null);
        }}
        className="font-mono text-xs"
        disabled={Boolean(excel)}
        placeholder={"email,name,company\nann@acme.com,Ann Lee,Acme\nbob@globex.com,Bob Stone,Globex"}
        aria-label="Recipients"
      />
      <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
        <label className="inline-flex items-center gap-2">
          <input type="file" accept=".xlsx,.csv,.tsv,.txt,text/csv,text/plain" onChange={(e) => readFile(e.target.files?.[0])} className="max-w-56 text-xs" aria-label="Upload an Excel or CSV file" />
        </label>
        <label className="inline-flex items-center gap-2">
          <input type="checkbox" checked={skipRecent} onChange={(e) => setSkipRecent(e.target.checked)} className="accent-brand-600" />
          Hold back people written to recently
        </label>
        <label className="inline-flex items-center gap-2">
          <input type="checkbox" checked={checkDomains} onChange={(e) => setCheckDomains(e.target.checked)} className="accent-brand-600" />
          Check that the domain can receive mail
        </label>
        {excel && <span className="font-mono text-xs text-stone-600">{excel.name} ready</span>}
        <span className="flex-1" />
        <Button variant="primary" loading={busy} disabled={!excel && text.trim().length < 3} onClick={run}>
          {busy ? "Importing…" : "Add to campaign"}
        </Button>
      </div>

      {result && (
        <div className="mt-4 rounded-[10px] bg-stone-50 p-3 text-sm text-stone-700">
          <p>
            <b>{result.added}</b> added
            {result.updated > 0 && <>, <b>{result.updated}</b> updated with the new message</>}
            {result.held_back > 0 && <>, <b>{result.held_back}</b> held back (see the Skipped filter for why)</>}
            {result.with_own_content > 0 && <>, <b>{result.with_own_content}</b> with their own message</>}
            {result.rejected_total > 0 && <>, <b>{result.rejected_total}</b> rejected</>}.
          </p>
          {result.columns.length > 0 && <p className="mt-1 text-xs text-stone-500">New variables: {result.columns.map((c) => `{{${c}}}`).join(" ")}</p>}
          {result.rejected.length > 0 && (
            <ul className="mt-2 max-h-40 space-y-0.5 overflow-y-auto font-mono text-xs text-stone-600">
              {result.rejected.map((r, i) => (
                <li key={i}>
                  line {r.line}: {r.value || "(empty)"} — {r.reason}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Card>
  );
}

function RecipientPanel({ campaign, recipient, onChanged }: { campaign: Campaign; recipient: OutreachRecipient; onChanged: () => void }) {
  const editable = ["pending", "failed", "skipped"].includes(recipient.status);
  const [form, setForm] = useState({ email: recipient.email, name: recipient.name, company: recipient.company, subject: recipient.subject, body: recipient.body });
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [step, setStep] = useState(0);
  const preview = useApi<EmailPreview>(`/outreach/campaigns/${campaign.id}/preview?recipient_id=${recipient.id}&step=${step}`);
  const base = `/outreach/campaigns/${campaign.id}/recipients/${recipient.id}`;
  const dirty = (Object.keys(form) as (keyof typeof form)[]).some((k) => form[k] !== recipient[k]);
  const heldRecently = recipient.status === "skipped" && (recipient.error ?? "").startsWith("Already");

  async function run(name: string, fn: () => Promise<unknown>) {
    setBusy(name);
    setError("");
    try {
      await fn();
      onChanged();
      preview.reload();
    } catch (e) {
      setError((e as Error).message);
    }
    setBusy("");
  }

  const save = () => run("save", () => api(base, { method: "PATCH", body: form }));
  const retry = (allowRecent: boolean) => run("retry", () => api(`${base}/retry${allowRecent ? "?allow_recent=true" : ""}`, { method: "POST" }));
  const generate = () => run("generate", async () => {
    if (dirty) await api(base, { method: "PATCH", body: form });
    await api(`${base}/generate`, { method: "POST" });
  });
  const remove = () => run("remove", async () => {
    if (confirm(`Remove ${recipient.email} from this campaign?`)) await api(base, { method: "DELETE" });
  });

  return (
    <div className="grid gap-5 bg-stone-50 p-4 lg:grid-cols-2">
      <div>
        <div className="mb-2 flex items-center justify-between gap-2">
          <p className="font-mono text-[10.5px] uppercase tracking-[0.12em] text-stone-500">Exactly what they get</p>
          {campaign.followups.length > 0 && (
            <Select aria-label="Which email" className="!w-48 !py-1 text-xs" value={step} onChange={(e) => setStep(Number(e.target.value))}>
              <option value={0}>First email</option>
              {campaign.followups.map((f, i) => (
                <option key={i} value={i + 1}>
                  Follow-up {i + 1} (after {f.days} d)
                </option>
              ))}
            </Select>
          )}
        </div>
        {preview.error && <Notice>{preview.error}</Notice>}
        {preview.data && (
          <div className="rounded-[10px] border border-stone-200 bg-white p-3 text-sm">
            {preview.data.missing.length > 0 && <Notice tone="amber">Missing value for: {preview.data.missing.join(", ")}. Fill it in on the right.</Notice>}
            <p className="font-medium text-stone-900">{preview.data.subject || <span className="text-stone-400">(no subject yet)</span>}</p>
            <p className="mt-2 whitespace-pre-wrap leading-relaxed text-stone-700">
              {preview.data.body || <span className="text-stone-400">{campaign.mode === "ai" ? "The AI writes this when its turn comes, or press “Write with AI” to read it first." : "(no message yet)"}</span>}
            </p>
          </div>
        )}
        {recipient.error && <p className="mt-2 text-xs text-red-700">{recipient.error}</p>}
        {recipient.gmail_thread_id && (
          <a href={gmailThreadUrl(recipient.gmail_thread_id)} target="_blank" rel="noreferrer" className="mt-2 inline-block text-sm font-medium text-brand-700 hover:underline">
            Open the thread in Gmail
          </a>
        )}
      </div>

      <div>
        <Notice>{error}</Notice>
        {editable ? (
          <div className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-3">
              <Field label="Email">
                <Input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
              </Field>
              <Field label="Name">
                <Input value={form.name} maxLength={200} onChange={(e) => setForm({ ...form, name: e.target.value })} />
              </Field>
              <Field label="Company">
                <Input value={form.company} maxLength={200} onChange={(e) => setForm({ ...form, company: e.target.value })} />
              </Field>
            </div>
            <Field label="Own subject" hint="Leave empty to use the campaign's subject.">
              <Input value={form.subject} maxLength={300} onChange={(e) => setForm({ ...form, subject: e.target.value })} />
            </Field>
            <Field label="Own message" hint="Leave empty to use the campaign's template.">
              <Textarea rows={5} value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} />
            </Field>
            <div className="flex flex-wrap gap-2">
              <Button variant="primary" loading={busy === "save"} disabled={Boolean(busy) || !dirty} onClick={save}>
                Save
              </Button>
              {campaign.ai_brief.trim() && (
                <Button loading={busy === "generate"} disabled={Boolean(busy)} onClick={generate}>
                  Write with AI
                </Button>
              )}
              {(recipient.status === "failed" || recipient.status === "skipped") && !heldRecently && (
                <Button loading={busy === "retry"} disabled={Boolean(busy)} onClick={() => retry(false)}>
                  Put back in the queue
                </Button>
              )}
              {heldRecently && (
                <Button loading={busy === "retry"} disabled={Boolean(busy)} onClick={() => retry(true)}>
                  Send anyway
                </Button>
              )}
              <span className="flex-1" />
              <Button variant="danger" loading={busy === "remove"} disabled={Boolean(busy)} onClick={remove}>
                Remove
              </Button>
            </div>
          </div>
        ) : (
          <p className="text-sm text-stone-500">
            This email is {recipient.status}
            {recipient.sent_at ? ` (${timeAgo(recipient.sent_at)})` : ""} and can no longer be changed.
          </p>
        )}
      </div>
    </div>
  );
}

function Recipients({ campaign, version, onChanged }: { campaign: Campaign; version: number; onChanged: () => void }) {
  const [status, setStatus] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const { data, error, loading, fetching, setPage, q, search, reload } = usePaged<OutreachRecipient>(`/outreach/campaigns/${campaign.id}/recipients`, {
    filters: { status },
    pageSize: 25,
  });

  // The campaign page reloads while running; the list follows so progress shows without a refresh.
  useEffect(() => {
    if (version > 0) reload();
  }, [version, reload]);

  return (
    <Card
      title="Recipients"
      action={
        <div className="flex flex-wrap gap-2">
          <SearchInput onSearch={search} placeholder="Search email, name, company" />
          <div className="w-32">
            <Select aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)}>
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s || "All"}
                </option>
              ))}
            </Select>
          </div>
        </div>
      }
    >
      <Notice>{error}</Notice>
      <ListBody loading={loading} fetching={fetching}>
        {data?.total === 0 ? (
          <Empty>{emptyMessage(Boolean(q || status), "Nobody yet. Paste or upload your list above.")}</Empty>
        ) : (
          <div className="-mx-5 overflow-x-auto">
            <table className="w-full text-sm">
              <tbody>
                {data?.items.map((r) => (
                  <RecipientRow key={r.id} campaign={campaign} recipient={r} open={open === r.id} onToggle={() => setOpen(open === r.id ? null : r.id)} onChanged={() => { reload(); onChanged(); }} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </ListBody>
      <Pagination data={data} fetching={fetching} onPage={setPage} />
    </Card>
  );
}

function RecipientRow({ campaign, recipient: r, open, onToggle, onChanged }: { campaign: Campaign; recipient: OutreachRecipient; open: boolean; onToggle: () => void; onChanged: () => void }) {
  return (
    <>
      <tr className="cursor-pointer border-t border-stone-100 hover:bg-stone-50" onClick={onToggle}>
        <td className="max-w-xs px-5 py-2.5">
          <button type="button" aria-expanded={open} className="block w-full truncate text-left font-medium text-stone-900">
            {r.email}
          </button>
          <span className="block truncate text-xs text-stone-500">{[r.name, r.company].filter(Boolean).join(" · ") || "No name"}</span>
        </td>
        <td className="hidden max-w-sm truncate px-3 py-2.5 text-xs text-stone-500 md:table-cell">{r.error ?? (r.status === "sent" && campaign.followups.length > 0 ? `Follow-ups: ${r.followups_sent} of ${campaign.followups.length} sent` : r.body ? "Has its own message" : "")}</td>
        <td className="px-3 py-2.5">
          <Badge>{r.status}</Badge>
        </td>
        <td className="whitespace-nowrap px-5 py-2.5 text-right font-mono text-xs text-stone-500">{r.sent_at ? timeAgo(r.sent_at) : ""}</td>
      </tr>
      {open && (
        <tr>
          <td colSpan={4} className="border-t border-stone-100 p-0">
            <RecipientPanel campaign={campaign} recipient={r} onChanged={onChanged} />
          </td>
        </tr>
      )}
    </>
  );
}

export default function CampaignPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { data: campaign, error, reload } = useApi<Campaign>(`/outreach/campaigns/${id}`);
  const [tab, setTab] = useState<"recipients" | "email">("recipients");
  const [busy, setBusy] = useState("");
  const [actionError, setActionError] = useState("");
  const [notice, setNotice] = useState("");
  const [version, setVersion] = useState(0);

  const running = campaign?.status === "running";
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => {
      reload();
      setVersion((v) => v + 1);
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [running, reload]);

  if (error) return <Notice>{error}</Notice>;
  if (!campaign) return <Loading label="Loading campaign…" />;

  const base = `/outreach/campaigns/${campaign.id}`;
  const total = totalCount(campaign.counts);
  const delivered = deliveredCount(campaign.counts);
  const closed = campaign.status === "cancelled";

  async function run(name: string, fn: () => Promise<void>) {
    setBusy(name);
    setActionError("");
    setNotice("");
    try {
      await fn();
    } catch (e) {
      setActionError((e as Error).message);
    }
    setBusy("");
  }

  const start = () =>
    run("start", async () => {
      const check = await api<CampaignCheck>(`${base}/check`);
      if (!check.ready) throw new Error(check.blockers.join(" "));
      const lines = [`Send to ${check.pending} people. At this pace that takes about ${check.estimated_days} day(s).`, ...check.warnings];
      if (check.missing_examples.length) lines.push("Without a value: " + check.missing_examples.slice(0, 5).map((m) => `${m.email} (${m.missing.join(", ")})`).join("; "));
      if (!confirm(lines.join("\n\n"))) return;
      await api(`${base}/start`, { method: "POST" });
      reload();
      setVersion((v) => v + 1);
    });
  const act = (name: string, path: string, message?: string) =>
    run(name, async () => {
      if (message && !confirm(message)) return;
      await api(`${base}/${path}`, { method: "POST" });
      reload();
      setVersion((v) => v + 1);
    });
  const testSend = () =>
    run("test", async () => {
      const res = await api<{ sent_to: string }>(`${base}/test-send`, { method: "POST", body: {} });
      setNotice(`A test email was sent to ${res.sent_to}.`);
    });
  const exportCsv = () => run("export", () => download(`${base}/export`, `${campaign.name}.csv`));
  const remove = () =>
    run("delete", async () => {
      if (!confirm("Delete this campaign?")) return;
      await api(base, { method: "DELETE" });
      router.replace("/outreach/campaigns");
    });

  async function saveSettings(input: CampaignInput) {
    await api(base, { method: "PATCH", body: input });
    reload();
    setTab("recipients");
    setNotice("Campaign saved. Emails not yet sent will use the new text and pace.");
  }

  const locked = Boolean(busy);

  return (
    <>
      <PageHeader
        title={campaign.name}
        subtitle={campaign.mode === "ai" ? "The AI writes each email from your brief." : "One template, filled in for each person."}
        action={
          <div className="flex flex-wrap items-center gap-2">
            <Badge>{campaign.status}</Badge>
            <Link href="/outreach/campaigns" className="text-sm font-medium text-stone-600 hover:text-stone-900">
              All campaigns
            </Link>
          </div>
        }
      />
      <Notice>{actionError}</Notice>
      <Notice tone="green">{notice}</Notice>
      {campaign.status === "paused" && campaign.pause_reason && <Notice tone="amber">{campaign.pause_reason}</Notice>}
      {running && campaign.waiting && <Notice tone="amber">Waiting: {campaign.waiting}</Notice>}
      {running && !campaign.waiting && (campaign.counts.pending ?? 0) === 0 && campaign.followups_scheduled > 0 && (
        <Notice tone="green">
          Everyone has had the first email. {campaign.followups_scheduled} {campaign.followups_scheduled === 1 ? "person is" : "people are"} waiting for a follow-up; they go out on their own, and the campaign finishes after the last one.
        </Notice>
      )}
      {running && !campaign.waiting && ((campaign.counts.pending ?? 0) > 0 || campaign.followups_scheduled === 0) && <Notice tone="green">Sending. The next email goes out after a random pause{campaign.next_send_at ? `, around ${new Date(campaign.next_send_at).toLocaleTimeString()}` : ""}.</Notice>}

      <div className="mb-5 flex flex-wrap items-center gap-2">
        {(campaign.status === "draft" || campaign.status === "paused" || campaign.status === "completed") && (
          <Button variant="primary" loading={busy === "start"} disabled={locked || campaign.status === "completed" && (campaign.counts.pending ?? 0) === 0} onClick={start}>
            {campaign.status === "paused" ? "Resume" : "Start sending"}
          </Button>
        )}
        {running && (
          <Button loading={busy === "pause"} disabled={locked} onClick={() => act("pause", "pause")}>
            Pause
          </Button>
        )}
        <Button loading={busy === "test"} disabled={locked || total === 0} onClick={testSend}>
          Send me a test
        </Button>
        <Button loading={busy === "export"} disabled={locked || total === 0} onClick={exportCsv}>
          Export CSV
        </Button>
        <span className="flex-1" />
        {!closed && (
          <Button variant="danger" loading={busy === "cancel"} disabled={locked} onClick={() => act("cancel", "cancel", "Cancel this campaign? Emails not yet sent will not be sent.")}>
            Cancel campaign
          </Button>
        )}
        {campaign.status !== "running" && delivered === 0 && (
          <Button variant="danger" loading={busy === "delete"} disabled={locked} onClick={remove}>
            Delete
          </Button>
        )}
      </div>

      <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
        <Stat label="Waiting" value={campaign.counts.pending ?? 0} accent />
        <Stat label="Sent" value={delivered} hint={`${campaign.sent_24h} in 24 h${campaign.followups.length ? `, ${campaign.followups_sent} follow-ups` : ""}`} />
        <Stat label="Replied" value={campaign.counts.replied ?? 0} />
        <Stat label="Bounced" value={campaign.counts.bounced ?? 0} />
        <Stat label="Failed" value={campaign.counts.failed ?? 0} />
        <Stat label="Skipped" value={campaign.counts.skipped ?? 0} />
      </div>

      <div className="mb-5 flex gap-1 border-b border-stone-300/70" role="tablist">
        {(["recipients", "email"] as const).map((t) => (
          <button
            key={t}
            type="button"
            role="tab"
            aria-selected={tab === t}
            onClick={() => setTab(t)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${tab === t ? "border-brand-500 text-stone-900" : "border-transparent text-stone-500 hover:text-stone-800"}`}
          >
            {t === "recipients" ? "Recipients" : "Email and schedule"}
          </button>
        ))}
      </div>

      {tab === "recipients" ? (
        <div className="space-y-6">
          {!closed && <Import campaign={campaign} onDone={() => { reload(); setVersion((v) => v + 1); }} />}
          <Recipients campaign={campaign} version={version} onChanged={reload} />
        </div>
      ) : closed ? (
        <Notice tone="amber">This campaign was cancelled and can no longer be changed.</Notice>
      ) : (
        <CampaignForm key={campaign.id} initial={campaign} columns={campaign.columns} submitLabel="Save changes" onSubmit={saveSettings} />
      )}
    </>
  );
}
