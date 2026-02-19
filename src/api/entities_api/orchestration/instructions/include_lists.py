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
    "L4_SUPERVISOR_IDENTITY",  # 1. You are the Commander
    "L4_SUPERVISOR_CONSTRAINTS",  # 2. Anti-stall / No single calls
    "L4_TRIAGE_PROTOCOL",  # 3. Decision Logic
    "L4_EXECUTION_PROTOCOL",  # 4. The "Double-Tap" (Plan + Delegate)
    "L4_URL_PROTOCOL",  # 5. Anti-Hallucination
    "TOOL_USAGE_PROTOCOL",  # 6. Syntax
    "FUNCTION_CALL_FORMATTING",
    "FUNCTION_CALL_WRAPPING",
    "CITATION_PROTOCOL",  # 7. How to format links in the Final Report
    "L4_SUPERVISOR_OUTPUT_FORMAT",  # 8. "Dense synthesis" (Renamed Key)
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
    "L4_TOOL_CHEATSHEET",  # 3. Specific Tool rules (Query requirements)
    "L4_EXECUTION_ALGORITHM",  # 4. Discovery -> Recon -> Snipe
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
