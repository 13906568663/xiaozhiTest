"""小智AI MCP 接入模块（平台能力总入口）。

把 agent-flow 平台的完整 agent 能力（ReAct / 技能 / 知识库 / 记忆 / 外部
MCP 工具）通过 MCP 协议反向接入小智AI语音终端：

  - 连接方向：我们主动拨出 WebSocket 到小智接入点（wss://api.xiaozhi.me/mcp/
    ?token=xxx），小智云端在这条连接上作为 MCP 客户端调用工具；
  - 工具面：只暴露 3 个"元工具"（ask_assistant / submit_task / query_task），
    真正干活的是绑定的平台机器人（XIAOZHI_CHATBOT_ID）；
  - 模块划分：
      server.py       工具定义（FastMCP）
      agent_proxy.py  路由到 ChatEngine（会话粘滞 / 隔离任务 / 回复截断）
      tasks.py        进程内后台任务表（超时降级 / 显式异步任务）
      bridge.py       WebSocket 出站连接 <-> MCP Server 流适配
      connector.py    生命周期（启动 / 指数退避重连 / 优雅停止）
"""
