from typing import Dict, List, Optional

SYSTEM_PROMPT = """You are an expert research assistant.\n"
    "Answer the user question using ONLY the provided excerpts.\n"
    "After each claim, cite the supporting file like (citation: <file_id>).\n"
    "Do NOT fabricate information.\n"""

DEFAULT_INSTRUCTIONS = {
    "system_prompt": SYSTEM_PROMPT,
}


def assemble_instructions(
    include_keys: Optional[List[str]] = None,
    exclude_keys: Optional[List[str]] = None,
    instruction_set: Optional[Dict[str, str]] = None,
) -> str:
    """
    Assembles the final instruction string from the structured dictionary.

    Args:
        include_keys: A list of keys to explicitly include. If None, all keys
                      (not in exclude_keys) are included.
        exclude_keys: A list of keys to explicitly exclude.
        instruction_set: The dictionary containing the instruction parts.

    Returns:
        A single string containing the combined instructions.
    """
    if instruction_set is None:
        instruction_set = DEFAULT_INSTRUCTIONS
    if include_keys and exclude_keys:
        raise ValueError("Cannot specify both include_keys and exclude_keys")

    final_instructions = []
    if include_keys:
        for key in include_keys:
            if key not in instruction_set:
                print(f"Warning: Requested instruction key '{key}' not found.")
            else:
                final_instructions.append(instruction_set[key])
    else:
        exclude_set = set(exclude_keys or [])
        for key, text in instruction_set.items():
            if key not in exclude_set:
                final_instructions.append(text)

    return "\n\n".join(final_instructions)
