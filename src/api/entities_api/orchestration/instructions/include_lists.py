from entities_api.orchestration.instructions.definitions import \
    LEVEL_3_WEB_USE_INSTRUCTIONS

L2_INSTRUCTIONS = [
    "TOOL_USAGE_PROTOCOL",
    "FUNCTION_CALL_FORMATTING",
    "FUNCTION_CALL_WRAPPING",
    "CODE_INTERPRETER",  # code interpreter
]

L3_INSTRUCTIONS = [
    "L3_IDENTITY",
    "L3_PLANNING_PROTOCOL",
    "TOOL_DECISION_PROTOCOL",
    "L3_PARALLEL_EXECUTION",
    "CODE_INTERPRETER"  # code interprete
    "CITATION_PROTOCOL",
    "TOOL_USAGE_PROTOCOL",
    "FUNCTION_CALL_FORMATTING",
    "FUNCTION_CALL_WRAPPING",
    "L3_SYNTAX_ENFORCEMENT",
]


LEVEL_4_SUPERVISOR_INSTRUCTIONS = [
    "L4_SUPERVISOR_IDENTITY",  # 1. WHO you are (Identity)
    "L4_TRIAGE_PROTOCOL",  # 2. DECISION: Classify the user query
    "L4_URL_PROTOCOL",  # 3. SAFETY: New Anti-Hallucination & Zero-Trust URL rules
    "L4_SUPERVISOR_CONSTRAINTS",  # 4. BOUNDARIES: Anti-stall & "No Single Calls"
    "L4_EXECUTION_PROTOCOL",  # 5. ACTION: The "Double-Tap" logic
    "TOOL_USAGE_PROTOCOL",  # 6. SYSTEM: Syntax rules
    "FUNCTION_CALL_FORMATTING",  # 7. SYSTEM: No markdown backticks
    "FUNCTION_CALL_WRAPPING",  # 8. SYSTEM: <fc> tags
    "L4_OUTPUT_FORMAT",  # 9. RESULT: Synthesis requirements
]


L4_RESEARCH_INSTRUCTIONS = [
    # --- 1. System Syntax (Prioritized to prevent schema errors) ---
    "TOOL_USAGE_PROTOCOL",
    "FUNCTION_CALL_FORMATTING",
    "FUNCTION_CALL_WRAPPING",
    # --- 2. Identity & Boundaries ---
    "L4_WORKER_IDENTITY",  # Transient Worker Identity
    "L4_STOPPING_CRITERIA",  # Specific L4 stop rules (prevent loops)
    # --- 3. Operational Logic ---
    "L4_TOOL_CHEATSHEET",  # Strict tool syntax (defines 'query' requirement)
    "L4_EXECUTION_ALGORITHM",  # The Discovery -> Recon -> Snipe loop
    "L4_DEPTH_PROTOCOL",  # Rules for comparative/deep queries
    # --- 4. Advanced Handling ---
    "BATCH_OPERATIONS",  # Parallelization rules (Standard Web L3 is fine here)
    "ERROR_HANDLING",  # Recovery from 403s/Empty results
    # --- 5. Reporting ---
    "L4_OUTPUT_FORMAT",  # Contains the new "REPORTING STANDARDS" (No Chat, just facts)
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
