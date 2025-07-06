from typing import Optional

from main_assembly import assemble_instructions

excluded_instructions = assemble_instructions(exclude_keys=["TOOL_USAGE_PROTOCOL"])
print(excluded_instructions)
