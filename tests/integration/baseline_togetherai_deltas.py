import os
from together import Together

# Ideally, set this in your environment variables: export TOGETHER_API_KEY="your_key"
client = Together(api_key=os.environ.get("TOGETHER_API_KEY", "d2c62c6ff04138210ca7e644fb8270a1d9508fbf93205465958040385a69701b"))



response_stream = client.chat.completions.create(
    model="Qwen/Qwen3-Next-80B-A3B-Thinking",
    messages=[
        {
            "role": "user",
            "content": "Explain black holes in PhD terms"
        }
    ],
    stream=True  # 1. Enable Streaming
)

print(f"{'DELTA TYPE':<15} | {'CONTENT PAYLOAD'}")
print("-" * 50)

# 2. Iterate over the generator
for chunk in response_stream:
    # Safely get the first choice (usually there is only one in streaming)
    if chunk.choices:
        delta = chunk.choices[0].delta

        # 3. Inspect what we received
        # DeepSeek-V3/Together usually sends 'content'.
        # If it were R1, you might see 'reasoning_content' depending on provider mapping.

        if delta.content is not None:
            # It is a text chunk
            print(f"{'Text Content':<15} | {repr(delta.content)}")

        elif delta.tool_calls:
            # It is a tool call chunk (if you had tools defined)
            print(f"{'Tool Call':<15} | {delta.tool_calls}")

        elif delta.role:
            # It is the header chunk establishing the role
            print(f"{'Role Setup':<15} | Role: {delta.role}")

        else:
            # Empty heartbeat or finish chunk
            print(f"{'Empty/Stop':<15} | None")