"""
Middle ground: raw `mcp` SDK talks to the tool server ourselves,
litellm is used ONLY for the completion() call - so you keep
multi-provider portability without litellm's MCP client wrapper.

Setup:
    pip install mcp litellm
    npm install -g @modelcontextprotocol/server-filesystem
    export OPENAI_API_KEY=...      # or ANTHROPIC_API_KEY, etc.
    python mcp_agent_litellm.py
"""

import asyncio
import json
from litellm import completion
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from dotenv import load_dotenv
load_dotenv(override=True)

server_params = StdioServerParameters(
    command="npx",
    args=["-y", "@modelcontextprotocol/server-filesystem", "./sandbox"],
)


def mcp_tools_to_openai_format(mcp_tools):
    # litellm/OpenAI want {"type": "function", "function": {...}} wrappers
    # with a "parameters" key - MCP calls the same thing "inputSchema".
    # Just a reshape, no new schemas written.
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.inputSchema,
            },
        }
        for t in mcp_tools
    ]


async def main():
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # STEP 1: get the tool list from the MCP server directly.
            mcp_tools = (await session.list_tools()).tools
            tools = mcp_tools_to_openai_format(mcp_tools)

            messages = [{
                "role": "user",
                "content": "add another function of your choice for hello.py without removing its content",
            }]

            while True:
                # STEP 2: litellm handles ONLY the model call here.
                response = completion(model="deepseek/deepseek-v4-flash", messages=messages, tools=tools)
                reply = response.choices[0].message
                messages.append(reply.model_dump())

                if not reply.tool_calls:
                    print("Agent:", reply.content)
                    break

                for call in reply.tool_calls:
                    args = json.loads(call.function.arguments)
                    print(f"-> running {call.function.name}({args})")

                    # STEP 3: run the tool through the MCP server directly.
                    result = await session.call_tool(call.function.name, args)
                    result_text = "".join(
                        c.text for c in result.content if c.type == "text"
                    )

                    print(result)
                    print(result_text)

                    messages.append({
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": result_text,
                    })
            print(mcp_tools)


if __name__ == "__main__":
    asyncio.run(main())