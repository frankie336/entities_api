

```

USER QUERY
   │
   ▼
┌───────────────────────┐
│  ORCHESTRATOR (L3)    │◄──────────────────────────────┐
└──────────┬────────────┘                               │
           │                                            │
           ▼                                            │
┌───────────────────────┐                               │
│  LLM "BRAIN"          │                               │
│  (System Prompt)      │                               │
└────┬───────────┬──────┘                               │
     │           │                                      │
     │ (Decides) │ (Reads/Writes)                       │
     │           ▼                                      │
     │     ┌────────────┐                               │
     │     │ SCRATCHPAD │  <-- [Redis Cache]            │
     │     │ (The Plan) │  "1. Find Revenue..."         │
     │     │ (Notes)    │  "2. Compare 2024..."         │
     │     └────────────┘                               │
     │                                                  │
     ▼                                                  │
┌──────────────┐      ┌─────────────────┐               │
│ WEB TOOLS    │      │ COMPUTER TOOLS  │               │
│ (Search/Read)│      │ (Python/Shell)  │               │
└────┬─────────┘      └───────┬─────────┘               │
     │                        │                         │
     ▼                        ▼                         │
  INTERNET              DATA PROCESSING ────────────────┘

```


### Visual Data Flow


```

[Database / Redis]
      |
      | (Load History via thread_id)
      v
+---------------------+
|  SUPERVISOR (Main)  | <--- "I need to find NVIDIA revenue."
+---------------------+
      |
      | (Delegate: "Find NVIDIA Rev") -> NO thread_id context passed
      v
   +---------------------------+
   |  WORKER (Ephemeral Loop)  |
   |  - System Prompt          |
   |  - Task: "Find Rev"       | <--- Starts Fresh!
   |  - Web Search Tools       |
   +---------------------------+
      |
      | (Return Text: "$60B")
      v
+---------------------+
|  SUPERVISOR (Main)  | <--- "Ah, the answer is $60B."
+---------------------+
      |
      | (Save to Scratchpad via thread_id)
      v
[Database / Redis]


```