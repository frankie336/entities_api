from entities_api.orchestration.instructions.definitions import \
    LEVEL_3_WEB_USE_INSTRUCTIONS

L2_INSTRUCTIONS = [
    "TOOL_USAGE_PROTOCOL",
    "FUNCTION_CALL_FORMATTING",
    "FUNCTION_CALL_WRAPPING",
    "CODE_INTERPRETER",  # code interpreter
    "CODE_FILE_HANDLING",
]

L3_INSTRUCTIONS = [
    "L3_IDENTITY",
    "L3_PLANNING_PROTOCOL",
    "TOOL_DECISION_PROTOCOL",
    "L3_PARALLEL_EXECUTION",
    "CODE_INTERPRETER"  # code interprete
    "CODE_FILE_HANDLING",  # code interpreter
    "CITATION_PROTOCOL",
    "TOOL_USAGE_PROTOCOL",
    "FUNCTION_CALL_FORMATTING",
    "FUNCTION_CALL_WRAPPING",
    "L3_SYNTAX_ENFORCEMENT",
]


LEVEL_4_SUPERVISOR_INSTRUCTIONS = [
    "L4_SUPERVISOR_IDENTITY",  # 1. Identity: Architect & Editor-in-Chief
    "L4_TRIAGE_PROTOCOL",  # 2. Decision Logic: Research vs Chat
    "L4_PLANNING_PROTOCOL",  # 3. The Brain: Mental Models
    "L4_TOOL_ORCHESTRATION_PROTOCOL",  # 4. The How: Tool roles & standard chain
    "L4_DELEGATION_PROTOCOL",  # 5. The Instruction: Prescriptive prompting
    "L4_SCRATCHPAD_MANAGEMENT_PROTOCOL",  # 6. The Whiteboard: Governor role, worker-written state
    "L4_EXECUTION_LOOP",  # 7. The Pulse: Initialize -> Delegate -> Evaluate
    "L4_CITATION_INTEGRITY",  # 8. Zero-Tolerance: VERIFIED entry required per claim
    "L4_ANTI_STALL",  # 9. The Guardrails: No stale URLs, promote ⚠️ to ☠️
    "L4_URL_PROTOCOL",  # 10. Safety: URL hallucination check
    "L4_FINAL_SYNTHESIS_PROTOCOL",  # 11. The Output: Supervisor owns the final answer
    "TOOL_USAGE_PROTOCOL",  # 12. Base Tool Syntax
    "FUNCTION_CALL_FORMATTING",  # 13. JSON formatting rules
    "FUNCTION_CALL_WRAPPING",  # 14. XML wrapping rules
    "CITATION_PROTOCOL",  # 15. Link formatting rules
]

L4_RESEARCH_INSTRUCTIONS = [
    "L4_WORKER_IDENTITY",  # 1. You are a Transient Worker + scratchpad access overview
    "L4_WORKER_SCRATCHPAD_PROTOCOL",  # 2. Read-first orientation, dedup, gap ID, tombstone awareness [NEW]
    "TOOL_USAGE_PROTOCOL",  # 3. Syntax (Strict)
    "FUNCTION_CALL_FORMATTING",  # 4. JSON formatting rules
    "FUNCTION_CALL_WRAPPING",  # 5. XML wrapping rules
    "TOOL_STRATEGY",  # 6. Very important for web search
    # "L4_TOOL_CHEATSHEET",            # (covered by TOOL_USAGE_PROTOCOL + TOOL_STRATEGY)
    # "L4_PARALLEL_EXECUTION",         # (redundant)
    "BATCH_OPERATIONS",  # 7. Parallel batching rules
    "L4_EXECUTION_ALGORITHM",  # 8. Discovery -> Recon -> Snipe, scratchpad read as Step 0
    "L4_DEPTH_PROTOCOL",  # 9. Comparative rigor, scratchpad-aware source counting
    "RICH_MEDIA_HANDLING",  # 10. Keep images/video links (borrowed from L3)
    "L4_STOPPING_CRITERIA",  # 11. When to quit, incl. "already in scratchpad" condition
    "L4_WORKER_REPORTING_FORMAT",  # 12. Structured report for direct scratchpad appending
]
L3_WEB_USE_INSTRUCTIONS = [
    "WEB_CORE_IDENTITY",
    "STOP_RULE",
    "RICH_MEDIA_HANDLING",
    "CITATION_PROTOCOL",
    "TOOL_STRATEGY",
    "BATCH_OPERATIONS",
    "CONTEXT_MANAGEMENT",
    "ERROR_HANDLING",
    "RESEARCH_QUALITY_PROTOCOL",
    "RESEARCH_PROGRESS_TRACKING",
    "POST_EXECUTION_PROTOCOL",
]


NO_CORE_INSTRUCTIONS = ["NONE"]
