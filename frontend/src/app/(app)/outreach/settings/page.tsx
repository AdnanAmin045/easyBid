"use client";

import Link from "next/link";
import { useState } from "react";
import { Button, Card, Field, Input, Loading, Notice, PageHeader, Select } from "@/components/ui";
import { api, useApi, type OutreachSettings } from "@/lib/api";

const MODELS = [
  { value: "gemini-3.5-flash", label: "Gemini 3.5 Flash (free tier)" },
  { value: "gemini-flash-lite-latest", label: "Gemini Flash Lite (free tier, fastest)" },
  { value: "gemini-pro-latest", label: "Gemini Pro" },
  { value: "claude-sonnet-5-5", label: "Claude Sonnet 5.5" },
  { value: "claude-opus-5-5", label: "Claude Opus 5.5 (best writing)" },
  { value: "claude-haiku-4-5", label: "Claude Haiku 4.5 (cheapest Claude)" },
];

function Form({ initial }: { initial: OutreachSettings }) {
  const [s, setS] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "red" | "green"; text: string } | null>(null);
  const num = (key: keyof OutreachSettings, props: { min?: number; max?: number } = {}) => (
    <Input type="number" {...props} value={String(s[key])} onChange={(e) => setS({ ...s, [key]: Number(e.target.value) })} />
  );

  async function save() {
    setBusy(true);
    setMessage(null);
    try {
      setS(await api<OutreachSettings>("/outreach/settings", { method: "PUT", body: s }));
      setMessage({ tone: "green", text: "Settings saved." });
    } catch (e) {
      setMessage({ tone: "red", text: (e as Error).message });
    }
    setBusy(false);
  }

  return (
    <>
      <Card title="Account limits">
        <p className="mb-4 text-sm text-stone-500">
          These apply to every campaign together, and to job applications sent from the same Gmail. A personal Gmail account is allowed 500 emails a day; staying far below that keeps it safe.
        </p>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Emails per 24 hours" hint="All campaigns and applications together">
            {num("daily_limit", { min: 1, max: 400 })}
          </Field>
          <Field label="Seconds between any two emails" hint="Whatever campaign they belong to">
            {num("min_gap_seconds", { min: 5, max: 600 })}
          </Field>
          <Field label="Do not repeat within (days)" hint="Skip people written to recently. 0 turns it off.">
            {num("skip_recent_days", { min: 0, max: 365 })}
          </Field>
          <Field label="Pause when bounces reach (%)" hint="Checked from 10 emails on">
            {num("bounce_pause_percent", { min: 1, max: 100 })}
          </Field>
        </div>
      </Card>
      <Card title="AI">
        <div className="max-w-sm">
          <Field label="Writing model" hint="Used for templates and for campaigns where the AI writes each email.">
            <Select value={s.model} onChange={(e) => setS({ ...s, model: e.target.value })}>
              {MODELS.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </Select>
          </Field>
        </div>
      </Card>
      <p className="text-sm text-stone-500">
        Your name and signature are set in{" "}
        <Link href="/jobs/settings" className="font-medium text-brand-700 hover:underline">
          Jobs settings
        </Link>
        , together with the Gmail connection.
      </p>
      <div className="sticky bottom-0 -mx-4 flex items-center gap-3 border-t border-stone-300/70 bg-canvas/95 px-4 py-3 md:-mx-8 md:px-8">
        <Button variant="primary" loading={busy} onClick={save}>
          {busy ? "Saving…" : "Save settings"}
        </Button>
        {message && <span className={`text-sm ${message.tone === "red" ? "text-red-700" : "text-emerald-700"}`}>{message.text}</span>}
      </div>
    </>
  );
}

export default function OutreachSettingsPage() {
  const { data, error, loading } = useApi<OutreachSettings>("/outreach/settings");
  return (
    <>
      <PageHeader title="Outreach settings" subtitle="The limits that protect your Gmail account, across all campaigns." />
      <div className="space-y-6">
        <Notice>{error}</Notice>
        {loading && <Loading label="Loading settings…" />}
        {data && <Form initial={data} />}
      </div>
    </>
  );
}
