"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { Badge, Button, Card, Field, Input, Loading, Notice, PageHeader, Select, Textarea } from "@/components/ui";
import { FollowUpsEditor } from "@/components/followups-editor";
import { api, gmailThreadUrl, timeAgo, useApi, type Application, type FollowUp, type GmailStatus, type JobSettings, type Resume } from "@/lib/api";

function Editor({ initial, onChanged }: { initial: Application; onChanged: (a: Application) => void }) {
  const router = useRouter();
  const { data: resumes } = useApi<Resume[]>("/jobs/resumes");
  const { data: settings } = useApi<JobSettings>("/jobs/settings");
  const { data: gmail } = useApi<GmailStatus>("/jobs/gmail");
  const [accountId, setAccountId] = useState<string>("");
  const [app, setApp] = useState(initial);
  const [to, setTo] = useState(initial.to_email);
  const [cc, setCc] = useState(initial.cc.join(", "));
  const [subject, setSubject] = useState(initial.subject);
  const [body, setBody] = useState(initial.body);
  const [resumeId, setResumeId] = useState(initial.resume_id ? String(initial.resume_id) : "");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const ccList = cc.split(",").map((s) => s.trim()).filter(Boolean);
  const dirty =
    to !== app.to_email || cc !== app.cc.join(", ") || subject !== app.subject || body !== app.body || resumeId !== (app.resume_id ? String(app.resume_id) : "");
  const max = settings?.email_max_chars ?? 2500;

  function load(next: Application) {
    setApp(next);
    setTo(next.to_email);
    setCc(next.cc.join(", "));
    setSubject(next.subject);
    setBody(next.body);
    setResumeId(next.resume_id ? String(next.resume_id) : "");
    onChanged(next);
  }

  async function run(name: string, fn: () => Promise<void>) {
    setBusy(name);
    setError("");
    setNotice("");
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    }
    setBusy("");
  }

  const patch = () =>
    api<Application>(`/jobs/applications/${app.id}`, {
      method: "PATCH",
      body: { to_email: to, cc: ccList, subject, body, ...(resumeId ? { resume_id: Number(resumeId) } : { clear_resume: true }) },
    });

  const save = () =>
    run("save", async () => {
      load(await patch());
      setNotice("Saved.");
    });

  const rewrite = () =>
    run("rewrite", async () => {
      if (dirty) await patch();
      load(await api<Application>(`/jobs/applications/${app.id}/rewrite`, { method: "POST" }));
      setNotice("Rewritten by the AI.");
    });

  const send = () =>
    run("send", async () => {
      if (dirty) load(await patch());
      try {
        load(await api<Application>(`/jobs/applications/${app.id}/send`, { method: "POST", body: { gmail_account_id: accountId ? Number(accountId) : null } }));
      } catch (e) {
        const message = (e as Error).message;
        if (!message.startsWith("duplicate: ") || !confirm(`${message.slice(11)}\n\nSend this application anyway?`)) throw e;
        load(await api<Application>(`/jobs/applications/${app.id}/send`, { method: "POST", body: { allow_duplicate: true, gmail_account_id: accountId ? Number(accountId) : null } }));
      }
      setNotice("Sent from your Gmail.");
    });

  const remove = () =>
    run("delete", async () => {
      if (!confirm("Delete this draft?")) return;
      await api(`/jobs/applications/${app.id}`, { method: "DELETE" });
      router.replace("/jobs/applications");
    });

  const locked = Boolean(busy);

  return (
    <Card title="Email">
      <Notice>{error}</Notice>
      <Notice tone="green">{notice}</Notice>
      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="To">
            <Input type="email" value={to} onChange={(e) => setTo(e.target.value)} />
          </Field>
          <Field label="CC" hint="Comma-separated">
            <Input value={cc} onChange={(e) => setCc(e.target.value)} />
          </Field>
        </div>
        <Field label="Subject">
          <Input value={subject} maxLength={300} onChange={(e) => setSubject(e.target.value)} />
        </Field>
        <Field label="Message">
          <Textarea rows={16} value={body} onChange={(e) => setBody(e.target.value)} />
        </Field>
        <div className="flex justify-end font-mono text-[11px] text-stone-400">
          <span className={body.length > max ? "text-red-700" : ""}>
            {body.length} / {max}
          </span>
        </div>
        <Field label="Attachment">
          <Select value={resumeId} onChange={(e) => setResumeId(e.target.value)}>
            <option value="">No attachment</option>
            {resumes?.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name} · {r.filename}
              </option>
            ))}
          </Select>
        </Field>
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-2 border-t border-stone-200 pt-4">
        <Button variant="danger" loading={busy === "delete"} disabled={locked} onClick={remove}>
          Delete
        </Button>
        <span className="flex-1" />
        <Button loading={busy === "rewrite"} disabled={locked} onClick={rewrite}>
          {busy === "rewrite" ? "Rewriting…" : "Rewrite with AI"}
        </Button>
        <Button loading={busy === "save"} disabled={locked || !dirty} onClick={save}>
          {busy === "save" ? "Saving…" : "Save"}
        </Button>
        {(gmail?.accounts.length ?? 0) > 1 && (
          <Select aria-label="Send from" className="max-w-56" value={accountId} disabled={locked} onChange={(e) => setAccountId(e.target.value)}>
            <option value="">Default ({gmail?.accounts.find((a) => a.is_default)?.email})</option>
            {gmail?.accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.email}
              </option>
            ))}
          </Select>
        )}
        <Button variant="primary" loading={busy === "send"} disabled={locked || !to || !subject.trim() || !body.trim()} onClick={send}>
          {busy === "send" ? "Sending…" : "Send from Gmail"}
        </Button>
      </div>
    </Card>
  );
}

