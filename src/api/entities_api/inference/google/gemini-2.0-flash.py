import os

import google.generativeai as genai

# Make sure your API key is configured (e.g., via environment variable)
# genai.configure(api_key=os.environ["GEMINI_API_KEY"])
genai.configure(
    api_key="AIzaSyBzR1BNNVY3Pf-FzPsAMgMYeKxRZNXAiKY"
)  # Or replace with your actual key

print("Available models that support generateContent:")
for m in genai.list_models():
    if "generateContent" in m.supported_generation_methods:
        print(f"- {m.name}")

# Now choose one of the printed models for your GenerativeModel initialization
# model = genai.GenerativeModel('put-one-of-the-valid-model-names-here')
# ... rest of your code ...
