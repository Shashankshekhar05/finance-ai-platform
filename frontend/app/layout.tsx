import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "LedgerLens — Finance Intelligence",
  description: "Evidence-grounded financial intelligence for your company.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
