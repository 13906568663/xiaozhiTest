import { AUTH_STORAGE_KEY } from "@/lib/auth-constants";

export { AUTH_STORAGE_KEY };

export type AuthPermission = {
  id: string;
  code: string;
  resource: string;
  action: string;
  description?: string | null;
};

export type AuthRole = {
  id: string;
  code: string;
  name: string;
  description?: string | null;
  status: string;
  is_system: boolean;
};

export type AuthUser = {
  id: string;
  username: string;
  display_name: string;
  status: string;
  is_superuser: boolean;
  roles: AuthRole[];
  permissions: AuthPermission[];
};

export type AuthSession = {
  access_token?: string | null;
  user: AuthUser;
};

export function persistAuthSession(session: AuthSession): void {
  if (typeof window === "undefined") return;

  window.localStorage.setItem(
    AUTH_STORAGE_KEY,
    JSON.stringify({
      access_token: session.access_token ?? null,
      user: session.user,
    } satisfies AuthSession),
  );
}

let snapshotRawKey: string | undefined;
let snapshotSession: AuthSession | null = null;

/**
 * 供 `useSyncExternalStore` 的 getSnapshot 使用：在 localStorage 未变时返回同一引用，避免无限重渲染。
 */
export function getAuthSessionSnapshot(): AuthSession | null {
  if (typeof window === "undefined") return null;

  const raw = window.localStorage.getItem(AUTH_STORAGE_KEY);
  const key = raw ?? "";

  if (key === snapshotRawKey) {
    return snapshotSession;
  }

  snapshotRawKey = key;

  if (!raw) {
    snapshotSession = null;
    return null;
  }

  try {
    snapshotSession = JSON.parse(raw) as AuthSession;
    return snapshotSession;
  } catch {
    window.localStorage.removeItem(AUTH_STORAGE_KEY);
    snapshotRawKey = "";
    snapshotSession = null;
    return null;
  }
}

export function readAuthSession(): AuthSession | null {
  if (typeof window === "undefined") return null;

  const raw = window.localStorage.getItem(AUTH_STORAGE_KEY);
  if (!raw) return null;

  try {
    return JSON.parse(raw) as AuthSession;
  } catch {
    window.localStorage.removeItem(AUTH_STORAGE_KEY);
    return null;
  }
}

export function readAuthToken(): string | null {
  return readAuthSession()?.access_token ?? null;
}

export function clearAuthSession(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(AUTH_STORAGE_KEY);
}
