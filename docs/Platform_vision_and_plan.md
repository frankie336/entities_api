# Project Uni5
## From the Lab to Enterprise Grade Orchestration — Instantly.

Most platforms make you choose. Either you're in the research and experimentation
world with scrappy tooling, or you're in the enterprise world with heavyweight
infrastructure requirements. The gap between those two is where most open source
models go to die — the training works but nobody can actually use them in a real
system without significant engineering.

This platform closes that gap entirely.

A model that has never been deployed anywhere — straight off a training run —
plugs directly into a full-featured enterprise orchestration stack with zero
infrastructure overhead.

```
Train model → save weights → point platform at path → full orchestration
```

No API deployment step. No vLLM setup. No distributed systems knowledge required.
Just a path to a directory.

The same platform already handles hosted providers (Hyperbolic, TogetherAI),
local runtimes (Ollama), sandboxed shell execution, multi-agent delegation,
file serving, and a streaming frontend. The model integration work completes
the picture.

---

## Why Single Machine First

The platform's existing architecture maps directly to the single machine market:

- Sandbox is FireJail on a single host — not a distributed system
- Tool routing, shell execution, and file handling are all single machine concepts
- Ollama (the dominant single machine runtime) is already a supported provider
- The open source community most likely to build on this platform is running
  consumer or prosumer hardware, not GPU clusters
- Enterprises with data privacy requirements cannot send data to an external API —
  local model execution is a hard requirement for them

The `transformers` adapter is the specific missing piece. It means the gap
between "I have weights" and "I have a running orchestration platform" is
closed entirely.

---

## The Model Integration Stack

Three adapters, three markets, one platform:

| Adapter | Format | Target User | Status |
|---|---|---|---|
| `transformers` | safetensors / bin | Researchers, AI labs, fine-tuners | **Build next** |
| GGUF / llama.cpp | GGUF | Prosumers, quantized model users, Ollama power users | Phase 2 |
| vLLM | any HF model | AI labs with GPU clusters | Phase 3 |

All three feed into the existing normalization pipeline. The platform surface
— tool routing, shell execution, file handling, streaming frontend — is
untouched regardless of which adapter is active.

---

## Phase 1 — `transformers` Adapter

### What it is

A provider adapter that loads a model from a local directory using the
HuggingFace `transformers` library and pipes its token stream into the
existing normalization pipeline via `TextIteratorStreamer`.

### Loading

```python
from transformers import AutoModelForCausalLM, AutoTokenizer
import torch

model_path = "/path/to/model"  # local directory or HF repo name

tokenizer = AutoTokenizer.from_pretrained(model_path)

model = AutoModelForCausalLM.from_pretrained(
    model_path,
    torch_dtype=torch.float32,   # float32 for CPU stability
    device_map="auto",           # auto-selects CPU / GPU / MPS
)
```

`Auto` classes read `config.json` and instantiate the correct architecture
automatically. No model-family-specific code required.

### Streaming

```python
from transformers import TextIteratorStreamer
from threading import Thread

streamer = TextIteratorStreamer(tokenizer, skip_special_tokens=False)

inputs = tokenizer.apply_chat_template(
    messages,
    return_tensors="pt",
    add_generation_prompt=True,
)

thread = Thread(target=model.generate, kwargs={
    "input_ids": inputs,
    "streamer": streamer,
    "max_new_tokens": 512,
})
thread.start()

for token in streamer:
    yield token  # feed directly into normalization pipeline
```

`skip_special_tokens=False` is important — special tokens (`<|im_start|>`,
`<tool_call>`, `</s>` etc.) are exactly what the normalization layer needs
to detect tool call boundaries.

### Integration point

`TextIteratorStreamer` sits in the same position as the existing Ollama or
OpenAI streaming client. The `for token in streamer` loop becomes the new
provider adapter. Everything downstream is unchanged.

### Key engineering challenges

**Tool call boundary detection**
Unlike provider APIs which emit pre-parsed `type: "call_arguments"` deltas,
raw token streams require the normalization layer to detect when it has
entered and exited a tool call block. Buffering logic needed. The existing
regex healing in `_map_chunk_to_event` is the foundation to build from.

**Chat template variance**
Every model family formats the prompt differently. `apply_chat_template`
handles this automatically using the template stored in
`tokenizer_config.json`. No manual prompt formatting required per model.

**CPU stability**
Use `torch.float32` on CPU — `float16` can produce NaN values without a GPU.
For machines with a GPU, `float16` or `bfloat16` halves memory usage.

### Deliverables

- [ ] `TransformersProviderAdapter` class implementing the existing provider
      interface
- [ ] Token stream → normalization pipeline bridge
- [ ] Tool call boundary detection and buffering
- [ ] Chat template application
- [ ] Config: accept local path or HF repo name interchangeably
- [ ] Document minimum hardware requirements per model size class

