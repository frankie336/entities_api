from transformers import AutoModelForCausalLM, AutoTokenizer
import torch

# Define model path
model_path = "C:/Users/franc/Models/HuggingFace/DeepSeek-R1-Distill-Qwen-1.5B"

# Load tokenizer
tokenizer = AutoTokenizer.from_pretrained(model_path)

# Load model (ensure it's on GPU if available)
device = "cuda" if torch.cuda.is_available() else "cpu"
model = AutoModelForCausalLM.from_pretrained(model_path, torch_dtype=torch.float16 if device == "cuda" else torch.float32)
model.to(device)

# Run a test prompt
prompt = "Once upon a time,"
inputs = tokenizer(prompt, return_tensors="pt").to(device)
outputs = model.generate(**inputs, max_length=50)

# Decode and print output
print(tokenizer.decode(outputs[0], skip_special_tokens=True))
