import { BASE_PATH } from "@/lib/base-path";

/**
 * 解析后端 API base url：
 *   1) 浏览器端 / SSR 端都优先读 NEXT_PUBLIC_API_BASE_URL（build 时烤入 bundle，运行时也可读）。
 *   2) 浏览器端无 env：返回同源相对路径 `<base_path>/api/v1`，由 nginx/ingress 反代到后端。
 *      统一前缀（默认 /agent-flow）与后端 BASE_PATH 保持一致，这样一个镜像可在
 *      任意域名/IP 下复用，无需为每个环境重打镜像。
 *   3) SSR 端无 env：兜底到本机 dev 地址，仅用于本地开发。生产建议显式注入 INTERNAL_API_BASE_URL
 *      或 NEXT_PUBLIC_API_BASE_URL。
 */
export function resolveApiBaseUrl(): string {
  const fromEnv = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
  if (fromEnv) {
    return fromEnv.replace(/\/$/, "");
  }

  if (typeof window !== "undefined") {
    return `${BASE_PATH}/api/v1`;
  }

  return `http://localhost:8000${BASE_PATH}/api/v1`;
}
