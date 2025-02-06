import openai
import json

# Initialize the OpenAI client with your Hyperbolic endpoint.
client = openai.OpenAI(
    api_key="sk-f7c38a5f36e44b3e849d13b7e40f7157",
    base_url="https://api.deepseek.com",
)

# Define the tools list for function calling.
tools = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get weather of an location, the user should supply a location first",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "The city and state, e.g. San Francisco, CA",
                    }
                },
                "required": ["location"]
            },
        }
    }
]


def send_messages(messages):
    """
    Sends messages along with tool definitions to the API and returns the first message
    from the response.
    """
    try:
        chat_completion = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            tools=tools
        )
        # Return the message object from the first choice.
        return chat_completion.choices[0].message
    except Exception as e:
        print(f"Error during send_messages: {e}")
        raise


# Start conversation with an initial user message.
messages = [{"role": "user", "content": "How's the weather in Hangzhou?"}]
try:
    response_message = send_messages(messages)
except Exception as e:
    print("Failed to send initial message:", e)
    exit(1)

print("User:\t", messages[0]['content'])
print("Initial response:")
print(response_message.content)

# Check for a tool call trigger.
if hasattr(response_message, "tool_calls") and response_message.tool_calls:
    tool_call = response_message.tool_calls[0]
    print("\nTool call triggered:")
    print(json.dumps(tool_call.dict(), indent=2))

    # Append the assistant's response (converted to dict) to the conversation history.
    messages.append(response_message.dict())

    # Simulate a tool response.
    tool_response = {
        "role": "tool",
        "tool_call_id": tool_call.id,
        "content": "24℃"
    }
    messages.append(tool_response)

    # Append a follow-up assistant message as a reminder of the tool output.
    reminder_message = {
        "role": "assistant",
        "content": "Reminder: Please make sure you have given the user the output from the tool call."
    }
    messages.append(reminder_message)

    try:
        final_response = send_messages(messages)
    except Exception as e:
        print("Failed to send follow-up messages:", e)
        exit(1)
    print("\nFinal response:")
    print(final_response.content)
else:
    print("\nNo tool call was triggered.")
