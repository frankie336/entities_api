import os

import google.generativeai as genai

genai.configure(api_key="AIzaSyBzR1BNNVY3Pf-FzPsAMgMYeKxRZNXAiKY")
print("Available models that support generateContent:")
for m in genai.list_models():
    if "generateContent" in m.supported_generation_methods:
        print(f"- {m.name}")
