"use client";

import Link from "next/link";
import { useState } from "react";
import { Badge, Button, Card, Notice, PageHeader } from "@/components/ui";
import { api, timeAgo, useApi, type Mode, type Settings, type Stats } from "@/lib/api";

const MODES: { value: Mode; label: string; hint: string }[] = [
  { value: "manual", label: "Manual", hint: "Every proposal waits for your approval." },
  { value: "semi", label: "Semi-auto", hint: "High-scoring projects are bid on automatically." },
  { value: "auto", label: "Auto", hint: "Every selected project is bid on automatically." },
];

function Stat({ label, value, href }: { label: string; value: string | number; href?: string }) {
  const body = (
    <div className="rounded-lg border border-zinc-200 bg-white p-4">
      <div className="text-xs font-medium uppercase tracking-wide text-zinc-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-zinc-900">{value}</div>
    </div>
  );
  return href ? <Link href={href}>{body}</Link> : body;
}

function Fact({ label, value }: { label: string; value: string | number }) {
  return (
    <div>
      <div className="text-xs font-medium uppercase tracking-wide text-zinc-500">{label}</div>
      <div className="mt-1 font-medium text-zinc-900">{value}</div>
    </div>
  );
}

export default function DashboardPage() {
  const { data: stats, error, reload } = useApi<Stats>("/stats");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "red" | "green"; text: string } | null>(null);

  async function act(fn: () => Promise<string | void>) {
    setBusy(true);
    setMessage(null);
    try {
      const text = await fn();
      if (text) setMessage({ tone: "green", text });
    } catch (e) {
      setMessage({ tone: "red", text: (e as Error).message });
    }
    setBusy(false);
    reload();
  }

  async function updateSettings(patch: Partial<Settings>) {
    const current = await api<Settings>("/settings");
    await api("/settings", { method: "PUT", body: { ...current, ...patch } });
  }

  const runNow = () =>
    act(async () => {
      const summary = await api<Record<string, string | number>>("/run", { method: "POST" });
      return `Run finished: ${Object.entries(summary).map(([k, v]) => `${k} ${v}`).join(", ")}`;
    });

  if (error) return <Notice>{error}</Notice>;
  if (!stats) return <p className="text-sm text-zinc-500">Loading…</p>;

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
        title="Dashboard"
        subtitle={`Last run: ${timeAgo(stats.last_cycle)}`}
        action={
          <div className="flex gap-2">
            <Button onClick={runNow} disabled={busy || stats.paused}>
              Run now
            </Button>
            {stats.paused ? (
              <Button variant="primary" disabled={busy} onClick={() => act(() => updateSettings({ paused: false }))}>
                Resume
              </Button>
            ) : (
              <Button variant="danger" disabled={busy} onClick={() => act(() => updateSettings({ paused: true }))}>
                Pause everything
              </Button>
            )}
          </div>
        }
      />

      {message && <Notice tone={message.tone}>{message.text}</Notice>}
      {stats.paused && <Notice tone="amber">EasyBid is paused. No projects are fetched and no bids are sent.</Notice>}

      {setup.length > 0 && (
        <Card title="Finish setup" className="mb-6">
          <ul className="space-y-2 text-sm">
            {setup.map((step) => (
              <li key={step.text}>
                {step.href ? (
                  <Link href={step.href} className="text-indigo-700 hover:underline">
                    {step.text}
                  </Link>
                ) : (
                  <span className="text-zinc-700">{step.text}</span>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}

      <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Waiting for approval" value={stats.proposals.pending ?? 0} href="/queue" />
        <Stat label="Bids sent today" value={`${stats.sent_today} / ${stats.daily_bid_cap}`} href="/bids" />
        <Stat label="Projects seen (24h)" value={seen} href="/projects" />
        <Stat label="Awarded" value={stats.awarded} href="/bids" />
      </div>

      {stats.account_problem && <Notice>Bidding is blocked: {stats.account_problem}.</Notice>}
      {stats.waiting && !stats.paused && <Notice>No new projects are taken right now: {stats.waiting}. EasyBid carries on by itself.</Notice>}

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
              <p className="mt-4 text-sm text-zinc-500">
                Projects this account cannot bid on are dropped before any AI is used.
                {Object.entries(stats.currency_min_balance_usd).map(([currency, amount]) => (
                  <span key={currency} className="block text-zinc-700">
                    Learned from Freelancer: {currency} projects need ${amount} in your balance.
                  </span>
                ))}
              </p>
            </>
          ) : (
            <p className="text-sm text-zinc-500">Checked on the first run.</p>
          )}
        </Card>

        <Card title="Bidding mode">
          <div className="space-y-2">
            {MODES.map((mode) => (
              <label
                key={mode.value}
                className={`flex cursor-pointer items-start gap-3 rounded-md border p-3 ${
                  stats.mode === mode.value ? "border-indigo-400 bg-indigo-50" : "border-zinc-200"
                }`}
              >
                <input
                  type="radio"
                  name="mode"
                  className="mt-1"
                  checked={stats.mode === mode.value}
                  disabled={busy}
                  onChange={() => act(() => updateSettings({ mode: mode.value }))}
                />
                <span>
                  <span className="block text-sm font-medium text-zinc-900">{mode.label}</span>
                  <span className="block text-xs text-zinc-500">{mode.hint}</span>
                </span>
              </label>
            ))}
          </div>
        </Card>

        <Card title="Last 24 hours">
          {seen === 0 ? (
            <p className="text-sm text-zinc-500">No projects fetched yet.</p>
          ) : (
            <ul className="space-y-2 text-sm">
              {Object.entries(p24).map(([status, count]) => (
                <li key={status} className="flex items-center justify-between">
                  <Badge>{status}</Badge>
                  <span className="font-medium text-zinc-800">{count}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Proposal prompt results" className="lg:col-span-2">
          {stats.prompts.length === 0 ? (
            <p className="text-sm text-zinc-500">Appears once bids have been sent.</p>
          ) : (
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase text-zinc-500">
                <tr>
                  <th className="pb-2">Version</th>
                  <th className="pb-2">Bids sent</th>
                  <th className="pb-2">Awarded</th>
                  <th className="pb-2">Win rate</th>
                </tr>
              </thead>
              <tbody>
                {stats.prompts.map((row) => (
                  <tr key={row.version} className="border-t border-zinc-100">
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
