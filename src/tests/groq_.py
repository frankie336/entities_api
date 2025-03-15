from groq import Groq

client = Groq(api_key="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")
completion = client.chat.completions.create(
    model="deepseek-r1-distill-llama-70b",
    messages=[
        {
            "role": "user",
            "content": "Hello, I am coding up a front end app for you. Is there any way you can send us just enough text so that we know how to correctly parse?"
        }
    ],
    temperature=0.6,
    max_completion_tokens=4096,
    top_p=0.95,
    stream=True,
    stop=None,
)

for chunk in completion:
    print(chunk.choices[0].delta.content or "", end="")
