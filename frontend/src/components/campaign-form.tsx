"use client";

import { useRef, useState } from "react";
import { FollowUpsEditor } from "@/components/followups-editor";
import { Button, Card, Field, Input, Notice, Select, Textarea } from "@/components/ui";
import { api, useApi, type CampaignInput, type GmailStatus, type OutreachTemplate, type Resume } from "@/lib/api";

export const EMPTY_CAMPAIGN: CampaignInput = {
  name: "",
  mode: "template",
  subject_template: "Quick question, {{first_name|there}}",
  body_template: "{Hi|Hello} {{first_name|there}},\n\n",
  ai_brief: "",
  footer: "",
  append_signature: true,
  resume_id: null,
  attach_first: true,
  gmail_account_id: null,
  min_delay_seconds: 45,
  max_delay_seconds: 150,
  daily_limit: 40,
  window_start_hour: 0,
  window_end_hour: 24,
  timezone: "UTC",
  weekdays_only: false,
  ramp_up: true,
  followups: [],
};

const BUILTIN = ["first_name", "name", "company", "email"];

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

function SendFrom({ value, onChange }: { value: number | null; onChange: (value: number | null) => void }) {
  const { data } = useApi<GmailStatus>("/jobs/gmail");
  const accounts = data?.accounts ?? [];
  const fallback = accounts.find((a) => a.is_default);
  return (
    <Card title="Send from">
      <div className="max-w-md">
        <Field
          label="Sending account"
          hint="Its limits, name and signature apply, and its follow-ups and replies stay on it. Add more accounts in Email settings."
        >
          <Select value={value ?? ""} onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}>
            <option value="">{fallback ? `Default (${fallback.email})` : "Default account"}</option>
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.email}
              </option>
            ))}
          </Select>
        </Field>
      </div>
    </Card>
  );
}

function TemplateWriter({ columns, onWritten }: { columns: string[]; onWritten: (subject: string, body: string) => void }) {
  const [brief, setBrief] = useState("");
  const [tone, setTone] = useState("friendly and direct");
  const [language, setLanguage] = useState("English");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function write() {
    setBusy(true);
    setError("");
    try {
      const result = await api<{ subject: string; body: string }>("/outreach/templates/generate", {
        method: "POST",
        body: { brief, tone, language, variables: columns },
      });
      onWritten(result.subject, result.body);
    } catch (e) {
      setError((e as Error).message);
    }
    setBusy(false);
  }

  return (
    <div className="rounded-[10px] border border-brand-200 bg-brand-50/40 p-4">
      <p className="mb-3 text-sm font-medium text-stone-800">Write the template with AI</p>
      <Notice>{error}</Notice>
      <Field label="What is this email about?" hint="Who you write to, what you offer, what you want back. The AI adds {{variables}} and wording options.">
        <Textarea rows={3} maxLength={4000} value={brief} onChange={(e) => setBrief(e.target.value)} placeholder="Offer web development services to small logistics companies and ask for a 15 minute call." />
      </Field>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <Field label="Tone">
          <Input value={tone} maxLength={100} onChange={(e) => setTone(e.target.value)} />
        </Field>
        <Field label="Language">
          <Input value={language} maxLength={40} onChange={(e) => setLanguage(e.target.value)} />
        </Field>
      </div>
      <Button className="mt-3" variant="dark" loading={busy} disabled={brief.trim().length < 10} onClick={write}>
        {busy ? "Writing…" : "Write template"}
      </Button>
    </div>
  );
}

