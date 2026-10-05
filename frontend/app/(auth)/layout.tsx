import { ToastProvider } from "@/components/overlay";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <ToastProvider>
      <main className="flex min-h-screen items-center justify-center px-4 py-10">
        <div className="w-full max-w-md">
          <div className="mb-6 text-center">
            <p className="t-app text-[20px]">LedgerLens</p>
            <p className="t-meta mt-1">Evidence-grounded finance intelligence</p>
          </div>
          <div className="rounded-[var(--radius-lg)] border border-[var(--line)] bg-[var(--surface)] p-6 shadow-[var(--shadow-card)]">
            {children}
          </div>
        </div>
      </main>
    </ToastProvider>
  );
}
