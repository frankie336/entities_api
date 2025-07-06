computer = {
    "type": "function",
    "function": {
        "name": "computer",
        "description": "Simulates a personal Linux workstation with internet access. Executes a list of terminal commands in a recoverable session, streaming output.",
        "parameters": {
            "type": "object",
            "properties": {
                "commands": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Sequential Linux commands as if typed directly into the terminal.",
                }
            },
            "required": ["commands"],
        },
    },
}