---

## Phase 2 — GGUF / llama.cpp Adapter

### What it is

An adapter for quantized models in GGUF format — the format used by llama.cpp
and Ollama under the hood. Targets the large market of users running
compressed models on consumer hardware.

### Why it matters

Quantization makes large models accessible on normal hardware:

| Model size | float16 VRAM | 4-bit GGUF VRAM |
|---|---|---|
| 7B | ~14 GB | ~4 GB |
| 13B | ~26 GB | ~8 GB |
| 70B | ~140 GB | ~40 GB |

A 70B model in 4-bit GGUF runs on a Mac Studio with 64GB unified memory.
A 7B model runs on a gaming laptop.

### Loading

```python
from llama_cpp import Llama

model = Llama(
    model_path="/path/to/model.gguf",
    n_gpu_layers=-1,   # offload all layers to GPU if available
    verbose=False,
)

for token in model("prompt here", stream=True):
    yield token["choices"][0]["text"]
```

### Deliverables

- [ ] `GGUFProviderAdapter` class
- [ ] Layer offload configuration (CPU only / partial GPU / full GPU)
- [ ] Same tool call boundary detection as Phase 1
- [ ] Document quantization format recommendations (GGUF Q4_K_M is the
      standard sweet spot)

---

## Phase 3 — vLLM Adapter

### What it is

An adapter for AI lab customers who have GPU clusters and need production-grade
throughput — tensor parallelism, continuous batching, PagedAttention KV cache.

### Key insight

vLLM in server mode exposes an OpenAI-compatible API:

```bash
python -m vllm.entrypoints.openai.api_server \
    --model meta-llama/Llama-3-70b \
    --tensor-parallel-size 8
```

This means the existing OpenAI-compatible provider adapter may already cover
this case with zero new code. Verify compatibility before building anything.

### Deliverables

- [ ] Audit existing OpenAI adapter against vLLM endpoint behaviour
- [ ] Document vLLM deployment configuration for platform users
- [ ] If gaps exist, implement `vLLMProviderAdapter`
- [ ] Tensor parallel size and GPU memory utilization configuration

---

## Token Pattern Profiling

Before building tool call detection, profile real token streams to understand
what the normalization layer needs to handle.

### Approach

Use small quantized models locally — same tokenizer conventions and chat
templates as their full-size counterparts, but run on any hardware:

```
Qwen2.5-1.5B-Instruct   — same family as Qwen3-80B you ran via TogetherAI
Llama-3.2-1B            — Meta family baseline
SmolLM2                 — extremely lightweight, good for rapid iteration
```

### What to capture

```python
for token in streamer:
    print(repr(token))  # repr reveals special tokens, whitespace, control chars
```

Specifically observe:

- How the model signals entry into a tool call block
- Whether tool call JSON arrives in one burst or character by character
- How the model signals exit from tool call back to natural language
- Special token conventions (`<tool_call>`, `<|python_tag|>`, `[TOOL_CALLS]`
  etc — these vary significantly across families)
- Behaviour on malformed / partial tool calls

Document findings per model family. This becomes the detection rule set for
the normalization layer.

---

## The Full Platform Story

Once all three phases are complete the platform covers every deployment scenario:

```
Got freshly trained weights?         →  transformers adapter
Got a quantized GGUF model?          →  GGUF adapter
Got a GPU cluster?                   →  vLLM adapter
Want a hosted provider?              →  already works (Hyperbolic, TogetherAI, etc)
Running Ollama locally?              →  already works
```

Five scenarios. One platform. **Uni5.**

Same tool routing. Same shell execution. Same multi-agent delegation. Same
streaming frontend. Same file handling. The model source becomes a
configuration detail, not an architectural decision.

That is the proposition: **From the lab to enterprise grade orchestration — instantly.**

LangChain built an abstraction layer. Project Uni5 is an orchestration platform.
The difference is everything.

---

## Immediate Next Actions

1. **Set up profiling environment** — install `transformers`, `torch`,
   `llama-cpp-python` in a local venv
2. **Download a small model** — `Qwen2.5-1.5B-Instruct` from HuggingFace
3. **Run raw token capture** — pipe `TextIteratorStreamer` output to a log
   file with `repr()` formatting, run a prompt that triggers a tool call
4. **Document token patterns** — catalogue special tokens and tool call
   boundary signals for at least two model families
5. **Design the provider adapter interface** — define the contract that
   `TransformersProviderAdapter` must satisfy to plug into the existing
   normalization pipeline
6. **Build `TransformersProviderAdapter`** — implement, test against the
   existing tool routing stack
7. **Repeat for GGUF** once Phase 1 is stable