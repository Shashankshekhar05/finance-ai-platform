"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getToken } from "@/lib/auth-store";

/** Root: route to the app or to login based on stored session. */
export default function RootPage() {
  const router = useRouter();
  useEffect(() => {
    router.replace(getToken() ? "/overview" : "/login");
  }, [router]);
  return (
    <main className="flex min-h-screen items-center justify-center">
      <p className="t-meta" role="status">Loading…</p>
    </main>
  );
}