function SentView({ app }: { app: Application }) {
  return (
    <Card title="Email">
      <dl className="space-y-3 text-sm">
        <div className="grid grid-cols-[5rem_1fr] gap-2">
          <dt className="text-stone-500">To</dt>
          <dd className="text-stone-900">{app.to_email}</dd>
        </div>
        {app.cc.length > 0 && (
          <div className="grid grid-cols-[5rem_1fr] gap-2">
            <dt className="text-stone-500">CC</dt>
            <dd className="text-stone-900">{app.cc.join(", ")}</dd>
          </div>
        )}
        <div className="grid grid-cols-[5rem_1fr] gap-2">
          <dt className="text-stone-500">Subject</dt>
          <dd className="font-medium text-stone-900">{app.subject}</dd>
        </div>
        {app.resume && (
          <div className="grid grid-cols-[5rem_1fr] gap-2">
            <dt className="text-stone-500">Attached</dt>
            <dd className="text-stone-900">{app.resume.filename}</dd>
          </div>
        )}
      </dl>
      <p className="mt-4 whitespace-pre-wrap rounded-[6px] bg-stone-50 p-4 text-sm leading-relaxed text-stone-800">{app.body}</p>
      {app.gmail_thread_id && (
        <a href={gmailThreadUrl(app.gmail_thread_id)} target="_blank" rel="noreferrer" className="mt-4 inline-block text-sm font-medium text-brand-700 hover:underline">
          Open the thread in Gmail
        </a>
      )}
    </Card>
  );
}

function FollowUps({ app, onChanged }: { app: Application; onChanged: (a: Application) => void }) {
  const [plan, setPlan] = useState<FollowUp[]>(app.followups);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const dirty = JSON.stringify(plan) !== JSON.stringify(app.followups);
  const sent = app.status === "sent";

  async function save() {
    setBusy(true);
    setError("");
    try {
      onChanged(await api<Application>(`/jobs/applications/${app.id}/followups`, { method: "PUT", body: { followups: plan } }));
      setSaved(true);
    } catch (e) {
      setError((e as Error).message);
    }
    setBusy(false);
  }

  return (
    <div className="space-y-3">
      {sent && app.outcome === "replied" && <Notice tone="green">They replied. No more follow-ups will be sent.</Notice>}
      {sent && app.outcome === "bounced" && <Notice>This email bounced. The address was added to the do-not-contact list.</Notice>}
      {sent && !app.outcome && app.followups.length > 0 && (
        <Notice tone="green">
          {app.followups_sent >= app.followups.length
            ? "All follow-ups have been sent."
            : `Follow-up ${app.followups_sent + 1} of ${app.followups.length} goes ${app.followups[app.followups_sent].days} days after the last email, if nobody has replied.`}{" "}
          {app.followups_sent > 0 && `${app.followups_sent} done.`}
        </Notice>
      )}
      {app.followup_note && <Notice tone="amber">{app.followup_note}</Notice>}
      <FollowUpsEditor
        kind="job"
        title={sent ? "Follow-ups" : "Follow-ups after sending"}
        value={plan}
        onChange={(next) => {
          setPlan(next);
          setSaved(false);
        }}
        variables="Variables: {{role}}, {{company}}, {{first_name}}, {{name}}."
      />
      <Notice>{error}</Notice>
      <div className="flex items-center gap-3">
        <Button variant="primary" loading={busy} disabled={busy || !dirty} onClick={save}>
          {busy ? "Saving…" : "Save follow-ups"}
        </Button>
        {saved && !dirty && <span className="text-sm text-emerald-700">Saved.</span>}
        {!sent && <span className="text-xs text-stone-500">They start counting when the email is sent.</span>}
      </div>
    </div>
  );
}

