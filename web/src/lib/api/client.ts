import axios, {
  type AxiosError,
  type AxiosInstance,
  type InternalAxiosRequestConfig,
} from "axios";

import { clearAuthSession, readAuthToken } from "@/lib/auth";
import { withBasePath } from "@/lib/base-path";

import { resolveApiBaseUrl } from "./base-url";
import { messageFromResponseData } from "./error-detail";
import { ApiError, type CreateApiClientOptions } from "./types";

const AUTH_HEADER = "Authorization";

/**
 * Axios is intended for **client-side** usage (hooks, event handlers).
 * Do not call from Server Components unless you pass cookies/headers explicitly.
 */
export function createApiClient(options: CreateApiClientOptions = {}): AxiosInstance {
  const { getAccessToken, onUnauthorized } = options;

  const instance = axios.create({
    baseURL: resolveApiBaseUrl(),
    timeout: 60_000,
    headers: { "Content-Type": "application/json" },
    validateStatus: (status) => status >= 200 && status < 300,
  });

  instance.interceptors.request.use((config: InternalAxiosRequestConfig) => {
    if (typeof window !== "undefined") {
      config.baseURL = resolveApiBaseUrl();
    }
    const token =
      getAccessToken?.() ?? (typeof window !== "undefined" ? readAuthToken() : null);
    if (token) {
      config.headers.set(AUTH_HEADER, `Bearer ${token}`);
    }
    // 默认 Content-Type 为 application/json；FormData 必须由浏览器/axios 设置 multipart 边界
    if (typeof FormData !== "undefined" && config.data instanceof FormData) {
      config.headers.delete("Content-Type");
    }
    return config;
  });

  instance.interceptors.response.use(
    (res) => res,
    (error: AxiosError<unknown>) => {
      const status = error.response?.status;
      if (status === 401) {
        onUnauthorized?.();
      }

      const data = error.response?.data;
      const message =
        messageFromResponseData(data) ||
        (typeof data === "object" &&
          data !== null &&
          "message" in data &&
          typeof (data as { message: unknown }).message === "string" &&
          (data as { message: string }).message) ||
        error.message ||
        "请求失败";

      const code =
        typeof data === "object" && data !== null && "code" in data
          ? String((data as { code: unknown }).code)
          : undefined;

      return Promise.reject(
        new ApiError({
          message,
          status,
          code,
          details: data,
        }),
      );
    },
  );

  return instance;
}

function defaultOnUnauthorized(): void {
  clearAuthSession();
  if (typeof window === "undefined") return;
  const loginPath = withBasePath("/login");
  if (window.location.pathname === loginPath) return;
  window.location.replace(loginPath);
}

/** 默认实例：Bearer 使用 AUTH_STORAGE_KEY 内的 access_token；401 清会话并回登录 */
export const apiClient = createApiClient({
  onUnauthorized: defaultOnUnauthorized,
});
