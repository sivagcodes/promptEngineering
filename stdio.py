from mcp.client.tcp import tcp_client
from mcp import ClientSession
from langgraph.prebuilt import create_react_agent
from langchain_openai import ChatOpenAI
from langchain_core.tools import StructuredTool
import asyncio


async def load_mcp_tools():
    reader, writer = await tcp_client("localhost", 3001)

    session = ClientSession(reader, writer)
    await session.initialize()

    tools = []
    mcp_tools = await session.list_tools()

    for t in mcp_tools.tools:

        async def tool_func(tool_name):
            async def _tool(**kwargs):
                return await session.call_tool(tool_name, kwargs)
            return _tool

        tools.append(
            StructuredTool.from_function(
                coroutine=await tool_func(t.name),
                name=t.name,
                description=t.description
            )
        )

    return tools


async def main():
    tools = await load_mcp_tools()

    llm = ChatOpenAI(model="gpt-4o-mini")

    agent = create_react_agent(llm, tools)

    result = await agent.ainvoke({
        "messages": [
            {"role": "user",
             "content": "Open example.com and tell me the h1 text"}
        ]
    })

    print(result)


asyncio.run(main())