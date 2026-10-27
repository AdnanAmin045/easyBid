"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useState, type ReactNode } from "react";
import { FollowUpsEditor } from "@/components/followups-editor";
import { Button, Card, Field, Input, Loading, Notice, PageHeader, Select, Textarea } from "@/components/ui";
import { api, useApi, type GmailAccount, type GmailStatus, type JobSettings, type OutreachSettings } from "@/lib/api";

const MODELS = [
  { value: "gemini-3.5-flash", label: "Gemini 3.5 Flash (free tier)" },
  { value: "gemini-flash-lite-latest", label: "Gemini Flash Lite (free tier, fastest)" },
  { value: "gemini-pro-latest", label: "Gemini Pro" },
  { value: "claude-sonnet-5-5", label: "Claude Sonnet 5.5" },
  { value: "claude-opus-5-5", label: "Claude Opus 5.5 (best writing)" },
  { value: "claude-haiku-4-5", label: "Claude Haiku 4.5 (cheapest Claude)" },
];

type Message = { tone: "red" | "green"; text: string } | null;

function ModelSelect({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return (
    <Select value={value} onChange={(e) => onChange(e.target.value)}>
      {MODELS.map((m) => (
        <option key={m.value} value={m.value}>
          {m.label}
        </option>
      ))}
    </Select>
  );
}

function Check({ label, hint, checked, onChange }: { label: string; hint?: string; checked: boolean; onChange: (value: boolean) => void }) {
  return (
    <label className="flex items-start gap-2.5 text-sm">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="mt-0.5 h-4 w-4 rounded border-stone-300 accent-brand-600" />
      <span>
        <span className="font-medium text-stone-800">{label}</span>
        {hint && <span className="block text-xs text-stone-500">{hint}</span>}
      </span>
    </label>
  );
}

/** One tool's block of settings with its own save button, so each tool is saved on its own. */
function Section({ title, subtitle, busy, message, onSave, children }: {
  title: string;
  subtitle: string;
  busy: boolean;
  message: Message;
  onSave: () => void;
  children: ReactNode;
}) {
  return (
    <section className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold text-stone-900">{title}</h2>
        <p className="text-sm text-stone-500">{subtitle}</p>
      </div>
      {children}
      <div className="flex items-center gap-3">
        <Button variant="primary" loading={busy} onClick={onSave}>
          {busy ? "Saving…" : `Save ${title.toLowerCase()}`}
        </Button>
        {message && <span className={`text-sm ${message.tone === "red" ? "text-red-700" : "text-emerald-700"}`}>{message.text}</span>}
      </div>
    </section>
  );
}

function useSaver<T extends object>(path: string, initial: T) {
  const [value, setValue] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<Message>(null);
  const update = (patch: Partial<T>) => setValue((current) => ({ ...current, ...patch }));
  const num = (key: keyof T, props: { min?: number; max?: number } = {}) => (
    <Input type="number" {...props} value={String(value[key])} onChange={(e) => update({ [key]: Number(e.target.value) } as unknown as Partial<T>)} />
  );
  async function save() {
    setBusy(true);
    setMessage(null);
    try {
      setValue(await api<T>(path, { method: "PUT", body: value }));
      setMessage({ tone: "green", text: "Saved." });
    } catch (e) {
      setMessage({ tone: "red", text: (e as Error).message });
    }
    setBusy(false);
  }
  return { value, update, num, busy, message, save };
}

function AccountRow({ account, onChanged, busy, setBusy, setError }: {
  account: GmailAccount;
  onChanged: () => void;
  busy: string;
  setBusy: (value: string) => void;
  setError: (value: string) => void;
}) {
  const [name, setName] = useState(account.sender_name);
  const [signature, setSignature] = useState(account.signature);
  const [open, setOpen] = useState(false);
  const dirty = name !== account.sender_name || signature !== account.signature;
  const mine = `${account.id}`;

  async function act(key: string, work: () => Promise<unknown>) {
    setBusy(key + mine);
    setError("");
    try {
      await work();
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    }
    setBusy("");
  }

  return (
    <li className="rounded-[10px] border border-stone-200 bg-white p-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-sm">
          <span className="h-2 w-2 rounded-full bg-emerald-500" aria-hidden="true" />
          <span className="font-medium text-stone-900">{account.email}</span>
          {account.is_default && <span className="rounded-full bg-brand-50 px-2 py-0.5 text-xs font-medium text-brand-700">Default</span>}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => setOpen(!open)}>{open ? "Hide details" : "Name & signature"}</Button>
          {!account.is_default && (
            <Button loading={busy === "default" + mine} disabled={Boolean(busy)} onClick={() => act("default", () => api(`/jobs/gmail/${account.id}/default`, { method: "POST" }))}>
              Make default
            </Button>
          )}
          <Button
            variant="danger"
            loading={busy === "disconnect" + mine}
            disabled={Boolean(busy)}
            onClick={() => {
              if (!confirm(`Disconnect ${account.email}? Campaigns running from it are paused, and follow-ups of emails it sent stop.`)) return;
              void act("disconnect", () => api(`/jobs/gmail/${account.id}/disconnect`, { method: "POST" }));
            }}
          >
            Disconnect
          </Button>
        </div>
      </div>
      {open && (
        <div className="mt-3 grid gap-3 border-t border-stone-200 pt-3 sm:grid-cols-2">
          <Field label="Sender name" hint="Leave empty to use the name in Jobs applications below.">
            <Input value={name} maxLength={120} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="Signature" hint="Leave empty to use the shared signature.">
            <Textarea rows={3} value={signature} maxLength={1000} onChange={(e) => setSignature(e.target.value)} />
          </Field>
          <div className="sm:col-span-2">
            <Button
              variant="primary"
              loading={busy === "save" + mine}
              disabled={!dirty || Boolean(busy)}
              onClick={() => act("save", () => api(`/jobs/gmail/${account.id}`, { method: "PATCH", body: { sender_name: name, signature } }))}
            >
              Save
            </Button>
          </div>
        </div>
      )}
    </li>
  );
}

