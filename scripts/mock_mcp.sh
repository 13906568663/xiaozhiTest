mkdir -p .tmp
export MOCK_MCP_LOG_PATH="${MOCK_MCP_LOG_PATH:-$PWD/.tmp/mock-mcp.log}"
uv run mock-mcp
