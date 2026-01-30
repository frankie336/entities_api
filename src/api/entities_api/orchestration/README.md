```
┌──────────────────────────────────────────┐
│ Orchestrator (process_conversation)     │
│  - multi-phase                          │
│  - state driven                         │
└──────────────────────────────────────────┘
                ↓
┌──────────────────────────────────────────┐
│ Stream Engine (stream)                  │
│  - streaming inference                 │
│  - cancellation                        │
│  - persistence                         │
│  - tool accumulation                   │
└──────────────────────────────────────────┘
                ↓
┌──────────────────────────────────────────┐
│ Delta Normalizer (Hyperbolic…)          │
│  - provider → canonical events         │
│  - optimistic FSM                      │
│  - tool + reasoning extraction         │
└──────────────────────────────────────────┘
                ↓
┌──────────────────────────────────────────┐
│ Provider Adapter (HyperbolicDs1)        │
│  - client instantiation only           │
└──────────────────────────────────────────┘
