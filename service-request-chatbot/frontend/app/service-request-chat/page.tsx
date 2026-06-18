"use client";

import { useState, useEffect } from "react";
import { ServiceRequestChat } from "@/components/chatbot/ServiceRequestChat";
import { RoleSelector } from "@/components/chatbot/RoleSelector";
import type { UserRole } from "@/lib/types/chat";

const ROLE_STORAGE_KEY = "sr_chat_user_role";

export default function ServiceRequestChatPage() {
  const [userRole, setUserRole] = useState<UserRole | null>(null);
  const [hydrated, setHydrated] = useState(false);

  // Read persisted role from localStorage on mount (client-only)
  useEffect(() => {
    const stored = localStorage.getItem(ROLE_STORAGE_KEY) as UserRole | null;
    if (stored) {
      setUserRole(stored);
    }
    setHydrated(true);
  }, []);

  function handleSelectRole(role: UserRole) {
    localStorage.setItem(ROLE_STORAGE_KEY, role);
    setUserRole(role);
  }

  function handleClearRole() {
    localStorage.removeItem(ROLE_STORAGE_KEY);
    setUserRole(null);
  }

  // Avoid rendering until localStorage has been read to prevent hydration mismatch
  if (!hydrated) {
    return null;
  }

  if (!userRole) {
    return (
      <main className="container mx-auto max-w-4xl px-4 py-8">
        <RoleSelector onSelect={handleSelectRole} />
      </main>
    );
  }

  return (
    <main className="container mx-auto max-w-6xl px-4 py-8">
      <ServiceRequestChat userRole={userRole} onClearRole={handleClearRole} />
    </main>
  );
}
