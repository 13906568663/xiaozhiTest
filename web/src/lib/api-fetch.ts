/**
 * 原生 fetch 封装，供需要 SSE 流式响应的模块使用（如 chat-stream）。
 */

import { clearAuthSession, readAuthToken } from "@/lib/auth";
import { resolveApiBaseUrl } from "@/lib/api/base-url";
import { formatApiErrorDetail } from "@/lib/api/error-detail";
import { withBasePath } from "@/lib/base-path";

export const API_BASE_URL = resolveApiBaseUrl();

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

let loginRedirectPending = false;

function redirectToLogin(): void {
  clearAuthSession();
  if (typeof window === "undefined") return;
  const loginPath = withBasePath("/login");
  if (window.location.pathname === loginPath || loginRedirectPending) return;
  loginRedirectPending = true;
  window.location.replace(loginPath);
}

export function buildApiHeaders(init?: RequestInit, requiresAuth = true): Headers {
  const headers = new Headers(init?.headers ?? {});

  if (!(init?.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  if (requiresAuth) {
    const token = readAuthToken();
    if (token) {
      headers.set("Authorization", `Bearer ${token}`);
    }
  }

  return headers;
}

async function parseError(response: Response): Promise<ApiError> {
  let message = `Request failed: ${response.status}`;
  try {
    const payload = (await response.json()) as { detail?: unknown };
    if (payload.detail !== undefined) {
      message = formatApiErrorDetail(payload.detail) || message;
    }
  } catch {
    // ignore
  }
  return new ApiError(message, response.status);
}

export async function requestJson<T>(
  path: string,
  init?: RequestInit,
  options?: { requiresAuth?: boolean; redirectOnUnauthorized?: boolean },
): Promise<T> {
  const requiresAuth = options?.requiresAuth ?? true;
  const redirectOnUnauthorized = options?.redirectOnUnauthorized ?? true;

  try {
    const response = await fetch(`${resolveApiBaseUrl()}${path}`, {
      ...init,
      cache: init?.cache ?? "no-store",
      credentials: init?.credentials ?? "include",
      headers: buildApiHeaders(init, requiresAuth),
      signal: init?.signal,
    });

    if (!response.ok) {
      const err = await parseError(response);
      if (response.status === 401 && redirectOnUnauthorized) {
        redirectToLogin();
      }
      throw err;
    }

    if (response.status === 204) {
      return undefined as T;
    }

    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof ApiError && error.status === 401 && redirectOnUnauthorized) {
      redirectToLogin();
    }
    throw error;
  }
}
