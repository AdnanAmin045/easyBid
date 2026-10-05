"use client";

import { useState } from "react";
import { Button, Card, Field, Input, Loading, Notice, PageHeader, Select } from "@/components/ui";
import { api, useApi, type Account, type Settings, type Skill } from "@/lib/api";

const MODELS = [
  { value: "claude-opus-5-5", label: "Claude Opus 5.5 (best quality)" },
  { value: "claude-sonnet-5-5", label: "Claude Sonnet 5.5 (cheaper)" },
  { value: "claude-haiku-4-5", label: "Claude Haiku 4.5 (cheapest Claude)" },
  { value: "gemini-3.5-flash", label: "Gemini 3.5 Flash (free tier)" },
  { value: "gemini-flash-latest", label: "Gemini Flash, newest (free tier, often busy)" },
  { value: "gemini-flash-lite-latest", label: "Gemini Flash Lite (free tier, fastest)" },
  { value: "gemini-pro-latest", label: "Gemini Pro" },
  { value: "cerebras/gpt-oss-120b", label: "Cerebras GPT-OSS 120B (free tier)" },
  { value: "cerebras/llama-3.3-70b", label: "Cerebras Llama 3.3 70B (free tier)" },
  { value: "groq/openai/gpt-oss-120b", label: "Groq GPT-OSS 120B (free tier)" },
  { value: "groq/llama-3.3-70b-versatile", label: "Groq Llama 3.3 70B (free tier)" },
  { value: "groq/llama-3.1-8b-instant", label: "Groq Llama 3.1 8B (free tier, for choosing only)" },
  { value: "mistral/mistral-small-latest", label: "Mistral Small (free tier)" },
  { value: "mistral/mistral-medium-latest", label: "Mistral Medium (free tier)" },
];
const modelLabel = (value: string) => MODELS.find((m) => m.value === value)?.label ?? value;
const UPGRADES = [
  { value: "NDA", label: "NDA required" },
  { value: "sealed", label: "Sealed bids" },
  { value: "fulltime", label: "Full-time" },
];

const toSkills = (ids: number[], names: string[]): Skill[] => ids.map((id, i) => ({ id, name: names[i] ?? String(id) }));
const toList = (text: string) => text.split(",").map((s) => s.trim()).filter(Boolean);

function FallbackModels({ title, models, onChange }: { title: string; models: string[]; onChange: (models: string[]) => void }) {
  const [custom, setCustom] = useState("");
  const add = (model: string) => {
    const value = model.trim();
    if (value && !models.includes(value)) onChange([...models, value]);
  };
  const move = (i: number, by: number) => {
    const next = [...models];
    [next[i], next[i + by]] = [next[i + by], next[i]];
    onChange(next);
  };
  return (
    <div>
      <span className="mb-1.5 block text-[13px] font-medium text-stone-700">{title}</span>
      {models.length === 0 && <p className="mb-2 text-xs text-stone-500">No fallbacks: bidding waits when the main model is out of quota.</p>}
      <ol className="mb-2 space-y-1">
        {models.map((model, i) => (
          <li key={model} className="flex items-center gap-2 rounded-[6px] border border-stone-200 px-2 py-1 text-sm">
            <span className="w-5 text-xs text-stone-500">{i + 1}.</span>
            <span className="flex-1 truncate">{modelLabel(model)}</span>
            <button type="button" aria-label="Move up" disabled={i === 0} className="px-1 disabled:opacity-30" onClick={() => move(i, -1)}>↑</button>
            <button type="button" aria-label="Move down" disabled={i === models.length - 1} className="px-1 disabled:opacity-30" onClick={() => move(i, 1)}>↓</button>
            <button type="button" aria-label={`Remove ${model}`} className="px-1" onClick={() => onChange(models.filter((m) => m !== model))}>×</button>
          </li>
        ))}
      </ol>
      <div className="flex gap-2">
        <Select value="" onChange={(e) => add(e.target.value)}>
          <option value="">Add a fallback model…</option>
          {MODELS.filter((m) => !models.includes(m.value)).map((m) => (
            <option key={m.value} value={m.value}>
              {m.label}
            </option>
          ))}
        </Select>
      </div>
      <form
        className="mt-2 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          add(custom);
          setCustom("");
        }}
      >
        <Input value={custom} placeholder="Or type a model id, e.g. groq/qwen/qwen3-32b" onChange={(e) => setCustom(e.target.value)} />
        <Button type="submit" disabled={!custom.trim()}>Add</Button>
      </form>
    </div>
  );
}

