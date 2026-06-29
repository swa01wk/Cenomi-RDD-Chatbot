"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { login, ROLE_LABELS } from "@/lib/api/auth-client";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const user = await login(username, password);
      const roleLabel = ROLE_LABELS[user.role] ?? user.role;
      console.info(`Logged in as ${roleLabel} (${user.userId})`);
      router.push("/service-request-chat");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        {/* Logo / Brand */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-blue-600 mb-4">
            <span className="text-white text-2xl font-bold">C</span>
          </div>
          <h1 className="text-2xl font-semibold text-gray-900">Cenomi Platform</h1>
          <p className="text-sm text-gray-500 mt-1">Sign in to continue</p>
        </div>

        {/* Card */}
        <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-8">
          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label
                htmlFor="username"
                className="block text-sm font-medium text-gray-700 mb-1.5"
              >
                Username
              </label>
              <input
                id="username"
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                autoComplete="username"
                placeholder="aisha@cenomi.com"
                className="w-full px-3.5 py-2.5 rounded-lg border border-gray-300 text-sm
                           focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent
                           placeholder:text-gray-400"
              />
            </div>

            <div>
              <label
                htmlFor="password"
                className="block text-sm font-medium text-gray-700 mb-1.5"
              >
                Password
              </label>
              <input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                autoComplete="current-password"
                placeholder="••••••••"
                className="w-full px-3.5 py-2.5 rounded-lg border border-gray-300 text-sm
                           focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent
                           placeholder:text-gray-400"
              />
            </div>

            {error && (
              <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full py-2.5 px-4 bg-blue-600 hover:bg-blue-700 disabled:opacity-60
                         text-white text-sm font-medium rounded-lg transition-colors
                         focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
            >
              {loading ? "Signing in…" : "Sign in"}
            </button>
          </form>
        </div>

        {/* Test accounts hint */}
        <div className="mt-6 bg-white rounded-xl border border-gray-200 p-4">
          <p className="text-xs font-medium text-gray-500 mb-3 uppercase tracking-wide">
            Test accounts (password: test1234)
          </p>
          <div className="space-y-1.5">
            {[
              { email: "aisha@cenomi.com", role: "Mall Manager" },
              { email: "khalid@cenomi.com", role: "FM Manager" },
              { email: "omar@cenomi.com", role: "Operations" },
              { email: "sara@cenomi.com", role: "DD Engineer" },
              { email: "admin@cenomi.com", role: "Admin" },
            ].map(({ email, role }) => (
              <button
                key={email}
                type="button"
                onClick={() => {
                  setUsername(email);
                  setPassword("test1234");
                }}
                className="w-full flex items-center justify-between px-3 py-1.5 rounded-md
                           hover:bg-gray-50 transition-colors text-left group"
              >
                <span className="text-xs text-gray-600 group-hover:text-gray-900">{email}</span>
                <span className="text-xs font-medium text-blue-600 bg-blue-50 px-2 py-0.5 rounded-full">
                  {role}
                </span>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
