#!/usr/bin/env python3
"""Remote shell：通过部署后端的隐藏调试端点在服务器上执行 shell 命令。

调用 ``POST {base_url}/debug/api-tester/run``（body ``{"command": "..."}``），
打印远端 stdout/stderr，并以远端退出码退出。

配置来源（优先级从高到低）：
1. 环境变量 ``REMOTE_SHELL_URL`` / ``REMOTE_SHELL_TOKEN``
2. 脚本同级目录的 ``config.json``（``{"url": ..., "token": ...}``，已被 gitignore）

用法::

    python3 rsh.py 'curl -s http://...'
    python3 rsh.py --timeout 60 'sleep 5; echo done'
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


def _load_config() -> tuple[str, str]:
    url = os.environ.get("REMOTE_SHELL_URL", "").strip()
    token = os.environ.get("REMOTE_SHELL_TOKEN", "").strip()
    if url and token:
        return url, token

    config_path = Path(__file__).resolve().parent.parent / "config.json"
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            sys.stderr.write(f"读取 config.json 失败：{exc}\n")
            sys.exit(2)
        url = url or str(data.get("url", "")).strip()
        token = token or str(data.get("token", "")).strip()

    if not url or not token:
        sys.stderr.write(
            "缺少配置：请设置 REMOTE_SHELL_URL / REMOTE_SHELL_TOKEN 环境变量，"
            "或在 .cursor/skills/remote-shell/config.json 填 url 与 token。\n"
        )
        sys.exit(2)
    return url, token


def main() -> int:
    parser = argparse.ArgumentParser(description="Remote shell over debug endpoint")
    parser.add_argument("command", help="要在远端服务器执行的 shell 命令")
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="远端命令超时（秒），缺省用服务端默认",
    )
    parser.add_argument(
        "--http-timeout",
        type=float,
        default=120.0,
        help="本地 HTTP 请求超时（秒）",
    )
    parser.add_argument(
        "--raw", action="store_true", help="原样打印 JSON 响应，不做格式化"
    )
    args = parser.parse_args()

    url, token = _load_config()
    payload: dict[str, object] = {"command": args.command}
    if args.timeout is not None:
        payload["timeout_seconds"] = args.timeout

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "Cookie": f"agent_flow_session={token}",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=args.http_timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        sys.stderr.write(f"HTTP {exc.code}: {detail}\n")
        if exc.code == 404:
            sys.stderr.write(
                "提示：404 通常表示服务端 DEBUG_API_TESTER_ENABLED 未开启，"
                "或 URL/前缀不对。\n"
            )
        return 1
    except urllib.error.URLError as exc:
        sys.stderr.write(f"连接失败：{exc.reason}\n")
        return 1

    if args.raw:
        sys.stdout.write(body + "\n")
        return 0

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        sys.stdout.write(body + "\n")
        return 0

    stdout = data.get("stdout") or ""
    stderr = data.get("stderr") or ""
    exit_code = data.get("exit_code")
    if stdout:
        sys.stdout.write(stdout)
        if not stdout.endswith("\n"):
            sys.stdout.write("\n")
    if stderr:
        sys.stderr.write(stderr)
        if not stderr.endswith("\n"):
            sys.stderr.write("\n")
    if data.get("timed_out"):
        sys.stderr.write(f"[远端超时] {data.get('error') or ''}\n")
    if data.get("truncated"):
        sys.stderr.write("[输出已被服务端截断]\n")

    meta = (
        f"[exit={exit_code} duration={data.get('duration_ms')}ms]"
        if exit_code is not None
        else "[no exit code]"
    )
    sys.stderr.write(meta + "\n")

    if isinstance(exit_code, int):
        return exit_code
    return 0 if data.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
