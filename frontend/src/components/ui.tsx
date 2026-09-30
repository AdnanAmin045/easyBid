"use client";

import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";

const control =
  "w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 disabled:bg-zinc-100";

const variants = {
  primary: "bg-indigo-600 text-white hover:bg-indigo-700",
  secondary: "border border-zinc-300 bg-white text-zinc-800 hover:bg-zinc-50",
  danger: "border border-red-200 bg-white text-red-700 hover:bg-red-50",
};

export function Spinner({ className = "h-4 w-4" }: { className?: string }) {
  return (
    <svg className={`shrink-0 animate-spin ${className}`} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" className="opacity-25" />
      <path fill="currentColor" className="opacity-75" d="M4 12a8 8 0 0 1 8-8V0C5.4 0 0 5.4 0 12h4z" />
    </svg>
  );
}

/** Shown in place of content that has not loaded yet. */
export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center justify-center gap-2 py-16 text-sm text-zinc-500">
      <Spinner className="h-5 w-5" />
      {label}
    </div>
  );
}

/** `loading` shows a spinner and blocks the button, so the action cannot be fired twice. */
export function Button({
  variant = "secondary",
  className = "",
  loading = false,
  disabled,
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: keyof typeof variants; loading?: boolean }) {
  return (
    <button
      type="button"
      {...props}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={`inline-flex items-center justify-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50 ${variants[variant]} ${className}`}
    >
      {loading && <Spinner />}
      {children}
    </button>
  );
}

export const Input = (props: InputHTMLAttributes<HTMLInputElement>) => (
  <input {...props} className={`${control} ${props.className ?? ""}`} />
);

export const Textarea = (props: TextareaHTMLAttributes<HTMLTextAreaElement>) => (
  <textarea {...props} className={`${control} leading-relaxed ${props.className ?? ""}`} />
);

export const Select = (props: SelectHTMLAttributes<HTMLSelectElement>) => (
  <select {...props} className={`${control} ${props.className ?? ""}`} />
);

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium text-zinc-700">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-zinc-500">{hint}</span>}
    </label>
  );
}

export function Card({ title, action, children, className = "" }: { title?: string; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-lg border border-zinc-200 bg-white p-5 ${className}`}>
      {(title || action) && (
        <div className="mb-4 flex items-center justify-between gap-3">
          <h2 className="text-sm font-semibold text-zinc-900">{title}</h2>
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

const tones: Record<string, string> = {
  green: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  red: "bg-red-50 text-red-700 ring-red-200",
  amber: "bg-amber-50 text-amber-800 ring-amber-200",
  blue: "bg-indigo-50 text-indigo-700 ring-indigo-200",
  gray: "bg-zinc-100 text-zinc-600 ring-zinc-200",
};

const statusTone: Record<string, string> = {
  sent: "green",
  awarded: "green",
  active: "blue",
  proposed: "blue",
  pending: "amber",
  sending: "amber",
  new: "gray",
  processing: "gray",
  filtered: "gray",
  skipped: "gray",
  rejected: "gray",
  retracted: "gray",
  failed: "red",
  error: "red",
};

export function Badge({ children, tone }: { children: string; tone?: keyof typeof tones }) {
  const color = tones[tone ?? statusTone[children] ?? "gray"];
  return <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${color}`}>{children}</span>;
}

export function PageHeader({ title, subtitle, action }: { title: string; subtitle?: string; action?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold text-zinc-900">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-zinc-500">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}

export function Notice({ tone = "red", children }: { tone?: "red" | "amber" | "green"; children: ReactNode }) {
  if (!children) return null;
  return <div className={`mb-4 rounded-md px-3 py-2 text-sm ring-1 ring-inset ${tones[tone]}`}>{children}</div>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="rounded-lg border border-dashed border-zinc-300 p-8 text-center text-sm text-zinc-500">{children}</p>;
}
