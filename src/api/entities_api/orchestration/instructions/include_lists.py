from entities_api.orchestration.instructions.definitions import \
    LEVEL_3_WEB_USE_INSTRUCTIONS

L2_INSTRUCTIONS = [
    "TOOL_USAGE_PROTOCOL",
    "FUNCTION_CALL_FORMATTING",
    "FUNCTION_CALL_WRAPPING",
]

L3_INSTRUCTIONS = [
    "L3_IDENTITY",
    "L3_PLANNING_PROTOCOL",
    "TOOL_DECISION_PROTOCOL",
    "L3_PARALLEL_EXECUTION",
    "CITATION_PROTOCOL",
    "TOOL_USAGE_PROTOCOL",
    "FUNCTION_CALL_FORMATTING",
    "FUNCTION_CALL_WRAPPING",
    "L3_SYNTAX_ENFORCEMENT",
]


LEVEL_4_SUPERVISOR_INSTRUCTIONS = [
    "L4_SUPERVISOR_IDENTITY",  # 1. WHO you are (first)
    "L4_TRIAGE_PROTOCOL",  # 2. FIRST STEP: Classify query (decision gate)
    "L4_SUPERVISOR_CONSTRAINTS",  # 3. WHAT you cannot do (boundaries)
    "L4_EXECUTION_PROTOCOL",  # 4. HOW you must act (the Double-Tap)
    "CITATION_PROTOCOL",
    "TOOL_USAGE_PROTOCOL",  # 5. Syntax rules (before using tools)
    "FUNCTION_CALL_FORMATTING",  # 6. Formatting specifics
    "FUNCTION_CALL_WRAPPING",  # 7. Wrapping specifics
    "L4_OUTPUT_FORMAT",  # 8. Final output expectations
]


L4_RESEARCH_INSTRUCTIONS = [
    "TOOL_USAGE_PROTOCOL",
    "FUNCTION_CALL_FORMATTING",
    "FUNCTION_CALL_WRAPPING",
    "L4_WORKER_IDENTITY",  # 1. WHO you are
    "L4_STOPPING_CRITERIA",  # 2. WHEN to stop (critical early!)
    "L4_TOOL_CHEATSHEET",  # 3. WHAT tools exist (reference)
    "TOOL_STRATEGY",  # 4. HOW to choose tools
    "L4_EXECUTION_ALGORITHM",  # 5. The basic research workflow
    "CITATION_PROTOCOL",
    "L4_DEPTH_PROTOCOL",  # 6. Enhanced workflow for complex queries
    "BATCH_OPERATIONS",  # 7. Parallelization rules
    "L3_PARALLEL_EXECUTION",  # 8. Advanced batching
    "ERROR_HANDLING",  # 9. Error recovery
    "RESEARCH_PROGRESS_TRACKING",  # 10. Quality checkpoints
    "STOP_RULE",  # 11. Reinforcement of stopping logic
    "POST_EXECUTION_PROTOCOL",  # 12. Synthesis requirements
    # "TOOL_USAGE_PROTOCOL",  # 13. Syntax rules
    # "FUNCTION_CALL_FORMATTING",  # 14. Format specifics
    # "FUNCTION_CALL_WRAPPING",  # 15. Wrapper specifics
    "L4_OUTPUT_FORMAT",  # 16. Final output
]


L3_WEB_USE_INSTRUCTIONS = [
    "WEB_CORE_IDENTITY",
    "STOP_RULE",
    "WEB_RECURSIVE_MANDATE",  # NEW: Explicit loop protocol
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
