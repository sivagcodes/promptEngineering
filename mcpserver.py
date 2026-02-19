"""
FastMCP Proxy Server — maintains ONE persistent @playwright/mcp subprocess
and re-exposes ALL its tools over SSE.

Architecture:
    agent.py ──SSE──► mcp_server.py (FastMCP, Python)
                              │
                     single persistent stdio session
                              │
                       @playwright/mcp (Node.js)   ← lives here!
                              │
                          Chromium (shared browser state across all tool calls)

Run with:
    python mcp_server.py

Pre-requisites:
    pip install fastmcp mcp
    npx playwright install chromium
"""

import json
import os
from contextlib import asynccontextmanager

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent, Tool

# ── Config ────────────────────────────────────────────────────────────────────

PLAYWRIGHT_MCP_PARAMS = StdioServerParameters(
    command="npx",
    args=["-y", "@playwright/mcp@latest", "--headless"],
    env={**os.environ},
)

# ── Global persistent session ─────────────────────────────────────────────────
# One subprocess, one browser — state persists across every tool call.

_session: ClientSession | None = None
_stdio_cm = None      # keeps the stdio_client context manager alive
_session_cm = None    # keeps the ClientSession context manager alive


async def start_playwright_session():
    """Launch @playwright/mcp subprocess and open a persistent MCP session."""
    global _session, _stdio_cm, _session_cm

    _stdio_cm = stdio_client(PLAYWRIGHT_MCP_PARAMS)
    read, write = await _stdio_cm.__aenter__()

    _session_cm = ClientSession(read, write)
    _session = await _session_cm.__aenter__()

    await _session.initialize()
    print("✅ @playwright/mcp subprocess started and session initialized.")


async def stop_playwright_session():
    """Cleanly shut down the MCP session and kill the subprocess."""
    global _session, _stdio_cm, _session_cm
    if _session_cm:
        await _session_cm.__aexit__(None, None, None)
    if _stdio_cm:
        await _stdio_cm.__aexit__(None, None, None)
    _session = None
    print("🛑 @playwright/mcp session closed.")


# ── Tool proxy registration ───────────────────────────────────────────────────

async def register_proxy_tools():
    """
    Ask @playwright/mcp for its full tool list and register each one
    on this FastMCP server. All calls share the single persistent session
    so browser state (current page, cookies, etc.) is maintained.
    """
    tools_result = await _session.list_tools()
    tools: list[Tool] = tools_result.tools

    print(f"🔧 Registering {len(tools)} tools from @playwright/mcp:")
    for tool in tools:
        print(f"   • {tool.name}")
        _register_tool(tool)


def _register_tool(tool: Tool):
    tool_name = tool.name
    tool_description = tool.description or tool_name

    async def proxy_fn(**kwargs) -> str:
        # ✅ Reuses the single persistent session — browser state is preserved!
        result = await _session.call_tool(tool_name, arguments=kwargs)
        parts = []
        for block in result.content:
            if isinstance(block, TextContent):
                parts.append(block.text)
            else:
                parts.append(json.dumps(block.model_dump()))
        return "\n".join(parts)

    proxy_fn.__name__ = tool_name
    proxy_fn.__doc__ = tool_description

    mcp.add_tool(proxy_fn, name=tool_name, description=tool_description)


# ── FastMCP app with lifespan ─────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app):
    """Start @playwright/mcp before accepting requests, stop it on shutdown."""
    await start_playwright_session()   # 🚀 subprocess starts here
    await register_proxy_tools()       # 🔧 tools registered here
    yield                              # ✅ server is now ready
    await stop_playwright_session()    # 🛑 clean shutdown


mcp = FastMCP("playwright-proxy", lifespan=lifespan)

# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("🚀 Starting FastMCP SSE server on http://0.0.0.0:8000/sse")
    mcp.run(transport="sse", host="0.0.0.0", port=8000)
