import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Service Request Chatbot",
  description: "POC foundation for production service request automation",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-zinc-50 text-zinc-900 dark:bg-zinc-950 dark:text-zinc-100">
        <header className="border-b border-zinc-200 bg-white/80 backdrop-blur dark:border-zinc-800 dark:bg-zinc-900/80">
          <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
            <Link href="/service-request-chat" className="font-semibold">
              Service Request Chat
            </Link>
            <nav className="flex gap-4 text-sm text-zinc-600 dark:text-zinc-400">
              <Link href="/admin/agent-observability">Observability</Link>
            </nav>
          </div>
        </header>
        <main className="mx-auto max-w-5xl px-4 py-6">{children}</main>
      </body>
    </html>
  );
}
