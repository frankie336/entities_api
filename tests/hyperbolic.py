import requests

url = "https://api.hyperbolic.xyz/v1/chat/completions"
headers = {
    "Content-Type": "application/json",
    "Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJwcmltZS50aGFub3MzMzZAZ21haWwuY29tIiwiaWF0IjoxNzM4NDc2MzgyfQ.4V27eTb-TRwPKcA5zit4pJckoEUEa7kxmHwFEn9kwTQ"
}
data = {
    "messages": [
        {
            "role": "user",
            "content": "<important>See tools.If this prompt triggers a function, return the name of the function. See tools.</important>What is the weather  SF today?"

        },


        {
            "role": "assistant",
            "content": "get_weather"
        },





    ],
    "model": "deepseek-ai/DeepSeek-V3",
    "max_tokens": 508,
    "temperature": 0.1,
    "top_p": 0.9,
    "tools": [
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
                            "description": "The city and state, e.g. San Francisco, CA"
                        }
                    },
                    "required": ["location"]
                }
            }
        }
    ]
}
response = requests.post(url, headers=headers, json=data)
print(response.json())
