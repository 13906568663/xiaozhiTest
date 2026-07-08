"""Self-developed agent runtime core.

Layered modules:
  - messages: Msg / ContentBlock / Role  (data carriers)
  - tool_protocol: ToolHandler / ToolResult / ToolContext / ToolRegistry
  - provider: OpenAICompatProvider (httpx async streaming)
  - formatter: messages -> OpenAI/DeepSeek API dicts
  - memory: Memory (state_dict / load_state_dict)
  - hooks: HookRunner (pre/post reply / pre/post acting)
  - compression: text-based memory compression
  - mcp_client: MCP client transports (http / stdio)
  - runtime: ConversationRuntime (the agent loop)
"""

from app.runtime_core.messages import (
    ContentBlock,
    Msg,
    MsgRole,
)
from app.runtime_core.tool_protocol import (
    ToolCategory,
    ToolContext,
    ToolDefinition,
    ToolHandler,
    ToolMeta,
    ToolRegistry,
    ToolResult,
)

__all__ = [
    "ContentBlock",
    "Msg",
    "MsgRole",
    "ToolCategory",
    "ToolContext",
    "ToolDefinition",
    "ToolHandler",
    "ToolMeta",
    "ToolRegistry",
    "ToolResult",
]
