import time
import json
import re
from openai import OpenAI


def get_current_weather(location):
    """
    Placeholder for your actual weather retrieval function.
    Replace this with code that calls a real weather API if needed.
    For demonstration, we return a simple string.
    """
    return f"25°C."


def camel_to_snake(name):
    """
    Convert a CamelCase function name to snake_case.
    For example, "getCurrentWeather" becomes "get_current_weather".
    """
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def extract_json_from_markdown(text):
    """
    Remove markdown formatting (e.g., triple backticks) from the text.
    If the text is wrapped in ```json ... ```, this function strips
    those markers and returns the inner JSON string.
    """
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    return text


def process_function_call(message):
    """
    Process the function call returned by the model.
    This function:
      1. Strips out any markdown formatting.
      2. Parses the cleaned JSON.
      3. Normalizes the function name.
      4. Dispatches the appropriate function.
    """
    try:
        cleaned_content = extract_json_from_markdown(message.content)
        parsed = json.loads(cleaned_content)
        function_name = parsed.get("name")
        arguments = parsed.get("arguments", {})

        # Normalize the function name (e.g., getCurrentWeather -> get_current_weather)
        normalized_name = camel_to_snake(function_name)
        print(
            f"Function call detected: original='{function_name}', normalized='{normalized_name}' with arguments {arguments}")

        if normalized_name in ["get_current_weather", "get_weather"]:
            result = get_current_weather(**arguments)
        elif normalized_name == "greet":
            result = f"Greetings! {arguments.get('message', '')}"
        else:
            result = f"Error: Unknown function '{normalized_name}'"

        return normalized_name, result

    except json.JSONDecodeError as e:
        print(f"JSON decode error: {e}")
        print("No valid function call detected.")
        return None, None


def send_messages(messages, force_tool_call=False, include_tools=True):
    """
    Send messages to the model.

    Parameters:
      - messages: The conversation history.
      - force_tool_call: When True, forces a function call.
      - include_tools: When True, includes the tools definitions in the request.
                     For follow-up calls, you might set this to False.
    """
    request_params = {
        "model": "deepseek-ai/DeepSeek-V3",
        "messages": messages,
        "temperature": 0.6,
    }
    if include_tools:
        request_params["tools"] = tools
    if force_tool_call:
        request_params["function_call"] = {"name": "get_weather"}

    response = client.chat.completions.create(**request_params)

    try:
        response_dict = response.to_dict()
    except AttributeError:
        response_dict = response.__dict__
    print("Full API Response:")
    print(json.dumps(response_dict, indent=2))

    return response.choices[0].message


# Initialize the client.
client = OpenAI(
    api_key="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJwcmltZS50aGFub3MzMzZAZ21haWwuY29tIiwiaWF0IjoxNzM4NDc2MzgyfQ.4V27eTb-TRwPKcA5zit4pJckoEUEa7kxmHwFEn9kwTQ",
    # Replace with your actual API key.
    base_url="https://api.hyperbolic.xyz/v1",
)

# Define multiple tools.
tools = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get weather of an location. The user should supply a location.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "City name and optionally state or country, e.g., 'Hangzhou, China'",
                    }
                },
                "required": ["location"]
            },
        }
    },
    {
        "type": "function",
        "function": {
            "name": "greet",
            "description": "Greet the user with a friendly message.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "The greeting message to deliver.",
                    }
                },
                "required": ["message"]
            },
        }
    },
]

# System prompt instructing the model on the desired response format.
system_prompt = {
    "role": "system",
    "content": (
        "You must strictly adhere to the following guidelines:\n"
        "- When a tool (function) is called, your response **must** be a valid JSON object containing only the keys 'name' and 'arguments'.\n"
        "- Do **not** wrap JSON responses in markdown (e.g., no triple backticks).\n"
        "- If a tool is invoked, **never** reply with an empty message.\n"
        "- If a tool response is provided by the system (with role='tool'), always **acknowledge and incorporate it** into your next response.\n"
        "- If the user’s request is unclear, request clarification instead of defaulting to a blank or incomplete response.\n"
        "- If no tool applies, respond naturally.\n"
        "Failure to follow these instructions will result in incorrect tool handling."
    )
}
# Example user prompt.
user_message = {"role": "user", "content": "How's the weather in Hangzhou?"}

# Construct the conversation.
messages = [system_prompt, user_message]

# Send the initial message.
assistant_message = send_messages(messages)
print(f"User>\t {user_message['content']}")
print("Assistant Response:")
print(assistant_message)

# --- Adopt the Example Workflow ---
# First, check if the native tool_calls attribute exists.
if hasattr(assistant_message, "tool_calls") and assistant_message.tool_calls:
    # If present, extract the first tool call.
    tool_call = assistant_message.tool_calls[0]
    messages.append(assistant_message)
    # Simulate executing the tool call.
    # (In a real system, you might use tool_call.arguments here.)
    result = get_current_weather(location="Hangzhou")
    # Append the tool's output as a new message with role "tool".
    tool_response_message = {
        "role": "tool",
        "tool_call_id": tool_call.id,  # Use the actual tool call ID.
        "content": result
    }
    messages.append(tool_response_message)
    followup_message = send_messages(messages, include_tools=False)
    print("Followup Assistant Response:")
    print(followup_message)
else:
    # --- Fallback: Use our custom parser ---
    function_name, function_result = process_function_call(assistant_message)
    if function_name and function_result:
        print(f"Executing function '{function_name}' with result: {function_result}")
        # Instead of using role "function", adopt the "tool" role as in the sample.
        tool_response_message = {
            "role": "tool",
            "tool_call_id": "dummy",  # Since we don't have a native tool call ID.
            "content": function_result
        }
        # Append the assistant message and then the tool message.
        messages.append(assistant_message)
        messages.append(tool_response_message)
        followup_message = send_messages(messages, include_tools=True)
        print("Followup Assistant Response:")
        print(followup_message)
    else:
        print("No function call to process. Proceeding with normal conversation.")


print(messages)