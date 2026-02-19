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
    "L4_SUPERVISOR_IDENTITY",  # 1. Identity: The Search Architect & Editor-in-Chief
    "L4_TRIAGE_PROTOCOL",  # 2. Decision Logic: Is this Research (Tier 1-3) or Chat (Tier 0)?
    "L4_PLANNING_PROTOCOL",  # 3. The Brain: Mental Models (Lookup vs Discovery vs Comparative) [NEW]
    "L4_DELEGATION_PROTOCOL",  # 4. The Instruction: Prescriptive Prompting for Workers [NEW]
    "L4_EXECUTION_LOOP",  # 5. The Pulse: Initialize -> Delegate -> Evaluate [NEW]
    "L4_ANTI_STALL",  # 6. The Guardrails: No guessing, one step at a time [NEW]
    "L4_URL_PROTOCOL",  # 7. Safety: Zero-tolerance URL hallucination check
    "L4_FINAL_SYNTHESIS_PROTOCOL",  # 8. The Output: Supervisor owns the final summary (Editor role) [NEW]
    "TOOL_USAGE_PROTOCOL",  # 9. Base Tool Syntax
    "FUNCTION_CALL_FORMATTING",  # 10. JSON formatting rules
    "FUNCTION_CALL_WRAPPING",  # 11. XML wrapping rules
    "CITATION_PROTOCOL",  # 12. Link formatting rules
]

# --- WORKER: The Transient Soldier ---
# REMOVED: BATCH_OPERATIONS (L4 Execution Algo covers this)
# REMOVED: ERROR_HANDLING (L4 Stopping Criteria covers this)
# ADDED: RICH_MEDIA_HANDLING (Worker needs to know how to handle images found on web)
L4_RESEARCH_INSTRUCTIONS = [
    "L4_WORKER_IDENTITY",  # 1. You are a Transient Worker
    "TOOL_USAGE_PROTOCOL",  # 2. Syntax (Strict)
    "FUNCTION_CALL_FORMATTING",
    "FUNCTION_CALL_WRAPPING",
    "TOOL_STRATEGY",  # -< --- Very important for web search
    # "L4_TOOL_CHEATSHEET",  # 3. Specific Tool rules (Query requirements)
    # "L4_PARALLEL_EXECUTION", <-- redundant
    "BATCH_OPERATIONS",
    "L4_EXECUTION_ALGORITHM",  # 4. Discovery -> Recon -> Snipe <- breaking logic
    "L4_DEPTH_PROTOCOL",  # 5. Comparative rigor
    "RICH_MEDIA_HANDLING",  # 6. Keep images/video links (borrowed from L3)
    "L4_STOPPING_CRITERIA",  # 7. When to quit
    "L4_WORKER_REPORTING_FORMAT",  # 8. "Direct Answer + Evidence" (Renamed Key)
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