interface SkillPickerProps {
  title: string;
  hint: string;
  empty: string;
  selected: Skill[];
  onChange: (skills: Skill[]) => void;
  importable?: boolean;
  blocked?: boolean;
}

function SkillPicker({ title, hint, empty, selected, onChange, importable, blocked }: SkillPickerProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Skill[]>([]);
  const [error, setError] = useState("");
  // Which request is running: "import" or "search".
  const [busy, setBusy] = useState("");

  const selectedIds = selected.map((s) => s.id);
  const add = (skills: Skill[]) => onChange([...selected, ...skills.filter((s) => !selectedIds.includes(s.id))]);
  const chip = blocked ? "bg-red-50 text-red-700" : "bg-brand-50 text-brand-700";

  async function run(name: string, fn: () => Promise<void>) {
    setBusy(name);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    }
    setBusy("");
  }

  return (
    <Card
      title={title}
      action={
        importable && (
          <Button
            loading={busy === "import"}
            disabled={Boolean(busy)}
            onClick={() => run("import", async () => add((await api<Account>("/account?refresh=true")).skills))}
          >
            {busy === "import" ? "Importing…" : "Import from my Freelancer profile"}
          </Button>
        )
      }
    >
      <Notice>{error}</Notice>
      <p className="mb-3 text-sm text-stone-500">{hint}</p>
      <div className="mb-4 flex flex-wrap gap-2">
        {selected.length === 0 && <span className="text-sm text-stone-500">{empty}</span>}
        {selected.map((skill) => (
          <span key={skill.id} className={`inline-flex items-center gap-1 rounded-full py-1 pl-3 pr-1 text-xs font-medium ${chip}`}>
            {skill.name}
            <button
              type="button"
              aria-label={`Remove ${skill.name}`}
              className="rounded-full px-1.5 hover:bg-black/5"
              onClick={() => onChange(selected.filter((s) => s.id !== skill.id))}
            >
              ×
            </button>
          </span>
        ))}
      </div>
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          run("search", async () => setResults(await api<Skill[]>(`/skills?q=${encodeURIComponent(query)}`)));
        }}
      >
        <Input value={query} placeholder="Search skills, e.g. Next.js" onChange={(e) => setQuery(e.target.value)} />
        <Button type="submit" loading={busy === "search"} disabled={Boolean(busy) || !query.trim()}>
          {busy === "search" ? "Searching…" : "Search"}
        </Button>
      </form>
      {results.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {results
            .filter((s) => !selectedIds.includes(s.id))
            .map((skill) => (
              <button key={skill.id} type="button" className="rounded-full border border-stone-300 px-3 py-1 text-xs hover:bg-stone-50" onClick={() => add([skill])}>
                + {skill.name}
              </button>
            ))}
        </div>
      )}
    </Card>
  );
}

