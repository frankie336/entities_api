code_interpreter = {
    "type": "function",
    "function": {
        "name": "code_interpreter",
        "description": "Executes Python code in a sandbox environment and returns JSON output.",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python code to execute"}
            },
            "required": ["code"],
        },
    },
}
