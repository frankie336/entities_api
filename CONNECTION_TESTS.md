curl -X POST "http://localhost:9000/v1/generate" \
     -H "Content-Type: application/json" \
     -d '{
           "messages": [
               {"role": "user", "content": "Tell me a joke."}
           ],
           "model_name": "ri-qwen2.5-math-1.5b",
           "max_tokens": 50,
           "temperature": 0.9,
           "stream": true
         }'

