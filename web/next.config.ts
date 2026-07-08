import type { NextConfig } from "next";

// 统一访问前缀：与后端 BASE_PATH 一致，便于 B 系统 nginx 原样反代。
// 默认 /agent-flow；显式设为空字符串则不加前缀（本地裸跑可关闭）。
const basePath = (process.env.NEXT_PUBLIC_BASE_PATH ?? "/wgzcb-jzdd-dx/api/agent-flow").replace(
  /\/+$/,
  "",
);

const nextConfig: NextConfig = {
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  // 生成自包含的 server bundle，运行时不依赖 node_modules / pnpm / corepack，
  // 适合内网无外网的部署机
  output: "standalone",
  // basePath 自动给页面路由与 /_next 资源加前缀；assetPrefix 确保静态资源
  // 也走同一前缀。空前缀时不设置，保持根路径行为。
  ...(basePath ? { basePath, assetPrefix: basePath } : {}),
  // 配了 basePath 后，直接访问真正的根路径 `/`（不带前缀）会 404。
  // 加一条重定向：把裸根路径 `/` 直接跳到登录页 `<basePath>/login`，
  // 这样用 `localhost:3000` / `ip:端口` 直接访问就会进登录页（已登录用户
  // 会被登录页自动转到任务看板）。
  // basePath: false 让 source 匹配「未加前缀」的真实根路径，否则 redirects
  // 的 source 会被自动加上 basePath，变成匹配 /agent-flow/。
  async redirects() {
    return [
      {
        source: "/",
        destination: `${basePath}/login`,
        basePath: false,
        permanent: false,
      },
    ];
  },
  async rewrites() {
    const afterFiles: { source: string; destination: string }[] = [];

    // 本地 dev：前端 :3000、后端 :8000。前端的 API 走相对路径
    // `<basePath>/api/v1`，会打到 Next；这里代理到 FastAPI，避免「请求失败 404」。
    if (process.env.NODE_ENV === "development" && basePath) {
      afterFiles.push({
        source: "/api/:path*",
        destination: `http://127.0.0.1:8000${basePath}/api/:path*`,
      });
    }

    return {
      beforeFiles: [],
      afterFiles,
      fallback: [],
    };
  },
};

export default nextConfig;
