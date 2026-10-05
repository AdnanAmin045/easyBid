"use client";

import Link from "next/link";
import { useState } from "react";
import { Badge, Button, Card, Loading, Notice, PageHeader, Spinner, Stat } from "@/components/ui";
import { api, timeAgo, useApi, type Mode, type Settings, type Stats } from "@/lib/api";

const MODES: { value: Mode; label: string; hint: string }[] = [
  { value: "manual", label: "Manual", hint: "Every proposal waits for your approval." },
  { value: "semi", label: "Semi-auto", hint: "High-scoring projects are bid on automatically." },
  { value: "auto", label: "Auto", hint: "Every selected project is bid on automatically." },
];

function Fact({ label, value }: { label: string; value: string | number }) {
  return (
    <div>
      <div className="text-xs font-medium uppercase tracking-wide text-stone-500">{label}</div>
      <div className="mt-1 font-medium text-stone-900">{value}</div>
    </div>
  );
}

export default function DashboardPage() {
  const { data: stats, error, fetching, reload } = useApi<Stats>("/stats");
  // Which action is being saved: "run", "pause", "resume" or "mode".
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState<{ tone: "red" | "green"; text: string } | null>(null);

  async function act(name: string, fn: () => Promise<string | void>) {
    setBusy(name);
    setMessage(null);
    try {
      const text = await fn();
      if (text) setMessage({ tone: "green", text });
    } catch (e) {
      setMessage({ tone: "red", text: (e as Error).message });
    }
    setBusy("");
    reload();
  }

  async function updateSettings(patch: Partial<Settings>) {
    const current = await api<Settings>("/settings");
    await api("/settings", { method: "PUT", body: { ...current, ...patch } });
  }

  const runNow = () =>
    act("run", async () => {
      const summary = await api<Record<string, string | number>>("/run", { method: "POST" });
      return `Run finished: ${Object.entries(summary).map(([k, v]) => `${k} ${v}`).join(", ")}`;
    });

  if (error) return <Notice>{error}</Notice>;
  if (!stats) return <Loading label="Loading dashboard…" />;
  // Controls stay locked until the dashboard shows the result of the last action.
  const working = Boolean(busy) || fetching;

  const setup = [
    { done: stats.skills_selected > 0, text: "Choose the skills to watch", href: "/settings" },
    { done: stats.proposal_prompt_active, text: "Save a proposal prompt", href: "/prompts" },
    { done: !stats.ai_problem, text: `Backend: ${stats.ai_problem}`, href: null },
  ].filter((step) => !step.done);
  const p24 = stats.projects_24h;
  const seen = Object.values(p24).reduce((a, b) => a + b, 0);

  return (
    <>
      <PageHeader
        title="Freelance overview"
        subtitle={`Last run: ${timeAgo(stats.last_cycle)}`}
        action={
          <div className="flex gap-2">
            <Button onClick={runNow} loading={busy === "run"} disabled={working || stats.paused}>
              {busy === "run" ? "Running…" : "Run now"}
            </Button>
            {stats.paused ? (
              <Button
                variant="primary"
                loading={busy === "resume"}
                disabled={working}
                onClick={() => act("resume", () => updateSettings({ paused: false }))}
              >
                {busy === "resume" ? "Resuming…" : "Resume"}
              </Button>
            ) : (
              <Button
                variant="danger"
                loading={busy === "pause"}
                disabled={working}
                onClick={() => act("pause", () => updateSettings({ paused: true }))}
              >
                {busy === "pause" ? "Pausing…" : "Pause everything"}
              </Button>
            )}
          </div>
        }
      />

      {message && <Notice tone={message.tone}>{message.text}</Notice>}
      {stats.paused && <Notice tone="amber">Bidding is paused. No projects are fetched and no bids are sent.</Notice>}

      {setup.length > 0 && (
        <Card title="Finish setup" className="mb-6">
          <ul className="space-y-2 text-sm">
            {setup.map((step) => (
              <li key={step.text}>
                {step.href ? (
                  <Link href={step.href} className="text-brand-700 hover:underline">
                    {step.text}
                  </Link>
                ) : (
                  <span className="text-stone-700">{step.text}</span>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}

      <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Link href="/queue" className="block transition hover:-translate-y-px">
          <Stat label="Waiting for approval" value={stats.proposals.pending ?? 0} />
        </Link>
        <Link href="/bids" className="block transition hover:-translate-y-px">
          <Stat label="Bids sent today" value={`${stats.sent_today} / ${stats.daily_bid_cap}`} />
        </Link>
        <Link href="/projects" className="block transition hover:-translate-y-px">
          <Stat label="Projects seen (24h)" value={seen} />
        </Link>
        <Link href="/bids" className="block transition hover:-translate-y-px">
          <Stat label="Awarded" value={stats.awarded} />
        </Link>
      </div>

      {!stats.scheduler_running && (
        <Notice>
          Automatic checking has not reported in for three minutes, so new projects are only checked when you press Run now. It normally
          starts by itself within a few minutes of the backend waking up; on a free Render plan the backend sleeps when nobody uses it.
        </Notice>
      )}
      {stats.account_problem && <Notice>Bidding is blocked: {stats.account_problem}.</Notice>}
      {stats.waiting && !stats.paused && <Notice>No new projects are taken right now: {stats.waiting}. Bidding carries on by itself.</Notice>}

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title={`Freelancer account${stats.account.username ? `: ${stats.account.username}` : ""}`} className="lg:col-span-2">
          {stats.account.username ? (
            <>
              <div className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
                <Fact label="Bids left" value={stats.account.bids_remaining ?? "unknown"} />
                <Fact label="Balance" value={stats.account.balance_usd != null ? `$${stats.account.balance_usd.toFixed(2)}` : "unknown"} />
                <Fact label="Membership" value={stats.account.membership ?? "unknown"} />
                <Fact
                  label="Badges"
                  value={
                    [
                      stats.account.identity_verified && "identity verified",
                      stats.account.payment_verified && "payment verified",
                      stats.account.freelancer_verified && "Freelancer Verified",
                      stats.account.preferred_freelancer && "Preferred Freelancer",
                    ]
                      .filter(Boolean)
                      .join(", ") || "none"
                  }
                />
              </div>
              <p className="mt-4 text-sm text-stone-500">
                Projects this account cannot bid on are dropped before any AI is used.
              </p>
            </>
          ) : (
            <p className="text-sm text-stone-500">Checked on the first run.</p>
          )}
        </Card>

        <Card
          title="Bidding mode"
          action={
            busy === "mode" && (
              <span role="status" className="inline-flex items-center gap-2 text-xs text-stone-500">
                <Spinner /> Saving…
              </span>
            )
          }
        >
          <div className="space-y-2">
            {MODES.map((mode) => (
              <label
                key={mode.value}
                className={`flex cursor-pointer items-start gap-3 rounded-md border p-3 ${
                  stats.mode === mode.value ? "border-brand-400 bg-brand-50" : "border-stone-200"
                }`}
              >
                <input
                  type="radio"
                  name="mode"
                  className="mt-1"
                  checked={stats.mode === mode.value}
                  disabled={working}
                  onChange={() => act("mode", () => updateSettings({ mode: mode.value }))}
                />
                <span>
                  <span className="block text-sm font-medium text-stone-900">{mode.label}</span>
                  <span className="block text-xs text-stone-500">{mode.hint}</span>
                </span>
              </label>
            ))}
          </div>
        </Card>

        <Card title="Last 24 hours">
          {seen === 0 ? (
            <p className="text-sm text-stone-500">No projects fetched yet.</p>
          ) : (
            <ul className="space-y-2 text-sm">
              {Object.entries(p24).map(([status, count]) => (
                <li key={status} className="flex items-center justify-between">
                  <Badge>{status}</Badge>
                  <span className="font-medium text-stone-800">{count}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Proposal prompt results" className="lg:col-span-2">
          {stats.prompts.length === 0 ? (
            <p className="text-sm text-stone-500">Appears once bids have been sent.</p>
          ) : (
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase text-stone-500">
                <tr>
                  <th className="pb-2">Version</th>
                  <th className="pb-2">Bids sent</th>
                  <th className="pb-2">Awarded</th>
                  <th className="pb-2">Win rate</th>
                </tr>
              </thead>
              <tbody>
                {stats.prompts.map((row) => (
                  <tr key={row.version} className="border-t border-stone-100">
                    <td className="py-2">
                      v{row.version} {row.is_active && <Badge tone="blue">active</Badge>}
                    </td>
                    <td>{row.sent}</td>
                    <td>{row.awarded}</td>
                    <td>{((row.awarded / row.sent) * 100).toFixed(1)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>
    </>
  );
}
