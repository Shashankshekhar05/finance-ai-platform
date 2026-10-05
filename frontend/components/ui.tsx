"use client";

import * as React from "react";

type Variant = "primary" | "secondary" | "danger" | "ghost";
type Size = "sm" | "md";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-[var(--accent)] text-[var(--accent-ink)] hover:bg-[var(--accent-deep)]",
  secondary:
    "bg-[var(--surface)] text-[var(--ink)] border border-[var(--line)] hover:border-[var(--faint)] hover:bg-[var(--surface-warm)]",
  danger: "bg-[var(--negative)] text-white hover:brightness-95",
  ghost: "text-[var(--muted)] hover:text-[var(--ink)] hover:bg-[var(--surface-warm)]",
};

const SIZES: Record<Size, string> = {
  sm: "h-8 px-3 text-[13px]",
  md: "h-10 px-4 text-[14px]",
};

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
}

export function Button({ variant = "primary", size = "md", className = "", ...rest }: ButtonProps) {
  return (
    <button
      className={`inline-flex items-center justify-center gap-2 rounded-[var(--radius-md)] font-semibold transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-50 ${VARIANTS[variant]} ${SIZES[size]} ${className}`}
      {...rest}
    />
  );
}

export function Input({ className = "", ...rest }: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={`h-10 w-full rounded-[var(--radius-md)] border border-[var(--line)] bg-[var(--surface)] px-3 text-[14px] text-[var(--ink)] placeholder:text-[var(--faint)] transition-colors focus:border-[var(--accent)] focus:outline-none ${className}`}
      {...rest}
    />
  );
}

export function Textarea({ className = "", ...rest }: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={`w-full rounded-[var(--radius-md)] border border-[var(--line)] bg-[var(--surface)] px-3 py-2.5 text-[14px] text-[var(--ink)] placeholder:text-[var(--faint)] transition-colors focus:border-[var(--accent)] focus:outline-none ${className}`}
      {...rest}
    />
  );
}

export function Select({ className = "", children, ...rest }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={`h-10 rounded-[var(--radius-md)] border border-[var(--line)] bg-[var(--surface)] px-2.5 text-[14px] text-[var(--ink)] transition-colors focus:border-[var(--accent)] focus:outline-none ${className}`}
      {...rest}
    >
      {children}
    </select>
  );
}

export function Field({
  label,
  error,
  hint,
  children,
}: {
  label: string;
  error?: string;
  hint?: string;
  children: React.ReactNode;
}) {
  const id = React.useId();
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="t-label">
        {label}
      </label>
      {React.isValidElement(children)
        ? React.cloneElement(children as React.ReactElement<{ id?: string }>, { id })
        : children}
      {error ? (
        <p role="alert" className="text-[12.5px] font-medium text-[var(--negative)]">
          {error}
        </p>
      ) : hint ? (
        <p className="t-meta">{hint}</p>
      ) : null}
    </div>
  );
}