export default function ApplicationPage() {
  const { id } = useParams<{ id: string }>();
  const { data, error } = useApi<Application>(`/jobs/applications/${id}`);
  const [current, setCurrent] = useState<Application | null>(null);
  const [showSource, setShowSource] = useState(false);

  if (error) return <Notice>{error}</Notice>;
  if (!data) return <Loading label="Loading application…" />;
  const app = current && current.id === data.id ? current : data;
  const details = app.details;

  return (
    <>
      <PageHeader
        title={app.role || "Application"}
        subtitle={[app.company, app.location].filter(Boolean).join(" · ") || app.to_email}
        action={
          <div className="flex items-center gap-3">
            <Badge>{app.status}</Badge>
            {app.outcome && <Badge>{app.outcome}</Badge>}
            <Link href="/jobs/applications" className="text-sm font-medium text-stone-600 hover:text-stone-900">
              All applications
            </Link>
          </div>
        }
      />
      {app.status === "failed" && app.error && <Notice>Last attempt failed: {app.error}</Notice>}
      {app.status === "sent" && <Notice tone="green">Sent {timeAgo(app.sent_at)} from your Gmail.</Notice>}

      <div className="grid gap-6 lg:grid-cols-[1.6fr_1fr]">
        <div className="min-w-0 space-y-6">
          {app.status === "draft" || app.status === "failed" ? <Editor key={app.id} initial={app} onChanged={setCurrent} /> : <SentView app={app} />}
          <FollowUps key={`${app.id}:${app.followups_sent}`} app={app} onChanged={setCurrent} />
        </div>

        <div className="space-y-6">
          <Card title="From the posting">
            <dl className="space-y-3 text-sm">
              {details.required_skills.length > 0 && (
                <div>
                  <dt className="font-mono text-[10.5px] uppercase tracking-[0.12em] text-stone-500">Skills asked for</dt>
                  <dd className="mt-1.5 flex flex-wrap gap-1">
                    {details.required_skills.map((skill) => (
                      <span key={skill} className="rounded-[4px] bg-stone-100 px-1.5 py-0.5 text-xs text-stone-700">
                        {skill}
                      </span>
                    ))}
                  </dd>
                </div>
              )}
              {details.apply_instructions.length > 0 && (
                <div>
                  <dt className="font-mono text-[10.5px] uppercase tracking-[0.12em] text-stone-500">Instructions</dt>
                  <dd className="mt-1 space-y-1 text-stone-800">
                    {details.apply_instructions.map((line) => (
                      <p key={line}>› {line}</p>
                    ))}
                  </dd>
                </div>
              )}
              {details.deadline && (
                <div>
                  <dt className="font-mono text-[10.5px] uppercase tracking-[0.12em] text-stone-500">Deadline</dt>
                  <dd className="mt-1 text-stone-800">{details.deadline}</dd>
                </div>
              )}
            </dl>
            <button type="button" className="mt-4 text-sm font-medium text-brand-700 hover:underline" onClick={() => setShowSource(!showSource)}>
              {showSource ? "Hide the job description" : "Show the job description"}
            </button>
            {showSource && <p className="mt-3 max-h-96 overflow-y-auto whitespace-pre-wrap rounded-[6px] bg-stone-50 p-3 text-xs leading-relaxed text-stone-700">{app.source_text}</p>}
          </Card>
          {app.model && <p className="px-1 font-mono text-[10.5px] uppercase tracking-[0.12em] text-stone-400">Written by {app.model}</p>}
        </div>
      </div>
    </>
  );
}
