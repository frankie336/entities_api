Title:

Show r/LocalLLaMA: I built an open source OpenAI API alternative that runs fully local — code interpreter, RAG, agents, computer use, now with vLLM + multimodal support

Body:

Solo dev, been building quietly for a while. It's a containerised orchestration platform with a Python SDK that gives you full OpenAI API feature parity — but runs entirely on your hardware with Ollama or vLLM.
Features: code interpreter, web search, deep research, computer use, file search + vector stores, conversation state, GDPR data handling, signed URLs for tool files.
Just shipped vLLM raw inference integration and multimodal input this week.
No VC. No hype. Just working software. [link]



/v1/completions        ← our raw profiling target
/v1/completions/render ← rendered prompt preview
/inference/v1/generate ← bonus raw generate endpoint
/v1/messages           ← Anthropic-style endpoint (vLLM added this!)