function Gmail() {
  const params = useSearchParams();
  const { data, error, loading, reload } = useApi<GmailStatus>("/jobs/gmail");
  const [busy, setBusy] = useState("");
  const [actionError, setActionError] = useState("");
  const result = params.get("gmail");

  async function connect() {
    setBusy("connect");
    setActionError("");
    try {
      const { url } = await api<{ url: string }>("/jobs/gmail/connect", { method: "POST" });
      window.location.assign(url);
    } catch (e) {
      setActionError((e as Error).message);
      setBusy("");
    }
  }

  return (
    <Card title="Gmail accounts">
      {result === "connected" && <Notice tone="green">Gmail connected.</Notice>}
      {result === "error" && <Notice>Gmail was not connected: {params.get("message") || "unknown error"}</Notice>}
      <Notice>{error || actionError}</Notice>
      {loading || !data ? (
        <p className="text-sm text-stone-500">Checking…</p>
      ) : (
        <>
          <p className="mb-3 text-sm text-stone-600">
            Emails are sent through the Gmail API from your own accounts. Connect as many as you like, then choose which one each campaign or
            application sends from. Follow-ups and reply checks always use the account the first email went from. Worklane asks for permission to
            send email and to read the threads it starts, so it can see replies. Your password is never seen or stored.
          </p>
          {data.accounts.length > 0 && (
            <ul className="mb-3 space-y-2">
              {data.accounts.map((account) => (
                <AccountRow key={account.id} account={account} onChanged={reload} busy={busy} setBusy={setBusy} setError={setActionError} />
              ))}
            </ul>
          )}
          {!data.configured && (
            <Notice tone="amber">
              The server has no Google OAuth client yet. Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET and GOOGLE_REDIRECT_URI on the backend first.
            </Notice>
          )}
          <Button variant="dark" loading={busy === "connect"} disabled={Boolean(busy) || !data.configured} onClick={connect}>
            {busy === "connect" ? "Opening Google…" : data.accounts.length ? "Connect another Gmail" : "Connect Gmail"}
          </Button>
          {data.accounts.length > 0 && (
            <p className="mt-2 text-xs text-stone-500">Google shows its account chooser, so pick the other address there.</p>
          )}
        </>
      )}
    </Card>
  );
}

function JobsSection({ initial }: { initial: JobSettings }) {
  const { value: s, update, num, busy, message, save } = useSaver<JobSettings>("/jobs/settings", initial);
  return (
    <Section title="Jobs applications" subtitle="Applications you send one by one, and their follow-ups." busy={busy} message={message} onSave={save}>
      <Card title="Sender">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Your name" hint="Shown as the sender, e.g. Adnan Amin. Used by campaigns too.">
            <Input value={s.sender_name} maxLength={120} onChange={(e) => update({ sender_name: e.target.value })} />
          </Field>
          <Field label="Writing model">
            <ModelSelect value={s.model} onChange={(model) => update({ model })} />
          </Field>
          <div className="sm:col-span-2">
            <Field label="Signature" hint="Added under every email, in applications and campaigns. Name, role, phone, LinkedIn, portfolio.">
              <Textarea rows={4} value={s.signature} maxLength={1000} onChange={(e) => update({ signature: e.target.value })} />
            </Field>
          </div>
        </div>
      </Card>
      <Card title="Limits">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Applications per day" hint="Resets at 00:00 UTC. 20 is a safe ceiling.">
            {num("daily_send_limit", { min: 1, max: 100 })}
          </Field>
          <Field label="Duplicate warning (days)" hint="Warn before writing to the same address or company again. 0 turns it off.">
            {num("duplicate_window_days", { min: 0, max: 365 })}
          </Field>
          <Field label="Minimum characters">{num("email_min_chars", { min: 50 })}</Field>
          <Field label="Maximum characters">{num("email_max_chars", { min: 300, max: 10000 })}</Field>
        </div>
      </Card>
      <FollowUpsEditor
        kind="job"
        title="Default follow-ups"
        value={s.default_followups}
        onChange={(default_followups) => update({ default_followups })}
        variables="Every new application starts with these; you can change them on each application. Variables: {{role}}, {{company}}, {{first_name}}."
      />
    </Section>
  );
}

