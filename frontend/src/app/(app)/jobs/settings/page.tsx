"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Button, Card, Field, Input, Loading, Notice, PageHeader, Select, Textarea } from "@/components/ui";
import { api, useApi, type GmailStatus, type JobSettings } from "@/lib/api";

const MODELS = [
  { value: "gemini-3.5-flash", label: "Gemini 3.5 Flash (free tier)" },
  { value: "gemini-flash-lite-latest", label: "Gemini Flash Lite (free tier, fastest)" },
  { value: "gemini-pro-latest", label: "Gemini Pro" },
  { value: "claude-sonnet-5-5", label: "Claude Sonnet 5.5" },
  { value: "claude-opus-5-5", label: "Claude Opus 5.5 (best writing)" },
  { value: "claude-haiku-4-5", label: "Claude Haiku 4.5 (cheapest Claude)" },
];

function Gmail() {
  const params = useSearchParams();
  const { data, error, loading, fetching, reload } = useApi<GmailStatus>("/jobs/gmail");
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

  async function disconnect() {
    if (!confirm("Disconnect Gmail? Applications cannot be sent until you connect again.")) return;
    setBusy("disconnect");
    setActionError("");
    try {
      await api("/jobs/gmail/disconnect", { method: "POST" });
      reload();
    } catch (e) {
      setActionError((e as Error).message);
    }
    setBusy("");
  }

  return (
    <Card title="Gmail connection">
      {result === "connected" && <Notice tone="green">Gmail connected.</Notice>}
      {result === "error" && <Notice>Gmail was not connected: {params.get("message") || "unknown error"}</Notice>}
      <Notice>{error || actionError}</Notice>
      {loading || !data ? (
        <p className="text-sm text-stone-500">Checking…</p>
      ) : data.connected ? (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 text-sm">
              <span className="h-2 w-2 rounded-full bg-emerald-500" aria-hidden="true" />
              <span className="font-medium text-stone-900">{data.email}</span>
            </div>
            {data.connected_at && <p className="mt-1 text-xs text-stone-500">Connected {new Date(data.connected_at).toLocaleString()}</p>}
          </div>
          <Button variant="danger" loading={busy === "disconnect"} disabled={Boolean(busy) || fetching} onClick={disconnect}>
            Disconnect
          </Button>
        </div>
      ) : (
        <>
          <p className="text-sm text-stone-600">
            Applications are sent through the Gmail API from your own account. Worklane asks for permission to send email and to read the threads it
            starts, so it can see replies. Your password is never seen or stored.
          </p>
          {!data.configured && (
            <Notice tone="amber">
              The server has no Google OAuth client yet. Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET and GOOGLE_REDIRECT_URI on the backend first.
            </Notice>
          )}
          <Button className="mt-3" variant="dark" loading={busy === "connect"} disabled={Boolean(busy) || !data.configured} onClick={connect}>
            {busy === "connect" ? "Opening Google…" : "Connect Gmail"}
          </Button>
        </>
      )}
    </Card>
  );
}

function SettingsForm({ initial }: { initial: JobSettings }) {
  const [s, setS] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "red" | "green"; text: string } | null>(null);
  const update = (patch: Partial<JobSettings>) => setS((current) => ({ ...current, ...patch }));
  const num = (key: keyof JobSettings, props: { min?: number; max?: number } = {}) => (
    <Input type="number" {...props} value={String(s[key])} onChange={(e) => update({ [key]: Number(e.target.value) } as Partial<JobSettings>)} />
  );

  async function save() {
    setBusy(true);
    setMessage(null);
    try {
      setS(await api<JobSettings>("/jobs/settings", { method: "PUT", body: s }));
      setMessage({ tone: "green", text: "Settings saved." });
    } catch (e) {
      setMessage({ tone: "red", text: (e as Error).message });
    }
    setBusy(false);
  }

  return (
    <>
      <Card title="Sender">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Your name" hint="Shown as the sender, e.g. Adnan Amin">
            <Input value={s.sender_name} maxLength={120} onChange={(e) => update({ sender_name: e.target.value })} />
          </Field>
          <Field label="Writing model">
            <Select value={s.model} onChange={(e) => update({ model: e.target.value })}>
              {MODELS.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </Select>
          </Field>
          <div className="sm:col-span-2">
            <Field label="Signature" hint="Added under every email. Name, role, phone, LinkedIn, portfolio.">
              <Textarea rows={4} value={s.signature} maxLength={1000} onChange={(e) => update({ signature: e.target.value })} />
            </Field>
          </div>
        </div>
      </Card>

      <Card title="Safety limits">
        <p className="mb-4 text-sm text-stone-500">These keep your personal Gmail looking like a person, not a mailing list.</p>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Emails per day" hint="Resets at 00:00 UTC. 20 is a safe ceiling.">
            {num("daily_send_limit", { min: 1, max: 100 })}
          </Field>
          <Field label="Duplicate warning (days)" hint="Warn before writing to the same address or company again. 0 turns it off.">
            {num("duplicate_window_days", { min: 0, max: 365 })}
          </Field>
          <Field label="Minimum characters">{num("email_min_chars", { min: 50 })}</Field>
          <Field label="Maximum characters">{num("email_max_chars", { min: 300, max: 10000 })}</Field>
        </div>
      </Card>

      <div className="sticky bottom-0 -mx-4 flex items-center gap-3 border-t border-stone-300/70 bg-canvas/95 px-4 py-3 md:-mx-8 md:px-8">
        <Button variant="primary" loading={busy} onClick={save}>
          {busy ? "Saving…" : "Save settings"}
        </Button>
        {message && <span className={`text-sm ${message.tone === "red" ? "text-red-700" : "text-emerald-700"}`}>{message.text}</span>}
      </div>
    </>
  );
}

export default function JobSettingsPage() {
  const { data, error, loading } = useApi<JobSettings>("/jobs/settings");
  return (
    <>
      <PageHeader title="Jobs settings" subtitle="Where applications are sent from, how they are signed, and the limits that protect your account." />
      <div className="space-y-6">
        {/* useSearchParams needs a Suspense boundary so the page can still be prerendered. */}
        <Suspense fallback={<Loading />}>
          <Gmail />
        </Suspense>
        <Notice>{error}</Notice>
        {loading && <Loading label="Loading settings…" />}
        {data && <SettingsForm initial={data} />}
      </div>
    </>
  );
}
