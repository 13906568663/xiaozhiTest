/**
 * 统一访问前缀（base path）。
 *
 * B 系统通过 nginx 反代我们的前后端时，所有页面 / 资源 / 接口都挂在该前缀下
 * （nginx 原样 proxy_pass，无需 rewrite）。值来自构建期注入的
 * NEXT_PUBLIC_BASE_PATH，默认 `/agent-flow`；显式设为空字符串则不加前缀。
 *
 * 该值必须与 `next.config.ts` 的 basePath 及后端 `BASE_PATH` 保持一致。
 *
 * 说明：Next.js 的 `<Link>` / `router` / `next/image` 会自动带 basePath，
 * 无需调用本工具；只有手写的 `window.location` 跳转、原生 `<a href>` 等
 * 才需要用 `withBasePath()` 显式拼接。
 */
export const BASE_PATH = (
  process.env.NEXT_PUBLIC_BASE_PATH ?? "/agent-flow"
).replace(/\/+$/, "");

export function withBasePath(path: string): string {
  const suffix = path.startsWith("/") ? path : `/${path}`;
  return `${BASE_PATH}${suffix}`;
}
