"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Button, Field, Input, Notice } from "@/components/ui";
import { api, setToken } from "@/lib/api";

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
    <div className="flex min-h-screen items-center justify-center px-4">
      <form onSubmit={submit} className="w-full max-w-sm rounded-lg border border-zinc-200 bg-white p-6">
        <h1 className="mb-1 text-xl font-semibold text-indigo-700">EasyBid</h1>
        <p className="mb-5 text-sm text-zinc-500">Sign in to your dashboard</p>
        <Notice>{error}</Notice>
        <div className="space-y-4">
          <Field label="Email">
            <Input type="email" name="email" id="email" autoComplete="username" required />
          </Field>
          <Field label="Password">
            <Input
              type="password"
              name="password"
              id="password"
              autoComplete="current-password"
              required
            />
          </Field>
          <Button type="submit" variant="primary" className="w-full" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </Button>
        </div>
      </form>
    </div>
  );
}
