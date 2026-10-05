"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import { useToast } from "@/components/overlay";
import { Button, Field, Input } from "@/components/ui";
import { apiRequest } from "@/lib/api";
import { setToken } from "@/lib/auth-store";
import type { TokenResponse, UserRead } from "@/lib/types";

export default function RegisterPage() {
  const router = useRouter();
  const toast = useToast();
  const [fullName, setFullName] = React.useState("");
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!fullName.trim() || !email.trim() || password.length < 8) {
      setError("Enter your name, a valid email, and a password of at least 8 characters.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await apiRequest<UserRead>("/auth/register", {
        method: "POST",
        body: { email: email.trim(), password, full_name: fullName.trim() },
      });
      const token = await apiRequest<TokenResponse>("/auth/login", {
        method: "POST",
        body: { email: email.trim(), password },
      });
      setToken(token.access_token);
      router.replace("/overview");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Registration failed.";
      setError(msg);
      toast.push("error", msg);
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <h1 className="t-page text-[20px]">Create your account</h1>
      <p className="t-meta mt-1">A personal company workspace is created for you.</p>
      <form onSubmit={submit} className="mt-5 flex flex-col gap-4" noValidate>
        <Field label="Full name">
          <Input
            type="text"
            autoComplete="name"
            placeholder="Asha Sharma"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
          />
        </Field>
        <Field label="Email">
          <Input
            type="email"
            autoComplete="email"
            placeholder="you@company.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </Field>
        <Field label="Password" hint="At least 8 characters.">
          <Input
            type="password"
            autoComplete="new-password"
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
          {loading ? "Creating account…" : "Create account"}
        </Button>
      </form>
      <p className="t-meta mt-4 text-center">
        Already have an account?{" "}
        <Link href="/login" className="font-semibold text-[var(--accent-deep)] hover:underline">
          Sign in
        </Link>
      </p>
    </>
  );
}
