"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import { useToast } from "@/components/overlay";
import { Button, Field, Input } from "@/components/ui";
import { apiRequest } from "@/lib/api";
import { setToken } from "@/lib/auth-store";
import type { TokenResponse } from "@/lib/types";

export default function LoginPage() {
  const router = useRouter();
  const toast = useToast();
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim() || !password) {
      setError("Enter your email and password.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await apiRequest<TokenResponse>("/auth/login", {
        method: "POST",
        body: { email: email.trim(), password },
      });
      setToken(res.access_token);
      router.replace("/overview");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Sign-in failed.";
      setError(msg);
      toast.push("error", msg);
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <h1 className="t-page text-[20px]">Sign in</h1>
      <p className="t-meta mt-1">Welcome back to your finance workspace.</p>
      <form onSubmit={submit} className="mt-5 flex flex-col gap-4" noValidate>
        <Field label="Email" error={error && !email.trim() ? "Email is required." : undefined}>
          <Input
            type="email"
            autoComplete="email"
            placeholder="you@company.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </Field>
        <Field label="Password">
          <Input
            type="password"
            autoComplete="current-password"
            placeholder="••••••••"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </Field>
        {error ? (
          <p role="alert" className="rounded-[var(--radius-md)] bg-[var(--negative-wash)] px-3 py-2 text-[13.5px] font-medium text-[var(--negative)]">
            {error}
          </p>
        ) : null}
        <Button type="submit" disabled={loading}>
          {loading ? "Signing in…" : "Sign in"}
        </Button>
      </form>
      <p className="t-meta mt-4 text-center">
        New here?{" "}
        <Link href="/register" className="font-semibold text-[var(--accent-deep)] hover:underline">
          Create an account
        </Link>
      </p>
    </>
  );
}
