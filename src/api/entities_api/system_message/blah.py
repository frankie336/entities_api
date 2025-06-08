
from typing import Optional
from main_assembly import assemble_instructions

# Call the function while excluding specific sections

excluded_instructions = assemble_instructions(
    exclude_keys=[
        "TOOL_USAGE_PROTOCOL",

    ]
)


print(excluded_instructions)  # Prints instructions without excluded sections
