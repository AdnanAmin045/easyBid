"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useSyncExternalStore, type ReactNode } from "react";
import { Loading } from "@/components/ui";
import { clearToken, getToken } from "@/lib/api";

const NAV = [
  { href: "/", label: "Dashboard" },
  { href: "/queue", label: "Queue" },
  { href: "/projects", label: "Projects" },
  { href: "/bids", label: "Bids" },
  { href: "/prompts", label: "Prompts" },
  { href: "/profile", label: "Profile" },
  { href: "/settings", label: "Settings" },
  { href: "/logs", label: "Logs" },
];

const noopSubscribe = () => () => {};

export default function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  // null on the server and during hydration, then the real value.
  const signedIn = useSyncExternalStore(noopSubscribe, () => Boolean(getToken()), () => null);

  useEffect(() => {
    if (signedIn === false) router.replace("/login");
  }, [signedIn, router]);

  // Session not read yet, or on the way to the login page.
  if (!signedIn) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Loading />
      </div>
    );
  }

  return (
    <div className="mx-auto flex min-h-screen max-w-7xl flex-col md:flex-row">
      <aside className="border-b border-zinc-200 bg-white px-4 py-3 md:w-52 md:shrink-0 md:border-b-0 md:border-r md:py-6">
        <div className="mb-3 text-lg font-semibold text-indigo-700 md:mb-6 md:px-2">EasyBid</div>
        <nav className="flex gap-1 overflow-x-auto md:flex-col">
          {NAV.map((item) => {
            const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`whitespace-nowrap rounded-md px-3 py-2 text-sm font-medium ${
                  active ? "bg-indigo-50 text-indigo-700" : "text-zinc-600 hover:bg-zinc-100"
                }`}
              >
                {item.label}
              </Link>
            );
          })}
          <button
            type="button"
            onClick={() => {
              clearToken();
              router.replace("/login");
            }}
            className="whitespace-nowrap rounded-md px-3 py-2 text-left text-sm font-medium text-zinc-500 hover:bg-zinc-100 md:mt-4"
          >
            Sign out
          </button>
        </nav>
      </aside>
      <main className="min-w-0 flex-1 px-4 py-6 md:px-8">{children}</main>
    </div>
  );
}
