"""
SIMPLE litellm tool-calling demo.

The whole idea in one sentence: the LLM never touches your files itself -
it just tells YOUR code what it wants to do, and your code does it.

Run it:
    pip install litellm
    export OPENAI_API_KEY=...      # or ANTHROPIC_API_KEY, etc.
    python simple_agent.py
"""

import json
from litellm import completion

# ---------------------------------------------------------------------------
# STEP 1: Write the real functions the model is allowed to trigger.
# These are 100% normal Python - nothing "AI" about them.
# ---------------------------------------------------------------------------

def write_file(filename, content):
    with open(filename, "w") as f:
        f.write(content)
    return f"Saved {filename}"


def read_file(filename):
    with open(filename, "r") as f:
        return f.read()


# A lookup table so we can call the right function by name later
TOOL_FUNCTIONS = {
    "write_file": write_file,
    "read_file": read_file,
}

# ---------------------------------------------------------------------------
# STEP 2: Describe those functions to the model as JSON schemas.
# This is NOT code the model runs - it's just documentation so the model
# knows the tool exists, what it's called, and what arguments it needs.
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or overwrite a file with the given content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["filename", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read and return the contents of a file.",
            "parameters": {
                "type": "object",
                "properties": {"filename": {"type": "string"}},
                "required": ["filename"],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# STEP 3: The agent loop.
# Call the model -> if it asks for a tool, run it locally -> send the result
# back -> repeat until the model just replies with plain text.
# ---------------------------------------------------------------------------

def run_agent(instruction, model="gpt-4o"):
    # The conversation so far. We keep appending to this list.
    messages = [{"role": "user", "content": instruction}]

    while True:
        # Send the full conversation + the tool schemas to the model.
        response = completion(model=model, messages=messages, tools=TOOLS)
        reply = response.choices[0].message

        # Always add the model's reply to the conversation history,
        # so it remembers what it just said on the next loop.
        messages.append(reply.model_dump())

        # Case A: the model did NOT ask for a tool -> it's giving a final answer.
        if not reply.tool_calls:
            print("Agent:", reply.content)
            break  # exit the loop, we're done

        # Case B: the model asked to use one or more tools.
        for call in reply.tool_calls:
            name = call.function.name                      # e.g. "write_file"
            args = json.loads(call.function.arguments)      # e.g. {"filename": "hello.py", ...}

            print(f"-> running {name}({args})")

            # Look up and run the REAL python function ourselves.
            # The model only requested this - it did not execute it.
            function_to_call = TOOL_FUNCTIONS[name]
            result = function_to_call(**args)

            # Feed the result back into the conversation as a "tool" message,
            # tagged with tool_call_id so the model knows which request it answers.
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": str(result),
            })

        # Loop back to STEP 3's completion() call with the new messages,
        # so the model can see the tool result and decide what to do next.


if __name__ == "__main__":
    run_agent("Create hello.py that prints 'Hello, world!', then read it back to me.")