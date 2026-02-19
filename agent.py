"""
Agent Client — connects to the running FastMCP server via SSE and runs the agent.
Make sure mcp_server.py is running before starting this.
Run with: python agent.py
"""

import asyncio
import os
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import AIMessage, ToolMessage

# ── MCP Config — SSE transport pointing at the FastMCP server ─────────────────

MCP_CONFIG = {
    "playwright": {
        "url": "http://localhost:8000/sse",   # ✅ SSE endpoint from FastMCP
        "transport": "sse",
    }
}

# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """
You are a deep research agent with full browser access via Playwright.

Guidelines:
- Navigate websites carefully and wait for pages to fully load.
- Extract only relevant, factual information.
- If a page fails, retry once before giving up.
- Always summarize findings clearly and concisely.
""".strip()


def load_skills(path: str = "skills.md") -> str:
    try:
        with open(path) as f:
            content = f.read().strip()
            if content:
                return content
    except FileNotFoundError:
        pass
    return SYSTEM_PROMPT


# ── Pretty printer ────────────────────────────────────────────────────────────

def print_step(step: dict) -> None:
    for node_name, output in step.items():
        messages = output.get("messages", [])
        if not messages:
            continue

        last = messages[-1]
        print(f"\n{'─' * 60}")
        print(f"  Node : {node_name}")

        if isinstance(last, AIMessage):
            if last.tool_calls:
                for tc in last.tool_calls:
                    print(f"  Tool : {tc['name']}")
                    print(f"  Args : {str(tc['args'])[:120]}")
            elif last.content:
                print(f"  AI   : {last.content}")

        elif isinstance(last, ToolMessage):
            print(f"  Result: {str(last.content)[:300]}")

        print(f"{'─' * 60}")


# ── Main agent ────────────────────────────────────────────────────────────────

async def run_agent(query: str) -> str:
    # ✅ v0.1.0: no context manager — use initialize() / close()
    client = MultiServerMCPClient(MCP_CONFIG)

    try:
        await client.initialize()

        tools = client.get_tools()
        if not tools:
            raise RuntimeError(
                "No tools received. Is mcp_server.py running on port 8000?"
            )

        print(f"✅ Connected to FastMCP server. Tools: {[t.name for t in tools]}")

        llm = ChatOpenAI(
            model="gpt-4o",
            temperature=0,
            api_key=os.environ.get("OPENAI_API_KEY"),
        )

        agent = create_react_agent(llm, tools, prompt=load_skills())

        print("\n--- Agent starting ---\n")

        final_answer = ""
        async for step in agent.astream(
            {"messages": [("user", query)]},
            stream_mode="updates",
        ):
            print_step(step)
            for output in step.values():
                for msg in output.get("messages", []):
                    if isinstance(msg, AIMessage) and msg.content and not msg.tool_calls:
                        final_answer = msg.content

        return final_answer

    finally:
        await client.close()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    QUERY = (
        "Go to https://techcrunch.com and find the latest article about OpenAI. "
        "Return the headline and a 2-sentence summary."
    )

    result = asyncio.run(run_agent(QUERY))

    print("\n══════════════════════════════════════════════")
    print("FINAL ANSWER")
    print("══════════════════════════════════════════════")
    print(result)
