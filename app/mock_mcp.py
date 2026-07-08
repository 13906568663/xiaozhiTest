from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Literal, cast

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

_McpLogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


def _env_value(*names: str, default: str = "") -> str:
    for name in names:
        raw = os.getenv(name, "").strip()
        if raw:
            return raw
    return default


def _env_log_level(*names: str, default: _McpLogLevel = "INFO") -> _McpLogLevel:
    raw = _env_value(*names).upper()
    if raw in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        return cast(_McpLogLevel, raw)
    return default


def _env_int(*names: str, default: int) -> int:
    raw = _env_value(*names)
    return int(raw) if raw else default


def _append_log(tool_name: str, payload: dict[str, Any]) -> None:
    log_path = _env_value("MOCK_MCP_LOG_PATH", "MOCK_HTTP_MCP_LOG_PATH")
    if not log_path:
        return
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "tool": tool_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **payload,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


server = FastMCP(
    name="mock-mcp",
    instructions=("Mock MCP。"),
    host=_env_value("MOCK_MCP_HOST", "MOCK_HTTP_MCP_HOST", default="127.0.0.1"),
    port=_env_int("MOCK_MCP_PORT", "MOCK_HTTP_MCP_PORT", default=18080),
    streamable_http_path=_env_value("MOCK_MCP_PATH", "MOCK_HTTP_MCP_PATH", default="/mcp"),
    stateless_http=True,
    log_level=_env_log_level("MOCK_MCP_LOG_LEVEL", "MOCK_HTTP_MCP_LOG_LEVEL"),
)

# ── 通知数据 ─────────────────────────────────────────────


class NoticeDataOutput(BaseModel):
    """工具返回体的结构化定义；字段说明会进入 MCP 的 outputSchema。"""

    success: bool = Field(description="服务端是否已接受并记录本次通知")
    detail: str = Field(
        default="",
        description="补充说明，例如重复通知时的提示；正常可为空字符串",
    )


@server.tool(
    name="notice_prepare_data",
    description=("通知下游准备数据核对工作"),
    structured_output=True,
)
def notice_prepare_data(
    id: Annotated[
        str,
        Field(
            description=("流程 ID，唤醒工作流流程"),
        ),
    ] = "",
) -> NoticeDataOutput:
    _append_log("notice_prepare_data", {"id": id})
    return NoticeDataOutput(success=True, detail="")


# ── 获取数据 ─────────────────────────────────────────────
class GetDataOutput(BaseModel):
    """工具返回体的结构化定义；字段说明会进入 MCP 的 outputSchema。"""

    success: bool = Field(description="服务端是否已接受并记录本次通知")
    data: list[dict[str, Any]] = Field(
        default=[],
        description="数据列表",
    )


@server.tool(
    name="get_data",
    description="获取数据",
    structured_output=True,
)
def get_data(
    data_type: Annotated[
        str,
        Field(
            description="数据类型或阶段",
        ),
    ] = "",
) -> GetDataOutput:
    _append_log("get_data", {"data_type": data_type})
    return GetDataOutput(
        success=True,
        data=[
            {
                "id": "1",
                "name": "工单数据",
                "description": "工单数据描述",
            },
            {
                "id": "2",
                "name": "工单数据",
                "description": "工单数据2描述",
            },
        ],
    )


# ── 启动 ─────────────────────────────────────────────────


def run() -> None:
    server.run(transport="streamable-http")


if __name__ == "__main__":
    run()
