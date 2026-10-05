"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Button, Field, Input, Notice } from "@/components/ui";
import { api, setToken } from "@/lib/api";

const LANES = [
  { tag: "FL", title: "Freelance", text: "Finds matching Freelancer.com projects and bids with your proposal prompt." },
  { tag: "JB", title: "Jobs", text: "Turns a job description into a tailored application sent from your Gmail." },
];

export default function LoginPage() {
  const router = useRouter();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    // Read the fields from the form itself, so values filled in by the browser's password manager are always used.
    const form = new FormData(e.currentTarget);
    const email = String(form.get("email") ?? "");
    const password = String(form.get("password") ?? "");
    setBusy(true);
    setError("");
    try {
      const { token } = await api<{ token: string }>("/auth/login", { method: "POST", body: { email, password } });
      setToken(token);
      router.replace("/");
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-[1.1fr_1fr]">
      <section className="grid-texture relative hidden flex-col justify-between overflow-hidden bg-graphite-900 p-12 text-graphite-300 lg:flex">
        <div className="flex items-center gap-2.5">
          <span className="grid h-8 w-8 place-items-center rounded-[5px] bg-brand-500 text-graphite-950">
            <svg viewBox="0 0 16 16" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="square" aria-hidden="true">
              <path d="M2 4h12M2 8h8M2 12h12" />
            </svg>
          </span>
          <span className="text-lg font-semibold tracking-tight text-white">Worklane</span>
        </div>

        <div className="max-w-md">
          <p className="font-mono text-[11px] uppercase tracking-[0.2em] text-brand-400">Operations console</p>
          <h1 className="mt-4 text-[40px] font-semibold leading-[1.05] tracking-[-0.03em] text-white">
            Every opportunity,
            <br />
            worked on its own lane.
          </h1>
          <ul className="mt-10 space-y-5">
            {LANES.map((lane) => (
              <li key={lane.tag} className="flex gap-4">
                <span className="mt-0.5 h-fit rounded-[3px] border border-graphite-700 px-1.5 py-0.5 font-mono text-[10px] text-graphite-400">
                  {lane.tag}
                </span>
                <div>
                  <div className="font-medium text-white">{lane.title}</div>
                  <p className="mt-1 text-sm leading-relaxed text-graphite-400">{lane.text}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>

        <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-graphite-500">Private workspace · single operator</p>
        <div aria-hidden="true" className="pointer-events-none absolute -bottom-40 -right-40 h-96 w-96 rounded-full bg-brand-500/10 blur-3xl" />
      </section>

      <section className="flex items-center justify-center px-5 py-16">
        <form onSubmit={submit} className="animate-rise w-full max-w-sm">
          <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-stone-500 lg:hidden">Worklane</p>
          <h2 className="mt-2 text-2xl font-semibold tracking-[-0.02em] text-stone-900">Sign in</h2>
          <p className="mb-7 mt-1.5 text-sm text-stone-500">Use the operator account configured on the server.</p>
          <Notice>{error}</Notice>
          <div className="space-y-4">
            <Field label="Email">
              <Input type="email" name="email" id="email" autoComplete="username" required />
            </Field>
            <Field label="Password">
              <Input type="password" name="password" id="password" autoComplete="current-password" required />
            </Field>
            <Button type="submit" variant="dark" className="w-full py-2.5" loading={busy}>
              {busy ? "Signing in…" : "Sign in"}
            </Button>
          </div>
        </form>
      </section>
    </div>
  );
}
