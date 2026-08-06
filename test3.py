"""
Same structure as mcp_agent_litellm.py, but the MCP server is REMOTE -
already running somewhere on the internet, not launched by us.

Difference vs. the local/stdio version:
- No StdioServerParameters / stdio_client (nothing to launch).
- Instead: streamablehttp_client(url) connects over plain HTTP to a
  server that's already up and running.
- May need an Authorization header if the server requires one - many
  free/demo MCP servers don't, but production ones usually do.

Setup:
    pip install mcp litellm
    export OPENAI_API_KEY=...
    python remote_mcp_agent.py
"""

import asyncio
import json
from litellm import completion
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

# The server's URL - this is the ONLY thing that tells us where the
# server lives, since we didn't start it ourselves.
MCP_SERVER_URL = "https://mcp.context7.com/mcp"

# Only needed if the server requires auth (many do, for rate limiting).
# Leave the dict empty if the server is fully open.
HEADERS = {
    # "Authorization": "Bearer YOUR_API_KEY",
}


def mcp_tools_to_openai_format(mcp_tools):
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
    # streamablehttp_client replaces stdio_client - it opens an HTTP
    # connection to an already-running server instead of spawning one.
    async with streamablehttp_client(MCP_SERVER_URL, headers=HEADERS) as (
        read,
        write,
        _get_session_id,   # HTTP transport also returns a session id getter; unused here
    ):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # STEP 1: same as before - ask the server what tools it has.
            mcp_tools = (await session.list_tools()).tools
            tools = mcp_tools_to_openai_format(mcp_tools)

            messages = [{
                "role": "user",
                "content": "Look up the latest docs for the 'requests' Python library and summarize how to make a GET request.",
            }]

            while True:
                # STEP 2: identical - litellm only ever talks to the LLM.
                response = completion(model="gpt-4o", messages=messages, tools=tools)
                reply = response.choices[0].message
                messages.append(reply.model_dump())

                if not reply.tool_calls:
                    print("Agent:", reply.content)
                    break

                for call in reply.tool_calls:
                    args = json.loads(call.function.arguments)
                    print(f"-> running {call.function.name}({args})")

                    # STEP 3: identical call shape - session.call_tool()
                    # doesn't care whether the server is local or remote.
                    result = await session.call_tool(call.function.name, args)
                    result_text = "".join(
                        c.text for c in result.content if c.type == "text"
                    )

                    messages.append({
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": result_text,
                    })


if __name__ == "__main__":
    asyncio.run(main())