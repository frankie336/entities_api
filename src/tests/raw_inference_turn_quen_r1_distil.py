from transformers import AutoModelForCausalLM, AutoTokenizer
import torch
import json

# Define model path
model_path = "C:/Users/franc/Models/HuggingFace/DeepSeek-R1-Distill-Qwen-1.5B"

# Load tokenizer and model
tokenizer = AutoTokenizer.from_pretrained(model_path)
device = "cuda" if torch.cuda.is_available() else "cpu"
model = AutoModelForCausalLM.from_pretrained(
    model_path,
    torch_dtype=torch.float16 if device == "cuda" else torch.float32
).to(device)
model.eval()

# Define available tool
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Retrieves the weather for a given location.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "The location for which to retrieve the weather."}
                },
                "required": ["location"]
            }
        }
    }
]

# Function registry (simulated tool execution)
FUNCTIONS = {
    "get_weather": lambda location: "24°C"  # Just the temperature, no extra text
}

# Define chat history
chat_history = [
    {
        "role": "system",
        "content": (
            "You are an AI assistant capable of function calling. "
            "When a function call is needed, you must return the function call directly in text. "
            "You will then receive the function result and continue responding.\n\n"
            "tools:\n"
            + json.dumps(TOOLS, indent=2)
        ),
    }
]

# Example user request
user_message = {"role": "user", "content": "Hello, how are you?"}
chat_history.append(user_message)

# Convert chat history to text
formatted_prompt = "\n".join([f"{msg['role'].capitalize()}: {msg['content']}" for msg in chat_history])

# Encode prompt and generate response
inputs = tokenizer(formatted_prompt, return_tensors="pt").to(device)
outputs = model.generate(
    **inputs,
    max_length=900,
    pad_token_id=tokenizer.eos_token_id,
    do_sample=False,
    temperature=1
)

# Decode model response
generated_text = tokenizer.decode(outputs[0], skip_special_tokens=True)
print("\nAssistant Response:\n", generated_text)

# Detect function call in generated text (assuming it would be of form get_weather("location"))
if "get_weather" in generated_text:
    try:
        # Extract location (assuming format 'get_weather("location")')
        location_start = generated_text.find('("') + 2
        location_end = generated_text.find('")')
        location = generated_text[location_start:location_end]

        # Log the tool call in chat history as assistant's response
        tool_call_message = {
            "role": "assistant",
            "content": f"get_weather({location})"
        }
        chat_history.append(tool_call_message)

        # Call the function (simulated)
        result = FUNCTIONS["get_weather"](location)

        # Append tool response to chat history
        tool_message = {"role": "tool", "content": result}
        chat_history.append(tool_message)

        # Generate final response based on updated chat history
        formatted_prompt = "\n".join([f"{msg['role'].capitalize()}: {msg['content']}" for msg in chat_history])
        inputs = tokenizer(formatted_prompt, return_tensors="pt").to(device)
        outputs = model.generate(
            **inputs,

            pad_token_id=tokenizer.eos_token_id,
            do_sample=False,  # Ensure deterministic output
            temperature=1
        )

        # Final assistant response
        final_response = tokenizer.decode(outputs[0], skip_special_tokens=True)
        print("\nFinal Assistant Response:\n", final_response)
        print(chat_history)

    except Exception as e:
        print("\nError processing function call:", e)
