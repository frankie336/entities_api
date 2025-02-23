from transformers import AutoModelForCausalLM, AutoTokenizer
import torch

# Define model path
model_path = "C:/Users/franc/Models/HuggingFace/DeepSeek-R1-Distill-Qwen-1.5B"

# Load tokenizer and model
tokenizer = AutoTokenizer.from_pretrained(model_path)
device = "cuda" if torch.cuda.is_available() else "cpu"
model = AutoModelForCausalLM.from_pretrained(
    model_path,
    torch_dtype=torch.float16 if device == "cuda" else torch.float32
)
model.to(device)
model.eval()

# Actual prompt with designated roles
prompt = (
    "User: Hi there, can you explain gradient descent in simple terms?\n"
    "Assistant: "
)

# Encode prompt and generate the assistant's response
inputs = tokenizer(prompt, return_tensors="pt").to(device)
outputs = model.generate(
    **inputs,
    max_length=200,            # Adjust max length as needed
    pad_token_id=tokenizer.eos_token_id,
    do_sample=True,            # Optional: enables sampling for varied responses
    temperature=0.7            # Optional: controls randomness
)

# Decode and print the full conversation output
generated_text = tokenizer.decode(outputs[0], skip_special_tokens=True)
print(generated_text)