function OutreachSection({ initial }: { initial: OutreachSettings }) {
  const { value: s, update, num, busy, message, save } = useSaver<OutreachSettings>("/outreach/settings", initial);
  return (
    <Section
      title="Outreach campaigns"
      subtitle="Bulk campaigns. Account limits apply to every campaign together; the schedule is what a new campaign starts with."
      busy={busy}
      message={message}
      onSave={save}
    >
      <Card title="Account limits (all campaigns together)">
        <p className="mb-4 text-sm text-stone-500">
          These also count job applications sent from the same Gmail. A personal Gmail account is allowed 500 emails a day; staying far below that keeps it safe.
        </p>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Emails per 24 hours" hint="Campaigns, follow-ups and applications together">
            {num("daily_limit", { min: 1, max: 400 })}
          </Field>
          <Field label="Seconds between any two emails" hint="Whatever campaign they belong to">
            {num("min_gap_seconds", { min: 5, max: 600 })}
          </Field>
          <Field label="Do not repeat within (days)" hint="Skip people written to recently. 0 turns it off. People who replied are always skipped.">
            {num("skip_recent_days", { min: 0, max: 365 })}
          </Field>
          <Field label="Pause when bounces reach (%)" hint="Checked from 10 emails on">
            {num("bounce_pause_percent", { min: 1, max: 100 })}
          </Field>
        </div>
      </Card>
      <Card title="Schedule for new campaigns">
        <p className="mb-4 text-sm text-stone-500">
          Every campaign gets its own copy of these when it is created, and can change them under Pace and schedule. Editing them here does not touch campaigns that already exist.
        </p>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Shortest wait (seconds)" hint="At least 15">
            {num("default_min_delay_seconds", { min: 15, max: 3600 })}
          </Field>
          <Field label="Longest wait (seconds)">{num("default_max_delay_seconds", { min: 15, max: 7200 })}</Field>
          <Field label="Emails per day, per campaign" hint="Rolling 24 hours">
            {num("default_campaign_daily_limit", { min: 1, max: 400 })}
          </Field>
          <Field label="Time zone" hint="e.g. Asia/Karachi">
            <div className="flex gap-1.5">
              <Input list="settings-timezones" value={s.default_timezone} onChange={(e) => update({ default_timezone: e.target.value })} />
              <Button className="shrink-0 !px-2.5 text-xs" onClick={() => update({ default_timezone: Intl.DateTimeFormat().resolvedOptions().timeZone })}>
                Mine
              </Button>
            </div>
            <datalist id="settings-timezones">{typeof Intl.supportedValuesOf === "function" && Intl.supportedValuesOf("timeZone").map((z) => <option key={z} value={z} />)}</datalist>
          </Field>
          <div className="sm:col-span-2 lg:col-span-4">
            <Check
              label="Send around the clock (24 hours)"
              hint="Emails go out whenever a campaign is running, day or night. Turn off to choose a window."
              checked={s.default_window_start_hour === 0 && s.default_window_end_hour === 24}
              onChange={(v) => update(v ? { default_window_start_hour: 0, default_window_end_hour: 24 } : { default_window_start_hour: 9, default_window_end_hour: 18 })}
            />
          </div>
          <Field label="Send from (hour)" hint="0 to 23">
            {num("default_window_start_hour", { min: 0, max: 23 })}
          </Field>
          <Field label="Until (hour)" hint="1 to 24">
            {num("default_window_end_hour", { min: 1, max: 24 })}
          </Field>
          <div className="space-y-3 sm:col-span-2">
            <Check label="Weekdays only" checked={s.default_weekdays_only} onChange={(v) => update({ default_weekdays_only: v })} />
            <Check label="Warm up" hint="10 emails on day one, 10 more each day, up to the daily limit." checked={s.default_ramp_up} onChange={(v) => update({ default_ramp_up: v })} />
          </div>
        </div>
      </Card>
      <Card title="AI">
        <div className="max-w-sm">
          <Field label="Writing model" hint="Used for templates and for campaigns where the AI writes each email.">
            <ModelSelect value={s.model} onChange={(model) => update({ model })} />
          </Field>
        </div>
      </Card>
    </Section>
  );
}

export default function EmailSettingsPage() {
  const jobs = useApi<JobSettings>("/jobs/settings");
  const outreach = useApi<OutreachSettings>("/outreach/settings");
  return (
    <>
      <PageHeader title="Email settings" subtitle="Gmail, limits and schedules for every tool that sends email, in one place." />
      <div className="space-y-10">
        {/* useSearchParams needs a Suspense boundary so the page can still be prerendered. */}
        <Suspense fallback={<Loading />}>
          <Gmail />
        </Suspense>
        <Notice>{jobs.error || outreach.error}</Notice>
        {(jobs.loading || outreach.loading) && <Loading label="Loading settings…" />}
        {jobs.data && <JobsSection initial={jobs.data} />}
        {outreach.data && <OutreachSection initial={outreach.data} />}
      </div>
    </>
  );
}
