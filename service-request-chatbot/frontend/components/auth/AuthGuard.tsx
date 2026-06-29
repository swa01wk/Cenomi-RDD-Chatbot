"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getStoredUser, logout, isAuthenticated, ROLE_LABELS } from "@/lib/api/auth-client";

interface AuthGuardProps {
  children: React.ReactNode;
}

/**
 * Wraps a page that requires authentication.
 * Redirects to /login when no JWT is stored.
 * Renders a role badge + logout button in the top-right corner.
 */
export function AuthGuard({ children }: AuthGuardProps) {
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [roleBadge, setRoleBadge] = useState<string | null>(null);

  useEffect(() => {
    if (!isAuthenticated()) {
      router.replace("/login");
      return;
    }
    const user = getStoredUser();
    if (user) {
      setRoleBadge(ROLE_LABELS[user.role] ?? user.role);
    }
    setReady(true);
  }, [router]);

  function handleLogout() {
    logout();
    router.replace("/login");
  }

  if (!ready) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="w-8 h-8 border-4 border-blue-600 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="relative">
      {/* Role badge + logout */}
      <div className="fixed top-3 right-4 z-50 flex items-center gap-2">
        {roleBadge && (
          <span className="text-xs font-medium text-blue-700 bg-blue-50 border border-blue-200 px-2.5 py-1 rounded-full">
            {roleBadge}
          </span>
        )}
        <button
          onClick={handleLogout}
          className="text-xs text-gray-500 hover:text-gray-800 bg-white border border-gray-200
                     px-2.5 py-1 rounded-full transition-colors hover:bg-gray-50"
        >
          Sign out
        </button>
      </div>
      {children}
    </div>
  );
}
