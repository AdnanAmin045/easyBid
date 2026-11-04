"use client";

import { useState } from "react";
import { Button, Card, Field, Input, Loading, Notice, PageHeader, Select, Textarea } from "@/components/ui";
import { api, apiUpload, useApi, useBlobUrl, type LinkedInDefaults, type LinkedInOverview, type LinkedInSettings, type LinkedInTargetSettings } from "@/lib/api";
import { PromptsEditor } from "./prompts-editor";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const MODELS = [
  { value: "gemini-3.5-flash", label: "Gemini 3.5 Flash (free tier)" },
  { value: "gemini-pro-latest", label: "Gemini Pro (better writing)" },
  { value: "gemini-flash-lite-latest", label: "Gemini Flash Lite (fastest)" },
  { value: "claude-sonnet-5-5", label: "Claude Sonnet 5.5 (needs an Anthropic key)" },
];

function Check({ label, hint, checked, onChange }: { label: string; hint?: string; checked: boolean; onChange: (v: boolean) => void }) {
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

function TargetForm({ title, subtitle, t, onChange }: { title: string; subtitle: string; t: LinkedInTargetSettings; onChange: (t: LinkedInTargetSettings) => void }) {
  const set = (patch: Partial<LinkedInTargetSettings>) => onChange({ ...t, ...patch });
  return (
    <Card title={title}>
      <p className="mb-4 text-sm text-stone-500">{subtitle}</p>
      <div className="space-y-4">
        <Check label="Write a post every day" checked={t.enabled} onChange={(v) => set({ enabled: v })} />
        <Check
          label="Post without asking me"
          hint="Off (recommended at first): each day's post waits for you to approve it. On: the best topic is researched, written, checked and posted at the time below with nobody tapping anything. If LinkedIn is not connected or its login has expired, it stays a draft and you get a Telegram message."
          checked={t.auto_approve}
          onChange={(v) => set({ auto_approve: v })}
        />
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Post time (24h, your time zone)">
            <Input value={t.post_time} maxLength={5} onChange={(e) => set({ post_time: e.target.value })} />
          </Field>
          <Field label="Poster">
            <Select value={t.poster} onChange={(e) => set({ poster: e.target.value as LinkedInTargetSettings["poster"] })}>
              <option value="auto">When the topic suits one</option>
              <option value="always">Every post</option>
              <option value="never">Never</option>
            </Select>
          </Field>
          <Field label="Days">
            <div className="flex flex-wrap gap-1.5">
              {DAYS.map((d, i) => (
                <button
                  key={d}
                  type="button"
                  onClick={() => set({ days: t.days.includes(i) ? t.days.filter((x) => x !== i) : [...t.days, i].sort() })}
                  className={`rounded-md px-2 py-1 text-xs font-medium ring-1 ring-inset ${t.days.includes(i) ? "bg-brand-50 text-brand-700 ring-brand-300" : "bg-white text-stone-500 ring-stone-200"}`}
                >
                  {d}
                </button>
              ))}
            </div>
          </Field>
        </div>
        <Field label="Voice" hint="Who is talking and how. The writer follows this closely.">
          <Textarea rows={3} value={t.voice} maxLength={1500} onChange={(e) => set({ voice: e.target.value })} />
        </Field>
        <Field label="Facts it may state" hint="Services, tools, years of experience, results you can stand behind. Anything not here or in the market data is never claimed as fact.">
          <Textarea rows={5} value={t.about} maxLength={3000} onChange={(e) => set({ about: e.target.value })} />
        </Field>
        <Field label="Audience">
          <Textarea rows={2} value={t.audience} maxLength={500} onChange={(e) => set({ audience: e.target.value })} />
        </Field>
        <Field label="First comment" hint="Posted under every post right after it goes out. A link to your site or booking page works well here, because links in the post itself reduce reach.">
          <Input value={t.first_comment} maxLength={1000} placeholder="Book a free 20-minute call: https://..." onChange={(e) => set({ first_comment: e.target.value })} />
        </Field>
        <Field label="Notes to the writer" hint="Topics to avoid or push, words to use or never use.">
          <Textarea rows={3} value={t.notes} maxLength={1500} onChange={(e) => set({ notes: e.target.value })} />
        </Field>
      </div>
    </Card>
  );
}

function Form({ initial, defaults, reload }: { initial: LinkedInSettings; defaults: LinkedInDefaults; reload: () => void }) {
  const [s, setS] = useState(initial);
  const [mentions, setMentions] = useState(Object.entries(initial.mentions).map(([k, v]) => `${k} = ${v}`).join("\n"));
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "red" | "green"; text: string } | null>(null);
  const [logoVersion, setLogoVersion] = useState(0);
  const [reading, setReading] = useState(false);
  const [siteInfo, setSiteInfo] = useState("");
  const logo = useBlobUrl("/linkedin/logo", logoVersion);

  // The recommended settings, keeping what only you can know: the pages it may tag, the company page id and your name.
  function applyRecommended() {
    if (!confirm("Replace every setting on this page with the recommended ones? Your page id, tagged pages and name are kept. Nothing is saved until you press Save.")) return;
    const d = defaults.settings;
    setS({ ...d, mentions: s.mentions, company_page_id: s.company_page_id, personal_name: s.personal_name });
    setMessage({ tone: "green", text: "Recommended settings are in the form. Press Save to keep them." });
  }

  function parseMentions(): Record<string, string> {
    const out: Record<string, string> = {};
    for (const line of mentions.split("\n")) {
      const [name, ...rest] = line.split("=");
      if (name?.trim() && rest.length) out[name.trim()] = rest.join("=").trim();
    }
    return out;
  }

  const payload = () => ({ ...s, fields: s.fields.filter((f) => f.trim()), mentions: parseMentions() });

  async function readSite() {
    setReading(true);
    setSiteInfo("");
    try {
      await api("/linkedin/settings", { method: "PUT", body: payload() });
      const r = await api<{ text: string }>("/linkedin/site/refresh", { method: "POST" });
      setSiteInfo(`Read ${r.text.length.toLocaleString()} characters from the site.`);
    } catch (e) {
      setSiteInfo((e as Error).message);
    }
    setReading(false);
  }

  async function save() {
    setBusy(true);
    setMessage(null);
    try {
      await api("/linkedin/settings", { method: "PUT", body: payload() });
      setMessage({ tone: "green", text: "Saved." });
      reload();
    } catch (e) {
      setMessage({ tone: "red", text: (e as Error).message });
    }
    setBusy(false);
  }

  async function upload(file: File | undefined) {
    if (!file) return;
    try {
      await apiUpload("/linkedin/logo", file);
      setLogoVersion((v) => v + 1);
      setMessage({ tone: "green", text: "Logo uploaded. New posters use it." });
    } catch (e) {
      setMessage({ tone: "red", text: (e as Error).message });
    }
  }

  async function removeLogo() {
    await api("/linkedin/logo", { method: "DELETE" });
    setLogoVersion((v) => v + 1);
  }

  return (
    <div className="space-y-6">
      <Card title="Brand and schedule">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Brand name (on posters)">
            <Input value={s.brand_name} maxLength={60} onChange={(e) => setS({ ...s, brand_name: e.target.value })} />
          </Field>
          <Field label="Website (on posters)">
            <Input value={s.website} maxLength={120} placeholder="codevryn.com" onChange={(e) => setS({ ...s, website: e.target.value })} />
          </Field>
          <Field label="Poster background">
            <div className="flex items-center gap-2">
              <input type="color" value={s.brand_primary} onChange={(e) => setS({ ...s, brand_primary: e.target.value })} className="h-9 w-12 rounded border border-stone-300" />
              <Input value={s.brand_primary} maxLength={7} onChange={(e) => setS({ ...s, brand_primary: e.target.value })} />
            </div>
          </Field>
          <Field label="Accent colour">
            <div className="flex items-center gap-2">
              <input type="color" value={s.brand_accent} onChange={(e) => setS({ ...s, brand_accent: e.target.value })} className="h-9 w-12 rounded border border-stone-300" />
              <Input value={s.brand_accent} maxLength={7} onChange={(e) => setS({ ...s, brand_accent: e.target.value })} />
            </div>
          </Field>
          <div className="sm:col-span-2">
            <Field label="Logo" hint="PNG with a transparent background looks best. Without one, posters show the first letter of the brand name.">
              <div className="flex items-center gap-3">
                {logo && (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={logo} alt="Logo" className="h-12 max-w-48 rounded bg-stone-800 p-1.5 object-contain" />
                )}
                <input type="file" accept="image/png,image/jpeg,image/webp" onChange={(e) => upload(e.target.files?.[0])} className="text-sm" />
                {logo && <Button onClick={removeLogo}>Remove</Button>}
              </div>
            </Field>
          </div>
          <Field label="Time zone" hint="Post times and the daily draft follow this, e.g. Asia/Karachi or America/New_York.">
            <Input value={s.timezone} onChange={(e) => setS({ ...s, timezone: e.target.value })} />
          </Field>
          <Field label="Write the day's draft at" hint="Leave a few hours before the post time to review it.">
            <Input value={s.generate_time} maxLength={5} onChange={(e) => setS({ ...s, generate_time: e.target.value })} />
          </Field>
          <Field label="Writing model" hint="When Gemini's free quota for the day is used up, posts are written by Groq instead, if GROQ_API_KEY (free) is set on the server.">
            <Select value={s.model} onChange={(e) => setS({ ...s, model: e.target.value })}>
              {MODELS.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Company page id" hint="The number in linkedin.com/company/<number>/admin. Needed to post as the page.">
            <Input value={s.company_page_id} maxLength={20} inputMode="numeric" onChange={(e) => setS({ ...s, company_page_id: e.target.value.replace(/\D/g, "") })} />
          </Field>
          <div className="sm:col-span-2">
            <Field label="Company website it reads" hint="Company posts may state anything that is on this site (services, process, technologies) and nothing else about the company. It is read again every week.">
              <div className="flex gap-2">
                <Input value={s.website_url} maxLength={200} placeholder="https://codevryn.com" onChange={(e) => setS({ ...s, website_url: e.target.value })} />
                <Button loading={reading} onClick={readSite}>
                  Read it now
                </Button>
              </div>
            </Field>
            {siteInfo && <p className="mt-1 text-xs text-stone-500">{siteInfo}</p>}
          </div>
          <div className="sm:col-span-2">
            <Field label="Fields to follow" hint="One per line, up to 6. Every day the web is searched for what happened in these fields, and the posts are about that.">
              <Textarea rows={5} value={s.fields.join("\n")} onChange={(e) => setS({ ...s, fields: e.target.value.split("\n") })} />
            </Field>
          </div>
          <div className="sm:col-span-2">
            <Field
              label="Pages it may tag"
              hint="One per line: Name = urn:li:organization:12345. The name must match the LinkedIn page exactly. LinkedIn does not let apps tag people, only pages."
            >
              <Textarea rows={3} value={mentions} onChange={(e) => setMentions(e.target.value)} placeholder="Codevryn = urn:li:organization:12345678" />
            </Field>
          </div>
          <div className="sm:col-span-2">
            <Check
              label="Write drafts even when a profile is not connected"
              hint="So you can copy the text and poster and post by hand, for example for the company page while LinkedIn reviews its API access."
              checked={s.draft_without_connection}
              onChange={(v) => setS({ ...s, draft_without_connection: v })}
            />
          </div>
        </div>
      </Card>
      <Card title="Personal profile posters">
        <p className="mb-4 text-sm text-stone-500">
          Posters for your own profile look different from the company&apos;s: no logo and no website, just you. They are there to inform and start a conversation, not to advertise.
        </p>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Your name on posters" hint="Leave blank to use the name of the connected LinkedIn account.">
            <Input value={s.personal_name} maxLength={80} onChange={(e) => setS({ ...s, personal_name: e.target.value })} />
          </Field>
          <Field label="What you do (under your name)">
            <Input value={s.personal_title} maxLength={60} onChange={(e) => setS({ ...s, personal_title: e.target.value })} />
          </Field>
          <Field label="Poster background">
            <div className="flex items-center gap-2">
              <input type="color" value={s.personal_primary} onChange={(e) => setS({ ...s, personal_primary: e.target.value })} className="h-9 w-12 rounded border border-stone-300" />
              <Input value={s.personal_primary} maxLength={7} onChange={(e) => setS({ ...s, personal_primary: e.target.value })} />
            </div>
          </Field>
          <Field label="Accent colour">
            <div className="flex items-center gap-2">
              <input type="color" value={s.personal_accent} onChange={(e) => setS({ ...s, personal_accent: e.target.value })} className="h-9 w-12 rounded border border-stone-300" />
              <Input value={s.personal_accent} maxLength={7} onChange={(e) => setS({ ...s, personal_accent: e.target.value })} />
            </div>
          </Field>
        </div>
      </Card>
      <TargetForm
        title="Personal profile"
        subtitle="Informative, built to start conversations with people who buy or build software."
        t={s.personal}
        onChange={(personal) => setS({ ...s, personal })}
      />
      <TargetForm title="Company page" subtitle="The studio's voice: what it does, how it works, what it has learned." t={s.company} onChange={(company) => setS({ ...s, company })} />
      <PromptsEditor s={s} setS={setS} defaults={defaults} />
      <div className="sticky bottom-0 -mx-4 flex flex-wrap items-center gap-3 border-t border-stone-200 bg-canvas/90 px-4 py-3 backdrop-blur md:-mx-8 md:px-8">
        <Button variant="primary" loading={busy} onClick={save}>
          {busy ? "Saving…" : "Save settings"}
        </Button>
        <Button onClick={applyRecommended}>Use recommended settings</Button>
        {message && <span className={`text-sm ${message.tone === "red" ? "text-red-700" : "text-emerald-700"}`}>{message.text}</span>}
      </div>
    </div>
  );
}

export default function LinkedInSettingsPage() {
  const overview = useApi<LinkedInOverview>("/linkedin/overview");
  const defaults = useApi<LinkedInDefaults>("/linkedin/settings/defaults");
  return (
    <>
      <PageHeader title="LinkedIn settings" subtitle="How each profile sounds, when it posts, how topics are chosen and what its posters look like." />
      <Notice>{overview.error || defaults.error}</Notice>
      {overview.loading || defaults.loading || !overview.data || !defaults.data ? (
        <Loading />
      ) : (
        <Form initial={overview.data.settings} defaults={defaults.data} reload={overview.reload} />
      )}
    </>
  );
}