function SettingsForm({ initial }: { initial: Settings }) {
  const [s, setS] = useState(initial);
  const [lists, setLists] = useState({
    exclude_keywords: initial.exclude_keywords.join(", "),
    currencies: initial.currencies.join(", "),
    languages: initial.languages.join(", "),
  });
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "red" | "green"; text: string } | null>(null);

  const update = (patch: Partial<Settings>) => setS((current) => ({ ...current, ...patch }));
  const num = (key: keyof Settings, props: { min?: number; max?: number; step?: number } = {}) => (
    <Input type="number" {...props} value={String(s[key])} onChange={(e) => update({ [key]: Number(e.target.value) } as Partial<Settings>)} />
  );
  const toggle = <T extends string>(list: T[], value: T) => (list.includes(value) ? list.filter((v) => v !== value) : [...list, value]);

  async function save() {
    setBusy(true);
    setMessage(null);
    try {
      const body: Settings = {
        ...s,
        exclude_keywords: toList(lists.exclude_keywords),
        currencies: toList(lists.currencies).map((c) => c.toUpperCase()),
        languages: toList(lists.languages).map((l) => l.toLowerCase()),
      };
      setS(await api<Settings>("/settings", { method: "PUT", body }));
      setMessage({ tone: "green", text: "Settings saved." });
    } catch (e) {
      setMessage({ tone: "red", text: (e as Error).message });
    }
    setBusy(false);
  }

  return (
    <div className="space-y-6">
      <SkillPicker
        title="My skills"
        hint="Projects tagged with any of these are fetched, and these are the skills a project is matched against."
        empty="No skills selected. Nothing will be fetched."
        importable
        selected={toSkills(s.skill_ids, s.skill_names)}
        onChange={(skills) => update({ skill_ids: skills.map((k) => k.id), skill_names: skills.map((k) => k.name) })}
      />

      <Card title="Skill match">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Field
            label="Minimum matching skills"
            hint="How many of a project's skill tags must be in My skills. At 2, a project that only shares one loose tag with you is dropped. 0 turns this off."
          >
            {num("min_skill_matches", { min: 0, max: 20 })}
          </Field>
        </div>
      </Card>

      <SkillPicker
        title="Blocked skills"
        hint="A project tagged with any of these is dropped, even if it also matches your skills."
        empty="Nothing blocked."
        blocked
        selected={toSkills(s.blocked_skill_ids, s.blocked_skill_names)}
        onChange={(skills) => update({ blocked_skill_ids: skills.map((k) => k.id), blocked_skill_names: skills.map((k) => k.name) })}
      />

      <Card title="Bidding">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="Mode">
            <Select value={s.mode} onChange={(e) => update({ mode: e.target.value as Settings["mode"] })}>
              <option value="manual">Manual: I approve every bid</option>
              <option value="semi">Semi-auto: high scores are sent</option>
              <option value="auto">Auto: every selected project</option>
            </Select>
          </Field>
          <Field label="Daily bid cap" hint="Applies in every mode. Resets at 00:00 UTC.">
            {num("daily_bid_cap", { min: 0 })}
          </Field>
          <Field label="Semi-auto score" hint="In semi-auto, this score or higher is sent without approval.">
            {num("semi_auto_min_score", { min: 0, max: 100 })}
          </Field>
          <Field label="Check every (seconds)">{num("poll_interval_seconds", { min: 30, max: 3600 })}</Field>
          <Field label="Projects per check" hint="Limits AI cost per run.">
            {num("max_projects_per_cycle", { min: 1, max: 50 })}
          </Field>
        </div>
      </Card>

      <Card title="Rules">
        <p className="mb-4 text-sm text-stone-500">Checked before any AI call. A project that fails a rule costs nothing.</p>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="Minimum fixed budget (USD)" hint="Compared with the top of the client's range.">
            {num("min_fixed_budget", { min: 0 })}
          </Field>
          <Field label="Minimum hourly rate (USD)">{num("min_hourly_rate", { min: 0 })}</Field>
          <Field label="Maximum existing bids">{num("max_bid_count", { min: 0 })}</Field>
          <Field label="Maximum age (minutes)">{num("max_age_minutes", { min: 1 })}</Field>
          <Field label="Minimum score" hint="0 turns this off.">
            {num("min_score", { min: 0, max: 100 })}
          </Field>
          <Field label="Languages" hint="Codes, comma-separated. Empty means any.">
            <Input value={lists.languages} onChange={(e) => setLists({ ...lists, languages: e.target.value })} />
          </Field>
          <Field label="Currencies" hint="e.g. USD, EUR. Empty means any.">
            <Input value={lists.currencies} onChange={(e) => setLists({ ...lists, currencies: e.target.value })} />
          </Field>
          <div className="sm:col-span-2">
            <Field label="Excluded keywords" hint="Comma-separated. A project containing any of these is dropped.">
              <Input value={lists.exclude_keywords} onChange={(e) => setLists({ ...lists, exclude_keywords: e.target.value })} />
            </Field>
          </div>
        </div>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <fieldset>
            <legend className="mb-1 text-sm font-medium text-stone-700">Project types</legend>
            {(["fixed", "hourly"] as const).map((type) => (
              <label key={type} className="mr-4 inline-flex items-center gap-2 text-sm capitalize">
                <input type="checkbox" checked={s.project_types.includes(type)} onChange={() => update({ project_types: toggle(s.project_types, type) })} />
                {type}
              </label>
            ))}
          </fieldset>
          <fieldset>
            <legend className="mb-1 text-sm font-medium text-stone-700">Skip projects marked</legend>
            {UPGRADES.map((upgrade) => (
              <label key={upgrade.value} className="mr-4 inline-flex items-center gap-2 text-sm">
                <input type="checkbox" checked={s.skip_upgrades.includes(upgrade.value)} onChange={() => update({ skip_upgrades: toggle(s.skip_upgrades, upgrade.value) })} />
                {upgrade.label}
              </label>
            ))}
          </fieldset>
        </div>
      </Card>

      <Card title="Pricing">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="Fixed price position" hint="0 bids the client's minimum, 1 the maximum, 0.6 a little above the middle.">
            {num("fixed_budget_position", { min: 0, max: 1, step: 0.05 })}
          </Field>
          <Field label="Delivery time (days)">{num("default_period_days", { min: 1 })}</Field>
          <Field label="Milestone %" hint="Share of the bid requested as the first milestone.">
            {num("milestone_percentage", { min: 1, max: 100 })}
          </Field>
          <Field label="Hourly rate (USD)" hint="Kept inside the client's range.">
            {num("hourly_rate", { min: 1 })}
          </Field>
          <Field label="Hours per week" hint="Used when the client does not state it.">
            {num("hourly_weekly_hours", { min: 1, max: 168 })}
          </Field>
        </div>
      </Card>

      <Card title="AI">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Model for choosing projects">
            <Select value={s.selection_model} onChange={(e) => update({ selection_model: e.target.value })}>
              {MODELS.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Model for writing proposals">
            <Select value={s.proposal_model} onChange={(e) => update({ proposal_model: e.target.value })}>
              {MODELS.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </Select>
          </Field>
          <FallbackModels
            title="If it is out of quota, choose with"
            models={s.selection_fallback_models}
            onChange={(selection_fallback_models) => update({ selection_fallback_models })}
          />
          <FallbackModels
            title="If it is out of quota, write with"
            models={s.proposal_fallback_models}
            onChange={(proposal_fallback_models) => update({ proposal_fallback_models })}
          />
          <p className="text-xs text-stone-500 sm:col-span-2">
            Fallbacks are tried in order. Each provider needs its key on the server (GEMINI_API_KEY, GROQ_API_KEY, CEREBRAS_API_KEY,
            MISTRAL_API_KEY); models without a key are skipped. With GEMINI_API_KEY_2 to _5 set, each Gemini key tries every
            Gemini model, cheapest to best, before the next key takes over.
          </p>
          <Field label="Proposal minimum characters">{num("proposal_min_chars", { min: 1 })}</Field>
          <Field label="Proposal maximum characters">{num("proposal_max_chars", { min: 100 })}</Field>
        </div>
      </Card>

      <div className="sticky bottom-0 -mx-4 flex items-center gap-3 border-t border-stone-200 bg-white/95 px-4 py-3 md:-mx-8 md:px-8">
        <Button variant="primary" loading={busy} onClick={save}>
          {busy ? "Saving…" : "Save settings"}
        </Button>
        {message && <span className={`text-sm ${message.tone === "red" ? "text-red-700" : "text-emerald-700"}`}>{message.text}</span>}
      </div>
    </div>
  );
}

export default function SettingsPage() {
  const { data, error, loading } = useApi<Settings>("/settings");
  return (
    <>
      <PageHeader title="Settings" subtitle="Which projects to fetch, the rules they must pass, and how bids are priced." />
      <Notice>{error}</Notice>
      {loading && <Loading label="Loading settings…" />}
      {data && <SettingsForm initial={data} />}
    </>
  );
}
