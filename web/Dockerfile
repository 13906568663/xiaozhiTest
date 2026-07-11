# syntax=docker/dockerfile:1
# 内网部署专用：构建期联网装依赖，运行期零外网依赖
# 关键设计：
#   1. 用 Debian slim 替代 alpine —— Next.js 16 在 alpine(musl) 上依赖的 @swc/core
#      和 lightningcss 的 native binary 经常装不全（导致 node_modules/.bin/next 不存在），
#      glibc 的 Debian 兼容性最好，next 官方也推荐生产用 Debian。
#   2. 用 npm 替代 corepack/pnpm —— 仓库里只有 package-lock.json，且 npm 是 node 自带，
#      runner 阶段不会有"找 pnpm 还要联 registry.npmjs.org"的死循环。
#   3. 启用 Next.js standalone 输出（next.config.ts 里 output: "standalone"），
#      runner 阶段只需要 .next/standalone + .next/static，连 node_modules 都不用拷。
#   4. base 镜像 pin 死小版本，重建可复现。
#   5. node 必须 >=22.12 —— vite 8 的打包器 rolldown 的原生二进制
#      (@rolldown/binding-linux-x64-gnu) engines 要求 ^20.19 || >=22.12，且是 optional 依赖；
#      node 22.11 下 npm 会「静默跳过」该平台二进制，导致 vite build 报
#      Cannot find module rolldown-binding.linux-x64-gnu.node。
FROM node:22.20.0-bookworm-slim AS base
WORKDIR /app

# ---------- 构建层（仅在能联网的构建机执行） ----------
FROM base AS builder

# 优先 npm ci（依赖锁文件），lock 缺失时回退到 npm install 以兼容首次构建
COPY package.json package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi && \
    test -x node_modules/.bin/next || (echo "ERROR: next 未正确安装" && ls -la node_modules/.bin/ | head -20 && exit 1)

COPY . .

# NEXT_PUBLIC_* 是 build-time 烤进 JS bundle 的，必须用 build-arg 传入
ARG NEXT_PUBLIC_API_BASE_URL
ARG NEXT_PUBLIC_BASE_PATH
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
ENV NEXT_PUBLIC_BASE_PATH=$NEXT_PUBLIC_BASE_PATH

# 跑 next build 生成 standalone 产物。直接用 node 调用二进制，绕开 PATH / .bin 软链接，最稳。
RUN node node_modules/next/dist/bin/next build

# ---------- 运行层（部署到内网，零外网依赖） ----------
FROM base AS runner
ENV NODE_ENV=production

RUN groupadd --system --gid 1001 nodejs && \
    useradd  --system --uid 1001 --gid nodejs nextjs

# Next.js standalone 已经把所需的最小 node_modules 内联到 standalone 目录里
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static     ./.next/static
# standalone 输出不会自动包含 public/；目录可能为空，构建期先占位再拷贝。
RUN mkdir -p ./public
COPY --from=builder --chown=nextjs:nodejs /app/public            ./public

USER nextjs
EXPOSE 3000
ENV PORT=3000 HOSTNAME="0.0.0.0"

CMD ["node", "server.js"]
