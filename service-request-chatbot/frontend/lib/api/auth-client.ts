const AUTH_TOKEN_KEY = "cenomi_access_token";
const AUTH_USER_KEY = "cenomi_user";

export interface LoginResponse {
  access_token: string;
  token_type: string;
  user_id: string;
  role: string;
  mall_names: string[];
  expires_in: number;
}

export interface CurrentUser {
  userId: string;
  role: string;
  mallNames: string[];
  accessToken: string;
}

function apiBase(): string {
  const base = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
  return `${base.replace(/\/$/, "")}/api`;
}

export async function login(username: string, password: string): Promise<CurrentUser> {
  const res = await fetch(`${apiBase()}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Login failed");
  }

  const data: LoginResponse = await res.json();
  const user: CurrentUser = {
    userId: data.user_id,
    role: data.role,
    mallNames: data.mall_names,
    accessToken: data.access_token,
  };

  if (typeof window !== "undefined") {
    localStorage.setItem(AUTH_TOKEN_KEY, data.access_token);
    localStorage.setItem(AUTH_USER_KEY, JSON.stringify(user));
  }
  return user;
}

export function logout(): void {
  if (typeof window !== "undefined") {
    localStorage.removeItem(AUTH_TOKEN_KEY);
    localStorage.removeItem(AUTH_USER_KEY);
  }
}

export function getStoredToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(AUTH_TOKEN_KEY);
}

export function getStoredUser(): CurrentUser | null {
  if (typeof window === "undefined") return null;
  const raw = localStorage.getItem(AUTH_USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as CurrentUser;
  } catch {
    return null;
  }
}

export function isAuthenticated(): boolean {
  return getStoredToken() !== null;
}

/** Role display labels */
export const ROLE_LABELS: Record<string, string> = {
  MALL_MANAGER: "Mall Manager",
  FM_MANAGER: "FM Manager",
  OPERATIONS: "Operations",
  DD_ENGINEER: "DD Engineer",
  ADMIN: "Admin",
};