export function CampaignForm({
  initial,
  columns = [],
  submitLabel,
  onSubmit,
}: {
  initial: CampaignInput;
  columns?: string[];
  submitLabel: string;
  onSubmit: (input: CampaignInput) => Promise<void>;
}) {
  // Only the editable fields: a loaded campaign also carries counts and status, which the API rejects.
  const [c, setC] = useState<CampaignInput>(() => {
    const picked = {} as Record<string, unknown>;
    for (const key of Object.keys(EMPTY_CAMPAIGN)) picked[key] = initial[key as keyof CampaignInput];
    return picked as unknown as CampaignInput;
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [showWriter, setShowWriter] = useState(false);
  const bodyRef = useRef<HTMLTextAreaElement>(null);
  const { data: resumes } = useApi<Resume[]>("/jobs/resumes");
  const { data: templates, reload: reloadTemplates } = useApi<OutreachTemplate[]>("/outreach/templates");
  const update = (patch: Partial<CampaignInput>) => setC((current) => ({ ...current, ...patch }));
  const num = (key: keyof CampaignInput, props: { min?: number; max?: number } = {}) => (
    <Input type="number" {...props} value={String(c[key])} onChange={(e) => update({ [key]: Number(e.target.value) } as Partial<CampaignInput>)} />
  );
  const variables = [...BUILTIN, ...columns.filter((v) => !BUILTIN.includes(v))];

  function insert(variable: string) {
    const field = bodyRef.current;
    const token = `{{${variable}}}`;
    if (!field) return update({ body_template: c.body_template + token });
    const { selectionStart: from, selectionEnd: to } = field;
    update({ body_template: c.body_template.slice(0, from) + token + c.body_template.slice(to) });
    requestAnimationFrame(() => {
      field.focus();
      field.setSelectionRange(from + token.length, from + token.length);
    });
  }

  async function saveTemplate() {
    const name = prompt("Name this template");
    if (!name?.trim()) return;
    setError("");
    try {
      await api("/outreach/templates", { method: "POST", body: { name: name.trim(), subject: c.subject_template, body: c.body_template } });
      reloadTemplates();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function submit() {
    setBusy(true);
    setError("");
    try {
      await onSubmit(c);
    } catch (e) {
      setError((e as Error).message);
    }
    setBusy(false);
  }

  return (
    <div className="space-y-6">
      <Notice>{error}</Notice>
      <Card title="Campaign">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Name" hint="For you only, e.g. Logistics agencies, October">
            <Input value={c.name} maxLength={160} onChange={(e) => update({ name: e.target.value })} />
          </Field>
          <Field label="How are the emails written?">
            <Select value={c.mode} onChange={(e) => update({ mode: e.target.value as CampaignInput["mode"] })}>
              <option value="template">One template, filled in for each person</option>
              <option value="ai">The AI writes each email separately</option>
            </Select>
          </Field>
        </div>
      </Card>

      <Card
        title="Email"
        action={
          c.mode === "template" && (
            <div className="flex flex-wrap items-center gap-2">
              {templates && templates.length > 0 && (
                <Select
                  aria-label="Use a saved template"
                  className="!w-48 !py-1"
                  value=""
                  onChange={(e) => {
                    const t = templates.find((x) => x.id === Number(e.target.value));
                    if (t) update({ subject_template: t.subject, body_template: t.body });
                  }}
                >
                  <option value="">Use saved template…</option>
                  {templates.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name}
                    </option>
                  ))}
                </Select>
              )}
              <Button className="!px-2.5 !py-1 text-xs" onClick={() => setShowWriter(!showWriter)}>
                Write with AI
              </Button>
              <Button className="!px-2.5 !py-1 text-xs" disabled={!c.subject_template.trim() || !c.body_template.trim()} onClick={saveTemplate}>
                Save as template
              </Button>
            </div>
          )
        }
      >
        {c.mode === "ai" ? (
          <Field label="Brief for the AI" hint="Who you are, what you offer and what you want from the reader. It writes a separate email for each person from their name, company and any other columns.">
            <Textarea rows={6} maxLength={4000} value={c.ai_brief} onChange={(e) => update({ ai_brief: e.target.value })} placeholder="I run a small React and Node.js studio. Offer a free 30 minute audit of their web app and ask whether they want it." />
          </Field>
        ) : (
          <div className="space-y-4">
            {showWriter && <TemplateWriter columns={columns} onWritten={(subject, body) => update({ subject_template: subject, body_template: body })} />}
            <Field label="Subject">
              <Input value={c.subject_template} maxLength={300} onChange={(e) => update({ subject_template: e.target.value })} />
            </Field>
            <Field label="Message">
              <Textarea ref={bodyRef} rows={12} value={c.body_template} onChange={(e) => update({ body_template: e.target.value })} />
            </Field>
            <div>
              <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
                <span className="mr-1 text-xs text-stone-500">Insert</span>
                {variables.map((v) => (
                  <button key={v} type="button" onClick={() => insert(v)} className="rounded-[4px] bg-stone-100 px-1.5 py-0.5 font-mono text-xs text-stone-700 hover:bg-brand-100 hover:text-brand-800">
                    {`{{${v}}}`}
                  </button>
                ))}
              </div>
              <p className="text-xs text-stone-500">
                <code>{"{{first_name|there}}"}</code> uses &quot;there&quot; when the name is empty. <code>{"{Hi|Hello|Hey}"}</code> picks one wording per person, so no two emails are identical. Columns of your
                list become variables too. Rows in the list can bring their own subject and message, which are sent as written.
              </p>
            </div>
          </div>
        )}
        <div className="mt-5 grid gap-4 border-t border-stone-200 pt-4 sm:grid-cols-2">
          <Field label="Footer" hint="Optional last line, e.g. an opt-out: If this isn't relevant, just reply 'no thanks' and I won't write again.">
            <Textarea rows={2} maxLength={1000} value={c.footer} onChange={(e) => update({ footer: e.target.value })} />
          </Field>
          <div className="space-y-4">
            <Field
              label="Attach a CV"
              hint={
                resumes && resumes.length === 0
                  ? "No CV uploaded yet. Upload one in Jobs > Profile & CVs, then choose it here."
                  : "The CV used by the switches below, and by any follow-up set to carry it."
              }
            >
              <Select value={c.resume_id ?? ""} onChange={(e) => update({ resume_id: e.target.value ? Number(e.target.value) : null, attach_first: true })}>
                <option value="">No attachment</option>
                {resumes?.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name} · {r.filename}
                  </option>
                ))}
              </Select>
            </Field>
            <Check
              label="Attach the CV to the first email"
              hint={c.resume_id ? undefined : "Choose a CV above first."}
              checked={c.attach_first && c.resume_id !== null}
              onChange={(v) => update({ attach_first: v })}
            />
            <Check label="Add my signature" hint="From Email settings. Turn off when your own messages already end with a signature." checked={c.append_signature} onChange={(v) => update({ append_signature: v })} />
          </div>
        </div>
      </Card>

      <FollowUpsEditor
        kind="campaign"
        value={c.followups}
        onChange={(followups) => update({ followups })}
        variables="Variables like {{first_name|there}} and your list's columns work here too."
      />

      <SendFrom value={c.gmail_account_id} onChange={(gmail_account_id) => update({ gmail_account_id })} />

      <Card title="Pace and schedule">
        <p className="mb-4 text-sm text-stone-500">
          Emails go out one at a time with a random wait in between, only inside the window below. This is what keeps a personal Gmail account from being flagged.
        </p>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Shortest wait (seconds)" hint="At least 15">
            {num("min_delay_seconds", { min: 15, max: 3600 })}
          </Field>
          <Field label="Longest wait (seconds)">{num("max_delay_seconds", { min: 15, max: 7200 })}</Field>
          <Field label="Emails per day" hint="Rolling 24 hours">
            {num("daily_limit", { min: 1 })}
          </Field>
          <Field label="Time zone" hint="e.g. Asia/Karachi">
            <div className="flex gap-1.5">
              <Input list="timezones" value={c.timezone} onChange={(e) => update({ timezone: e.target.value })} />
              <Button className="shrink-0 !px-2.5 text-xs" onClick={() => update({ timezone: Intl.DateTimeFormat().resolvedOptions().timeZone })}>
                Mine
              </Button>
            </div>
            <datalist id="timezones">{typeof Intl.supportedValuesOf === "function" && Intl.supportedValuesOf("timeZone").map((z) => <option key={z} value={z} />)}</datalist>
          </Field>
          <div className="sm:col-span-2 lg:col-span-4">
            <Check
              label="Send around the clock (24 hours)"
              hint="Emails go out whenever the campaign is running, day or night. Turn off to choose a window."
              checked={c.window_start_hour === 0 && c.window_end_hour === 24}
              onChange={(v) => update(v ? { window_start_hour: 0, window_end_hour: 24 } : { window_start_hour: 9, window_end_hour: 18 })}
            />
          </div>
          <Field label="Send from (hour)" hint="0 to 23">
            {num("window_start_hour", { min: 0, max: 23 })}
          </Field>
          <Field label="Until (hour)" hint="1 to 24">
            {num("window_end_hour", { min: 1, max: 24 })}
          </Field>
          <div className="space-y-3 sm:col-span-2">
            <Check label="Weekdays only" checked={c.weekdays_only} onChange={(v) => update({ weekdays_only: v })} />
            <Check label="Warm up" hint="10 emails on day one, 10 more each day, up to the daily limit." checked={c.ramp_up} onChange={(v) => update({ ramp_up: v })} />
          </div>
        </div>
      </Card>

      <div className="sticky bottom-0 -mx-4 flex items-center gap-3 border-t border-stone-300/70 bg-canvas/95 px-4 py-3 md:-mx-8 md:px-8">
        <Button variant="primary" loading={busy} disabled={!c.name.trim()} onClick={submit}>
          {busy ? "Saving…" : submitLabel}
        </Button>
      </div>
    </div>
  );
}
