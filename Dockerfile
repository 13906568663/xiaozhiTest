# syntax=docker/dockerfile:1
# 内网部署专用：构建期联网装依赖（uv.lock 已 freeze），运行期零外网依赖
# base 镜像 pin 死小版本，避免重建结果漂移
FROM python:3.12.7-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# 镜像源参数化：内网构建机访问 pypi.org / deb.debian.org 极慢，默认走阿里云镜像；
# 海外服务器上直连官方源反而更快，构建时用 --build-arg 覆盖即可，例如：
#   --build-arg UV_INDEX=https://pypi.org/simple/ --build-arg APT_MIRROR_CN=false
ARG UV_INDEX=https://mirrors.aliyun.com/pypi/simple/
ENV UV_DEFAULT_INDEX=${UV_INDEX}
ARG APT_MIRROR_CN=true

# curl 仅作为容器内 healthcheck/排障使用；不需要可移除
RUN if [ "$APT_MIRROR_CN" = "true" ]; then \
        sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
        sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list 2>/dev/null || true; \
    fi
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# uv 二进制 pin 死版本，避免每次构建从 ghcr 拉到不同版本
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /usr/local/bin/

WORKDIR /app

# ---------- 依赖安装层（利用 Docker 缓存，仅安装第三方依赖） ----------
FROM base AS deps

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# ---------- 运行层 ----------
FROM base AS runtime

COPY --from=deps /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock alembic.ini ./
COPY app/ app/
COPY alembic/ alembic/
COPY scripts/ scripts/

# 把当前项目以 editable 方式安装到 venv，注册 [project.scripts] 入口
# （timeout-sweeper / api 等 entry point 依赖这一步；uv.lock 已 freeze，不联网）
RUN uv sync --frozen --no-dev

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
